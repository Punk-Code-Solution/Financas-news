"""Conta notícias com/sem capa no Turso (diagnóstico rápido)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

_ = load_dotenv(ROOT / ".env")
from db import get_db, reset_db_client


def main() -> int:
    reset_db_client()
    c = get_db()
    miss = int(
        c.execute(
            """
            SELECT COUNT(*) FROM news
            WHERE imagem_url IS NULL OR TRIM(COALESCE(imagem_url, '')) = ''
            """
        ).rows[0][0]
    )
    total = int(c.execute("SELECT COUNT(*) FROM news").rows[0][0])
    with_url = int(
        c.execute(
            """
            SELECT COUNT(*) FROM news
            WHERE imagem_url IS NOT NULL AND TRIM(imagem_url) != ''
            """
        ).rows[0][0]
    )
    pexels = int(
        c.execute(
            """
            SELECT COUNT(*) FROM news
            WHERE imagem_url LIKE '%pexels%'
            """
        ).rows[0][0]
    )
    media = int(
        c.execute(
            """
            SELECT COUNT(*) FROM news
            WHERE imagem_url LIKE '/media/%' OR imagem_url LIKE '%/media/articles/%'
            """
        ).rows[0][0]
    )
    print(f"total={total}")
    print(f"com_capa={with_url}")
    print(f"sem_capa={miss}")
    print(f"pexels_cdn={pexels}")
    print(f"media_local={media}")
    print("--- mais novas sem capa (ate 15) ---")
    rows = c.execute(
        """
        SELECT id, titulo, COALESCE(published_at, created_at, '')
        FROM news
        WHERE imagem_url IS NULL OR TRIM(COALESCE(imagem_url, '')) = ''
        ORDER BY id DESC
        LIMIT 15
        """
    ).rows
    for row in rows:
        titulo = (row[1] or "")[:70]
        print(f"id={row[0]} data={row[2]} | {titulo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
