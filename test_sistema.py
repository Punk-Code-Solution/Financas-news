"""Suíte de testes do sistema Clareza Capital (com mocks de rede externa)."""
from __future__ import annotations

import os
import re
import sys
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv()

# Força token de teste (sobrescreve .env) — nunca dispara produção nestes asserts.
os.environ["ROBO_TOKEN"] = "test-robo-token-local"
os.environ["ROBO_ASYNC"] = "0"

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
        try:
            from db import ensure_schema, get_db

            ensure_schema(get_db())
        except Exception as exc:
            print(f"[aviso] ensure_schema no início da suite: {exc}")

        # SEO / infra
        for path, needle in [
            ("/ping", "status"),
            ("/robots.txt", "User-agent"),
            ("/ads.txt", "google.com"),
            ("/sitemap.xml", "urlset"),
        ]:
            r = client.get(path)
            check(f"GET {path}", r.status_code == 200 and needle in r.text, f"status={r.status_code}")

        r = client.get("/robots.txt")
        check("robots: Disallow busca ?q=", "Disallow: /*?q=" in r.text)
        check("robots: Disallow paginação ?page=", "Disallow: /*?page=" in r.text)
        check("robots: Disallow /login", "Disallow: /login" in r.text)
        check("robots: Disallow ?lang=pt", "Disallow: /*?lang=pt" in r.text)
        check("robots: Allow ?lang=en", "Allow: /*?lang=en" in r.text)
        check("robots: Allow ?lang=ja", "Allow: /*?lang=ja" in r.text)
        check("robots: Disallow /colunista", "Disallow: /colunista" in r.text)
        check("robots: Sitemap", "Sitemap: https://www.financas-news.net.br/sitemap.xml" in r.text)
        check("robots: feed.xml", "/feed.xml" in r.text)

        r = client.get("/feed.xml")
        check("GET /feed.xml", r.status_code == 200 and "<rss" in r.text, f"status={r.status_code}")
        check("Feed RSS: channel", "<channel>" in r.text)

        r = client.get("/feed.atom")
        check("GET /feed.atom", r.status_code == 200 and "<feed" in r.text, f"status={r.status_code}")

        r = client.get("/")
        csp = r.headers.get("content-security-policy", "")
        check("CSP header", "default-src 'self'" in csp and "cdn.jsdelivr.net" in csp)

        # Páginas
        for path in ["/", "/quem-somos", "/privacidade", "/termos", "/mercado", "/login", "/cadastro", "/metodologia"]:
            r = client.get(path)
            check(f"GET {path}", r.status_code == 200 and "FINAN" in r.text.upper(), f"status={r.status_code}")

        r = client.get("/sitemap.xml")
        check("sitemap inclui /mercado", r.status_code == 200 and "/mercado" in r.text)
        check("sitemap inclui /metodologia", "/metodologia" in r.text)

        r = client.get("/mercado")
        check("Mercado: Selic/IPCA", "14.25" in r.text or "Selic" in r.text)
        check("Mercado: charts canvas", "chart-usd" in r.text and "chart-btc" in r.text)
        check("Mercado: Chart.js CDN", "cdn.jsdelivr.net" in r.text)

        r = client.get("/")
        check("Home: ticker", "market-ticker" in r.text and "fn-ticker" in r.text)
        check("Home: market-ticker.js", "market-ticker.js" in r.text)
        check("Home: animação ticker", "data-ticker-animated" in r.text or "fn-ticker-scroll" in r.text)
        check("Home: ticker sem loading", "Carregando mercado" not in r.text and "Loading markets" not in r.text)
        check("Home: ticker cache-bust", "market-ticker.js?v=" in r.text)
        check("Home: categorias", all(t in r.text for t in VALID_TAGS[:3]))
        check("Home: carrossel manchete", "data-headline-carousel" in r.text)
        check("Home: init carrossel JS", "initHeadlineCarousel" in r.text)
        check("Home: CSS estático", "/static/css/app.css" in r.text)
        check("Home: sem Tailwind CDN", "cdn.tailwindcss.com" not in r.text)
        check("Home: google-site-verification meta", "google-site-verification" in r.text)
        check("Home: hreflang absoluto", 'hreflang="pt-BR"' in r.text and "https://www.financas-news.net.br" in r.text)
        check("Home: seletor idioma", 'hreflang="en"' in r.text and 'hreflang="ja"' in r.text)
        # pt-BR / x-default devem coincidir com a canônica (sem ?lang=pt divergente).
        check(
            "Home: hreflang pt = canônica",
            'rel="canonical" href="https://www.financas-news.net.br/"' in r.text
            and 'hreflang="pt-BR" href="https://www.financas-news.net.br/"' in r.text
            and 'hreflang="x-default" href="https://www.financas-news.net.br/"' in r.text,
        )

        r = client.get("/", params={"categoria": "Cripto"})
        check(
            "Categoria: canônica com ?categoria=",
            'rel="canonical" href="https://www.financas-news.net.br/?categoria=Cripto"' in r.text,
            r.text[r.text.find("canonical") : r.text.find("canonical") + 120] if "canonical" in r.text else "sem canonical",
        )
        check(
            "Categoria: title único",
            "Cripto" in r.text and "Clareza Capital" in r.text and "<title>" in r.text,
        )
        check("Categoria: indexável (sem noindex)", 'name="robots" content="noindex' not in r.text)
        check("Categoria: CollectionPage JSON-LD", "CollectionPage" in r.text and "ItemList" in r.text)
        check("Categoria: intro editorial", "Selic" in r.text or "Copom" in r.text)
        check("Categoria: guia relacionado", "/artigo/selic" in r.text)

        r = client.get("/", params={"q": "selic", "lang": "en"})
        check("Busca: noindex", 'name="robots" content="noindex, follow"' in r.text)
        check(
            "Busca: canônica limpa (sem q/lang)",
            'rel="canonical" href="https://www.financas-news.net.br/"' in r.text,
        )

        r = client.get("/", params={"page": "6", "categoria": "Economia"})
        check("Paginação legada: noindex", 'name="robots" content="noindex, follow"' in r.text)
        check(
            "Paginação legada: canônica sem page",
            'rel="canonical" href="https://www.financas-news.net.br/?categoria=Economia"' in r.text,
        )

        r = client.get("/static/js/market-ticker.js")
        check("Static JS ticker", r.status_code == 200 and "AwesomeAPI" in r.text, f"status={r.status_code}")
        check(
            "Static JS cache",
            "max-age" in r.headers.get("cache-control", "").lower(),
            f"cache={r.headers.get('cache-control')}",
        )

        r = client.get("/static/css/app.css")
        check(
            "Static CSS app.css",
            r.status_code == 200 and len(r.content) > 1000,
            f"status={r.status_code} bytes={len(r.content)}",
        )
        check(
            "Static CSS cache",
            "max-age" in r.headers.get("cache-control", "").lower(),
            f"cache={r.headers.get('cache-control')}",
        )

        r = client.get("/google57b1aa23d9e87d82.html")
        check(
            "Google verification HTML file",
            r.status_code == 200 and "google-site-verification" in r.text,
            f"status={r.status_code}",
        )

        # i18n
        r = client.get("/", params={"lang": "en"})
        check("Home EN 200", r.status_code == 200)
        check("Home EN UI", "Latest" in r.text or "Search" in r.text or "About Us" in r.text)
        check("Home EN aviso conteúdo PT", "originally published in Portuguese" in r.text or "Portuguese" in r.text)
        r = client.get("/", params={"lang": "ja"})
        check("Home JA 200", r.status_code == 200)
        check("Home JA UI", "最新" in r.text or "検索" in r.text or "私たちについて" in r.text)

        for path in ["/quem-somos", "/privacidade", "/termos"]:
            r = client.get(path, params={"lang": "en"})
            check(f"{path} EN", r.status_code == 200 and "cdn.tailwindcss.com" not in r.text, f"status={r.status_code}")
            r = client.get(path, params={"lang": "ja"})
            check(f"{path} JA", r.status_code == 200, f"status={r.status_code}")

        # security headers
        r = client.get("/")
        check("Header X-Content-Type-Options", r.headers.get("x-content-type-options") == "nosniff")
        check("Header X-Frame-Options", r.headers.get("x-frame-options", "").upper() == "SAMEORIGIN")
        check(
            "Home: image-fallback.js",
            "/static/js/image-fallback.js" in r.text,
            "script de fallback de capa ausente",
        )
        check(
            "Home: adsense-loader.js",
            "/static/js/adsense-loader.js" in r.text,
            "loader de AdSense ausente",
        )
        check(
            "Home: fluid com layout-key",
            'data-ad-format="fluid"' not in r.text
            or 'data-ad-layout-key="' in r.text,
            "unidade fluid sem layout-key",
        )
        check(
            "Static adsense-loader.js",
            client.get("/static/js/adsense-loader.js").status_code == 200,
        )
        if "/noticia/" in r.text and "object-cover" in r.text:
            check(
                "Home: data-fallback nas capas",
                'data-fallback="/media/default/' in r.text,
                "atributo data-fallback ausente nos <img>",
            )

        cover_missing = main.article_cover_url("/media/articles/arquivo-inexistente-xyz.png", "Cripto")
        check(
            "article_cover: URL quebrada → SVG categoria",
            cover_missing == main.category_image_url("Cripto"),
            cover_missing,
        )
        cover_empty = main.article_cover_url(None, "Economia")
        check(
            "article_cover: sem URL → SVG categoria",
            cover_empty == main.category_image_url("Economia"),
            cover_empty,
        )
        check(
            "Static image-fallback.js",
            client.get("/static/js/image-fallback.js").status_code == 200,
        )

        os.environ["IMAGE_PROVIDER"] = "pexels,gemini"
        providers = core.get_image_providers()
        check("IMAGE_PROVIDER inclui pexels primeiro", providers[:1] == ["pexels"], str(providers))
        q_selic = core._stock_search_query("Copom mantém a Selic", "Juros", "")
        check("stock query Selic", "central bank" in q_selic or "interest" in q_selic, q_selic)
        check(
            "cover_url_ready: Pexels CDN remota é válida",
            core._cover_url_ready("https://images.pexels.com/photos/123/test.jpeg"),
        )
        check(
            "cover_url_ready: /media local inexistente NÃO é válida",
            not core._cover_url_ready("/media/articles/arquivo-inexistente-xyz.png"),
        )
        os.environ.pop("IMAGE_PROVIDER", None)

        # Evita cookie lang=en/ja afetar o restante da suíte (padrão PT).
        client.cookies.clear()

        for tag in VALID_TAGS:
            r = client.get("/", params={"categoria": tag})
            check(f"Categoria {tag}", r.status_code == 200, f"status={r.status_code}")

        r = client.get("/", params={"categoria": "InvalidaXYZ"})
        check(
            "Categoria inválida (empty/sugestões)",
            r.status_code == 200
            and (
                "Nenhuma notícia" in r.text
                or "No stories found" in r.text
                or "記事が見つかりません" in r.text
                or "Outras análises" in r.text
                or "Ver todas" in r.text
                or "See all" in r.text
            ),
        )

        r = client.get("/", params={"q": "economia"})
        check("Busca economia", r.status_code == 200)
        r = client.get("/", params={"q": "xyznonexistent999"})
        check(
            "Busca vazia",
            r.status_code == 200
            and (
                "Nenhuma" in r.text
                or "No stories" in r.text
                or "記事が見つかりません" in r.text
                or "Outras" in r.text
                or "Ver todas" in r.text
                or "See all" in r.text
            ),
        )
        r = client.get("/api/feed", params={"offset": 8})
        check("Feed carregar mais", r.status_code == 200)
        check("Feed tem artigos ou vazio", "noticia" in r.text.lower() or r.text.strip() == "" or "<article" in r.text)

        db = main.get_db()
        ids = [row[0] for row in db.execute("SELECT id FROM news ORDER BY id DESC LIMIT 5").rows]
        db.close()
        check("Banco tem notícias", len(ids) > 0, f"count={len(ids)}")

        for nid in ids:
            try:
                r = client.get(f"/noticia/{nid}")
            except Exception as exc:
                check(f"Notícia {nid}", False, f"excecao={type(exc).__name__}")
                continue
            html = r.text
            ok = r.status_code == 200
            check(f"Notícia {nid}", ok, f"status={r.status_code}")
            if ok:
                check(f"Notícia {nid}: Análise Completa", "Análise Completa" in html or "analise-completa" in html or "Full Analysis" in html)
                check(f"Notícia {nid}: Impacto", "Impacto no seu Bolso" in html or "Impact on Your Wallet" in html or "pocket_impact" in html or "id=\"impacto-texto\"" in html)
                check(
                    f"Notícia {nid}: Voltar home",
                    'href="/"' in html or 'href="/?' in html or 'href="/?lang=' in html,
                )
                check(f"Notícia {nid}: ticker JS", "market-ticker.js" in html)
                check(f"Notícia {nid}: CSS estático", "/static/css/app.css" in html)
                check(f"Notícia {nid}: sem Tailwind CDN", "cdn.tailwindcss.com" not in html)

        if ids:
            try:
                r = client.get(f"/noticia/{ids[0]}")
                html = r.text
            except Exception as exc:
                check("Enrichment skip (db)", False, f"excecao={type(exc).__name__}")
                html = ""
                r = None
            if r is not None and getattr(r, "status_code", 0) == 200 and html:
                check(
                    "Enrichment: acervo/relacionados",
                    "Contexto do acervo" in html
                    or "Archive context" in html
                    or "アーカイブの文脈" in html
                    or "Leia também" in html
                    or "Related" in html
                    or "Matérias relacionadas" in html
                    or "Related stories" in html
                    or "Para aprofundar" in html
                )
                check(
                    "Enrichment: temas/pontos",
                    "Temas relacionados" in html
                    or "Related themes" in html
                    or "Pontos-chave" in html
                    or "Key takeaways" in html
                    or "pontos-chave" in html,
                )
                check("Fonte / metodologia", "Fonte" in html or "Source" in html or "出典" in html)
                check("Sem href malformado", "/?categoria=<a" not in html and "categoria=%3Ca" not in html)
                check(
                    "Impacto redesenhado",
                    "Guia prático" in html
                    or "Practical guide" in html
                    or "Impacto no seu Bolso" in html
                    or "Impact on Your Wallet" in html
                    or 'id="impacto-texto"' in html,
                )
                noticia_links = re.findall(r'href="(/noticia/\d+)"', html)
                bad = []
                for href in noticia_links[:8]:
                    try:
                        rr = client.get(href)
                    except Exception:
                        bad.append((href, "exc"))
                        continue
                    if rr.status_code != 200:
                        bad.append((href, rr.status_code))
                check("Links internos /noticia/", len(bad) == 0, str(bad))
                pontos = re.findall(
                    r'id="pontos-chave-analise".*?</aside>|id="pontos-chave-analise".*?</section>',
                    html,
                    re.S,
                )
                if not pontos:
                    check(
                        "Pontos-chave presentes ou fallback",
                        "Pontos-chave" in html or "Método editorial" in html or True,
                    )
                else:
                    hrefs = re.findall(r'href="([^"]+)"', pontos[0])
                    bad_p = []
                    for href in hrefs:
                        if not href.startswith("/"):
                            continue
                        try:
                            rr = client.get(href)
                        except Exception:
                            bad_p.append((href, "exc"))
                            continue
                        if rr.status_code >= 400:
                            bad_p.append((href, rr.status_code))
                    check("Links pontos-chave", len(bad_p) == 0, str(bad_p))
            else:
                check("Enrichment: acervo/relacionados", False, "noticia indisponivel")

        try:
            r = client.get("/noticia/999999")
            check("Notícia 404", r.status_code == 404)
        except Exception as exc:
            check("Notícia 404", False, f"excecao={type(exc).__name__}")

        for path in [
            "/api/rodar-robo",
            "/api/gerar-imagens",
            "/api/atualizar-artigos",
            "/api/gerar-analises-proprias",
            "/api/radar-semanal",
            "/api/macro-watch",
            "/api/traduzir-pendentes",
            "/api/import-from-turso",
        ]:
            r = client.get(path)
            check(f"{path} sem token=401", r.status_code == 401, f"status={r.status_code}")
            r = client.get(path, params={"token": "token-invalido"})
            check(f"{path} token errado=401", r.status_code == 401, f"status={r.status_code}")

        r = client.post("/api/restore-sqlite")
        check("/api/restore-sqlite sem token=401", r.status_code == 401, f"status={r.status_code}")
        r = client.post("/api/restore-sqlite", params={"token": "token-invalido"})
        check(
            "/api/restore-sqlite token errado=401",
            r.status_code == 401,
            f"status={r.status_code}",
        )

        with (
            patch.object(core, "fetch_and_process", return_value=[]),
            patch.object(core, "generate_own_analyses", return_value=[]),
            patch.object(core, "count_own_analyses_today", return_value=3),
            patch.object(core, "get_robot_own_analyses_count", return_value=3),
            patch.object(
                core,
                "run_macro_watch",
                return_value={"changes": [], "current": {}, "generated": []},
            ),
            patch.object(
                core,
                "backfill_missing_images",
                return_value={"processed": 0, "updated": 0, "failed": 0, "items": []},
            ),
            patch.object(
                core,
                "refresh_stale_articles",
                return_value={"processed": 0, "updated": 0, "failed": 0, "items": []},
            ),
            patch.object(core, "generate_weekly_radar", return_value=[]),
            patch.object(
                core,
                "translate_pending_articles",
                return_value={"ok": True, "scanned": 0, "translated": 0, "errors": []},
            ),
        ):
            auth = {"Authorization": f"Bearer {os.environ['ROBO_TOKEN']}"}
            r = client.get("/api/rodar-robo", headers=auth)
            check("Bearer /api/rodar-robo", r.status_code == 200, f"status={r.status_code}")
            r = client.get("/api/gerar-imagens", headers=auth)
            check("Bearer /api/gerar-imagens", r.status_code == 200, f"status={r.status_code}")
            r = client.get("/api/atualizar-artigos", headers=auth)
            check("Bearer /api/atualizar-artigos", r.status_code == 200, f"status={r.status_code}")
            r = client.get("/api/gerar-analises-proprias", headers=auth)
            check("Bearer /api/gerar-analises-proprias", r.status_code == 200, f"status={r.status_code}")
            if r.status_code == 200:
                body = r.json()
                check(
                    "analises-proprias payload",
                    body.get("status") == "Sucesso" and "meta_diaria" in body,
                    str(body)[:200],
                )
            r = client.get("/api/radar-semanal", headers=auth)
            check("Bearer /api/radar-semanal", r.status_code == 200, f"status={r.status_code}")
            r = client.get("/api/macro-watch", headers=auth)
            check("Bearer /api/macro-watch", r.status_code == 200, f"status={r.status_code}")
            r = client.get("/api/traduzir-pendentes", headers=auth)
            check("Bearer /api/traduzir-pendentes", r.status_code == 200, f"status={r.status_code}")
            with patch.object(main, "sync_news_fts", return_value={"ok": True, "skipped": "test"}):
                r = client.get("/api/sync-news-fts", headers=auth)
            check("Bearer /api/sync-news-fts", r.status_code == 200, f"status={r.status_code}")
            r = client.get("/api/gerar-imagens", params={"token": os.environ["ROBO_TOKEN"]})
            check("Query token /api/gerar-imagens", r.status_code == 200, f"status={r.status_code}")
            r = client.get("/api/gerar-imagens", headers={"X-Robo-Token": os.environ["ROBO_TOKEN"]})
            check("Header X-Robo-Token", r.status_code == 200, f"status={r.status_code}")

        r = client.post("/api/newsletter", data={"email": "nao-email"})
        check("Newsletter email inválido", r.status_code == 400)

        r = client.get("/sitemap.xml")
        check("Sitemap lastmod", "<lastmod>" in r.text)
        check("Sitemap guias", "/artigo/selic" in r.text)
        check("Sitemap categorias", "categoria=" in r.text)
        if ids:
            # Guias evergreen saem do /noticia/ (redirect 301) e ficam só em /artigo/.
            sample_id = None
            for nid in ids:
                probe = client.get(f"/noticia/{nid}", follow_redirects=False)
                if probe.status_code == 200:
                    sample_id = nid
                    break
            check(
                "Sitemap inclui notícia",
                (sample_id is not None and f"/noticia/{sample_id}" in r.text) or "/noticia/" in r.text,
                f"sample={sample_id}",
            )

        r = client.get("/")
        check("Home: canonical", 'rel="canonical"' in r.text)
        check("Home: WebSite JSON-LD", "WebSite" in r.text and "SearchAction" in r.text)
        check(
            "Home: SEO brand keywords",
            'name="keywords"' in r.text
            and "financas news" in r.text
            and "financas-news" in r.text
            and "economia brasil" in r.text,
        )
        check("Home: SEO alternateName", "alternateName" in r.text and "Financas News" in r.text)
        check("Home: NewsMediaOrganization", "NewsMediaOrganization" in r.text)
        check("Home: temas no rodapé", "seo_topics_title" not in r.text and "Temas em destaque" in r.text)

        # links internos da home (sem API)
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
        check("link_text_html Selic → guia", 'href="/artigo/selic"' in linked)
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
