"""SEO: host canônico, meta clip, ISO com fuso, RSS RFC-822, OG raster."""
from __future__ import annotations

import os
from unittest.mock import patch

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from starlette.requests import Request

load_dotenv()
os.environ.setdefault("ROBO_TOKEN", "test-robo-token-local")
os.environ["USE_TURSO"] = "0"

import core
import main

FAKE_MARKET = {
    "coletado_em": "17/07/2026 08:00",
    "Dólar (USD/BRL)": {"cotacao": "R$ 5,10", "variacao_24h": "-0.25%"},
}
FAKE_BCB = {
    "Selic meta (% a.a.)": {"valor": "14.25", "data": "17/07/2026"},
    "IPCA acumulado 12 meses (%)": {"valor": "4.64", "data": "17/07/2026"},
}


def test_clip_meta_description_breaks_on_word():
    text = (
        "O pedido de expulsão protocolado contra Erick Crus, sócio com exatas 40% "
        "das cotas da Brasil Bitcoin, escancara um grave racha na cúpula da corretora após revelações"
    )
    clipped = main.clip_meta_description(text, limit=157)
    assert clipped.endswith("…")
    assert " após re…" not in clipped
    assert " " in clipped
    assert len(clipped) <= 158


def test_to_iso8601_adds_brt_offset():
    iso = main._to_iso8601("12/10/2026 18:37")
    assert iso is not None
    assert iso.endswith("-03:00")
    assert "2026-10-12T18:37:00" in iso


def test_to_rfc822_has_timezone_token():
    pub = main._to_rfc822("12/10/2026 18:37")
    assert "2026" in pub
    assert ("-" in pub[-6:] or "+" in pub[-6:] or "GMT" in pub)


def test_canonical_host_redirect_www_to_apex():
    scope = {
        "type": "http",
        "asgi": {"version": "3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/noticia/1",
        "raw_path": b"/noticia/1",
        "query_string": b"utm=1",
        "headers": [(b"host", b"www.financas-news.net.br")],
        "client": ("1.2.3.4", 443),
        "server": ("www.financas-news.net.br", 443),
    }
    request = Request(scope)
    with patch.object(main, "SITE_ORIGIN", "https://financas-news.net.br"):
        resp = main._canonical_host_redirect(request)
    assert resp is not None
    assert resp.status_code == 301
    assert resp.headers["location"].startswith("https://financas-news.net.br/noticia/1")


def test_canonical_host_skips_testserver():
    scope = {
        "type": "http",
        "asgi": {"version": "3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 80),
        "server": ("testserver", 80),
    }
    assert main._canonical_host_redirect(Request(scope)) is None


def test_home_uses_raster_og_and_logo():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        r = client.get("/")
        assert r.status_code == 200
        assert "/static/brand/og-default.png" in r.text
        assert "/static/brand/logo-512.png" in r.text
        assert "economia.svg" not in r.text.split("og:image")[1][:200]
        assert client.get("/static/brand/og-default.png").status_code == 200
        assert client.get("/static/brand/logo-512.png").status_code == 200


def test_sitemap_index_and_pages():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        idx = client.get("/sitemap.xml")
        assert idx.status_code == 200
        assert "sitemapindex" in idx.text
        assert "/sitemap-pages.xml" in idx.text
        pages = client.get("/sitemap-pages.xml")
        assert pages.status_code == 200
        assert "/mercado" in pages.text
        news = client.get("/sitemap-news/1.xml")
        assert news.status_code == 200
        assert "urlset" in news.text


if __name__ == "__main__":
    test_clip_meta_description_breaks_on_word()
    test_to_iso8601_adds_brt_offset()
    test_to_rfc822_has_timezone_token()
    test_canonical_host_redirect_www_to_apex()
    test_canonical_host_skips_testserver()
    test_home_uses_raster_og_and_logo()
    test_sitemap_index_and_pages()
    print("PASS: test_seo_fixes")
