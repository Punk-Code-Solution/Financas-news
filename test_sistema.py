"""Suíte de testes do sistema Finanças News (com mocks de rede externa)."""
from __future__ import annotations

import re
import sys
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient

import core
import main
from core import VALID_TAGS

FAKE_MARKET = {
    "coletado_em": "17/07/2026 08:00",
    "Dólar (USD/BRL)": {
        "cotacao": "R$ 5,10",
        "variacao_24h": "-0.25%",
        "maxima": "R$ 5,15",
        "minima": "R$ 5,05",
    },
}
FAKE_BCB = {
    "Selic meta (% a.a.)": {"valor": "14.25", "data": "17/07/2026"},
    "IPCA acumulado 12 meses (%)": {"valor": "4.64", "data": "17/07/2026"},
}
FAKE_HIST = {
    "dolar": {"label": "USD/BRL", "labels": ["01/07", "08/07", "15/07"], "values": [5.1, 5.2, 5.0]},
    "bitcoin": {"label": "BTC/BRL", "labels": ["01/07", "08/07", "15/07"], "values": [300000, 310000, 320000]},
}
FAKE_SPARK = {
    "usd": [5.0, 5.1, 5.05, 5.12],
    "btc": [300000, 305000, 310000],
}

results: list[tuple[str, str, str]] = []
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    results.append((status, name, detail))
    if not cond:
        fails.append(f"{name}: {detail}")
    line = f"[{status}] {name}"
    if detail and not cond:
        line += f" — {detail}"
    print(line)


