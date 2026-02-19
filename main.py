import sqlite3
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn
import os

app = FastAPI()

# Configuração de arquivos estáticos e templates
# Certifique-se de ter as pastas 'static' e 'templates' no seu projeto
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_PATH = 'news.db'

# --- FUNÇÃO AUXILIAR PARA O BANCO DE DADOS ---
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Permite acessar colunas pelo nome
    return conn

# --- ROTAS PRINCIPAIS ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    conn = get_db_connection()
    # Busca as últimas 20 notícias para a Home
    news = conn.execute('SELECT * FROM news ORDER BY id DESC LIMIT 20').fetchall()
    conn.close()
    return templates.TemplateResponse("index.html", {"request": request, "news": news})

@app.get("/noticia/{noticia_id}", response_class=HTMLResponse)
async def ver_noticia(request: Request, noticia_id: int):
    conn = get_db_connection()
    noticia = conn.execute('SELECT * FROM news WHERE id = ?', (noticia_id,)).fetchone()
    conn.close()
    
    if noticia is None:
        raise HTTPException(status_code=404, detail="Notícia não encontrada")
        
    return templates.TemplateResponse("noticia.html", {"request": request, "noticia": noticia})

# --- ROTAS DE CONFORMIDADE (ADSENSE & SEO) ---

@app.get("/privacidade", response_class=HTMLResponse)
async def privacidade(request: Request):
    return templates.TemplateResponse("privacidade.html", {"request": request})

@app.get("/termos", response_class=HTMLResponse)
async def termos(request: Request):
    return templates.TemplateResponse("termos.html", {"request": request})

@app.get("/ads.txt", response_class=Response)
def get_ads_txt():
    # Seu ID de editor verificado pelo Google
    content = "google.com, pub-3623062544438213, DIRECT, f08c47fec0942fa0"
    return Response(content=content, media_type="text/plain")

@app.get("/robots.txt", response_class=Response)
def get_robots_txt():
    content = "User-agent: *\nAllow: /\nSitemap: https://financas-news.net.br/sitemap.xml"
    return Response(content=content, media_type="text/plain")

@app.get("/sitemap.xml", response_class=Response)
def get_sitemap():
    conn = get_db_connection()
    noticias = conn.execute('SELECT id FROM news ORDER BY id DESC LIMIT 500').fetchall()
    conn.close()

    # Links base
    urls = [
        "https://financas-news.net.br/",
        "https://financas-news.net.br/privacidade",
        "https://financas-news.net.br/termos"
    ]
    
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    # Adiciona páginas estáticas
    for url in urls:
        xml_content += f'  <url><loc>{url}</loc><changefreq>daily</changefreq><priority>0.8</priority></url>\n'
    
    # Adiciona links dinâmicos das notícias para o Google indexar
    for n in noticias:
        xml_content += f'  <url><loc>https://financas-news.net.br/noticia/{n["id"]}</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>\n'
        
    xml_content += '</urlset>'
    return Response(content=xml_content, media_type="application/xml")

# --- INICIALIZAÇÃO ---

if __name__ == "__main__":
    # Porta configurada para rodar localmente e no Render
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)