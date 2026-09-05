import os
import json
import hmac
import re
import threading
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from fastapi import FastAPI, Request, Response, HTTPException, Form, File, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles as StarletteStaticFiles
import uvicorn
from dotenv import load_dotenv

import core
from db import (
    QueryResult,
    DatabaseConfigError,
    DatabaseUnavailableError,
    TursoQuotaError,
    _is_transient_db_error,
    activate_local_sqlite,
    build_fts_match_query,
    db_backend_label,
    default_article_images_dir,
    default_local_database_path,
    ensure_schema,
    existing_news_links,
    fts_available,
    get_db,
    import_turso_into_sqlite,
    index_news_by_link,
    invalidate_sentiment_cache,
    log_runtime_config_checklist,
    reset_db_client,
    restore_sqlite_payload,
    sqlite_table_counts,
    sync_news_fts,
    RESTORE_MAX_BYTES,
)
from educational_guides import (
    EDUCATIONAL_GUIDES,
    GUIDE_LINK_PREFIX,
    ensure_educational_guides,
    find_guide_noticia_id,
    get_guide_by_slug,
    guides_for_tag,
)
from newsletter_service import (
    CONTACT_BODY_MAX,
    CONTACT_SUBJECT_MAX,
    enqueue_urgency_alert,
    is_send_configured,
    send_contact_message,
    send_daily_digest,
    send_urgency_alert,
    send_weekly_digest,
)
from monetization import get_monetization_config, get_contextual_affiliate
from article_enrichment import (
    build_article_enrichment,
    clean_source_url,
    infer_source_name,
    resolve_referencias_internas,
    source_homepage,
)
from i18n import (
    COOKIE_MAX_AGE,
    COOKIE_NAME,
    SITE_TOPIC_KEYWORDS,
    SUPPORTED_LANGS,
    absolute_url,
    apply_lang_to_relative_url,
    build_hreflang_map,
    build_i18n_context,
    localized_path,
    normalize_lang,
    resolve_lang,
    translate as i18n_translate,
)
import community_auth as community
from community_auth import CONSENT_COOKIE, SESSION_USER_KEY
import columnists

_ = load_dotenv()

# Limiar alinhado ao sitemap / purge_thin_news — artigos abaixo recebem noindex.
# Proxy conservador de ~800 palavras (ver core.MIN_ARTICLE_WORDS / MIN_ARTICLE_CHARS).
THIN_RESUMO_CHARS = core.MIN_ARTICLE_CHARS

FEED_BATCH = 8
FEATURED_COUNT = 4
# Chamadas de texto ("Leia também") logo abaixo da manchete principal.
HEADLINE_TRAIL = 3
HOME_TOP_COUNT = FEATURED_COUNT + HEADLINE_TRAIL
HOME_HEADLINE_MAX = 5
RSS_FEED_LIMIT = 50


def _content_security_policy() -> str:
    """CSP compatível com AdSense, SWG, Google Fonts, Chart.js CDN e scripts inline do portal."""
    directives = [
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'self'",
        (
            "script-src 'self' 'unsafe-inline' "
            "https://pagead2.googlesyndication.com https://cdn.jsdelivr.net "
            "https://www.googletagmanager.com https://www.google-analytics.com "
            "https://accounts.google.com https://news.google.com"
        ),
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: https: blob:",
        (
            "connect-src 'self' https://economia.awesomeapi.com.br "
            "https://cdn.jsdelivr.net "
            "https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net "
            "https://www.google.com https://ep1.adtrafficquality.google "
            "https://accounts.google.com https://oauth2.googleapis.com "
            "https://news.google.com"
        ),
        (
            # about: (scheme) cobre iframes about:blank do AdSense; about:blank não é source CSP válido
            "frame-src about: https://googleads.g.doubleclick.net "
            "https://tpc.googlesyndication.com https://www.google.com "
            "https://accounts.google.com https://news.google.com"
        ),
    ]
    return "; ".join(directives)


class CachedStaticFiles(StarletteStaticFiles):
    """StaticFiles com Cache-Control longo para assets versionados."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=604800, stale-while-revalidate=86400"
        return response


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    log_runtime_config_checklist()

    def _boot():
        try:
            print(f"   [db] backend={db_backend_label()}", flush=True)
            client = get_db()
            ensure_schema(client)
            n = ensure_educational_guides(client)
            if n:
                print(f"Guias educativos sincronizados: {n}")
                _invalidate_home_cache()
            core.backfill_home_priority(client)
        except Exception as exc:
            print(f"Aviso: schema/DB no startup: {exc}")
        try:
            core.warmup_market_caches()
            _load_home_listing(None, 0, HOME_TOP_COUNT + FEED_BATCH, None)
        except Exception as exc:
            print(f"Aviso: warmup inicial falhou: {exc}")

    # Background: não bloqueia o worker no reload (Turso remoto pode demorar).
    threading.Thread(target=_boot, daemon=True, name="startup-boot").start()
    yield


_cloud_host = core.is_cloud_host()
app = FastAPI(
    lifespan=_lifespan,
    docs_url=None if _cloud_host else "/docs",
    redoc_url=None if _cloud_host else "/redoc",
    openapi_url=None if _cloud_host else "/openapi.json",
)


@app.exception_handler(DatabaseConfigError)
async def _database_config_error_handler(_request: Request, exc: DatabaseConfigError):
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
            "hint": (
                "Na Railway: USE_LOCAL_DB=true com volume (news.db). "
                "TURSO_* so e necessario para /api/import-from-turso."
            ),
        },
    )


@app.exception_handler(DatabaseUnavailableError)
async def _database_unavailable_handler(request: Request, _exc: DatabaseUnavailableError):
    """Turso instável: 503 em vez de stack 500 (home, artigo, sitemap, APIs)."""
    path = request.url.path or ""
    wants_json = path.startswith("/api/") or "application/json" in (
        request.headers.get("accept") or ""
    )
    headers = {"Retry-After": "20"}
    if wants_json:
        return JSONResponse(
            status_code=503,
            content={"detail": "Banco temporariamente indisponível. Tente de novo em instantes."},
            headers=headers,
        )
    response = _render(request, "db_unavailable.html", {}, status_code=503)
    response.headers["Retry-After"] = "20"
    return response

# Sessão de usuário da comunidade (separada do ROBO_TOKEN).
_https_only_sessions = (os.getenv("SESSION_HTTPS_ONLY", "true").strip().lower() not in ("0", "false", "no"))
app.add_middleware(
    SessionMiddleware,
    secret_key=community.session_secret(),
    session_cookie="fn_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=_https_only_sessions
    and (
        core.is_cloud_host()
        or os.getenv("FORCE_SECURE_COOKIES", "") == "1"
    ),
)

ARTICLE_IMAGES_DIR = default_article_images_dir()
os.environ["ARTICLE_IMAGES_DIR"] = ARTICLE_IMAGES_DIR
os.makedirs(ARTICLE_IMAGES_DIR, exist_ok=True)
os.makedirs("static/images/articles", exist_ok=True)
AVATAR_UPLOAD_DIR = str(community.avatar_upload_dir())
os.environ["AVATAR_DIR"] = AVATAR_UPLOAD_DIR
community.ensure_default_avatar()

if os.path.exists("static"):
    app.mount("/static", CachedStaticFiles(directory="static"), name="static")
if os.path.isdir(ARTICLE_IMAGES_DIR):
    app.mount("/media/articles", CachedStaticFiles(directory=ARTICLE_IMAGES_DIR), name="article_images")
if os.path.isdir(AVATAR_UPLOAD_DIR):
    # Uploads de perfil no volume Railway (ou static/avatars local).
    app.mount("/media/avatars", CachedStaticFiles(directory=AVATAR_UPLOAD_DIR), name="user_avatars")
templates = Jinja2Templates(directory="templates")


def _current_user(request: Request):
    uid = request.session.get(SESSION_USER_KEY)
    if not uid:
        return None
    try:
        user = community.find_user_by_id(get_db(), int(uid))
        return columnists.enrich_user_role(get_db(), user)
    except Exception:
        return None


def _require_login(request: Request, next_path: str = "/"):
    user = _current_user(request)
    if not user:
        raise HTTPException(
            status_code=303,
            headers={"Location": f"/login?next={next_path}"},
        )
    if not user.get("email_verified", True):
        return RedirectResponse("/verificar-email", status_code=303)
    return user


def _require_columnist(request: Request):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login?next=/colunista", status_code=303)
    if not columnists.is_columnist_user(user):
        return RedirectResponse("/colunista/candidatar", status_code=303)
    return user


def _require_admin_user(request: Request):
    user = _current_user(request)
    if not user or not columnists.is_admin_user(user):
        raise HTTPException(status_code=403, detail="Acesso restrito.")
    return user


def _extract_admin_token(request: Request, token: str | None = None) -> str:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    header = request.headers.get("x-admin-token") or request.headers.get("x-robo-token") or ""
    if header.strip():
        return header.strip()
    return (token or request.query_params.get("token") or "").strip()


def require_admin_or_robo(request: Request, token: str | None = None) -> None:
    """Cron/admin API: ADMIN_TOKEN ou ROBO_TOKEN (Bearer / header / query)."""
    expected_admin = columnists.get_admin_token()
    expected_robo = get_robo_token()
    provided = _extract_admin_token(request, token)
    if not expected_admin and not expected_robo:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN/ROBO_TOKEN nao configurado")
    ok = False
    if expected_admin and columnists.tokens_match(provided, expected_admin):
        ok = True
    if expected_robo and columnists.tokens_match(provided, expected_robo):
        ok = True
    if not ok:
        raise HTTPException(status_code=401, detail="Nao autorizado")


def _and_published(sql_has_where: bool) -> str:
    joiner = " AND " if sql_has_where else " WHERE "
    return joiner + columnists.PUBLISHED_SQL


def _safe_next_url(raw: str | None, default: str = "/") -> str:
    value = (raw or default).strip() or default
    if not value.startswith("/") or value.startswith("//"):
        return default
    if value.startswith("/idioma"):
        return default
    return value


def _lang_cookie_secure() -> bool:
    return _https_only_sessions and (
        core.is_cloud_host() or os.getenv("FORCE_SECURE_COOKIES", "") == "1"
    )


def _set_lang_cookie(response: Response, lang: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        lang,
        max_age=COOKIE_MAX_AGE,
        samesite="lax",
        httponly=False,
        path="/",
        secure=_lang_cookie_secure(),
    )


def _client_ip(request: Request) -> str | None:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client:
        return request.client.host
    return None


def _request_headers_map(request: Request) -> dict[str, str]:
    return {k.lower(): v for k, v in request.headers.items()}


@app.middleware("http")
async def security_and_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Content-Security-Policy", _content_security_policy())
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    path = request.url.path or ""
    if path.startswith("/media/default/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=604800, stale-while-revalidate=86400"
    return response


CATEGORIAS = core.VALID_TAGS


def _render(request: Request, name: str, context: dict[str, Any] | None = None, *, status_code: int = 200):
    """Renderiza template com i18n e persiste cookie de idioma quando ?lang= estiver presente."""
    ctx = {
        "request": request,
        **build_i18n_context(request),
        "current_user": _current_user(request),
        "google_oauth_enabled": community.google_oauth_configured(),
    }
    if context:
        ctx.update(context)
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context=ctx,
        status_code=status_code,
    )
    if request.query_params.get("lang"):
        _set_lang_cookie(response, resolve_lang(request))
    return response


@app.get("/idioma/{code}")
def set_idioma(request: Request, code: str, next: str | None = None):
    """Grava o cookie de idioma e redireciona (PT limpo; EN/JA com ?lang=)."""
    lang = normalize_lang(code)
    dest = apply_lang_to_relative_url(_safe_next_url(next, "/"), lang)
    response = RedirectResponse(url=dest, status_code=303)
    _set_lang_cookie(response, lang)
    return response


# Cache curto da listagem da home (evita round-trips repetidos no Turso).
_HOME_CACHE: dict[str, tuple[float, dict[str, object]]] = {}
_HOME_CACHE_LOCK = threading.Lock()
_HOME_CACHE_TTL = float(os.getenv("HOME_CACHE_TTL", "20"))

DEFAULT_CATEGORY_IMAGES = {
    "Cripto": {"slug": "cripto", "label": "Cripto", "from": "#0b1220", "to": "#14532d", "accent": "#4ade80", "icon": "₿"},
    "Economia": {"slug": "economia", "label": "Economia", "from": "#0f172a", "to": "#0e7490", "accent": "#67e8f9", "icon": "∑"},
    "Dólar": {"slug": "dolar", "label": "Dólar", "from": "#052e16", "to": "#166534", "accent": "#86efac", "icon": "$"},
    "Ações": {"slug": "acoes", "label": "Ações", "from": "#172554", "to": "#1d4ed8", "accent": "#93c5fd", "icon": "↗"},
    "Juros": {"slug": "juros", "label": "Juros", "from": "#1c1917", "to": "#9a3412", "accent": "#fdba74", "icon": "%"},
    "Inflação": {"slug": "inflacao", "label": "Inflação", "from": "#450a0a", "to": "#b91c1c", "accent": "#fca5a5", "icon": "▲"},
    "Imóveis": {"slug": "imoveis", "label": "Imóveis", "from": "#0c4a6e", "to": "#0369a1", "accent": "#7dd3fc", "icon": "⌂"},
    "Fintech": {"slug": "fintech", "label": "Fintech", "from": "#2e1065", "to": "#7c3aed", "accent": "#d8b4fe", "icon": "⚡"},
    "Commodities": {"slug": "commodities", "label": "Commodities", "from": "#422006", "to": "#a16207", "accent": "#fde68a", "icon": "◆"},
    "Política Econômica": {"slug": "politica-economica", "label": "Política", "from": "#1e1b4b", "to": "#4338ca", "accent": "#a5b4fc", "icon": "⚖"},
}
DEFAULT_IMAGE_BY_SLUG = {item["slug"]: item for item in DEFAULT_CATEGORY_IMAGES.values()}


def category_image_url(tag: object) -> str:
    item = DEFAULT_CATEGORY_IMAGES.get(str(tag), DEFAULT_CATEGORY_IMAGES["Economia"])
    return f"/media/default/{item['slug']}.svg?v=3"


def article_cover_url(imagem_url: object, tag: object) -> str:
    """Capa do artigo, ou SVG padrão da categoria se a URL estiver vazia ou o arquivo não existir."""
    url = str(imagem_url).strip() if imagem_url is not None else ""
    if not url:
        return category_image_url(tag)
    # URLs remotas externas: manter; o onerror do cliente cobre falha de carga.
    if url.startswith(("http://", "https://")) and "/media/articles/" not in url:
        return url
    if core._media_file_exists(url):
        return url
    return category_image_url(tag)


templates.env.globals["category_image"] = category_image_url
templates.env.globals["article_cover"] = article_cover_url

SITE_ORIGIN = os.getenv("SITE_ORIGIN", "https://financas-news.net.br").rstrip("/")


def _to_iso8601(value: object) -> str | None:
    """Converte datas do portal (dd/mm/YYYY HH:MM) para ISO-8601 (SEO/schema)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text.replace(" ", "T", 1) if " " in text and "T" not in text else text
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return None


