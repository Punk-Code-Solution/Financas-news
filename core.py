from google import genai
from google.genai import types
import feedparser
import os
import base64
import ssl
from bs4 import BeautifulSoup
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from dotenv import load_dotenv
import requests

from db import get_db, get_editorial_context

load_dotenv()

# Cache em memória para não bloquear cada pageview com APIs externas.
_MARKET_CACHE: dict[str, tuple[float, Any]] = {}
_MARKET_CACHE_LOCK = threading.Lock()
_HTTP_TIMEOUT = float(os.getenv("MARKET_HTTP_TIMEOUT", "3"))
_CACHE_TTL_SNAPSHOT = int(os.getenv("MARKET_CACHE_TTL", "300"))  # 5 min
_CACHE_TTL_HISTORICAL = int(os.getenv("MARKET_HIST_CACHE_TTL", "900"))  # 15 min


def _cache_get(key: str):
    with _MARKET_CACHE_LOCK:
        item = _MARKET_CACHE.get(key)
        if not item:
            return None
        expires_at, value = item
        if time.time() >= expires_at:
            return None
        return value


def _cache_set(key: str, value: Any, ttl: int) -> Any:
    with _MARKET_CACHE_LOCK:
        _MARKET_CACHE[key] = (time.time() + ttl, value)
    return value


def _cache_get_stale(key: str):
    """Retorna valor mesmo expirado (fallback rápido)."""
    with _MARKET_CACHE_LOCK:
        item = _MARKET_CACHE.get(key)
        return item[1] if item else None


def _http_get_json(url: str, timeout: float | None = None) -> Any | None:
    try:
        res = requests.get(url, headers=HEADERS, timeout=timeout or _HTTP_TIMEOUT)
        if res.status_code == 200:
            return res.json()
    except Exception:
        return None
    return None


VALID_TAGS = [
    "Cripto",
    "Economia",
    "Dólar",
    "Ações",
    "Juros",
    "Inflação",
    "Imóveis",
    "Fintech",
    "Commodities",
    "Política Econômica",
]

DEFAULT_GEMINI_MODELOS = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]

_exhausted_models: set[str] = set()
_exhausted_image_models: set[str] = set()


def _configure_ssl_certs() -> None:
    try:
        import certifi

        bundle = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    except ImportError:
        pass


def _create_genai_client():
    _configure_ssl_certs()
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    http_options = None
    if os.getenv("GEMINI_SSL_VERIFY", "true").lower() in ("0", "false", "no"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        http_options = types.HttpOptions(
            client_args={"verify": ctx},
            async_client_args={"verify": ctx},
        )

    return genai.Client(api_key=api_key.strip(), http_options=http_options)


if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
    print("ERRO CRITICO: Chave API nao encontrada no .env")
    client = None
else:
    client = _create_genai_client()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

RSS_FEEDS = [
    {
        "url": "https://livecoins.com.br/feed/",
        "fonte": "Livecoins",
        "tag_hint": "Cripto",
    },
    {
        "url": "https://g1.globo.com/dynamo/economia/rss2.xml",
        "fonte": "G1 Economia",
        "tag_hint": "Economia",
    },
    {
        "url": "https://www.infomoney.com.br/feed/",
        "fonte": "InfoMoney",
        "tag_hint": "Economia",
    },
    {
        "url": "https://br.investing.com/rss/news.rss",
        "fonte": "Investing.com Brasil",
        "tag_hint": "Ações",
    },
    {
        "url": "https://exame.com/feed/",
        "fonte": "Exame",
        "tag_hint": "Economia",
    },
    {
        "url": "https://www.moneytimes.com.br/feed/",
        "fonte": "Money Times",
        "tag_hint": "Ações",
    },
    {
        "url": "https://neofeed.com.br/feed/",
        "fonte": "NeoFeed",
        "tag_hint": "Fintech",
    },
    {
        "url": "https://valor.globo.com/financas/rss.xml",
        "fonte": "Valor Econômico",
        "tag_hint": "Economia",
    },
    {
        "url": "https://www.infomoney.com.br/temas/mercado-imobiliario/feed/",
        "fonte": "InfoMoney Imóveis",
        "tag_hint": "Imóveis",
    },
    {
        "url": "https://br.investing.com/rss/news_301.rss",
        "fonte": "Investing Commodities",
        "tag_hint": "Commodities",
    },
    {
        "url": "https://g1.globo.com/dynamo/politica/rss2.xml",
        "fonte": "G1 Política",
        "tag_hint": "Política Econômica",
    },
    {
        "url": "https://www.infomoney.com.br/temas/inflacao/feed/",
        "fonte": "InfoMoney Inflação",
        "tag_hint": "Inflação",
    },
    {
        "url": "https://www.infomoney.com.br/temas/juros/feed/",
        "fonte": "InfoMoney Juros",
        "tag_hint": "Juros",
    },
    {
        "url": "https://br.investing.com/rss/news_25.rss",
        "fonte": "Investing Forex",
        "tag_hint": "Dólar",
    },
]

BCB_SERIES = {
    "selic_meta": 432,
    "ipca_12m": 13522,
    "dolar_comercial": 1,
}

AWESOME_HISTORICAL = {
    "Dólar (USD/BRL)": "USD-BRL",
    "Bitcoin (BTC/BRL)": "BTC-BRL",
    "Euro (EUR/BRL)": "EUR-BRL",
}

BCB_HISTORICAL_LABELS = {
    "selic_meta": "Selic meta (% a.a.)",
    "ipca_12m": "IPCA 12 meses (%)",
    "dolar_comercial": "Dólar comercial (R$/US$)",
}


def clean_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator=" ").strip()


