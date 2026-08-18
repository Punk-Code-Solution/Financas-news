"""Canônicas, links internos e robots — mitigação GSC ?lang=pt."""
from __future__ import annotations

import os
import re

from dotenv import load_dotenv
from starlette.requests import Request

load_dotenv()
os.environ["USE_LOCAL_DB"] = "1"
os.environ.setdefault("LOCAL_DATABASE_PATH", os.path.join(".", ".tmp-i18n-test.db"))
os.environ.setdefault("ROBO_TOKEN", "test-robo-token-local")

from fastapi.testclient import TestClient

from i18n import lang_switch_url, localized_path
import core
import main
from db import ensure_schema, get_db, reset_db_client
from unittest.mock import patch

reset_db_client()
ensure_schema(get_db(), force=True)

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


def test_lang_switch_url_uses_idioma_route():
    pt = lang_switch_url(_request("/", "lang=en"), "pt")
    assert pt.startswith("/idioma/pt")
    assert "next=" in pt
    en = lang_switch_url(_request("/mercado", "categoria=Juros"), "en")
    assert en.startswith("/idioma/en")
    assert "next=" in en
    ja = lang_switch_url(_request("/mercado", ""), "ja")
    assert ja.startswith("/idioma/ja")


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
    assert "Disallow: /idioma" in body


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
        assert "/idioma/pt" in r.text


def test_idioma_pt_overrides_en_cookie_and_accept_language():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        client.cookies.set("lang", "en")
        r = client.get(
            "/idioma/pt",
            params={"next": "/"},
            headers={"Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.cookies.get("lang") == "pt"
        location = r.headers.get("location") or ""
        assert location.endswith("/")
        assert "lang=" not in location

        r2 = client.get("/", headers={"Accept-Language": "en-US,en;q=0.9"})
        assert r2.status_code == 200
        assert 'lang="pt-BR"' in r2.text
        assert "/idioma/en" in r2.text
        assert "/idioma/ja" in r2.text


def test_idioma_en_redirects_with_lang_query():
    client = TestClient(main.app)
    r = client.get(
        "/idioma/en",
        params={"next": "/mercado"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.cookies.get("lang") == "en"
    location = r.headers.get("location") or ""
    assert "/mercado" in location
    assert "lang=en" in location


def test_home_switcher_uses_idioma_route():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        r = client.get("/")
        assert r.status_code == 200
        assert 'href="/idioma/en' in r.text
        assert 'href="/idioma/ja' in r.text
        assert 'href="/idioma/pt' in r.text
