"""Testes do quality gate de publicação (AdSense / thin content)."""
from __future__ import annotations

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
    resumo = resumo + "\n\nO IPCA em 4,5% e o CDI em 10,4% reforçam o cenário."
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


if __name__ == "__main__":
    test_count_words_basic()
    test_gate_rejects_empty()
    test_gate_rejects_thin()
    test_gate_rejects_banned_phrase()
    test_gate_accepts_dense_article()
    print("OK quality gate")
