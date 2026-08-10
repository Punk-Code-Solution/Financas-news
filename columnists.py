"""Colunistas: candidatura, publicação moderada, views, carteira e destaque pago."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import requests

import community_auth as community
from profanity_filter import find_blocked_terms

ROLE_USER = "user"
ROLE_COLUMNIST = "columnist"
ROLE_ADMIN = "admin"

ORIGIN_EDITORIAL = "editorial"
ORIGIN_COLUMNIST = "columnist"

STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_PUBLISHED = "published"
STATUS_REJECTED = "rejected"

APP_PENDING = "pending"
APP_APPROVED = "approved"
APP_REJECTED = "rejected"

# Visibilidade no feed: legado (NULL) conta como publicado.
PUBLISHED_SQL = (
    "(moderation_status IS NULL OR moderation_status = '' OR moderation_status = 'published')"
)

BOOST_CAP_PRIORITY = 90
MIN_TITLE_LEN = 12
MIN_SUMMARY_LEN = 40
MIN_BODY_LEN = 200
MAX_TITLE_LEN = 200
MAX_SUMMARY_LEN = 800
MAX_BODY_LEN = 50000
COVER_MAX_BYTES = 1024 * 1024
COVER_ALLOWED = {".jpg", ".jpeg", ".png", ".webp"}


def save_columnist_cover(user_id: int, filename: str, data: bytes) -> str:
    """Salva capa opcional do artigo; retorna URL pública /media/articles/..."""
    from pathlib import Path

    ext = Path(filename or "").suffix.lower()
    if ext not in COVER_ALLOWED:
        raise ValueError("Capa: use JPG, PNG ou WEBP.")
    if not data or len(data) > COVER_MAX_BYTES:
        raise ValueError("Capa inválida ou maior que 1 MB.")
    if not (
        data[:3] == b"\xff\xd8\xff"
        or data[:8] == b"\x89PNG\r\n\x1a\n"
        or data[:4] == b"RIFF"
    ):
        raise ValueError("Arquivo de capa não parece uma imagem válida.")
    root = Path(os.getenv("ARTICLE_IMAGES_DIR", "static/images/articles"))
    root.mkdir(parents=True, exist_ok=True)
    safe = f"col_{int(user_id)}_{secrets.token_hex(8)}{ext}"
    (root / safe).write_bytes(data)
    return f"/media/articles/{safe}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def columnist_share_rate() -> float:
    raw = _env("COLUMNIST_SHARE_RATE", "0.35")
    try:
        rate = float(raw)
    except ValueError:
        rate = 0.35
    return max(0.30, min(0.40, rate))


def site_rpm_brl() -> float:
    raw = _env("COLUMNIST_SITE_RPM_BRL", "8.0")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 8.0


def payout_min_brl() -> float:
    raw = _env("COLUMNIST_PAYOUT_MIN_BRL", "50")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 50.0


def admin_emails() -> set[str]:
    raw = _env("COLUMNIST_ADMIN_EMAILS") or _env("ADMIN_EMAILS")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def get_admin_token() -> str:
    return _env("ADMIN_TOKEN") or _env("COLUMNIST_ADMIN_TOKEN")


def is_admin_user(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    role = str(user.get("role") or ROLE_USER).lower()
    if role == ROLE_ADMIN:
        return True
    email = str(user.get("email") or "").strip().lower()
    return bool(email and email in admin_emails())


def is_columnist_user(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    if is_admin_user(user):
        return True
    return str(user.get("role") or "").lower() == ROLE_COLUMNIST


def tokens_match(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    a = provided.encode("utf-8")
    b = expected.encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def enrich_user_role(client, user: dict[str, Any] | None) -> dict[str, Any] | None:
    """Garante role/pix_key no dict do usuário (schema pode estar atrasado)."""
    if not user:
        return None
    if "role" in user and user.get("role") is not None:
        email = str(user.get("email") or "").lower()
        if email in admin_emails() and user.get("role") != ROLE_ADMIN:
            user = dict(user)
            user["role"] = ROLE_ADMIN
        return user
    try:
        result = client.execute(
            "SELECT role, pix_key FROM users WHERE id = ? LIMIT 1",
            [int(user["id"])],
        )
        if result.rows:
            user = dict(user)
            user["role"] = str(result.rows[0][0] or ROLE_USER)
            user["pix_key"] = result.rows[0][1]
            if str(user.get("email") or "").lower() in admin_emails():
                user["role"] = ROLE_ADMIN
    except Exception:
        user = dict(user)
        user["role"] = ROLE_ADMIN if str(user.get("email") or "").lower() in admin_emails() else ROLE_USER
        user["pix_key"] = None
    return user


def set_user_role(client, user_id: int, role: str) -> None:
    role = role if role in (ROLE_USER, ROLE_COLUMNIST, ROLE_ADMIN) else ROLE_USER
    client.execute("UPDATE users SET role = ? WHERE id = ?", [role, int(user_id)])


def set_user_pix_key(client, user_id: int, pix_key: str | None) -> None:
    client.execute(
        "UPDATE users SET pix_key = ? WHERE id = ?",
        [(pix_key or "").strip() or None, int(user_id)],
    )


# --- Candidaturas ---


def get_application(client, user_id: int) -> dict[str, Any] | None:
    result = client.execute(
        """
        SELECT id, user_id, pitch, status, admin_note, created_at, reviewed_at
        FROM columnist_applications WHERE user_id = ? ORDER BY id DESC LIMIT 1
        """,
        [int(user_id)],
    )
    if not result.rows:
        return None
    row = result.rows[0]
    return {
        "id": int(row[0]),
        "user_id": int(row[1]),
        "pitch": str(row[2] or ""),
        "status": str(row[3] or APP_PENDING),
        "admin_note": row[4],
        "created_at": row[5],
        "reviewed_at": row[6],
    }


def submit_application(client, user_id: int, pitch: str) -> dict[str, Any]:
    pitch = (pitch or "").strip()
    if len(pitch) < 40:
        raise ValueError("Conte uma apresentação com pelo menos 40 caracteres.")
    if len(pitch) > 2000:
        raise ValueError("Apresentação excede 2000 caracteres.")
    existing = get_application(client, user_id)
    if existing and existing["status"] == APP_PENDING:
        raise ValueError("Você já tem uma candidatura em análise.")
    if existing and existing["status"] == APP_APPROVED:
        raise ValueError("Você já é colunista.")
    now = utc_now_iso()
    client.execute(
        """
        INSERT INTO columnist_applications (user_id, pitch, status, created_at)
        VALUES (?, ?, ?, ?)
        """,
        [int(user_id), pitch, APP_PENDING, now],
    )
    return get_application(client, user_id) or {"status": APP_PENDING}


def list_pending_applications(client, limit: int = 50) -> list[dict[str, Any]]:
    result = client.execute(
        """
        SELECT a.id, a.user_id, a.pitch, a.status, a.created_at, u.name, u.email
        FROM columnist_applications a
        JOIN users u ON u.id = a.user_id
        WHERE a.status = ?
        ORDER BY a.id ASC LIMIT ?
        """,
        [APP_PENDING, int(limit)],
    )
    rows = []
    for row in result.rows or []:
        rows.append(
            {
                "id": int(row[0]),
                "user_id": int(row[1]),
                "pitch": str(row[2] or ""),
                "status": str(row[3] or ""),
                "created_at": row[4],
                "user_name": row[5],
                "user_email": row[6],
            }
        )
    return rows


def review_application(
    client, application_id: int, *, approve: bool, admin_note: str = ""
) -> dict[str, Any]:
    result = client.execute(
        "SELECT id, user_id, status FROM columnist_applications WHERE id = ? LIMIT 1",
        [int(application_id)],
    )
    if not result.rows:
        raise ValueError("Candidatura não encontrada.")
    user_id = int(result.rows[0][1])
    status = APP_APPROVED if approve else APP_REJECTED
    now = utc_now_iso()
    client.execute(
        """
        UPDATE columnist_applications
        SET status = ?, admin_note = ?, reviewed_at = ?
        WHERE id = ?
        """,
        [status, (admin_note or "").strip()[:500], now, int(application_id)],
    )
    if approve:
        set_user_role(client, user_id, ROLE_COLUMNIST)
    return {"id": int(application_id), "user_id": user_id, "status": status}


# --- Artigos ---


def _slug_token() -> str:
    return secrets.token_hex(4)


def validate_article_fields(titulo: str, resumo: str, body: str, tag: str) -> tuple[str, str, str, str]:
    titulo = (titulo or "").strip()
    resumo = (resumo or "").strip()
    body = (body or "").strip()
    tag = (tag or "").strip() or "Economia"
    if len(titulo) < MIN_TITLE_LEN:
        raise ValueError(f"Título muito curto (mín. {MIN_TITLE_LEN}).")
    if len(titulo) > MAX_TITLE_LEN:
        raise ValueError(f"Título muito longo (máx. {MAX_TITLE_LEN}).")
    if len(resumo) < MIN_SUMMARY_LEN:
        raise ValueError(f"Resumo muito curto (mín. {MIN_SUMMARY_LEN}).")
    if len(resumo) > MAX_SUMMARY_LEN:
        raise ValueError(f"Resumo muito longo (máx. {MAX_SUMMARY_LEN}).")
    if len(body) < MIN_BODY_LEN:
        raise ValueError(f"Texto muito curto (mín. {MIN_BODY_LEN} caracteres).")
    if len(body) > MAX_BODY_LEN:
        raise ValueError("Texto excede o limite permitido.")
    if find_blocked_terms(body) or find_blocked_terms(titulo):
        raise ValueError("Texto rejeitado pela moderação automática. Revise o conteúdo.")
    return titulo, resumo, body, tag


def create_article(
    client,
    *,
    user_id: int,
    author_name: str,
    titulo: str,
    resumo: str,
    body: str,
    tag: str,
    submit: bool,
    imagem_url: str | None = None,
) -> int:
    titulo, resumo, body, tag = validate_article_fields(titulo, resumo, body, tag)
    now = utc_now_iso()
    status = STATUS_PENDING if submit else STATUS_DRAFT
    link = f"internal://columnist/{user_id}/{_slug_token()}"
    fonte = f"Colunista · {author_name}"
    client.execute(
        """
        INSERT INTO news (
            titulo, resumo, impacto, link, tag, sentimento, published_at, fonte,
            created_at, updated_at, conteudo_extra, home_priority, imagem_url,
            author_id, content_origin, moderation_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            titulo,
            resumo,
            body[:4000],
            link,
            tag,
            "Neutro",
            now if submit else None,
            fonte,
            now,
            now,
            body,
            20,
            (imagem_url or "").strip() or None,
            int(user_id),
            ORIGIN_COLUMNIST,
            status,
        ],
    )
    result = client.execute("SELECT id FROM news WHERE link = ? LIMIT 1", [link])
    if not result.rows:
        raise RuntimeError("Falha ao criar artigo.")
    return int(result.rows[0][0])


