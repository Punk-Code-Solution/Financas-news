from google import genai
from google.genai import types
import feedparser
import os
import base64
import ssl
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from dotenv import load_dotenv
import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from db import existing_news_links, get_db, get_editorial_context

_ = load_dotenv()

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
    timeout = timeout or _HTTP_TIMEOUT
    _configure_ssl_certs()
    try:
        res = requests.get(url, headers=HEADERS, timeout=timeout)
        if res.status_code == 200:
            return res.json()
        return None
    except requests.exceptions.SSLError:
        try:
            # Alguns ambientes Windows não reconhecem a cadeia local mesmo com
            # certifi. O fallback é restrito a esta chamada.
            urllib3.disable_warnings(InsecureRequestWarning)
            res = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
            if res.status_code == 200:
                return res.json()
        except Exception:
            return None
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
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash",
    "gemini-3.5-flash",
]

# Gemini Image (Nano Banana). Imagen 4 removido — 404 "no longer available to new users".
DEFAULT_GEMINI_IMAGE_MODELOS = [
    "gemini-3.1-flash-lite-image",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image",
]

# OpenAI Images: ao esgotar RPD de um modelo, tenta o próximo.
# Contas novas costumam ter só GPT Image (DALL-E pode retornar "does not exist").
DEFAULT_OPENAI_IMAGE_MODELOS = [
    "gpt-image-2",
    "gpt-image-1.5",
    "gpt-image-1",
    "gpt-image-1-mini",
    "dall-e-3",
    "dall-e-2",
]

# Hugging Face Inference Providers (text-to-image).
DEFAULT_HF_IMAGE_MODELOS = [
    "black-forest-labs/FLUX.1-schnell",
]

_exhausted_models_by_key: dict[str, set[str]] = {}
# Cota de imagem por chave API (id curto → modelos esgotados nesta varredura).
_exhausted_image_models_by_key: dict[str, set[str]] = {}
# Modelos de imagem removidos permanentemente (404/descontinuados) até reiniciar.
_unavailable_image_models: set[str] = set()
# OpenAI: cota diária/RPM esgotada nesta execução; modelos sem acesso/404.
_exhausted_openai_image_models: set[str] = set()
_unavailable_openai_image_models: set[str] = set()
# Hugging Face: modelos esgotados / indisponíveis nesta execução.
_exhausted_hf_image_models: set[str] = set()
_unavailable_hf_image_models: set[str] = set()
# Cache de clients Gemini por fingerprint da chave.
_genai_clients_by_key: dict[str, Any] = {}
_genai_clients_lock = threading.Lock()
# Rate limit OpenAI Images (projeto com 1 imagem/minuto).
_openai_image_lock = threading.Lock()
_openai_last_image_at: float = 0.0


def _configure_ssl_certs() -> None:
    try:
        import certifi

        bundle = certifi.where()
        _ = os.environ.setdefault("SSL_CERT_FILE", bundle)
        _ = os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    except ImportError:
        pass


def _ssl_verify_enabled() -> bool:
    """False apenas se SSL_VERIFY / OPENAI_SSL_VERIFY / GEMINI_SSL_VERIFY = false."""
    for var in ("SSL_VERIFY", "OPENAI_SSL_VERIFY", "GEMINI_SSL_VERIFY"):
        raw = os.getenv(var)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip().lower() not in ("0", "false", "no")
    return True


def _gemini_http_options():
    if _ssl_verify_enabled():
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return types.HttpOptions(
        client_args={"verify": ctx},
        async_client_args={"verify": ctx},
    )


def _create_openai_client(api_key: str):
    """Client OpenAI; em Windows com MITM/antivirus, use GEMINI_SSL_VERIFY=false."""
    from openai import OpenAI

    if _ssl_verify_enabled():
        return OpenAI(api_key=api_key)
    import httpx

    print("   [img/openai] SSL verify desativado (GEMINI_SSL_VERIFY/SSL_VERIFY=false).")
    return OpenAI(api_key=api_key, http_client=httpx.Client(verify=False, timeout=120.0))


def get_gemini_api_keys() -> list[str]:
    """Chaves Gemini em ordem de prioridade (1 → 2 → 3 → lista).

    Variáveis aceitas:
    - GOOGLE_API_KEY / GEMINI_API_KEY (chave 1)
    - GOOGLE_API_KEY_2 / GEMINI_API_KEY_2 (chave 2)
    - GOOGLE_API_KEY_3 / GEMINI_API_KEY_3 (chave 3)
    - GOOGLE_API_KEYS / GEMINI_API_KEYS (lista separada por vírgula)
    """
    keys: list[str] = []
    seen: set[str] = set()

    def _add(raw: str | None) -> None:
        if not raw:
            return
        for part in str(raw).split(","):
            key = part.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            keys.append(key)

    _add(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    _add(os.getenv("GOOGLE_API_KEY_2") or os.getenv("GEMINI_API_KEY_2"))
    _add(os.getenv("GOOGLE_API_KEY_3") or os.getenv("GEMINI_API_KEY_3"))
    _add(os.getenv("GOOGLE_API_KEYS") or os.getenv("GEMINI_API_KEYS"))
    return keys


def get_gemini_api_keys_for_images() -> list[str]:
    """Para capas: prioriza chaves 2 e 3 (Imagen) e deixa a 1 por último."""
    keys = get_gemini_api_keys()
    if len(keys) <= 1:
        return keys
    return keys[1:] + keys[:1]


def get_robot_max_per_feed() -> int:
    try:
        return max(1, min(int(os.getenv("ROBOT_MAX_PER_FEED", "3")), 8))
    except ValueError:
        return 3


def get_robot_max_articles() -> int:
    try:
        return max(1, min(int(os.getenv("ROBOT_MAX_ARTICLES", "36")), 80))
    except ValueError:
        return 36


def get_robot_own_analyses_count() -> int:
    """Mínimo de análises próprias (a partir do acervo) a gerar por dia."""
    try:
        return max(0, min(int(os.getenv("ROBOT_OWN_ANALYSES", "3")), 10))
    except ValueError:
        return 3


OWN_ANALYSIS_LINK_PREFIX = "internal://analise/"
OWN_ANALYSIS_FONTE = "Finanças News"


def _api_key_id(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:8]


def _create_genai_client(api_key: str | None = None):
    _configure_ssl_certs()
    key = (api_key or "").strip()
    if not key:
        keys = get_gemini_api_keys()
        if not keys:
            return None
        key = keys[0]

    return genai.Client(api_key=key, http_options=_gemini_http_options())


def get_genai_client(api_key: str | None = None):
    """Reutiliza client por chave (evita recriar a cada imagem)."""
    keys = get_gemini_api_keys()
    if not keys and not api_key:
        return None
    key = (api_key or keys[0]).strip()
    key_id = _api_key_id(key)
    cached = _genai_clients_by_key.get(key_id)
    if cached is not None:
        return cached
    with _genai_clients_lock:
        cached = _genai_clients_by_key.get(key_id)
        if cached is not None:
            return cached
        created = _create_genai_client(key)
        if created is not None:
            _genai_clients_by_key[key_id] = created
        return created


def _reset_image_quota_state() -> None:
    _exhausted_image_models_by_key.clear()
    _unavailable_image_models.clear()
    _exhausted_openai_image_models.clear()
    _unavailable_openai_image_models.clear()
    _exhausted_hf_image_models.clear()
    _unavailable_hf_image_models.clear()


_gemini_keys = get_gemini_api_keys()
if not _gemini_keys:
    print("ERRO CRITICO: Chave API nao encontrada no .env")
    client = None
else:
    client = get_genai_client(_gemini_keys[0])
    if len(_gemini_keys) > 1:
        print(f"Gemini: {len(_gemini_keys)} chaves API carregadas (fallback de cota ativo).")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

RSS_FEEDS = [
    # --- Brasil ---
    {"url": "https://g1.globo.com/dynamo/economia/rss2.xml", "fonte": "G1 Economia", "tag_hint": "Economia"},
    {"url": "https://g1.globo.com/dynamo/politica/rss2.xml", "fonte": "G1 Política", "tag_hint": "Política Econômica"},
    {"url": "https://pox.globo.com/rss/valor", "fonte": "Valor Econômico", "tag_hint": "Economia"},
    {"url": "https://www.infomoney.com.br/feed/", "fonte": "InfoMoney", "tag_hint": "Economia"},
    {"url": "https://www.infomoney.com.br/mercados/feed/", "fonte": "InfoMoney Mercados", "tag_hint": "Ações"},
    {"url": "https://www.infomoney.com.br/economia/feed/", "fonte": "InfoMoney Economia", "tag_hint": "Inflação"},
    {"url": "https://www.infomoney.com.br/onde-investir/feed/", "fonte": "InfoMoney Onde Investir", "tag_hint": "Juros"},
    {"url": "https://exame.com/feed/", "fonte": "Exame", "tag_hint": "Economia"},
    {"url": "https://www.moneytimes.com.br/feed/", "fonte": "Money Times", "tag_hint": "Ações"},
    {"url": "https://neofeed.com.br/feed/", "fonte": "NeoFeed", "tag_hint": "Fintech"},
    {"url": "https://br.investing.com/rss/news.rss", "fonte": "Investing.com Brasil", "tag_hint": "Ações"},
    {"url": "https://br.investing.com/rss/news_301.rss", "fonte": "Investing Commodities", "tag_hint": "Commodities"},
    {"url": "https://br.investing.com/rss/news_25.rss", "fonte": "Investing Forex", "tag_hint": "Dólar"},
    {"url": "https://www.cnnbrasil.com.br/economia/feed/", "fonte": "CNN Brasil Economia", "tag_hint": "Economia"},
    {"url": "https://www.estadao.com.br/rss/economia.xml", "fonte": "Estadão Economia", "tag_hint": "Economia"},
    {"url": "https://feeds.folha.uol.com.br/mercado/rss091.xml", "fonte": "Folha Mercado", "tag_hint": "Economia"},
    {"url": "https://rss.uol.com.br/feed/economia.xml", "fonte": "UOL Economia", "tag_hint": "Economia"},
    {"url": "https://www.poder360.com.br/feed/", "fonte": "Poder360", "tag_hint": "Política Econômica"},
    {"url": "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml", "fonte": "Agência Brasil", "tag_hint": "Política Econômica"},
    {"url": "https://livecoins.com.br/feed/", "fonte": "Livecoins", "tag_hint": "Cripto"},
    {"url": "https://cointelegraph.com/rss/tag/brazil", "fonte": "Cointelegraph Brasil", "tag_hint": "Cripto"},
    # --- Internacional ---
    {"url": "https://feeds.bbci.co.uk/news/business/rss.xml", "fonte": "BBC Business", "tag_hint": "Economia"},
    {"url": "https://www.cnbc.com/id/10001147/device/rss/rss.html", "fonte": "CNBC", "tag_hint": "Economia"},
    {"url": "https://feeds.reuters.com/reuters/businessNews", "fonte": "Reuters Business", "tag_hint": "Economia"},
    {"url": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "fonte": "MarketWatch", "tag_hint": "Ações"},
    {"url": "https://finance.yahoo.com/news/rssindex", "fonte": "Yahoo Finance", "tag_hint": "Ações"},
    {"url": "https://www.theguardian.com/uk/business/rss", "fonte": "The Guardian Business", "tag_hint": "Economia"},
    {"url": "https://www.investing.com/rss/news.rss", "fonte": "Investing.com World", "tag_hint": "Ações"},
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "fonte": "CoinDesk", "tag_hint": "Cripto"},
    {"url": "https://cointelegraph.com/rss", "fonte": "Cointelegraph", "tag_hint": "Cripto"},
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


_REFRESHING_KEYS: set[str] = set()
_REFRESHING_LOCK = threading.Lock()


def _refresh_in_background(cache_key: str, refresh_fn) -> None:
    with _REFRESHING_LOCK:
        if cache_key in _REFRESHING_KEYS:
            return
        _REFRESHING_KEYS.add(cache_key)

    def _run():
        try:
            refresh_fn()
        except Exception:
            pass
        finally:
            with _REFRESHING_LOCK:
                _REFRESHING_KEYS.discard(cache_key)

    threading.Thread(target=_run, daemon=True).start()


def _load_market_snapshot() -> dict[str, Any]:
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


def fetch_market_snapshot(blocking: bool = True) -> dict[str, Any]:
    """Cotações em tempo real via AwesomeAPI (cache 5 min).

    Com blocking=False (páginas web): devolve cache/stale na hora e atualiza em background.
    """
    cached = _cache_get("market_snapshot")
    if cached is not None:
        return cached

    stale = _cache_get_stale("market_snapshot")
    if not blocking:
        _refresh_in_background("market_snapshot", _load_market_snapshot)
        return stale or {"coletado_em": datetime.now().strftime("%d/%m/%Y %H:%M")}

    return _load_market_snapshot()


def _load_bcb_snapshot() -> dict[str, dict[str, Any]]:
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


def fetch_bcb_snapshot(blocking: bool = True) -> dict[str, dict[str, Any]]:
    """Indicadores macro do Banco Central (cache 5 min, requests em paralelo)."""
    cached = _cache_get("bcb_snapshot")
    if cached is not None:
        return cached

    stale = _cache_get_stale("bcb_snapshot")
    if not blocking:
        _refresh_in_background("bcb_snapshot", _load_bcb_snapshot)
        return stale or {}

    return _load_bcb_snapshot()


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
            + f"/dados/ultimos/{days}?formato=json"
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


def warmup_market_caches() -> None:
    """Pré-aquece caches de mercado no startup para o 1º pageview não esperar rede."""
    try:
        _ = fetch_market_snapshot(blocking=True)
    except Exception:
        pass
    try:
        _ = fetch_bcb_snapshot(blocking=True)
    except Exception:
        pass
    try:
        _ = fetch_market_historical()
    except Exception:
        pass
    try:
        _ = fetch_sparkline_data(blocking=True)
    except Exception:
        pass


def parse_article_datetime(*candidates: object) -> datetime | None:
    """Converte datas do portal (BR ou ISO) para datetime."""
    formats = (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    )
    for raw in candidates:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        if text.endswith("Z"):
            text = text[:-1]
        # Descarta fração de segundos em ISO
        if "." in text and "T" in text:
            text = text.split(".", 1)[0]
        for fmt in formats:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def _has_market_payload(payload: object) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    return any(
        isinstance(v, dict) and k not in ("coletado_em", "erro_cotacoes", "referencia")
        for k, v in payload.items()
    )


def fetch_market_snapshot_as_of(as_of: datetime) -> dict[str, Any]:
    """Cotações próximas à data da análise (não usa 'hoje')."""
    day_key = as_of.strftime("%Y%m%d")
    cache_key = f"market_asof_{day_key}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    start = as_of - timedelta(days=7)
    snapshot: dict[str, Any] = {
        "coletado_em": as_of.strftime("%d/%m/%Y %H:%M"),
        "referencia": "histórico na data da análise",
    }

    pairs = [
        ("USD-BRL", "Dólar (USD/BRL)"),
        ("EUR-BRL", "Euro (EUR/BRL)"),
        ("BTC-BRL", "Bitcoin (BTC/BRL)"),
    ]

    def _one(pair: str, label: str):
        url = (
            f"https://economia.awesomeapi.com.br/json/daily/{pair}/"
            + f"?start_date={start.strftime('%Y%m%d')}&end_date={day_key}"
        )
        dados = _http_get_json(url, timeout=_HTTP_TIMEOUT)
        if not isinstance(dados, list) or not dados:
            return None
        # API costuma devolver do mais recente ao mais antigo
        item = dados[0]
        return label, {
            "cotacao": _format_brl(item.get("bid")),
            "variacao_24h": _format_pct(item.get("pctChange")),
            "maxima": _format_brl(item.get("high")),
            "minima": _format_brl(item.get("low")),
            "data_ref": datetime.fromtimestamp(int(item["timestamp"])).strftime("%d/%m/%Y")
            if item.get("timestamp")
            else as_of.strftime("%d/%m/%Y"),
        }

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_one, pair, label) for pair, label in pairs]
        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception:
                continue
            if result:
                label, payload = result
                snapshot[label] = payload

    if not _has_market_payload(snapshot):
        stale = _cache_get_stale(cache_key)
        if stale and _has_market_payload(stale):
            return stale
        return snapshot

    return _cache_set(cache_key, snapshot, _CACHE_TTL_HISTORICAL)


