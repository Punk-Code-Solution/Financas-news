"""Testes de feed RSS/Atom e newsletter (envio mockado)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from dotenv import load_dotenv

load_dotenv()
os.environ["ROBO_TOKEN"] = "test-robo-token-local"
os.environ["NEWSLETTER_ENABLED"] = "true"

from fastapi.testclient import TestClient

import core
import main
import newsletter_service as ns

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
        assert "Clareza Capital" in r.text
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
            return_value={"ok": True, "recipients": 1, "items": 2},
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


def test_newsletter_from_uses_clareza_display_name():
    with patch.dict(os.environ, {"NEWSLETTER_FROM": "news@example.com"}, clear=False):
        assert ns.newsletter_from() == "Clareza Capital <news@example.com>"


def test_daily_digest_caps_at_two_alta_and_skips_empty():
    now = datetime.now()
    recent = (now - timedelta(hours=2)).strftime("%d/%m/%Y %H:%M")
    long_resumo = "x" * 220
    rows = [
        (1, "Alta 1", long_resumo, "Juros", 100, recent),
        (2, "Alta 2", long_resumo, "Câmbio", 100, recent),
        (3, "Alta 3", long_resumo, "Bolsa", 100, recent),
        (4, "Média", long_resumo, "Economia", 50, recent),
    ]
    fake_client = MagicMock()
    fake_client.execute.return_value = SimpleNamespace(rows=rows)

    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
    ):
        digest = ns.build_daily_digest(fake_client)
    assert digest["skip_send"] is False
    assert len(digest["items"]) == 2
    assert "Clareza Capital" in digest["subject"]
    assert "Clareza Capital" in digest["html"]
    assert "/privacidade" in digest["html"]
    assert "Outras análises" not in digest["html"]

    empty_client = MagicMock()
    empty_client.execute.return_value = SimpleNamespace(rows=[])
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
    ):
        empty = ns.build_daily_digest(empty_client)
    assert empty["skip_send"] is True
    assert empty["items"] == []

    with patch.object(ns, "build_daily_digest", return_value=empty):
        sent = ns.send_daily_digest(MagicMock())
    assert sent.get("skipped") is True
    assert sent.get("ok") is True


def test_urgency_alert_branding():
    payload = ns.build_urgency_alert(9, "Copom eleva Selic", "Juros", "Resumo curto.", 100)
    assert payload["subject"].startswith("Clareza Capital:")
    assert "Clareza Capital" in payload["html"]
    assert "/privacidade" in payload["html"]
    assert "Finanças News" not in payload["html"]


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
        test_newsletter_from_uses_clareza_display_name,
        test_daily_digest_caps_at_two_alta_and_skips_empty,
        test_urgency_alert_branding,
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
