"""Testes da rotina de análises próprias (sem chamar Gemini)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ROBO_TOKEN", "test-token-fake")
os.environ.setdefault("ROBOT_OWN_ANALYSES", "3")

import core


def test_slugify_and_link():
    assert core._slugify_tag("Política Econômica") == "politica-economica"
    link = core._own_analysis_link("Cripto", seed="abc")
    assert link.startswith(core.OWN_ANALYSIS_LINK_PREFIX)
    assert "cripto" in link


def test_macro_relevance_avoids_selic_for_crypto():
    rel = core._macro_topic_relevance(
        "Bitcoin rompe resistência após ETF",
        "Criptoativos sobem com dólar estável",
        "Cripto",
    )
    assert rel["selic"] is False
    assert rel["dolar"] is True


def test_macro_relevance_flags_selic_for_copom():
    rel = core._macro_topic_relevance(
        "Copom mantém Selic em 14,25%",
        "Comunicado do Banco Central",
        "Juros",
    )
    assert rel["selic"] is True


def test_select_analysis_lenses_returns_two_distinct():
    lenses = core.select_analysis_lenses(
        "Bitcoin em alta com fluxo estrangeiro",
        "Criptoativos sobem com dólar estável",
        "Cripto",
        count=2,
    )
    assert len(lenses) == 2
    assert lenses[0]["id"] != lenses[1]["id"]
    block = core._build_lens_prompt_block(lenses)
    assert "LENTES ANALÍTICAS" in block
    assert "PROIBIDO" in block


def test_pick_angles_diverse_tags():
    rows = []
    for i, tag in enumerate(["Cripto", "Cripto", "Dólar", "Dólar", "Ações", "Ações", "Juros", "Juros"]):
        rows.append(
            (
                i,
                f"Titulo {tag} {i}",
                tag,
                "Negativo" if i % 2 == 0 else "Positivo",
                f"Impacto {i}",
                f"Resumo longo o suficiente {i}",
                "Fonte X",
                "25/07/2026 10:00",
            )
        )
    angles = core._pick_own_analysis_angles(rows, 3)
    assert len(angles) == 3
    tags = {a["tag"] for a in angles}
    assert len(tags) >= 2
    for a in angles:
        assert len(a["titles"]) >= 2
        title, brief = core._build_own_analysis_brief(a)
        assert "ANÁLISE EDITORIAL PRÓPRIA" in brief
        assert a["tag"] in brief
        assert title


def test_generate_respects_daily_meta():
    with (
        patch.object(core, "count_own_analyses_today", return_value=3),
        patch.object(core, "get_robot_own_analyses_count", return_value=3),
    ):
        out = core.generate_own_analyses()
    assert out == []


def test_generate_skips_without_api_key():
    with (
        patch.object(core, "count_own_analyses_today", return_value=0),
        patch.object(core, "get_robot_own_analyses_count", return_value=3),
        patch.object(core, "get_gemini_api_keys", return_value=[]),
    ):
        out = core.generate_own_analyses()
    assert out == []


def main() -> int:
    test_slugify_and_link()
    test_macro_relevance_avoids_selic_for_crypto()
    test_macro_relevance_flags_selic_for_copom()
    test_select_analysis_lenses_returns_two_distinct()
    test_pick_angles_diverse_tags()
    test_generate_respects_daily_meta()
    test_generate_skips_without_api_key()
    print("PASS: test_own_analyses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