def fetch_bcb_snapshot_as_of(as_of: datetime) -> dict[str, dict[str, Any]]:
    """Indicadores BCB vigentes na data da análise."""
    day_key = as_of.strftime("%Y%m%d")
    cache_key = f"bcb_asof_{day_key}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    labels = {
        "selic_meta": "Selic meta (% a.a.)",
        "ipca_12m": "IPCA acumulado 12 meses (%)",
        "dolar_comercial": "Dólar comercial (R$/US$)",
    }
    start = as_of - timedelta(days=120)
    snapshot: dict[str, dict[str, Any]] = {}

    def _one(key: str, series_id: int):
        url = (
            f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_id}/dados"
            + f"?formato=json&dataInicial={start.strftime('%d/%m/%Y')}"
            + f"&dataFinal={as_of.strftime('%d/%m/%Y')}"
        )
        dados = _http_get_json(url, timeout=_HTTP_TIMEOUT)
        if not isinstance(dados, list) or not dados:
            return None
        last = dados[-1]
        return labels[key], {
            "valor": last.get("valor"),
            "data": last.get("data"),
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
                snapshot[label] = payload

    if not snapshot:
        stale = _cache_get_stale(cache_key)
        if stale:
            return stale
        return snapshot

    return _cache_set(cache_key, snapshot, _CACHE_TTL_HISTORICAL)


def fetch_market_historical_as_of(
    as_of: datetime,
    days_short: int = 30,
    days_long: int = 90,
    blocking: bool = True,
) -> dict[str, Any]:
    """Séries históricas terminando na data da análise."""
    day_key = as_of.strftime("%Y%m%d")
    cache_key = f"market_hist_asof_{day_key}_{days_short}_{days_long}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    stale = _cache_get_stale(cache_key) or {}

    def _awesome_range(days: int) -> dict[str, Any]:
        start = as_of - timedelta(days=days)
        series: dict[str, Any] = {}
        for label, pair in AWESOME_HISTORICAL.items():
            url = (
                f"https://economia.awesomeapi.com.br/json/daily/{pair}/"
                + f"?start_date={start.strftime('%Y%m%d')}&end_date={day_key}"
            )
            dados = _http_get_json(url, timeout=_HTTP_TIMEOUT)
            if not isinstance(dados, list) or not dados:
                continue
            dados = list(reversed(dados))
            series[label] = {
                "labels": [
                    datetime.fromtimestamp(int(d.get("timestamp", 0))).strftime("%d/%m")
                    for d in dados
                    if d.get("timestamp")
                ],
                "values": [float(d.get("bid", 0)) for d in dados if d.get("bid") is not None],
                "periodo_dias": days,
                "fonte": "AwesomeAPI",
                "ate": as_of.strftime("%d/%m/%Y"),
            }
        return series

    def _bcb_range(days: int) -> dict[str, Any]:
        start = as_of - timedelta(days=days)
        series: dict[str, Any] = {}
        for key, series_id in BCB_SERIES.items():
            label = BCB_HISTORICAL_LABELS[key]
            url = (
                f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_id}/dados"
                + f"?formato=json&dataInicial={start.strftime('%d/%m/%Y')}"
                + f"&dataFinal={as_of.strftime('%d/%m/%Y')}"
            )
            dados = _http_get_json(url, timeout=_HTTP_TIMEOUT)
            if not isinstance(dados, list) or not dados:
                continue
            series[label] = {
                "labels": [d.get("data", "")[:5] for d in dados],
                "values": [float(str(d.get("valor", "0")).replace(",", ".")) for d in dados],
                "periodo_dias": days,
                "fonte": "BCB",
                "ate": as_of.strftime("%d/%m/%Y"),
            }
        return series

    def _load() -> dict[str, Any]:
        short: dict[str, Any] = {}
        long_: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            f_a30 = pool.submit(_awesome_range, days_short)
            f_b30 = pool.submit(_bcb_range, min(days_short, 40))
            f_a90 = pool.submit(_awesome_range, days_long)
            f_b90 = pool.submit(_bcb_range, days_long)
            for fut, target in (
                (f_a30, short),
                (f_b30, short),
                (f_a90, long_),
                (f_b90, long_),
            ):
                try:
                    target.update(fut.result() or {})
                except Exception:
                    pass
        payload = {
            "30d": short,
            "90d": long_,
            "coletado_em": as_of.strftime("%d/%m/%Y %H:%M"),
            "referencia": f"séries até {as_of.strftime('%d/%m/%Y')}",
        }
        if short or long_:
            return _cache_set(cache_key, payload, _CACHE_TTL_HISTORICAL)
        return stale or payload

    if not blocking:
        if stale:
            _refresh_in_background(cache_key, _load)
            return stale
        # Sem cache: carrega de forma limitada (bloqueia pouco) para não ficar vazio.
        return _load()

    return _load()


def _snapshot_aligned_to_period(payload: object, as_of: datetime | None) -> bool:
    """True se o snapshot parece pertencer ao período da análise (não a 'hoje')."""
    if not _has_market_payload(payload):
        return False
    assert isinstance(payload, dict)
    if payload.get("referencia"):
        return True
    if as_of is None:
        # Sem data da análise: não confiar em snapshot sem marca histórica.
        return False
    coletado = parse_article_datetime(payload.get("coletado_em"))
    if not coletado:
        return False
    delta = (coletado.date() - as_of.date()).days
    return -5 <= delta <= 5


def _historico_aligned_to_period(hist: object, as_of: datetime | None) -> bool:
    if not isinstance(hist, dict) or not (hist.get("30d") or hist.get("90d")):
        return False
    if hist.get("referencia"):
        return True
    if as_of is None:
        return False
    coletado = parse_article_datetime(hist.get("coletado_em"))
    if not coletado:
        return False
    return abs((coletado.date() - as_of.date()).days) <= 5


def resolve_article_market_data(
    dados_mercado: dict[str, Any] | None,
    *,
    published_at: object = None,
    created_at: object = None,
    blocking_hist: bool = False,
) -> dict[str, Any]:
    """Garante cotacoes/bcb/historico do período da análise — nunca substitui por 'hoje'."""
    market_data = dict(dados_mercado or {})

    # Snapshot original preservado tem prioridade sobre refresh posterior.
    if _has_market_payload(market_data.get("cotacoes_publicacao")):
        market_data["cotacoes"] = market_data["cotacoes_publicacao"]
    if _has_market_payload(market_data.get("bcb_publicacao")):
        market_data["bcb"] = market_data["bcb_publicacao"]
    if _historico_aligned_to_period(market_data.get("historico_publicacao"), None):
        market_data["historico"] = market_data["historico_publicacao"]

    as_of = parse_article_datetime(published_at, created_at)

    needs_cot = not _snapshot_aligned_to_period(market_data.get("cotacoes"), as_of)
    needs_bcb = not _snapshot_aligned_to_period(market_data.get("bcb"), as_of)
    needs_hist = not _historico_aligned_to_period(market_data.get("historico"), as_of)

    if as_of and (needs_cot or needs_bcb or needs_hist):
        try:
            if needs_cot:
                market_data["cotacoes"] = fetch_market_snapshot_as_of(as_of)
            if needs_bcb:
                market_data["bcb"] = fetch_bcb_snapshot_as_of(as_of)
            if needs_hist:
                market_data["historico"] = fetch_market_historical_as_of(
                    as_of,
                    blocking=blocking_hist,
                )
        except Exception:
            pass
    elif needs_cot or needs_bcb or needs_hist:
        # Sem data da análise: não inventa cotações de hoje.
        if needs_cot:
            market_data["cotacoes"] = {}
        if needs_bcb:
            market_data["bcb"] = {}
        if needs_hist:
            market_data["historico"] = {}

    if as_of:
        market_data["periodo_analise"] = as_of.strftime("%d/%m/%Y")

    return market_data


def _fold_label(text: str) -> str:
    """Remove acentos para casar 'Dólar'/'dolar' e 'Inflação'/'inflacao'."""
    import unicodedata

    norm = unicodedata.normalize("NFD", str(text).lower())
    return "".join(c for c in norm if unicodedata.category(c) != "Mn")


def _series_delta(series: dict[str, Any] | None, approx_days: int) -> dict[str, Any] | None:
    """Compara último ponto da série com o valor ~N dias atrás."""
    if not isinstance(series, dict):
        return None
    values = series.get("values") or []
    labels = series.get("labels") or []
    if len(values) < 2:
        return None
    current = float(values[-1])
    # Séries diárias: recua N pontos; mensais (Selic/IPCA): usa ponto anterior se N curto.
    if len(values) > approx_days + 1:
        idx = len(values) - 1 - approx_days
    else:
        idx = max(0, len(values) - 2)
    past = float(values[idx])
    if past == 0:
        return None
    change = current - past
    pct = (change / abs(past)) * 100.0
    return {
        "valor_passado": past,
        "variacao": change,
        "variacao_pct": round(pct, 2),
        "data_passada": labels[idx] if idx < len(labels) else "",
        "positivo": change >= 0,
        "dias": approx_days,
    }


def _find_hist_series(historico: dict[str, Any], *name_hints: str) -> dict[str, Any] | None:
    """Localiza série no histórico 30d/90d por trechos do nome."""
    if not historico:
        return None
    hints = [_fold_label(h) for h in name_hints if h]
    for period in ("30d", "90d"):
        period_data = historico.get(period) or {}
        if not isinstance(period_data, dict):
            continue
        for name, series in period_data.items():
            name_l = _fold_label(name)
            if any(h in name_l for h in hints):
                return series if isinstance(series, dict) else None
    return None


def _format_delta_line(delta: dict[str, Any] | None, suffix: str = "") -> str:
    if not delta:
        return "n/d"
    pct = delta.get("variacao_pct")
    past = delta.get("valor_passado")
    data = delta.get("data_passada") or ""
    sign = "+ " if (pct or 0) >= 0 else ""
    past_txt = f"{past:.4g}".replace(".", ",") if isinstance(past, float) else str(past)
    bits = [f"{sign}{pct}% vs ~{delta.get('dias')}d", f"de {past_txt}{suffix}"]
    if data:
        bits.append(f"({data})")
    return " ".join(bits)


# Escolas analíticas para enriquecer o texto — paráfrase original; sem citações literais.
ANALYTICAL_LENSES: list[dict[str, Any]] = [
    {
        "id": "valor_margem",
        "label": "Valor e margem de segurança",
        "school": "Tradição Graham/Buffett",
        "tags": ("Economia", "Ações", "Juros", "Inflação", "Imóveis", "Fintech"),
        "keywords": ("ação", "bolsa", "empresa", "lucro", "dividendo", "valuation", "balanço"),
        "hint": (
            "Enquadre preço versus valor, proteção de capital e paciência. "
            "Evite perseguir retorno sem entender o risco de perda permanente."
        ),
    },
    {
        "id": "ciclos_credito",
        "label": "Ciclos de crédito e liquidez",
        "school": "Macro estrutural (Ray Dalio)",
        "tags": ("Economia", "Juros", "Política Econômica", "Dólar", "Inflação"),
        "keywords": ("juros", "dívida", "copom", "selic", "crédito", "liquidez", "fiscal", "spread"),
        "hint": (
            "Situar o fato no estágio do ciclo (expansão, aperto, desaceleração). "
            "Relacione política monetária, fluxo de capital e apetite a risco sem repetir só a Selic."
        ),
    },
    {
        "id": "risco_assimetrico",
        "label": "Risco assimétrico e ciclos de humor",
        "school": "Crédito/contrarian (Howard Marks)",
        "tags": ("Cripto", "Ações", "Commodities", "Fintech"),
        "keywords": ("rally", "crash", "euforia", "medo", "volatilidade", "bolha", "correção", "bear"),
        "hint": (
            "Mostre onde o mercado já precifica otimismo ou pessimismo. "
            "Destaque assimetria risco/retorno e o que invalidaria a tese."
        ),
    },
    {
        "id": "custo_disciplina",
        "label": "Disciplina de longo prazo e custos",
        "school": "Indexação e eficiência (John Bogle)",
        "tags": ("Economia", "Ações", "Fintech", "Inflação"),
        "keywords": ("etf", "fundo", "taxa", "diversific", "aposentadoria", "poupança", "carteira"),
        "hint": (
            "Priorize diversificação, custos, rebalanceamento e horizonte. "
            "Evite prometer timing perfeito; foque em processo repetível."
        ),
    },
]


