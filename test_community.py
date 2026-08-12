"""Testes da comunidade: profanidade, hash de senha, comentários, digest e verificação de e-mail."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("ROBO_TOKEN", "test-robo-token-local")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("IP_HASH_SALT", "test-ip-salt")

from community_auth import (
    authenticate_local,
    can_resend_verification,
    create_comment,
    create_user,
    delete_own_comment,
    generate_verify_token,
    hash_password,
    is_verify_token_expired,
    issue_email_verification,
    parse_consent_cookie,
    verify_email_token,
    verify_password,
)
from newsletter_service import build_daily_digest, build_verification_email
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
    except ValueError:
        pass
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
    long_resumo = "A" * 220
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    client.execute.return_value = MagicMock(
        rows=[
            (10, "Selic sobe", long_resumo, "Juros", 100, now),
            (9, "Dólar cai", long_resumo, "Dólar", 90, now),
        ]
    )
    with patch("core.fetch_market_snapshot", return_value={}), patch(
        "core.fetch_bcb_snapshot", return_value={}
    ):
        digest = build_daily_digest(client, extra_n=5)
    assert digest["headline"] is not None
    assert digest["headline"]["titulo"] == "Selic sobe"
    assert any(x["titulo"] == "Dólar cai" for x in digest.get("items") or [])
    assert "subject" in digest and "html" in digest and "text" in digest
    assert "Clareza Capital" in digest["subject"]


def test_verify_token_entropy_and_expiry():
    token = generate_verify_token()
    assert len(token) >= 32
    assert token != generate_verify_token()
    recent = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert not is_verify_token_expired(recent)
    old = (datetime.now(timezone.utc) - timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert is_verify_token_expired(old)
    assert can_resend_verification(None)
    assert not can_resend_verification(recent)


def test_create_user_unverified_and_verify_flow():
    client = MagicMock()
    token_holder: dict[str, str] = {}

    def execute(sql, params=None):
        params = params or []
        sql_n = " ".join(str(sql).split())
        if sql_n.startswith("INSERT INTO users"):
            token_holder["token"] = params[7]
            return MagicMock(rows=[])
        if "FROM users WHERE email =" in sql_n and "password_hash" in sql_n:
            return MagicMock(
                rows=[
                    (
                        1,
                        "Ana",
                        "ana@example.com",
                        "/static/avatars/default.svg",
                        None,
                        hash_password("senha-segura-123"),
                        0,
                        token_holder.get("token"),
                        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
                ]
            )
        if sql_n.startswith(
            "SELECT id, name, email, avatar_url, google_id, email_verified, email_verify_token"
        ):
            if "email_verify_token = ?" in sql_n:
                return MagicMock(
                    rows=[
                        (
                            1,
                            "Ana",
                            "ana@example.com",
                            "/static/avatars/default.svg",
                            None,
                            0,
                            params[0],
                            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        )
                    ]
                )
            return MagicMock(
                rows=[
                    (
                        1,
                        "Ana",
                        "ana@example.com",
                        "/static/avatars/default.svg",
                        None,
                        0,
                        token_holder.get("token"),
                        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
                ]
            )
        if sql_n.startswith("UPDATE users") and "email_verified = 1" in sql_n:
            token_holder["verified"] = "1"
            return MagicMock(rows=[])
        if sql_n.startswith(
            "SELECT id, name, email, avatar_url, google_id, email_verified FROM users WHERE id"
        ):
            return MagicMock(
                rows=[(1, "Ana", "ana@example.com", "/static/avatars/default.svg", None, 0)]
            )
        return MagicMock(rows=[])

    client.execute.side_effect = execute
    user = create_user(client, name="Ana", email="ana@example.com", password="senha-segura-123")
    assert user["email_verified"] is False
    assert user.get("email_verify_token")
    assert token_holder.get("token")

    auth = authenticate_local(client, "ana@example.com", "senha-segura-123")
    assert auth is not None
    assert auth.get("email_verified") is False

    result = verify_email_token(client, token_holder["token"])
    assert result["ok"] is True
    assert result["user"]["email_verified"] is True


def test_login_blocked_semantics_for_unverified():
    """Senha ok + email_verified=0 ⇒ caller deve bloquear sessão (regra Gamers League)."""
    client = MagicMock()
    pw = hash_password("senha-segura-123")
    client.execute.return_value = MagicMock(
        rows=[
            (
                9,
                "Bob",
                "bob@example.com",
                "/static/avatars/default.svg",
                None,
                pw,
                0,
                "tok",
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        ]
    )
    user = authenticate_local(client, "bob@example.com", "senha-segura-123")
    assert user is not None
    assert user.get("email_verified") is False


def test_verification_email_payload():
    payload = build_verification_email(name="Ana", token="abcTOKEN1234567890", ttl_hours=48)
    assert "Ative sua conta" in payload["subject"]
    assert "verificar-email?token=abcTOKEN1234567890" in payload["text"]
    assert "verificar-email?token=abcTOKEN1234567890" in payload["html"]
    assert "Spam" in payload["text"]
    assert "transacional" in payload["text"].lower() or "cadastro" in payload["text"].lower()
    assert "Spam" in payload["html"] or "spam" in payload["html"].lower()


def test_send_verification_not_configured_returns_false():
    from newsletter_service import send_verification_email

    with patch.dict(os.environ, {"RESEND_API_KEY": "", "SMTP_HOST": "", "NEWSLETTER_WEBHOOK_URL": ""}, clear=False):
        # Garante que SMTP_FROM sozinho não conta como configurado.
        os.environ.pop("SMTP_FROM", None)
        result = send_verification_email(
            email="ana@example.com",
            name="Ana",
            token="abcTOKEN1234567890",
            ttl_hours=48,
        )
    assert result.get("ok") is False
    assert result.get("not_configured") is True
    assert "verify_url" in result
    assert "financas-news.net.br" in result["verify_url"] or "verificar-email" in result["verify_url"]


def test_send_verification_uses_site_origin_env():
    from newsletter_service import build_verification_email

    with patch.dict(os.environ, {"SITE_ORIGIN": "https://www.financas-news.net.br"}, clear=False):
        payload = build_verification_email(name="Ana", token="tokXYZ", ttl_hours=48)
    assert payload["verify_url"].startswith("https://www.financas-news.net.br/verificar-email?token=tokXYZ")


def test_send_verification_mock_success():
    from newsletter_service import send_verification_email

    with patch("newsletter_service.send_email", return_value={"ok": True, "provider": "resend"}) as mock_send:
        result = send_verification_email(
            email="ana@example.com",
            name="Ana",
            token="abcTOKEN1234567890",
            ttl_hours=48,
        )
    assert result.get("ok") is True
    mock_send.assert_called_once()
    assert "verificar-email?token=abcTOKEN1234567890" in result["verify_url"]


def test_mail_fail_user_msg_is_honest():
    from newsletter_service import MAIL_SEND_FAIL_USER_MSG

    assert "Não foi possível enviar o e-mail" in MAIL_SEND_FAIL_USER_MSG
    assert "suporte" in MAIL_SEND_FAIL_USER_MSG.lower()


def test_reenviar_ui_when_mailer_not_configured():
    """POST /reenviar-verificacao sem mailer → redirect com erro honesto (não finge envio)."""
    from urllib.parse import unquote

    from fastapi.testclient import TestClient

    import main
    from newsletter_service import MAIL_SEND_FAIL_USER_MSG

    with patch("newsletter_service.is_send_configured", return_value=False):
        client = TestClient(main.app)
        resp = client.post(
            "/reenviar-verificacao",
            data={"email": "pendente@example.com"},
            follow_redirects=False,
        )
    assert resp.status_code == 303
    loc = unquote(resp.headers.get("location") or "")
    assert "verificar=1" in loc
    assert "erro=" in loc
    assert MAIL_SEND_FAIL_USER_MSG in loc
    assert "enviamos um novo link" not in loc


def test_issue_verification_rate_limit():
    client = MagicMock()
    recent = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def execute(sql, params=None):
        sql_n = " ".join(str(sql).split())
        if "WHERE id =" in sql_n and "email_verified" in sql_n and "password_hash" not in sql_n:
            return MagicMock(
                rows=[(3, "Ana", "ana@example.com", "/static/avatars/default.svg", None, 0)]
            )
        if "password_hash" in sql_n:
            return MagicMock(
                rows=[
                    (
                        3,
                        "Ana",
                        "ana@example.com",
                        "/static/avatars/default.svg",
                        None,
                        "hash",
                        0,
                        "old",
                        recent,
                    )
                ]
            )
        return MagicMock(rows=[])

    client.execute.side_effect = execute
    issued = issue_email_verification(client, 3)
    assert issued.get("ok") is False
    assert issued.get("rate_limited") is True


def test_delete_own_comment_ok():
    client = MagicMock()
    client.execute.side_effect = [
        MagicMock(rows=[(10, 5, 99, None)]),  # SELECT id, user_id, news_id, parent_id
        MagicMock(rows=[]),  # DELETE votes
        MagicMock(rows=[]),  # DELETE replies
        MagicMock(rows=[]),  # DELETE comment
    ]
    result = delete_own_comment(client, 10, 5)
    assert result["ok"] is True
    assert result["id"] == 10
    assert result["news_id"] == 99
    sqls = [c.args[0] for c in client.execute.call_args_list]
    assert any("DELETE FROM comments WHERE id" in s for s in sqls)
    assert any("DELETE FROM comments WHERE parent_id" in s for s in sqls)


def test_delete_own_comment_forbidden_for_other_user():
    client = MagicMock()
    client.execute.return_value = MagicMock(rows=[(10, 5, 99, None)])
    try:
        delete_own_comment(client, 10, 7)
        assert False, "deveria negar exclusão de comentário alheio"
    except ValueError as exc:
        assert "próprio" in str(exc).lower()
    assert client.execute.call_count == 1


def test_delete_own_comment_not_found():
    client = MagicMock()
    client.execute.return_value = MagicMock(rows=[])
    try:
        delete_own_comment(client, 404, 1)
        assert False, "deveria falhar para comentário inexistente"
    except ValueError as exc:
        assert "não encontrado" in str(exc).lower()


def test_avatar_upload_uses_railway_volume_path():
    import tempfile
    from pathlib import Path

    import community_auth as community

    td = tempfile.mkdtemp()
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
        "0000000c4944415408d763f8ffff3f0005fe02fea533a32b0000000049454e44ae426082"
    )
    with patch.dict(os.environ, {"RAILWAY_VOLUME_MOUNT_PATH": td}, clear=False):
        os.environ.pop("AVATAR_DIR", None)
        url = community.save_avatar_upload(7, "a.png", png)
        assert url.startswith("/media/avatars/u7_")
        assert (Path(td) / "avatars" / url.rsplit("/", 1)[-1]).is_file()


def test_create_comment_json_payload_includes_user_id():
    client = MagicMock()
    client.execute.side_effect = [
        MagicMock(rows=[]),  # INSERT
        MagicMock(rows=[(42,)]),  # SELECT id
    ]
    result = create_comment(
        client,
        news_id=1,
        user_id=7,
        body="Comentário objetivo sobre a Selic.",
        parent_id=None,
        ip="127.0.0.1",
        headers={},
        consent={"necessary": True, "analytics": False, "preferences": False},
    )
    assert result["user_id"] == 7
    assert result["id"] == 42
    assert result["status"] == "published"


if __name__ == "__main__":
    test_profanity_blocks_common_terms()
    test_profanity_allows_clean_finance_text()
    test_password_hash_roundtrip()
    test_comment_rejected_on_profanity()
    test_consent_cookie_parse()
    test_daily_digest_payload()
    test_verify_token_entropy_and_expiry()
    test_create_user_unverified_and_verify_flow()
    test_login_blocked_semantics_for_unverified()
    test_verification_email_payload()
    test_send_verification_not_configured_returns_false()
    test_send_verification_uses_site_origin_env()
    test_send_verification_mock_success()
    test_mail_fail_user_msg_is_honest()
    test_reenviar_ui_when_mailer_not_configured()
    test_issue_verification_rate_limit()
    test_delete_own_comment_ok()
    test_delete_own_comment_forbidden_for_other_user()
    test_delete_own_comment_not_found()
    test_avatar_upload_uses_railway_volume_path()
    test_create_comment_json_payload_includes_user_id()
    print("OK test_community")
