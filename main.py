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
from monetization import get_monetization_config

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
           fonte, dados_mercado, contexto_editorial, imagem_url
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
    
    # FORMATO CORRIGIDO PARA EVITAR ERRO 500 (TypeError)
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
        }
    )

@app.get("/noticia/{noticia_id}", response_class=HTMLResponse)
async def ver_noticia(request: Request, noticia_id: int):
    client = get_db()
    result = client.execute(NEWS_SELECT + " WHERE id = ?", [noticia_id])
    client.close()
    
    if not result.rows:
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

    return templates.TemplateResponse(
        request=request,
        name="noticia.html",
        context={
            "request": request,
            "noticia": noticia,
            "dados_mercado": dados_mercado,
            "monetization": get_monetization_config(),
            "categorias": CATEGORIAS,
        },
    )

@app.post("/api/newsletter")
async def newsletter_signup(email: str = Form(...)):
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="E-mail inválido")

    config = get_monetization_config()
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
            client.execute('''
                INSERT INTO news (titulo, resumo, impacto, link, tag, sentimento, published_at, fonte, dados_mercado, contexto_editorial, created_at, imagem_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                n["titulo_viral"],
                n["resumo_simples"],
                n["impacto_bolso"],
                n["original_link"],
                n["tag"],
                n.get("sentimento", "Neutro"),
                agora,
                n.get("fonte"),
                n.get("dados_mercado"),
                n.get("contexto_editorial", ""),
                agora,
                n.get("imagem_url"),
            ])
            salvas += 1
            
    client.close()
    return {
        "status": "Sucesso", 
        "processadas_pela_ia": len(noticias_geradas), 
        "novas_salvas_no_banco": salvas
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)