def _macro_topic_relevance(title: str, content: str, tag_hint: str) -> dict[str, bool]:
    """Indica quais indicadores macro são centrais à matéria (evita forçar Selic em tudo)."""
    text = _fold_label(f"{title} {content[:1500]} {tag_hint}")
    return {
        "selic": any(
            k in text
            for k in ("selic", "copom", "juros", "taxa basica", "banco central", "credito", "di ")
        )
        or tag_hint in ("Juros", "Política Econômica"),
        "ipca": any(k in text for k in ("ipca", "inflacao", "precos", "custos", "cesta"))
        or tag_hint in ("Inflação", "Economia"),
        "dolar": any(k in text for k in ("dolar", "cambio", "usd", "eur", "forex", "real "))
        or tag_hint in ("Dólar", "Commodities", "Economia"),
    }


def _score_analysis_lens(lens: dict[str, Any], text_fold: str, tag_hint: str) -> int:
    score = 0
    if tag_hint in lens.get("tags", ()):
        score += 2
    for kw in lens.get("keywords", ()):
        if kw in text_fold:
            score += 3
    return score


def select_analysis_lenses(
    title: str,
    content: str,
    tag_hint: str,
    count: int = 2,
) -> list[dict[str, Any]]:
    """Escolhe lentes analíticas diversas para a matéria (sem repetir sempre a mesma dupla)."""
    text_fold = _fold_label(f"{title} {content[:1200]} {tag_hint}")
    ranked = sorted(
        ANALYTICAL_LENSES,
        key=lambda lens: _score_analysis_lens(lens, text_fold, tag_hint),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lens in ranked:
        if lens["id"] in seen:
            continue
        selected.append(lens)
        seen.add(lens["id"])
        if len(selected) >= count:
            break
    for lens in ANALYTICAL_LENSES:
        if len(selected) >= count:
            break
        if lens["id"] not in seen:
            selected.append(lens)
            seen.add(lens["id"])
    # Rotaciona a ordem por matéria para variar o ângulo dominante.
    if len(selected) > 1:
        pivot = sum(ord(c) for c in (title or "")[:48]) % len(selected)
        selected = selected[pivot:] + selected[:pivot]
    return selected[:count]


def _build_lens_prompt_block(lenses: list[dict[str, Any]]) -> str:
    lines = [
        "## LENTES ANALÍTICAS (incorpore 2 escolas — texto ORIGINAL)",
        "Use as ideias abaixo como enquadramento editorial. PROIBIDO: aspas atribuídas a pessoas, "
        "trechos de livros/discursos ou frases registradas. Pode mencionar a ESCOLA (ex.: "
        "'tradição do valor') sem reproduzir obra protegida.",
        "",
    ]
    for lens in lenses:
        lines.append(f"- **{lens['label']}** (referência escolar: {lens['school']})")
        lines.append(f"  {lens['hint']}")
    lines.extend(
        [
            "",
            "Inclua no JSON o campo `lentes_analiticas`: lista com 2 objetos "
            '`{"escola": "nome curto da escola", "aplicacao": "2-3 frases originais aplicando a matéria"}`.',
        ]
    )
    return "\n".join(lines)


def _build_macro_usage_rules(relevance: dict[str, bool], tag_hint: str) -> str:
    lines = [
        "## USO DOS DADOS MACRO (contextual — NÃO repetir Selic em toda matéria)",
        "- Use APENAS indicadores relevantes ao fato; o painel é referência, não checklist obrigatório.",
    ]
    if relevance.get("selic"):
        lines.append(
            "- Selic/juros: CENTRAIS nesta matéria — cite com valor e tendência 7d/30d quando disponível."
        )
    else:
        lines.append(
            "- Selic/juros: PERIFÉRICOS — no máximo 1 menção breve no box `contexto_mercado` "
            "(ou omita se não agregar). NÃO abra o artigo com Selic."
        )
    if relevance.get("ipca"):
        lines.append("- IPCA/inflação: relevante — use com número concreto.")
    else:
        lines.append("- IPCA: só cite se conectar naturalmente ao fato (evite clichê).")
    if relevance.get("dolar"):
        lines.append("- Câmbio: relevante — use dólar ou par correlato da tag.")
    else:
        lines.append("- Câmbio: cite só se o fato tiver vínculo direto com FX ou commodities.")
    lines.extend(
        [
            f"- Categoria {tag_hint}: priorize cotações e indicadores da tag antes do núcleo macro.",
            "- Em 6 parágrafos, use números concretos em pelo menos 4 — mas VARIE os indicadores "
            "(não repita Selic em todos).",
            "- Se o acervo recente já saturou Selic/juros, traga ângulo novo (setorial, fiscal, "
            "comportamental ou internacional).",
        ]
    )
    return "\n".join(lines)


def format_data_context(market, bcb, db_context, historico=None, tag_hint: str = "Economia"):
    """Monta bloco de dados para injetar no prompt da IA (painel fixo + tendência)."""
    hist = historico or {}
    lines = [
        "=== PAINEL MACRO DE REFERÊNCIA (use só indicadores relevantes à matéria) ===",
        f"Coletado em: {market.get('coletado_em', 'agora')}",
        f"Categoria da matéria: {tag_hint}",
    ]

    # Núcleo BCB
    if bcb:
        lines.append("\n--- Indicadores macro (BCB) ---")
        for key, val in bcb.items():
            if not isinstance(val, dict):
                continue
            label = str(key)
            hint = "selic" if "selic" in label.lower() else (
                "ipca" if "ipca" in label.lower() else (
                    "dolar" if "dolar" in label.lower() or "dólar" in label.lower() else label[:12]
                )
            )
            series = _find_hist_series(hist, hint, label)
            d7 = _series_delta(series, 7)
            d30 = _series_delta(series, 30)
            lines.append(
                f"- {label}: {val.get('valor')} (ref. {val.get('data')}) | "
                + f"tendência 7d: {_format_delta_line(d7)} | 30d: {_format_delta_line(d30)}"
            )

    # Cotações: dólar sempre + extras da tag
    tag_extras = {
        "Cripto": ["Bitcoin (BTC/BRL)"],
        "Ações": ["Bitcoin (BTC/BRL)", "Euro (EUR/BRL)"],
        "Commodities": ["Euro (EUR/BRL)", "Bitcoin (BTC/BRL)"],
        "Dólar": ["Euro (EUR/BRL)"],
        "Fintech": ["Bitcoin (BTC/BRL)"],
    }
    preferred_quotes = ["Dólar (USD/BRL)"] + tag_extras.get(tag_hint, ["Euro (EUR/BRL)"])[:1]
    lines.append("\n--- Cotações (AwesomeAPI) — use 1–2 relevantes à tag ---")
    for key in preferred_quotes:
        val = market.get(key)
        if not isinstance(val, dict):
            continue
        series = _find_hist_series(hist, key, key.split("(")[0].strip())
        d7 = _series_delta(series, 7)
        d30 = _series_delta(series, 30)
        lines.append(
            f"- {key}: {val.get('cotacao')} (var. 24h: {val.get('variacao_24h')}) | "
            + f"7d: {_format_delta_line(d7)} | 30d: {_format_delta_line(d30)}"
        )
    # Demais cotações disponíveis (contexto extra, sem obrigar)
    for key, val in market.items():
        if key in ("coletado_em", "erro_cotacoes") or key in preferred_quotes:
            continue
        if isinstance(val, dict):
            lines.append(
                f"- {key}: {val.get('cotacao')} (var. 24h: {val.get('variacao_24h')}) [opcional]"
            )

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


def _article_image_slug(link: str, article_id: int | None = None) -> str:
    key = link.strip() if link else f"article-{article_id or 0}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def get_gemini_image_models() -> list[str]:
    raw = os.getenv("GEMINI_IMAGE_MODELOS", "")
    if raw.strip():
        return [m.strip() for m in raw.split(",") if m.strip()]
    # Imagen 4 foi descontinuado — usar Nano Banana / Gemini Image (GA + fallbacks).
    return DEFAULT_GEMINI_IMAGE_MODELOS.copy()


TAG_IMAGE_VISUALS = {
    "Cripto": "digital finance infrastructure, trading screens, global fintech offices — not coin close-ups",
    "Economia": "macroeconomy, Brazilian business district, policy and growth visuals",
    "Dólar": "currency exchange desk, USD/BRL trading screens, forex floor",
    "Ações": "equity markets, ticker boards, institutional trading floor, B3-style atmosphere",
    "Juros": "central bank architecture, yield curves on screens, monetary policy mood",
    "Inflação": "supermarket prices, household budget pressure, cost-of-living atmosphere",
    "Imóveis": "modern apartments, city real estate, property keys and skyline",
    "Fintech": "mobile payments, banking app UI glow, digital wallet infrastructure",
    "Commodities": "oil, gold, agriculture logistics — industrial commodity scenes",
    "Política Econômica": "government buildings, fiscal documents, parliament atmosphere",
}

# Sinais no título/resumo → cena concreta (evita capa genérica de “moedas de Bitcoin”).
_IMAGE_SCENE_CUES: list[tuple[tuple[str, ...], str]] = [
    (
        ("nova zelândia", "new zealand", "auckland", "wellington"),
        "New Zealand financial district / Auckland waterfront skyline at dusk, Pacific atmosphere, "
        + "modern glass offices of a licensed financial-services firm expanding into Oceania",
    ),
    (
        ("bitmex",),
        "abandoned crypto derivatives trading floor, dark empty desks, offline monitors, "
        + "sense of an exchange shutting down — crisis, not celebration",
    ),
    (
        ("colapso", "falência", "fechamento", "fim da exchange", "shut down", "collapse"),
        "financial crisis mood: empty trading desks, red warning lights on dark screens, "
        + "deserted exchange office — no triumphant coin photos",
    ),
    (
        ("compliance", "vigilância", "regulação", "regulament", "kyc", "aml"),
        "regulatory compliance desk: KYC documents, surveillance monitor wall, "
        + "institutional audit room with soft cool lighting — professional, not speculative",
    ),
    (
        ("binance",),
        "global crypto exchange operations hub with world-map screens and compliance analysts "
        + "at desks — institutional security vibe, not gold coins",
    ),
    (
        ("bitget",),
        "fintech firm expanding abroad: passport and boarding-pass motifs beside "
        + "glowing trading terminals, international growth energy",
    ),
    (
        ("japão", "japonês", "japonesa", "tokyo", "tóquio", "repatria", "iene", "yen"),
        "Tokyo skyline and financial towers, abstract yen capital-flow visuals, "
        + "global risk and repatriation mood — macro, not crypto coins",
    ),
    (
        ("selic", "copom", "banco central"),
        "Brazilian Central Bank building mood, interest-rate decision atmosphere, formal macro policy",
    ),
    (
        ("ipca", "inflação", "preço dos alimentos"),
        "Brazilian supermarket aisle with price tags and cost-of-living tension",
    ),
    (
        ("dólar", "cambio", "câmbio", "usd/brl"),
        "currency exchange counter, USD and BRL notes blurred, forex screens",
    ),
    (
        ("petróleo", "óleo", "brent", "wti"),
        "oil barrels and energy logistics, industrial commodity scene",
    ),
    (
        ("ouro", "gold"),
        "gold bars in a vault under dramatic light — only if the story is about gold",
    ),
    (
        ("imóvel", "imóveis", "apartamento", "aluguel"),
        "modern Brazilian apartment buildings and real-estate keys",
    ),
    (
        ("bitcoin", "btc"),
        "Bitcoin as secondary motif only if essential — prefer network nodes or institutional custody vault "
        + "over piles of physical coins",
    ),
]


def _first_paragraph(text: str, max_chars: int = 320) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    para = re.split(r"\n\s*\n", raw, maxsplit=1)[0].strip()
    para = re.sub(r"\s+ ", " ", para)
    return para[:max_chars]


def _extract_image_scene_cues(title: str, resumo: str, tag: str) -> str:
    blob = f"{title}\n{resumo}".lower()
    hits: list[str] = []
    for keys, scene in _IMAGE_SCENE_CUES:
        if any(k in blob for k in keys):
            hits.append(scene)
        if len(hits) >= 2:
            break
    if hits:
        return " | ".join(hits)
    fallback = TAG_IMAGE_VISUALS.get(tag, "financial markets, economy, professional journalism")
    return (
        f"Invent a unique editorial scene that visually retells THIS headline "
        + f"(not a stock category wallpaper). Mood board: {fallback}."
    )


def _build_image_prompt(title: str, tag: str, resumo: str = "") -> str:
    headline = re.sub(r"\s+ ", " ", (title or "").strip())[:180]
    context = _first_paragraph(resumo, 360)
    scene = _extract_image_scene_cues(headline, context, tag or "Economia")
    return (
        "Create ONE editorial cover image for a Brazilian financial news site (Finanças News). "
        + "Illustrate the SPECIFIC story below — the reader must recognize the topic without reading text.\n"
        + f"Headline: {headline}\n"
        + f"Category: {tag or 'Economia'}\n"
        + f"Story context: {context or '(use the headline only)'}\n"
        + f"Required scene: {scene}\n"
        + "Composition: cinematic 16:9, photojournalism or polished illustration, dramatic lighting, "
        + "rich but restrained colors, single clear focal subject.\n"
        + "Strict rules: no text, letters, numbers, logos, watermarks, brand marks, or readable UI; "
        + "no celebrity faces; no generic gold Bitcoin coin piles or repeated crypto wallpaper "
        + "unless the headline is literally about physical coins; avoid looking like a stock template "
        + "used for every crypto article."
    )


def _normalize_image_bytes(data: bytes | str) -> bytes:
    if isinstance(data, str):
        return base64.b64decode(data)
    return data


def _save_image_bytes(data: bytes, mime_type: str, slug: str) -> str | None:
    ext = "png" if "png" in (mime_type or "") else "jpg"
    filename = f"{slug}.{ext}"
    filepath = get_article_images_dir() / filename
    _ = filepath.write_bytes(data)
    return f"/media/articles/{filename}"


def get_pexels_api_key() -> str:
    return (os.getenv("PEXELS_API_KEY") or os.getenv("PEXELS_KEY") or "").strip()


def _pexels_use_remote_url() -> bool:
    """Se true, grava a URL do CDN Pexels no banco (capa aparece sem disco local/Render).

    No Render, o default e remoto: disco efemero nao persiste capas entre deploys
    e ``ARTICLE_IMAGES_DIR`` local costuma falhar. Defina ``PEXELS_USE_REMOTE_URL=false``
    so se houver disco persistente montado de proposito.
    """
    raw = (os.getenv("PEXELS_USE_REMOTE_URL") or "").strip().lower()
    if raw:
        return raw in ("1", "true", "yes", "on")
    # RENDER e setado automaticamente pelo host; dashboard sem a var nao deve cair em disco.
    return bool(os.getenv("RENDER"))


# Flag setada em HTTP 429 para o backfill/script pausar (tier free ~200 req/h).
_pexels_rate_limited_flag = False

# IDs de foto Pexels ja usados em capas (DB + sessao) — evita repetir a mesma imagem.
_USED_PEXELS_LOCK = threading.Lock()
_used_pexels_ids: set[str] | None = None


def pexels_rate_limited() -> bool:
    return bool(_pexels_rate_limited_flag)


def clear_pexels_rate_limit() -> None:
    global _pexels_rate_limited_flag
    _pexels_rate_limited_flag = False


def clear_used_pexels_cache() -> None:
    """Forca recarregar IDs usados a partir do banco na proxima geracao."""
    global _used_pexels_ids
    with _USED_PEXELS_LOCK:
        _used_pexels_ids = None


def _pexels_photo_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/photos/(\d+)/", str(url))
    return match.group(1) if match else None


def _ensure_used_pexels_ids() -> set[str]:
    """Carrega do Turso os IDs Pexels ja ligados a noticias (cache em memoria)."""
    global _used_pexels_ids
    with _USED_PEXELS_LOCK:
        if _used_pexels_ids is not None:
            return _used_pexels_ids
        ids: set[str] = set()
        try:
            client_db = get_db()
            rows = client_db.execute(
                """
                SELECT imagem_url FROM news
                WHERE imagem_url LIKE '%pexels.com/photos/%'
                """
            ).rows
            for row in rows:
                pid = _pexels_photo_id_from_url(row[0] if row else None)
                if pid:
                    ids.add(pid)
            client_db.close()
        except Exception as exc:
            print(f"   [img/pexels] Nao foi possivel listar IDs usados: {exc}")
        _used_pexels_ids = ids
        print(f"   [img/pexels] Capas Pexels ja usadas: {len(ids)} foto(s)")
        return _used_pexels_ids


def _mark_pexels_id_used(photo_id: str | None) -> None:
    if not photo_id:
        return
    ids = _ensure_used_pexels_ids()
    with _USED_PEXELS_LOCK:
        ids.add(str(photo_id))


# Pool em memoria + lock de busca (workers reusam pool; API serializada).
_PEXELS_POOL: dict[str, list[dict[str, Any]]] = {}
_PEXELS_POOL_NEXT_PAGE: dict[str, int] = {}
_PEXELS_POOL_LOCK = threading.Lock()
_PEXELS_SEARCH_LOCK = threading.Lock()


def clear_pexels_pool() -> None:
    with _PEXELS_POOL_LOCK:
        _PEXELS_POOL.clear()
        _PEXELS_POOL_NEXT_PAGE.clear()


def _pexels_photo_url(photo: dict[str, Any] | None) -> str | None:
    if not photo:
        return None
    src = photo.get("src") or {}
    return src.get("large2x") or src.get("large") or src.get("original") or src.get("medium")


def _pexels_search(
    api_key: str,
    query: str,
    page: int,
    verify: bool,
) -> list[dict[str, Any]]:
    params = {
        "query": query,
        "per_page": 80,  # max Pexels: 1 chamada abastece muitas capas da mesma query
        "orientation": "landscape",
        "size": "large",
        "page": max(1, min(int(page), 80)),
    }
    # Uma busca por vez — workers paralelos reusam o pool sem martelar a API.
    global _pexels_rate_limited_flag
    with _PEXELS_SEARCH_LOCK:
        if _pexels_rate_limited_flag:
            return []
        try:
            resp = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": api_key},
                params=params,
                timeout=25,
                verify=verify,
            )
        except requests.exceptions.SSLError:
            urllib3.disable_warnings(InsecureRequestWarning)
            try:
                resp = requests.get(
                    "https://api.pexels.com/v1/search",
                    headers={"Authorization": api_key},
                    params=params,
                    timeout=25,
                    verify=False,
                )
            except Exception as exc:
                print(f"   [img/pexels] Erro de rede na busca: {exc}")
                return []
        except Exception as exc:
            print(f"   [img/pexels] Erro de rede na busca: {exc}")
            return []

        if resp.status_code == 401:
            print("   [img/pexels] Token invalido (401).")
            return []
        if resp.status_code == 429:
            _pexels_rate_limited_flag = True
            print("   [img/pexels] Rate limit (429) — pulando.")
            return []
        if resp.status_code != 200:
            print(f"   [img/pexels] HTTP {resp.status_code} na busca.")
            return []
        try:
            return list((resp.json() or {}).get("photos") or [])
        except Exception:
            print("   [img/pexels] JSON invalido.")
            return []


