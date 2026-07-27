"""Testes de feed RSS/Atom e newsletter (envio mockado)."""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv()
os.environ["ROBO_TOKEN"] = "test-robo-token-local"
os.environ["NEWSLETTER_ENABLED"] = "true"

from fastapi.testclient import TestClient

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


def test_feed_xml_structure():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        r = client.get("/feed.xml")
        assert r.status_code == 200
        assert "<rss" in r.text and "<channel>" in r.text
        assert "Finanças News" in r.text
        assert r.headers.get("content-type", "").startswith("application/rss+xml")


def test_feed_atom_structure():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        r = client.get("/feed.atom")
        assert r.status_code == 200
        assert "<feed" in r.text and "xmlns=\"http://www.w3.org/2005/Atom\"" in r.text


def test_robots_references_feed():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        r = client.get("/robots.txt")
        assert "/feed.xml" in r.text


def test_category_intro_block():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        r = client.get("/", params={"categoria": "Juros"})
        assert r.status_code == 200
        assert "CollectionPage" in r.text
        assert "ItemList" in r.text
        assert "Selic" in r.text or "Copom" in r.text
        assert "/artigo/selic" in r.text


def test_newsletter_digest_requires_auth():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        r = client.get("/api/newsletter-digest")
        assert r.status_code == 401


def test_newsletter_digest_send_mocked():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
        patch("main.is_send_configured", return_value=True),
        patch(
            "main.send_weekly_digest",
            return_value={"ok": True, "recipients": 1, "items": 5},
        ),
    ):
        client = TestClient(main.app)
        r = client.get(
            "/api/newsletter-digest",
            headers={"Authorization": f"Bearer {os.environ['ROBO_TOKEN']}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True


def test_csp_header_present():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        client = TestClient(main.app)
        r = client.get("/")
        csp = r.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "pagead2.googlesyndication.com" in csp
        assert "cdn.jsdelivr.net" in csp


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tests = [
        test_feed_xml_structure,
        test_feed_atom_structure,
        test_robots_references_feed,
        test_category_intro_block,
        test_newsletter_digest_requires_auth,
        test_newsletter_digest_send_mocked,
        test_csp_header_present,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {fn.__name__}: {exc}")
    raise SystemExit(1 if failed else 0)
