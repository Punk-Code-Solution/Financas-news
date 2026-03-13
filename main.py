import os
from datetime import datetime
import sqlite3
import libsql_client
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn
from dotenv import load_dotenv

import core

# Carrega as chaves do arquivo .env (se estiver rodando localmente)
load_dotenv()

app = FastAPI()

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Captura as credenciais da nuvem
TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

def get_db():
    if not TURSO_URL or not TURSO_TOKEN:
        raise ValueError("Credenciais do Turso não encontradas.")
    return libsql_client.create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)

# Garante que a tabela existe no novo banco de dados em nuvem ao iniciar
try:
    startup_client = get_db()
    startup_client.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT,
            resumo TEXT,
            impacto TEXT,
            link TEXT,
            tag TEXT
        )
    ''')
    # Adiciona a coluna sentimento de forma segura (ignora se já existir)
    try:
        startup_client.execute('ALTER TABLE news ADD COLUMN sentimento TEXT')
    except:
        pass
    startup_client.close()
except Exception as e:
    print(f"Aviso: Falha na inicialização do Turso: {e}")

# ==========================================
# ROTAS DE PÁGINAS (FRONTEND)
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, categoria: str = None, page: int = 1, q: str = None):
    """
    Página inicial com paginação.
    - Em produção tenta usar Turso normalmente
    - Localmente, se o Turso falhar (ex.: erro 505), cai para o SQLite `news.db`
    """
    limit = 20
    offset = (page - 1) * limit

    def query_turso(client):
        if q:
            busca = f"%{q}%"
            result = client.execute(
                "SELECT * FROM news WHERE titulo LIKE ? OR resumo LIKE ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                [busca, busca, limit, offset],
            )
            count_res = client.execute(
                "SELECT COUNT(*) FROM news WHERE titulo LIKE ? OR resumo LIKE ?",
                [busca, busca],
            )
        elif categoria:
            result = client.execute(
                "SELECT * FROM news WHERE tag = ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                [categoria, limit, offset],
            )
            count_res = client.execute(
                "SELECT COUNT(*) FROM news WHERE tag = ?",
                [categoria],
            )
        else:
            result = client.execute(
                "SELECT * FROM news ORDER BY id DESC LIMIT ? OFFSET ?",
                [limit, offset],
            )
            count_res = client.execute("SELECT COUNT(*) FROM news")

        news = result.rows
        total_news = count_res.rows[0][0]
        return news, total_news

    def query_sqlite():
        conn = sqlite3.connect("news.db")
        cur = conn.cursor()

        if q:
            busca = f"%{q}%"
            cur.execute(
                "SELECT id, titulo, resumo, impacto, link, tag, sentimento "
                "FROM news WHERE titulo LIKE ? OR resumo LIKE ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (busca, busca, limit, offset),
            )
            news = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) FROM news WHERE titulo LIKE ? OR resumo LIKE ?",
                (busca, busca),
            )
        elif categoria:
            cur.execute(
                "SELECT id, titulo, resumo, impacto, link, tag, sentimento "
                "FROM news WHERE tag = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (categoria, limit, offset),
            )
            news = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) FROM news WHERE tag = ?",
                (categoria,),
            )
        else:
            cur.execute(
                "SELECT id, titulo, resumo, impacto, link, tag, sentimento "
                "FROM news ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            news = cur.fetchall()
            cur.execute("SELECT COUNT(*) FROM news")

        total_news = cur.fetchone()[0]
        conn.close()
        return news, total_news

    # Primeiro tenta Turso (produção)
    news = []
    total_news = 0
    client = None
    try:
        client = get_db()
        news, total_news = query_turso(client)
    except Exception as e:
        print(f"Aviso: erro ao buscar notícias no Turso, usando SQLite local: {e}")
        news, total_news = query_sqlite()
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    total_pages = (total_news + limit - 1) // limit if total_news > 0 else 1

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "news": news,
            "categoria_ativa": categoria,
            "page": page,
            "limit": limit,
            "q": q,
            "total_pages": total_pages,
        },
    )

@app.get("/noticia/{noticia_id}", response_class=HTMLResponse)
async def ver_noticia(request: Request, noticia_id: int):
    client = get_db()
    result = client.execute('SELECT * FROM news WHERE id = ?', [noticia_id])
    client.close()
    
    if not result.rows:
        raise HTTPException(status_code=404, detail="Notícia não encontrada")
        
    return templates.TemplateResponse("noticia.html", {"request": request, "noticia": result.rows[0]})

@app.get("/quem-somos", response_class=HTMLResponse)
async def quem_somos(request: Request):
    return templates.TemplateResponse("quem-somos.html", {"request": request})

@app.get("/privacidade", response_class=HTMLResponse)
async def privacidade(request: Request):
    return templates.TemplateResponse("privacidade.html", {"request": request})

@app.get("/termos", response_class=HTMLResponse)
async def termos(request: Request):
    return templates.TemplateResponse("termos.html", {"request": request})

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
def rodar_robo(token: str = None):
    # Proteção: Só roda se a senha estiver na URL
    if token != "punkcode2026":
        raise HTTPException(status_code=401, detail="Não autorizado")
        
    print("🤖 Iniciando robô via API...")
    noticias_geradas = core.fetch_and_process()
    
    if not noticias_geradas:
        return {"status": "Aviso: Nenhuma notícia foi processada ou houve erro na IA."}
        
    client = get_db()
    salvas = 0
    
    for n in noticias_geradas:
        # QA: Verifica se a notícia já existe no banco (evita duplicidade)
        check = client.execute("SELECT id FROM news WHERE link = ?", [n["original_link"]])
        
        if not check.rows:
            # Salva definitivamente na Nuvem (Turso) com a coluna Sentimento
            client.execute('''
                INSERT INTO news (titulo, resumo, impacto, link, tag, sentimento)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', [
                n["titulo_viral"],
                n["resumo_simples"],
                n["impacto_bolso"],
                n["original_link"],
                n["tag"],
                n.get("sentimento", "Neutro") # Garante que envia o sentimento ou "Neutro"
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