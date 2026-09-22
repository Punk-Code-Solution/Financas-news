"""Gera capas Pexels so para noticias com conteudo (resumo nao vazio / nao thin).

Uso:
  PYTHONPATH=. python tools/fill_covers_nonempty.py
  PYTHONPATH=. python tools/fill_covers_nonempty.py --min-chars 1
  PYTHONPATH=. python tools/fill_covers_nonempty.py --batch 40 --max-batches 100
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

_ = load_dotenv(ROOT / ".env")
os.environ.setdefault("IMAGE_PROVIDER", "pexels")
os.environ.setdefault("PEXELS_USE_REMOTE_URL", "1")

import core  # noqa: E402
from db import DbClient, get_db, reset_db_client, _is_transient_db_error  # noqa: E402


def count_missing(client: DbClient, min_chars: int) -> int:
    raw = client.execute(
        """
        SELECT COUNT(*) FROM news
        WHERE (imagem_url IS NULL OR TRIM(COALESCE(imagem_url, '')) = '')
          AND LENGTH(COALESCE(resumo, '')) >= ?
        """,
        [min_chars],
    ).rows[0][0]
    return int(raw)


def fetch_pending(client: DbClient, limit: int, min_chars: int) -> list:
    return list(
        client.execute(
            """
            SELECT id, titulo, tag, link, resumo, imagem_url
            FROM news
            WHERE (imagem_url IS NULL OR TRIM(COALESCE(imagem_url, '')) = '')
              AND LENGTH(COALESCE(resumo, '')) >= ?
            ORDER BY id DESC
            LIMIT ?
            """,
            [min_chars, limit],
        ).rows
    )


def _with_db_retry(fn, *, label: str, attempts: int = 3):
    delay = 2.0
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if not _is_transient_db_error(exc) or attempt >= attempts:
                raise
            print(
                f"[{label}] Turso timeout ({type(exc).__name__}) — "
                + f"reconecta {attempt}/{attempts} em {delay:.0f}s…",
                flush=True,
            )
            reset_db_client()
            time.sleep(delay)
            delay *= 2
    assert last_exc is not None
    raise last_exc


def backfill_nonempty(limit: int, min_chars: int) -> dict:
    """Igual a core.backfill_missing_images, mas filtra resumo >= min_chars."""
    core._reset_image_quota_state()
    client_db = get_db()
    rows = fetch_pending(client_db, limit, min_chars)
    updated: list[dict] = []
    failed: list[dict] = []

    if not rows:
        print("   [img] Nenhuma noticia com conteudo sem capa.", flush=True)
        client_db.close()
        return {
            "processed": 0,
            "updated": 0,
            "failed": 0,
            "items": [],
            "errors": [],
        }

    print(
        f"   [img] Backfill nao-vazio: ate {len(rows)} capa(s) "
        + f"(min_chars={min_chars}, id DESC).",
        flush=True,
    )

    def _process_row(row):
        article_id = int(row[0])
        titulo, tag, link, resumo = row[1], row[2], row[3] or "", row[4] or ""
        print(f"   [img] Capa pendente #{article_id}: {(titulo or '')[:60]}...", flush=True)
        url = core.generate_article_image(
            titulo,
            tag,
            link,
            resumo,
            article_id=article_id,
            use_openai=True,
        )
        return article_id, titulo or "", url

    parallel = (
        core._pexels_use_remote_url()
        and core.get_image_providers() == ["pexels"]
        and len(rows) >= 8
    )
    workers = min(8, len(rows)) if parallel else 1
    results: list[tuple[int, str, str | None]] = []

    if workers == 1:
        for row in rows:
            results.append(_process_row(row))
    else:
        print(f"   [img] Modo paralelo: {workers} workers", flush=True)
        api_key = core.get_pexels_api_key()
        if api_key:
            core._configure_ssl_certs()
            verify = core._ssl_verify_enabled()
            if not verify:
                import urllib3
                from urllib3.exceptions import InsecureRequestWarning

                urllib3.disable_warnings(InsecureRequestWarning)
            _ = core._ensure_used_pexels_ids()
            warmed: set[str] = set()
            for row in rows:
                q = core._stock_search_query(row[1] or "", row[2] or "", row[4] or "")
                if q in warmed:
                    continue
                warmed.add(q)
                _ = core._pexels_refill_pool(api_key, q, verify, 1)

        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_process_row, row) for row in rows]
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as exc:
                    print(f"   [img] Worker falhou: {exc}", flush=True)

    for article_id, titulo, imagem_url in results:
        if core.pexels_rate_limited() and not imagem_url:
            failed.append({"id": article_id, "titulo": "rate_limit_429"})
            continue
        if imagem_url and core._cover_url_ready(imagem_url):
            _ = client_db.execute(
                "UPDATE news SET imagem_url = ? WHERE id = ?",
                [imagem_url, article_id],
            )
            updated.append({"id": article_id, "imagem_url": imagem_url})
        else:
            failed.append({"id": article_id, "titulo": (titulo or "")[:80]})

    client_db.close()
    return {
        "processed": len(updated) + len(failed),
        "updated": len(updated),
        "failed": len(failed),
        "items": updated,
        "errors": failed,
        "rate_limited": core.pexels_rate_limited(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera capas para noticias com conteudo.")
    parser.add_argument(
        "--min-chars",
        type=int,
        default=core.MIN_ARTICLE_CHARS,
        help=f"Minimo de chars no resumo (default={core.MIN_ARTICLE_CHARS})",
    )
    parser.add_argument("--batch", type=int, default=40)
    parser.add_argument("--hot", type=int, default=12)
    parser.add_argument("--max-batches", type=int, default=200)
    args = parser.parse_args()

    if not core.get_pexels_api_key():
        print("PEXELS_API_KEY ausente")
        return 1

    min_chars = max(0, args.min_chars)
    missing = _with_db_retry(lambda: count_missing(get_db(), min_chars), label="count")
    print(
        f"sem_capa_nao_vazio={missing} min_chars={min_chars} "
        + f"remote={core._pexels_use_remote_url()} providers={core.get_image_providers()}",
        flush=True,
    )
    if missing <= 0:
        print("Nada a fazer.")
        return 0

    print("\n=== SMOKE ===", flush=True)
    core.clear_pexels_rate_limit()
    core.clear_used_pexels_cache()
    core.clear_pexels_pool()
    smoke = _with_db_retry(
        lambda: backfill_nonempty(limit=min(4, missing), min_chars=min_chars),
        label="smoke",
    )
    print(smoke, flush=True)
    if not smoke.get("updated"):
        print("Smoke falhou — tentando 1 capa sequencial...", flush=True)
        core.clear_pexels_pool()
        smoke = _with_db_retry(
            lambda: backfill_nonempty(limit=1, min_chars=min_chars),
            label="smoke1",
        )
        print(smoke, flush=True)
        if not smoke.get("updated"):
            print("Smoke falhou — abort.")
            return 2

    hot = max(1, args.hot)
    batch = max(1, args.batch)
    done = int(smoke.get("updated") or 0)
    fail_streak = 0
    missing = _with_db_retry(lambda: count_missing(get_db(), min_chars), label="count")

    def run_pass(n: int, label: str) -> dict:
        nonlocal done
        t0 = time.time()
        result = _with_db_retry(
            lambda: backfill_nonempty(limit=n, min_chars=min_chars),
            label=label,
            attempts=4,
        )
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

    for i in range(args.max_batches):
        if missing <= 0:
            break

        if core.pexels_rate_limited():
            print("429 — pausa 55 min", flush=True)
            time.sleep(55 * 60)
            core.clear_pexels_rate_limit()

        print(f"\n=== ciclo {i + 1} (restam ~{missing}) ===", flush=True)
        try:
            hot_result = run_pass(hot, "hot/novas")
            if hot_result.get("rate_limited"):
                print("429 — pausa 55 min", flush=True)
                time.sleep(55 * 60)
                core.clear_pexels_rate_limit()
                fail_streak = 0
                missing = _with_db_retry(
                    lambda: count_missing(get_db(), min_chars), label="count"
                )
                continue

            result = run_pass(batch, "bulk/backlog")
            upd = int(hot_result.get("updated") or 0) + int(result.get("updated") or 0)
            missing = max(0, missing - upd)

            if result.get("rate_limited"):
                print("429 — pausa 55 min", flush=True)
                time.sleep(55 * 60)
                core.clear_pexels_rate_limit()
                fail_streak = 0
                missing = _with_db_retry(
                    lambda: count_missing(get_db(), min_chars), label="count"
                )
                continue

            if upd == 0:
                fail_streak += 1
                missing = _with_db_retry(
                    lambda: count_missing(get_db(), min_chars), label="count"
                )
                if fail_streak >= 5:
                    print("5 ciclos sem progresso — fim.")
                    break
                time.sleep(5)
            else:
                fail_streak = 0
                time.sleep(0.5)
                if (i + 1) % 5 == 0:
                    missing = _with_db_retry(
                        lambda: count_missing(get_db(), min_chars), label="count"
                    )
        except Exception as exc:
            if not _is_transient_db_error(exc):
                raise
            fail_streak += 1
            print(f"ciclo abortado por Turso: {exc} — pausa 30s", flush=True)
            reset_db_client()
            time.sleep(30)
            if fail_streak >= 8:
                print("Turso indisponível demais — encerrando.")
                break

    missing = _with_db_retry(lambda: count_missing(get_db(), min_chars), label="count")
    print(f"\nFIM acumulado={done} restam_sem_capa_nao_vazio={missing}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