def _guide_slug_from_link(link: object) -> str | None:
    if not link:
        return None
    text = str(link).strip()
    if text.startswith(GUIDE_LINK_PREFIX):
        slug = text[len(GUIDE_LINK_PREFIX) :].strip("/")
        return slug or None
    return None


def _article_has_translation(noticia: tuple | list, lang: str) -> bool:
    if lang == "en":
        return bool(len(noticia) > 15 and noticia[15])
    if lang == "ja":
        return bool(len(noticia) > 17 and noticia[17])
    return True


def _apply_article_locale(noticia: tuple | list, lang: str) -> list[Any]:
    """Substitui título/resumo pelas traduções quando existirem (mínimo viável i18n)."""
    row = list(noticia)
    if lang == "en" and len(row) > 16 and row[15]:
        row[1] = row[15]
        if row[16]:
            row[2] = row[16]
    elif lang == "ja" and len(row) > 18 and row[17]:
        row[1] = row[17]
        if row[18]:
            row[2] = row[18]
    return row


def _internal_refs_from_market(dados_mercado: dict[str, Any]) -> list[dict[str, Any]]:
    """Referências internas resolvidas (com noticia_id) para o bloco destacado no artigo."""
    refs: list[dict[str, Any]] = []
    seen: set[int] = set()
    for ref in dados_mercado.get("referencias_internas") or []:
        if not isinstance(ref, dict):
            continue
        nid = ref.get("noticia_id")
        try:
            nid_int = int(nid) if nid is not None else 0
        except (TypeError, ValueError):
            continue
        if not nid_int or nid_int in seen:
            continue
        seen.add(nid_int)
        titulo = (ref.get("titulo") or ref.get("trecho") or f"Notícia #{nid_int}").strip()
        trecho = (ref.get("trecho") or "").strip()
        refs.append({"id": nid_int, "titulo": titulo[:120], "trecho": trecho[:180]})
        if len(refs) >= 6:
            break
    return refs


# ==========================================
# ROTAS DE PÁGINAS (FRONTEND) - ATUALIZADAS PARA FASTAPI MODERNO
# ==========================================

NEWS_SELECT = """
    SELECT id, titulo, resumo, impacto, link, tag, sentimento,
           COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao,
           fonte, dados_mercado, contexto_editorial, imagem_url,
           conteudo_extra, updated_at, versao_analise,
           titulo_en, resumo_en, titulo_ja, resumo_ja
    FROM news
"""

# Fallback se o host ainda não aplicou ALTER das colunas de tradução.
NEWS_SELECT_LEGACY = """
    SELECT id, titulo, resumo, impacto, link, tag, sentimento,
           COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao,
           fonte, dados_mercado, contexto_editorial, imagem_url,
           conteudo_extra, updated_at, versao_analise,
           NULL AS titulo_en, NULL AS resumo_en, NULL AS titulo_ja, NULL AS resumo_ja
    FROM news
"""


def _fetch_news_by_id(client, noticia_id: int) -> QueryResult:
    """Busca notícia com colunas i18n; cai para SELECT legado se o schema estiver atrasado."""
    # Não chama ensure_schema aqui: no hot path isso espera o lock do boot/startup
    # e pode estourar timeout em /noticia enquanto o Turso migra.
    try:
        return client.execute(NEWS_SELECT + " WHERE id = ?", [noticia_id])
    except DatabaseUnavailableError:
        raise
    except Exception as exc:
        # KeyError/timeout é instabilidade Turso — não é schema atrasado.
        # O fallback LEGACY dobrava o retry e ainda caía em 500.
        if _is_transient_db_error(exc):
            raise
        return client.execute(NEWS_SELECT_LEGACY + " WHERE id = ?", [noticia_id])


# Listagem da home: mantém os mesmos índices das templates, sem puxar blobs pesados.
NEWS_LIST_SELECT = """
    SELECT id, titulo, resumo, impacto, link, tag, sentimento,
           COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao,
           fonte, NULL AS dados_mercado, NULL AS contexto_editorial, imagem_url,
           NULL AS conteudo_extra, updated_at, versao_analise,
           COALESCE(home_priority, 0) AS home_priority
    FROM news
"""

# JOIN com news_fts exige prefixo: titulo/resumo existem nas duas tabelas.
FTS_NEWS_LIST_SELECT = """
    SELECT news.id, news.titulo, news.resumo, news.impacto, news.link, news.tag, news.sentimento,
           COALESCE(NULLIF(news.published_at, ''), news.created_at) AS data_publicacao,
           news.fonte, NULL AS dados_mercado, NULL AS contexto_editorial, news.imagem_url,
           NULL AS conteudo_extra, news.updated_at, news.versao_analise,
           COALESCE(news.home_priority, 0) AS home_priority
    FROM news
"""


def _invalidate_home_cache() -> None:
    with _HOME_CACHE_LOCK:
        _HOME_CACHE.clear()


def _home_cache_key(categoria: str | None, offset: int, limit: int, q: str | None) -> str:
    return f"{categoria or ''}|{offset}|{limit}|{(q or '').strip().lower()}"


def _home_cache_stale(cache_key: str) -> dict[str, object] | None:
    """Última listagem conhecida (mesmo expirada) para não 500ar a home."""
    with _HOME_CACHE_LOCK:
        cached = _HOME_CACHE.get(cache_key)
        if cached:
            payload = dict(cached[1])
            payload["stale"] = True
            return payload
        for key, (_expires, payload) in _HOME_CACHE.items():
            if key.endswith("||") or "|0|" in key:
                stale = dict(payload)
                stale["stale"] = True
                return stale
    return None


def _execute_fts_listing(
    client,
    fts_q: str,
    categoria: str | None,
    fetch_limit: int,
    offset: int,
) -> QueryResult:
    """Busca FTS com ranking bm25 (título pesa mais que resumo). Fallback sem bm25."""
    params: list[Any] = [fts_q]
    where = " JOIN news_fts ON news_fts.rowid = news.id WHERE news_fts MATCH ?"
    if categoria:
        where += " AND news.tag = ?"
        params.append(categoria)
    where += (
        " AND (news.moderation_status IS NULL OR news.moderation_status = ''"
        " OR news.moderation_status = 'published')"
    )
    params.extend([fetch_limit, offset])
    ranked_sql = (
        FTS_NEWS_LIST_SELECT
        + where
        + " ORDER BY bm25(news_fts, 10.0, 2.5), news.id DESC LIMIT ? OFFSET ?"
    )
    plain_sql = FTS_NEWS_LIST_SELECT + where + " ORDER BY news.id DESC LIMIT ? OFFSET ?"
    try:
        return client.execute(ranked_sql, params)
    except Exception:
        return client.execute(plain_sql, params)


def _load_home_listing(
    categoria: str | None,
    offset: int,
    limit: int,
    q: str | None,
    *,
    include_suggestions: bool = True,
) -> dict[str, object]:
    offset = max(0, offset)
    limit = max(1, min(limit, 40))
    cache_key = _home_cache_key(categoria, offset, limit, q)
    now = time.time()
    with _HOME_CACHE_LOCK:
        cached = _HOME_CACHE.get(cache_key)
        if cached and now < cached[0]:
            return cached[1]

    client = get_db()
    # Busca limit+1 para saber has_more sem COUNT(*) extra.
    fetch_limit = limit + 1
    q_clean = (q or "").strip() or None
    result: QueryResult | None = None

    try:
        if q_clean:
            fts_q = build_fts_match_query(q_clean) if fts_available() else None
            if fts_q:
                try:
                    result = _execute_fts_listing(client, fts_q, categoria, fetch_limit, offset)
                except Exception:
                    result = None

            if result is None:
                # Fallback: tokens AND em título/resumo (mais seletivo que um único LIKE).
                tokens = [t for t in re.findall(r"[0-9A-Za-zÀ-ÿ]{2,}", q_clean, flags=re.UNICODE)][:5]
                if not tokens:
                    tokens = [q_clean]
                where_parts: list[str] = []
                params: list[Any] = []
                for token in tokens:
                    where_parts.append("(titulo LIKE ? OR resumo LIKE ?)")
                    like = f"%{token}%"
                    params.extend([like, like])
                where_sql = " AND ".join(where_parts)
                if categoria:
                    where_sql = f"({where_sql}) AND tag = ?"
                    params.append(categoria)
                params.extend([fetch_limit, offset])
                result = client.execute(
                    NEWS_LIST_SELECT + f" WHERE {where_sql}" + _and_published(True) + " ORDER BY id DESC LIMIT ? OFFSET ?",
                    params,
                )
        elif categoria:
            result = client.execute(
                NEWS_LIST_SELECT + " WHERE tag = ?" + _and_published(True) + " ORDER BY id DESC LIMIT ? OFFSET ?",
                [categoria, fetch_limit, offset],
            )
        else:
            result = client.execute(
                NEWS_LIST_SELECT + " WHERE " + columnists.PUBLISHED_SQL + " ORDER BY id DESC LIMIT ? OFFSET ?",
                [fetch_limit, offset],
            )
    except Exception as exc:
        stale = _home_cache_stale(cache_key)
        if stale:
            print(
                f"   [home] Turso falhou ({type(exc).__name__}); servindo cache antigo.",
                flush=True,
            )
            return stale
        raise

    rows = list(result.rows) if result else []
    has_more = len(rows) > limit
    news = rows[:limit]

    suggested_news: list[Any] = []
    if include_suggestions and not news and (categoria or q_clean):
        try:
            if categoria:
                suggested_result = client.execute(
                    NEWS_LIST_SELECT + " WHERE tag != ? ORDER BY id DESC LIMIT ?",
                    [categoria, FEED_BATCH],
                )
            else:
                suggested_result = client.execute(
                    NEWS_LIST_SELECT + " ORDER BY id DESC LIMIT ?",
                    [FEED_BATCH],
                )
            suggested_news = suggested_result.rows
        except Exception:
            suggested_news = []

    next_offset = offset + len(news)
    total_news = next_offset + (1 if has_more else 0)

    payload: dict[str, object] = {
        "news": news,
        "suggested_news": suggested_news,
        "total_news": total_news,
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset,
        "has_more": has_more,
    }
    with _HOME_CACHE_LOCK:
        _HOME_CACHE[cache_key] = (now + _HOME_CACHE_TTL, payload)
    return payload


def _load_headline_news(categoria: str | None) -> list[Any]:
    """Manchetes importantes (urgência Alta) para o hero da home."""
    client = get_db()
    try:
        columnists.expire_boosts(client)
    except Exception:
        pass
    where = "WHERE COALESCE(home_priority, 0) >= ?" + _and_published(True)
    params: list[Any] = [core.HOME_HEADLINE_MIN_PRIORITY]
    if categoria:
        where += " AND tag = ?"
        params.append(categoria)
    params.append(HOME_HEADLINE_MAX)
    try:
        result = client.execute(
            NEWS_LIST_SELECT + where + " ORDER BY home_priority DESC, id DESC LIMIT ?",
            params,
        )
        return list(result.rows) if result else []
    except Exception as exc:
        print(f"   [home] manchetes indisponíveis ({type(exc).__name__})", flush=True)
        return []


