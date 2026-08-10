"""Semeia SQLite local para QA visual do front (não usa Turso)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
os.environ["USE_LOCAL_DB"] = "1"
os.environ["LOCAL_DATABASE_PATH"] = str(ROOT / "qa_frontend.db")
os.environ["COLUMNIST_ADMIN_EMAILS"] = "admin-qa@clareza.test"

from db import LocalDbClient, ensure_schema
import community_auth as community
import columnists

PASSWORD = "senha-segura-123"
USER_EMAIL = "qa.user@clareza.test"
ADMIN_EMAIL = "admin-qa@clareza.test"
COLUMNIST_EMAIL = "qa.colunista@clareza.test"


def main() -> None:
    path = os.environ["LOCAL_DATABASE_PATH"]
    client = LocalDbClient(path)
    import db as dbmod

    dbmod._schema_ready = False
    dbmod._fts_ready = False
    ensure_schema(client)

    resumo = ("Análise editorial de QA visual. " * 40)[:900]
    existing = client.execute("SELECT id FROM news WHERE link = ?", ["https://example.test/qa-selic"])
    if not existing.rows:
        client.execute(
            """
            INSERT INTO news (
                titulo, resumo, impacto, link, tag, sentimento, published_at, fonte,
                created_at, moderation_status, home_priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', 85)
            """,
            [
                "Copom e o crédito: leitura de QA",
                resumo,
                "Juros altos pressionam financiamento imobiliário.",
                "https://example.test/qa-selic",
                "Juros",
                "Neutro",
                "2026-08-09T20:00:00Z",
                "Clareza Capital",
                "2026-08-09T20:00:00Z",
            ],
        )

    for name, email, role in (
        ("QA User", USER_EMAIL, "user"),
        ("Admin QA", ADMIN_EMAIL, "admin"),
        ("Colunista QA", COLUMNIST_EMAIL, "columnist"),
    ):
        found = community.find_user_by_email(client, email)
        if not found:
            user = community.create_user(client, name=name, email=email, password=PASSWORD)
            community.mark_email_verified(client, int(user["id"]))
            uid = int(user["id"])
        else:
            uid = int(found["id"])
            if not found.get("email_verified"):
                community.mark_email_verified(client, uid)
        client.execute("UPDATE users SET role = ? WHERE id = ?", [role, uid])

    print("SQLite:", path)
    print("Login QA:", USER_EMAIL, "/", PASSWORD)
    print("Login colunista:", COLUMNIST_EMAIL, "/", PASSWORD)
    print("Login admin:", ADMIN_EMAIL, "/", PASSWORD)


if __name__ == "__main__":
    main()