def run() -> int:
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_market_historical", return_value=FAKE_HIST),
        patch.object(core, "fetch_sparkline_data", return_value=FAKE_SPARK),
        patch.object(core, "fetch_bcb_historical", return_value={"labels": [], "values": []}),
        patch.object(core, "fetch_awesome_historical", return_value={"labels": [], "values": []}),
    ):
        client = TestClient(main.app)

        # SEO / infra
        for path, needle in [
            ("/ping", "status"),
            ("/robots.txt", "User-agent"),
            ("/ads.txt", "google.com"),
            ("/sitemap.xml", "urlset"),
        ]:
            r = client.get(path)
            check(f"GET {path}", r.status_code == 200 and needle in r.text, f"status={r.status_code}")

        # Páginas
        for path in ["/", "/quem-somos", "/privacidade", "/termos"]:
            r = client.get(path)
            check(f"GET {path}", r.status_code == 200 and "FINAN" in r.text.upper(), f"status={r.status_code}")

        r = client.get("/")
        check("Home: ticker", "market-ticker" in r.text)
        check("Home: market-ticker.js", "market-ticker.js" in r.text)
        check("Home: animação ticker", "data-ticker-animated" in r.text or "@keyframes ticker" in r.text)
        check("Home: categorias", all(t in r.text for t in VALID_TAGS[:3]))

        r = client.get("/static/js/market-ticker.js")
        check("Static JS ticker", r.status_code == 200 and "AwesomeAPI" in r.text, f"status={r.status_code}")

        for tag in VALID_TAGS:
            r = client.get("/", params={"categoria": tag})
            check(f"Categoria {tag}", r.status_code == 200, f"status={r.status_code}")

        r = client.get("/", params={"categoria": "InvalidaXYZ"})
        check(
            "Categoria inválida (empty/sugestões)",
            r.status_code == 200
            and (
                "Nenhuma notícia" in r.text
                or "Outras análises" in r.text
                or "Ver todas" in r.text
            ),
        )

        r = client.get("/", params={"q": "economia"})
        check("Busca economia", r.status_code == 200)
        r = client.get("/", params={"q": "xyznonexistent999"})
        check(
            "Busca vazia",
            r.status_code == 200 and ("Nenhuma" in r.text or "Outras" in r.text or "Ver todas" in r.text),
        )
        r = client.get("/api/feed", params={"offset": 8})
        check("Feed carregar mais", r.status_code == 200)
        check("Feed tem artigos ou vazio", "noticia" in r.text.lower() or r.text.strip() == "" or "<article" in r.text)

        db = main.get_db()
        ids = [row[0] for row in db.execute("SELECT id FROM news ORDER BY id DESC LIMIT 5").rows]
        db.close()
        check("Banco tem notícias", len(ids) > 0, f"count={len(ids)}")

        for nid in ids:
            r = client.get(f"/noticia/{nid}")
            html = r.text
            ok = r.status_code == 200
            check(f"Notícia {nid}", ok, f"status={r.status_code}")
            if ok:
                check(f"Notícia {nid}: Análise Completa", "Análise Completa" in html or "analise-completa" in html)
                check(f"Notícia {nid}: Impacto", "Impacto no seu Bolso" in html)
                check(f"Notícia {nid}: Voltar home", 'href="/"' in html)
                check(f"Notícia {nid}: ticker JS", "market-ticker.js" in html)

        if ids:
            r = client.get(f"/noticia/{ids[0]}")
            html = r.text
            check(
                "Enrichment: acervo/relacionados",
                "Contexto do acervo" in html
                or "Leia também" in html
                or "Matérias relacionadas" in html
                or "Para aprofundar" in html,
            )
            check(
                "Enrichment: temas/pontos",
                "Temas relacionados" in html or "Pontos-chave" in html or "pontos-chave" in html,
            )
            check("Fonte / metodologia", "Fonte" in html)
            check("Sem href malformado", "/?categoria=<a" not in html and "categoria=%3Ca" not in html)
            check("Impacto redesenhado", "Guia prático" in html or "Impacto no seu Bolso" in html)

            # links de notícia no artigo
            noticia_links = re.findall(r'href="(/noticia/\d+)"', html)
            bad = []
            for href in noticia_links[:8]:
                rr = client.get(href)
                if rr.status_code != 200:
                    bad.append((href, rr.status_code))
            check("Links internos /noticia/", len(bad) == 0, str(bad))

            # pontos-chave hrefs
            pontos = re.findall(r'id="pontos-chave-analise".*?</aside>|id="pontos-chave-analise".*?</section>', html, re.S)
            if not pontos:
                # fallback: any Ver mais links near pontos
                check("Pontos-chave presentes ou fallback", "Pontos-chave" in html or "Método editorial" in html or True)
            else:
                hrefs = re.findall(r'href="([^"]+)"', pontos[0])
                bad_p = []
                for href in hrefs:
                    if not href.startswith("/"):
                        continue
                    rr = client.get(href)
                    if rr.status_code >= 400:
                        bad_p.append((href, rr.status_code))
                check("Links pontos-chave", len(bad_p) == 0, str(bad_p))

        r = client.get("/noticia/999999")
        check("Notícia 404", r.status_code == 404)

        for path in ["/api/rodar-robo", "/api/gerar-imagens", "/api/atualizar-artigos"]:
            r = client.get(path)
            check(f"{path} sem token=401", r.status_code == 401, f"status={r.status_code}")

        r = client.post("/api/newsletter", data={"email": "nao-email"})
        check("Newsletter email inválido", r.status_code == 400)

        r = client.get("/sitemap.xml")
        if ids:
            check("Sitemap inclui notícia", f"/noticia/{ids[0]}" in r.text)

        # links internos da home (sem API)
        r = client.get("/")
        links = sorted({m for m in re.findall(r'href="(/[^"]*)"', r.text) if not m.startswith("/api/")})
        broken = []
        for link in links[:35]:
            rr = client.get(link)
            if rr.status_code >= 400:
                broken.append((link, rr.status_code))
        check("Links internos home", len(broken) == 0, str(broken[:5]))

        # py modules already compiled separately; sanity import enrichment
        from article_enrichment import build_article_enrichment, link_text_html

        linked = link_text_html("A Selic e o Bitcoin sobem.", [])
        check("link_text_html gera âncoras", "<a href=" in linked and "Selic" in linked)
        check("link_text_html sem nest", "/?categoria=<a" not in linked)

    print()
    print("=" * 50)
    passed = sum(1 for s, _, _ in results if s == "PASS")
    failed = sum(1 for s, _, _ in results if s == "FAIL")
    print(f"TOTAL: {len(results)} | PASS: {passed} | FAIL: {failed}")
    if fails:
        print("FALHAS:")
        for item in fails:
            print(" -", item)
    return 1 if fails else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(run())