def _pexels_take_from_pool(query: str) -> dict[str, Any] | None:
    used = _ensure_used_pexels_ids()
    with _PEXELS_POOL_LOCK:
        pool = _PEXELS_POOL.setdefault(query, [])
        while pool:
            photo = pool.pop(0)
            url = _pexels_photo_url(photo)
            pid = str(photo.get("id") or "").strip() or (_pexels_photo_id_from_url(url) or "")
            if not url or (pid and pid in used):
                continue
            return photo
    return None


def _pexels_refill_pool(
    api_key: str,
    query: str,
    verify: bool,
    preferred_page: int = 1,
) -> int:
    """Uma chamada API; adiciona fotos ainda nao usadas ao pool. Retorna qtd nova."""
    if pexels_rate_limited():
        return 0
    with _PEXELS_POOL_LOCK:
        # Sempre avanca a partir de 1 (paginas altas do Pexels costumam vir vazias).
        page = _PEXELS_POOL_NEXT_PAGE.get(query, 1)
        _PEXELS_POOL_NEXT_PAGE[query] = page + 1 if page < 80 else 1

    photos = _pexels_search(api_key, query, page, verify)
    if not photos:
        # Se a pagina atual veio vazia, volta para 1 na proxima.
        with _PEXELS_POOL_LOCK:
            if page > 1:
                _PEXELS_POOL_NEXT_PAGE[query] = 1
        return 0

    used = _ensure_used_pexels_ids()
    added = 0
    with _PEXELS_POOL_LOCK:
        pool = _PEXELS_POOL.setdefault(query, [])
        seen = {str(p.get("id") or "") for p in pool}
        ordered = list(photos)
        if len(ordered) > 1:
            start = max(0, int(preferred_page) - 1) % len(ordered)
            ordered = ordered[start:] + ordered[:start]
        for photo in ordered:
            pid = str(photo.get("id") or "").strip()
            if not pid or pid in used or pid in seen:
                continue
            if not _pexels_photo_url(photo):
                continue
            pool.append(photo)
            seen.add(pid)
            added += 1
    if added:
        print(f"   [img/pexels] Pool '{query[:40]}': +{added} foto(s) (pagina {page})")
    return added


# Termos PT → consulta em inglês (Pexels indexa melhor em EN).
# Ordem importa: temas específicos ANTES de Selic/IPCA (muitos títulos citam Selic só de passagem).
_STOCK_TERM_QUERIES: list[tuple[tuple[str, ...], str]] = [
    (("pet ", " pets", "plano pet", "planos pet", "veterin"), "pet dog veterinary family"),
    (("megashow", "show ", "festival", "entretenimento", "cinema", "teatro", "pipoca", "lazer"), "concert festival entertainment crowd"),
    (("futebol", "corinthians", "flamengo", "palmeiras", "jogador", "clube", "esport"), "soccer stadium football match"),
    (("agroneg", "agro ", "soja", "café", "cafe", "queijo", "safra", "rural"), "agriculture farm harvest brazil"),
    (("imóvel", "imoveis", "imóveis", "imobiliár", "aluguel", "apartamento"), "modern apartment buildings real estate"),
    (("capital", "capitais", "câmbio capital", "controle de capital"), "capital controls finance currency"),
    (("empreendedor", "startup", "negócio", "negocio", "pme", "mei "), "entrepreneur startup small business"),
    (("trabalho", "carreira", "emprego", "salário", "salario", "qualidade de vida"), "office career work life balance"),
    (("eleitoral", "eleição", "eleicao", "congresso", "governo", "política", "politica"), "government building parliament election"),
    (("bitcoin", "btc", "cripto", "crypto", "ethereum"), "cryptocurrency trading screens"),
    (("fintech", "nubank", "pix", "banco digital"), "fintech mobile payment smartphone"),
    (("dólar", "dolar", "câmbio", "cambio", "usd", "forex"), "currency exchange forex trading"),
    (("ações", "acoes", "bolsa", "ibovespa", "b3", "ibov"), "stock market trading floor"),
    (("petróleo", "petroleo", "brent", "wti", "óleo", "oleo"), "oil industry energy commodities"),
    (("ouro", "gold"), "gold bars vault finance"),
    (("ipca", "inflação", "inflacao", "preço", "preco", "custo de vida"), "supermarket prices inflation cost of living"),
    (("selic", "copom", "banco central", "taxa de juros"), "central bank building interest rates"),
    (("juros",), "interest rates finance charts"),
    (("economia", "econômic", "economic", "pib", "recessão", "recessao", "crescimento"), "business district skyline economy"),
]

_STOCK_TAG_QUERIES = {
    "Cripto": "cryptocurrency trading desk screens",
    "Economia": "brazilian business skyline economy",
    "Dólar": "currency exchange usd forex",
    "Ações": "stock market trading floor",
    "Juros": "central bank interest rates",
    "Inflação": "supermarket cost of living prices",
    "Imóveis": "modern apartments real estate city",
    "Fintech": "mobile banking fintech payment",
    "Commodities": "commodity trading oil agriculture",
    "Política Econômica": "government fiscal policy building",
}


def _stock_search_query(title: str, tag: str, resumo: str = "") -> str:
    """Monta query curta em inglês para banco de fotos (Pexels).

    Prioriza o título (o resumo editorial costuma citar Selic/IPCA/dólar em todo artigo
    e poluiria a busca se viesse primeiro).
    """
    title_l = (title or "").lower()
    for keys, query in _STOCK_TERM_QUERIES:
        if any(k in title_l for k in keys):
            return query

    tag_q = _STOCK_TAG_QUERIES.get(str(tag or ""))
    if tag_q:
        return tag_q

    resumo_l = (resumo or "").lower()
    for keys, query in _STOCK_TERM_QUERIES:
        if any(k in resumo_l for k in keys):
            return query

    return _STOCK_TAG_QUERIES.get("Economia", "financial news business economy")


def _fit_cover_jpeg(raw: bytes, max_side: int = 1280) -> bytes | None:
    """Recorta ao centro 16:9 e exporta JPEG (capa editorial)."""
    try:
        from PIL import Image
    except ImportError:
        print("   [img/pexels] Pillow nao instalado.")
        return None
    try:
        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGB")
        w, h = img.size
        if w < 64 or h < 64:
            return None
        target_ratio = 16 / 9
        current = w / h
        if current > target_ratio:
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, h))
        elif current < target_ratio:
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            img = img.crop((0, top, w, top + new_h))
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85, optimize=True)
        return out.getvalue()
    except Exception as exc:
        print(f"   [img/pexels] Falha ao processar imagem: {exc}")
        return None