def _split_home_editorial(
    news: list[Any],
    headline_news: list[Any],
) -> dict[str, list[Any]]:
    """Separa manchetes, cards laterais, trilha e feed sem duplicar IDs."""
    headline_ids = {row[0] for row in headline_news}
    top_pool = [row for row in news[:HOME_TOP_COUNT] if row[0] not in headline_ids]
    feed_pool = [row for row in news[HOME_TOP_COUNT:] if row[0] not in headline_ids]

    headlines = list(headline_news)
    if not headlines and top_pool:
        headlines = [top_pool[0]]
        top_pool = top_pool[1:]

    secondary = top_pool[:3]
    trilha = top_pool[3 : 3 + HEADLINE_TRAIL]
    feed_news = top_pool[3 + HEADLINE_TRAIL :] + feed_pool

    return {
        "headline_news": headlines,
        "secondary_news": secondary,
        "trilha_news": trilha,
        "feed_news": feed_news,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request, categoria: str | None = None, q: str | None = None):
    # Sem busca: 4 destaques + 3 chamadas + 8 no feed. Com busca: só o feed de 8.
    initial_limit = FEED_BATCH if q else HOME_TOP_COUNT + FEED_BATCH
    listing = _load_home_listing(categoria, 0, initial_limit, q)
    sparklines = core.fetch_sparkline_data(blocking=False)

    editorial: dict[str, list[Any]] = {
        "headline_news": [],
        "secondary_news": [],
        "trilha_news": [],
        "feed_news": list(listing["news"]) if q else [],
    }
    if listing["news"] and not q:
        headlines = _load_headline_news(categoria)
        editorial = _split_home_editorial(list(listing["news"]), headlines)

    # Categorias vazias: não indexar. Busca/paginação já marcam noindex via i18n.
    empty_category = bool(categoria and not q and not listing["news"])
    render_ctx: dict[str, Any] = {
        "news": listing["news"],
        "headline_news": editorial["headline_news"],
        "secondary_news": editorial["secondary_news"],
        "trilha_news": editorial["trilha_news"],
        "feed_news": editorial["feed_news"] if not q else listing["news"],
        "categoria_ativa": categoria,
        "category_guides": guides_for_tag(categoria) if categoria and not q else [],
        "categorias": CATEGORIAS,
        "q": q,
        "has_more": listing["has_more"],
        "next_offset": listing["next_offset"],
        "feed_batch": FEED_BATCH,
        "featured_count": FEATURED_COUNT,
        "home_top_count": HOME_TOP_COUNT,
        "monetization": get_monetization_config(),
        "suggested_news": listing["suggested_news"],
        "sparklines": sparklines,
        "stale_listing": bool(listing.get("stale")),
    }
    if empty_category:
        render_ctx["robots_noindex"] = True
    response = _render(
        request,
        "index.html",
        render_ctx,
    )
    response.headers["Cache-Control"] = "public, max-age=15, stale-while-revalidate=30"
    return response


@app.get("/api/feed", response_class=HTMLResponse)
def api_feed(
    request: Request,
    offset: int = 0,
    categoria: str | None = None,
    q: str | None = None,
):
    listing = _load_home_listing(
        categoria,
        max(0, offset),
        FEED_BATCH,
        q,
        include_suggestions=False,
    )
    sparklines = core.fetch_sparkline_data(blocking=False)
    i18n = build_i18n_context(request)
    html = templates.get_template("partials/feed_news_items.html").render(
        {
            "feed_news": listing["news"],
            "sparklines": sparklines,
            "request": request,
            "monetization": get_monetization_config(),
            **i18n,
        }
    )
    response = HTMLResponse(
        content=html,
        headers={
            "X-Has-More": "1" if listing["has_more"] else "0",
            "X-Next-Offset": str(listing["next_offset"]),
            "Cache-Control": "public, max-age=15, stale-while-revalidate=30",
        },
    )
    if request.query_params.get("lang"):
        _set_lang_cookie(response, resolve_lang(request))
    return response


def _render_noticia_page(
    request: Request,
    noticia_id: int,
    noticia: tuple | list,
    *,
    canonical_path: str | None = None,
):
    client = get_db()
    dados_mercado = {}
    if len(noticia) > 9 and noticia[9]:
        try:
            raw_dados = noticia[9]
            if isinstance(raw_dados, (str, bytes, bytearray)):
                dados_mercado = json.loads(raw_dados)
        except json.JSONDecodeError:
            pass

    lang = resolve_lang(request)
    display = _apply_article_locale(noticia, lang)

    tag = str(display[5]) if len(display) > 5 and display[5] else "Economia"
    resumo = str(display[2]) if len(display) > 2 and display[2] else ""
    impacto = str(display[3]) if len(display) > 3 and display[3] else ""
    contexto = str(display[10]) if len(display) > 10 and display[10] else ""
    fonte_url = clean_source_url(display[4] if len(display) > 4 else None)
    fonte_nome = infer_source_name(
        display[8] if len(display) > 8 else None,
        display[4] if len(display) > 4 else None,
    )
    if not fonte_url:
        fonte_url = source_homepage(fonte_nome, display[4] if len(display) > 4 else None)

    try:
        enrichment = build_article_enrichment(
            client,
            noticia_id,
            tag,
            dados_mercado,
            resumo=resumo,
            published_at=display[7] if len(display) > 7 else None,
            created_at=None,
        )
    except Exception as exc:
        # Página principal não pode cair por falha transitória Turso no enrichment.
        print(f"Aviso: enrichment parcial em /noticia/{noticia_id}: {exc}", flush=True)
        enrichment = {
            "market_stats": {"pontos_chave": []},
            "related_articles": [],
            "acervo_stats": {"total": 0, "positivo": 0, "negativo": 0, "neutro": 0, "tom": "Neutro", "insight": "", "chart": []},
            "historical_charts": [],
            "before_after": None,
            "relevance": None,
            "trust": None,
            "timeline": [],
            "cenarios": [],
            "perfil_investidor": {},
            "glossario": [],
            "faq": [],
            "tabela_comparativa": None,
            "lentes_analiticas": [],
            "atualizacao": None,
            "related_entities": [],
            "cross_links": [],
            "data_source_links": [],
            "linked_resumo": "",
            "linked_resumo_parts": [],
            "periodo_analise": None,
        }
    contextual_affiliate = get_contextual_affiliate(tag)
    reading_minutes = core.estimate_reading_minutes(resumo, impacto, contexto)
    internal_refs = _internal_refs_from_market(dados_mercado)

    path = canonical_path or f"/noticia/{noticia_id}"
    published_iso = _to_iso8601(display[7] if len(display) > 7 else None)
    updated_iso = _to_iso8601(display[13] if len(display) > 13 else None) or published_iso
    article_canonical = absolute_url(SITE_ORIGIN, path)
    has_en = _article_has_translation(noticia, "en")
    has_ja = _article_has_translation(noticia, "ja")
    hreflang_full = has_en or has_ja
    article_hreflang = build_hreflang_map(SITE_ORIGIN, path, {}, full=hreflang_full)

    # Thin content: evita indexação de análises curtas (mesmo limiar do sitemap / quality gate).
    resumo_len = len(str(resumo or ""))
    resumo_words = core.count_words(resumo)
    thin_article = (
        resumo_len < THIN_RESUMO_CHARS and resumo_words < core.MIN_ARTICLE_WORDS
    )

    user = _current_user(request)

    columnist_author = None
    columnist_body = None
    is_columnist_article = False
    try:
        meta = client.execute(
            """
            SELECT author_id, content_origin, moderation_status, conteudo_extra
            FROM news WHERE id = ? LIMIT 1
            """,
            [int(noticia_id)],
        )
        if meta.rows:
            author_id = meta.rows[0][0]
            origin = str(meta.rows[0][1] or "")
            mod_status = str(meta.rows[0][2] or columnists.STATUS_PUBLISHED)
            extra = meta.rows[0][3]
            is_columnist_article = origin == columnists.ORIGIN_COLUMNIST
            if is_columnist_article:
                columnist_body = str(extra or impacto or "")
                columnist_author = columnists.get_author_public(client, int(author_id) if author_id else None)
                allowed = mod_status == columnists.STATUS_PUBLISHED
                if not allowed and user:
                    if columnists.is_admin_user(user) or (
                        author_id is not None and int(user["id"]) == int(author_id)
                    ):
                        allowed = True
                if not allowed:
                    raise HTTPException(status_code=404, detail="Notícia não encontrada")
                if mod_status == columnists.STATUS_PUBLISHED and author_id:
                    try:
                        columnists.record_page_view(
                            client,
                            int(noticia_id),
                            author_id=int(author_id),
                            ip=_client_ip(request),
                            user_agent=request.headers.get("user-agent"),
                            viewer_user_id=int(user["id"]) if user else None,
                        )
                    except Exception:
                        pass
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Aviso: meta colunista /noticia/{noticia_id}: {exc}", flush=True)

    comments: list[dict[str, Any]] = []
    try:
        comments = community.list_comments(
            get_db(),
            int(noticia_id),
            include_pending_for_user=int(user["id"]) if user else None,
        )
    except Exception as exc:
        print(f"   [comments] listagem falhou id={noticia_id}: {exc}")

    response = _render(
        request,
        "noticia.html",
        {
            "noticia": display,
            "dados_mercado": dados_mercado,
            "enrichment": enrichment,
            "monetization": get_monetization_config(),
            "contextual_affiliate": contextual_affiliate,
            "reading_minutes": reading_minutes,
            "internal_refs": internal_refs,
            "categorias": CATEGORIAS,
            "fonte_url": fonte_url,
            "fonte_nome": fonte_nome,
            "canonical_path": path,
            "canonical_query": {},
            "canonical_url": article_canonical,
            "hreflang_urls": article_hreflang,
            "hreflang_full": hreflang_full,
            "robots_noindex": thin_article or is_columnist_article,
            "published_iso": published_iso,
            "updated_iso": updated_iso,
            "content_translated": lang != "pt" and _article_has_translation(noticia, lang),
            "comments": comments,
            "comment_flash": request.query_params.get("comment_msg"),
            "comment_flash_ok": request.query_params.get("comment_ok") == "1",
            "columnist_author": columnist_author,
            "columnist_body": columnist_body,
            "is_columnist_article": is_columnist_article,
        },
    )
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    return response


@app.get("/noticia/{noticia_id}", response_class=HTMLResponse)
def ver_noticia(request: Request, noticia_id: int):
    client = get_db()
    result = _fetch_news_by_id(client, noticia_id)

    if not result.rows:
        raise HTTPException(status_code=404, detail="Notícia não encontrada")

    noticia = result.rows[0]
    guide_slug = _guide_slug_from_link(noticia[4] if len(noticia) > 4 else None)
    if guide_slug and get_guide_by_slug(guide_slug):
        lang = (request.query_params.get("lang") or "").strip().lower()
        target = localized_path(
            f"/artigo/{guide_slug}",
            lang if lang in SUPPORTED_LANGS else "pt",
        )
        return RedirectResponse(url=target, status_code=301)

    return _render_noticia_page(request, noticia_id, noticia)


@app.get("/artigo/{slug}", response_class=HTMLResponse)
def ver_artigo_educativo(request: Request, slug: str):
    """Guias evergreen no mesmo molde de /noticia/{id}, com URL estável para hiperlinks."""
    if not get_guide_by_slug(slug):
        raise HTTPException(status_code=404, detail="Artigo não encontrado")

    client = get_db()
    # Sync completo só no startup. Aqui só materializa se o guia ainda não existir
    # (evita 4 UPDATEs Turso por pageview — causa KeyError/timeout em /artigo).
    noticia_id = find_guide_noticia_id(client, slug)
    if not noticia_id:
        try:
            ensure_educational_guides(client)
        except Exception:
            pass
        noticia_id = find_guide_noticia_id(client, slug)
    if not noticia_id:
        raise HTTPException(status_code=404, detail="Artigo não encontrado")

    result = _fetch_news_by_id(client, noticia_id)
    if not result.rows:
        raise HTTPException(status_code=404, detail="Artigo não encontrado")

    return _render_noticia_page(
        request,
        noticia_id,
        result.rows[0],
        canonical_path=f"/artigo/{slug}",
    )

@app.post("/api/newsletter")
async def newsletter_signup(email: str = Form(...)):
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="E-mail inválido")

    config = get_monetization_config()
    if not config.get("newsletter_enabled"):
        raise HTTPException(status_code=404, detail="Newsletter indisponível")

    newsletter_url = config.get("newsletter_external_url")
    if isinstance(newsletter_url, str) and newsletter_url:
        return RedirectResponse(url=newsletter_url, status_code=303)

    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    client = get_db()
    try:
        client.execute(
            "INSERT INTO newsletter_subscribers (email, created_at) VALUES (?, ?)",
            [email, agora],
        )
    except Exception:
        pass
    client.close()
    return RedirectResponse(url="/?newsletter=ok", status_code=303)


