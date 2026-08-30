"""Mesa político-financeira (prompt separado da cobertura de mercado)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ROBO_TOKEN", "test-token-fake")

import core


def test_politico_from_tag():
    assert core.is_politico_financeira(
        "Congresso vota pacote",
        "O orçamento muda o gasto público.",
        "Política Econômica",
    )


def test_politico_from_economia_feed_with_fiscal():
    assert core.is_politico_financeira(
        "Câmara aprova reforma tributária",
        "O imposto sobre consumo muda o custo de vida e o mercado reage.",
        "Economia",
    )


def test_not_politico_for_crypto():
    assert not core.is_politico_financeira(
        "Bitcoin rompe resistência após ETF",
        "Criptoativos sobem com fluxo de ETFs.",
        "Cripto",
    )


def test_skip_pure_politics_without_economic_angle():
    assert core.should_skip_politico_sem_economia(
        "Deputado troca farpas em sessão",
        "Troca de acusações pessoais no plenário, só briga de lideranças.",
        "Política Econômica",
    )
    assert not core.should_skip_politico_sem_economia(
        "Câmara vota IOF",
        "O aumento do IOF encarece o crédito e pressiona o câmbio.",
        "Política Econômica",
    )
    assert not core.should_skip_politico_sem_economia(
        "Congresso vota taxa das blusinhas e escala 6x1",
        "A pauta inclui a MP das blusinhas e o fim da jornada 6x1.",
        "Política Econômica",
    )
    assert not core.should_skip_politico_sem_economia(
        "Brasil cria 58 mil postos, aponta Caged",
        "O Caged de julho mostra emprego formal e o INSS na pauta do Senado.",
        "Política Econômica",
    )


def test_expanded_politico_and_economia_feeds():
    fontes = {f["fonte"] for f in core.RSS_FEEDS}
    politico = [f["fonte"] for f in core.RSS_FEEDS if f["tag_hint"] == "Política Econômica"]
    economia = [f["fonte"] for f in core.RSS_FEEDS if f["tag_hint"] == "Economia"]
    assert "Folha Poder" in politico
    assert "O Globo Política" in politico
    assert "Congresso em Foco" in politico
    assert "JOTA" in politico
    assert "Agência Brasil Política" in politico
    assert "O Globo Economia" in economia
    assert "Veja Economia" in economia
    assert "CartaCapital Economia" in economia
    assert "Agência Brasil Economia" in economia
    assert "CNN Brasil Economia" not in fontes
    assert "Estadão Economia" not in fontes
    urls = {f["url"] for f in core.RSS_FEEDS}
    assert "https://www.cnnbrasil.com.br/economia/feed/" not in urls
    assert "https://www.estadao.com.br/rss/economia.xml" not in urls
    assert "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml" not in urls


def test_politico_max_articles_default(monkeypatch):
    monkeypatch.delenv("ROBOT_POLITICO_MAX_ARTICLES", raising=False)
    assert core.get_robot_politico_max_articles() == 14
    monkeypatch.setenv("ROBOT_POLITICO_MAX_ARTICLES", "0")
    assert core.get_robot_politico_max_articles() == 0
    monkeypatch.setenv("ROBOT_POLITICO_MAX_ARTICLES", "16")
    assert core.get_robot_politico_max_articles() == 16


def test_prompts_are_distinct():
    fin = core._build_financeiro_news_prompt(
        "Selic", "texto", "G1", "Juros", "dados", "Juros, Economia", "", ""
    )
    pol = core._build_politico_financeira_prompt(
        "IOF", "texto", "Poder360", "Política Econômica", "dados", "Juros, Economia", "", ""
    )
    assert "mercado de capitais e criptoativos" in fin
    assert "POLÍTICA ECONÔMICA" in pol
    assert "mesa SEPARADA" in pol
    assert "pedir voto" in pol
    assert "pedir voto" not in fin


def test_process_news_uses_politico_prompt():
    captured: list[str] = []

    def _fake_gen(prompt: str) -> str:
        captured.append(prompt)
        return '{"titulo_viral":"x","resumo_simples":"y","tag":"Política Econômica"}'

    with patch.object(core, "get_gemini_api_keys", return_value=["fake"]), patch.object(
        core, "generate_content_with_fallback", side_effect=_fake_gen
    ):
        core.process_news_with_ai(
            "Câmara aprova pacote fiscal",
            "O orçamento e o IOF mudam o crédito.",
            "G1 Política",
            "Política Econômica",
            "painel",
        )
    assert captured
    assert "mesa SEPARADA" in captured[0]


def test_ordered_feeds_politico_first(monkeypatch):
    monkeypatch.delenv("ROBOT_POLITICO_FIRST", raising=False)
    ordered = core.ordered_rss_feeds()
    politico = [f for f in ordered if f["tag_hint"] == "Política Econômica"]
    assert ordered[: len(politico)] == politico
    monkeypatch.setenv("ROBOT_POLITICO_FIRST", "0")
    same = core.ordered_rss_feeds()
    assert same == list(core.RSS_FEEDS)


def test_macro_politica_does_not_force_selic():
    rel = core._macro_topic_relevance(
        "Câmara discute emenda parlamentar",
        "Disputa de vagas na Mesa do Congresso, sem reunião de política monetária.",
        "Política Econômica",
    )
    assert rel["selic"] is False


def test_politico_prompt_does_not_prioritize_ipca_cambio():
    pol = core._build_politico_financeira_prompt(
        "IOF", "texto", "Poder360", "Política Econômica", "dados", "Juros, Economia", "", ""
    )
    assert "priorize fiscal, câmbio, Ibovespa, IPCA" not in pol
    assert "Câmbio, Selic e IPCA só se o fato for sobre isso" in pol
    assert "calendário da votação" in pol


if __name__ == "__main__":
    test_politico_from_tag()
    test_politico_from_economia_feed_with_fiscal()
    test_not_politico_for_crypto()
    test_skip_pure_politics_without_economic_angle()
    test_expanded_politico_and_economia_feeds()
    test_prompts_are_distinct()
    test_process_news_uses_politico_prompt()
    test_macro_politica_does_not_force_selic()
    test_politico_prompt_does_not_prioritize_ipca_cambio()
    print("PASS: test_politico_financeira")
