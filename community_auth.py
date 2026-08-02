"""Auth de comunidade (usuários, sessão, OAuth Google) e comentários."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from profanity_filter import moderate_comment

DEFAULT_AVATAR = "/static/avatars/default.svg"
AVATAR_DIR = Path(os.getenv("AVATAR_DIR", "static/avatars"))
AVATAR_MAX_BYTES = 512 * 1024
AVATAR_ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
SESSION_USER_KEY = "user_id"
CONSENT_COOKIE = "fn_consent"
IP_HASH_SALT_ENV = "IP_HASH_SALT"
EMAIL_VERIFY_TTL_HOURS = int(os.getenv("EMAIL_VERIFY_TTL_HOURS") or "48")
EMAIL_VERIFY_RESEND_COOLDOWN_SEC = int(os.getenv("EMAIL_VERIFY_RESEND_COOLDOWN_SEC") or "120")
EMAIL_NOT_VERIFIED_MSG = (
    "Confirme seu e-mail pelo link enviado antes de entrar. "
    "Se não recebeu, use reenviar verificação."
)


def _env(key: str) -> str:
    return (os.getenv(key) or "").strip()


def session_secret() -> str:
    secret = _env("SESSION_SECRET")
    if secret:
        return secret
    # Dev fallback explícito — produção deve definir SESSION_SECRET.
    return "financas-news-dev-session-change-me"


def hash_password(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    import bcrypt

    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (email or "").strip()))


def validate_password_strength(password: str) -> str | None:
    if len(password or "") < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    salt = _env(IP_HASH_SALT_ENV) or session_secret()
    return hmac.new(salt.encode("utf-8"), ip.encode("utf-8"), hashlib.sha256).hexdigest()


def parse_consent_cookie(raw: str | None) -> dict[str, bool]:
    """Cookie fn_consent: necessary=1&analytics=0&preferences=0."""
    out = {"necessary": True, "analytics": False, "preferences": False}
    if not raw:
        return out
    for part in raw.split("&"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        key = k.strip().lower()
        if key in out:
            out[key] = v.strip() in ("1", "true", "yes", "on")
    out["necessary"] = True
    return out


def consent_allows_geo(consent: dict[str, bool]) -> bool:
    return bool(consent.get("analytics") or consent.get("preferences"))


def approximate_geo(request_headers: dict[str, str], *, allowed: bool) -> str | None:
    """Geo aproximada só com consentimento — headers de CDN ou Accept-Language."""
    if not allowed:
        return None
    for header in (
        "cf-ipcountry",
        "x-vercel-ip-country",
        "cloudfront-viewer-country",
        "x-country-code",
    ):
        val = (request_headers.get(header) or request_headers.get(header.title()) or "").strip()
        if val and len(val) <= 8:
            return val.upper()
    accept = (request_headers.get("accept-language") or "").split(",")[0].strip()
    if "-" in accept:
        return accept.split("-")[-1][:8].upper()
    if accept:
        return accept[:8].upper()
    return None


def ensure_default_avatar() -> None:
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    path = AVATAR_DIR / "default.svg"
    if path.is_file():
        return
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128" role="img" aria-label="Avatar">
  <rect width="128" height="128" fill="#1e293b"/>
  <circle cx="64" cy="48" r="24" fill="#94a3b8"/>
  <ellipse cx="64" cy="104" rx="40" ry="28" fill="#94a3b8"/>
</svg>"""
    path.write_text(svg, encoding="utf-8")


def create_user(
    client,
    *,
    name: str,
    email: str,
    password: str | None = None,
    google_id: str | None = None,
    avatar_url: str | None = None,
    email_verified: bool | None = None,
) -> dict[str, Any]:
    email_n = email.strip().lower()
    name_n = (name or "").strip()[:80] or email_n.split("@")[0]
    if not validate_email(email_n):
        raise ValueError("E-mail inválido.")
    if password:
        err = validate_password_strength(password)
        if err:
            raise ValueError(err)
        pw_hash = hash_password(password)
    else:
        pw_hash = None
    agora = now_iso()
    avatar = avatar_url or DEFAULT_AVATAR
    ensure_default_avatar()
    # Google OAuth já prova o e-mail; cadastro local exige verificação.
    verified = 1 if (email_verified if email_verified is not None else bool(google_id)) else 0
    verify_token = None
    verify_sent_at = None
    if not verified:
        verify_token = generate_verify_token()
        verify_sent_at = agora
    client.execute(
        """
        INSERT INTO users (
            name, email, password_hash, google_id, avatar_url, created_at, consent_at,
            email_verified, email_verify_token, email_verify_sent_at
        )
        VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
        """,
        [name_n, email_n, pw_hash, google_id, avatar, agora, verified, verify_token, verify_sent_at],
    )
    row = client.execute(
        """
        SELECT id, name, email, avatar_url, google_id, email_verified, email_verify_token, email_verify_sent_at
        FROM users WHERE email = ? LIMIT 1
        """,
        [email_n],
    ).rows[0]
    return _user_dict(row, include_verify=True)