def update_article(
    client,
    *,
    news_id: int,
    user_id: int,
    titulo: str,
    resumo: str,
    body: str,
    tag: str,
    submit: bool,
    is_admin: bool = False,
    imagem_url: str | None = None,
) -> None:
    article = get_article_for_author(client, news_id, user_id if not is_admin else None)
    if not article:
        raise ValueError("Artigo não encontrado.")
    if not is_admin and int(article["author_id"]) != int(user_id):
        raise PermissionError("Sem permissão.")
    if not is_admin and article["moderation_status"] == STATUS_PUBLISHED:
        raise ValueError("Artigo publicado: abra nova versão ou peça revisão ao admin.")
    titulo, resumo, body, tag = validate_article_fields(titulo, resumo, body, tag)
    now = utc_now_iso()
    status = article["moderation_status"]
    if submit:
        status = STATUS_PENDING
    elif status == STATUS_REJECTED:
        status = STATUS_DRAFT
    cover = (imagem_url or "").strip() or article.get("imagem_url")
    client.execute(
        """
        UPDATE news SET
            titulo = ?, resumo = ?, impacto = ?, tag = ?, conteudo_extra = ?,
            updated_at = ?, moderation_status = ?, imagem_url = ?,
            published_at = CASE WHEN ? = 'pending' THEN COALESCE(published_at, ?) ELSE published_at END
        WHERE id = ?
        """,
        [
            titulo,
            resumo,
            body[:4000],
            tag,
            body,
            now,
            status,
            cover,
            status,
            now,
            int(news_id),
        ],
    )