def _format_pct(value):
    try:
        pct = float(value)
        return f"+{pct:.2f}%" if pct >= 0 else f"{pct:.2f}%"
    except (TypeError, ValueError):
        return "n/d"


def _format_brl(value):
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def fetch_market_snapshot() -> dict[str, Any]:
    """Cotações em tempo real via AwesomeAPI (cache 5 min)."""
    cached = _cache_get("market_snapshot")
    if cached is not None:
        return cached

    snapshot: dict[str, Any] = {"coletado_em": datetime.now().strftime("%d/%m/%Y %H:%M")}
    data = _http_get_json(
        "https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL",
        timeout=_HTTP_TIMEOUT,
    )
    if isinstance(data, dict):
        for key, label in [
            ("USDBRL", "Dólar (USD/BRL)"),
            ("EURBRL", "Euro (EUR/BRL)"),
            ("BTCBRL", "Bitcoin (BTC/BRL)"),
        ]:
            if key in data:
                item = data[key]
                snapshot[label] = {
                    "cotacao": _format_brl(item.get("bid")),
                    "variacao_24h": _format_pct(item.get("pctChange")),
                    "maxima": _format_brl(item.get("high")),
                    "minima": _format_brl(item.get("low")),
                }
    elif not any(k for k in snapshot if k != "coletado_em"):
        stale = _cache_get_stale("market_snapshot")
        if stale:
            return stale

    return _cache_set("market_snapshot", snapshot, _CACHE_TTL_SNAPSHOT)


def fetch_bcb_snapshot() -> dict[str, dict[str, Any]]:
    """Indicadores macro do Banco Central (cache 5 min, requests em paralelo)."""
    cached = _cache_get("bcb_snapshot")
    if cached is not None:
        return cached

    labels = {
        "selic_meta": "Selic meta (% a.a.)",
        "ipca_12m": "IPCA acumulado 12 meses (%)",
        "dolar_comercial": "Dólar comercial (R$/US$)",
    }
    snapshot: dict[str, dict[str, Any]] = {}

    def _one(key: str, series_id: int):
        url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_id}/dados/ultimos/1?formato=json"
        dados = _http_get_json(url, timeout=_HTTP_TIMEOUT)
        if isinstance(dados, list) and dados:
            return labels[key], {
                "valor": dados[0].get("valor"),
                "data": dados[0].get("data"),
            }
        return None

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_one, key, sid) for key, sid in BCB_SERIES.items()]
        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception:
                continue
            if result:
                label, payload = result
                snapshot[label] = payload

    if not snapshot:
        stale = _cache_get_stale("bcb_snapshot")
        if stale:
            return stale

    return _cache_set("bcb_snapshot", snapshot, _CACHE_TTL_SNAPSHOT)


def fetch_bcb_historical(days: int = 90) -> dict[str, Any]:
    """Séries históricas BCB para gráficos de linha (paralelo + cache)."""
    cache_key = f"bcb_hist_{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    series: dict[str, Any] = {}

    def _one(key: str, series_id: int):
        label = BCB_HISTORICAL_LABELS[key]
        url = (
            f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_id}"
            f"/dados/ultimos/{days}?formato=json"
        )
        dados = _http_get_json(url, timeout=_HTTP_TIMEOUT)
        if not isinstance(dados, list) or not dados:
            return None
        return label, {
            "labels": [d.get("data", "") for d in dados],
            "values": [float(str(d.get("valor", "0")).replace(",", ".")) for d in dados],
            "periodo_dias": days,
            "fonte": "BCB",
        }

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_one, key, sid) for key, sid in BCB_SERIES.items()]
        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception:
                continue
            if result:
                label, payload = result
                series[label] = payload

    if not series:
        stale = _cache_get_stale(cache_key)
        if stale:
            return stale

    return _cache_set(cache_key, series, _CACHE_TTL_HISTORICAL)