def _generate_article_image_pexels(title: str, tag: str, resumo: str, slug: str) -> str | None:
    """Busca foto editorial no Pexels; reusa pool por query e evita IDs ja usados."""
    api_key = get_pexels_api_key()
    if not api_key:
        print("   [img/pexels] PEXELS_API_KEY nao configurada.")
        return None

    base_query = _stock_search_query(title, tag, resumo)
    query_variants = [
        base_query,
        f"{base_query} brazil",
        f"{base_query} city",
        f"{base_query} office",
    ]
    print(f"   [img/pexels] Buscando foto: {base_query!r}")
    _configure_ssl_certs()
    verify = _ssl_verify_enabled()
    if not verify:
        urllib3.disable_warnings(InsecureRequestWarning)

    slug_hash = int(hashlib.sha256(slug.encode()).hexdigest(), 16)
    preferred_page = (slug_hash % 20) + 1

    photo: dict[str, Any] | None = None
    for query in query_variants:
        if pexels_rate_limited():
            return None
        photo = _pexels_take_from_pool(query)
        if photo:
            break
        # Ate 4 buscas (320 fotos) por variante antes de mudar a query.
        for _ in range(4):
            if pexels_rate_limited():
                return None
            added = _pexels_refill_pool(api_key, query, verify, preferred_page)
            if added <= 0:
                continue
            photo = _pexels_take_from_pool(query)
            if photo:
                break
        if photo:
            break

    if not photo:
        # Acervo grande: fotos "novas" da query acabam. Permite reuso determinístico
        # por slug para ainda cobrir o backlog (melhor que artigo sem capa).
        # Paginas altas do Pexels costumam vir vazias — prioriza pagina 1.
        reuse_pages = [1, (slug_hash % 8) + 1, 2, 3, 4]
        for query in query_variants:
            if photo or pexels_rate_limited():
                break
            for page in reuse_pages:
                if pexels_rate_limited():
                    break
                photos = _pexels_search(api_key, query, page, verify)
                if not photos:
                    continue
                candidate = photos[slug_hash % len(photos)]
                if _pexels_photo_url(candidate):
                    photo = candidate
                    print(
                        f"   [img/pexels] Reuso (pool esgotado) id={candidate.get('id')} "
                        f"query={query[:36]!r} page={page}"
                    )
                    break
        if not photo:
            print("   [img/pexels] Nenhuma foto nova utilizavel.")
            return None

    url = _pexels_photo_url(photo) or ""
    url_id = str(photo.get("id") or "").strip() or _pexels_photo_id_from_url(url)
    photographer = (photo.get("photographer") or "").strip()
    safe_name = photographer.encode("ascii", "replace").decode("ascii") or "stock"

    if _pexels_use_remote_url():
        _mark_pexels_id_used(url_id)
        print(f"   [img/pexels] Capa remota OK ({safe_name}, id={url_id}): {url[:80]}...")
        return url

    try:
        img_resp = requests.get(url, timeout=40, verify=verify)
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(InsecureRequestWarning)
        try:
            img_resp = requests.get(url, timeout=40, verify=False)
        except Exception as exc:
            print(f"   [img/pexels] Download falhou: {exc}")
            return None
    except Exception as exc:
        print(f"   [img/pexels] Download falhou: {exc}")
        return None
    if img_resp.status_code != 200 or not img_resp.content:
        return None
    jpeg = _fit_cover_jpeg(img_resp.content)
    if not jpeg:
        return None
    saved = _save_image_bytes(jpeg, "image/jpeg", slug)
    if saved:
        _mark_pexels_id_used(url_id)
        print(f"   [img/pexels] Capa OK ({safe_name}, id={url_id}): {saved}")
        return saved
    return None


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


def _is_image_model_unavailable(exc: Exception) -> bool:
    """Modelo removido/descontinuado na API (vale para todas as chaves)."""
    msg = str(exc)
    return (
        "NOT_FOUND" in msg
        or "no longer available" in msg
        or "is not found" in msg
        or "not supported for generateContent" in msg
        or "not supported for generateImages" in msg
    )


def _is_image_key_access_error(exc: Exception) -> bool:
    """Sem cota/acesso nesta chave — tentar o mesmo modelo na próxima chave."""
    msg = str(exc).lower()
    return (
        "permission_denied" in msg
        or "not enabled" in msg
        or "does not have access" in msg
        or "api key not valid" in msg
        or "consumer_invalid" in msg
    )


def get_openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def get_hf_token() -> str:
    return (os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or "").strip()


def get_hf_image_models() -> list[str]:
    raw = os.getenv("HF_IMAGE_MODELOS", "").strip()
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    return DEFAULT_HF_IMAGE_MODELOS.copy()


def get_openai_image_models() -> list[str]:
    """Lista de modelos OpenAI de imagem (fallback em cota/indisponibilidade)."""
    raw = os.getenv("OPENAI_IMAGE_MODELOS", "").strip()
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    single = os.getenv("OPENAI_IMAGE_MODEL", "").strip()
    if single:
        return [single]
    return DEFAULT_OPENAI_IMAGE_MODELOS.copy()


def get_openai_image_model() -> str:
    """Primeiro modelo da fila (compatível com logs/env antigos)."""
    models = get_openai_image_models()
    return models[0] if models else "dall-e-2"


def get_openai_image_min_interval() -> float:
    """Intervalo mínimo entre gerações OpenAI (padrão 65s ≈ 1 imagem/min)."""
    raw = os.getenv("OPENAI_IMAGE_MIN_INTERVAL", "65").strip()
    try:
        return max(60.0, float(raw))
    except ValueError:
        return 65.0


def _is_openai_image_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "rate_limit" in msg
        or "rate limit" in msg
        or "quota" in msg
        or "insufficient_quota" in msg
        or "billing" in msg
        or "429" in msg
        or "requests per day" in msg
        or "rpd" in msg
        or "images per minute" in msg
    )


def _is_openai_billing_hard_limit(exc: Exception) -> bool:
    """Limite de billing da conta — afeta todos os modelos OpenAI."""
    msg = str(exc).lower()
    return "billing_hard_limit" in msg or "billing hard limit" in msg


def _is_openai_image_model_unavailable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "model_not_found" in msg
        or "does not exist" in msg
        or "not available" in msg
        or "not supported" in msg
        or "invalid_model" in msg
        or "not allowed" in msg
        or "access" in msg and "denied" in msg
        or "404" in msg
    )


def _openai_prompt_for_model(model: str, prompt: str) -> str:
    text = prompt.strip()
    if model.startswith("dall-e-2"):
        return text[:1000]
    if model.startswith("dall-e-3"):
        return text[:4000]
    return text[:32000]


def _openai_image_generate_kwargs(model: str, prompt: str) -> dict[str, Any]:
    """Monta kwargs compatíveis com DALL-E vs GPT Image."""
    safe_prompt = _openai_prompt_for_model(model, prompt)
    if model.startswith("dall-e-2"):
        # Sem response_format: algumas contas/API rejects unknown_parameter.
        return {
            "model": model,
            "prompt": safe_prompt,
            "n": 1,
            "size": "1024x1024",
        }
    if model.startswith("dall-e-3"):
        return {
            "model": model,
            "prompt": safe_prompt,
            "n": 1,
            "size": "1792x1024",
            "quality": "standard",
        }
    # GPT Image (gpt-image-1/1.5/1-mini/2): sempre retorna b64; sem response_format.
    return {
        "model": model,
        "prompt": safe_prompt,
        "n": 1,
        "size": "1536x1024",
        "quality": "medium",
        "output_format": "png",
    }


def _extract_openai_image_bytes(response) -> bytes | None:
    data = getattr(response, "data", None) or []
    if not data:
        return None
    item = data[0]
    b64 = getattr(item, "b64_json", None)
    if b64:
        return base64.b64decode(b64)
    url = getattr(item, "url", None)
    if url:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        return r.content
    return None


def get_image_providers() -> list[str]:
    """Lista ordenada de provedores de imagem.

    ``IMAGE_PROVIDER`` aceita um ou vários (separados por vírgula):
    - ``pexels,gemini,huggingface,openai`` — stock → Gemini → HF → OpenAI
    - ``openai,gemini`` — OpenAI primeiro
    - ``auto`` / vazio — Cursor (local) → Pexels → Gemini → Hugging Face → OpenAI

    No Render, ``cursor`` é ignorado (SDK não roda lá).
    Aliases: ``hf`` → ``huggingface``, ``stock`` → ``pexels``.
    """
    raw = os.getenv("IMAGE_PROVIDER", "").strip().lower()
    on_render = bool(os.getenv("RENDER"))
    aliases = {"hf": "huggingface", "stock": "pexels"}
    allowed = {"cursor", "gemini", "openai", "huggingface", "hf", "pexels", "stock", "auto"}

    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    parts = [p for p in parts if p in allowed]

    def _expand_auto() -> list[str]:
        if on_render:
            return ["pexels", "gemini", "huggingface", "openai"]
        return ["cursor", "pexels", "gemini", "huggingface", "openai"]

    if not parts or parts == ["auto"]:
        ordered = _expand_auto()
    else:
        ordered = []
        for part in parts:
            if part == "auto":
                ordered.extend(_expand_auto())
            elif part == "cursor" and on_render:
                continue
            else:
                ordered.append(aliases.get(part, part))

    seen: set[str] = set()
    providers: list[str] = []
    for name in ordered:
        canon = aliases.get(name, name)
        if canon == "auto" or canon in seen:
            continue
        seen.add(canon)
        providers.append(canon)

    return providers or _expand_auto()


def get_image_provider() -> str:
    """Primeiro provedor da fila (compatível com código legado)."""
    providers = get_image_providers()
    return providers[0] if providers else "gemini"


def _wait_openai_image_slot() -> None:
    """Respeita o teto de 1 imagem/minuto do projeto OpenAI."""
    global _openai_last_image_at
    interval = get_openai_image_min_interval()
    with _openai_image_lock:
        now = time.time()
        wait = interval - (now - _openai_last_image_at)
        if wait > 0:
            print(f"   [img/openai] Aguardando {wait:.0f}s (limite 1 imagem/min)...")
            time.sleep(wait)
        _openai_last_image_at = time.time()


def _resolve_existing_article_image(slug: str) -> str | None:
    images_dir = get_article_images_dir()
    for existing in images_dir.glob(f"{slug}.*"):
        return f"/media/articles/{existing.name}"
    return None


def _generate_article_image_cursor(prompt: str, slug: str) -> str | None:
    api_key = os.getenv("CURSOR_API_KEY", "").strip()
    if not api_key:
        print("   [img/cursor] CURSOR_API_KEY nao configurada.")
        return None

    try:
        from cursor_sdk import (  # type: ignore[import-not-found]
            Agent,
            AgentOptions,
            CursorAgentError,
            LocalAgentOptions,
        )
    except ImportError:
        print("   [img/cursor] Pacote cursor-sdk nao instalado. Rode: pip install -r requirements.txt")
        return None

    images_dir = get_article_images_dir()
    output_png = (images_dir / slug).with_suffix(".png")
    output_jpg = (images_dir / slug).with_suffix(".jpg")
    project_root = Path(__file__).resolve().parent
    started_at = time.time()
    model = os.getenv("CURSOR_IMAGE_MODEL", "composer-2.5").strip() or "composer-2.5"

    agent_prompt = (
        "Gere exatamente UMA imagem editorial usando a ferramenta de geracao de imagens do Cursor.\n\n"
        + f"Descricao: {prompt}\n\n"
        + "Requisitos obrigatorios:\n"
        + "- Proporcao 16:9\n"
        + "- Sem texto, letras, logos ou marcas d'agua\n"
        + f"- Salve o arquivo exatamente em: {output_png.resolve()}\n"
        + "- Se nao conseguir PNG, salve em JPG no mesmo diretorio com o mesmo nome base\n\n"
        + "Ao concluir, responda apenas: SAVED"
    )

    print(f"   [img/cursor] Gerando imagem via Cursor ({model})...")
    try:
        result = Agent.prompt(
            agent_prompt,
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=str(project_root)),
            ),
        )
        if result.status == "error":
            run_id = getattr(result, "id", "?")
            print(f"   [img/cursor] Agente retornou erro (run={run_id}).")
            return None
    except CursorAgentError as exc:
        print(f"   [img/cursor] Falha ao iniciar agente: {exc}")
        return None
    except Exception as exc:
        print(f"   [img/cursor] Falha: {exc}")
        return None

    for candidate in (output_png, output_jpg):
        if candidate.exists() and candidate.stat().st_size > 1024:
            return f"/media/articles/{candidate.name}"

    for path in sorted(images_dir.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        if path.stat().st_mtime < started_at - 5 or path.stat().st_size <= 1024:
            continue
        if path.stem != slug:
            target = images_dir / f"{slug}{path.suffix.lower()}"
            if not target.exists():
                path = path.replace(target)
                path = target
        return f"/media/articles/{path.name}"

    print("   [img/cursor] Agente concluiu, mas nenhum arquivo de imagem foi encontrado.")
    return None


def _generate_article_image_gemini(prompt: str, slug: str) -> str | None:
    keys = get_gemini_api_keys_for_images()
    if not keys:
        print("   [img/gemini] Cliente Gemini indisponivel (GOOGLE_API_KEY/GEMINI_API_KEY).")
        return None

    all_models = get_gemini_image_models()
    if not all_models:
        print("   [img/gemini] Nenhum modelo de imagem configurado.")
        return None

    for key_index, api_key in enumerate(keys, start=1):
        key_id = _api_key_id(api_key)
        exhausted = _exhausted_image_models_by_key.setdefault(key_id, set())
        modelos = [
            m
            for m in all_models
            if m not in exhausted and m not in _unavailable_image_models
        ]
        if not modelos:
            print(
                f"   [img/gemini] Chave {key_index}/{len(keys)} sem modelos "
                + f"(cota: {sorted(exhausted)} | indisponiveis: {sorted(_unavailable_image_models)})."
            )
            continue

        gen_client = get_genai_client(api_key)
        if gen_client is None:
            print(f"   [img/gemini] Falha ao criar client da chave {key_index}.")
            continue

        print(f"   [img/gemini] Tentando chave {key_index}/{len(keys)}...")
        for model in modelos:
            try:
                print(f"   [img/gemini] Gerando imagem ({model}, chave {key_index})...")
                if model.startswith("imagen"):
                    response = gen_client.models.generate_images(
                        model=model,
                        prompt=prompt,
                        config=types.GenerateImagesConfig(
                            number_of_images=1,
                            output_mime_type="image/jpeg",
                            aspect_ratio="16:9",
                        ),
                    )
                else:
                    response = gen_client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE", "TEXT"],
                            image_config=types.ImageConfig(aspect_ratio="16:9"),
                        ),
                    )

                extracted = _extract_image_from_response(response)
                if extracted:
                    data, mime_type = extracted
                    url = _save_image_bytes(data, mime_type, slug)
                    print(f"   [img/gemini] Imagem salva: {url} (chave {key_index})")
                    return url
                print(f"   [img/gemini] Resposta sem imagem ({model}, chave {key_index}).")
            except Exception as e:
                if _is_image_model_unavailable(e):
                    _unavailable_image_models.add(model)
                    print(f"   [img/gemini] Modelo indisponivel na API, removendo da fila: {model}")
                elif _is_image_quota_error(e) or _is_image_key_access_error(e):
                    exhausted.add(model)
                    print(
                        f"   [img/gemini] Sem cota/acesso em {model} (chave {key_index}) "
                        + "— proximo modelo/chave."
                    )
                print(f"   [img/gemini] Falha ({model}, chave {key_index}): {e}")
                continue

    return None


