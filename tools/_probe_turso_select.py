"""Probe which SELECT shapes fail against Turso via PooledClient."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

_ = load_dotenv(ROOT / ".env")
from db import get_db, reset_db_client

SQLS = [
    ("simple_order", "SELECT id FROM news ORDER BY id DESC LIMIT 3"),
    (
        "missing_full",
        """
        SELECT id, titulo, data_publicacao FROM news
        WHERE imagem_url IS NULL OR TRIM(COALESCE(imagem_url, '')) = ''
        ORDER BY id DESC LIMIT 15
        """,
    ),
    (
        "missing_no_trim",
        """
        SELECT id, titulo FROM news
        WHERE imagem_url IS NULL OR imagem_url = ''
        ORDER BY id DESC LIMIT 15
        """,
    ),
    (
        "missing_no_order",
        """
        SELECT id FROM news
        WHERE imagem_url IS NULL OR TRIM(COALESCE(imagem_url, '')) = ''
        LIMIT 15
        """,
    ),
    (
        "missing_id_only_order",
        """
        SELECT id FROM news
        WHERE imagem_url IS NULL OR TRIM(COALESCE(imagem_url, '')) = ''
        ORDER BY id DESC LIMIT 15
        """,
    ),
    (
        "missing_substr",
        """
        SELECT id, substr(titulo, 1, 60) AS t, data_publicacao
        FROM news
        WHERE imagem_url IS NULL OR length(trim(ifnull(imagem_url, ''))) = 0
        ORDER BY id DESC LIMIT 15
        """,
    ),
]


def main() -> int:
    reset_db_client()
    c = get_db()
    for name, sql in SQLS:
        try:
            rows = c.execute(sql).rows
            print(f"OK {name}: {len(rows)} rows sample={rows[:2]!r}")
        except Exception as exc:
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