def fetch_awesome_historical(days: int = 30) -> dict[str, Any]:
    """Séries históricas AwesomeAPI (paralelo + cache)."""
    cache_key = f"awesome_hist_{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    series: dict[str, Any] = {}

    def _one(label: str, pair: str):
        url = f"https://economia.awesomeapi.com.br/json/daily/{pair}/{days}"
        dados = _http_get_json(url, timeout=_HTTP_TIMEOUT)
        if not isinstance(dados, list) or not dados:
            return None
        dados = list(reversed(dados))
        return label, {
            "labels": [
                datetime.fromtimestamp(int(d.get("timestamp", 0))).strftime("%d/%m")
                for d in dados
                if d.get("timestamp")
            ],
            "values": [float(d.get("bid", 0)) for d in dados],
            "periodo_dias": days,
            "fonte": "AwesomeAPI",
        }

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_one, label, pair) for label, pair in AWESOME_HISTORICAL.items()]
        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception:
                continue
            if result:
                label, payload = result
                series[label] = payload

    if not series:
        stale = _cache_get_stale(cache_key)
        if stale:
            return stale

    return _cache_set(cache_key, series, _CACHE_TTL_HISTORICAL)


def fetch_market_historical(days_short: int = 30, days_long: int = 90) -> dict[str, Any]:
    """Agrega histórico BCB + AwesomeAPI (cache 15 min)."""
    cache_key = f"market_hist_{days_short}_{days_long}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    short: dict[str, Any] = {}
    long_: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_a30 = pool.submit(fetch_awesome_historical, days_short)
        f_b30 = pool.submit(fetch_bcb_historical, min(days_short, 30))
        f_a90 = pool.submit(fetch_awesome_historical, days_long)
        f_b90 = pool.submit(fetch_bcb_historical, days_long)
        try:
            short = {**f_a30.result(), **f_b30.result()}
        except Exception:
            short = {}
        try:
            long_ = {**f_a90.result(), **f_b90.result()}
        except Exception:
            long_ = {}

    payload = {
        "30d": short,
        "90d": long_,
        "coletado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    if not short and not long_:
        stale = _cache_get_stale(cache_key)
        if stale:
            return stale
    return _cache_set(cache_key, payload, _CACHE_TTL_HISTORICAL)


def fetch_sparkline_data(blocking: bool = False) -> dict[str, list[float]]:
    """Mini séries (7 dias) para sparklines na home.

    Por padrão não bloqueia o request: devolve cache (ou {}) e atualiza em background.
    """
    cache_key = "sparklines_7d"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    stale = _cache_get_stale(cache_key) or {}

    def _refresh():
        sparklines: dict[str, list[float]] = {}
        for label, pair in list(AWESOME_HISTORICAL.items())[:2]:
            dados = _http_get_json(
                f"https://economia.awesomeapi.com.br/json/daily/{pair}/7",
                timeout=_HTTP_TIMEOUT,
            )
            if isinstance(dados, list):
                dados = list(reversed(dados))
                sparklines[label] = [float(d.get("bid", 0)) for d in dados if d.get("bid")]
        if sparklines:
            _cache_set(cache_key, sparklines, _CACHE_TTL_SNAPSHOT)

    if blocking:
        _refresh()
        return _cache_get(cache_key) or stale

    threading.Thread(target=_refresh, daemon=True).start()
    return stale


def format_data_context(market, bcb, db_context):
    """Monta bloco de dados para injetar no prompt da IA."""
    lines = [
        "=== DADOS DE MERCADO EM TEMPO REAL (cite números específicos na análise) ===",
        f"Coletado em: {market.get('coletado_em', 'agora')}",
    ]
    for key, val in market.items():
        if key in ("coletado_em", "erro_cotacoes"):
            continue
        if isinstance(val, dict):
            lines.append(
                f"- {key}: {val.get('cotacao')} (var. 24h: {val.get('variacao_24h')}, "
                f"máx: {val.get('maxima')}, mín: {val.get('minima')})"
            )

    if bcb:
        lines.append("\n=== INDICADORES MACROECONÔMICOS (Banco Central do Brasil) ===")
        for key, val in bcb.items():
            lines.append(f"- {key}: {val.get('valor')} (ref. {val.get('data')})")

    lines.append("\n=== ACERVO EDITORIAL DO PORTAL (cruze tendências, evite repetir) ===")
    lines.append(db_context)

    return "\n".join(lines)


def get_gemini_modelos() -> list[str]:
    raw = os.getenv("GEMINI_MODELOS", "")
    if raw.strip():
        return [m.strip() for m in raw.split(",") if m.strip()]
    return DEFAULT_GEMINI_MODELOS.copy()


def _is_daily_quota_error(exc: Exception) -> bool:
    msg = str(exc)
    return "PerDay" in msg or "PerDayPerProjectPerModel" in msg


def _is_rpm_quota_error(exc: Exception) -> bool:
    msg = str(exc)
    return "PerMinute" in msg or "PerMinutePerProjectPerModel" in msg


def _extract_retry_delay(exc: Exception) -> float:
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc), re.IGNORECASE)
    if match:
        return float(match.group(1))
    return 35.0


