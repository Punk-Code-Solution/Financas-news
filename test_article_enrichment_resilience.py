"""Regressao: enrichment nao derruba a pagina quando Turso falha."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import article_enrichment as ae


class BoomClient:
    def execute(self, sql: str, args: list[Any] | None = None):
        raise KeyError("result")


class Result:
    def __init__(self, rows: list[Any]):
        self.rows = rows


def test_get_related_articles_fail_soft():
    assert ae.get_related_articles(BoomClient(), "Economia", 1) == []


def test_get_acervo_stats_fail_soft():
    stats = ae.get_acervo_stats(BoomClient(), "Economia")
    assert stats["total"] == 0
    assert stats["tom"] == "Neutro"


def test_get_related_articles_uses_cache():
    ae._RELATED_CACHE.clear()
    client = MagicMock()
    client.execute.return_value = Result(
        [(10, "Titulo", "Economia", "Neutro", "01/01/2026", "resumo curto")]
    )

    first = ae.get_related_articles(client, "Economia", 99, limit=4)
    second = ae.get_related_articles(client, "Economia", 99, limit=4)
    assert len(first) == 1
    assert first[0]["id"] == 10
    assert second[0]["id"] == 10
    assert client.execute.call_count == 1


def test_build_article_enrichment_survives_db_errors():
    enrichment = ae.build_article_enrichment(
        BoomClient(),
        noticia_id=1,
        tag="Economia",
        dados_mercado={},
        resumo="A Selic influencia o credito.",
    )
    assert enrichment["related_articles"] == []
    assert enrichment["acervo_stats"]["total"] == 0
    assert enrichment["market_stats"] is not None
    assert enrichment["linked_resumo_parts"] or "Selic" in enrichment["linked_resumo"]


if __name__ == "__main__":
    test_get_related_articles_fail_soft()
    test_get_acervo_stats_fail_soft()
    test_get_related_articles_uses_cache()
    test_build_article_enrichment_survives_db_errors()
    print("PASS: test_article_enrichment_resilience")