def _generate_article_image_openai(prompt: str, slug: str) -> str | None:
    api_key = get_openai_api_key()
    if not api_key:
        print("   [img/openai] OPENAI_API_KEY nao configurada.")
        return None

    try:
        from openai import OpenAI  # noqa: F401 — valida dependencia
    except ImportError:
        print("   [img/openai] Pacote openai nao instalado. Rode: pip install -r requirements.txt")
        return None

    all_models = get_openai_image_models()
    modelos = [
        m
        for m in all_models
        if m not in _exhausted_openai_image_models and m not in _unavailable_openai_image_models
    ]
    if not modelos:
        print(
            f"   [img/openai] Sem modelos "
            + f"(cota: {sorted(_exhausted_openai_image_models)} | "
            + f"indisponiveis: {sorted(_unavailable_openai_image_models)})."
        )
        return None

    _wait_openai_image_slot()
    client = _create_openai_client(api_key)

    for model in modelos:
        try:
            print(f"   [img/openai] Gerando imagem ({model})...")
            response = client.images.generate(**_openai_image_generate_kwargs(model, prompt))
            raw = _extract_openai_image_bytes(response)
            if not raw:
                print(f"   [img/openai] Resposta sem imagem ({model}).")
                continue
            url = _save_image_bytes(raw, "image/png", slug)
            print(f"   [img/openai] Imagem salva: {url} ({model})")
            return url
        except Exception as e:
            if _is_openai_billing_hard_limit(e):
                for m in all_models:
                    _exhausted_openai_image_models.add(m)
                print(
                    "   [img/openai] Billing hard limit atingido — "
                    + "interrompendo fila OpenAI (libere o limite no painel OpenAI)."
                )
                print(f"   [img/openai] Falha ({model}): {e}")
                return None
            if _is_openai_image_model_unavailable(e):
                _unavailable_openai_image_models.add(model)
                print(f"   [img/openai] Modelo indisponivel, removendo da fila: {model}")
            elif _is_openai_image_quota_error(e):
                _exhausted_openai_image_models.add(model)
                print(
                    f"   [img/openai] Sem cota/RPM em {model} — proximo modelo."
                )
            print(f"   [img/openai] Falha ({model}): {e}")
            continue

    return None


def _create_hf_client(token: str):
    """Client Hugging Face; respeita SSL_VERIFY=false no Windows/MITM."""
    from huggingface_hub import InferenceClient, set_client_factory

    if not _ssl_verify_enabled():
        import httpx

        def _insecure_client_factory():
            return httpx.Client(verify=False, timeout=120.0)

        set_client_factory(_insecure_client_factory)
        print("   [img/hf] SSL verify desativado (GEMINI_SSL_VERIFY/SSL_VERIFY=false).")
    return InferenceClient(token=token)


def _is_hf_image_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "rate limit" in msg
        or "rate_limit" in msg
        or "quota" in msg
        or "429" in msg
        or "too many requests" in msg
        or "payment required" in msg
        or "402" in msg
    )


def _is_hf_image_model_unavailable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "not found" in msg
        or "404" in msg
        or "does not exist" in msg
        or "unsupported" in msg
        or "no inference provider" in msg
    )


def _generate_article_image_huggingface(prompt: str, slug: str) -> str | None:
    token = get_hf_token()
    if not token:
        print("   [img/hf] HF_TOKEN nao configurada.")
        return None

    try:
        from huggingface_hub import InferenceClient
    except ImportError:
        print(
            "   [img/hf] Pacote huggingface_hub nao instalado. "
            + "Rode: pip install -r requirements.txt"
        )
        return None

    all_models = get_hf_image_models()
    modelos = [
        m
        for m in all_models
        if m not in _exhausted_hf_image_models and m not in _unavailable_hf_image_models
    ]
    if not modelos:
        print(
            f"   [img/hf] Sem modelos "
            + f"(cota: {sorted(_exhausted_hf_image_models)} | "
            + f"indisponiveis: {sorted(_unavailable_hf_image_models)})."
        )
        return None

    client = _create_hf_client(token)

    for model in modelos:
        try:
            print(f"   [img/hf] Gerando imagem ({model})...")
            image = client.text_to_image(prompt, model=model)
            buf = io.BytesIO()
            if hasattr(image, "save"):
                image.save(buf, format="PNG")
                raw = buf.getvalue()
            elif isinstance(image, (bytes, bytearray)):
                raw = bytes(image)
            else:
                print(f"   [img/hf] Resposta sem imagem ({model}): {type(image)}")
                continue
            url = _save_image_bytes(raw, "image/png", slug)
            print(f"   [img/hf] Imagem salva: {url} ({model})")
            return url
        except Exception as e:
            if _is_hf_image_model_unavailable(e):
                _unavailable_hf_image_models.add(model)
                print(f"   [img/hf] Modelo indisponivel, removendo da fila: {model}")
            elif _is_hf_image_quota_error(e):
                _exhausted_hf_image_models.add(model)
                print(f"   [img/hf] Sem cota/credito em {model} — proximo modelo.")
            print(f"   [img/hf] Falha ({model}): {e}")
            continue

    return None


def generate_article_image(
    title: str,
    tag: str,
    link: str,
    resumo: str = "",
    article_id: int | None = None,
    use_openai: bool = True,
) -> str | None:
    """Gera capa editorial; retorna URL pública ou None em caso de falha.

    Provedores vêm de ``IMAGE_PROVIDER`` (um ou vários, ex.: ``gemini,openai``).
    ``use_openai=False`` remove OpenAI da fila (varredura do robô).
    """
    slug = _article_image_slug(link, article_id)
    existing = _resolve_existing_article_image(slug)
    if existing:
        return existing

    prompt = _build_image_prompt(title, tag, resumo)
    providers = get_image_providers()
    if not use_openai:
        providers = [p for p in providers if p != "openai"]

    if not providers:
        print("   [img] Nenhum provedor de imagem disponivel.")
        return None

    print(f"   [img] Provedores na ordem: {', '.join(providers)}")
    print(f"   [img] Prompt (trecho): {prompt[:160].replace(chr(10), ' ')}...")

    for provider in providers:
        if provider == "pexels":
            if not get_pexels_api_key():
                print("   [img/pexels] PEXELS_API_KEY ausente — pulando.")
                continue
            url = _generate_article_image_pexels(title, tag, resumo, slug)
            if url:
                return url
            print("   [img/pexels] Sem capa — proximo provedor.")
            continue

        if provider == "cursor":
            if not os.getenv("CURSOR_API_KEY", "").strip():
                print("   [img/cursor] CURSOR_API_KEY nao configurada — pulando.")
                continue
            url = _generate_article_image_cursor(prompt, slug)
            if url:
                print(f"   [img] Imagem salva: {url}")
                return url
            print("   [img/cursor] Sem capa — proximo provedor.")
            continue

        if provider == "gemini":
            if not get_gemini_api_keys():
                print("   [img/gemini] Sem GOOGLE_API_KEY — pulando.")
                continue
            url = _generate_article_image_gemini(prompt, slug)
            if url:
                return url
            print("   [img/gemini] Sem capa — proximo provedor.")
            continue

        if provider == "openai":
            if not get_openai_api_key():
                print("   [img/openai] OPENAI_API_KEY ausente — pulando.")
                continue
            url = _generate_article_image_openai(prompt, slug)
            if url:
                return url
            print("   [img/openai] Sem capa — proximo provedor.")
            continue

        if provider == "huggingface":
            if not get_hf_token():
                print("   [img/hf] HF_TOKEN ausente — pulando.")
                continue
            url = _generate_article_image_huggingface(prompt, slug)
            if url:
                return url
            print("   [img/hf] Sem capa — proximo provedor.")
            continue

    print("   [img] Imagem nao gerada — artigo seguira sem capa.")
    return None


def _media_filename_from_url(imagem_url: str | None) -> str | None:
    if not imagem_url:
        return None
    name = str(imagem_url).strip().rstrip("/").rsplit("/", 1)[-1]
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        return None
    return name


def _media_file_exists(imagem_url: str | None) -> bool:
    name = _media_filename_from_url(imagem_url)
    if not name:
        return False
    path = get_article_images_dir() / name
    return path.is_file() and path.stat().st_size > 0


def _cover_url_ready(imagem_url: str | None) -> bool:
    """True se a capa pode ser publicada (arquivo local ou URL http(s) externa)."""
    if not imagem_url:
        return False
    url = str(imagem_url).strip()
    if url.startswith(("http://", "https://")):
        return True
    return _media_file_exists(url)


def backfill_missing_images(limit: int = 1, repair_broken: bool = True) -> dict[str, Any]:
    """Gera capas pendentes: prioriza notícias mais novas (id DESC).

    Também repara registros com ``imagem_url`` apontando para arquivo ausente no disco
    (comum quando o cron grava no Turso e o arquivo não persistiu no host).
    """
    _reset_image_quota_state()
    client_db = get_db()
    # Stock (Pexels) é rápido — varre mais fundo para achar antigos sem capa.
    scan = max(limit * 80, 200)
    result = client_db.execute(
        """
        SELECT id, titulo, tag, link, resumo, imagem_url
        FROM news
        WHERE imagem_url IS NULL OR TRIM(COALESCE(imagem_url, '')) = ''
        ORDER BY id DESC
        LIMIT ?
        """,
        [scan],
    )

    rows: list[Any] = []
    repaired_ids: list[int] = []
    for row in result.rows:
        rows.append(row)
        if len(rows) >= limit:
            break

    if repair_broken and len(rows) < limit:
        broken_scan = max(limit * 40, 80)
        recent = client_db.execute(
            """
            SELECT id, titulo, tag, link, resumo, imagem_url
            FROM news
            WHERE imagem_url IS NOT NULL AND TRIM(imagem_url) != ''
            ORDER BY id DESC
            LIMIT ?
            """,
            [broken_scan],
        )
        for row in recent.rows:
            if len(rows) >= limit:
                break
            article_id = int(row[0])
            imagem_url = row[5] if len(row) > 5 else None
            # Só repara caminhos locais quebrados. URL http(s) (Pexels CDN etc.)
            # é capa válida — _media_file_exists falharia e apagaria capas remotas.
            if not _cover_url_ready(imagem_url):
                print(
                    f"   [img] URL quebrada #{article_id}: {imagem_url} "
                    + f"(arquivo ausente em {get_article_images_dir()}) — regenerando."
                )
                _ = client_db.execute(
                    "UPDATE news SET imagem_url = NULL WHERE id = ?",
                    [article_id],
                )
                repaired_ids.append(article_id)
                rows.append(row)

    updated: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    if not rows:
        print("   [img] Nenhuma noticia sem capa (nem URL quebrada) para backfill.")
        client_db.close()
        return {
            "processed": 0,
            "updated": 0,
            "failed": 0,
            "repaired_broken": 0,
            "items": [],
            "errors": [],
            "priority": "newest_first",
        }

    print(
        f"   [img] Backfill: ate {len(rows)} capa(s), prioridade noticias novas "
        + f"(id DESC); reparos={len(repaired_ids)}."
    )

    def _process_row(row: Any) -> tuple[int, str, str | None, str]:
        article_id = int(row[0])
        titulo, tag, link, resumo = row[1], row[2], row[3] or "", row[4] or ""
        print(f"   [img] Capa pendente #{article_id}: {(titulo or '')[:60]}...")
        if pexels_rate_limited():
            return article_id, titulo or "", None, "rate_limit"
        url = generate_article_image(
            titulo,
            tag,
            link,
            resumo,
            article_id=article_id,
            use_openai=True,
        )
        return article_id, titulo or "", url, "ok"

    # Pexels remoto: paraleliza geracao (pool compartilhado = poucas buscas API).
    # Lotes pequenos ficam sequenciais (mais estavel no smoke / debug).
    parallel = (
        _pexels_use_remote_url()
        and get_image_providers() == ["pexels"]
        and len(rows) >= 8
    )
    workers = min(8, len(rows)) if parallel else 1
    if parallel:
        print(f"   [img] Modo paralelo: {workers} workers")
        # Pre-aquece pool por query unica (1 busca / tema no lote).
        api_key = get_pexels_api_key()
        if api_key:
            _configure_ssl_certs()
            verify = _ssl_verify_enabled()
            if not verify:
                urllib3.disable_warnings(InsecureRequestWarning)
            _ = _ensure_used_pexels_ids()
            warmed: set[str] = set()
            for row in rows:
                q = _stock_search_query(row[1] or "", row[2] or "", row[4] or "")
                if q in warmed:
                    continue
                warmed.add(q)
                _ = _pexels_refill_pool(api_key, q, verify, 1)

    results: list[tuple[int, str, str | None, str]] = []
    if workers == 1:
        for row in rows:
            if pexels_rate_limited():
                failed.append({"id": int(row[0]), "titulo": "rate_limit_429"})
                break
            results.append(_process_row(row))
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_process_row, row) for row in rows]
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as exc:
                    print(f"   [img] Worker falhou: {exc}")

    for article_id, titulo, imagem_url, status in results:
        if status == "rate_limit" or pexels_rate_limited() and not imagem_url:
            failed.append({"id": article_id, "titulo": "rate_limit_429"})
            continue
        if imagem_url and _cover_url_ready(imagem_url):
            _ = client_db.execute(
                "UPDATE news SET imagem_url = ? WHERE id = ?",
                [imagem_url, article_id],
            )
            updated.append({"id": article_id, "imagem_url": imagem_url})
        else:
            if imagem_url and not _cover_url_ready(imagem_url):
                print(f"   [img] Arquivo nao persistiu apos gerar ({imagem_url}) — nao atualiza DB.")
            failed.append({"id": article_id, "titulo": (titulo or "")[:80]})

    client_db.close()
    return {
        "processed": len(updated) + len(failed),
        "updated": len(updated),
        "failed": len(failed),
        "repaired_broken": len(repaired_ids),
        "items": updated,
        "errors": failed,
        "rate_limited": pexels_rate_limited(),
        "priority": "newest_first",
    }


