from google import genai
from google.genai import types
import feedparser
import os
import base64
import ssl
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from dotenv import load_dotenv
import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

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
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

# Ordem: lite/barato primeiro; GA estável antes de preview/pro.
DEFAULT_GEMINI_IMAGE_MODELOS = [
    "gemini-3.1-flash-lite-image",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-lite-image-preview",
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image",
    "gemini-3-pro-image-preview",
]

_exhausted_models: set[str] = set()
# Cota de imagem por chave API (id curto → modelos esgotados nesta varredura).
_exhausted_image_models_by_key: dict[str, set[str]] = {}
# Modelos de imagem removidos permanentemente (404/descontinuados) até reiniciar.
_unavailable_image_models: set[str] = set()
# Cache de clients Gemini por fingerprint da chave.
_genai_clients_by_key: dict[str, Any] = {}
_genai_clients_lock = threading.Lock()


def _configure_ssl_certs() -> None:
    try:
        import certifi

        bundle = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    except ImportError:
        pass


def _gemini_http_options():
    if os.getenv("GEMINI_SSL_VERIFY", "true").lower() not in ("0", "false", "no"):
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return types.HttpOptions(
        client_args={"verify": ctx},
        async_client_args={"verify": ctx},
    )


def get_gemini_api_keys() -> list[str]:
    """Chaves Gemini em ordem de prioridade (primária → secundária → lista).

    Variáveis aceitas:
    - GOOGLE_API_KEY / GEMINI_API_KEY (chave 1)
    - GOOGLE_API_KEY_2 / GEMINI_API_KEY_2 (chave 2)
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
    _add(os.getenv("GOOGLE_API_KEYS") or os.getenv("GEMINI_API_KEYS"))
    return keys


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
        "url": "https://pox.globo.com/rss/valor",
        "fonte": "Valor Econômico",
        "tag_hint": "Economia",
    },
    {
        "url": "https://www.infomoney.com.br/mercados/feed/",
        "fonte": "InfoMoney Mercados",
        "tag_hint": "Ações",
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
        "url": "https://www.infomoney.com.br/economia/feed/",
        "fonte": "InfoMoney Economia",
        "tag_hint": "Inflação",
    },
    {
        "url": "https://www.infomoney.com.br/onde-investir/feed/",
        "fonte": "InfoMoney Onde Investir",
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


def warmup_market_caches() -> None:
    """Pré-aquece caches de mercado no startup para o 1º pageview não esperar rede."""
    try:
        fetch_market_snapshot(blocking=True)
    except Exception:
        pass
    try:
        fetch_bcb_snapshot(blocking=True)
    except Exception:
        pass
    try:
        fetch_market_historical()
    except Exception:
        pass
    try:
        fetch_sparkline_data(blocking=True)
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
            f"?start_date={start.strftime('%Y%m%d')}&end_date={day_key}"
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
            f"?formato=json&dataInicial={start.strftime('%d/%m/%Y')}"
            f"&dataFinal={as_of.strftime('%d/%m/%Y')}"
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
                f"?start_date={start.strftime('%Y%m%d')}&end_date={day_key}"
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
                f"?formato=json&dataInicial={start.strftime('%d/%m/%Y')}"
                f"&dataFinal={as_of.strftime('%d/%m/%Y')}"
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
    sign = "+" if (pct or 0) >= 0 else ""
    past_txt = f"{past:.4g}".replace(".", ",") if isinstance(past, float) else str(past)
    bits = [f"{sign}{pct}% vs ~{delta.get('dias')}d", f"de {past_txt}{suffix}"]
    if data:
        bits.append(f"({data})")
    return " ".join(bits)


def format_data_context(market, bcb, db_context, historico=None, tag_hint: str = "Economia"):
    """Monta bloco de dados para injetar no prompt da IA (painel fixo + tendência)."""
    hist = historico or {}
    lines = [
        "=== PAINEL OBRIGATÓRIO (cite Selic, IPCA 12m e dólar em TODA análise) ===",
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
                f"tendência 7d: {_format_delta_line(d7)} | 30d: {_format_delta_line(d30)}"
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
            f"7d: {_format_delta_line(d7)} | 30d: {_format_delta_line(d30)}"
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


def get_gemini_image_models() -> list[str]:
    raw = os.getenv("GEMINI_IMAGE_MODELOS", "")
    if raw.strip():
        return [m.strip() for m in raw.split(",") if m.strip()]
    # Imagen 4 foi descontinuado — usar Nano Banana / Gemini Image (GA + fallbacks).
    return DEFAULT_GEMINI_IMAGE_MODELOS.copy()


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


def _is_image_model_unavailable(exc: Exception) -> bool:
    msg = str(exc)
    return (
        "NOT_FOUND" in msg
        or "no longer available" in msg
        or "is not found" in msg
        or "not supported for generateContent" in msg
    )


def get_image_provider() -> str:
    """Resolve o provedor de imagem.

    Em produção (Render), sempre usa Gemini — o Cursor SDK só funciona localmente.
    Localmente, o padrão é ``auto`` (Cursor se houver chave, senão Gemini).
    """
    raw = os.getenv("IMAGE_PROVIDER", "").strip().lower()
    on_render = bool(os.getenv("RENDER"))

    if raw not in {"cursor", "gemini", "auto", ""}:
        raw = ""

    if on_render:
        # Cursor não roda no Render; auto/cursor/vazio → gemini.
        if raw in {"", "auto", "cursor"}:
            return "gemini"
        return raw

    if raw in {"cursor", "gemini", "auto"}:
        return raw
    return "auto"


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
        from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions
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
        f"Descricao: {prompt}\n\n"
        "Requisitos obrigatorios:\n"
        "- Proporcao 16:9\n"
        "- Sem texto, letras, logos ou marcas d'agua\n"
        f"- Salve o arquivo exatamente em: {output_png.resolve()}\n"
        "- Se nao conseguir PNG, salve em JPG no mesmo diretorio com o mesmo nome base\n\n"
        "Ao concluir, responda apenas: SAVED"
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
                path.replace(target)
                path = target
        return f"/media/articles/{path.name}"

    print("   [img/cursor] Agente concluiu, mas nenhum arquivo de imagem foi encontrado.")
    return None


def _generate_article_image_gemini(prompt: str, slug: str) -> str | None:
    keys = get_gemini_api_keys()
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
                f"(cota: {sorted(exhausted)} | indisponiveis: {sorted(_unavailable_image_models)})."
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
                    print(f"   [img/gemini] Modelo indisponivel, removendo da fila: {model}")
                elif _is_image_quota_error(e):
                    exhausted.add(model)
                    print(
                        f"   [img/gemini] Cota esgotada em {model} (chave {key_index}) "
                        "— proximo modelo/chave."
                    )
                print(f"   [img/gemini] Falha ({model}, chave {key_index}): {e}")
                continue

    return None


def generate_article_image(
    title: str,
    tag: str,
    link: str,
    resumo: str = "",
    article_id: int | None = None,
) -> str | None:
    """Gera capa editorial; retorna URL pública ou None em caso de falha."""
    slug = _article_image_slug(link, article_id)
    existing = _resolve_existing_article_image(slug)
    if existing:
        return existing

    prompt = _build_image_prompt(title, tag, resumo)
    provider = get_image_provider()
    use_cursor = provider in {"cursor", "auto"} and bool(os.getenv("CURSOR_API_KEY", "").strip())
    use_gemini = provider in {"gemini", "auto"} and bool(get_gemini_api_keys())

    if use_cursor:
        url = _generate_article_image_cursor(prompt, slug)
        if url:
            print(f"   [img] Imagem salva: {url}")
            return url
        if provider == "cursor":
            print("   [img] Imagem nao gerada — artigo seguira sem capa.")
            return None

    if use_gemini:
        url = _generate_article_image_gemini(prompt, slug)
        if url:
            return url

    print("   [img] Imagem nao gerada — artigo seguira sem capa.")
    return None


def backfill_missing_images(limit: int = 10) -> dict[str, Any]:
    """Gera capas para artigos que ainda nao possuem imagem_url."""
    _reset_image_quota_state()
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
- PROIBIDO: parágrafo só com opinião genérica sem número concreto dos DADOS DE MERCADO.
- OBRIGATÓRIO: citar Selic, IPCA (12 meses) e dólar (pelo menos uma vez no artigo), com o valor fornecido.
- OBRIGATÓRIO: citar pelo menos 1 cotação extra relevante à categoria (ex.: BTC em Cripto, EUR em Dólar).
- OBRIGATÓRIO: em CADA um dos 6 parágrafos do resumo_simples, amarrar a interpretação a pelo menos 1 número citado (ex.: "com a Selic a X%...", "o dólar a R$ Y...").
- OBRIGATÓRIO: quando houver tendência 7d/30d nos dados, usar em pelo menos 2 parágrafos (mostrar direção, não só o print do dia).
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
1. **Abertura**: O fato em uma frase forte + por que importa AGORA — cite 1 número do painel.
2. **Contexto com dados**: Selic + IPCA e/ou câmbio — valores e tendência 7d/30d quando disponível.
3. **Cruzamento de fontes**: Relacione com o acervo editorial + 1 cotação/indicador.
4. **Análise aprofundada**: Causas e riscos — cada afirmação forte amarrada a um dado citado.
5. **Cenários**: 30/90/180 dias com âncoras numéricas (juros, inflação ou câmbio).
6. **Guia prático**: 2-3 ações concretas ligadas aos números do cenário atual.

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
                f"as cotações mudaram — {'; '.join(changes[:4])}. "
                f"Os gráficos e o painel principal continuam no período da análise."
            )

    if atualizacao:
        base["atualizacao"] = atualizacao

    # Mantém cotacoes/bcb/historico = período da análise (nunca troca pelo "hoje")
    base["cotacoes"] = base.get("cotacoes_publicacao") or base.get("cotacoes") or {}
    base["bcb"] = base.get("bcb_publicacao") or base.get("bcb") or {}
    if base.get("historico_publicacao"):
        base["historico"] = base["historico_publicacao"]

    client.execute(
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


def fetch_and_process(max_per_feed=2):
    noticias_processadas = []
    _exhausted_models.clear()
    _reset_image_quota_state()
    print(f"\n--- Iniciando Varredura: {datetime.now()} ---")
    print(f"   🧠 Modelos Gemini: {', '.join(get_gemini_modelos())}")
    print(f"   🖼️ Modelos de imagem: {', '.join(get_gemini_image_models())}")
    print(f"   🔑 Chaves Gemini: {len(get_gemini_api_keys())}")

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
            data_context = format_data_context(market, bcb, db_context, historico, tag_hint)

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
                    try:
                        from article_enrichment import clean_source_url

                        entry_link = clean_source_url(entry_link) or entry_link
                    except Exception:
                        pass
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