def get_article_images_dir() -> Path:
    base = os.getenv("ARTICLE_IMAGES_DIR", "static/images/articles")
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_gemini_image_models() -> list[str]:
    raw = os.getenv("GEMINI_IMAGE_MODELOS", "")
    if raw.strip():
        return [m.strip() for m in raw.split(",") if m.strip()]
    return [
        "gemini-2.5-flash-image",
        "gemini-2.0-flash-preview-image-generation",
        "imagen-4.0-fast-generate-001",
    ]


TAG_IMAGE_VISUALS = {
    "Cripto": "Bitcoin, cryptocurrency coins, blockchain network, digital finance",
    "Economia": "macroeconomy, GDP charts, Brazilian economy skyline, business district",
    "Dólar": "US dollar bills, currency exchange, forex trading screens",
    "Ações": "stock market tickers, trading floor, rising charts, B3 style visuals",
    "Juros": "interest rates, central bank building, yield curve charts",
    "Inflação": "shopping prices, inflation chart, consumer goods, price tags",
    "Imóveis": "modern apartments, real estate, city buildings, property keys",
    "Fintech": "mobile banking app, digital payments, fintech innovation",
    "Commodities": "oil barrels, gold bars, agricultural fields, commodity trading",
    "Política Econômica": "government building, fiscal policy, parliament, budget documents",
}


def _article_image_slug(link: str, article_id: int | None = None) -> str:
    key = link.strip() if link else f"article-{article_id or 0}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _build_image_prompt(title: str, tag: str, resumo: str = "") -> str:
    visual = TAG_IMAGE_VISUALS.get(tag, "financial markets, economy, professional journalism")
    summary = (resumo or "").strip()[:220]
    return (
        f"Create a high-quality editorial cover photo for a Brazilian financial news website. "
        f"Headline topic: {title[:140]}. "
        f"Category: {tag}. "
        f"Article context: {summary}. "
        f"Visual elements: {visual}. "
        f"Style: cinematic, professional photojournalism or polished digital illustration, "
        f"dramatic lighting, rich colors, 16:9 composition. "
        f"Strict rules: no text, no letters, no logos, no watermarks, no brand names, no faces."
    )


def _normalize_image_bytes(data: bytes | str) -> bytes:
    if isinstance(data, str):
        return base64.b64decode(data)
    return data


def _save_image_bytes(data: bytes, mime_type: str, slug: str) -> str | None:
    ext = "png" if "png" in (mime_type or "") else "jpg"
    filename = f"{slug}.{ext}"
    filepath = get_article_images_dir() / filename
    filepath.write_bytes(data)
    return f"/media/articles/{filename}"


def _extract_image_from_response(response) -> tuple[bytes, str] | None:
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                return _normalize_image_bytes(inline.data), getattr(inline, "mime_type", "image/jpeg")

    generated = getattr(response, "generated_images", None) or []
    for item in generated:
        image = getattr(item, "image", None)
        if image and getattr(image, "image_bytes", None):
            return _normalize_image_bytes(image.image_bytes), getattr(image, "mime_type", "image/jpeg")
    return None


def _is_image_quota_error(exc: Exception) -> bool:
    msg = str(exc)
    return "PerDay" in msg or "Quota" in msg or "RESOURCE_EXHAUSTED" in msg