def find_user_by_email(client, email: str) -> dict[str, Any] | None:
    result = client.execute(
        """
        SELECT id, name, email, avatar_url, google_id, password_hash,
               email_verified, email_verify_token, email_verify_sent_at
        FROM users WHERE email = ? LIMIT 1
        """,
        [email.strip().lower()],
    )
    if not result.rows:
        return None
    return _user_dict(result.rows[0], include_hash=True, include_verify=True)


def find_user_by_id(client, user_id: int) -> dict[str, Any] | None:
    result = client.execute(
        """
        SELECT id, name, email, avatar_url, google_id, email_verified
        FROM users WHERE id = ? LIMIT 1
        """,
        [int(user_id)],
    )
    if not result.rows:
        return None
    return _user_dict(result.rows[0], include_verify=True)


def find_user_by_google_id(client, google_id: str) -> dict[str, Any] | None:
    result = client.execute(
        """
        SELECT id, name, email, avatar_url, google_id, email_verified
        FROM users WHERE google_id = ? LIMIT 1
        """,
        [google_id],
    )
    if not result.rows:
        return None
    return _user_dict(result.rows[0], include_verify=True)


def _as_bool_flag(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return str(value).strip().lower() in ("1", "true", "yes")


def _user_dict(row, *, include_hash: bool = False, include_verify: bool = False) -> dict[str, Any]:
    data = {
        "id": int(row[0]),
        "name": str(row[1] or ""),
        "email": str(row[2] or ""),
        "avatar_url": str(row[3] or DEFAULT_AVATAR),
        "google_id": row[4] if len(row) > 4 else None,
    }
    if include_hash:
        # SELECT ... password_hash, email_verified, ...
        data["password_hash"] = row[5] if len(row) > 5 else None
        if include_verify and len(row) > 6:
            data["email_verified"] = _as_bool_flag(row[6])
            data["email_verify_token"] = row[7] if len(row) > 7 else None
            data["email_verify_sent_at"] = row[8] if len(row) > 8 else None
    elif include_verify and len(row) > 5:
        # SELECT ... google_id, email_verified [, token, sent_at]
        data["email_verified"] = _as_bool_flag(row[5])
        if len(row) > 6:
            data["email_verify_token"] = row[6]
        if len(row) > 7:
            data["email_verify_sent_at"] = row[7]
    return data


def generate_verify_token() -> str:
    return secrets.token_urlsafe(32)


def parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_verify_token_expired(sent_at: str | None) -> bool:
    dt = parse_iso_utc(sent_at)
    if not dt:
        return True
    return datetime.now(timezone.utc) > dt + timedelta(hours=EMAIL_VERIFY_TTL_HOURS)


def can_resend_verification(sent_at: str | None) -> bool:
    dt = parse_iso_utc(sent_at)
    if not dt:
        return True
    return datetime.now(timezone.utc) >= dt + timedelta(seconds=EMAIL_VERIFY_RESEND_COOLDOWN_SEC)


def issue_email_verification(client, user_id: int, *, force: bool = False) -> dict[str, Any]:
    """Gera novo token e grava no usuário. Não envia e-mail (caller dispara)."""
    user = find_user_by_id(client, user_id)
    if not user:
        return {"ok": False, "error": "Usuário não encontrado."}
    if user.get("email_verified"):
        return {"ok": False, "error": "E-mail já verificado.", "already_verified": True}
    full = find_user_by_email(client, str(user["email"]))
    sent_at = (full or {}).get("email_verify_sent_at") if full else None
    if not force and not can_resend_verification(sent_at):
        return {
            "ok": False,
            "error": "Aguarde 2 minutos antes de solicitar um novo link.",
            "rate_limited": True,
        }
    token = generate_verify_token()
    agora = now_iso()
    client.execute(
        """
        UPDATE users
        SET email_verify_token = ?, email_verify_sent_at = ?, email_verified = 0
        WHERE id = ?
        """,
        [token, agora, int(user_id)],
    )
    return {
        "ok": True,
        "token": token,
        "email": user["email"],
        "name": user["name"],
        "sent_at": agora,
    }


def verify_email_token(client, token: str) -> dict[str, Any]:
    raw = (token or "").strip()
    if not raw or len(raw) < 16:
        return {"ok": False, "error": "Link inválido ou expirado."}
    result = client.execute(
        """
        SELECT id, name, email, avatar_url, google_id, email_verified,
               email_verify_token, email_verify_sent_at
        FROM users WHERE email_verify_token = ? LIMIT 1
        """,
        [raw],
    )
    if not result.rows:
        return {"ok": False, "error": "Link inválido ou expirado."}
    user = _user_dict(result.rows[0], include_verify=True)
    if user.get("email_verified"):
        return {"ok": True, "already_verified": True, "user": user}
    if is_verify_token_expired(user.get("email_verify_sent_at")):
        return {"ok": False, "error": "Link expirado. Solicite um novo pelo reenvio.", "expired": True}
    client.execute(
        """
        UPDATE users
        SET email_verified = 1, email_verify_token = NULL, email_verify_sent_at = NULL
        WHERE id = ?
        """,
        [int(user["id"])],
    )
    user["email_verified"] = True
    user["email_verify_token"] = None
    user["email_verify_sent_at"] = None
    return {"ok": True, "user": user}


def mark_email_verified(client, user_id: int) -> None:
    client.execute(
        """
        UPDATE users
        SET email_verified = 1, email_verify_token = NULL, email_verify_sent_at = NULL
        WHERE id = ?
        """,
        [int(user_id)],
    )


def authenticate_local(client, email: str, password: str) -> dict[str, Any] | None:
    user = find_user_by_email(client, email)
    if not user or not user.get("password_hash"):
        return None
    if not verify_password(password, str(user["password_hash"])):
        return None
    user.pop("password_hash", None)
    user.pop("email_verify_token", None)
    return user


def link_or_create_google_user(
    client,
    *,
    google_id: str,
    email: str,
    name: str,
    picture: str | None,
) -> dict[str, Any]:
    existing = find_user_by_google_id(client, google_id)
    if existing:
        if not existing.get("email_verified"):
            mark_email_verified(client, int(existing["id"]))
            existing["email_verified"] = True
        return existing
    by_email = find_user_by_email(client, email)
    if by_email:
        client.execute(
            """
            UPDATE users
            SET google_id = ?,
                avatar_url = COALESCE(NULLIF(?, ''), avatar_url),
                name = COALESCE(NULLIF(?, ''), name),
                email_verified = 1,
                email_verify_token = NULL,
                email_verify_sent_at = NULL
            WHERE id = ?
            """,
            [google_id, picture or "", name or "", by_email["id"]],
        )
        return find_user_by_id(client, int(by_email["id"])) or by_email
    return create_user(
        client,
        name=name,
        email=email,
        password=None,
        google_id=google_id,
        avatar_url=picture or DEFAULT_AVATAR,
        email_verified=True,
    )


def google_oauth_configured() -> bool:
    return bool(_env("GOOGLE_OAUTH_CLIENT_ID") and _env("GOOGLE_OAUTH_CLIENT_SECRET") and _env("GOOGLE_OAUTH_REDIRECT_URI"))


def google_authorize_url(state: str) -> str:
    params = {
        "client_id": _env("GOOGLE_OAUTH_CLIENT_ID"),
        "redirect_uri": _env("GOOGLE_OAUTH_REDIRECT_URI"),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "include_granted_scopes": "true",
        "state": state,
        "prompt": "select_account",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def exchange_google_code(code: str) -> dict[str, Any]:
    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": _env("GOOGLE_OAUTH_CLIENT_ID"),
            "client_secret": _env("GOOGLE_OAUTH_CLIENT_SECRET"),
            "redirect_uri": _env("GOOGLE_OAUTH_REDIRECT_URI"),
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if token_resp.status_code >= 400:
        raise ValueError("Falha ao trocar código OAuth Google.")
    tokens = token_resp.json()
    access = tokens.get("access_token")
    if not access:
        raise ValueError("Token Google ausente.")
    info_resp = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access}"},
        timeout=20,
    )
    if info_resp.status_code >= 400:
        raise ValueError("Falha ao obter perfil Google.")
    info = info_resp.json()
    return {
        "google_id": str(info.get("sub") or ""),
        "email": str(info.get("email") or ""),
        "name": str(info.get("name") or info.get("given_name") or ""),
        "picture": str(info.get("picture") or "") or None,
    }


