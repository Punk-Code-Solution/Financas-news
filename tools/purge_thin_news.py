"""Remove notícias thin (resumo curto) que prejudicam indexação no Google.

Protege guias evergreen. Uso:
  PYTHONPATH=. python tools/purge_thin_news.py --dry-run
  PYTHONPATH=. python tools/purge_thin_news.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from db import get_db, sync_news_fts  # noqa: E402
from educational_guides import EDUCATIONAL_GUIDES, find_guide_noticia_id  # noqa: E402

MIN_RESUMO = 400


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Executa DELETE (sem isso: dry-run)")
    parser.add_argument("--min-resumo", type=int, default=MIN_RESUMO)
    args = parser.parse_args()

    client = get_db()
    guide_ids: set[int] = set()
    for guide in EDUCATIONAL_GUIDES:
        nid = find_guide_noticia_id(client, guide["slug"])
        if nid:
            guide_ids.add(int(nid))

    rows = client.execute(
        """
        SELECT id, LENGTH(COALESCE(resumo, '')), substr(titulo, 1, 80)
        FROM news
        WHERE LENGTH(COALESCE(resumo, '')) < ?
        ORDER BY id
        """,
        [args.min_resumo],
    ).rows

    to_delete = [int(r[0]) for r in rows if int(r[0]) not in guide_ids]
    skipped_guides = [int(r[0]) for r in rows if int(r[0]) in guide_ids]

    print(f"Thin (resumo < {args.min_resumo}): {len(rows)}")
    print(f"  deletar: {len(to_delete)} | proteger guias: {skipped_guides}")
    for r in rows[:15]:
        flag = "KEEP-GUIDE" if int(r[0]) in guide_ids else "DELETE"
        print(f"  [{flag}] id={r[0]} len={r[1]} | {r[2]}")
    if len(rows) > 15:
        print(f"  ... +{len(rows) - 15} outras")

    if not args.apply:
        print("\nDry-run. Rode com --apply para apagar.")
        return 0

    if not to_delete:
        print("Nada a apagar.")
        return 0

    print(f"Executando DELETE WHERE LENGTH(resumo) < {args.min_resumo}...")
    if guide_ids:
        placeholders = ",".join("?" * len(guide_ids))
        client.execute(
            f"""
            DELETE FROM news
            WHERE LENGTH(COALESCE(resumo, '')) < ?
              AND id NOT IN ({placeholders})
            """,
            [args.min_resumo, *sorted(guide_ids)],
        )
    else:
        client.execute(
            "DELETE FROM news WHERE LENGTH(COALESCE(resumo, '')) < ?",
            [args.min_resumo],
        )

    try:
        print("Rebuild FTS (pode demorar no Turso)...")
        sync_news_fts(client)
        print("FTS ok.")
    except Exception as exc:
        print(f"Aviso FTS rebuild: {exc}")

    left = client.execute(
        "SELECT COUNT(*) FROM news WHERE LENGTH(COALESCE(resumo, '')) < ?",
        [args.min_resumo],
    ).rows[0][0]
    total = client.execute("SELECT COUNT(*) FROM news").rows[0][0]
    print(f"OK: purge concluído. Total news={total}. Thin restantes (<{args.min_resumo}): {left}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
