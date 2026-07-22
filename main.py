import os
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from fastapi import FastAPI, Request, Response, HTTPException, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.staticfiles import StaticFiles as StarletteStaticFiles
import uvicorn
from dotenv import load_dotenv

import core
from db import QueryResult, get_db, ensure_schema
from monetization import get_monetization_config, get_contextual_affiliate
from article_enrichment import (
    build_article_enrichment,
    clean_source_url,
    infer_source_name,
    resolve_referencias_internas,
    source_homepage,
)
from i18n import COOKIE_MAX_AGE, COOKIE_NAME, build_i18n_context, resolve_lang

load_dotenv()


class CachedStaticFiles(StarletteStaticFiles):
    """StaticFiles com Cache-Control longo para assets versionados."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=604800, stale-while-revalidate=86400"
        return response


app = FastAPI()

ARTICLE_IMAGES_DIR = os.getenv("ARTICLE_IMAGES_DIR", "static/images/articles")
os.makedirs(ARTICLE_IMAGES_DIR, exist_ok=True)
os.makedirs("static/images/articles", exist_ok=True)

if os.path.exists("static"):
    app.mount("/static", CachedStaticFiles(directory="static"), name="static")
if os.path.isdir(ARTICLE_IMAGES_DIR):
    app.mount("/media/articles", CachedStaticFiles(directory=ARTICLE_IMAGES_DIR), name="article_images")
templates = Jinja2Templates(directory="templates")


@app.middleware("http")
async def security_and_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
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
    ctx = {"request": request, **build_i18n_context(request)}
    if context:
        ctx.update(context)
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context=ctx,
        status_code=status_code,
    )
    if request.query_params.get("lang"):
        response.set_cookie(
            COOKIE_NAME,
            resolve_lang(request),
            max_age=COOKIE_MAX_AGE,
            samesite="lax",
            httponly=False,
        )
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


templates.env.globals["category_image"] = category_image_url

try:
    startup_client = get_db()
    ensure_schema(startup_client)
except Exception as e:
    print(f"Aviso: Falha na inicialização do Turso: {e}")


@app.on_event("startup")
def _warmup_on_startup():
    def _run():
        try:
            core.warmup_market_caches()
            # Aquece a listagem padrão da home (destaques + 1º lote do feed).
            _load_home_listing(None, 0, FEATURED_COUNT + FEED_BATCH, None)
        except Exception as exc:
            print(f"Aviso: warmup inicial falhou: {exc}")

    threading.Thread(target=_run, daemon=True).start()

# ==========================================
# ROTAS DE PÁGINAS (FRONTEND) - ATUALIZADAS PARA FASTAPI MODERNO
# ==========================================

NEWS_SELECT = """
    SELECT id, titulo, resumo, impacto, link, tag, sentimento,
           COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao,
           fonte, dados_mercado, contexto_editorial, imagem_url,
           conteudo_extra, updated_at, versao_analise
    FROM news
"""

# Listagem da home: mantém os mesmos índices das templates, sem puxar blobs pesados.
NEWS_LIST_SELECT = """
    SELECT id, titulo, resumo, impacto, link, tag, sentimento,
           COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao,
           fonte, NULL AS dados_mercado, NULL AS contexto_editorial, imagem_url,
           NULL AS conteudo_extra, updated_at, versao_analise
    FROM news
