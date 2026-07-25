"""Preenche capas via Pexels (local) em lotes contra o Turso.

Respeita o tier free (~200 req/h ≈ ~90 capas/h: 1 search + 1 download).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

_ = load_dotenv(ROOT / ".env")
os.environ["IMAGE_PROVIDER"] = "pexels"  # só stock nesta corrida

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
    total = int(client.execute("SELECT COUNT(*) FROM news").rows[0][0])
    missing = count_missing(client)
    print(f"total={total} sem_capa={missing}")
    print(f"providers={core.get_image_providers()}")
    print(f"images_dir={core.get_article_images_dir()}")

    print("\n=== SMOKE 1 capa ===")
    core.clear_pexels_rate_limit()
    smoke = core.backfill_missing_images(limit=1)
    print(smoke)
    if not smoke.get("updated"):
        print("Smoke sem update — abort.")
        return 2

    missing = count_missing(client)
    print(f"restam={missing}")

    batch = 10
    max_batches = 800
    done = int(smoke.get("updated") or 0)
    failed_streak = 0

    for i in range(max_batches):
        missing = count_missing(client)
        if missing <= 0:
            break

        if core.pexels_rate_limited():
            print("rate limit ativo — pausa 55 min", flush=True)
            time.sleep(55 * 60)
            core.clear_pexels_rate_limit()

        n = min(batch, missing)
        print(f"\n=== lote {i + 1}: {n} (restam {missing}) ===", flush=True)
        t0 = time.time()
        result = core.backfill_missing_images(limit=n)
        elapsed = time.time() - t0
        upd = int(result.get("updated") or 0)
        fail = int(result.get("failed") or 0)
        done += upd
        print(
            f"updated={upd} failed={fail} repaired={result.get('repaired_broken', 0)} "
            f"rate_limited={result.get('rate_limited')} "
            f"em {elapsed:.1f}s | acumulado={done}",
            flush=True,
        )

        if result.get("rate_limited"):
            print("429 detectado — pausa 55 min antes de continuar", flush=True)
            time.sleep(55 * 60)
            core.clear_pexels_rate_limit()
            failed_streak = 0
            continue

        if upd == 0:
            failed_streak += 1
            if failed_streak >= 5:
                print("5 lotes sem progresso — parando.")
                break
            time.sleep(30)
        else:
            failed_streak = 0
            # ~10 capas ≈ 20 req; ritmo agressivo até 429 (aí pausa 55 min)
            time.sleep(25)

    print(f"\n=== FIM local === novas={done} sem_capa={count_missing(client)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
