"""Busca FTS: sinônimos, ranking bm25 e rota de sync autenticada."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("ROBO_TOKEN", "test-robo-token-local")

from fastapi.testclient import TestClient

import db as dbmod
import main


def test_fts_query_expands_selic_synonyms():
    q = dbmod.build_fts_match_query("Selic")
    assert q is not None
    low = q.lower()
    assert "selic" in low
    assert "copom" in low
    assert "juros" in low


def test_fts_query_expands_inflacao_accent():
    q = dbmod.build_fts_match_query("inflação")
    assert q is not None
    low = q.lower()
    assert "ipca" in low
    assert "infla" in low


def test_fts_query_ignores_junk():
    assert dbmod.build_fts_match_query("??") is None
    assert dbmod.build_fts_match_query("") is None
    assert dbmod.build_fts_match_query("a") is None


def test_fts_query_caps_terms():
    q = dbmod.build_fts_match_query(
        "selic ipca dolar bitcoin cambio copom juros cripto usd btc inflacao"
    )
    assert q is not None
    assert q.count(" OR ") <= 15


def test_upsert_news_fts_noop_on_local(monkeypatch):
    monkeypatch.setenv("USE_LOCAL_DB", "1")
    client = MagicMock()
    assert dbmod.upsert_news_fts(client, 1, "t", "r") is True
    client.execute.assert_not_called()


def test_upsert_skips_when_fts_unavailable(monkeypatch):
    monkeypatch.setenv("USE_LOCAL_DB", "0")
    monkeypatch.setattr(dbmod, "_schema_ready", False)
    monkeypatch.setattr(dbmod, "_fts_ready", False)
    client = MagicMock()
    assert dbmod.upsert_news_fts(client, 1, "t", "r") is False
    client.execute.assert_not_called()


def test_upsert_news_fts_writes_on_remote(monkeypatch):
    monkeypatch.setenv("USE_LOCAL_DB", "0")
    monkeypatch.setattr(dbmod, "_schema_ready", True)
    monkeypatch.setattr(dbmod, "_fts_ready", True)
    client = MagicMock()
    client.execute.return_value = dbmod.QueryResult([])
    assert dbmod.upsert_news_fts(client, 42, "Titulo Selic", "Resumo") is True
    assert client.execute.call_count >= 1
    sqls = " ".join(str(c.args[0]).lower() for c in client.execute.call_args_list)
    assert "news_fts" in sqls


def test_execute_fts_listing_orders_by_bm25():
    captured: dict[str, str] = {}

    class FakeClient:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = list(params or [])
            return dbmod.QueryResult([])

    main._execute_fts_listing(FakeClient(), '"selic"*', None, 11, 0)
    sql = captured["sql"].lower()
    assert "news_fts match" in sql
    assert "bm25(" in sql
    assert "join news_fts" in sql
    assert captured["params"][0] == '"selic"*'


def test_sync_news_fts_requires_auth():
    client = TestClient(main.app)
    r = client.get("/api/sync-news-fts")
    assert r.status_code == 401


def test_sync_news_fts_wrong_token():
    client = TestClient(main.app)
    r = client.get("/api/sync-news-fts", headers={"Authorization": "Bearer token-errado"})
    assert r.status_code == 401


def test_sync_news_fts_bearer_ok():
    with patch.object(main, "sync_news_fts", return_value={"ok": True, "rebuilt": True}):
        client = TestClient(main.app)
        r = client.get(
            "/api/sync-news-fts",
            headers={"Authorization": f"Bearer {os.environ['ROBO_TOKEN']}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True
        assert body.get("status") == "Sucesso"


def test_search_synonym_and_relevance(tmp_path, monkeypatch):
    path = str(tmp_path / "fts_qa.db")
    monkeypatch.setenv("USE_LOCAL_DB", "1")
    monkeypatch.setenv("LOCAL_DATABASE_PATH", path)
    dbmod._client = None
    local = dbmod.LocalDbClient(path)
    dbmod.ensure_schema(local, force=True)
    dbmod._client = local
    assert dbmod.fts_available()

    long_resumo = ("Texto editorial sem a palavra-chave principal. " * 40)[:900]
    buried = long_resumo + " Menciona selic só no fim."
    local.execute(
        """
        INSERT INTO news (
            titulo, resumo, impacto, link, tag, sentimento, published_at, fonte,
            created_at, moderation_status, home_priority
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', 40)
        """,
        [
            "Selic: o que muda no financiamento",
            long_resumo,
            "Juros altos encarecem o crédito.",
            "https://example.test/fts-title",
            "Juros",
            "Neutro",
            "2026-08-01T10:00:00Z",
            "Clareza Capital",
            "2026-08-01T10:00:00Z",
        ],
    )
    local.execute(
        """
        INSERT INTO news (
            titulo, resumo, impacto, link, tag, sentimento, published_at, fonte,
            created_at, moderation_status, home_priority
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', 40)
        """,
        [
            "Mercado reage ao comunicado",
            buried,
            "Leitura genérica do mercado.",
            "https://example.test/fts-buried",
            "Economia",
            "Neutro",
            "2026-08-09T10:00:00Z",
            "Clareza Capital",
            "2026-08-09T10:00:00Z",
        ],
    )
    local.execute(
        """
        INSERT INTO news (
            titulo, resumo, impacto, link, tag, sentimento, published_at, fonte,
            created_at, moderation_status, home_priority
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', 40)
        """,
        [
            "Copom comunica decisão de juros",
            long_resumo,
            "O Copom explica o ciclo.",
            "https://example.test/fts-copom",
            "Juros",
            "Neutro",
            "2026-08-08T10:00:00Z",
            "Clareza Capital",
            "2026-08-08T10:00:00Z",
        ],
    )
    fts_q = dbmod.build_fts_match_query("selic")
    assert fts_q and "copom" in fts_q.lower()
    indexed = int(local.execute("SELECT COUNT(*) FROM news_fts").rows[0][0] or 0)
    if indexed < 3:
        local.execute("INSERT INTO news_fts(news_fts) VALUES('rebuild')")
    result = main._execute_fts_listing(local, fts_q, None, 20, 0)
    titles = [str(row[1]) for row in result.rows]
    assert any("Copom comunica" in t for t in titles), titles
    assert any("Selic: o que muda" in t for t in titles), titles
    assert titles.index(next(t for t in titles if "Selic: o que muda" in t)) < titles.index(
        next(t for t in titles if "Mercado reage" in t)
    )
