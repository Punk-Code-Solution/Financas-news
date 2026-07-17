import os
import json
from datetime import datetime
from fastapi import FastAPI, Request, Response, HTTPException, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
from dotenv import load_dotenv

import core
from db import get_db, ensure_schema
from monetization import get_monetization_config, get_contextual_affiliate
from article_enrichment import build_article_enrichment, resolve_referencias_internas

load_dotenv()

app = FastAPI()

ARTICLE_IMAGES_DIR = os.getenv("ARTICLE_IMAGES_DIR", "static/images/articles")
os.makedirs(ARTICLE_IMAGES_DIR, exist_ok=True)
os.makedirs("static/images/articles", exist_ok=True)

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
if os.path.isdir(ARTICLE_IMAGES_DIR):
    app.mount("/media/articles", StaticFiles(directory=ARTICLE_IMAGES_DIR), name="article_images")
templates = Jinja2Templates(directory="templates")

CATEGORIAS = core.VALID_TAGS

DEFAULT_CATEGORY_IMAGES = {
    "Cripto": {"slug": "cripto", "label": "Cripto", "from": "#0b1220", "to": "#14532d", "accent": "#4ade80", "icon": "₿"},
    "Economia": {"slug": "economia", "label": "Economia", "from": "#0f172a", "to": "#0e7490", "accent": "#67e8f9", "icon": "∑"},
    "Dólar": {"slug": "dolar", "label": "Dólar", "from": "#052e16", "to": "#166534", "accent": "#86efac", "icon": "$"},
    "Ações": {"slug": "acoes", "label": "Ações", "from": "#172554", "to": "#1d4ed8", "accent": "#93c5fd", "icon": "↗"},
    "Juros": {"slug": "juros", "label": "Juros", "from": "#1c1917", "to": "#9a3412", "accent": "#fdba74", "icon": "%"},
    "Inflação": {"slug": "inflacao", "label": "Inflação", "from": "#450a0a", "to": "#b91c1c", "accent": "#fca5a5", "icon": "▲"},
    "Imóveis": {"slug": "imoveis", "label": "Imóveis", "from": "#0c4a6e", "to": "#0369a1", "accent": "#7dd3fc", "icon": "⌂"},
    "Fintech": {"slug": "fintech", "label": "Fintech", "from": "#2e1065", "to": "#7c3aed", "accent": "#d8b4fe", "icon": "⚡"},
    "Commodities": {"slug": "commodities", "label": "Commodities", "from": "#422006", "to": "#a16207", "accent": "#fde68a", "icon": "◆"},
    "Política Econômica": {"slug": "politica-economica", "label": "Política", "from": "#1e1b4b", "to": "#4338ca", "accent": "#a5b4fc", "icon": "⚖"},
}
DEFAULT_IMAGE_BY_SLUG = {item["slug"]: item for item in DEFAULT_CATEGORY_IMAGES.values()}


def category_image_url(tag: object) -> str:
    item = DEFAULT_CATEGORY_IMAGES.get(str(tag), DEFAULT_CATEGORY_IMAGES["Economia"])
    return f"/media/default/{item['slug']}.svg?v=3"


templates.env.globals["category_image"] = category_image_url

try:
    startup_client = get_db()
    ensure_schema(startup_client)
    startup_client.close()
except Exception as e:
    print(f"Aviso: Falha na inicialização do Turso: {e}")

# ==========================================
# ROTAS DE PÁGINAS (FRONTEND) - ATUALIZADAS PARA FASTAPI MODERNO
# ==========================================

NEWS_SELECT = """
    SELECT id, titulo, resumo, impacto, link, tag, sentimento,
           COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao,
           fonte, dados_mercado, contexto_editorial, imagem_url,
           conteudo_extra, updated_at, versao_analise
    FROM news
"""

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, categoria: str | None = None, page: int = 1, q: str | None = None):
    client = get_db()
    limit = 20
    offset = (page - 1) * limit
    
    if q:
        busca = f"%{q}%"
        result = client.execute(
            NEWS_SELECT + " WHERE titulo LIKE ? OR resumo LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
            [busca, busca, limit, offset],
        )
        count_res = client.execute('SELECT COUNT(*) FROM news WHERE titulo LIKE ? OR resumo LIKE ?', [busca, busca])
    elif categoria:
        result = client.execute(
            NEWS_SELECT + " WHERE tag = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            [categoria, limit, offset],
        )
        count_res = client.execute('SELECT COUNT(*) FROM news WHERE tag = ?', [categoria])
    else:
        result = client.execute(NEWS_SELECT + " ORDER BY id DESC LIMIT ? OFFSET ?", [limit, offset])
        count_res = client.execute('SELECT COUNT(*) FROM news')
    
    news = result.rows

    suggested_news = []
    if not news and (categoria or q):
        if categoria:
            suggested_result = client.execute(
                NEWS_SELECT + " WHERE tag != ? ORDER BY id DESC LIMIT ?",
                [categoria, 8],
            )
        else:
            suggested_result = client.execute(
                NEWS_SELECT + " ORDER BY id DESC LIMIT ?",
                [8],
            )
        suggested_news = suggested_result.rows
    
    row_count = count_res.rows[0][0]
    if isinstance(row_count, (int, float)):
        total_news = int(row_count)
    elif isinstance(row_count, str):
        total_news = int(row_count)
    else:
        total_news = 0
    total_pages = (total_news + limit - 1) // limit
    if total_pages == 0:
        total_pages = 1
        
    client.close()
    
    # Sparklines: não bloqueiam a home (cache + refresh em background).
    sparklines = core.fetch_sparkline_data(blocking=False)

    return templates.TemplateResponse(
        request=request,
        name="index.html", 
        context={
            "request": request, 
            "news": news, 
            "categoria_ativa": categoria,
            "categorias": CATEGORIAS,
            "page": page,
            "limit": limit,
            "q": q,
            "total_pages": total_pages,
            "monetization": get_monetization_config(),
            "suggested_news": suggested_news,
            "sparklines": sparklines,
        }
    )

