"""Canônicas, links internos e robots — mitigação GSC ?lang=pt."""
from __future__ import annotations

import os
import re

from dotenv import load_dotenv
from starlette.requests import Request

load_dotenv()
os.environ.setdefault("ROBO_TOKEN", "test-robo-token-local")

from fastapi.testclient import TestClient

from i18n import lang_switch_url, localized_path
import core
import main
from unittest.mock import patch

FAKE_MARKET = {
    "coletado_em": "17/07/2026 08:00",
    "Dólar (USD/BRL)": {"cotacao": "R$ 5,10", "variacao_24h": "-0.25%"},
}
FAKE_BCB = {
    "Selic meta (% a.a.)": {"valor": "14.25", "data": "17/07/2026"},
    "IPCA acumulado 12 meses (%)": {"valor": "4.64", "data": "17/07/2026"},
}


def _canonical_href(html: str) -> str:
    match = re.search(r'rel="canonical" href="([^"]+)"', html)
    assert match, "canônica ausente no HTML"
    return match.group(1)


def _request(path: str = "/", query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": [],
            "client": ("127.0.0.1", 123),
            "server": ("test", 80),
        }
    )


def test_localized_path_pt_is_clean():
    assert localized_path("/noticia/12", "pt") == "/noticia/12"
    assert localized_path("/", "pt") == "/"
    assert localized_path("/?categoria=Juros", "pt") == "/?categoria=Juros"
    assert localized_path("/mercado", "") == "/mercado"


def test_localized_path_en_ja_appends_lang():
    assert localized_path("/noticia/12", "en") == "/noticia/12?lang=en"
    assert localized_path("/?categoria=Juros", "ja") == "/?categoria=Juros&lang=ja"
    assert localized_path("/mercado", "en") == "/mercado?lang=en"


def test_lang_switch_url_pt_strips_param():
    assert lang_switch_url(_request("/", "lang=en"), "pt") == "/"
    assert lang_switch_url(_request("/mercado", "lang=pt"), "pt") == "/mercado"
    assert lang_switch_url(_request("/mercado", ""), "en") == "/mercado?lang=en"
    assert lang_switch_url(_request("/mercado", "categoria=Juros"), "ja") == (
        "/mercado?categoria=Juros&lang=ja"
    )


def test_robots_blocks_lang_pt_allows_en_ja():
    client = TestClient(main.app)
    r = client.get("/robots.txt")
    assert r.status_code == 200
    body = r.text
    assert "Disallow: /*?lang=pt" in body
    assert "Disallow: /*?*lang=pt" in body
    assert "Allow: /*?lang=en" in body
    assert "Allow: /*?lang=ja" in body
    assert "Disallow: /colunista" in body
    assert "Disallow: /admin/" in body


def test_pt_home_does_not_emit_lang_pt_links():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        r = client.get("/")
        assert r.status_code == 200
        assert "?lang=pt" not in r.text
        href = _canonical_href(r.text)
        assert href.endswith("/")
        assert "lang=" not in href


def test_lang_pt_query_still_canonicalizes_to_clean_url():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        r = client.get("/?lang=pt")
        assert r.status_code == 200
        href = _canonical_href(r.text)
        assert href.endswith("/")
        assert "lang=" not in href
        assert "?lang=pt" not in r.text


def test_en_home_keeps_lang_param_not_pt():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        r = client.get("/?lang=en")
        assert r.status_code == 200
        assert "?lang=en" in r.text
        assert "?lang=pt" not in r.text
        href = _canonical_href(r.text)
        assert href.endswith("/")
        assert "lang=" not in href