def generate_article_image(
    title: str,
    tag: str,
    link: str,
    resumo: str = "",
    article_id: int | None = None,
) -> str | None:
    """Gera capa editorial; retorna URL pública ou None em caso de falha."""
    if not client:
        return None

    slug = _article_image_slug(link, article_id)
    images_dir = get_article_images_dir()
    for existing in images_dir.glob(f"{slug}.*"):
        return f"/media/articles/{existing.name}"

    prompt = _build_image_prompt(title, tag, resumo)
    modelos = [m for m in get_gemini_image_models() if m not in _exhausted_image_models]
    if not modelos:
        print("   [img] Todos os modelos de imagem esgotaram a cota nesta execucao.")
        return None

    for model in modelos:
        try:
            print(f"   [img] Gerando imagem ({model})...")
            if model.startswith("imagen"):
                response = client.models.generate_images(
                    model=model,
                    prompt=prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        output_mime_type="image/jpeg",
                        aspect_ratio="16:9",
                    ),
                )
            else:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                        image_config=types.ImageConfig(aspect_ratio="16:9"),
                    ),
                )

            extracted = _extract_image_from_response(response)
            if extracted:
                data, mime_type = extracted
                url = _save_image_bytes(data, mime_type, slug)
                print(f"   [img] Imagem salva: {url}")
                return url
        except Exception as e:
            if _is_image_quota_error(e):
                _exhausted_image_models.add(model)
            print(f"   [img] Falha ({model}): {e}")
            continue

    print("   [img] Imagem nao gerada — artigo seguira sem capa.")
    return None


def backfill_missing_images(limit: int = 10) -> dict[str, Any]:
    """Gera capas para artigos que ainda nao possuem imagem_url."""
    client_db = get_db()
    result = client_db.execute(
        """
        SELECT id, titulo, tag, link, resumo
        FROM news
        WHERE imagem_url IS NULL OR imagem_url = ''
        ORDER BY id DESC
        LIMIT ?
        """,
        [limit],
    )
    rows = result.rows

    updated: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for row in rows:
        article_id, titulo, tag, link, resumo = row[0], row[1], row[2], row[3] or "", row[4] or ""
        imagem_url = generate_article_image(titulo, tag, link, resumo, article_id=article_id)
        if imagem_url:
            client_db.execute(
                "UPDATE news SET imagem_url = ? WHERE id = ?",
                [imagem_url, article_id],
            )
            updated.append({"id": article_id, "imagem_url": imagem_url})
        else:
            failed.append({"id": article_id, "titulo": titulo[:80]})

    client_db.close()
    return {
        "processed": len(rows),
        "updated": len(updated),
        "failed": len(failed),
        "items": updated,
        "errors": failed,
    }


def generate_content_with_fallback(prompt: str) -> str | None:
    """Tenta modelos em ordem; troca em cota diária; espera só em limite por minuto."""
    if not client:
        return None

    modelos = [m for m in get_gemini_modelos() if m not in _exhausted_models]
    if not modelos:
        print("   ❌ Todos os modelos Gemini esgotaram a cota diária nesta execução.")
        return None

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.7,
    )

    for model in modelos:
        rpm_retries = 0
        max_rpm_retries = 3

        while rpm_retries <= max_rpm_retries:
            try:
                print(f"   🤖 Modelo: {model}")
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                if not response.text:
                    return None
                return response.text

            except Exception as e:
                if _is_daily_quota_error(e):
                    print(f"   ⚠️ Cota diária esgotada em {model} — próximo modelo.")
                    _exhausted_models.add(model)
                    break

                if _is_rpm_quota_error(e) and rpm_retries < max_rpm_retries:
                    delay = _extract_retry_delay(e)
                    print(f"   ⏳ Limite por minuto em {model}, aguardando {delay:.0f}s...")
                    time.sleep(delay)
                    rpm_retries += 1
                    continue

                print(f"   ❌ Erro na IA ({model}): {e}")
                break

    return None


