"""Testes do destaque editorial na home (prioridade e split)."""
from __future__ import annotations

import core
import main


def _row(
    news_id: int,
    title: str = "Titulo",
    *,
    home_priority: int = 0,
) -> tuple:
    return (
        news_id,
        title,
        "Resumo",
        "Impacto",
        f"https://example.com/{news_id}",
        "Economia",
        "Neutro",
        "2026-07-27",
        "Fonte",
        None,
        None,
        None,
        None,
        None,
        1,
        home_priority,
    )


def test_compute_home_priority_urgencia():
    assert core.compute_home_priority({"urgencia": "Alta"}) == core.HOME_PRIORITY_ALTA
    assert core.compute_home_priority({"urgencia": "Média"}) == core.HOME_PRIORITY_MEDIA
    assert core.compute_home_priority({"urgencia": "Baixa"}) == core.HOME_PRIORITY_BAIXA
    assert core.compute_home_priority(None) == 0


def test_compute_home_priority_cap_com_imagem():
    score = core.compute_home_priority({"urgencia": "Alta", "imagem_url": "https://img.test/x.jpg"})
    assert score == core.HOME_PRIORITY_ALTA


def test_split_home_editorial_usa_headlines_importantes():
    news = [_row(i, f"N{i}") for i in range(1, 12)]
    headlines = [_row(99, "Urgente", home_priority=100), _row(98, "Urgente 2", home_priority=100)]
    out = main._split_home_editorial(news, headlines)

    assert [r[0] for r in out["headline_news"]] == [99, 98]
    assert 99 not in {r[0] for r in out["secondary_news"]}
    assert 98 not in {r[0] for r in out["secondary_news"]}
    assert len(out["secondary_news"]) == 3
    assert len(out["trilha_news"]) == main.HEADLINE_TRAIL


def test_split_home_editorial_fallback_primeira_noticia():
    news = [_row(i, f"N{i}") for i in range(1, 10)]
    out = main._split_home_editorial(news, [])

    assert out["headline_news"][0][0] == 1
    assert out["headline_news"][0][0] not in {r[0] for r in out["secondary_news"]}