@app.get("/noticia/{noticia_id}", response_class=HTMLResponse)
async def ver_noticia(request: Request, noticia_id: int):
    client = get_db()
    result = client.execute(NEWS_SELECT + " WHERE id = ?", [noticia_id])

    if not result.rows:
        client.close()
        raise HTTPException(status_code=404, detail="Notícia não encontrada")

    noticia = result.rows[0]
    dados_mercado = {}
    if len(noticia) > 9 and noticia[9]:
        try:
            raw_dados = noticia[9]
            if isinstance(raw_dados, (str, bytes, bytearray)):
                dados_mercado = json.loads(raw_dados)
        except json.JSONDecodeError:
            pass

    tag = str(noticia[5]) if len(noticia) > 5 and noticia[5] else "Economia"
    resumo = str(noticia[2]) if len(noticia) > 2 and noticia[2] else ""

    enrichment = build_article_enrichment(
        client,
        noticia_id,
        tag,
        dados_mercado,
        resumo=resumo,
    )
    contextual_affiliate = get_contextual_affiliate(tag)
    client.close()

    return templates.TemplateResponse(
        request=request,
        name="noticia.html",
        context={
            "request": request,
            "noticia": noticia,
            "dados_mercado": dados_mercado,
            "enrichment": enrichment,
            "monetization": get_monetization_config(),
            "contextual_affiliate": contextual_affiliate,
            "categorias": CATEGORIAS,
        },
    )

@app.post("/api/newsletter")
async def newsletter_signup(email: str = Form(...)):
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="E-mail inválido")

    config = get_monetization_config()
    if not config.get("newsletter_enabled"):
        raise HTTPException(status_code=404, detail="Newsletter indisponível")

    newsletter_url = config.get("newsletter_external_url")
    if isinstance(newsletter_url, str) and newsletter_url:
        return RedirectResponse(url=newsletter_url, status_code=303)

    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    client = get_db()
    try:
        client.execute(
            "INSERT INTO newsletter_subscribers (email, created_at) VALUES (?, ?)",
            [email, agora],
        )
    except Exception:
        pass
    client.close()
    return RedirectResponse(url="/?newsletter=ok", status_code=303)

@app.get("/quem-somos", response_class=HTMLResponse)
async def quem_somos(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="quem-somos.html", 
        context={"request": request}
    )

@app.get("/privacidade", response_class=HTMLResponse)
async def privacidade(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="privacidade.html", 
        context={"request": request}
    )

@app.get("/termos", response_class=HTMLResponse)
async def termos(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="termos.html", 
        context={"request": request}
    )

# ==========================================
# ROTAS DE SEO E INTEGRAÇÕES
# ==========================================

@app.get("/ads.txt", response_class=Response)
def get_ads_txt():
    content = "google.com, pub-3623062544438213, DIRECT, f08c47fec0942fa0"
    return Response(content=content, media_type="text/plain")