def generate_content_with_fallback(prompt: str) -> str | None:
    """Tenta modelos e chaves em ordem; troca em cota diária; espera só em RPM."""
    keys = get_gemini_api_keys()
    if not keys:
        return None

    all_models = get_gemini_modelos()
    if not all_models:
        return None

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.7,
    )

    for key_index, api_key in enumerate(keys, start=1):
        key_id = _api_key_id(api_key)
        exhausted = _exhausted_models_by_key.setdefault(key_id, set())
        modelos = [m for m in all_models if m not in exhausted]
        if not modelos:
            print(f"   ⚠️ Chave {key_index}/{len(keys)}: todos os modelos de texto esgotados.")
            continue

        gen_client = get_genai_client(api_key)
        if gen_client is None:
            continue

        print(f"   🔑 Texto: chave {key_index}/{len(keys)}")
        for model in modelos:
            rpm_retries = 0
            max_rpm_retries = 3

            while rpm_retries <= max_rpm_retries:
                try:
                    print(f"   🤖 Modelo: {model}")
                    response = gen_client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=config,
                    )
                    if not response.text:
                        return None
                    return response.text

                except Exception as e:
                    if _is_daily_quota_error(e):
                        print(
                            f"   ⚠️ Cota diária esgotada em {model} "
                            + f"(chave {key_index}) — próximo modelo/chave."
                        )
                        exhausted.add(model)
                        break

                    if _is_rpm_quota_error(e) and rpm_retries < max_rpm_retries:
                        delay = _extract_retry_delay(e)
                        print(f"   ⏳ Limite por minuto em {model}, aguardando {delay:.0f}s...")
                        time.sleep(delay)
                        rpm_retries += 1
                        continue

                    print(f"   ❌ Erro na IA ({model}, chave {key_index}): {e}")
                    break

    print("   ❌ Todas as chaves/modelos Gemini esgotaram a cota diária nesta execução.")
    return None


def _all_text_models_exhausted() -> bool:
    keys = get_gemini_api_keys()
    models = get_gemini_modelos()
    if not keys or not models:
        return True
    return all(
        len(_exhausted_models_by_key.get(_api_key_id(k), set())) >= len(models)
        for k in keys
    )


