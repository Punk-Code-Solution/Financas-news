"""Testes do quality gate de publicação (AdSense / thin content)."""
from __future__ import annotations

import os

from core import MIN_ARTICLE_WORDS, count_words, passes_publish_quality_gate


def _long_resumo(words: int = MIN_ARTICLE_WORDS + 20) -> str:
    base = "A Selic em 10,50 por cento muda o crédito e a poupança do brasileiro. "
    # ~10 palavras por frase; repete até atingir o mínimo.
    parts = []
    while count_words(" ".join(parts)) < words:
        parts.append(base)
    return "\n\n".join(parts)


def test_count_words_basic():
    assert count_words("um dois três") == 3
    assert count_words("") == 0
    assert count_words(None) == 0


def test_gate_rejects_empty():
    ok, reason = passes_publish_quality_gate(None)
    assert ok is False
    assert reason == "sem_json"


def test_gate_rejects_thin():
    ok, reason = passes_publish_quality_gate(
        {
            "resumo_simples": "Texto curto sem profundidade.",
            "impacto_bolso": "Pouco impacto no bolso 1%.",
            "contexto_mercado": "Selic em 10,5%.",
            "dados_citados": ["10,5%"],
        }
    )
    assert ok is False
    assert reason.startswith("thin_")


def test_gate_rejects_banned_phrase():
    resumo = _long_resumo() + "\n\nSegundo a matéria, o mercado reagiu com 3%."
    ok, reason = passes_publish_quality_gate(
        {
            "resumo_simples": resumo,
            "impacto_bolso": "Crédito mais caro em 1,2 ponto; poupança rende menos no curto prazo.",
            "contexto_mercado": "Selic em 10,50% e dólar a R$ 5,20 no painel.",
            "dados_citados": ["10,50%", "5,20", "1,2"],
        }
    )
    assert ok is False
    assert "frase_proibida" in reason


def test_gate_accepts_dense_article():
    resumo = _long_resumo()
    # Garante dígitos no corpo (âncoras numéricas).
    resumo = resumo + "\n\nO IPCA em 4,5% e o CDI em 10,4% reforçam o cenário com Selic 10,50%."
    ok, reason = passes_publish_quality_gate(
        {
            "resumo_simples": resumo,
            "impacto_bolso": "Financiamento sobe cerca de 1,5%; poupança perde atratividade frente ao CDI.",
            "contexto_mercado": "Selic 10,50% a.a.; dólar R$ 5,18; IPCA 12m em 4,5%.",
            "dados_citados": ["10,50%", "5,18", "4,5%"],
        }
    )
    assert ok is True, reason
    assert reason == "ok"


def test_gate_rejects_source_paraphrase():
    from core import source_overlap_ratio

    # Vocabulário variado copiado da fonte (simula rewrite leve / RSS).
    source = (
        "Petroleo Brent subiu para 84 dolares apos corte de oferta da OPEP. "
        "Refinarias brasileiras ajustaram precos da gasolina e do diesel nas bombas. "
        "Distribuidores antecipam reajuste de 3 pontos percentuais nas capitais. "
        "Investidores monitoram balanco da Petrobras e fluxo cambial no porto de Santos. "
        "Consumidores sentem impacto no frete e na cesta basica das grandes cidades. "
        "Analistas cruzam cotacao do barril com dolar comercial e margem das refinarias. "
    ) * 12
    resumo = source + " IPCA 4,5% CDI 10,4% Selic 10,50%."
    while count_words(resumo) < MIN_ARTICLE_WORDS:
        resumo += "\n\n" + source[:400]
    ratio = source_overlap_ratio(resumo, source)
    assert ratio >= 0.55, ratio
    ok, reason = passes_publish_quality_gate(
        {
            "resumo_simples": resumo,
            "impacto_bolso": "Financiamento sobe cerca de 1,5%; poupança perde atratividade frente ao CDI.",
            "contexto_mercado": "Selic 10,50% a.a.; dólar R$ 5,18; IPCA 12m em 4,5%.",
            "dados_citados": ["10,50%", "5,18", "4,5%"],
        },
        source_text=source,
    )
    assert ok is False, reason
    assert "parafrase_fonte" in reason