CONTACT_FORM_COOLDOWN_SEC = 60
AUTH_LOGIN_MAX_HITS = 8
AUTH_LOGIN_WINDOW_SEC = 15 * 60
AUTH_SIGNUP_MAX_HITS = 5
AUTH_SIGNUP_WINDOW_SEC = 60 * 60
_AUTH_RATE_LOCK = threading.Lock()
_AUTH_RATE_HITS: dict[str, list[float]] = {}


def reset_auth_rate_limits() -> None:
    """Zera o limiter in-memory (testes)."""
    with _AUTH_RATE_LOCK:
        _AUTH_RATE_HITS.clear()


def _auth_rate_limited(bucket: str, *, max_hits: int, window_sec: float) -> bool:
    now = time.time()
    with _AUTH_RATE_LOCK:
        hits = [t for t in _AUTH_RATE_HITS.get(bucket, []) if now - t < window_sec]
        if len(hits) >= max_hits:
            _AUTH_RATE_HITS[bucket] = hits
            return True
        hits.append(now)
        _AUTH_RATE_HITS[bucket] = hits
        return False


def _auth_client_bucket(request: Request, kind: str) -> str:
    return f"{kind}:{_client_ip(request) or 'unknown'}"


@app.post("/fale-conosco")
async def fale_conosco(
    request: Request,
    subject: str = Form(""),
    body: str = Form(""),
    page_url: str = Form(""),
):
    """Formulário público Fale conosco (AJAX JSON). Sem login obrigatório."""
    lang = resolve_lang(request)
    subj = (subject or "").strip()
    text = (body or "").strip()
    page = (page_url or "").strip()[:500]
    if page and not (page.startswith("/") or page.startswith(SITE_ORIGIN)):
        page = ""

    last_at = request.session.get("contact_last_at")
    now = time.time()
    if isinstance(last_at, (int, float)) and (now - float(last_at)) < CONTACT_FORM_COOLDOWN_SEC:
        return JSONResponse(
            {"ok": False, "error": i18n_translate(lang, "contact_rate_limited")},
            status_code=429,
        )

    if not subj or not text:
        return JSONResponse(
            {"ok": False, "error": i18n_translate(lang, "contact_required")},
            status_code=400,
        )
    if len(subj) > CONTACT_SUBJECT_MAX or len(text) > CONTACT_BODY_MAX:
        return JSONResponse(
            {"ok": False, "error": i18n_translate(lang, "contact_too_long")},
            status_code=400,
        )

    user = _current_user(request)
    result = send_contact_message(
        subject=subj,
        body=text,
        page_url=page,
        user_email=str(user.get("email") or "") if user else "",
        user_name=str(user.get("name") or "") if user else "",
        client_ip=_client_ip(request) or "",
    )
    if not result.get("ok"):
        return JSONResponse(
            {"ok": False, "error": i18n_translate(lang, "contact_error")},
            status_code=502,
        )

    request.session["contact_last_at"] = now
    return JSONResponse(
        {"ok": True, "message": i18n_translate(lang, "contact_success")},
    )


@app.get("/quem-somos", response_class=HTMLResponse)
async def quem_somos(request: Request):
    return _render(request, "quem-somos.html")


@app.get("/contato", response_class=HTMLResponse)
def contato(request: Request):
    return _render(
        request,
        "contato.html",
        {
            "canonical_path": "/contato",
            "canonical_query": {},
            "canonical_url": absolute_url(SITE_ORIGIN, "/contato"),
        },
    )


@app.get("/metodologia", response_class=HTMLResponse)
def metodologia(request: Request):
    return _render(
        request,
        "metodologia.html",
        {
            "canonical_path": "/metodologia",
            "canonical_query": {},
            "canonical_url": absolute_url(SITE_ORIGIN, "/metodologia"),
        },
    )


@app.get("/privacidade", response_class=HTMLResponse)
async def privacidade(request: Request):
    return _render(request, "privacidade.html")

@app.get("/termos", response_class=HTMLResponse)
async def termos(request: Request):
    return _render(request, "termos.html")


@app.get("/mercado", response_class=HTMLResponse)
def mercado_dashboard(request: Request):
    """Painel público: Selic, IPCA, dólar, BTC + histórico/sparklines + links editoriais."""
    # blocking=True: painel já espera o histórico; evita 1º paint com "—" nos cards.
    market = core.fetch_market_snapshot(blocking=True)
    bcb = core.fetch_bcb_snapshot(blocking=True)
    historico = core.fetch_market_historical()
    sparklines = core.fetch_sparkline_data(blocking=False)

    selic = bcb.get("Selic meta (% a.a.)") or {}
    ipca = bcb.get("IPCA acumulado 12 meses (%)") or {}
    usd = market.get("Dólar (USD/BRL)") or {}
    btc = market.get("Bitcoin (BTC/BRL)") or {}

    hist_30 = historico.get("30d") if isinstance(historico, dict) else {}
    if not isinstance(hist_30, dict):
        hist_30 = {}

    charts = {
        "selic": hist_30.get("Selic meta (% a.a.)"),
        "ipca": hist_30.get("IPCA 12 meses (%)") or hist_30.get("IPCA acumulado 12 meses (%)"),
        "usd": hist_30.get("Dólar (USD/BRL)") or hist_30.get("Dólar comercial (R$/US$)"),
        "btc": hist_30.get("Bitcoin (BTC/BRL)"),
    }

    related_analyses: list[dict[str, Any]] = []
    try:
        rows = get_db().execute(
            """
            SELECT id, titulo, tag
            FROM news
            WHERE LENGTH(COALESCE(resumo, '')) >= ?
            ORDER BY id DESC
            LIMIT 8
            """,
            [THIN_RESUMO_CHARS],
        ).rows
        related_analyses = [
            {"id": int(r[0]), "titulo": str(r[1] or ""), "tag": str(r[2] or "")}
            for r in (rows or [])
        ]
    except Exception as exc:
        print(f"   [mercado] related analyses: {exc}")

    response = _render(
        request,
        "mercado.html",
        {
            "market": market,
            "bcb": bcb,
            "selic": selic,
            "ipca": ipca,
            "usd": usd,
            "btc": btc,
            "sparklines": sparklines,
            "charts": charts,
            "historico": historico,
            "monetization": get_monetization_config(),
            "categorias": CATEGORIAS,
            "related_analyses": related_analyses,
            "collected_at": market.get("coletado_em")
            or (historico.get("coletado_em") if isinstance(historico, dict) else None),
        },
    )
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
    return response


# ==========================================
# COMUNIDADE: login, cadastro, perfil, comentários
# ==========================================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _current_user(request):
        return RedirectResponse(url="/perfil", status_code=303)
    return _render(
        request,
        "login.html",
        {
            "next_url": _safe_next_url(request.query_params.get("next")),
            "auth_error": request.query_params.get("erro"),
            "auth_success": request.query_params.get("msg"),
            "needs_verification": request.query_params.get("verificar") == "1",
            "verify_email": (request.query_params.get("email") or "").strip().lower(),
            "robots_noindex": True,
        },
    )


@app.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    from urllib.parse import quote

    if _auth_rate_limited(
        _auth_client_bucket(request, "login"),
        max_hits=AUTH_LOGIN_MAX_HITS,
        window_sec=AUTH_LOGIN_WINDOW_SEC,
    ):
        return RedirectResponse(url="/login?erro=Muitas+tentativas.+Aguarde+alguns+minutos.", status_code=303)

    user = community.authenticate_local(get_db(), email, password)
    if not user:
        return RedirectResponse(url="/login?erro=Credenciais+inválidas", status_code=303)
    if not user.get("email_verified"):
        return RedirectResponse(
            url=(
                f"/login?verificar=1&email={quote(str(user['email']))}"
                f"&erro={quote(community.EMAIL_NOT_VERIFIED_MSG)}"
            ),
            status_code=303,
        )
    request.session[SESSION_USER_KEY] = int(user["id"])
    return RedirectResponse(url=_safe_next_url(next, "/"), status_code=303)


@app.get("/cadastro", response_class=HTMLResponse)
def cadastro_page(request: Request):
    if _current_user(request):
        return RedirectResponse(url="/perfil", status_code=303)
    return _render(
        request,
        "cadastro.html",
        {
            "auth_error": request.query_params.get("erro"),
            "auth_success": request.query_params.get("msg"),
            "robots_noindex": True,
        },
    )


@app.post("/cadastro")
async def cadastro_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    from urllib.parse import quote

    if _auth_rate_limited(
        _auth_client_bucket(request, "cadastro"),
        max_hits=AUTH_SIGNUP_MAX_HITS,
        window_sec=AUTH_SIGNUP_WINDOW_SEC,
    ):
        return RedirectResponse(url="/cadastro?erro=Muitas+tentativas.+Aguarde+e+tente+de+novo.", status_code=303)

    client = get_db()
    try:
        if community.find_user_by_email(client, email):
            return RedirectResponse(url="/cadastro?erro=E-mail+já+cadastrado", status_code=303)
        user = community.create_user(client, name=name, email=email, password=password)
    except ValueError as exc:
        return RedirectResponse(url=f"/cadastro?erro={quote(str(exc))}", status_code=303)
    except DatabaseUnavailableError:
        return RedirectResponse(
            url="/cadastro?erro="
            + quote("Banco temporariamente indisponível. Tente de novo em instantes."),
            status_code=303,
        )
    except Exception as exc:
        if _is_transient_db_error(exc):
            return RedirectResponse(
                url="/cadastro?erro="
                + quote("Banco temporariamente indisponível. Tente de novo em instantes."),
                status_code=303,
            )
        print(f"   [auth] falha no cadastro: {type(exc).__name__}: {exc}", flush=True)
        return RedirectResponse(url="/cadastro?erro=Não+foi+possível+criar+a+conta", status_code=303)

    from newsletter_service import MAIL_SEND_FAIL_USER_MSG, send_verification_email

    token = user.get("email_verify_token")
    mail_ok = False
    if token:
        try:
            send_result = send_verification_email(
                email=str(user["email"]),
                name=str(user.get("name") or ""),
                token=str(token),
                ttl_hours=community.EMAIL_VERIFY_TTL_HOURS,
            )
            mail_ok = bool(send_result.get("ok"))
        except Exception as exc:
            print(f"[newsletter] falha ao enviar e-mail de verificação: {exc}", flush=True)
            mail_ok = False

    if not mail_ok:
        err = quote(MAIL_SEND_FAIL_USER_MSG)
        return RedirectResponse(
            url=f"/login?verificar=1&email={quote(str(user['email']))}&erro={err}",
            status_code=303,
        )

    msg = quote(community.EMAIL_SIGNUP_OK_MSG)
    return RedirectResponse(
        url=f"/login?verificar=1&email={quote(str(user['email']))}&msg={msg}",
        status_code=303,
    )


@app.get("/verificar-email", response_class=HTMLResponse)
def verificar_email(request: Request, token: str | None = None):
    from urllib.parse import quote

    result = community.verify_email_token(get_db(), token or "")
    if result.get("ok"):
        msg = quote("E-mail confirmado! Agora você já pode entrar.")
        return RedirectResponse(url=f"/login?msg={msg}", status_code=303)
    err = quote(str(result.get("error") or "Link inválido ou expirado."))
    return RedirectResponse(url=f"/login?verificar=1&erro={err}", status_code=303)


@app.post("/reenviar-verificacao")
async def reenviar_verificacao(request: Request, email: str = Form(...)):
    from urllib.parse import quote

    from newsletter_service import MAIL_SEND_FAIL_USER_MSG, is_send_configured, send_verification_email

    client = get_db()
    email_n = (email or "").strip().lower()
    # Infra sem mailer: mensagem honesta (não finge envio).
    if not is_send_configured():
        print("[newsletter] mailer nao configurado", flush=True)
        return RedirectResponse(
            url=(
                f"/login?verificar=1&email={quote(email_n)}"
                f"&erro={quote(MAIL_SEND_FAIL_USER_MSG)}"
            ),
            status_code=303,
        )

    user = community.find_user_by_email(client, email_n) if email_n else None
    # Resposta genérica anti-enumeração (padrão Gamers League) + dica de Spam.
    ok_msg = quote(community.EMAIL_RESEND_OK_MSG)
    if user and not user.get("email_verified"):
        issued = community.issue_email_verification(client, int(user["id"]))
        if issued.get("rate_limited"):
            return RedirectResponse(
                url=(
                    f"/login?verificar=1&email={quote(email_n)}"
                    f"&erro={quote(str(issued.get('error') or 'Aguarde antes de reenviar.'))}"
                ),
                status_code=303,
            )
        if issued.get("ok") and issued.get("token"):
            try:
                send_result = send_verification_email(
                    email=str(issued["email"]),
                    name=str(issued.get("name") or ""),
                    token=str(issued["token"]),
                    ttl_hours=community.EMAIL_VERIFY_TTL_HOURS,
                )
                if not send_result.get("ok"):
                    return RedirectResponse(
                        url=(
                            f"/login?verificar=1&email={quote(email_n)}"
                            f"&erro={quote(MAIL_SEND_FAIL_USER_MSG)}"
                        ),
                        status_code=303,
                    )
            except Exception as exc:
                print(f"[newsletter] falha ao reenviar verificação: {exc}", flush=True)
                return RedirectResponse(
                    url=(
                        f"/login?verificar=1&email={quote(email_n)}"
                        f"&erro={quote(MAIL_SEND_FAIL_USER_MSG)}"
                    ),
                    status_code=303,
                )
    return RedirectResponse(
        url=f"/login?verificar=1&email={quote(email_n)}&msg={ok_msg}",
        status_code=303,
    )


