"""Religa no Turso as capas cujo arquivo ja existe (slug = hash do link).

Use depois de subir os JPGs para o disco do Render (/var/data/article_images)
quando o banco ficou com imagem_url NULL (ex.: apos revert_local_only_covers).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

_ = load_dotenv(ROOT / ".env")

from db import get_db


def slug_for(link: str, article_id: int) -> str:
    key = (link or "").strip() or f"article-{article_id}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def main() -> int:
    images_dir = ROOT / "static" / "images" / "articles"
    local = {p.name for p in images_dir.glob("*.jpg")} | {p.name for p in images_dir.glob("*.png")}
    print(f"arquivos_locais={len(local)}")

    client = get_db()
    rows = client.execute(
        """
        SELECT id, link, imagem_url FROM news
        WHERE imagem_url IS NULL OR TRIM(COALESCE(imagem_url, '')) = ''
        ORDER BY id DESC
        """
    ).rows

    updates: list[tuple[str, int]] = []
    for article_id, link, _ in rows:
        aid = int(article_id)
        slug = slug_for(str(link or ""), aid)
        for ext in ("jpg", "png"):
            name = f"{slug}.{ext}"
            if name in local:
                updates.append((f"/media/articles/{name}", aid))
                break

    print(f"sem_capa={len(rows)} relinkaveis={len(updates)}")
    if not updates:
        print("Nada a religar.")
        return 0

    batch = 50
    done = 0
    for i in range(0, len(updates), batch):
        chunk = updates[i : i + batch]
        for url, aid in chunk:
            client.execute("UPDATE news SET imagem_url = ? WHERE id = ?", [url, aid])
        done += len(chunk)
        print(f"relinkadas={done}/{len(updates)}")

    with_url = client.execute(
        """
        SELECT COUNT(*) FROM news
        WHERE imagem_url IS NOT NULL AND TRIM(imagem_url) != ''
        """
    ).rows[0][0]
    print(f"OK com_url_agora={with_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
