"""Encolhe o índice AdSense/SEO: seo_noindex no bulk RSS/IA; mantém vitrine curada.

Protege guias evergreen (/artigo/*), institucionais (não estão em news) e as N
análises mais recentes/densas. Uso:

  PYTHONPATH=. python tools/curate_adsense_index.py --dry-run
  PYTHONPATH=. python tools/curate_adsense_index.py --apply --keep 60
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

_ = load_dotenv(ROOT / ".env")

from core import MIN_ARTICLE_CHARS  # noqa: E402
from db import get_db  # noqa: E402
from educational_guides import EDUCATIONAL_GUIDES, find_guide_noticia_id  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Marca seo_noindex=1 no bulk de notícias IA/RSS, mantendo guias e "
            "uma vitrine curada (~30–80) indexável."
        )
    )
    parser.add_argument("--apply", action="store_true", help="Persiste seo_noindex (senão dry-run)")
    parser.add_argument(
        "--keep",
        type=int,
        default=60,
        help="Quantas análises densas recentes manter indexáveis (default 60)",
    )
    parser.add_argument(
        "--min-resumo",
        type=int,
        default=MIN_ARTICLE_CHARS,
        help="Só entra na vitrine se LENGTH(resumo) >= este limiar",
    )
    args = parser.parse_args()
    keep = max(10, min(int(args.keep), 200))

    client = get_db()
    guide_ids: set[int] = set()
    for guide in EDUCATIONAL_GUIDES:
        nid = find_guide_noticia_id(client, guide["slug"])
        if nid:
            guide_ids.add(int(nid))

    # Vitrine: publicadas (ou legado), densas, sem noindex prévio forçado na seleção.
    showcase = client.execute(
        """
        SELECT id FROM news
        WHERE LENGTH(COALESCE(resumo, '')) >= ?
          AND (moderation_status IS NULL OR moderation_status = '' OR moderation_status = 'published')
          AND COALESCE(content_origin, 'editorial') != 'columnist'
        ORDER BY
          CASE WHEN COALESCE(home_priority, 0) >= 40 THEN 0 ELSE 1 END,
          id DESC
        LIMIT ?
        """,
        [args.min_resumo, keep],
    ).rows
    keep_ids = {int(r[0]) for r in (showcase or [])} | guide_ids

    total = int(client.execute("SELECT COUNT(*) FROM news").rows[0][0])
    already = int(
        client.execute(
            "SELECT COUNT(*) FROM news WHERE COALESCE(seo_noindex, 0) = 1"
        ).rows[0][0]
    )

    # Candidatos a noindex: tudo que não está na vitrine/guias.
    if keep_ids:
        placeholders = ",".join("?" * len(keep_ids))
        candidates = client.execute(
            f"""
            SELECT id FROM news
            WHERE id NOT IN ({placeholders})
              AND COALESCE(seo_noindex, 0) = 0
              AND COALESCE(content_origin, 'editorial') != 'columnist'
            """,
            sorted(keep_ids),
        ).rows
    else:
        candidates = client.execute(
            """
            SELECT id FROM news
            WHERE COALESCE(seo_noindex, 0) = 0
              AND COALESCE(content_origin, 'editorial') != 'columnist'
            """
        ).rows

    to_flag = [int(r[0]) for r in (candidates or [])]

    print(f"Total news: {total}")
    print(f"Já seo_noindex=1: {already}")
    print(f"Vitrine+guias protegidos: {len(keep_ids)} (keep={keep}, guias={len(guide_ids)})")
    print(f"Marcar noindex: {len(to_flag)}")
    for nid in sorted(keep_ids)[:12]:
        print(f"  [KEEP] id={nid}")
    if len(keep_ids) > 12:
        print(f"  ... +{len(keep_ids) - 12} keep")
    for nid in to_flag[:10]:
        print(f"  [NOINDEX] id={nid}")
    if len(to_flag) > 10:
        print(f"  ... +{len(to_flag) - 10} noindex")

    if not args.apply:
        print("\nDry-run. Rode com --apply para gravar seo_noindex=1.")
        return 0

    if not to_flag:
        print("Nada a marcar.")
        return 0

    # Batch UPDATE
    batch = 200
    for i in range(0, len(to_flag), batch):
        chunk = to_flag[i : i + batch]
        ph = ",".join("?" * len(chunk))
        client.execute(
            f"UPDATE news SET seo_noindex = 1 WHERE id IN ({ph})",
            chunk,
        )
        print(f"  batch {i // batch + 1}: {len(chunk)} ids")

    # Garante vitrine/guias indexáveis
    if keep_ids:
        ph = ",".join("?" * len(keep_ids))
        client.execute(
            f"UPDATE news SET seo_noindex = 0 WHERE id IN ({ph})",
            sorted(keep_ids),
        )

    left_indexable = client.execute(
        """
        SELECT COUNT(*) FROM news
        WHERE COALESCE(seo_noindex, 0) = 0
          AND (moderation_status IS NULL OR moderation_status = '' OR moderation_status = 'published')
        """
    ).rows[0][0]
    print(f"OK: indexáveis restantes (publicado + seo_noindex=0) = {left_indexable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
