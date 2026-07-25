"""Preenche capas faltantes com URL remota do Pexels (aparecem no Render sem upload)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
os.environ["IMAGE_PROVIDER"] = "pexels"
os.environ["PEXELS_USE_REMOTE_URL"] = "1"

import core
from db import get_db


def count_missing(client) -> int:
    return int(
        client.execute(
            """
            SELECT COUNT(*) FROM news
            WHERE imagem_url IS NULL OR TRIM(COALESCE(imagem_url, '')) = ''
            """
        ).rows[0][0]
    )


def main() -> int:
    if not core.get_pexels_api_key():
        print("PEXELS_API_KEY ausente")
        return 1

    client = get_db()
    missing = count_missing(client)
    print(f"sem_capa={missing} remote={core._pexels_use_remote_url()} providers={core.get_image_providers()}")

    print("\n=== SMOKE ===", flush=True)
    core.clear_pexels_rate_limit()
    smoke = core.backfill_missing_images(limit=2)
    print(smoke, flush=True)
    if not smoke.get("updated"):
        print("Smoke falhou — abort.")
        return 2

    batch = 15
    max_batches = 400
    done = int(smoke.get("updated") or 0)
    fail_streak = 0

    for i in range(max_batches):
        missing = count_missing(client)
        if missing <= 0:
            break

        if core.pexels_rate_limited():
            print("429 — pausa 55 min", flush=True)
            time.sleep(55 * 60)
            core.clear_pexels_rate_limit()

        n = min(batch, missing)
        print(f"\n=== lote {i + 1}: {n} (restam {missing}) ===", flush=True)
        result = core.backfill_missing_images(limit=n)
        upd = int(result.get("updated") or 0)
        done += upd
        print(
            f"updated={upd} failed={result.get('failed')} "
            f"rate_limited={result.get('rate_limited')} acumulado={done}",
            flush=True,
        )

        if result.get("rate_limited"):
            print("429 — pausa 55 min", flush=True)
            time.sleep(55 * 60)
            core.clear_pexels_rate_limit()
            fail_streak = 0
            continue

        if upd == 0:
            fail_streak += 1
            if fail_streak >= 5:
                print("5 lotes sem progresso — fim.")
                break
            time.sleep(20)
        else:
            fail_streak = 0
            # ~15 req API; ritmo ate ~180/h
            time.sleep(12)

    print(f"\n=== FIM === novas={done} sem_capa={count_missing(client)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
