"""Copia o banco Turso para um arquivo SQLite (volume Railway / backup local).

Uso:
  PYTHONPATH=. python tools/migrate_turso_to_sqlite.py --out dumps/news.db
  PYTHONPATH=. python tools/migrate_turso_to_sqlite.py --out dumps/news.db --force

Nao imprime tokens, dumps nem PII. *.db esta no .gitignore.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

_ = load_dotenv(ROOT / ".env")

from db import (  # noqa: E402
    TursoQuotaError,
    import_turso_into_sqlite,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrar Turso → SQLite (dump / copia de tabelas)."
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "dumps" / "news.db"),
        help="Caminho do SQLite de destino (default: dumps/news.db)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Sobrescreve o destino mesmo se ja tiver noticias",
    )
    args = parser.parse_args()
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = import_turso_into_sqlite(str(dest), force=bool(args.force))
    except TursoQuotaError:
        print(
            "ERRO: Turso recusou o dump (cota/plano BLOCKED). "
            "Libere a cota no painel Turso e rode de novo.",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(f"ERRO: {type(exc).__name__}", file=sys.stderr)
        return 1
    counts = result.get("counts") or {}
    news = counts.get("news", 0)
    print(
        f"ok skipped={result.get('skipped')} method={result.get('method')} "
        f"news={news} tables={len(counts)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