@app.post("/logout")
async def logout_submit(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/perfil", response_class=HTMLResponse)
def perfil_page(request: Request):
    user = _current_user(request)
    if not user:
        return RedirectResponse(url="/login?next=/perfil", status_code=303)
    return _render(
        request,
        "perfil.html",
        {
            "current_user": user,
            "profile_flash": request.query_params.get("msg"),
            "profile_flash_ok": request.query_params.get("ok") == "1",
            "robots_noindex": True,
        },
    )


@app.post("/perfil/avatar")
async def perfil_avatar(request: Request, avatar: UploadFile = File(...)):
    user = _current_user(request)
    if not user:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "login_required"}, status_code=401)
        return RedirectResponse(url="/login?next=/perfil", status_code=303)
    data = await avatar.read()
    try:
        url = community.save_avatar_upload(int(user["id"]), avatar.filename or "avatar.jpg", data)
        get_db().execute("UPDATE users SET avatar_url = ? WHERE id = ?", [url, int(user["id"])])
    except ValueError as exc:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        from urllib.parse import quote

        return RedirectResponse(url=f"/perfil?ok=0&msg={quote(str(exc))}", status_code=303)
    except Exception:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "Falha no upload"}, status_code=500)
        return RedirectResponse(url="/perfil?ok=0&msg=Falha+no+upload", status_code=303)
    if _wants_json(request):
        return JSONResponse({"ok": True, "avatar_url": url, "message": "Avatar atualizado"})
    return RedirectResponse(url="/perfil?ok=1&msg=Avatar+atualizado", status_code=303)


@app.get("/auth/google")
def auth_google_start(request: Request):
    if not community.google_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth não configurado")
    import secrets

    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["oauth_next"] = _safe_next_url(request.query_params.get("next"), "/")
    return RedirectResponse(url=community.google_authorize_url(state), status_code=302)


@app.get("/auth/google/callback")
def auth_google_callback(request: Request, code: str | None = None, state: str | None = None):
    if not community.google_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth não configurado")
    expected = request.session.get("oauth_state")
    if not code or not state or not expected or state != expected:
        return RedirectResponse(url="/login?erro=OAuth+inválido", status_code=303)
    try:
        info = community.exchange_google_code(code)
        if not info.get("email") or not info.get("google_id"):
            return RedirectResponse(url="/login?erro=Perfil+Google+incompleto", status_code=303)
        user = community.link_or_create_google_user(
            get_db(),
            google_id=str(info["google_id"]),
            email=str(info["email"]),
            name=str(info.get("name") or ""),
            picture=info.get("picture"),
        )
    except Exception:
        return RedirectResponse(url="/login?erro=Falha+no+login+Google", status_code=303)
    request.session.pop("oauth_state", None)
    next_url = _safe_next_url(request.session.pop("oauth_next", None), "/")
    request.session[SESSION_USER_KEY] = int(user["id"])
    return RedirectResponse(url=next_url, status_code=303)


def _wants_json(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    if "application/json" in accept:
        return True
    return (request.headers.get("x-requested-with") or "").lower() == "xmlhttprequest"


@app.post("/noticia/{noticia_id}/comentarios")
async def post_comment(
    request: Request,
    noticia_id: int,
    body: str = Form(...),
    parent_id: int | None = Form(None),
):
    user = _current_user(request)
    if not user:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "login_required", "login_url": f"/login?next=/noticia/{noticia_id}%23comentarios"}, status_code=401)
        return RedirectResponse(url=f"/login?next=/noticia/{noticia_id}%23comentarios", status_code=303)
    consent = community.parse_consent_cookie(request.cookies.get(CONSENT_COOKIE))
    from urllib.parse import quote

    try:
        result = community.create_comment(
            get_db(),
            news_id=noticia_id,
            user_id=int(user["id"]),
            body=body,
            parent_id=parent_id,
            ip=_client_ip(request),
            headers=_request_headers_map(request),
            consent=consent,
        )
    except ValueError as exc:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return RedirectResponse(
            url=f"/noticia/{noticia_id}?comment_ok=0&comment_msg={quote(str(exc))}#comentarios",
            status_code=303,
        )
    except Exception:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "Erro ao salvar"}, status_code=500)
        return RedirectResponse(
            url=f"/noticia/{noticia_id}?comment_ok=0&comment_msg={quote('Erro ao salvar')}#comentarios",
            status_code=303,
        )
    published = result.get("status") == "published"
    msg = "Comentário publicado." if published else "Comentário bloqueado pela moderação."
    if _wants_json(request):
        comment = {
            "id": result.get("id"),
            "user_id": result.get("user_id") or int(user["id"]),
            "parent_id": result.get("parent_id"),
            "body": result.get("body"),
            "status": result.get("status"),
            "created_at": result.get("created_at"),
            "created_at_label": result.get("created_at_label"),
            "geo_country": result.get("geo_country"),
            "upvotes": 0,
            "author_name": user.get("name") or "",
            "author_avatar": community.normalize_avatar_url(user.get("avatar_url")),
        }
        count = 0
        try:
            count = len(
                community.list_comments(
                    get_db(),
                    noticia_id,
                    include_pending_for_user=int(user["id"]),
                )
            )
        except Exception:
            count = 0
        return JSONResponse(
            {
                "ok": published,
                "message": msg,
                "comment": comment,
                "count": count,
            }
        )
    ok = "1" if published else "0"
    return RedirectResponse(
        url=f"/noticia/{noticia_id}?comment_ok={ok}&comment_msg={quote(msg)}#comentarios",
        status_code=303,
    )


@app.post("/comentarios/{comment_id}/upvote")
async def upvote_comment_route(
    request: Request,
    comment_id: int,
    news_id: int = Form(...),
):
    user = _current_user(request)
    if not user:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "login_required"}, status_code=401)
        return RedirectResponse(url=f"/login?next=/noticia/{news_id}%23comentarios", status_code=303)
    added = community.upvote_comment(get_db(), comment_id, int(user["id"]))
    if _wants_json(request):
        return JSONResponse({"ok": True, "added": bool(added)})
    return RedirectResponse(url=f"/noticia/{news_id}#comentarios", status_code=303)


@app.post("/comentarios/{comment_id}/excluir")
async def delete_comment_route(
    request: Request,
    comment_id: int,
    news_id: int = Form(...),
):
    user = _current_user(request)
    if not user:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "login_required"}, status_code=401)
        return RedirectResponse(url=f"/login?next=/noticia/{news_id}%23comentarios", status_code=303)
    try:
        result = community.delete_own_comment(get_db(), comment_id, int(user["id"]))
    except ValueError as exc:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        from urllib.parse import quote

        return RedirectResponse(
            url=f"/noticia/{news_id}?comment_ok=0&comment_msg={quote(str(exc))}#comentarios",
            status_code=303,
        )
    except Exception:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "Erro ao excluir"}, status_code=500)
        return RedirectResponse(
            url=f"/noticia/{news_id}?comment_ok=0&comment_msg=Erro+ao+excluir#comentarios",
            status_code=303,
        )
    if _wants_json(request):
        count = 0
        try:
            count = len(
                community.list_comments(
                    get_db(),
                    int(result["news_id"]),
                    include_pending_for_user=int(user["id"]),
                )
            )
        except Exception:
            count = 0
        return JSONResponse({"ok": True, "id": result["id"], "count": count, "message": "Comentário excluído."})
    return RedirectResponse(url=f"/noticia/{news_id}#comentarios", status_code=303)

# ==========================================
# ROTAS DE SEO E INTEGRAÇÕES
# ==========================================

@app.get("/ads.txt", response_class=Response)
def get_ads_txt():
    content = "google.com, pub-3623062544438213, DIRECT, f08c47fec0942fa0"
    return Response(content=content, media_type="text/plain")


@app.get("/google57b1aa23d9e87d82.html", response_class=Response)
def get_google_site_verification():
    """Arquivo HTML de verificação do Google Search Console."""
    path = Path(__file__).resolve().parent / "google57b1aa23d9e87d82.html"
    if path.is_file():
        content = path.read_text(encoding="utf-8")
    else:
        content = "google-site-verification: google57b1aa23d9e87d82.html"
    return Response(content=content, media_type="text/html; charset=utf-8")