@app.get("/media/default/{slug}.svg", response_class=Response)
def get_default_category_image(slug: str):
    """Capa padrão centrada — funciona em hero e thumbnails com object-cover."""
    item = DEFAULT_IMAGE_BY_SLUG.get(slug, DEFAULT_CATEGORY_IMAGES["Economia"])
    label = str(item["label"])
    icon = str(item["icon"])
    color_from = str(item["from"])
    color_to = str(item["to"])
    accent = str(item["accent"])
    # Composição centrada (600,338): ao cortar em cards pequenos o foco permanece legível.
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675" role="img" aria-label="{label}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{color_from}"/>
      <stop offset="100%" stop-color="{color_to}"/>
    </linearGradient>
    <radialGradient id="spot" cx="50%" cy="46%" r="42%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity=".18"/>
      <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1200" height="675" fill="url(#bg)"/>
  <rect width="1200" height="675" fill="url(#spot)"/>
  <g fill="none" stroke="{accent}" stroke-opacity=".26" stroke-width="4" stroke-linecap="round">
    <path d="M60 400 L230 300 L380 340 L560 200 L730 260 L920 130 L1150 190"/>
    <path d="M60 440 L250 390 L420 420 L600 300 L790 340 L1150 230" stroke-opacity=".14"/>
  </g>
  <circle cx="600" cy="337" r="128" fill="#020617" fill-opacity=".45" stroke="{accent}" stroke-width="3" stroke-opacity=".7"/>
  <text x="600" y="337" text-anchor="middle" dominant-baseline="central"
        font-family="Segoe UI Symbol, Arial, sans-serif" font-size="86" font-weight="700" fill="{accent}">{icon}</text>
</svg>"""
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/robots.txt", response_class=Response)
def get_robots_txt():
    content = "User-agent: *\nAllow: /\nSitemap: https://financas-news.net.br/sitemap.xml"
    return Response(content=content, media_type="text/plain")

@app.get("/sitemap.xml", response_class=Response)
def get_sitemap():
    client = get_db()
    result = client.execute('SELECT id FROM news ORDER BY id DESC LIMIT 500')
    noticias = result.rows
    client.close()

    urls = [
        "https://financas-news.net.br/",
        "https://financas-news.net.br/quem-somos",
        "https://financas-news.net.br/privacidade",
        "https://financas-news.net.br/termos"
    ]
    
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    for url in urls:
        xml_content += f'  <url><loc>{url}</loc><changefreq>daily</changefreq><priority>0.8</priority></url>\n'
    
    for n in noticias:
        xml_content += f'  <url><loc>https://financas-news.net.br/noticia/{n[0]}</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>\n'
        
    xml_content += '</urlset>'
    return Response(content=xml_content, media_type="application/xml")

# ==========================================
# ROTAS DE INFRAESTRUTURA E ROBÔ
# ==========================================

@app.get("/ping")
def ping():
    return {"status": "Render acordado!"}

@app.get("/api/gerar-imagens")
def gerar_imagens(token: str | None = None, limit: int = 10):
    if token != "punkcode2026":
        raise HTTPException(status_code=401, detail="Nao autorizado")

    limit = max(1, min(limit, 20))
    print(f"Gerando imagens para ate {limit} artigos sem capa...")
    resultado = core.backfill_missing_images(limit=limit)
    return {"status": "Sucesso", **resultado}


@app.get("/api/rodar-robo")
def rodar_robo(token: str | None = None):
    if token != "punkcode2026":
        raise HTTPException(status_code=401, detail="Não autorizado")
        
    print("🤖 Iniciando robô via API...")
    noticias_geradas = core.fetch_and_process()
    
    if not noticias_geradas:
        return {"status": "Aviso: Nenhuma notícia foi processada ou houve erro na IA."}
        
    client = get_db()
    salvas = 0
    
    for n in noticias_geradas:
        check = client.execute("SELECT id FROM news WHERE link = ?", [n["original_link"]])
        
        if not check.rows:
            agora = n.get("published_at")
            dados_raw = n.get("dados_mercado")
            if dados_raw:
                try:
                    dados_obj = json.loads(dados_raw) if isinstance(dados_raw, str) else dados_raw
                    refs = dados_obj.get("referencias_internas") or []
                    if refs:
                        dados_obj["referencias_internas"] = resolve_referencias_internas(client, refs)
                        dados_raw = json.dumps(dados_obj, ensure_ascii=False)
                except json.JSONDecodeError:
                    pass

            client.execute('''
                INSERT INTO news (titulo, resumo, impacto, link, tag, sentimento, published_at, fonte, dados_mercado, contexto_editorial, created_at, imagem_url, versao_analise)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                n["titulo_viral"],
                n["resumo_simples"],
                n["impacto_bolso"],
                n["original_link"],
                n["tag"],
                n.get("sentimento", "Neutro"),
                agora,
                n.get("fonte"),
                dados_raw if dados_raw else n.get("dados_mercado"),
                n.get("contexto_editorial", ""),
                agora,
                n.get("imagem_url"),
                n.get("versao_analise", 1),
            ])
            salvas += 1
            
    client.close()
    return {
        "status": "Sucesso", 
        "processadas_pela_ia": len(noticias_geradas), 
        "novas_salvas_no_banco": salvas
    }


@app.get("/api/atualizar-artigos")
def atualizar_artigos(token: str | None = None, limit: int = 10):
    if token != "punkcode2026":
        raise HTTPException(status_code=401, detail="Não autorizado")

    limit = max(1, min(limit, 50))
    print(f"Atualizando dados de mercado de ate {limit} artigos...")
    resultado = core.refresh_stale_articles(limit=limit)
    return {"status": "Sucesso", **resultado}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)