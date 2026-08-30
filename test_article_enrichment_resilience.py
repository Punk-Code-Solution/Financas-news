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


def _sample_market() -> dict:
    cotacoes = {
        "Dólar (USD/BRL)": {"cotacao": "R$ 5,10", "variacao_24h": "0%"},
        "Bitcoin (BTC/BRL)": {"cotacao": "R$ 350000", "variacao_24h": "+1%"},
        "Euro (EUR/BRL)": {"cotacao": "R$ 5,60", "variacao_24h": "-0.1%"},
    }
    return {
        "cotacoes": cotacoes,
        "bcb": {
            "Selic meta (% a.a.)": {"valor": "14.25", "data": "17/07/2026"},
            "IPCA acumulado 12 meses (%)": {"valor": "4.64", "data": "17/07/2026"},
            "Dólar comercial (R$)": {"valor": "5.10", "data": "17/07/2026"},
        },
        "historico": {},
        "dados_citados": [],
    }


def test_build_market_stats_crypto_skips_selic_ipca_usd():
    stats = ae.build_market_stats(
        {**_sample_market(), "dados_citados": ["BTC 350 mil"]},
        "Cripto",
        resumo="Bitcoin sobe com fluxo de ETF.",
    )
    labels = [str(item["label"]) for item in stats["indicadores"]]
    assert not any("Selic" in label or "IPCA" in label for label in labels)
    quote_labels = [str(item["label"]) for item in stats["cotacoes"]]
    assert any("Bitcoin" in label for label in quote_labels)
    assert not any("USD" in label for label in quote_labels)
    assert stats["painel_nucleo"] is False


def test_build_market_stats_juros_keeps_selic():
    stats = ae.build_market_stats(
        {**_sample_market(), "dados_citados": ["Selic 14,25%"]},
        "Juros",
        resumo="Copom mantém a Selic.",
    )
    labels = [str(item["label"]) for item in stats["indicadores"]]
    assert any("Selic" in label for label in labels)
    assert stats["painel_nucleo"] is True


if __name__ == "__main__":
    test_get_related_articles_fail_soft()
    test_get_acervo_stats_fail_soft()
    test_get_related_articles_uses_cache()
    test_build_article_enrichment_survives_db_errors()
    test_build_market_stats_crypto_skips_selic_ipca_usd()
    test_build_market_stats_juros_keeps_selic()
    print("PASS: test_article_enrichment_resilience")
