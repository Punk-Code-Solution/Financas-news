"""Publicações sociais (LinkedIn + Instagram) a partir de matérias do portal.

LinkedIn: gera texto pronto para copiar/colar (padrão editorial da Punk Code).
Instagram: gera legenda no mesmo espírito + publica via Meta Graph API quando
`INSTAGRAM_ACCESS_TOKEN` e `INSTAGRAM_BUSINESS_ACCOUNT_ID` estiverem configurados.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

BRAND_NAME = "Clareza Capital"
BRAND_CONTACT = "punkcodesolution@gmail.com"
DEFAULT_SITE_ORIGIN = "https://financas-news.net.br"

# Alinhado ao digest: matérias de urgência Alta.
SOCIAL_MIN_PRIORITY = 80
SOCIAL_LOOKBACK_HOURS = 24
SOCIAL_MAX_PER_RUN = 3

CHANNEL_LINKEDIN = "linkedin"
CHANNEL_INSTAGRAM = "instagram"
STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_SKIPPED = "skipped"
STATUS_ERROR = "error"


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def site_origin() -> str:
    return _env("SITE_ORIGIN", DEFAULT_SITE_ORIGIN).rstrip("/")


def _now_iso() -> str:
    try:
        return datetime.now(ZoneInfo("America/Sao_Paulo")).replace(microsecond=0).isoformat()
    except Exception:
        return datetime.now().replace(microsecond=0).isoformat()


def _clean(text: object, *, max_len: int | None = None) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if max_len is not None and len(value) > max_len:
        return value[: max_len - 1].rstrip() + "…"
    return value


def _hashtags_for_tag(tag: str) -> list[str]:
    base = [
        "#ClarezaCapital",
        "#MercadoFinanceiro",
        "#Economia",
        "#Investimentos",
        "#Financas",
    ]
    by_tag = {
        "Cripto": ["#Cripto", "#Bitcoin"],
        "Economia": ["#EconomiaBR", "#Macroeconomia"],
        "Dólar": ["#Dolar", "#Cambio"],
        "Ações": ["#Acoes", "#Bolsa"],
        "Juros": ["#Selic", "#Juros"],
        "Inflação": ["#IPCA", "#Inflacao"],
        "Imóveis": ["#Imoveis", "#CreditoImobiliario"],
        "Fintech": ["#Fintech", "#BancosDigitais"],
        "Commodities": ["#Commodities", "#Agronegocio"],
        "Política Econômica": ["#PoliticaEconomica", "#Brasil"],
    }
    extra = by_tag.get(tag, ["#Analise", "#Noticias"])
    # Mantém 5–7 tags no total (padrão LinkedIn).
    merged: list[str] = []
    for item in base[:3] + extra + base[3:]:
        if item not in merged:
            merged.append(item)
        if len(merged) >= 7:
            break
    return merged


def article_url(news_id: int) -> str:
    return f"{site_origin()}/noticia/{int(news_id)}"


def absolute_image_url(imagem_url: object) -> str | None:
    """URL pública da capa (Instagram exige imagem acessível via HTTPS)."""
    raw = _clean(imagem_url)
    if not raw:
        return None
    if raw.startswith("https://"):
        return raw
    if raw.startswith("http://"):
        # Meta Graph exige HTTPS.
        return "https://" + raw[len("http://") :]
    origin = site_origin()
    if raw.startswith("/"):
        return f"{origin}{raw}"
    return f"{origin}/{raw.lstrip('/')}"


def build_linkedin_post(
    *,
    titulo: str,
    resumo: str,
    tag: str,
    url: str,
) -> str:
    """Texto pronto para LinkedIn (padrão Punk Code / Clareza Capital)."""
    title = _clean(titulo, max_len=120)
    blurb = _clean(resumo, max_len=280)
    if not blurb:
        blurb = (
            f"Análise objetiva da {BRAND_NAME} sobre {tag.lower()} "
            "com contexto de mercado e impacto prático para o leitor."
        )
    tags = _hashtags_for_tag(tag)

    lines = [
        f"**{title}**",
        "",
        (
            f"A {BRAND_NAME} publica uma leitura clara sobre {tag.lower()}, "
            "cruzando o cenário do dia com indicadores e orientação prática."
        ),
        "",
        blurb,
        "",
        (
            "O objetivo é transformar ruído de manchete em contexto: "
            "o que mudou, por que importa e o que observar a seguir."
        ),
        "",
        "O que você encontra:",
        f"• Análise editorial em português sobre {tag.lower()}",
        "• Contexto macro e impacto no bolso do leitor",
        "• Leitura objetiva, sem jargão desnecessário",
        "",
        f"Acesse: {url}",
        f"Saiba mais: {site_origin()}",
        f"Contato: {BRAND_CONTACT}",
        "",
        " ".join(tags),
    ]
    return "\n".join(lines).strip() + "\n"


def build_instagram_caption(
    *,
    titulo: str,
    resumo: str,
    tag: str,
    url: str,
) -> str:
    """Legenda pronta para Instagram (adaptada do padrão LinkedIn).

    Instagram não usa markdown; o gancho fica na 1ª linha e o link
    aparece no texto (perfil Business costuma usar link na bio).
    """
    title = _clean(titulo, max_len=100)
    blurb = _clean(resumo, max_len=220)
    if not blurb:
        blurb = (
            f"Leitura clara da {BRAND_NAME} sobre {tag.lower()} "
            "com contexto e impacto prático."
        )
    tags = _hashtags_for_tag(tag)

    lines = [
        title,
        "",
        (
            f"A {BRAND_NAME} resume o que importa em {tag.lower()}: "
            "contexto, impacto e próximos sinais a observar."
        ),
        "",
        blurb,
        "",
        "O que você encontra:",
        f"• Análise objetiva sobre {tag.lower()}",
        "• Contexto de mercado sem enrolação",
        "• Link completo no site (bio / story)",
        "",
        f"Acesse: {url}",
        f"Saiba mais: {site_origin()}",
        f"Contato: {BRAND_CONTACT}",
        "",
        " ".join(tags),
    ]
    caption = "\n".join(lines).strip()
    # Limite prático de legenda do Instagram.
    if len(caption) > 2100:
        caption = caption[:2097].rstrip() + "…"
    return caption + "\n"


def instagram_config_status() -> dict[str, Any]:
    token = _env("INSTAGRAM_ACCESS_TOKEN") or _env("META_ACCESS_TOKEN")
    account_id = _env("INSTAGRAM_BUSINESS_ACCOUNT_ID") or _env("INSTAGRAM_ACCOUNT_ID")
    version = _env("INSTAGRAM_GRAPH_API_VERSION", "v24.0")
    return {
        "configured": bool(token and account_id),
        "has_access_token": bool(token),
        "has_account_id": bool(account_id),
        "graph_api_version": version,
        "account_id_preview": (account_id[:6] + "…") if account_id else "",
    }


def is_instagram_publish_configured() -> bool:
    return bool(instagram_config_status()["configured"])


def publish_instagram_photo(
    *,
    image_url: str,
    caption: str,
) -> dict[str, Any]:
    """Publica foto no Instagram via Content Publishing API (Meta Graph)."""
    status = instagram_config_status()
    if not status["configured"]:
        return {
            "ok": False,
            "not_configured": True,
            "error": "INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_BUSINESS_ACCOUNT_ID nao configurados",
        }

    token = _env("INSTAGRAM_ACCESS_TOKEN") or _env("META_ACCESS_TOKEN")
    account_id = _env("INSTAGRAM_BUSINESS_ACCOUNT_ID") or _env("INSTAGRAM_ACCOUNT_ID")
    version = status["graph_api_version"]
    base = f"https://graph.facebook.com/{version}/{account_id}"

    try:
        create = requests.post(
            f"{base}/media",
            data={
                "image_url": image_url,
                "caption": caption,
                "access_token": token,
            },
            timeout=45,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": f"Falha de rede ao criar container: {exc}"[:300]}

    if create.status_code >= 400:
        return {
            "ok": False,
            "error": f"Instagram create media HTTP {create.status_code}",
            "body": create.text[:500],
            "status_code": create.status_code,
        }

    creation_id = (create.json() or {}).get("id")
    if not creation_id:
        return {"ok": False, "error": "Resposta sem creation_id", "body": create.text[:500]}

    # Aguarda container ficar pronto (FINISHED) antes de publicar.
    for _ in range(12):
        try:
            st = requests.get(
                f"https://graph.facebook.com/{version}/{creation_id}",
                params={
                    "fields": "status_code,status",
                    "access_token": token,
                },
                timeout=30,
            )
            payload = st.json() if st.status_code < 400 else {}
            code = str(payload.get("status_code") or "").upper()
            if code in ("FINISHED", "PUBLISHED"):
                break
            if code in ("ERROR", "EXPIRED"):
                return {
                    "ok": False,
                    "error": f"Container Instagram status={code}",
                    "body": str(payload)[:500],
                    "creation_id": creation_id,
                }
        except requests.RequestException:
            pass
        time.sleep(2)

    try:
        publish = requests.post(
            f"{base}/media_publish",
            data={
                "creation_id": creation_id,
                "access_token": token,
            },
            timeout=45,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": f"Falha de rede ao publicar: {exc}"[:300],
            "creation_id": creation_id,
        }

    if publish.status_code >= 400:
        return {
            "ok": False,
            "error": f"Instagram publish HTTP {publish.status_code}",
            "body": publish.text[:500],
            "status_code": publish.status_code,
            "creation_id": creation_id,
        }

    media_id = (publish.json() or {}).get("id")
    return {
        "ok": True,
        "provider": "instagram_graph",
        "creation_id": creation_id,
        "media_id": media_id,
    }


def _already_posted(client, news_id: int, channel: str) -> bool:
    try:
        result = client.execute(
            """
            SELECT 1 FROM social_posts
            WHERE news_id = ? AND channel = ? AND status = ?
            LIMIT 1
            """,
            [news_id, channel, STATUS_PUBLISHED],
        )
        return bool(result.rows)
    except Exception:
        return False


def _has_draft(client, news_id: int, channel: str) -> bool:
    try:
        result = client.execute(
            """
            SELECT 1 FROM social_posts
            WHERE news_id = ? AND channel = ?
            LIMIT 1
            """,
            [news_id, channel],
        )
        return bool(result.rows)
    except Exception:
        return False


def _upsert_social_post(
    client,
    *,
    news_id: int,
    channel: str,
    caption: str,
    status: str,
    image_url: str | None = None,
    external_id: str | None = None,
    error: str | None = None,
) -> None:
    now = _now_iso()
    client.execute(
        """
        INSERT INTO social_posts (
            news_id, channel, caption, image_url, status, external_id, error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(news_id, channel) DO UPDATE SET
            caption = excluded.caption,
            image_url = excluded.image_url,
            status = excluded.status,
            external_id = excluded.external_id,
            error = excluded.error,
            updated_at = excluded.updated_at
        """,
        [
            news_id,
            channel,
            caption,
            image_url or "",
            status,
            external_id or "",
            error or "",
            now,
            now,
        ],
    )


def fetch_social_candidates(
    client,
    *,
    max_items: int = SOCIAL_MAX_PER_RUN,
    min_priority: int = SOCIAL_MIN_PRIORITY,
    lookback_hours: int = SOCIAL_LOOKBACK_HOURS,
    news_id: int | None = None,
) -> list[dict[str, Any]]:
    """Seleciona matérias candidatas a publicação social."""
    import core

    if news_id is not None:
        result = client.execute(
            """
            SELECT id, titulo, resumo, tag,
                   COALESCE(home_priority, 0) AS prio,
                   COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao,
                   imagem_url
            FROM news
            WHERE id = ?
            LIMIT 1
            """,
            [news_id],
        )
        rows = result.rows or []
    else:
        limit = max(20, max_items * 10)
        result = client.execute(
            """
            SELECT id, titulo, resumo, tag,
                   COALESCE(home_priority, 0) AS prio,
                   COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao,
                   imagem_url
            FROM news
            WHERE COALESCE(home_priority, 0) >= ?
              AND LENGTH(COALESCE(resumo, '')) >= 120
            ORDER BY COALESCE(home_priority, 0) DESC, id DESC
            LIMIT ?
            """,
            [min_priority, limit],
        )
        rows = result.rows or []

    cutoff = time.time() - max(1, lookback_hours) * 3600
    items: list[dict[str, Any]] = []
    for row in rows:
        nid = int(row[0])
        titulo = _clean(row[1])
        if not titulo:
            continue
        if news_id is None:
            prio = int(row[4] or 0)
            if prio < min_priority:
                continue
            published = core.parse_article_datetime(row[5] if len(row) > 5 else None)
            if published is not None and published.timestamp() < cutoff:
                continue
        items.append(
            {
                "id": nid,
                "titulo": titulo,
                "resumo": _clean(row[2]),
                "tag": _clean(row[3]) or "Economia",
                "priority": int(row[4] or 0),
                "imagem_url": _clean(row[6]) if len(row) > 6 else "",
                "url": article_url(nid),
            }
        )
        if news_id is None and len(items) >= max(1, max_items):
            break
    return items


def process_social_publish(
    client,
    *,
    news_id: int | None = None,
    channels: list[str] | None = None,
    publish_instagram: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Gera drafts LinkedIn/Instagram e publica no Instagram quando configurado."""
    wanted = channels or [CHANNEL_LINKEDIN, CHANNEL_INSTAGRAM]
    wanted = [c.strip().lower() for c in wanted if c and c.strip()]
    candidates = fetch_social_candidates(client, news_id=news_id)
    if not candidates:
        return {
            "ok": True,
            "skipped": True,
            "reason": "sem_candidatos",
            "items": [],
            "instagram_config": instagram_config_status(),
        }

    results: list[dict[str, Any]] = []
    for article in candidates:
        nid = int(article["id"])
        entry: dict[str, Any] = {
            "news_id": nid,
            "titulo": article["titulo"],
            "url": article["url"],
            "channels": {},
        }
        image = absolute_image_url(article.get("imagem_url"))

        if CHANNEL_LINKEDIN in wanted:
            if not force and _already_posted(client, nid, CHANNEL_LINKEDIN):
                entry["channels"][CHANNEL_LINKEDIN] = {
                    "status": STATUS_SKIPPED,
                    "reason": "ja_publicado",
                }
            elif not force and _has_draft(client, nid, CHANNEL_LINKEDIN):
                entry["channels"][CHANNEL_LINKEDIN] = {
                    "status": STATUS_SKIPPED,
                    "reason": "draft_existente",
                }
            else:
                caption = build_linkedin_post(
                    titulo=article["titulo"],
                    resumo=article["resumo"],
                    tag=article["tag"],
                    url=article["url"],
                )
                _upsert_social_post(
                    client,
                    news_id=nid,
                    channel=CHANNEL_LINKEDIN,
                    caption=caption,
                    status=STATUS_DRAFT,
                    image_url=image,
                )
                entry["channels"][CHANNEL_LINKEDIN] = {
                    "status": STATUS_DRAFT,
                    "caption": caption,
                    "note": "Texto pronto para copiar e colar no LinkedIn",
                }

        if CHANNEL_INSTAGRAM in wanted:
            if not force and _already_posted(client, nid, CHANNEL_INSTAGRAM):
                entry["channels"][CHANNEL_INSTAGRAM] = {
                    "status": STATUS_SKIPPED,
                    "reason": "ja_publicado",
                }
            else:
                caption = build_instagram_caption(
                    titulo=article["titulo"],
                    resumo=article["resumo"],
                    tag=article["tag"],
                    url=article["url"],
                )
                channel_result: dict[str, Any] = {
                    "status": STATUS_DRAFT,
                    "caption": caption,
                    "image_url": image,
                }

                if publish_instagram and is_instagram_publish_configured():
                    if not image or not image.startswith("https://"):
                        channel_result.update(
                            {
                                "status": STATUS_ERROR,
                                "error": "imagem_url HTTPS obrigatoria para publicar no Instagram",
                            }
                        )
                        _upsert_social_post(
                            client,
                            news_id=nid,
                            channel=CHANNEL_INSTAGRAM,
                            caption=caption,
                            status=STATUS_ERROR,
                            image_url=image,
                            error=channel_result["error"],
                        )
                    else:
                        published = publish_instagram_photo(
                            image_url=image,
                            caption=caption,
                        )
                        if published.get("ok"):
                            media_id = str(published.get("media_id") or "")
                            _upsert_social_post(
                                client,
                                news_id=nid,
                                channel=CHANNEL_INSTAGRAM,
                                caption=caption,
                                status=STATUS_PUBLISHED,
                                image_url=image,
                                external_id=media_id,
                            )
                            channel_result.update(
                                {
                                    "status": STATUS_PUBLISHED,
                                    "media_id": media_id,
                                    "creation_id": published.get("creation_id"),
                                }
                            )
                        else:
                            err = str(published.get("error") or "falha_publicacao")
                            _upsert_social_post(
                                client,
                                news_id=nid,
                                channel=CHANNEL_INSTAGRAM,
                                caption=caption,
                                status=STATUS_ERROR,
                                image_url=image,
                                error=err,
                            )
                            channel_result.update(
                                {
                                    "status": STATUS_ERROR,
                                    "error": err,
                                    "body": published.get("body"),
                                }
                            )
                else:
                    _upsert_social_post(
                        client,
                        news_id=nid,
                        channel=CHANNEL_INSTAGRAM,
                        caption=caption,
                        status=STATUS_DRAFT,
                        image_url=image,
                    )
                    if not is_instagram_publish_configured():
                        channel_result["note"] = (
                            "Draft salvo. Configure INSTAGRAM_ACCESS_TOKEN e "
                            "INSTAGRAM_BUSINESS_ACCOUNT_ID para publicar automaticamente."
                        )
                    else:
                        channel_result["note"] = "Draft salvo (publish_instagram=false)."

                entry["channels"][CHANNEL_INSTAGRAM] = channel_result

        results.append(entry)

    return {
        "ok": True,
        "skipped": False,
        "count": len(results),
        "items": results,
        "instagram_config": instagram_config_status(),
    }


def social_posts_summary(payload: dict[str, Any]) -> str:
    """Resumo curto para logs/cron."""
    if payload.get("skipped"):
        return f"social_publish skipped: {payload.get('reason')}"
    parts = []
    for item in payload.get("items") or []:
        ch = item.get("channels") or {}
        li = (ch.get(CHANNEL_LINKEDIN) or {}).get("status", "-")
        ig = (ch.get(CHANNEL_INSTAGRAM) or {}).get("status", "-")
        parts.append(f"#{item.get('news_id')}:li={li}/ig={ig}")
    return "social_publish " + (", ".join(parts) if parts else "vazio")