@app.get("/media/default/{slug}.svg", response_class=Response)
def get_default_category_image(slug: str):
    """Capa padrão centrada — funciona em hero e thumbnails com object-cover."""
    item = DEFAULT_IMAGE_BY_SLUG.get(slug, DEFAULT_CATEGORY_IMAGES["Economia"])
    label = str(item["label"])
    icon = str(item["icon"])
    color_from = str(item["from"])
    color_to = str(item["to"])
    accent = str(item["accent"])
    # Composição centrada (600,338): ao cortar em cards pequenos o foco permanece legível.
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675" role="img" aria-label="{label}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{color_from}"/>
      <stop offset="100%" stop-color="{color_to}"/>
    </linearGradient>
    <radialGradient id="spot" cx="50%" cy="46%" r="42%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity=".18"/>
      <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1200" height="675" fill="url(#bg)"/>
  <rect width="1200" height="675" fill="url(#spot)"/>
  <g fill="none" stroke="{accent}" stroke-opacity=".26" stroke-width="4" stroke-linecap="round">
    <path d="M60 400 L230 300 L380 340 L560 200 L730 260 L920 130 L1150 190"/>
    <path d="M60 440 L250 390 L420 420 L600 300 L790 340 L1150 230" stroke-opacity=".14"/>
  </g>
  <circle cx="600" cy="337" r="128" fill="#020617" fill-opacity=".45" stroke="{accent}" stroke-width="3" stroke-opacity=".7"/>
  <text x="600" y="337" text-anchor="middle" dominant-baseline="central"
        font-family="Segoe UI Symbol, Arial, sans-serif" font-size="86" font-weight="700" fill="{accent}">{icon}</text>
</svg>"""
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/robots.txt", response_class=Response)
def get_robots_txt():
    # Busca, paginação legada e áreas de conta não devem consumir crawl budget.
    content = (
        "User-agent: *\n"
        + "Allow: /\n"
        + "Disallow: /api/\n"
        + "Disallow: /ping\n"
        + "Disallow: /login\n"
        + "Disallow: /cadastro\n"
        + "Disallow: /perfil\n"
        + "Disallow: /fale-conosco\n"
        + "Disallow: /verificar-email\n"
        + "Disallow: /reenviar-verificacao\n"
        + "Disallow: /auth/\n"
        + "Disallow: /colunista\n"
        + "Disallow: /admin/\n"
        + "Disallow: /idioma\n"
        + "Disallow: /*?q=\n"
        + "Disallow: /*?*q=\n"
        + "Disallow: /*?page=\n"
        + "Disallow: /*?*page=\n"
        + "Disallow: /*?lang=pt\n"
        + "Disallow: /*?*lang=pt\n"
        + "Allow: /*?lang=en\n"
        + "Allow: /*?*lang=en\n"
        + "Allow: /*?lang=ja\n"
        + "Allow: /*?*lang=ja\n"
        + "Disallow: /*?lang=\n"
        + "Disallow: /*?*lang=\n"
        + f"Sitemap: {SITE_ORIGIN}/sitemap.xml\n"
        + f"Sitemap: {SITE_ORIGIN}/feed.xml\n"
    )
    return Response(content=content, media_type="text/plain")


def _xml_escape(text: object) -> str:
    raw = str(text or "")
    return (
        raw.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _feed_rows(limit: int = RSS_FEED_LIMIT) -> list[Any]:
    client = get_db()
    try:
        result = client.execute(
            NEWS_LIST_SELECT + " ORDER BY id DESC LIMIT ?",
            [max(1, min(limit, 100))],
        )
        return list(result.rows or [])
    except Exception as exc:
        print(f"   [feed] Turso falhou ({type(exc).__name__})", flush=True)
        return []


def _row_pub_iso(row: tuple | list) -> str:
    iso = _to_iso8601(row[7] if len(row) > 7 else None)
    return iso or datetime.now().isoformat()


def _build_rss_xml(rows: list[Any]) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{_xml_escape('Clareza Capital')}</title>",
        f"<link>{_xml_escape(SITE_ORIGIN)}</link>",
        f"<description>{_xml_escape('Notícias financeiras, economia e mercado em tempo real.')}</description>",
        f'<atom:link href="{_xml_escape(absolute_url(SITE_ORIGIN, "/feed.xml"))}" rel="self" type="application/rss+xml" />',
        "<language>pt-BR</language>",
    ]
    for row in rows:
        nid = int(row[0])
        titulo = _xml_escape(row[1])
        resumo = _xml_escape((str(row[2] or ""))[:500])
        pub = _xml_escape(_row_pub_iso(row))
        link = _xml_escape(absolute_url(SITE_ORIGIN, f"/noticia/{nid}"))
        parts.extend(
            [
                "<item>",
                f"<title>{titulo}</title>",
                f"<link>{link}</link>",
                f"<guid isPermaLink=\"true\">{link}</guid>",
                f"<pubDate>{pub}</pubDate>",
                f"<description>{resumo}</description>",
                "</item>",
            ]
        )
    parts.extend(["</channel>", "</rss>"])
    return "\n".join(parts)


def _build_atom_xml(rows: list[Any]) -> str:
    updated = _row_pub_iso(rows[0]) if rows else datetime.now().isoformat()
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"<title>{_xml_escape('Clareza Capital')}</title>",
        f"<link href=\"{_xml_escape(SITE_ORIGIN)}\" />",
        f"<id>{_xml_escape(SITE_ORIGIN + '/')}</id>",
        f"<updated>{_xml_escape(updated)}</updated>",
    ]
    for row in rows:
        nid = int(row[0])
        titulo = _xml_escape(row[1])
        resumo = _xml_escape((str(row[2] or ""))[:500])
        pub = _xml_escape(_row_pub_iso(row))
        link = _xml_escape(absolute_url(SITE_ORIGIN, f"/noticia/{nid}"))
        parts.extend(
            [
                "<entry>",
                f"<title>{titulo}</title>",
                f"<link href=\"{link}\" />",
                f"<id>{link}</id>",
                f"<updated>{pub}</updated>",
                f"<summary>{resumo}</summary>",
                "</entry>",
            ]
        )
    parts.append("</feed>")
    return "\n".join(parts)


@app.get("/feed.xml", response_class=Response)
def get_feed_rss():
    xml = _build_rss_xml(_feed_rows())
    return Response(
        content=xml,
        media_type="application/rss+xml; charset=utf-8",
        headers={"Cache-Control": "public, max-age=300, stale-while-revalidate=600"},
    )


@app.get("/feed.atom", response_class=Response)
def get_feed_atom():
    xml = _build_atom_xml(_feed_rows())
    return Response(
        content=xml,
        media_type="application/atom+xml; charset=utf-8",
        headers={"Cache-Control": "public, max-age=300, stale-while-revalidate=600"},
    )


@app.get("/sitemap.xml", response_class=Response)
def get_sitemap():
    client = get_db()
    guide_ids: set[int] = set()
    for guide in EDUCATIONAL_GUIDES:
        try:
            nid = find_guide_noticia_id(client, guide["slug"])
            if nid:
                guide_ids.add(int(nid))
        except Exception:
            continue

    # Só artigos com corpo mínimo (evita thin/legado no sitemap).
    # Prioriza capas presentes — sinal forte para Discover/indexação.
    noticias: list[Any] = []
    try:
        result = client.execute(
            """
            SELECT id,
                   COALESCE(NULLIF(updated_at, ''), NULLIF(published_at, ''), created_at) AS lastmod
            FROM news
            WHERE LENGTH(COALESCE(resumo, '')) >= ?
            ORDER BY
              CASE WHEN imagem_url IS NOT NULL AND TRIM(imagem_url) != '' THEN 0 ELSE 1 END,
              id DESC
            LIMIT 500
            """,
            [THIN_RESUMO_CHARS],
        )
        noticias = result.rows
    except Exception as exc:
        print(f"   [sitemap] Turso falhou ({type(exc).__name__}); só URLs estáticas.", flush=True)

    today = datetime.now().date().isoformat()
    static_urls = [
        (absolute_url(SITE_ORIGIN, "/"), "daily", "1.0", today),
        (absolute_url(SITE_ORIGIN, "/quem-somos"), "monthly", "0.6", today),
        (absolute_url(SITE_ORIGIN, "/metodologia"), "monthly", "0.7", today),
        (absolute_url(SITE_ORIGIN, "/contato"), "monthly", "0.5", today),
        (absolute_url(SITE_ORIGIN, "/mercado"), "hourly", "0.8", today),
        (absolute_url(SITE_ORIGIN, "/privacidade"), "monthly", "0.3", today),
        (absolute_url(SITE_ORIGIN, "/termos"), "monthly", "0.3", today),
    ]
    for tag in SITE_TOPIC_KEYWORDS:
        static_urls.append(
            (absolute_url(SITE_ORIGIN, "/", {"categoria": tag}), "daily", "0.7", today)
        )
    for guide in EDUCATIONAL_GUIDES:
        static_urls.append(
            (absolute_url(SITE_ORIGIN, f"/artigo/{guide['slug']}"), "weekly", "0.9", today)
        )

    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, changefreq, priority, lastmod in static_urls:
        xml_parts.append(
            f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod>"
            + f"<changefreq>{changefreq}</changefreq><priority>{priority}</priority></url>"
        )

    for row in noticias:
        nid = int(row[0])
        if nid in guide_ids:
            continue
        lastmod = _to_iso8601(row[1] if len(row) > 1 else None)
        lastmod_date = (lastmod or today)[:10]
        xml_parts.append(
            f"  <url><loc>{absolute_url(SITE_ORIGIN, f'/noticia/{nid}')}</loc>"
            + f"<lastmod>{lastmod_date}</lastmod>"
            + f"<changefreq>weekly</changefreq><priority>0.6</priority></url>"
        )

    xml_parts.append("</urlset>")
    return Response(content="\n".join(xml_parts), media_type="application/xml")

# ==========================================
# ROTAS DE INFRAESTRUTURA E ROBÔ
# ==========================================

ROBO_TOKEN_MIN_LEN = 16


def get_robo_token() -> str:
    """Segredo das rotas /api/robô — só via ambiente (nunca hardcoded)."""
    return (os.getenv("ROBO_TOKEN") or os.getenv("ROBOT_TOKEN") or "").strip()


def extract_robo_token(request: Request, token: str | None = None) -> str | None:
    """Ordem: Authorization Bearer → X-Robo-Token → query ?token= (cron legado)."""
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        value = auth[7:].strip()
        if value:
            return value
    for header_name in ("X-Robo-Token", "X-Robot-Token"):
        value = (request.headers.get(header_name) or "").strip()
        if value:
            return value
    if token is not None and str(token).strip():
        return str(token).strip()
    q = (request.query_params.get("token") or "").strip()
    return q or None


def _tokens_match(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    a = provided.encode("utf-8")
    b = expected.encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def require_robo_auth(request: Request, token: str | None = None) -> None:
    expected = get_robo_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="ROBO_TOKEN nao configurado no ambiente",
        )
    if core.is_cloud_host() and len(expected) < ROBO_TOKEN_MIN_LEN:
        raise HTTPException(
            status_code=503,
            detail="ROBO_TOKEN demasiado previsivel — defina um segredo longo no painel",
        )
    provided = extract_robo_token(request, token)
    if not provided or not _tokens_match(provided, expected):
        raise HTTPException(status_code=401, detail="Nao autorizado")


def _persist_generated_news(noticias_geradas: list[dict[str, Any]]) -> int:
    """Insere no banco o lote gerado pela IA. Retorna quantas linhas novas."""
    if not noticias_geradas:
        return 0

    client = get_db()
    salvas = 0
    existing = existing_news_links([n.get("original_link", "") for n in noticias_geradas])

    for n in noticias_geradas:
        link = n.get("original_link") or ""
        if not link or link in existing:
            continue

        agora = n.get("published_at")
        dados_raw = n.get("dados_mercado")
        if dados_raw:
            try:
                dados_obj = json.loads(dados_raw) if isinstance(dados_raw, str) else dados_raw
                refs = dados_obj.get("referencias_internas") or []
                if refs:
                    dados_obj["referencias_internas"] = resolve_referencias_internas(client, refs)
                    dados_raw = json.dumps(dados_obj, ensure_ascii=False)
            except json.JSONDecodeError:
                pass

        priority = core.compute_home_priority(n)
        try:
            client.execute(
                """
                INSERT INTO news (
                    titulo, resumo, impacto, link, tag, sentimento, published_at,
                    fonte, dados_mercado, contexto_editorial, created_at, imagem_url, versao_analise,
                    home_priority
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    n["titulo_viral"],
                    n["resumo_simples"],
                    n["impacto_bolso"],
                    link,
                    n["tag"],
                    n.get("sentimento", "Neutro"),
                    agora,
                    n.get("fonte"),
                    dados_raw if dados_raw else n.get("dados_mercado"),
                    n.get("contexto_editorial", ""),
                    agora,
                    n.get("imagem_url"),
                    n.get("versao_analise", 1),
                    priority,
                ],
            )
        except Exception as exc:
            print(
                f"   [db] INSERT news falhou ({type(exc).__name__})",
                flush=True,
            )
            continue
        existing.add(link)
        salvas += 1
        print("   [db] gravou noticia no banco", flush=True)
        try:
            index_news_by_link(client, link)
        except Exception:
            pass

        if priority >= core.HOME_HEADLINE_MIN_PRIORITY:
            try:
                id_row = client.execute("SELECT id FROM news WHERE link = ? LIMIT 1", [link])
                if id_row.rows:
                    news_id = int(id_row.rows[0][0])
                    enqueue_urgency_alert(
                        client,
                        news_id,
                        str(n.get("titulo_viral") or ""),
                        str(n.get("tag") or "Economia"),
                        str(n.get("resumo_simples") or ""),
                        priority,
                    )
            except Exception as exc:
                print(f"   [newsletter] fila alerta urgencia ignorada: {exc}")

    return salvas


@app.get("/api/sync-news-fts")
def api_sync_news_fts(request: Request, token: str | None = None):
    """Rebuild do índice FTS (cron). No SQLite local os triggers já cobrem INSERT/UPDATE."""
    require_robo_auth(request, token)
    result = sync_news_fts()
    _invalidate_home_cache()
    return {"status": "Sucesso" if result.get("ok") else "Falha", **result}


@app.api_route("/api/import-from-turso", methods=["GET", "POST"])
def api_import_from_turso(
    request: Request,
    token: str | None = None,
    force: int = 0,
):
    """Copia o Turso para o SQLite do volume. Auth: ROBO_TOKEN."""
    require_robo_auth(request, token)
    try:
        result = import_turso_into_sqlite(force=bool(force))
    except TursoQuotaError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Turso recusou o dump (cota/plano). "
                "Libere a cota e tente de novo; nao e falha do portal."
            ),
        ) from exc
    except DatabaseConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        print(f"   [migrate] import falhou: {type(exc).__name__}", flush=True)
        raise HTTPException(
            status_code=502,
            detail="Falha ao importar o Turso para o SQLite do volume.",
        ) from exc
    try:
        ensure_schema(get_db(), force=True)
    except Exception as exc:
        print(f"   [migrate] schema apos import: {exc}", flush=True)
    _invalidate_home_cache()
    return {"status": "Sucesso", **result}


@app.post("/api/restore-sqlite")
async def api_restore_sqlite(
    request: Request,
    token: str | None = None,
    file: UploadFile | None = File(None),
):
    """Sobe um .db/.sql (opcional gzip) para o volume. Auth: ROBO_TOKEN."""
    require_robo_auth(request, token)
    if file is None:
        raise HTTPException(status_code=400, detail="arquivo obrigatorio")
    name = (file.filename or "news.db").replace("\\", "/").split("/")[-1].lower()
    if not name.endswith((".db", ".sqlite", ".sql", ".gz", ".db.gz", ".sql.gz")):
        raise HTTPException(
            status_code=400,
            detail="arquivo deve ser .db, .sqlite, .sql ou .gz",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="arquivo vazio")
    if len(data) > RESTORE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="arquivo excede 150 MB")
    dest = default_local_database_path()
    reset_db_client()
    try:
        result = restore_sqlite_payload(data, dest)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        print(f"   [migrate] restore falhou: {type(exc).__name__}", flush=True)
        raise HTTPException(
            status_code=400,
            detail="Nao foi possivel restaurar o arquivo enviado.",
        ) from exc
    if not sqlite_table_counts(dest).get("news"):
        raise HTTPException(
            status_code=400,
            detail="arquivo restaurado sem tabela news (ou vazia)",
        )
    activate_local_sqlite()
    try:
        ensure_schema(get_db(), force=True)
    except Exception as exc:
        print(f"   [migrate] schema apos restore: {exc}", flush=True)
    _invalidate_home_cache()
    return {
        "status": "Sucesso",
        "path": dest,
        "counts": sqlite_table_counts(dest),
        **result,
    }