def process_news_with_ai(title, content, fonte, tag_hint, market_context):
    if not client:
        return None

    print(f"   🤖 Enviando para IA: {title[:40]}...")

    tags_list = ", ".join(VALID_TAGS)
    prompt = f"""
Você é o editor-chefe de análise do portal "Finanças News" (financas-news.net.br), especializado em economia brasileira, mercado de capitais e criptoativos.

Sua missão é produzir uma ANÁLISE EDITORIAL ORIGINAL de alto valor — não um resumo, não uma paráfrase da notícia fonte. O Google e leitores exigem conteúdo com dados concretos, contexto histórico e utilidade prática.

## REGRAS INEGOCIÁVEIS
- PROIBIDO: resumir a notícia, usar "segundo a matéria", "o texto relata", "conforme publicado".
- OBRIGATÓRIO: citar pelo menos 3 números reais dos DADOS DE MERCADO fornecidos abaixo (cotações, variações, Selic, IPCA).
- OBRIGATÓRIO: conectar o fato da notícia com o cenário macro brasileiro (inflação, juros, câmbio, bolsa).
- OBRIGATÓRIO: cruzar com o ACERVO EDITORIAL — mencione se há tendência (ex.: "terceira notícia negativa sobre X esta semana").
- OBRIGATÓRIO: dar orientação prática para o leitor comum (investidor iniciante ou chefe de família).
- Mínimo de 500 palavras no campo resumo_simples.
- Tom: jornalístico, analítico, acessível. Você domina tecnologia e finanças, com visão de livre mercado e empreendedorismo.

## NOTÍCIA FONTE
Fonte RSS: {fonte}
Categoria sugerida: {tag_hint}
Título original: {title}
Conteúdo base (use como ponto de partida, não como texto a reescrever):
{content[:2500]}

## DADOS PARA CRUZAMENTO (use estes números na análise)
{market_context}

## ESTRUTURA DO ARTIGO (campo resumo_simples — 6 parágrafos separados por \\n\\n)
1. **Abertura**: O fato em uma frase forte + por que importa AGORA para o brasileiro.
2. **Contexto com dados**: Selic, IPCA, câmbio ou cripto — números reais dos dados fornecidos.
3. **Cruzamento de fontes**: Relacione com tendências do acervo editorial do portal.
4. **Análise aprofundada**: Causas, atores do mercado, riscos e oportunidades. Opinião embasada.
5. **Cenários**: O que pode acontecer em 30, 90 e 180 dias (seja específico).
6. **Guia prático**: 2-3 ações concretas para o leitor (diversificar, cautela, oportunidade, etc.).

Retorne APENAS JSON válido (sem ```json):
{{
    "titulo_viral": "Título jornalístico, informativo e específico (máx. 90 caracteres). Evite clickbait vazio.",
    "resumo_simples": "Artigo completo de 6 parágrafos com \\n\\n entre eles. Mínimo 500 palavras.",
    "contexto_mercado": "Box de 3-4 frases com os principais números citados (cotações, Selic, IPCA) formatados para leitura rápida.",
    "impacto_bolso": "3 frases diretas: impacto no bolso, na poupança/investimentos e no custo de vida.",
    "tag": "UMA de: {tags_list}",
    "sentimento": "UM de: Positivo, Negativo, Neutro",
    "dados_citados": ["lista dos dados numéricos que você efetivamente usou no texto"],
    "pontos_chave": [
        {{
            "titulo": "Nome curto do ponto (ex: Selic 14,25%)",
            "descricao": "Uma frase explicando por que esse dado importa para o leitor",
            "categoria": "UMA de: {tags_list} — categoria para link interno"
        }}
    ],
    "timeline": [
        {{"data": "Mar/2024 ou data aproximada", "evento": "Marco histórico relevante para contextualizar a notícia"}}
    ],
    "cenarios": [
        {{"prazo": "30 dias", "probabilidade": "alta|média|baixa", "descricao": "Cenário específico e mensurável"}},
        {{"prazo": "90 dias", "probabilidade": "alta|média|baixa", "descricao": "Cenário específico"}},
        {{"prazo": "180 dias", "probabilidade": "alta|média|baixa", "descricao": "Cenário específico"}}
    ],
    "perfil_investidor": {{
        "conservador": "Orientação específica para perfil conservador (2-3 frases)",
        "moderado": "Orientação para perfil moderado (2-3 frases)",
        "arrojado": "Orientação para perfil arrojado (2-3 frases)"
    }},
    "glossario": [
        {{"termo": "Termo técnico usado no texto", "definicao": "Definição acessível em 1-2 frases"}}
    ],
    "referencias_internas": [
        {{"trecho": "trecho exato de 3-8 palavras do resumo para linkar", "titulo_busca": "palavras-chave para encontrar matéria relacionada no acervo"}}
    ],
    "faq": [
        {{"pergunta": "Pergunta que o leitor iniciante faria", "resposta": "Resposta objetiva em 2-4 frases"}},
        {{"pergunta": "Segunda pergunta relevante", "resposta": "Resposta objetiva"}},
        {{"pergunta": "Terceira pergunta relevante", "resposta": "Resposta objetiva"}}
    ],
    "urgencia": "UM de: Alta, Média, Baixa — quão urgente é agir sobre esta notícia",
    "publico_alvo": "UM de: Iniciante, Intermediário, Avançado, Geral",
    "horizonte": "UM de: Curto prazo, Médio prazo, Longo prazo",
    "confianca_dados": "UM de: Alta, Média, Baixa — confiança nos dados citados",
    "tabela_comparativa": {{
        "titulo": "Título da comparação (ex: Renda fixa vs variável neste cenário)",
        "colunas": ["Opção A", "Opção B", "Opção C"],
        "linhas": [
            {{"rotulo": "Risco", "valores": ["Baixo", "Médio", "Alto"]}},
            {{"rotulo": "Retorno esperado", "valores": ["~12% a.a.", "~15% a.a.", "~25% a.a."]}}
        ]
    }}
}}
"""

    try:
        text = generate_content_with_fallback(prompt)
        if not text:
            return None
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"   ❌ Erro ao processar resposta da IA: {e}")
        return None