def process_news_with_ai(title, content, fonte, tag_hint, market_context):
    if not get_gemini_api_keys():
        return None

    print(f"   🤖 Enviando para IA: {title[:40]}...")

    tags_list = ", ".join(VALID_TAGS)
    macro_rel = _macro_topic_relevance(title, content, tag_hint)
    lenses = select_analysis_lenses(title, content, tag_hint, count=2)
    lens_block = _build_lens_prompt_block(lenses)
    macro_rules = _build_macro_usage_rules(macro_rel, tag_hint)

    prompt = f"""
Você é o editor-chefe de análise do portal "Finanças News" (financas-news.net.br), especializado em economia brasileira, mercado de capitais e criptoativos.

Sua missão é produzir uma ANÁLISE EDITORIAL ORIGINAL de alto valor — não um resumo, não uma paráfrase da notícia fonte. O Google e leitores exigem conteúdo com dados concretos, contexto histórico e utilidade prática.

## REGRAS INEGOCIÁVEIS
- PROIBIDO: resumir a notícia, usar "segundo a matéria", "o texto relata", "conforme publicado".
- PROIBIDO: parágrafo só com opinião genérica sem número concreto dos DADOS DE MERCADO ou do acervo.
- PROIBIDO: abrir toda matéria com Selic/juros quando o fato for de outro tema (cripto, política local, consumo, etc.).
- PROIBIDO: repetir a mesma fórmula macro (Selic + IPCA + dólar) em todos os parágrafos — varie os indicadores.
- OBRIGATÓRIO: usar números concretos do painel em pelo menos 4 dos 6 parágrafos (indicadores VARIADOS).
- OBRIGATÓRIO: citar pelo menos 1 cotação ou indicador alinhado à categoria `{tag_hint}`.
- OBRIGATÓRIO: quando houver tendência 7d/30d nos dados, usar em pelo menos 2 parágrafos (direção, não só o print do dia).
- OBRIGATÓRIO: conectar o fato da notícia com o cenário macro brasileiro SOMENTE quando fizer sentido editorial.
- OBRIGATÓRIO: cruzar com o ACERVO EDITORIAL — mencione se há tendência (ex.: "terceira notícia negativa sobre X esta semana").
- OBRIGATÓRIO: incorporar as 2 lentes analíticas abaixo em paráfrase original (sem citações literais de especialistas).
- OBRIGATÓRIO: dar orientação prática para o leitor comum (investidor iniciante ou chefe de família).
- Mínimo de 500 palavras no campo resumo_simples.
- Tom: jornalístico, analítico, acessível. Você domina tecnologia e finanças, com visão de livre mercado e empreendedorismo.

{macro_rules}

{lens_block}

## NOTÍCIA FONTE
Fonte RSS: {fonte}
Categoria sugerida: {tag_hint}
Título original: {title}
Conteúdo base (use como ponto de partida, não como texto a reescrever):
{content[:2500]}

## DADOS PARA CRUZAMENTO (use estes números na análise)
{market_context}

## ESTRUTURA DO ARTIGO (campo resumo_simples — 6 parágrafos separados por \\n\\n)
1. **Abertura**: O fato em uma frase forte + por que importa AGORA — número ligado ao TEMA (não force Selic se irrelevante).
2. **Contexto com dados**: Indicadores macro/cotações RELEVANTES — valores e tendência 7d/30d quando disponível.
3. **Cruzamento de fontes**: Relacione com o acervo editorial + 1 lente analítica aplicada ao caso.
4. **Análise aprofundada**: Causas e riscos — cada afirmação forte amarrada a um dado citado.
5. **Cenários**: 30/90/180 dias com âncoras numéricas variadas (não só juros).
6. **Guia prático**: 2-3 ações concretas + segunda lente analítica (disciplina, risco ou ciclo).

Retorne APENAS JSON válido (sem ```json):
{{
    "titulo_viral": "Título jornalístico, informativo e específico (máx. 90 caracteres). Evite clickbait vazio.",
    "resumo_simples": "Artigo completo de 6 parágrafos com \\n\\n entre eles. Mínimo 500 palavras.",
    "contexto_mercado": "Box de 3-4 frases com os principais números citados (variados; não só Selic).",
    "impacto_bolso": "3 frases diretas: impacto no bolso, na poupança/investimentos e no custo de vida.",
    "tag": "UMA de: {tags_list}",
    "sentimento": "UM de: Positivo, Negativo, Neutro",
    "dados_citados": ["lista dos dados numéricos que você efetivamente usou no texto"],
    "lentes_analiticas": [
        {{"escola": "nome curto da escola", "aplicacao": "2-3 frases originais aplicando a matéria"}}
    ],
    "pontos_chave": [
        {{
            "titulo": "Nome curto do ponto (ex: volatilidade do BTC)",
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
        "tabela_comparativa", "referencias_internas", "lentes_analiticas",
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


HOME_PRIORITY_ALTA = 100
HOME_PRIORITY_MEDIA = 50
HOME_PRIORITY_BAIXA = 20
HOME_HEADLINE_MIN_PRIORITY = 80


def compute_home_priority(ai_data: dict[str, Any] | None) -> int:
    """Pontuação editorial para manchete da home (maior = mais importante)."""
    if not ai_data:
        return 0
    urgencia = str(ai_data.get("urgencia") or "Média").strip().lower()
    if urgencia == "alta":
        score = HOME_PRIORITY_ALTA
    elif urgencia in ("média", "media"):
        score = HOME_PRIORITY_MEDIA
    else:
        score = HOME_PRIORITY_BAIXA
    if ai_data.get("imagem_url"):
        score += 5
    return min(score, HOME_PRIORITY_ALTA)


def compute_home_priority_from_json(raw: str | dict[str, Any] | None) -> int:
    if not raw:
        return 0
    try:
        obj = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return 0
    if not isinstance(obj, dict):
        return 0
    return compute_home_priority(obj)


def backfill_home_priority(client, limit: int = 300) -> int:
    """Preenche home_priority em matérias antigas a partir de dados_mercado.urgencia."""
    try:
        result = client.execute(
            """
            SELECT id, dados_mercado FROM news
            WHERE COALESCE(home_priority, 0) = 0
              AND dados_mercado IS NOT NULL AND dados_mercado != ''
            ORDER BY id DESC LIMIT ?
            """,
            [max(1, limit)],
        )
    except Exception as exc:
        print(f"   [home_priority] backfill ignorado: {exc}")
        return 0

    updated = 0
    for row in result.rows or []:
        priority = compute_home_priority_from_json(row[1])
        if priority <= 0:
            continue
        client.execute("UPDATE news SET home_priority = ? WHERE id = ?", [priority, row[0]])
        updated += 1
    if updated:
        print(f"   [home_priority] backfill: {updated} matéria(s) atualizada(s).")
    return updated


def refresh_article_market_data(article_id: int, add_update_note: bool = True) -> dict[str, Any] | None:
    """Compara cotações atuais com o snapshot da publicação — sem sobrescrever o período da análise."""
    client = get_db()
    result = client.execute(
        """
        SELECT id, titulo, tag, dados_mercado, contexto_editorial, versao_analise,
               COALESCE(NULLIF(published_at, ''), created_at) AS data_ref
        FROM news WHERE id = ?
        """,
        [article_id],
    )
    if not result.rows:
        client.close()
        return None

    row = result.rows[0]
    noticia_id, titulo, tag, raw_dados, contexto_editorial, versao, data_ref = (
        row[0], row[1], row[2], row[3], row[4], row[5], row[6]
    )
    versao = int(versao or 1)

    old_dados: dict[str, Any] = {}
    if raw_dados:
        try:
            old_dados = json.loads(raw_dados)
        except json.JSONDecodeError:
            pass

    # Garante snapshot do período da análise antes de qualquer comparação.
    as_of = parse_article_datetime(data_ref, (old_dados.get("cotacoes") or {}).get("coletado_em"))
    base = resolve_article_market_data(
        old_dados,
        published_at=data_ref,
        blocking_hist=True,
    )

    market_now = fetch_market_snapshot(blocking=True)
    bcb_now = fetch_bcb_snapshot(blocking=True)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Preserva originais
    if _has_market_payload(base.get("cotacoes")) and not _has_market_payload(base.get("cotacoes_publicacao")):
        base["cotacoes_publicacao"] = base["cotacoes"]
    if _has_market_payload(base.get("bcb")) and not _has_market_payload(base.get("bcb_publicacao")):
        base["bcb_publicacao"] = base["bcb"]
    if isinstance(base.get("historico"), dict) and (
        base["historico"].get("30d") or base["historico"].get("90d")
    ) and not base.get("historico_publicacao"):
        base["historico_publicacao"] = base["historico"]

    base["cotacoes_atuais"] = market_now
    base["bcb_atuais"] = bcb_now

    atualizacao = None
    if add_update_note and _has_market_payload(base.get("cotacoes_publicacao")):
        old_cot = base["cotacoes_publicacao"]
        changes = []
        for label, info in market_now.items():
            if label in ("coletado_em", "erro_cotacoes", "referencia") or not isinstance(info, dict):
                continue
            old_info = old_cot.get(label, {})
            if isinstance(old_info, dict) and old_info.get("cotacao") != info.get("cotacao"):
                changes.append(f"{label}: {old_info.get('cotacao', 'n/d')} → {info.get('cotacao', 'n/d')}")
        if changes:
            periodo = (as_of.strftime("%d/%m/%Y") if as_of else "a publicação")
            atualizacao = (
                f"Atualização em {agora}: desde {periodo}, "
                + f"as cotações mudaram — {'; '.join(changes[:4])}. "
                + f"Os gráficos e o painel principal continuam no período da análise."
            )

    if atualizacao:
        base["atualizacao"] = atualizacao

    # Mantém cotacoes/bcb/historico = período da análise (nunca troca pelo "hoje")
    base["cotacoes"] = base.get("cotacoes_publicacao") or base.get("cotacoes") or {}
    base["bcb"] = base.get("bcb_publicacao") or base.get("bcb") or {}
    if base.get("historico_publicacao"):
        base["historico"] = base["historico_publicacao"]

    _ = client.execute(
        """
        UPDATE news
        SET dados_mercado = ?, updated_at = ?, versao_analise = ?
        WHERE id = ?
        """,
        [json.dumps(base, ensure_ascii=False), agora, versao + 1, noticia_id],
    )
    client.close()
    return {
        "id": noticia_id,
        "titulo": titulo,
        "versao_analise": versao + 1,
        "atualizacao": atualizacao,
        "coletado_em": agora,
        "periodo_analise": as_of.strftime("%d/%m/%Y") if as_of else None,
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


def _news_link_exists(link: str) -> bool:
    if not link:
        return False
    try:
        return link in existing_news_links([link])
    except Exception:
        return False


def _slugify_tag(tag: str) -> str:
    raw = (tag or "economia").strip().lower()
    table = str.maketrans(
        {
            "á": "a", "à": "a", "ã": "a", "â": "a",
            "é": "e", "ê": "e",
            "í": "i",
            "ó": "o", "ô": "o", "õ": "o",
            "ú": "u",
            "ç": "c",
            " ": "-",
        }
    )
    slug = raw.translate(table)
    slug = re.sub(r"[^a-z0-9-]+ ", "", slug)
    return slug.strip("-") or "economia"


def _own_analysis_link(tag: str, seed: str = "") -> str:
    day = datetime.now().strftime("%Y%m%d")
    tag_slug = _slugify_tag(tag)
    digest = hashlib.sha256(f"{day}|{tag}|{seed}".encode()).hexdigest()[:8]
    return f"{OWN_ANALYSIS_LINK_PREFIX}{day}-{tag_slug}-{digest}"


def count_own_analyses_today() -> int:
    """Quantas análises próprias (internal://analise/) já foram publicadas hoje."""
    day = datetime.now().strftime("%Y%m%d")
    prefix = f"{OWN_ANALYSIS_LINK_PREFIX}{day}-"
    try:
        client = get_db()
        row = client.execute(
            "SELECT COUNT(*) FROM news WHERE link LIKE ?",
            [f"{prefix}%"],
        ).rows
        return int(row[0][0]) if row else 0
    except Exception as exc:
        print(f"   [analise-propria] Falha ao contar do dia: {exc}")
        return 0


def _fetch_recent_source_news(limit: int = 40) -> list[tuple]:
    """Notícias externas recentes do acervo (exclui guias e análises próprias)."""
    client = get_db()
    result = client.execute(
        """
        SELECT id, titulo, tag, sentimento, impacto, resumo, fonte, published_at
        FROM news
        WHERE link NOT LIKE 'internal://%'
        ORDER BY id DESC
        LIMIT ?
        """,
        [max(8, limit)],
    )
    return list(result.rows)


def _pick_own_analysis_angles(rows: list[tuple], count: int) -> list[dict[str, Any]]:
    """Escolhe ângulos distintos por tag a partir do acervo recente."""
    by_tag: dict[str, list[tuple]] = {}
    for row in rows:
        tag = str(row[2] or "Economia").strip()
        if tag not in VALID_TAGS:
            tag = "Economia"
        by_tag.setdefault(tag, []).append(row)

    # Prioriza tags com mais matéria recente e sentimento definido.
    ranked = sorted(
        by_tag.items(),
        key=lambda item: (len(item[1]), 1 if item[0] != "Economia" else 0),
        reverse=True,
    )

    angles: list[dict[str, Any]] = []
    for tag, items in ranked:
        if len(angles) >= count:
            break
        sample = items[:8]
        titles = [str(r[1] or "").strip() for r in sample if r[1]]
        if len(titles) < 2:
            continue
        sentiments = [str(r[3] or "Neutro") for r in sample]
        neg = sum(1 for s in sentiments if "negativ" in s.lower())
        pos = sum(1 for s in sentiments if "positiv" in s.lower())
        if neg >= pos and neg > 0:
            tone = "cautela"
        elif pos > neg:
            tone = "oportunidade"
        else:
            tone = "panorama"
        angles.append(
            {
                "tag": tag,
                "tone": tone,
                "items": sample,
                "titles": titles,
            }
        )

    # Se ainda faltam ângulos, faz cortes temáticos dentro de Economia.
    if len(angles) < count and "Economia" in by_tag:
        eco = by_tag["Economia"]
        chunks = [eco[i : i + 6] for i in range(0, min(len(eco), 18), 6)]
        for chunk in chunks:
            if len(angles) >= count:
                break
            titles = [str(r[1] or "").strip() for r in chunk if r[1]]
            if len(titles) < 2:
                continue
            if any(a["tag"] == "Economia" and a["titles"][:2] == titles[:2] for a in angles):
                continue
            angles.append(
                {
                    "tag": "Economia",
                    "tone": "panorama",
                    "items": chunk,
                    "titles": titles,
                }
            )

    return angles[:count]


def _build_own_analysis_brief(angle: dict[str, Any]) -> tuple[str, str]:
    """Monta título-semente e conteúdo sintético a partir do acervo."""
    tag = angle["tag"]
    tone = angle["tone"]
    items = angle["items"]
    day_label = datetime.now().strftime("%d/%m/%Y")

    tone_title = {
        "cautela": f"Radar {tag}: o que o acervo do dia sinaliza de risco",
        "oportunidade": f"Radar {tag}: sinais positivos no acervo desta semana",
        "panorama": f"Análise própria: panorama de {tag} em {day_label}",
    }
    title = tone_title.get(tone, f"Análise própria: {tag} — {day_label}")

    lines = [
        f"Esta é uma ANÁLISE EDITORIAL PRÓPRIA do portal Finanças News ({day_label}).",
        "NÃO existe uma única notícia RSS de origem — o editor cruza várias matérias já publicadas no acervo.",
        f"Categoria-foco: {tag}. Tom sugerido: {tone}.",
        "",
        "FATOS / MATÉRIAS DO ACERVO PARA CRUZAR (use como evidência, sem plágio):",
    ]
    for row in items:
        titulo = str(row[1] or "").strip()
        sentimento = str(row[3] or "Neutro").strip()
        impacto = str(row[4] or "").strip()
        fonte = str(row[6] or "").strip()
        when = str(row[7] or "").strip()
        resumo = str(row[5] or "").strip().replace("\n", " ")
        lines.append(
            f"- [{sentimento}] {titulo}"
            + (f" ({fonte}" + (f", {when}" if when else "") + ")" if fonte or when else "")
        )
        if impacto:
            lines.append(f"  Impacto registrado: {impacto[:280]}")
        if resumo:
            lines.append(f"  Trecho útil: {resumo[:420]}")

    lines.extend(
        [
            "",
            "INSTRUÇÃO ESPECIAL PARA ANÁLISE PRÓPRIA:",
            "- Produza um texto AUTORAL que une esses fios em uma tese editorial clara.",
            "- Use indicadores do painel SOMENTE quando relevantes; não repita Selic em toda análise.",
            "- Incorpore 2 lentes analíticas (escolas clássicas) em paráfrase original — sem citações literais.",
            "- Em cada parágrafo, amarre a interpretação a números variados (não só juros).",
            "- Explique o que muda para o investidor comum à luz do conjunto (não de uma só manchete).",
            "- Evite repetir títulos do acervo; sintetize e avance a análise.",
        ]
    )
    return title, "\n".join(lines)


def generate_own_analyses(count: int | None = None) -> list[dict[str, Any]]:
    """Gera análises editoriais próprias a partir do acervo (sem RSS).

    Consome cota Gemini de texto (e tenta capa). Respeita o mínimo diário
    configurado em ``ROBOT_OWN_ANALYSES`` (default 3): só gera o que ainda falta hoje.
    """
    target_day = get_robot_own_analyses_count() if count is None else max(0, min(int(count), 10))
    if target_day <= 0:
        print("   [analise-propria] Desativada (ROBOT_OWN_ANALYSES=0).")
        return []

    already = count_own_analyses_today()
    missing = max(0, target_day - already)
    if missing <= 0:
        print(f"   [analise-propria] Meta diária já atingida ({already}/{target_day}).")
        return []

    if not get_gemini_api_keys():
        print("   [analise-propria] Sem GOOGLE_API_KEY — abortando.")
        return []

    print(
        f"\n--- Análises próprias: faltam {missing} hoje "
        + f"(já={already}, meta={target_day}) ---"
    )

    source_rows = _fetch_recent_source_news(limit=max(24, missing * 10))
    if len(source_rows) < 4:
        print("   [analise-propria] Acervo insuficiente (<4 matérias externas).")
        return []

    angles = _pick_own_analysis_angles(source_rows, missing)
    if not angles:
        print("   [analise-propria] Não foi possível montar ângulos a partir do acervo.")
        return []

    market = fetch_market_snapshot()
    bcb = fetch_bcb_snapshot()
    historico = fetch_market_historical()
    generated: list[dict[str, Any]] = []

    for angle in angles:
        if _all_text_models_exhausted():
            print("   [analise-propria] Cota diária esgotada — interrompendo.")
            break

        tag = angle["tag"]
        seed_title, brief = _build_own_analysis_brief(angle)
        link = _own_analysis_link(tag, seed=seed_title + "|" + "|".join(angle["titles"][:3]))

        if existing_news_links([link]):
            print(f"   [analise-propria] Link já existe — pulando {link}")
            continue

        db_context = get_editorial_context(tag_hint=tag)
        data_context = format_data_context(market, bcb, db_context, historico, tag)
        print(f"   [analise-propria] Gerando ângulo {tag}/{angle['tone']}: {seed_title[:60]}...")

        ai_data = process_news_with_ai(
            seed_title,
            brief,
            OWN_ANALYSIS_FONTE,
            tag,
            data_context,
        )

        if ai_data is None and _all_text_models_exhausted():
            print("   [analise-propria] Cota esgotada após tentativa.")
            break
        if not ai_data:
            print("   [analise-propria] IA não retornou JSON — próximo ângulo.")
            continue

        out_tag = ai_data.get("tag", tag)
        if out_tag not in VALID_TAGS:
            out_tag = tag
            ai_data["tag"] = out_tag

        imagem_url = generate_article_image(
            ai_data.get("titulo_viral", seed_title),
            out_tag,
            link,
            ai_data.get("resumo_simples", ""),
            use_openai=False,
        )
        if imagem_url:
            print("   [analise-propria] Capa OK.")
        else:
            print("   [analise-propria] Sem capa nesta rodada.")

        published = datetime.now().strftime("%d/%m/%Y %H:%M")
        generated.append(
            {
                "original_link": link,
                "fonte": OWN_ANALYSIS_FONTE,
                "published_at": published,
                "imagem_url": imagem_url,
                "dados_mercado": _build_dados_mercado_payload(market, bcb, ai_data, historico),
                "contexto_editorial": ai_data.get("contexto_mercado", ""),
                "versao_analise": 1,
                **ai_data,
            }
        )
        print(f"   [analise-propria] OK: {ai_data.get('titulo_viral', seed_title)[:70]}")

    print(f"   [analise-propria] Lote: {len(generated)} análise(s) própria(s).")
    return generated


def fetch_and_process(max_per_feed: int | None = None, max_articles: int | None = None):
    """Varre feeds, gera análise + capa e prioriza artigos com imagem no lote."""
    noticias_processadas = []
    max_per_feed = max_per_feed if max_per_feed is not None else get_robot_max_per_feed()
    max_articles = max_articles if max_articles is not None else get_robot_max_articles()
    _exhausted_models_by_key.clear()
    _reset_image_quota_state()
    print(f"\n--- Iniciando Varredura: {datetime.now()} ---")
    print(f"   🧠 Modelos Gemini: {', '.join(get_gemini_modelos())}")
    print(f"   🖼️ Modelos de imagem: {', '.join(get_gemini_image_models())}")
    openai_models = get_openai_image_models() if get_openai_api_key() else []
    openai_label = ", ".join(openai_models) if openai_models else "(sem OPENAI_API_KEY)"
    print(f"   🖼️ Fallback OpenAI: {openai_label} (backfill; troca modelo em cota)")
    hf_models = get_hf_image_models() if get_hf_token() else []
    hf_label = ", ".join(hf_models) if hf_models else "(sem HF_TOKEN)"
    print(f"   🖼️ Fallback Hugging Face: {hf_label}")
    print(f"   🔑 Chaves Gemini: {len(get_gemini_api_keys())} (imagem prioriza 2→3→1)")
    print(f"   📰 Fontes: {len(RSS_FEEDS)} | até {max_per_feed}/feed | teto {max_articles}/rodada")

    market = fetch_market_snapshot()
    bcb = fetch_bcb_snapshot()
    historico = fetch_market_historical()
    print(f"   📊 Dados de mercado coletados: {len(market)} cotações, {len(bcb)} indicadores BCB")

    for feed_config in RSS_FEEDS:
        if len(noticias_processadas) >= max_articles:
            print(f"   🛑 Teto da rodada atingido ({max_articles} artigos).")
            break

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
            data_context = format_data_context(market, bcb, db_context, historico, tag_hint)

            entries = list(feed.entries[:max_per_feed])
            entry_links: list[str] = []
            for entry in entries:
                entry_link = str(getattr(entry, "link", "") or "")
                try:
                    from article_enrichment import clean_source_url

                    entry_link = clean_source_url(entry_link) or entry_link
                except Exception:
                    pass
                entry_links.append(entry_link)

            already_published = existing_news_links(entry_links)

            for entry, entry_link in zip(entries, entry_links):
                if len(noticias_processadas) >= max_articles:
                    break

                print(f"   📄 Encontrada: {entry.title[:60]}...")

                if not entry_link or entry_link in already_published:
                    print("   ⏭️ Já publicada — pulando (economiza cota).")
                    continue

                raw_content = extract_entry_content(entry)
                clean_text = clean_html(raw_content)

                if len(clean_text) < 80:
                    print("   ⚠️ Texto muito curto, pulando.")
                    continue

                ai_data = process_news_with_ai(entry.title, clean_text, fonte, tag_hint, data_context)

                if ai_data is None and _all_text_models_exhausted():
                    print("   🛑 Cota diária esgotada em todas as chaves/modelos — interrompendo varredura.")
                    noticias_processadas.sort(key=lambda n: 0 if n.get("imagem_url") else 1)
                    return noticias_processadas

                if not ai_data:
                    continue

                tag = ai_data.get("tag", tag_hint)
                if tag not in VALID_TAGS:
                    tag = tag_hint if tag_hint in VALID_TAGS else "Economia"
                    ai_data["tag"] = tag

                imagem_url = generate_article_image(
                    ai_data.get("titulo_viral", entry.title),
                    tag,
                    entry_link,
                    ai_data.get("resumo_simples", ""),
                    use_openai=False,
                )
                if imagem_url:
                    print("   🖼️ Capa OK — prioridade Discover.")
                else:
                    print("   ⚠️ Sem capa nesta rodada — backfill pode completar depois.")

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
                already_published.add(entry_link)
                print("   ✅ Processado com sucesso!")

        except Exception as e:
            print(f"   ❌ Erro Crítico: {e}")

    noticias_processadas.sort(key=lambda n: 0 if n.get("imagem_url") else 1)
    com_capa = sum(1 for n in noticias_processadas if n.get("imagem_url"))
    print(f"   📦 Lote: {len(noticias_processadas)} artigos ({com_capa} com capa).")
    return noticias_processadas


if __name__ == "__main__":
    print("🚀 Modo de Teste Manual Iniciado...")
    resultado = fetch_and_process(max_per_feed=1)
    print(f"\n📊 Total processado: {len(resultado)}")
    if resultado:
        print("🎉 SUCESSO! JSON gerado:")
        print(json.dumps(resultado[0], indent=2, ensure_ascii=False))