@app.get("/api/newsletter-digest")
def newsletter_digest(request: Request, token: str | None = None):
    """Digest semanal: 1–2 matérias Alta + painel macro (cron com ROBO_TOKEN)."""
    require_robo_auth(request, token)
    if not is_send_configured():
        raise HTTPException(status_code=503, detail="Provedor de envio nao configurado")
    client = get_db()
    result = send_weekly_digest(client)
    if result.get("skipped"):
        return {"status": "Ignorado", **result}
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Falha no envio"))
    return {"status": "Sucesso", **result}


@app.get("/api/newsletter-digest-diario")
def newsletter_digest_diario(request: Request, token: str | None = None):
    """Digest até 2x/dia: 1–2 matérias Alta; não envia se não houver conteúdo importante."""
    require_robo_auth(request, token)
    if not is_send_configured():
        raise HTTPException(status_code=503, detail="Provedor de envio nao configurado")
    client = get_db()
    result = send_daily_digest(client)
    if result.get("skipped"):
        return {"status": "Ignorado", **result}
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Falha no envio"))
    return {"status": "Sucesso", **result}


@app.get("/api/newsletter-alerta")
def newsletter_alerta(
    request: Request,
    token: str | None = None,
    news_id: int | None = None,
):
    """Reenvio manual de alerta de urgência para uma notícia (auth robô)."""
    require_robo_auth(request, token)
    if news_id is None:
        raise HTTPException(status_code=400, detail="news_id obrigatorio")
    if not is_send_configured():
        raise HTTPException(status_code=503, detail="Provedor de envio nao configurado")

    client = get_db()
    row = client.execute(
        "SELECT id, titulo, resumo, tag, COALESCE(home_priority, 0) FROM news WHERE id = ?",
        [news_id],
    )
    if not row.rows:
        raise HTTPException(status_code=404, detail="Noticia nao encontrada")
    data = row.rows[0]
    result = send_urgency_alert(
        client,
        int(data[0]),
        str(data[1] or ""),
        str(data[3] or "Economia"),
        str(data[2] or ""),
        int(data[4] or 0),
    )
    if not result.get("ok") and not result.get("skipped"):
        raise HTTPException(status_code=400, detail=result.get("error", "Falha no envio"))
    return {"status": "Sucesso", **result}


@app.get("/api/radar-semanal")
def radar_semanal(request: Request, token: str | None = None, force: int = 0):
    """Gera o Radar da semana (análise própria) e persiste no banco."""
    require_robo_auth(request, token)
    geradas = core.generate_weekly_radar(force=bool(force))
    # Se force e já existia, generate_weekly_radar cria link novo; se vazio sem force, ok.
    salvas = _persist_generated_news(geradas)
    if salvas:
        cover_limit = min(5, salvas)
        backfill = core.backfill_missing_images(limit=cover_limit)
        _invalidate_home_cache()
        invalidate_sentiment_cache()
    else:
        backfill = None
    return {
        "status": "Sucesso",
        "processadas_pela_ia": len(geradas),
        "novas_salvas_no_banco": salvas,
        "titulos": [g.get("titulo_viral") for g in geradas],
        "backfill_capas": backfill,
    }


@app.get("/api/macro-watch")
def macro_watch(request: Request, token: str | None = None):
    """Compara Selic/IPCA com snapshot anterior; gera matéria se mudou."""
    require_robo_auth(request, token)
    result = core.run_macro_watch(persist_state=True)
    geradas = result.get("generated") or []
    salvas = _persist_generated_news(geradas)
    if salvas:
        _ = core.backfill_missing_images(limit=min(5, salvas))
        _invalidate_home_cache()
        invalidate_sentiment_cache()
    return {
        "status": "Sucesso",
        "changes": result.get("changes") or [],
        "current": result.get("current") or {},
        "processadas_pela_ia": len(geradas),
        "novas_salvas_no_banco": salvas,
        "titulos": [g.get("titulo_viral") for g in geradas],
    }


@app.get("/api/traduzir-pendentes")
def traduzir_pendentes(request: Request, token: str | None = None, limit: int = 10):
    """Traduz título+resumo pendentes para EN/JA (auth robô)."""
    require_robo_auth(request, token)
    result = core.translate_pending_articles(limit=limit)
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Falha na traducao"))
    return {"status": "Sucesso", **result}


@app.get("/ping")
def ping():
    return {"status": "Render acordado!"}


@app.get("/api/gerar-imagens")
def gerar_imagens(request: Request, token: str | None = None, limit: int = 1):
    """Gera capas pendentes (Pexels/stock rápido; IA como fallback). Prioriza noticias novas."""
    require_robo_auth(request, token)

    # Stock permite lotes maiores; IA ainda respeita cotas internas.
    limit = max(1, min(limit, 40))
    print(f"Gerando imagens para ate {limit} artigos sem capa (prioridade: novas)...")
    resultado = core.backfill_missing_images(limit=limit)
    _invalidate_home_cache()
    return {
        "status": "Sucesso",
        **resultado,
        # Diagnóstico de config (sem expor segredo): ajuda a identificar env faltando no host.
        "providers": core.get_image_providers(),
        "pexels_key": bool(core.get_pexels_api_key()),
        "pexels_remote_url": core._pexels_use_remote_url(),
    }


@app.get("/api/gerar-analises-proprias")
def gerar_analises_proprias(request: Request, token: str | None = None, count: int | None = None):
    """Gera análises editoriais próprias a partir do acervo (sem RSS).

    Consome a cota diária de texto Gemini. Por padrão completa a meta
    ``ROBOT_OWN_ANALYSES`` (mín. 5/dia) — só gera o que ainda falta hoje.
    """
    require_robo_auth(request, token)

    meta = core.get_robot_own_analyses_count()
    alvo = meta if count is None else max(0, min(int(count), 10))
    print(f"Gerando análises próprias (alvo={alvo}, meta_dia={meta})...")
    geradas = core.generate_own_analyses(count=alvo)
    salvas = _persist_generated_news(geradas)
    # Cobre o lote novo (não só 1) — capas falham no hot path com 429/cota.
    cover_limit = min(40, max(salvas, 1)) if salvas else 0
    backfill = core.backfill_missing_images(limit=cover_limit) if cover_limit else None
    _invalidate_home_cache()
    invalidate_sentiment_cache()
    return {
        "status": "Sucesso",
        "meta_diaria": meta,
        "ja_publicadas_hoje": core.count_own_analyses_today(),
        "processadas_pela_ia": len(geradas),
        "novas_salvas_no_banco": salvas,
        "backfill_capas": backfill,
        "titulos": [g.get("titulo_viral") for g in geradas],
    }


@app.get("/api/rodar-robo")
def rodar_robo(request: Request, token: str | None = None):
    require_robo_auth(request, token)
    if _robo_runs_async():
        if not _robo_job_lock.acquire(blocking=False):
            return JSONResponse(
                {"status": "Ignorado", "detail": "Robo ja em execucao"},
                status_code=202,
            )

        def _job() -> None:
            try:
                _execute_robot_pipeline()
            except Exception as exc:
                print(f"   [robo] falha em background: {type(exc).__name__}: {exc}", flush=True)
                traceback.print_exc()
            finally:
                _robo_job_lock.release()

        try:
            threading.Thread(target=_job, name="rodar-robo", daemon=True).start()
        except Exception:
            _robo_job_lock.release()
            raise
        return JSONResponse(
            {
                "status": "Aceito",
                "detail": "Robo iniciado em segundo plano. Acompanhe os logs do servico.",
            },
            status_code=202,
        )
    return _execute_robot_pipeline()


