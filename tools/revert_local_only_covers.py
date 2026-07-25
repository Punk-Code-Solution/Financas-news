"""Reverte no Turso as capas cujo arquivo so existe localmente (404 no Render).

Mantem os JPGs em static/images/articles para sync/regeneracao posterior.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from db import get_db


def main() -> int:
    images_dir = ROOT / "static" / "images" / "articles"
    local_names = {p.name for p in images_dir.glob("*.jpg")} | {
        p.name for p in images_dir.glob("*.png")
    }
    if not local_names:
        print("Nenhum arquivo local em static/images/articles")
        return 1

    client = get_db()
    rows = client.execute(
        """
        SELECT id, imagem_url FROM news
        WHERE imagem_url IS NOT NULL AND TRIM(imagem_url) != ''
        """
    ).rows

    to_clear: list[int] = []
    for article_id, imagem_url in rows:
        url = str(imagem_url or "").strip()
        name = url.rsplit("/", 1)[-1].split("?", 1)[0]
        if name in local_names:
            to_clear.append(int(article_id))

    print(f"local_files={len(local_names)} candidatas_db={len(to_clear)}")
    if not to_clear:
        print("Nada a reverter.")
        return 0

    # Lotes para nao estourar payload do Turso
    batch = 100
    cleared = 0
    for i in range(0, len(to_clear), batch):
        chunk = to_clear[i : i + batch]
        placeholders = ",".join("?" * len(chunk))
        client.execute(
            f"UPDATE news SET imagem_url = NULL WHERE id IN ({placeholders})",
            chunk,
        )
        cleared += len(chunk)
        print(f"revertidas={cleared}/{len(to_clear)}")

    miss = client.execute(
        """
        SELECT COUNT(*) FROM news
        WHERE imagem_url IS NULL OR TRIM(COALESCE(imagem_url, '')) = ''
        """
    ).rows[0][0]
    print(f"OK sem_capa_agora={miss}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