def save_avatar_upload(user_id: int, filename: str, data: bytes) -> str:
    ensure_default_avatar()
    ext = Path(filename or "").suffix.lower()
    if ext not in AVATAR_ALLOWED:
        raise ValueError("Tipo de imagem não permitido (use JPG, PNG, WEBP ou GIF).")
    if len(data) > AVATAR_MAX_BYTES:
        raise ValueError("Imagem muito grande (máx. 512 KB).")
    if not data:
        raise ValueError("Arquivo vazio.")
    # Magic bytes básicos
    if not (
        data[:3] == b"\xff\xd8\xff"
        or data[:8] == b"\x89PNG\r\n\x1a\n"
        or data[:6] in (b"GIF87a", b"GIF89a")
        or data[:4] == b"RIFF"
    ):
        raise ValueError("Arquivo não parece uma imagem válida.")
    safe_name = f"u{int(user_id)}_{secrets.token_hex(8)}{ext}"
    path = AVATAR_DIR / safe_name
    path.write_bytes(data)
    return f"/static/avatars/{safe_name}"


def list_comments(client, news_id: int, *, include_pending_for_user: int | None = None) -> list[dict[str, Any]]:
    result = client.execute(
        """
        SELECT c.id, c.news_id, c.user_id, c.parent_id, c.body, c.status, c.created_at,
               c.geo_country, c.upvotes, u.name, u.avatar_url
        FROM comments c
        JOIN users u ON u.id = c.user_id
        WHERE c.news_id = ?
          AND (c.status = 'published' OR (c.user_id = ? AND c.status IN ('pending', 'blocked')))
        ORDER BY COALESCE(c.parent_id, c.id) ASC, c.id ASC
        LIMIT 200
        """,
        [int(news_id), int(include_pending_for_user or 0)],
    )
    items: list[dict[str, Any]] = []
    for row in result.rows or []:
        items.append(
            {
                "id": int(row[0]),
                "news_id": int(row[1]),
                "user_id": int(row[2]),
                "parent_id": int(row[3]) if row[3] is not None else None,
                "body": str(row[4] or ""),
                "status": str(row[5] or ""),
                "created_at": str(row[6] or ""),
                "geo_country": row[7],
                "upvotes": int(row[8] or 0),
                "author_name": str(row[9] or ""),
                "author_avatar": str(row[10] or DEFAULT_AVATAR),
            }
        )
    return items


