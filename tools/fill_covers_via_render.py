"""Preenche capas faltantes via API do Render (arquivos no disco de producao)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

SITE = (os.getenv("SITE_ORIGIN") or "https://financas-news.net.br").rstrip("/")
TOKEN = (os.getenv("ROBO_TOKEN") or os.getenv("ROBOT_TOKEN") or "").strip()


def call_fill(limit: int = 10) -> dict:
    url = f"{SITE}/api/gerar-imagens"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    # SSL_VERIFY=false no Windows/MITM local
    verify = str(os.getenv("SSL_VERIFY", "true")).strip().lower() not in ("0", "false", "no")
    resp = requests.get(
        url,
        headers=headers,
        params={"limit": limit},
        timeout=300,
        verify=verify,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def main() -> int:
    if not TOKEN:
        print("ROBO_TOKEN ausente no .env")
        return 1

    limit = int(os.getenv("FILL_LIMIT", "10"))
    max_batches = int(os.getenv("FILL_MAX_BATCHES", "600"))
    pause = float(os.getenv("FILL_PAUSE_SEC", "20"))

    print(f"site={SITE} limit={limit} max_batches={max_batches} pause={pause}s")
    print("=== SMOKE ===", flush=True)
    smoke = call_fill(1)
    print(smoke, flush=True)
    if not smoke.get("updated"):
        print("Smoke sem update — confira PEXELS_API_KEY no Render / rate limit.")
        # continua mesmo assim se ainda houver pendentes

    done = int(smoke.get("updated") or 0)
    fail_streak = 0

    for i in range(max_batches):
        print(f"\n=== lote {i + 1} ===", flush=True)
        try:
            result = call_fill(limit)
        except Exception as exc:
            print(f"erro: {exc}", flush=True)
            fail_streak += 1
            if fail_streak >= 5:
                print("5 falhas seguidas — parando.")
                break
            time.sleep(60)
            continue

        upd = int(result.get("updated") or 0)
        fail = int(result.get("failed") or 0)
        done += upd
        print(
            f"updated={upd} failed={fail} rate_limited={result.get('rate_limited')} "
            f"acumulado={done} raw={result}",
            flush=True,
        )

        if result.get("rate_limited"):
            print("rate limit — pausa 55 min", flush=True)
            time.sleep(55 * 60)
            fail_streak = 0
            continue

        if upd == 0:
            fail_streak += 1
            if fail_streak >= 5:
                print("5 lotes sem progresso — fim (acabou ou bloqueio).")
                break
            time.sleep(30)
        else:
            fail_streak = 0
            time.sleep(pause)

    print(f"\n=== FIM === acumulado={done}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