"""


def _invalidate_home_cache() -> None:
    with _HOME_CACHE_LOCK:
        _HOME_CACHE.clear()


FEED_BATCH = 8
FEATURED_COUNT = 4


def _home_cache_key(categoria: str | None, offset: int, limit: int, q: str | None) -> str:
    return f"{categoria or ''}|{offset}|{limit}|{(q or '').strip().lower()}"


def _parse_count(row_count: object) -> int:
    if isinstance(row_count, (int, float)):
        return int(row_count)
    if isinstance(row_count, str):
        return int(row_count)
    return 0


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

    result: QueryResult
    count_res: QueryResult
    if q:
        busca = f"%{q}%"
        result = client.execute(
            NEWS_LIST_SELECT + " WHERE titulo LIKE ? OR resumo LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
            [busca, busca, limit, offset],
        )
        count_res = client.execute(
            "SELECT COUNT(*) FROM news WHERE titulo LIKE ? OR resumo LIKE ?",
            [busca, busca],
        )
    elif categoria:
        result = client.execute(
            NEWS_LIST_SELECT + " WHERE tag = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            [categoria, limit, offset],
        )
        count_res = client.execute("SELECT COUNT(*) FROM news WHERE tag = ?", [categoria])
    else:
        result = client.execute(
            NEWS_LIST_SELECT + " ORDER BY id DESC LIMIT ? OFFSET ?",
            [limit, offset],
        )
        count_res = client.execute("SELECT COUNT(*) FROM news")

    news = result.rows
    suggested_news: list[Any] = []
    if include_suggestions and not news and (categoria or q):
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

    total_news = _parse_count(count_res.rows[0][0] if count_res.rows else 0)
    next_offset = offset + len(news)
    has_more = next_offset < total_news

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


@app.get("/", response_class=HTMLResponse)
def index(request: Request, categoria: str | None = None, q: str | None = None):
    # Sem busca: 4 destaques + 8 no feed (2 colunas). Com busca: só o feed de 8.
    initial_limit = FEED_BATCH if q else FEATURED_COUNT + FEED_BATCH
    listing = _load_home_listing(categoria, 0, initial_limit, q)
    sparklines = core.fetch_sparkline_data(blocking=False)

    response = _render(
        request,
        "index.html",
        {
            "news": listing["news"],
            "categoria_ativa": categoria,
            "categorias": CATEGORIAS,
            "q": q,
            "has_more": listing["has_more"],
            "next_offset": listing["next_offset"],
            "feed_batch": FEED_BATCH,
            "monetization": get_monetization_config(),
            "suggested_news": listing["suggested_news"],
            "sparklines": sparklines,
        },
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
        response.set_cookie(
            COOKIE_NAME,
            resolve_lang(request),
            max_age=COOKIE_MAX_AGE,
            samesite="lax",
            httponly=False,
        )
    return response


@app.get("/noticia/{noticia_id}", response_class=HTMLResponse)
def ver_noticia(request: Request, noticia_id: int):
    client = get_db()
    result = client.execute(NEWS_SELECT + " WHERE id = ?", [noticia_id])

    if not result.rows:
        raise HTTPException(status_code=404, detail="Notícia não encontrada")

    noticia = result.rows[0]
    dados_mercado = {}
    if len(noticia) > 9 and noticia[9]:
        try:
            raw_dados = noticia[9]
            if isinstance(raw_dados, (str, bytes, bytearray)):
                dados_mercado = json.loads(raw_dados)
        except json.JSONDecodeError:
            pass

    tag = str(noticia[5]) if len(noticia) > 5 and noticia[5] else "Economia"
    resumo = str(noticia[2]) if len(noticia) > 2 and noticia[2] else ""
    fonte_url = clean_source_url(noticia[4] if len(noticia) > 4 else None)
    fonte_nome = infer_source_name(
        noticia[8] if len(noticia) > 8 else None,
        noticia[4] if len(noticia) > 4 else None,
    )
    if not fonte_url:
        fonte_url = source_homepage(fonte_nome, noticia[4] if len(noticia) > 4 else None)

    enrichment = build_article_enrichment(
        client,
        noticia_id,
        tag,
        dados_mercado,
        resumo=resumo,
        published_at=noticia[7] if len(noticia) > 7 else None,
        created_at=None,
    )
    contextual_affiliate = get_contextual_affiliate(tag)

    response = _render(
        request,
        "noticia.html",
        {
            "noticia": noticia,
            "dados_mercado": dados_mercado,
            "enrichment": enrichment,
            "monetization": get_monetization_config(),
            "contextual_affiliate": contextual_affiliate,
            "categorias": CATEGORIAS,
            "fonte_url": fonte_url,
            "fonte_nome": fonte_nome,
        },
    )
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    return response

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

@app.get("/quem-somos", response_class=HTMLResponse)
async def quem_somos(request: Request):
    return _render(request, "quem-somos.html")

@app.get("/privacidade", response_class=HTMLResponse)
async def privacidade(request: Request):
    return _render(request, "privacidade.html")

@app.get("/termos", response_class=HTMLResponse)
async def termos(request: Request):
    return _render(request, "termos.html")

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
    content = "User-agent: *\nAllow: /\nSitemap: https://financas-news.net.br/sitemap.xml"
    return Response(content=content, media_type="text/plain")

@app.get("/sitemap.xml", response_class=Response)
def get_sitemap():
    client = get_db()
    result = client.execute('SELECT id FROM news ORDER BY id DESC LIMIT 500')
    noticias = result.rows
    client.close()

    urls = [
        "https://financas-news.net.br/",
        "https://financas-news.net.br/quem-somos",
        "https://financas-news.net.br/privacidade",
        "https://financas-news.net.br/termos"
    ]
    
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    for url in urls:
        xml_content += f'  <url><loc>{url}</loc><changefreq>daily</changefreq><priority>0.8</priority></url>\n'
    
    for n in noticias:
        xml_content += f'  <url><loc>https://financas-news.net.br/noticia/{n[0]}</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>\n'
        
    xml_content += '</urlset>'
    return Response(content=xml_content, media_type="application/xml")

# ==========================================
# ROTAS DE INFRAESTRUTURA E ROBÔ
# ==========================================

@app.get("/ping")
def ping():
    return {"status": "Render acordado!"}

@app.get("/api/gerar-imagens")
def gerar_imagens(token: str | None = None, limit: int = 10):
    if token != "punkcode2026":
        raise HTTPException(status_code=401, detail="Nao autorizado")

    limit = max(1, min(limit, 20))
    print(f"Gerando imagens para ate {limit} artigos sem capa...")
    resultado = core.backfill_missing_images(limit=limit)
    _invalidate_home_cache()
    return {"status": "Sucesso", **resultado}


@app.get("/api/rodar-robo")
def rodar_robo(token: str | None = None):
    if token != "punkcode2026":
        raise HTTPException(status_code=401, detail="Não autorizado")
        
    print("🤖 Iniciando robô via API...")
    noticias_geradas = core.fetch_and_process()
    
    if not noticias_geradas:
        return {"status": "Aviso: Nenhuma notícia foi processada ou houve erro na IA."}
        
    client = get_db()
    salvas = 0
    
    for n in noticias_geradas:
        check = client.execute("SELECT id FROM news WHERE link = ?", [n["original_link"]])
        
        if not check.rows:
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

            client.execute('''
                INSERT INTO news (titulo, resumo, impacto, link, tag, sentimento, published_at, fonte, dados_mercado, contexto_editorial, created_at, imagem_url, versao_analise)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                n["titulo_viral"],
                n["resumo_simples"],
                n["impacto_bolso"],
                n["original_link"],
                n["tag"],
                n.get("sentimento", "Neutro"),
                agora,
                n.get("fonte"),
                dados_raw if dados_raw else n.get("dados_mercado"),
                n.get("contexto_editorial", ""),
                agora,
                n.get("imagem_url"),
                n.get("versao_analise", 1),
            ])
            salvas += 1
            
    _invalidate_home_cache()
    return {
        "status": "Sucesso", 
        "processadas_pela_ia": len(noticias_geradas), 
        "novas_salvas_no_banco": salvas
    }


@app.get("/api/atualizar-artigos")
def atualizar_artigos(token: str | None = None, limit: int = 10):
    if token != "punkcode2026":
        raise HTTPException(status_code=401, detail="Não autorizado")

    limit = max(1, min(limit, 50))
    print(f"Atualizando dados de mercado de ate {limit} artigos...")
    resultado = core.refresh_stale_articles(limit=limit)
    _invalidate_home_cache()
    return {"status": "Sucesso", **resultado}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)