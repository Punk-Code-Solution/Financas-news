"""Preenche capas faltantes com URL remota do Pexels (aparecem no Render sem upload).

Otimizado: pool de 80 fotos/query, workers paralelos, lotes grandes, pouca pausa.
"""
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
    core.clear_used_pexels_cache()
    core.clear_pexels_pool()
    smoke = core.backfill_missing_images(limit=4)
    print(smoke, flush=True)
    if not smoke.get("updated"):
        print("Smoke falhou — tentando 1 capa sequencial...", flush=True)
        core.clear_pexels_pool()
        smoke = core.backfill_missing_images(limit=1)
        print(smoke, flush=True)
        if not smoke.get("updated"):
            print("Smoke falhou — abort.")
            return 2

    # HOT = janela das mais novas coberta antes do backlog a cada ciclo, garantindo
    # que artigos recem-publicados furem a fila. BULK = varre o backlog antigo.
    hot = 12
    batch = 40
    max_batches = 200
    done = int(smoke.get("updated") or 0)
    fail_streak = 0
    missing = count_missing(client)

    def run_pass(n: int, label: str) -> dict:
        nonlocal done
        t0 = time.time()
        result = core.backfill_missing_images(limit=n)
        elapsed = time.time() - t0
        upd = int(result.get("updated") or 0)
        done += upd
        rate = (upd / elapsed) if elapsed else 0.0
        print(
            f"[{label}] updated={upd} failed={result.get('failed')} "
            + f"rate_limited={result.get('rate_limited')} "
            + f"em {elapsed:.1f}s ({rate:.1f}/s) "
            + f"acumulado={done}",
            flush=True,
        )
        return result

    for i in range(max_batches):
        if missing <= 0:
            break

        if core.pexels_rate_limited():
            print("429 — pausa 55 min", flush=True)
            time.sleep(55 * 60)
            core.clear_pexels_rate_limit()

        print(f"\n=== ciclo {i + 1} (restam ~{missing}) ===", flush=True)

        # 1) Passe quente: sempre as mais novas primeiro (id DESC no backfill).
        hot_result = run_pass(hot, "hot/novas")
        if hot_result.get("rate_limited"):
            print("429 — pausa 55 min", flush=True)
            time.sleep(55 * 60)
            core.clear_pexels_rate_limit()
            fail_streak = 0
            missing = count_missing(client)
            continue

        # 2) Passe backlog: varre as antigas (as mais novas ja sairam no passe quente).
        result = run_pass(batch, "bulk/backlog")
        upd = int(hot_result.get("updated") or 0) + int(result.get("updated") or 0)
        missing = max(0, missing - upd)

        if result.get("rate_limited"):
            print("429 — pausa 55 min", flush=True)
            time.sleep(55 * 60)
            core.clear_pexels_rate_limit()
            fail_streak = 0
            missing = count_missing(client)
            continue

        if upd == 0:
            fail_streak += 1
            missing = count_missing(client)
            if fail_streak >= 5:
                print("5 ciclos sem progresso — fim.")
                break
            time.sleep(5)
        else:
            fail_streak = 0
            # Pool reduz req/capa; pausa curta so para nao martelar o Turso.
            time.sleep(0.5)
            if (i + 1) % 5 == 0:
                missing = count_missing(client)

    print(f"\n=== FIM === novas={done} sem_capa={count_missing(client)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
