"""Purge legacy enrichment news via direct DELETE (Turso-friendly)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from db import get_db, sync_news_fts  # noqa: E402

LEGACY_WHERE = """
(link IS NULL OR link NOT LIKE 'internal://artigo/%')
AND (
  dados_mercado IS NULL OR dados_mercado = ''
  OR dados_mercado NOT LIKE '%lentes_analiticas%'
)
"""


def main() -> int:
    apply = "--apply" in sys.argv
    client = get_db()

    print("counting...", flush=True)
    total = int(client.execute("SELECT COUNT(*) FROM news").rows[0][0])
    legacy = int(client.execute(f"SELECT COUNT(*) FROM news WHERE {LEGACY_WHERE}").rows[0][0])
    modern = int(
        client.execute(
            """
            SELECT COUNT(*) FROM news
            WHERE dados_mercado IS NOT NULL AND dados_mercado != ''
              AND dados_mercado LIKE '%lentes_analiticas%'
            """
        ).rows[0][0]
    )
    print(f"total={total} modern={modern} legacy={legacy}", flush=True)

    if not apply:
        print("Dry-run. Use --apply to delete.", flush=True)
        return 0

    if legacy <= 0:
        print("Nothing to delete.", flush=True)
        return 0

    print("deleting comments for legacy news...", flush=True)
    try:
        client.execute(
            f"""
            DELETE FROM comments
            WHERE news_id IN (SELECT id FROM news WHERE {LEGACY_WHERE})
            """
        )
        print("comments deleted", flush=True)
    except Exception as exc:
        print(f"comments skip: {exc}", flush=True)

    # Delete in ID ranges to avoid one huge Turso statement.
    bounds = client.execute("SELECT MIN(id), MAX(id) FROM news").rows[0]
    lo, hi = int(bounds[0]), int(bounds[1])
    step = 500
    deleted_est = 0
    print(f"deleting news id range {lo}..{hi} step={step}", flush=True)
    for start in range(lo, hi + 1, step):
        end = start + step - 1
        before = int(
            client.execute(
                f"SELECT COUNT(*) FROM news WHERE id BETWEEN ? AND ? AND {LEGACY_WHERE}",
                [start, end],
            ).rows[0][0]
        )
        if before == 0:
            continue
        t0 = time.time()
        client.execute(
            f"""
            DELETE FROM news
            WHERE id BETWEEN ? AND ?
              AND {LEGACY_WHERE}
            """,
            [start, end],
        )
        deleted_est += before
        print(
            f"  range {start}-{end}: ~{before} in {time.time() - t0:.1f}s (accum~{deleted_est})",
            flush=True,
        )

    print("rebuilding FTS...", flush=True)
    try:
        sync_news_fts(client)
        print("FTS ok", flush=True)
    except Exception as exc:
        print(f"FTS warning: {exc}", flush=True)

    total2 = int(client.execute("SELECT COUNT(*) FROM news").rows[0][0])
    legacy2 = int(client.execute(f"SELECT COUNT(*) FROM news WHERE {LEGACY_WHERE}").rows[0][0])
    print(f"DONE total={total2} legacy_left={legacy2} removed~={total - total2}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