def test_hybrid_b_rss_stays_pending():
    from core import should_auto_publish_item

    os.environ["EDITORIAL_REVIEW_REQUIRED"] = "1"
    os.environ["EDITORIAL_AUTO_PUBLISH_OWN"] = "1"
    resumo = _long_resumo() + "\n\nO IPCA em 4,5% e o CDI em 10,4% reforçam o cenário com Selic 10,50%."
    ok, score, reason = should_auto_publish_item(
        link="https://exemplo.com/rss-noticia",
        resumo=resumo,
        impacto="Financiamento sobe cerca de 1,5%; poupança perde atratividade frente ao CDI.",
        contexto="Selic 10,50% a.a.; dólar R$ 5,18; IPCA 12m em 4,5%.",
        dados_citados=["10,50%", "5,18", "4,5%"],
        auto_published_today=0,
    )
    assert ok is False
    assert reason == "rss_requires_human"
    assert score >= 0


def test_hybrid_b_own_auto_publishes_when_score_ok():
    from core import should_auto_publish_item

    os.environ["EDITORIAL_REVIEW_REQUIRED"] = "1"
    os.environ["EDITORIAL_AUTO_PUBLISH_OWN"] = "1"
    os.environ["EDITORIAL_AUTO_PUBLISH_MIN_SCORE"] = "50"
    os.environ["EDITORIAL_AUTO_PUBLISH_DAILY_CAP"] = "2"
    resumo = _long_resumo() + "\n\nO IPCA em 4,5% e o CDI em 10,4% reforçam o cenário com Selic 10,50%."
    ok, score, reason = should_auto_publish_item(
        link="internal://analise/20261018-economia-abcd1234",
        resumo=resumo,
        impacto="Financiamento sobe cerca de 1,5%; poupança perde atratividade frente ao CDI.",
        contexto="Selic 10,50% a.a.; dólar R$ 5,18; IPCA 12m em 4,5%.",
        dados_citados=["10,50%", "5,18", "4,5%"],
        auto_published_today=0,
    )
    assert ok is True, (score, reason)
    assert reason == "auto_own_ok"


def test_hybrid_b_own_respects_daily_cap():
    from core import should_auto_publish_item

    os.environ["EDITORIAL_REVIEW_REQUIRED"] = "1"
    os.environ["EDITORIAL_AUTO_PUBLISH_OWN"] = "1"
    os.environ["EDITORIAL_AUTO_PUBLISH_MIN_SCORE"] = "50"
    os.environ["EDITORIAL_AUTO_PUBLISH_DAILY_CAP"] = "2"
    resumo = _long_resumo() + "\n\nO IPCA em 4,5% e o CDI em 10,4% reforçam o cenário com Selic 10,50%."
    ok, _, reason = should_auto_publish_item(
        link="internal://analise/20261018-economia-abcd1234",
        resumo=resumo,
        impacto="Financiamento sobe cerca de 1,5%; poupança perde atratividade frente ao CDI.",
        contexto="Selic 10,50% a.a.; dólar R$ 5,18; IPCA 12m em 4,5%.",
        dados_citados=["10,50%", "5,18", "4,5%"],
        auto_published_today=2,
    )
    assert ok is False
    assert reason == "daily_cap_reached"


if __name__ == "__main__":
    test_count_words_basic()
    test_gate_rejects_empty()
    test_gate_rejects_thin()
    test_gate_rejects_banned_phrase()
    test_gate_accepts_dense_article()
    test_gate_rejects_source_paraphrase()
    test_hybrid_b_rss_stays_pending()
    test_hybrid_b_own_auto_publishes_when_score_ok()
    test_hybrid_b_own_respects_daily_cap()
    print("OK quality gate")
