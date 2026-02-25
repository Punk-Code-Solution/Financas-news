import os
import random
from datetime import datetime

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
    startup_client.close()
except Exception as e:
    print(f"Aviso: Falha na inicialização do Turso: {e}")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, categoria: str = None, page: int = 1):
    client = None
    limit = 20  # Número de notícias por página
    offset = (page - 1) * limit  # Calcula quantas notícias pular

    news = []
    try:
        client = get_db()

        if categoria:
            result = client.execute(
                'SELECT * FROM news WHERE tag = ? ORDER BY id DESC LIMIT ? OFFSET ?',
                [categoria, limit, offset],
            )
        else:
            result = client.execute(
                'SELECT * FROM news ORDER BY id DESC LIMIT ? OFFSET ?',
                [limit, offset],
            )

        news = result.rows
    except Exception as e:
        # Em desenvolvimento/local, evita erro 500 quando o Turso não estiver acessível
        print(f"Aviso: erro ao buscar notícias no banco: {e}")

        # Gera 30 notícias falsas em memória para testes locais,
        # respeitando paginação (limit/offset) para testar os botões.
        hoje = datetime.utcnow().strftime("%d/%m/%Y")
        tags_possiveis = ["Cripto", "Economia", "Geral"]
        sentimentos = ["Positivo", "Negativo", "Neutro"]

        todas_noticias = []
        for i in range(1, 31):
            tag = random.choice(tags_possiveis)
            sentimento = random.choice(sentimentos)
            todas_noticias.append(
                {
                    "id": i,
                    "titulo": f"Notícia de teste #{i} sobre {tag}",
                    "resumo": "Esta é uma notícia de teste gerada localmente para validação visual da interface.",
                    "impacto": f"Impacto {sentimento.lower()} simulado no seu bolso para fins de desenvolvimento.",
                    "link": "https://exemplo.local/noticia-teste",
                    "tag": tag,
                    "data": hoje,
                    "sentimento": sentimento,
                }
            )

        # Aplica paginação nos dados fake
        inicio = offset
        fim = offset + limit
        news = todas_noticias[inicio:fim]
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "news": news,
            "categoria_ativa": categoria,
            "page": page,
            "limit": limit,
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

@app.get("/privacidade", response_class=HTMLResponse)
async def privacidade(request: Request):
    return templates.TemplateResponse("privacidade.html", {"request": request})

@app.get("/termos", response_class=HTMLResponse)
async def termos(request: Request):
    return templates.TemplateResponse("termos.html", {"request": request})

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
        # Acessa o ID usando o índice [0] do resultado
        xml_content += f'  <url><loc>https://financas-news.net.br/noticia/{n[0]}</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>\n'
        
    xml_content += '</urlset>'
    return Response(content=xml_content, media_type="application/xml")

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
            # Salva definitivamente na Nuvem (Turso)
            client.execute('''
                INSERT INTO news (titulo, resumo, impacto, link, tag)
                VALUES (?, ?, ?, ?, ?)
            ''', [
                n["titulo_viral"],
                n["resumo_simples"],
                n["impacto_bolso"],
                n["original_link"],
                n["tag"]
            ])
            salvas += 1
            
    client.close()
    return {
        "status": "Sucesso", 
        "processadas_pela_ia": len(noticias_geradas), 
        "novas_salvas_no_banco": salvas
    }

@app.get("/quem-somos", response_class=HTMLResponse)
async def quem_somos(request: Request):
    return templates.TemplateResponse("quem-somos.html", {"request": request})

@app.get("/ping")
def ping():
    return {"status": "Render acordado!"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)