def _build_dados_mercado_payload(market, bcb, ai_data, historico=None) -> str:
    extra_keys = (
        "timeline", "cenarios", "perfil_investidor", "glossario", "faq",
        "urgencia", "publico_alvo", "horizonte", "confianca_dados",
        "tabela_comparativa", "referencias_internas",
    )
    payload = {
        "cotacoes": market,
        "bcb": bcb,
        "dados_citados": ai_data.get("dados_citados", []),
        "pontos_chave": ai_data.get("pontos_chave", []),
        "historico": historico or fetch_market_historical(),
    }
    for key in extra_keys:
        if ai_data.get(key):
            payload[key] = ai_data[key]
    return json.dumps(payload, ensure_ascii=False)


def refresh_article_market_data(article_id: int, add_update_note: bool = True) -> dict[str, Any] | None:
    """Atualiza cotações e indicadores de um artigo antigo."""
    client = get_db()
    result = client.execute(
        "SELECT id, titulo, tag, dados_mercado, contexto_editorial, versao_analise FROM news WHERE id = ?",
        [article_id],
    )
    if not result.rows:
        client.close()
        return None

    row = result.rows[0]
    noticia_id, titulo, tag, raw_dados, contexto_editorial, versao = row[0], row[1], row[2], row[3], row[4], row[5]
    versao = int(versao or 1)

    old_dados: dict[str, Any] = {}
    if raw_dados:
        try:
            old_dados = json.loads(raw_dados)
        except json.JSONDecodeError:
            pass

    market = fetch_market_snapshot()
    bcb = fetch_bcb_snapshot()
    historico = fetch_market_historical()
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    atualizacao = None
    if add_update_note and old_dados.get("cotacoes"):
        old_cot = old_dados["cotacoes"]
        changes = []
        for label, info in market.items():
            if label in ("coletado_em", "erro_cotacoes") or not isinstance(info, dict):
                continue
            old_info = old_cot.get(label, {})
            if isinstance(old_info, dict) and old_info.get("cotacao") != info.get("cotacao"):
                changes.append(f"{label}: {old_info.get('cotacao', 'n/d')} → {info.get('cotacao', 'n/d')}")
        if changes:
            atualizacao = (
                f"Atualização em {agora}: desde a publicação original, "
                f"as cotações mudaram — {'; '.join(changes[:4])}."
            )

    new_dados = dict(old_dados)
    new_dados["cotacoes"] = market
    new_dados["bcb"] = bcb
    new_dados["historico"] = historico
    if atualizacao:
        new_dados["atualizacao"] = atualizacao

    contexto_lines = []
    for key, val in market.items():
        if key in ("coletado_em", "erro_cotacoes") or not isinstance(val, dict):
            continue
        contexto_lines.append(f"{key}: {val.get('cotacao')} ({val.get('variacao_24h')} em 24h)")
    for key, val in bcb.items():
        if isinstance(val, dict):
            contexto_lines.append(f"{key}: {val.get('valor')} (ref. {val.get('data')})")
    novo_contexto = contexto_editorial or ""
    if contexto_lines:
        novo_contexto = " | ".join(contexto_lines[:6])

    client.execute(
        """
        UPDATE news
        SET dados_mercado = ?, contexto_editorial = ?, updated_at = ?, versao_analise = ?
        WHERE id = ?
        """,
        [json.dumps(new_dados, ensure_ascii=False), novo_contexto, agora, versao + 1, noticia_id],
    )
    client.close()
    return {
        "id": noticia_id,
        "titulo": titulo,
        "versao_analise": versao + 1,
        "atualizacao": atualizacao,
        "coletado_em": agora,
    }


