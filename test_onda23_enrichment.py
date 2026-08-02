"""Testes ONDA 2/3: radar, macro-watch, /mercado, UX artigo, tradução, afiliados."""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv()
os.environ["ROBO_TOKEN"] = "test-robo-token-local"

from fastapi.testclient import TestClient

import core
import main
import monetization

FAKE_MARKET = {
    "coletado_em": "02/08/2026 10:00",
    "Dólar (USD/BRL)": {
        "cotacao": "R$ 5,10",
        "variacao_24h": "-0.25%",
    },
    "Bitcoin (BTC/BRL)": {
        "cotacao": "R$ 350.000,00",
        "variacao_24h": "+1.10%",
    },
}
FAKE_BCB = {
    "Selic meta (% a.a.)": {"valor": "14.25", "data": "31/07/2026"},
    "IPCA acumulado 12 meses (%)": {"valor": "4.64", "data": "15/07/2026"},
}
FAKE_HIST = {
    "30d": {
        "Dólar (USD/BRL)": {"labels": ["01/07", "15/07"], "values": [5.1, 5.2]},
        "Bitcoin (BTC/BRL)": {"labels": ["01/07", "15/07"], "values": [300000, 320000]},
        "Selic meta (% a.a.)": {"labels": ["01/07", "15/07"], "values": [14.25, 14.25]},
        "IPCA 12 meses (%)": {"labels": ["01/07", "15/07"], "values": [4.5, 4.64]},
    },
    "90d": {},
    "coletado_em": "02/08/2026 10:00",
}
FAKE_SPARK = {"usd": [5.0, 5.1, 5.05], "btc": [300000, 310000]}


def _client():
    return TestClient(main.app)


def test_estimate_reading_minutes():
    assert core.estimate_reading_minutes("") == 1
    text = " ".join(["palavra"] * 400)
    assert core.estimate_reading_minutes(text) == 2


def test_awesome_daily_url_requires_days_for_range():
    """Sem /{days} no path a AwesomeAPI devolve 1 ponto (linha invisível no Chart.js)."""
    url = core._awesome_daily_url(
        "USD-BRL",
        days=30,
        start_date="20260703",
        end_date="20260802",
    )
    assert "/json/daily/USD-BRL/30?" in url
    assert "start_date=20260703" in url
    assert "end_date=20260802" in url
    assert core._awesome_daily_url("BTC-BRL", days=7).endswith("/BTC-BRL/7")


def test_parse_awesome_daily_points_aligns_labels_values():
    raw = [
        {"bid": "5.10", "timestamp": "1785531571"},  # mais recente
        {"bid": "5.05", "timestamp": "1785455978"},
        {"bid": None, "timestamp": "1785368934"},  # ignorado
    ]
    points = core._parse_awesome_daily_points(raw)
    assert len(points) == 2
    labels = [p[0] for p in points]
    values = [p[1] for p in points]
    assert len(labels) == len(values)
    assert values[0] == 5.05
    assert values[-1] == 5.10


def test_mercado_page():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_market_historical", return_value=FAKE_HIST),
        patch.object(core, "fetch_sparkline_data", return_value=FAKE_SPARK),
    ):
        r = _client().get("/mercado")
        assert r.status_code == 200
        assert "14.25" in r.text
        assert "chart-usd" in r.text
        assert "Chart" in r.text or "chart.js" in r.text.lower() or "cdn.jsdelivr.net" in r.text


def test_radar_requires_auth():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value=FAKE_SPARK),
    ):
        r = _client().get("/api/radar-semanal")
        assert r.status_code == 401


def test_radar_semanal_mocked():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value=FAKE_SPARK),
        patch.object(core, "generate_weekly_radar", return_value=[]),
        patch.object(main, "_persist_generated_news", return_value=0),
    ):
        r = _client().get(
            "/api/radar-semanal",
            headers={"Authorization": f"Bearer {os.environ['ROBO_TOKEN']}"},
        )
        assert r.status_code == 200
        assert r.json().get("status") == "Sucesso"


def test_macro_watch_requires_auth():
    r = _client().get("/api/macro-watch")
    assert r.status_code == 401