def _robo_runs_async() -> bool:
    flag = os.getenv("ROBO_ASYNC", "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    if flag in ("0", "false", "no"):
        return False
    return core.is_cloud_host()


_robo_job_lock = threading.Lock()


def _execute_robot_pipeline() -> dict[str, Any]:
    print("Iniciando robo via API...", flush=True)

    # 1) Reserva da cota do dia: análises próprias a partir do acervo (meta ≥ 3).
    # Roda ANTES do RSS para não perder a cota Gemini com feeds.
    own_target = core.get_robot_own_analyses_count()
    own_geradas: list[dict[str, Any]] = []
    own_salvas = 0
    if own_target > 0:
        print(f"Análises próprias: prioridade na cota (meta diária={own_target})...")
        own_geradas = core.generate_own_analyses()
        own_salvas = _persist_generated_news(own_geradas)

    # 2) RSS: teto da rodada reduzido pelo que ainda falta da meta própria,
    # para não esgotar a cota antes de completar o mínimo diário.
    reserved = max(0, own_target - core.count_own_analyses_today())
    max_articles = max(1, core.get_robot_max_articles() - reserved)
    incremental = {"n": 0}

    def _persist_item(item: dict[str, Any]) -> None:
        added = _persist_generated_news([item])
        incremental["n"] += added
        if added:
            _invalidate_home_cache()

    noticias_geradas = core.fetch_and_process(
        max_articles=max_articles,
        on_item=_persist_item,
    )
    salvas = incremental["n"] + _persist_generated_news(noticias_geradas)

    # 2b) Macro-watch: Selic/IPCA — gera matéria se o indicador mudou desde a última rodada.
    print("Macro-watch: conferindo Selic/IPCA...")
    macro_result = core.run_macro_watch(persist_state=True)
    macro_geradas = macro_result.get("generated") or []
    macro_salvas = _persist_generated_news(macro_geradas)

    # Se a meta própria ainda não fechou (ex.: acervo curto na 1ª passagem), tenta de novo.
    if own_target > 0 and core.count_own_analyses_today() < own_target:
        print("Análises próprias: 2ª passagem após RSS...")
        extra = core.generate_own_analyses()
        own_geradas.extend(extra)
        own_salvas += _persist_generated_news(extra)

    if not noticias_geradas and not own_geradas and not macro_geradas:
        print("Nenhuma noticia nova — gerando capa para pendentes (prioridade id DESC)...")
        backfill = core.backfill_missing_images(limit=8)
        _invalidate_home_cache()
        return {
            "status": "Sem noticias novas — backfill de capas executado.",
            "processadas_pela_ia": 0,
            "novas_salvas_no_banco": 0,
            "analises_proprias": {
                "meta_diaria": own_target,
                "processadas": 0,
                "salvas": 0,
                "hoje": core.count_own_analyses_today(),
            },
            "macro_watch": {
                "changes": macro_result.get("changes") or [],
                "salvas": macro_salvas,
            },
            "backfill_capas": backfill,
        }

    novas = salvas + own_salvas + macro_salvas
    cover_limit = min(40, max(novas, 8))
    print(
        f"Backfill pos-robo: ate {cover_limit} capa(s) pendente(s) "
        + f"(novas_salvas={novas}, prioridade noticias novas)..."
    )
    backfill = core.backfill_missing_images(limit=cover_limit)
    _invalidate_home_cache()
    invalidate_sentiment_cache()
    return {
        "status": "Sucesso",
        "processadas_pela_ia": len(noticias_geradas),
        "novas_salvas_no_banco": salvas,
        "analises_proprias": {
            "meta_diaria": own_target,
            "processadas": len(own_geradas),
            "salvas": own_salvas,
            "hoje": core.count_own_analyses_today(),
            "titulos": [g.get("titulo_viral") for g in own_geradas],
        },
        "macro_watch": {
            "changes": macro_result.get("changes") or [],
            "salvas": macro_salvas,
            "titulos": [g.get("titulo_viral") for g in macro_geradas],
        },
        "backfill_capas": backfill,
    }


@app.get("/api/atualizar-artigos")
def atualizar_artigos(request: Request, token: str | None = None, limit: int = 10):
    require_robo_auth(request, token)

    limit = max(1, min(limit, 50))
    print(f"Atualizando dados de mercado de ate {limit} artigos...")
    resultado = core.refresh_stale_articles(limit=limit)
    _invalidate_home_cache()
    return {"status": "Sucesso", **resultado}


# ==========================================
# COLUNISTAS (publicação, boost, carteira)
# ==========================================


@app.get("/termos-colunista", response_class=HTMLResponse)
def termos_colunista(request: Request):
    return _render(request, "columnist_terms.html", {})


@app.get("/colunista", response_class=HTMLResponse)
def columnist_home(request: Request):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login?next=/colunista", status_code=303)
    if not columnists.is_columnist_user(user):
        return RedirectResponse("/colunista/candidatar", status_code=303)
    client = get_db()
    flash = request.query_params.get("msg")
    flash_ok = request.query_params.get("ok") == "1"
    return _render(
        request,
        "columnist_dashboard.html",
        {
            "articles": columnists.list_author_articles(client, int(user["id"])),
            "balance": columnists.wallet_balance(client, int(user["id"])),
            "views_total": columnists.count_views(client, author_id=int(user["id"])),
            "ledger": columnists.list_ledger(client, int(user["id"])),
            "share_rate": columnists.columnist_share_rate(),
            "is_admin": columnists.is_admin_user(user),
            "flash": flash,
            "flash_ok": flash_ok,
        },
    )


@app.get("/colunista/candidatar", response_class=HTMLResponse)
def columnist_apply_get(request: Request):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login?next=/colunista/candidatar", status_code=303)
    if columnists.is_columnist_user(user) and not columnists.is_admin_user(user):
        return RedirectResponse("/colunista", status_code=303)
    client = get_db()
    return _render(
        request,
        "columnist_apply.html",
        {
            "application": columnists.get_application(client, int(user["id"])),
            "flash": request.query_params.get("msg"),
            "flash_ok": request.query_params.get("ok") == "1",
        },
    )


@app.post("/colunista/candidatar")
async def columnist_apply_post(request: Request, pitch: str = Form(...)):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login?next=/colunista/candidatar", status_code=303)
    try:
        columnists.submit_application(get_db(), int(user["id"]), pitch)
        return RedirectResponse("/colunista/candidatar?ok=1&msg=Candidatura+enviada.", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            f"/colunista/candidatar?ok=0&msg={quote_plus(str(exc))}",
            status_code=303,
        )


@app.get("/colunista/novo", response_class=HTMLResponse)
def columnist_new_get(request: Request):
    user = _require_columnist(request)
    if isinstance(user, RedirectResponse):
        return user
    return _render(
        request,
        "columnist_editor.html",
        {
            "article": None,
            "categorias": CATEGORIAS,
            "form_action": "/colunista/novo",
            "flash": request.query_params.get("msg"),
            "flash_ok": request.query_params.get("ok") == "1",
        },
    )


@app.post("/colunista/novo")
async def columnist_new_post(
    request: Request,
    titulo: str = Form(...),
    resumo: str = Form(...),
    body: str = Form(...),
    tag: str = Form("Economia"),
    action: str = Form("draft"),
    cover: UploadFile | None = File(None),
):
    user = _require_columnist(request)
    if isinstance(user, RedirectResponse):
        return user
    try:
        imagem_url = None
        if cover and cover.filename:
            data = await cover.read()
            if data:
                imagem_url = columnists.save_columnist_cover(
                    int(user["id"]), cover.filename, data
                )
        news_id = columnists.create_article(
            get_db(),
            user_id=int(user["id"]),
            author_name=str(user["name"]),
            titulo=titulo,
            resumo=resumo,
            body=body,
            tag=tag,
            submit=action == "submit",
            imagem_url=imagem_url,
        )
        _invalidate_home_cache()
        msg = "Enviado+para+revisao." if action == "submit" else "Rascunho+salvo."
        return RedirectResponse(f"/colunista?ok=1&msg={msg}", status_code=303)
    except (ValueError, RuntimeError) as exc:
        return RedirectResponse(
            f"/colunista/novo?ok=0&msg={quote_plus(str(exc))}",
            status_code=303,
        )


@app.get("/colunista/editar/{news_id}", response_class=HTMLResponse)
def columnist_edit_get(request: Request, news_id: int):
    user = _require_columnist(request)
    if isinstance(user, RedirectResponse):
        return user
    article = columnists.get_article_for_author(get_db(), news_id, int(user["id"]))
    if not article:
        raise HTTPException(status_code=404, detail="Artigo não encontrado")
    return _render(
        request,
        "columnist_editor.html",
        {
            "article": article,
            "categorias": CATEGORIAS,
            "form_action": f"/colunista/editar/{news_id}",
            "flash": request.query_params.get("msg"),
            "flash_ok": request.query_params.get("ok") == "1",
        },
    )


@app.post("/colunista/editar/{news_id}")
async def columnist_edit_post(
    request: Request,
    news_id: int,
    titulo: str = Form(...),
    resumo: str = Form(...),
    body: str = Form(...),
    tag: str = Form("Economia"),
    action: str = Form("draft"),
    cover: UploadFile | None = File(None),
):
    user = _require_columnist(request)
    if isinstance(user, RedirectResponse):
        return user
    try:
        imagem_url = None
        if cover and cover.filename:
            data = await cover.read()
            if data:
                imagem_url = columnists.save_columnist_cover(
                    int(user["id"]), cover.filename, data
                )
        columnists.update_article(
            get_db(),
            news_id=news_id,
            user_id=int(user["id"]),
            titulo=titulo,
            resumo=resumo,
            body=body,
            tag=tag,
            submit=action == "submit",
            is_admin=columnists.is_admin_user(user),
            imagem_url=imagem_url,
        )
        _invalidate_home_cache()
        return RedirectResponse("/colunista?ok=1&msg=Artigo+atualizado.", status_code=303)
    except (ValueError, PermissionError) as exc:
        return RedirectResponse(
            f"/colunista/editar/{news_id}?ok=0&msg={quote_plus(str(exc))}",
            status_code=303,
        )


@app.post("/colunista/pix")
async def columnist_pix(request: Request, pix_key: str = Form("")):
    user = _require_columnist(request)
    if isinstance(user, RedirectResponse):
        return user
    columnists.set_user_pix_key(get_db(), int(user["id"]), pix_key)
    return RedirectResponse("/colunista?ok=1&msg=Chave+PIX+salva.", status_code=303)


@app.post("/colunista/saque")
async def columnist_payout(request: Request):
    user = _require_columnist(request)
    if isinstance(user, RedirectResponse):
        return user
    try:
        columnists.request_payout(get_db(), int(user["id"]))
        return RedirectResponse("/colunista?ok=1&msg=Saque+solicitado.", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            f"/colunista?ok=0&msg={quote_plus(str(exc))}",
            status_code=303,
        )


@app.get("/colunista/impulsionar/{news_id}", response_class=HTMLResponse)
def columnist_boost_get(request: Request, news_id: int):
    user = _require_columnist(request)
    if isinstance(user, RedirectResponse):
        return user
    article = columnists.get_article_for_author(get_db(), news_id, int(user["id"]))
    if not article:
        raise HTTPException(status_code=404, detail="Artigo não encontrado")
    return _render(
        request,
        "columnist_boost.html",
        {
            "article": article,
            "plans": list(columnists.boost_plans().values()),
            "mp_ready": columnists.mp_configured(),
            "pix": None,
            "flash": request.query_params.get("msg"),
            "flash_ok": request.query_params.get("ok") == "1",
        },
    )


@app.post("/colunista/impulsionar/{news_id}")
async def columnist_boost_post(
    request: Request,
    news_id: int,
    plan_id: str = Form(...),
    simulate: str = Form(""),
):
    user = _require_columnist(request)
    if isinstance(user, RedirectResponse):
        return user
    client = get_db()
    try:
        order = columnists.create_boost_order(
            client, user_id=int(user["id"]), news_id=news_id, plan_id=plan_id
        )
    except ValueError as exc:
        return RedirectResponse(
            f"/colunista/impulsionar/{news_id}?ok=0&msg={quote_plus(str(exc))}",
            status_code=303,
        )

    if simulate == "1" and not columnists.mp_configured():
        columnists.activate_boost(client, int(order["id"]))
        _invalidate_home_cache()
        return RedirectResponse("/colunista?ok=1&msg=Destaque+ativado+(simulacao).", status_code=303)

    try:
        origin = (os.getenv("SITE_ORIGIN") or str(request.base_url)).rstrip("/")
        pix = columnists.mp_create_pix_payment(
            amount_brl=float(order["amount_brl"]),
            description=f"Destaque Clareza Capital — {order['plan']['label']}",
            external_reference=order["external_ref"],
            payer_email=str(user["email"]),
            notification_url=f"{origin}/webhooks/mercadopago",
        )
        if pix.get("payment_id"):
            client.execute(
                "UPDATE boost_orders SET mp_payment_id = ? WHERE id = ?",
                [str(pix["payment_id"]), int(order["id"])],
            )
        article = columnists.get_article_for_author(client, news_id, int(user["id"]))
        return _render(
            request,
            "columnist_boost.html",
            {
                "article": article,
                "plans": list(columnists.boost_plans().values()),
                "mp_ready": True,
                "pix": pix,
                "order_id": order["id"],
                "amount_brl": order["amount_brl"],
                "flash": None,
                "flash_ok": True,
            },
        )
    except Exception as exc:
        return RedirectResponse(
            f"/colunista/impulsionar/{news_id}?ok=0&msg={quote_plus(str(exc)[:180])}",
            status_code=303,
        )


@app.post("/colunista/impulsionar/{news_id}/confirmar")
async def columnist_boost_confirm(
    request: Request,
    news_id: int,
    order_id: int = Form(...),
    payment_id: str = Form(""),
):
    user = _require_columnist(request)
    if isinstance(user, RedirectResponse):
        return user
    client = get_db()
    try:
        if payment_id:
            pay = columnists.mp_get_payment(payment_id)
            if str(pay.get("status")) in ("approved", "authorized"):
                columnists.activate_boost(client, int(order_id))
                _invalidate_home_cache()
                return RedirectResponse("/colunista?ok=1&msg=Destaque+ativado.", status_code=303)
        return RedirectResponse(
            f"/colunista/impulsionar/{news_id}?ok=0&msg=Pagamento+ainda+nao+confirmado.",
            status_code=303,
        )
    except Exception as exc:
        return RedirectResponse(
            f"/colunista/impulsionar/{news_id}?ok=0&msg={quote_plus(str(exc)[:180])}",
            status_code=303,
        )


@app.post("/webhooks/mercadopago")
async def webhook_mercadopago(request: Request):
    """Webhook MP: ativa boost quando payment approved."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data_id = None
    if isinstance(payload, dict):
        data_id = (payload.get("data") or {}).get("id") or payload.get("id")
    if not data_id and request.query_params.get("data.id"):
        data_id = request.query_params.get("data.id")
    if not data_id:
        return JSONResponse({"ok": True, "ignored": True})
    try:
        pay = columnists.mp_get_payment(data_id)
        if str(pay.get("status")) not in ("approved", "authorized"):
            return JSONResponse({"ok": True, "status": pay.get("status")})
        ext = str(pay.get("external_reference") or "")
        client = get_db()
        order = columnists.find_boost_by_external_ref(client, ext)
        if order:
            columnists.activate_boost(client, int(order["id"]))
            _invalidate_home_cache()
        return JSONResponse({"ok": True})
    except Exception as exc:
        print(f"[mp webhook] {exc}", flush=True)
        return JSONResponse({"ok": False}, status_code=500)


@app.get("/admin/colunistas", response_class=HTMLResponse)
def admin_columnists_get(request: Request):
    _require_admin_user(request)
    client = get_db()
    return _render(
        request,
        "admin_columnists.html",
        {
            "applications": columnists.list_pending_applications(client),
            "articles": columnists.list_pending_articles(client),
            "payouts": columnists.list_pending_payouts(client),
            "flash": request.query_params.get("msg"),
            "flash_ok": request.query_params.get("ok") == "1",
        },
    )


@app.post("/admin/colunistas/candidatura/{application_id}")
async def admin_review_application(
    request: Request,
    application_id: int,
    decision: str = Form(...),
):
    _require_admin_user(request)
    columnists.review_application(
        get_db(), application_id, approve=decision == "approve"
    )
    return RedirectResponse("/admin/colunistas?ok=1&msg=Candidatura+atualizada.", status_code=303)


@app.post("/admin/colunistas/artigo/{news_id}")
async def admin_review_article(
    request: Request,
    news_id: int,
    decision: str = Form(...),
    admin_note: str = Form(""),
):
    _require_admin_user(request)
    columnists.review_article(
        get_db(), news_id, approve=decision == "approve", admin_note=admin_note
    )
    _invalidate_home_cache()
    return RedirectResponse("/admin/colunistas?ok=1&msg=Artigo+atualizado.", status_code=303)


@app.post("/admin/colunistas/saque/{payout_id}")
async def admin_settle_payout(
    request: Request,
    payout_id: int,
    decision: str = Form(...),
):
    _require_admin_user(request)
    columnists.settle_payout(get_db(), payout_id, paid=decision == "paid")
    return RedirectResponse("/admin/colunistas?ok=1&msg=Saque+atualizado.", status_code=303)


@app.post("/api/columnists/credit-daily")
def api_columnists_credit_daily(request: Request, token: str | None = None, day: str | None = None):
    require_admin_or_robo(request, token)
    result = columnists.credit_daily_shares(get_db(), day=day)
    return result


@app.post("/api/columnists/expire-boosts")
def api_columnists_expire_boosts(request: Request, token: str | None = None):
    require_admin_or_robo(request, token)
    n = columnists.expire_boosts(get_db())
    _invalidate_home_cache()
    return {"ok": True, "expired": n}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # Reload só em .py — evita reinício ao editar templates e trava menos no Windows.
    use_reload = os.getenv("UVICORN_RELOAD", "1").lower() in ("1", "true", "yes")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=use_reload,
        reload_includes=["*.py"] if use_reload else None,
        reload_excludes=[".venv", "__pycache__", "*.pyc", "*.db", "*.html"] if use_reload else None,
    )