def refresh_stale_articles(limit: int = 10, min_days_old: int = 7) -> dict[str, Any]:
    """Atualiza artigos mais antigos que min_days_old dias."""
    client = get_db()
    result = client.execute(
        """
        SELECT id FROM news
        ORDER BY id DESC
        LIMIT ?
        """,
        [limit * 3],
    )
    ids = [r[0] for r in result.rows]
    client.close()

    updated = []
    for aid in ids[:limit]:
        res = refresh_article_market_data(aid)
        if res:
            updated.append(res)
    return {"processed": len(updated), "items": updated}


def extract_entry_content(entry) -> str:
    summary = entry.get("summary")
    if summary:
        return str(summary)
    content_list = entry.get("content") or []
    if not content_list:
        return ""
    first_item = content_list[0]
    value = first_item.get("value") if hasattr(first_item, "get") else getattr(first_item, "value", "")
    return str(value or "")


def fetch_and_process(max_per_feed=2):
    noticias_processadas = []
    _exhausted_models.clear()
    print(f"\n--- Iniciando Varredura: {datetime.now()} ---")
    print(f"   🧠 Modelos Gemini: {', '.join(get_gemini_modelos())}")

    market = fetch_market_snapshot()
    bcb = fetch_bcb_snapshot()
    historico = fetch_market_historical()
    print(f"   📊 Dados de mercado coletados: {len(market)} cotações, {len(bcb)} indicadores BCB")

    for feed_config in RSS_FEEDS:
        feed_url = feed_config["url"]
        fonte = feed_config["fonte"]
        tag_hint = feed_config["tag_hint"]

        print(f"🔍 Acessando: {fonte} ({feed_url})")
        try:
            response = requests.get(feed_url, headers=HEADERS, timeout=15)
            if response.status_code != 200:
                print(f"   ❌ Erro HTTP {response.status_code}")
                continue

            feed = feedparser.parse(response.content)
            if not feed.entries:
                print("   ⚠️ Feed vazio.")
                continue

            db_context = get_editorial_context(tag_hint=tag_hint)
            data_context = format_data_context(market, bcb, db_context)

            for entry in feed.entries[:max_per_feed]:
                print(f"   📄 Encontrada: {entry.title[:60]}...")

                raw_content = extract_entry_content(entry)
                clean_text = clean_html(raw_content)

                if len(clean_text) < 80:
                    print("   ⚠️ Texto muito curto, pulando.")
                    continue

                ai_data = process_news_with_ai(entry.title, clean_text, fonte, tag_hint, data_context)

                if ai_data is None and len(_exhausted_models) >= len(get_gemini_modelos()):
                    print("   🛑 Cota diária esgotada em todos os modelos — interrompendo varredura.")
                    return noticias_processadas

                if ai_data:
                    tag = ai_data.get("tag", tag_hint)
                    if tag not in VALID_TAGS:
                        tag = tag_hint if tag_hint in VALID_TAGS else "Economia"
                        ai_data["tag"] = tag

                    entry_link = str(getattr(entry, "link", "") or "")
                    imagem_url = generate_article_image(
                        ai_data.get("titulo_viral", entry.title),
                        tag,
                        entry_link,
                        ai_data.get("resumo_simples", ""),
                    )

                    published = datetime.now().strftime("%d/%m/%Y %H:%M")
                    news_item = {
                        "original_link": entry_link,
                        "fonte": fonte,
                        "published_at": published,
                        "imagem_url": imagem_url,
                        "dados_mercado": _build_dados_mercado_payload(market, bcb, ai_data, historico),
                        "contexto_editorial": ai_data.get("contexto_mercado", ""),
                        "versao_analise": 1,
                        **ai_data,
                    }
                    noticias_processadas.append(news_item)
                    print("   ✅ Processado com sucesso!")

        except Exception as e:
            print(f"   ❌ Erro Crítico: {e}")

    return noticias_processadas


if __name__ == "__main__":
    print("🚀 Modo de Teste Manual Iniciado...")
    resultado = fetch_and_process(max_per_feed=1)
    print(f"\n📊 Total processado: {len(resultado)}")
    if resultado:
        print("🎉 SUCESSO! JSON gerado:")
        print(json.dumps(resultado[0], indent=2, ensure_ascii=False))