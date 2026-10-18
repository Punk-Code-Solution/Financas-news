"""Checklist amostral estilo adsense-site-auditor / adsense-checklist.

Sorteia 20–50 URLs indexáveis e reporta thin, near-duplicate, densidade de ads
(revisão) e presença de páginas institucionais. Não substitui curadoria humana.

  PYTHONPATH=. python tools/adsense_qa_sample.py
  PYTHONPATH=. python tools/adsense_qa_sample.py --sample 40
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

_ = load_dotenv(ROOT / ".env")

from columnists import FEED_VISIBLE_SQL  # noqa: E402
from core import MIN_ARTICLE_CHARS, MIN_ARTICLE_WORDS, count_words  # noqa: E402
from db import get_db  # noqa: E402
from monetization import adsense_review_mode  # noqa: E402


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _shingle_fingerprint(text: str, n: int = 8) -> set[str]:
    tokens = [t.casefold() for t in _TOKEN_RE.findall(text or "") if len(t) > 2]
    if len(tokens) < n:
        return set()
    out: set[str] = set()
    for i in range(len(tokens) - n + 1):
        out.add(" ".join(tokens[i : i + n]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="QA amostral AdSense (thin / duplicata / ads).")
    parser.add_argument("--sample", type=int, default=30, help="Tamanho da amostra (20–50)")
    args = parser.parse_args()
    sample_n = max(20, min(int(args.sample), 50))

    client = get_db()
    institutional = [
        ("/", "home"),
        ("/quem-somos", "about"),
        ("/metodologia", "methodology"),
        ("/contato", "contact"),
        ("/privacidade", "privacy"),
        ("/mercado", "market"),
    ]
    print("=== Páginas institucionais (checklist manual no browser) ===")
    for path, label in institutional:
        print(f"  [ ] {label}: https://financas-news.net.br{path}")

    review = adsense_review_mode()
    print(f"\n=== Densidade de ads ===")
    print(f"  ADSENSE_REVIEW_MODE ativo: {review} (esperado: True até aprovação)")
    print("  Em revisão: no máx. 1 display + Auto ads; sem fluid/sidebar/autorelaxed.")

    rows = client.execute(
        f"""
        SELECT id, titulo, resumo, tag, fonte, link,
               LENGTH(COALESCE(resumo, '')) AS chars
        FROM news
        WHERE {FEED_VISIBLE_SQL}
          AND LENGTH(COALESCE(resumo, '')) >= ?
        ORDER BY id DESC
        LIMIT ?
        """,
        [MIN_ARTICLE_CHARS // 2, sample_n * 3],
    ).rows or []

    # Amostra estável: hash do id
    ranked = sorted(rows, key=lambda r: hashlib.md5(str(r[0]).encode()).hexdigest())
    sample = ranked[:sample_n]

    thin = 0
    short_titles = 0
    near_dup_pairs: list[tuple[int, int, float]] = []
    fps: list[tuple[int, set[str]]] = []

    print(f"\n=== Amostra de {len(sample)} URLs indexáveis ===")
    for r in sample:
        nid, titulo, resumo, tag, fonte, link, chars = (
            int(r[0]),
            str(r[1] or ""),
            str(r[2] or ""),
            str(r[3] or ""),
            str(r[4] or ""),
            str(r[5] or ""),
            int(r[6] or 0),
        )
        words = count_words(resumo)
        is_thin = words < MIN_ARTICLE_WORDS and chars < MIN_ARTICLE_CHARS
        if is_thin:
            thin += 1
        if len(titulo) < 25:
            short_titles += 1
        flag = "THIN" if is_thin else "ok"
        print(f"  [{flag}] /noticia/{nid} words={words} chars={chars} tag={tag} | {titulo[:70]}")
        fps.append((nid, _shingle_fingerprint(resumo)))

    # Near-duplicate: Jaccard dos 8-grams
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            a, b = fps[i][1], fps[j][1]
            if not a or not b:
                continue
            inter = len(a & b)
            union = len(a | b) or 1
            jacc = inter / union
            if jacc >= 0.35:
                near_dup_pairs.append((fps[i][0], fps[j][0], jacc))

    near_dup_pairs.sort(key=lambda x: -x[2])
    print(f"\n=== Resumo ===")
    print(f"  Thin na amostra: {thin}/{len(sample)}")
    print(f"  Títulos curtos (<25): {short_titles}")
    print(f"  Pares near-duplicate (Jaccard≥0.35): {len(near_dup_pairs)}")
    for a, b, j in near_dup_pairs[:8]:
        print(f"    ~dup {a} ↔ {b} jaccard={j:.2f}")

    # Overlap com link RSS quando houver texto curto na fonte gravada — só heurística título
    print("\n=== Próximos passos operacionais ===")
    print("  1. Corrigir thin/near-dup na fila /admin/editorial (rejeitar ou reescrever).")
    print("  2. Confirmar no GSC cobertura estável 2–4 semanas com índice enxuto.")
    print("  3. Só então reaplicar AdSense (texto em DOCUMENTACAO.md §11b).")
    print("  4. Não reaplicar só com SEO/OG/sitemap sem curadoria humana.")
    return 0 if thin == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
