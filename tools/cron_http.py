"""Dispara um job autenticado do portal (uso em cron one-shot / Railway).

Uso:
  SITE_ORIGIN=https://www.financas-news.net.br ROBO_TOKEN=... python tools/cron_http.py rodar-robo

Jobs: ver JOBS abaixo. Nunca passe o token na URL.
"""
from __future__ import annotations

import os
import sys

import requests

JOBS: dict[str, tuple[str, str]] = {
    "rodar-robo": ("GET", "/api/rodar-robo"),
    "gerar-imagens": ("GET", "/api/gerar-imagens?limit=5"),
    "atualizar-artigos": ("GET", "/api/atualizar-artigos?limit=20"),
    "macro-watch": ("GET", "/api/macro-watch"),
    "traduzir-pendentes": ("GET", "/api/traduzir-pendentes?limit=10"),
    "newsletter-digest-diario": ("GET", "/api/newsletter-digest-diario"),
    "newsletter-digest": ("GET", "/api/newsletter-digest"),
    "radar-semanal": ("GET", "/api/radar-semanal"),
    "sync-news-fts": ("GET", "/api/sync-news-fts"),
    "columnists-credit-daily": ("POST", "/api/columnists/credit-daily"),
    "columnists-expire-boosts": ("POST", "/api/columnists/expire-boosts"),
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in JOBS:
        names = ", ".join(sorted(JOBS))
        print(f"Uso: python tools/cron_http.py <job>\nJobs: {names}", file=sys.stderr)
        return 2

    token = (os.getenv("ROBO_TOKEN") or os.getenv("ROBOT_TOKEN") or "").strip()
    origin = (os.getenv("SITE_ORIGIN") or "https://www.financas-news.net.br").rstrip("/")
    if not token:
        print("ROBO_TOKEN nao configurado", file=sys.stderr)
        return 1

    method, path = JOBS[sys.argv[1]]
    url = f"{origin}{path}"
    timeout = int(os.getenv("CRON_HTTP_TIMEOUT", "900"))
    headers = {"Authorization": f"Bearer {token}"}

    print(f"cron_http: {method} {path}")
    resp = requests.request(method, url, headers=headers, timeout=timeout)
    print(f"status={resp.status_code} body={resp.text[:800]}")
    if resp.status_code not in (200, 202):
        resp.raise_for_status()
        print(f"status inesperado={resp.status_code}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
