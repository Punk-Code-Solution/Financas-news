"""Testes da comunidade: profanidade, hash de senha, comentários e digest diário."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("ROBO_TOKEN", "test-robo-token-local")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("IP_HASH_SALT", "test-ip-salt")

from community_auth import hash_password, verify_password, create_comment, parse_consent_cookie
from newsletter_service import build_daily_digest
from profanity_filter import find_blocked_terms, is_clean, moderate_comment


def test_profanity_blocks_common_terms():
    assert find_blocked_terms("Que merda de análise")
    assert not is_clean("vai se foder")
    decision = moderate_comment("Isso é uma porra")
    assert decision["ok"] is False
    assert decision["status"] == "blocked"


def test_profanity_allows_clean_finance_text():
    text = "A Selic em 14,25% pressiona o crédito imobiliário no curto prazo."
    assert is_clean(text)
    decision = moderate_comment(text)
    assert decision["ok"] is True
    assert decision["status"] == "published"


def test_password_hash_roundtrip():
    hashed = hash_password("senha-segura-123")
    assert hashed != "senha-segura-123"
    assert verify_password("senha-segura-123", hashed)
    assert not verify_password("outra", hashed)


def test_comment_rejected_on_profanity():
    client = MagicMock()
    try:
        create_comment(
            client,
            news_id=1,
            user_id=1,
            body="Que merda isso",
            parent_id=None,
            ip="127.0.0.1",
            headers={},
            consent={"necessary": True, "analytics": False, "preferences": False},
        )
        # create_comment bloqueia com status blocked (não raises) após moderate
    except ValueError:
        pass
    # Quando blocked, ainda faz INSERT — verificar chamada
    assert client.execute.called
    args = client.execute.call_args_list[0][0]
    assert "INSERT INTO comments" in args[0]
    assert "blocked" in args[1]


def test_consent_cookie_parse():
    c = parse_consent_cookie("necessary=1&analytics=1&preferences=0")
    assert c["necessary"] is True
    assert c["analytics"] is True
    assert c["preferences"] is False


def test_daily_digest_payload():
    client = MagicMock()
    client.execute.side_effect = [
        MagicMock(rows=[(10, "Selic sobe", "Texto longo da manchete" * 5, "Juros", 90, "01/08/2026")]),
        MagicMock(rows=[
            (10, "Selic sobe", "Juros"),
            (9, "Dólar cai", "Dólar"),
            (8, "IPCA", "Inflação"),
        ]),
    ]
    with patch("core.fetch_market_snapshot", return_value={}), patch(
        "core.fetch_bcb_snapshot", return_value={}
    ):
        digest = build_daily_digest(client, extra_n=5)
    assert digest["headline"] is not None
    assert digest["headline"]["titulo"] == "Selic sobe"
    assert any(x["titulo"] == "Dólar cai" for x in digest["links"])
    assert "subject" in digest and "html" in digest and "text" in digest
    assert "Finanças News" in digest["subject"]


if __name__ == "__main__":
    test_profanity_blocks_common_terms()
    test_profanity_allows_clean_finance_text()
    test_password_hash_roundtrip()
    test_comment_rejected_on_profanity()
    test_consent_cookie_parse()
    test_daily_digest_payload()
    print("OK test_community")
