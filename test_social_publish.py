"""Testes de publicação social (LinkedIn + Instagram)."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from dotenv import load_dotenv

load_dotenv()
os.environ["ROBO_TOKEN"] = "test-robo-token-local"
os.environ.pop("INSTAGRAM_ACCESS_TOKEN", None)
os.environ.pop("META_ACCESS_TOKEN", None)
os.environ.pop("INSTAGRAM_BUSINESS_ACCOUNT_ID", None)
os.environ.pop("INSTAGRAM_ACCOUNT_ID", None)

from fastapi.testclient import TestClient

import core
import main
import social_publish as sp

FAKE_MARKET = {
    "coletado_em": "11/08/2026 08:00",
    "Dólar (USD/BRL)": {"cotacao": "R$ 5,10", "variacao_24h": "-0.25%"},
}
FAKE_BCB = {
    "Selic meta (% a.a.)": {"valor": "14.25", "data": "11/08/2026"},
    "IPCA acumulado 12 meses (%)": {"valor": "4.64", "data": "11/08/2026"},
}


def _client():
    return TestClient(main.app)


def test_linkedin_post_follows_pattern():
    text = sp.build_linkedin_post(
        titulo="Copom eleva Selic em 0,25 ponto",
        resumo="O Copom elevou a Selic e o mercado reprecifica o ciclo de juros no Brasil.",
        tag="Juros",
        url="https://financas-news.net.br/noticia/42",
    )
    assert text.startswith("**Copom eleva Selic")
    assert "O que você encontra:" in text
    assert "• " in text
    assert "Acesse: https://financas-news.net.br/noticia/42" in text
    assert "Saiba mais:" in text
    assert "Contato:" in text
    assert "#ClarezaCapital" in text
    assert "#Selic" in text


def test_instagram_caption_is_plain_text_ready():
    text = sp.build_instagram_caption(
        titulo="Dólar fecha em alta com exterior",
        resumo="O dólar avançou com aversão global e o câmbio doméstico reagiu.",
        tag="Dólar",
        url="https://financas-news.net.br/noticia/7",
    )
    assert not text.startswith("**")
    assert "O que você encontra:" in text
    assert "Acesse: https://financas-news.net.br/noticia/7" in text
    assert "#ClarezaCapital" in text
    assert "#Dolar" in text
    assert len(text) < 2200


def test_absolute_image_url_requires_https():
    assert sp.absolute_image_url("https://cdn.example/cover.jpg") == "https://cdn.example/cover.jpg"
    assert sp.absolute_image_url("http://cdn.example/cover.jpg") == "https://cdn.example/cover.jpg"
    assert sp.absolute_image_url("/media/articles/a.jpg").startswith("https://")
    assert sp.absolute_image_url("") is None


def test_social_publish_requires_auth():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        r = _client().get("/api/social-publish")
        assert r.status_code == 401


def test_social_publish_drafts_without_instagram_creds():
    fake_db = MagicMock()
    fake_db.execute.side_effect = [
        # fetch candidates
        SimpleNamespace(
            rows=[
                (
                    99,
                    "Selic sobe e crédito encarece",
                    "Resumo longo o bastante para virar post social no portal Clareza Capital.",
                    "Juros",
                    90,
                    "11/08/2026 10:00",
                    "https://images.pexels.com/photos/1/cover.jpg",
                )
            ]
        ),
        # linkedin upsert
        SimpleNamespace(rows=[]),
        # instagram upsert draft
        SimpleNamespace(rows=[]),
    ]

    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
        patch.object(main, "get_db", return_value=fake_db),
        patch.object(sp, "is_instagram_publish_configured", return_value=False),
    ):
        r = _client().get(
            "/api/social-publish",
            headers={"Authorization": "Bearer test-robo-token-local"},
            params={"news_id": 99, "force": 1},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "Sucesso"
        assert body["count"] == 1
        channels = body["items"][0]["channels"]
        assert channels["linkedin"]["status"] == "draft"
        assert "O que você encontra:" in channels["linkedin"]["caption"]
        assert channels["instagram"]["status"] == "draft"
        assert "Configure INSTAGRAM_ACCESS_TOKEN" in channels["instagram"]["note"]
        assert fake_db.execute.call_count == 3

def test_instagram_publish_calls_graph_api():
    create_resp = MagicMock(status_code=200)
    create_resp.json.return_value = {"id": "creation-1"}
    create_resp.text = '{"id":"creation-1"}'

    status_resp = MagicMock(status_code=200)
    status_resp.json.return_value = {"status_code": "FINISHED"}

    publish_resp = MagicMock(status_code=200)
    publish_resp.json.return_value = {"id": "media-9"}
    publish_resp.text = '{"id":"media-9"}'

    with (
        patch.dict(
            os.environ,
            {
                "INSTAGRAM_ACCESS_TOKEN": "token-test",
                "INSTAGRAM_BUSINESS_ACCOUNT_ID": "17841400000000000",
            },
            clear=False,
        ),
        patch.object(sp.requests, "post", side_effect=[create_resp, publish_resp]) as post_mock,
        patch.object(sp.requests, "get", return_value=status_resp),
        patch.object(sp.time, "sleep", return_value=None),
    ):
        out = sp.publish_instagram_photo(
            image_url="https://images.pexels.com/photos/1/cover.jpg",
            caption="Legenda de teste\n",
        )
        assert out["ok"] is True
        assert out["media_id"] == "media-9"
        assert out["creation_id"] == "creation-1"
        assert post_mock.call_count == 2


def test_social_status_endpoint():
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
    ):
        r = _client().get(
            "/api/social-publish/status",
            headers={"Authorization": "Bearer test-robo-token-local"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["instagram"]["configured"] is False


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tests = [
        test_linkedin_post_follows_pattern,
        test_instagram_caption_is_plain_text_ready,
        test_absolute_image_url_requires_https,
        test_social_publish_requires_auth,
        test_social_publish_drafts_without_instagram_creds,
        test_instagram_publish_calls_graph_api,
        test_social_status_endpoint,
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