def create_comment(
    client,
    *,
    news_id: int,
    user_id: int,
    body: str,
    parent_id: int | None,
    ip: str | None,
    headers: dict[str, str],
    consent: dict[str, bool],
) -> dict[str, Any]:
    decision = moderate_comment(body)
    status = str(decision["status"])
    if status == "rejected":
        raise ValueError("Comentário inválido.")
    if parent_id is not None:
        parent = client.execute(
            "SELECT id, parent_id FROM comments WHERE id = ? AND news_id = ? LIMIT 1",
            [int(parent_id), int(news_id)],
        ).rows
        if not parent:
            raise ValueError("Comentário pai não encontrado.")
        # Apenas 1 nível de reply
        if parent[0][1] is not None:
            raise ValueError("Respostas aninhadas não são permitidas.")
    geo = approximate_geo(headers, allowed=consent_allows_geo(consent))
    ip_h = hash_ip(ip) if consent_allows_geo(consent) else None
    consent_at = now_iso() if consent_allows_geo(consent) else None
    agora = now_iso()
    final_status = "published" if status == "published" else "blocked"
    body_clean = body.strip()
    client.execute(
        """
        INSERT INTO comments (
            news_id, user_id, parent_id, body, status, created_at,
            consent_at, ip_hash, geo_country, upvotes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        [
            int(news_id),
            int(user_id),
            int(parent_id) if parent_id is not None else None,
            body_clean,
            final_status,
            agora,
            consent_at,
            ip_h,
            geo,
        ],
    )
    row = client.execute(
        """
        SELECT id FROM comments
        WHERE news_id = ? AND user_id = ? AND created_at = ? AND body = ?
        ORDER BY id DESC LIMIT 1
        """,
        [int(news_id), int(user_id), agora, body_clean],
    ).rows
    cid = int(row[0][0]) if row else 0
    return {
        "id": cid,
        "status": final_status,
        "ok": bool(decision.get("ok")),
        "reason": decision.get("reason"),
    }


def upvote_comment(client, comment_id: int, user_id: int) -> bool:
    """Upvote simples (idempotente via tabela auxiliar se existir; senão +1 limitado)."""
    try:
        existing = client.execute(
            "SELECT 1 FROM comment_votes WHERE comment_id = ? AND user_id = ? LIMIT 1",
            [int(comment_id), int(user_id)],
        ).rows
        if existing:
            return False
        client.execute(
            "INSERT INTO comment_votes (comment_id, user_id, created_at) VALUES (?, ?, ?)",
            [int(comment_id), int(user_id), now_iso()],
        )
        client.execute(
            "UPDATE comments SET upvotes = COALESCE(upvotes, 0) + 1 WHERE id = ?",
            [int(comment_id)],
        )
        return True
    except Exception:
        return False