def get_article_for_author(client, news_id: int, user_id: int | None) -> dict[str, Any] | None:
    result = client.execute(
        """
        SELECT id, titulo, resumo, conteudo_extra, impacto, tag, author_id,
               content_origin, moderation_status, home_priority, boost_until,
               published_at, created_at, imagem_url, fonte
        FROM news WHERE id = ? LIMIT 1
        """,
        [int(news_id)],
    )
    if not result.rows:
        return None
    row = result.rows[0]
    data = {
        "id": int(row[0]),
        "titulo": str(row[1] or ""),
        "resumo": str(row[2] or ""),
        "body": str(row[3] or row[4] or ""),
        "tag": str(row[5] or ""),
        "author_id": int(row[6]) if row[6] is not None else None,
        "content_origin": str(row[7] or ORIGIN_EDITORIAL),
        "moderation_status": str(row[8] or STATUS_PUBLISHED),
        "home_priority": int(row[9] or 0),
        "boost_until": row[10],
        "published_at": row[11],
        "created_at": row[12],
        "imagem_url": row[13],
        "fonte": row[14],
    }
    if user_id is not None and data["author_id"] != int(user_id):
        return None
    return data


def list_author_articles(client, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    result = client.execute(
        """
        SELECT id, titulo, moderation_status, created_at, updated_at, home_priority, boost_until
        FROM news
        WHERE author_id = ? AND content_origin = ?
        ORDER BY id DESC LIMIT ?
        """,
        [int(user_id), ORIGIN_COLUMNIST, int(limit)],
    )
    return [
        {
            "id": int(r[0]),
            "titulo": str(r[1] or ""),
            "moderation_status": str(r[2] or ""),
            "created_at": r[3],
            "updated_at": r[4],
            "home_priority": int(r[5] or 0),
            "boost_until": r[6],
        }
        for r in (result.rows or [])
    ]


def list_pending_articles(client, limit: int = 50) -> list[dict[str, Any]]:
    result = client.execute(
        """
        SELECT n.id, n.titulo, n.created_at, n.author_id, u.name, u.email
        FROM news n
        LEFT JOIN users u ON u.id = n.author_id
        WHERE n.content_origin = ? AND n.moderation_status = ?
        ORDER BY n.id ASC LIMIT ?
        """,
        [ORIGIN_COLUMNIST, STATUS_PENDING, int(limit)],
    )
    return [
        {
            "id": int(r[0]),
            "titulo": str(r[1] or ""),
            "created_at": r[2],
            "author_id": int(r[3]) if r[3] is not None else None,
            "author_name": r[4],
            "author_email": r[5],
        }
        for r in (result.rows or [])
    ]


def review_article(client, news_id: int, *, approve: bool, admin_note: str = "") -> None:
    article = get_article_for_author(client, news_id, None)
    if not article or article["content_origin"] != ORIGIN_COLUMNIST:
        raise ValueError("Artigo de colunista não encontrado.")
    now = utc_now_iso()
    if approve:
        client.execute(
            """
            UPDATE news SET moderation_status = ?, published_at = COALESCE(published_at, ?),
                   updated_at = ?, home_priority = CASE
                       WHEN COALESCE(home_priority, 0) < 20 THEN 50 ELSE home_priority END
            WHERE id = ?
            """,
            [STATUS_PUBLISHED, now, now, int(news_id)],
        )
    else:
        note = (admin_note or "").strip()[:500]
        client.execute(
            """
            UPDATE news SET moderation_status = ?, updated_at = ?,
                   contexto_editorial = COALESCE(contexto_editorial, '') || ?
            WHERE id = ?
            """,
            [STATUS_REJECTED, now, f"\n[Revisão] {note}" if note else "", int(news_id)],
        )


def get_author_public(client, author_id: int | None) -> dict[str, Any] | None:
    if not author_id:
        return None
    user = community.find_user_by_id(client, int(author_id))
    if not user:
        return None
    return {
        "id": user["id"],
        "name": user["name"],
        "avatar_url": user.get("avatar_url"),
    }


# --- Pageviews e carteira ---


def _viewer_hash(ip: str | None, ua: str | None) -> str:
    salt = _env("IP_HASH_SALT", "clareza-columnist")
    raw = f"{salt}|{(ip or '').strip()}|{(ua or '')[:120]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def record_page_view(
    client,
    news_id: int,
    *,
    author_id: int | None,
    ip: str | None,
    user_agent: str | None,
    viewer_user_id: int | None = None,
) -> bool:
    """Registra 1 view por visitante/dia. Retorna True se creditou."""
    if not author_id:
        return False
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    vhash = _viewer_hash(ip, user_agent)
    try:
        client.execute(
            """
            INSERT INTO page_views (news_id, author_id, viewer_hash, viewer_user_id, day, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                int(news_id),
                int(author_id),
                vhash,
                int(viewer_user_id) if viewer_user_id else None,
                day,
                utc_now_iso(),
            ],
        )
        return True
    except Exception:
        return False


def count_views(client, news_id: int | None = None, author_id: int | None = None) -> int:
    if news_id is not None:
        result = client.execute(
            "SELECT COUNT(*) FROM page_views WHERE news_id = ?",
            [int(news_id)],
        )
    elif author_id is not None:
        result = client.execute(
            "SELECT COUNT(*) FROM page_views WHERE author_id = ?",
            [int(author_id)],
        )
    else:
        return 0
    return int(result.rows[0][0]) if result.rows else 0


def wallet_balance(client, user_id: int) -> float:
    result = client.execute(
        "SELECT COALESCE(SUM(amount_brl), 0) FROM wallet_ledger WHERE user_id = ?",
        [int(user_id)],
    )
    return float(result.rows[0][0]) if result.rows else 0.0


def list_ledger(client, user_id: int, limit: int = 40) -> list[dict[str, Any]]:
    result = client.execute(
        """
        SELECT id, kind, amount_brl, news_id, meta_json, created_at
        FROM wallet_ledger WHERE user_id = ? ORDER BY id DESC LIMIT ?
        """,
        [int(user_id), int(limit)],
    )
    return [
        {
            "id": int(r[0]),
            "kind": str(r[1] or ""),
            "amount_brl": float(r[2] or 0),
            "news_id": int(r[3]) if r[3] is not None else None,
            "meta_json": r[4],
            "created_at": r[5],
        }
        for r in (result.rows or [])
    ]


def credit_daily_shares(client, day: str | None = None) -> dict[str, Any]:
    """Credita participação estimada: views do dia × RPM × share / 1000."""
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Evita crédito duplicado no mesmo dia.
    marker = client.execute(
        "SELECT id FROM wallet_ledger WHERE kind = ? AND meta_json LIKE ? LIMIT 1",
        ["daily_share", f'%"day": "{day}"%'],
    )
    if marker.rows:
        return {"ok": True, "skipped": True, "day": day, "credited": 0}

    share = columnist_share_rate()
    rpm = site_rpm_brl()
    result = client.execute(
        """
        SELECT author_id, news_id, COUNT(*) AS views
        FROM page_views
        WHERE day = ?
        GROUP BY author_id, news_id
        """,
        [day],
    )
    credited = 0.0
    entries = 0
    now = utc_now_iso()
    for row in result.rows or []:
        author_id = int(row[0])
        news_id = int(row[1])
        views = int(row[2] or 0)
        if views <= 0:
            continue
        amount = round((views / 1000.0) * rpm * share, 4)
        if amount <= 0:
            continue
        meta = json.dumps(
            {"day": day, "views": views, "rpm": rpm, "share": share, "news_id": news_id},
            ensure_ascii=False,
        )
        client.execute(
            """
            INSERT INTO wallet_ledger (user_id, kind, amount_brl, news_id, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [author_id, "daily_share", amount, news_id, meta, now],
        )
        credited += amount
        entries += 1
    return {"ok": True, "day": day, "credited": round(credited, 2), "entries": entries, "share": share, "rpm": rpm}


def request_payout(client, user_id: int, amount: float | None = None) -> dict[str, Any]:
    balance = wallet_balance(client, user_id)
    min_brl = payout_min_brl()
    amount = float(amount) if amount is not None else balance
    amount = round(amount, 2)
    if amount < min_brl:
        raise ValueError(f"Saque mínimo: R$ {min_brl:.2f}.")
    if amount > balance + 1e-6:
        raise ValueError("Saldo insuficiente.")
    user = community.find_user_by_id(client, user_id)
    user = enrich_user_role(client, user)
    pix = (user or {}).get("pix_key") if user else None
    if not pix:
        raise ValueError("Cadastre sua chave PIX no painel do colunista.")
    now = utc_now_iso()
    client.execute(
        """
        INSERT INTO payout_requests (user_id, amount_brl, pix_key, status, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        [int(user_id), amount, str(pix), "pending", now],
    )
    client.execute(
        """
        INSERT INTO wallet_ledger (user_id, kind, amount_brl, news_id, meta_json, created_at)
        VALUES (?, ?, ?, NULL, ?, ?)
        """,
        [int(user_id), "payout_hold", -amount, json.dumps({"pix_key": pix}, ensure_ascii=False), now],
    )
    return {"ok": True, "amount_brl": amount, "status": "pending"}


def list_pending_payouts(client, limit: int = 50) -> list[dict[str, Any]]:
    result = client.execute(
        """
        SELECT p.id, p.user_id, p.amount_brl, p.pix_key, p.status, p.created_at, u.name, u.email
        FROM payout_requests p
        JOIN users u ON u.id = p.user_id
        WHERE p.status = 'pending'
        ORDER BY p.id ASC LIMIT ?
        """,
        [int(limit)],
    )
    return [
        {
            "id": int(r[0]),
            "user_id": int(r[1]),
            "amount_brl": float(r[2] or 0),
            "pix_key": r[3],
            "status": r[4],
            "created_at": r[5],
            "user_name": r[6],
            "user_email": r[7],
        }
        for r in (result.rows or [])
    ]


def settle_payout(client, payout_id: int, *, paid: bool, admin_note: str = "") -> None:
    result = client.execute(
        "SELECT id, user_id, amount_brl, status FROM payout_requests WHERE id = ? LIMIT 1",
        [int(payout_id)],
    )
    if not result.rows:
        raise ValueError("Saque não encontrado.")
    row = result.rows[0]
    if str(row[3]) != "pending":
        raise ValueError("Saque já processado.")
    user_id = int(row[1])
    amount = float(row[2] or 0)
    now = utc_now_iso()
    status = "paid" if paid else "rejected"
    client.execute(
        """
        UPDATE payout_requests SET status = ?, admin_note = ?, reviewed_at = ? WHERE id = ?
        """,
        [status, (admin_note or "").strip()[:500], now, int(payout_id)],
    )
    if not paid:
        # Devolve hold.
        client.execute(
            """
            INSERT INTO wallet_ledger (user_id, kind, amount_brl, news_id, meta_json, created_at)
            VALUES (?, ?, ?, NULL, ?, ?)
            """,
            [
                user_id,
                "payout_refund",
                amount,
                json.dumps({"payout_id": int(payout_id)}, ensure_ascii=False),
                now,
            ],
        )


# --- Boost / destaque pago ---

def boost_plans() -> dict[str, dict[str, Any]]:
    return {
        "carousel_24h": {
            "id": "carousel_24h",
            "label": "Carrossel 24h",
            "hours": 24,
            "priority": 88,
            "price_brl": float(_env("BOOST_PRICE_CAROUSEL_BRL", "49.90") or "49.90"),
        },
        "featured_7d": {
            "id": "featured_7d",
            "label": "Destaques 7 dias",
            "hours": 24 * 7,
            "priority": 75,
            "price_brl": float(_env("BOOST_PRICE_FEATURED_BRL", "99.90") or "99.90"),
        },
    }


def get_boost_plan(plan_id: str) -> dict[str, Any]:
    plan = boost_plans().get(plan_id)
    if not plan:
        raise ValueError("Plano de destaque inválido.")
    return plan


def create_boost_order(
    client,
    *,
    user_id: int,
    news_id: int,
    plan_id: str,
) -> dict[str, Any]:
    article = get_article_for_author(client, news_id, user_id)
    if not article:
        raise ValueError("Artigo não encontrado.")
    if article["moderation_status"] != STATUS_PUBLISHED:
        raise ValueError("Só é possível impulsionar artigos publicados.")
    plan = get_boost_plan(plan_id)
    now = utc_now_iso()
    external_ref = f"boost-{user_id}-{news_id}-{secrets.token_hex(4)}"
    client.execute(
        """
        INSERT INTO boost_orders (
            user_id, news_id, plan_id, amount_brl, status, external_ref, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            int(user_id),
            int(news_id),
            plan["id"],
            float(plan["price_brl"]),
            "pending",
            external_ref,
            now,
        ],
    )
    result = client.execute(
        "SELECT id FROM boost_orders WHERE external_ref = ? LIMIT 1",
        [external_ref],
    )
    order_id = int(result.rows[0][0])
    return {
        "id": order_id,
        "external_ref": external_ref,
        "plan": plan,
        "news_id": int(news_id),
        "amount_brl": float(plan["price_brl"]),
    }


def activate_boost(client, order_id: int) -> None:
    result = client.execute(
        """
        SELECT id, news_id, plan_id, status FROM boost_orders WHERE id = ? LIMIT 1
        """,
        [int(order_id)],
    )
    if not result.rows:
        raise ValueError("Pedido de destaque não encontrado.")
    row = result.rows[0]
    if str(row[3]) == "paid":
        return
    plan = get_boost_plan(str(row[2]))
    news_id = int(row[1])
    until = datetime.now(timezone.utc) + timedelta(hours=int(plan["hours"]))
    until_iso = until.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    priority = min(BOOST_CAP_PRIORITY, int(plan["priority"]))
    now = utc_now_iso()
    cur = client.execute(
        "SELECT COALESCE(home_priority, 0) FROM news WHERE id = ? LIMIT 1",
        [news_id],
    )
    current = int(cur.rows[0][0]) if cur.rows else 0
    new_priority = max(current, priority)
    client.execute(
        """
        UPDATE news SET home_priority = ?, boost_until = ?, updated_at = ?
        WHERE id = ?
        """,
        [new_priority, until_iso, now, news_id],
    )
    client.execute(
        """
        UPDATE boost_orders SET status = 'paid', paid_at = ?, boost_until = ? WHERE id = ?
        """,
        [now, until_iso, int(order_id)],
    )


def find_boost_by_external_ref(client, external_ref: str) -> dict[str, Any] | None:
    result = client.execute(
        """
        SELECT id, user_id, news_id, plan_id, amount_brl, status, external_ref
        FROM boost_orders WHERE external_ref = ? LIMIT 1
        """,
        [external_ref],
    )
    if not result.rows:
        return None
    r = result.rows[0]
    return {
        "id": int(r[0]),
        "user_id": int(r[1]),
        "news_id": int(r[2]),
        "plan_id": str(r[3]),
        "amount_brl": float(r[4] or 0),
        "status": str(r[5]),
        "external_ref": str(r[6]),
    }


def expire_boosts(client) -> int:
    """Remove prioridade de boosts vencidos. Retorna quantidade afetada."""
    now = utc_now_iso()
    result = client.execute(
        """
        SELECT id, home_priority FROM news
        WHERE boost_until IS NOT NULL AND boost_until != '' AND boost_until < ?
        LIMIT 200
        """,
        [now],
    )
    n = 0
    for row in result.rows or []:
        nid = int(row[0])
        client.execute(
            """
            UPDATE news SET boost_until = NULL,
                   home_priority = CASE
                       WHEN COALESCE(home_priority, 0) > 50 THEN 50
                       ELSE COALESCE(home_priority, 20)
                   END
            WHERE id = ?
            """,
            [nid],
        )
        n += 1
    return n


# --- Mercado Pago (PIX) ---


def mp_access_token() -> str:
    return _env("MERCADOPAGO_ACCESS_TOKEN")


def mp_configured() -> bool:
    return bool(mp_access_token())


def mp_create_pix_payment(
    *,
    amount_brl: float,
    description: str,
    external_reference: str,
    payer_email: str,
    notification_url: str | None = None,
) -> dict[str, Any]:
    token = mp_access_token()
    if not token:
        raise RuntimeError("MERCADOPAGO_ACCESS_TOKEN não configurado.")
    payload: dict[str, Any] = {
        "transaction_amount": round(float(amount_brl), 2),
        "description": description[:200],
        "payment_method_id": "pix",
        "external_reference": external_reference,
        "payer": {"email": payer_email},
    }
    if notification_url:
        payload["notification_url"] = notification_url
    res = requests.post(
        "https://api.mercadopago.com/v1/payments",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": external_reference,
        },
        json=payload,
        timeout=30,
    )
    if res.status_code >= 400:
        raise RuntimeError(f"Mercado Pago erro {res.status_code}: {res.text[:300]}")
    data = res.json()
    poi = (data.get("point_of_interaction") or {}).get("transaction_data") or {}
    return {
        "payment_id": data.get("id"),
        "status": data.get("status"),
        "qr_code": poi.get("qr_code"),
        "qr_code_base64": poi.get("qr_code_base64"),
        "ticket_url": poi.get("ticket_url"),
        "external_reference": external_reference,
        "raw": data,
    }


def mp_get_payment(payment_id: str | int) -> dict[str, Any]:
    token = mp_access_token()
    if not token:
        raise RuntimeError("MERCADOPAGO_ACCESS_TOKEN não configurado.")
    res = requests.get(
        f"https://api.mercadopago.com/v1/payments/{quote(str(payment_id))}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if res.status_code >= 400:
        raise RuntimeError(f"Mercado Pago get erro {res.status_code}")
    return res.json()


def sanitize_plain(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return text.strip()