def test_macro_watch_mocked():
    with (
        patch.object(
            core,
            "run_macro_watch",
            return_value={"changes": [], "current": {}, "generated": []},
        ),
        patch.object(main, "_persist_generated_news", return_value=0),
    ):
        r = _client().get(
            "/api/macro-watch",
            headers={"Authorization": f"Bearer {os.environ['ROBO_TOKEN']}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "Sucesso"
        assert "changes" in body


def test_traduzir_pendentes_auth():
    r = _client().get("/api/traduzir-pendentes")
    assert r.status_code == 401


def test_traduzir_pendentes_mocked():
    with patch.object(
        core,
        "translate_pending_articles",
        return_value={"ok": True, "scanned": 0, "translated": 0, "errors": []},
    ):
        r = _client().get(
            "/api/traduzir-pendentes",
            headers={"Authorization": f"Bearer {os.environ['ROBO_TOKEN']}"},
        )
        assert r.status_code == 200
        assert r.json().get("translated") == 0


def test_contextual_affiliate_copy():
    with patch.dict(os.environ, {"AFFILIATE_BINANCE_URL": "https://example.com/ref"}, clear=False):
        item = monetization.get_contextual_affiliate("Cripto")
        assert item is not None
        assert item["url"] == "https://example.com/ref"
        assert "cripto" in str(item["titulo"]).lower() or "Cripto" in str(item["titulo"])


def test_contextual_affiliate_requires_http_url():
    """Sem URL http(s) real (vazio, null, texto) → None; com URL → aparece."""
    cleared = {
        "AFFILIATE_BINANCE_URL": "",
        "AFFILIATE_XP_URL": "null",
        "AFFILIATE_MERCADO_BITCOIN_URL": "none",
        "AFFILIATE_BTG_URL": "  ",
    }
    with patch.dict(os.environ, cleared, clear=False):
        assert monetization.get_contextual_affiliate("Cripto") is None
        assert monetization.get_contextual_affiliate("Ações") is None
        assert monetization.get_contextual_affiliate("Juros") is None
        cfg = monetization.get_monetization_config()
        assert cfg["affiliates"] == []

    with patch.dict(
        os.environ,
        {
            **cleared,
            "AFFILIATE_BINANCE_URL": "null",
            "SPONSORED_SLOT_URL": "null",
            "AMAZON_AFFILIATE_TAG": "null",
        },
        clear=False,
    ):
        cfg = monetization.get_monetization_config()
        assert cfg["affiliates"] == []
        assert cfg["sponsored"]["enabled"] is False
        assert cfg["amazon_books_url"] == ""

    with patch.dict(os.environ, {"AFFILIATE_XP_URL": "https://example.com/xp"}, clear=False):
        item = monetization.get_contextual_affiliate("Economia")
        assert item is not None
        assert item["url"] == "https://example.com/xp"
        assert item["id"] == "xp"


def test_home_has_mercado_link():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value=FAKE_SPARK),
    ):
        r = _client().get("/")
        assert r.status_code == 200
        assert "/mercado" in r.text


def test_article_reading_time_and_refs():
    assert core.estimate_reading_minutes(" ".join(["x"] * 200)) == 1
    refs = main._internal_refs_from_market(
        {
            "referencias_internas": [
                {"noticia_id": 10, "titulo": "IPCA em alta", "trecho": "Inflação pressiona"},
                {"noticia_id": 10, "titulo": "dup", "trecho": "ignore"},
                {"titulo": "sem id", "trecho": "x"},
            ]
        }
    )
    assert len(refs) == 1
    assert refs[0]["id"] == 10
    assert "IPCA" in refs[0]["titulo"]

    row = (
        1,
        "Titulo PT",
        "Resumo PT",
        "impacto",
        "link",
        "Economia",
        "Neutro",
        "01/01/2026",
        "Fonte",
        None,
        None,
        None,
        None,
        None,
        1,
        "Title EN",
        "Summary EN",
        "タイトル",
        "要約",
    )
    en = main._apply_article_locale(row, "en")
    assert en[1] == "Title EN" and en[2] == "Summary EN"
    ja = main._apply_article_locale(row, "ja")
    assert ja[1] == "タイトル" and ja[2] == "要約"
    assert main._article_has_translation(row, "en")
    assert main._article_has_translation(row, "ja")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tests = [
        test_estimate_reading_minutes,
        test_awesome_daily_url_requires_days_for_range,
        test_parse_awesome_daily_points_aligns_labels_values,
        test_mercado_page,
        test_radar_requires_auth,
        test_radar_semanal_mocked,
        test_macro_watch_requires_auth,
        test_macro_watch_mocked,
        test_traduzir_pendentes_auth,
        test_traduzir_pendentes_mocked,
        test_contextual_affiliate_copy,
        test_contextual_affiliate_requires_http_url,
        test_home_has_mercado_link,
        test_article_reading_time_and_refs,
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
