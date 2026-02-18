from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
import uvicorn
from core import fetch_and_process
import sqlite3
import threading
import time
import schedule

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Configuração do Banco de Dados
def init_db():
    conn = sqlite3.connect('news.db', check_same_thread=False)
    c = conn.cursor()
    # Cria a tabela se não existir
    c.execute('''CREATE TABLE IF NOT EXISTS news 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, titulo text, resumo text, impacto text, tag text, sentimento text, data text, link text)''')
    conn.commit()
    conn.close()

# Salva notícias no banco (evitando duplicatas)
def save_news_to_db(news_list):
    if not news_list: return
    
    conn = sqlite3.connect('news.db', check_same_thread=False)
    c = conn.cursor()
    count = 0
    for n in news_list:
        # Verifica se já existe pelo título
        c.execute("SELECT id FROM news WHERE titulo = ?", (n['titulo_viral'],))
        if not c.fetchone():
            c.execute("INSERT INTO news (titulo, resumo, impacto, tag, sentimento, data, link) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (n['titulo_viral'], n['resumo_simples'], n['impacto_bolso'], n['tag'], n['sentimento'], n['published_at'], n['original_link']))
            count += 1
    conn.commit()
    conn.close()
    print(f"--- 💾 {count} novas notícias salvas no Banco de Dados ---")

# O Robô que trabalha em segundo plano
def run_scheduler():
    # 1. Roda imediatamente ao iniciar
    print("🤖 Robô iniciado: Buscando notícias agora...")
    try:
        news = fetch_and_process()
        save_news_to_db(news)
    except Exception as e:
        print(f"Erro na primeira busca: {e}")
    
    # 2. Agenda para rodar a cada 30 minutos
    schedule.every(30).minutes.do(lambda: save_news_to_db(fetch_and_process()))
    
    while True:
        schedule.run_pending()
        time.sleep(1)

@app.on_event("startup")
def startup_event():
    init_db()
    # Inicia a thread do robô sem travar o site
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()

@app.get("/")
async def read_root(request: Request):
    conn = sqlite3.connect('news.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Busca as 20 notícias mais recentes
    news = c.execute("SELECT * FROM news ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    
    return templates.TemplateResponse("index.html", {"request": request, "news": news})

# 1. Rota robots.txt (Diz para o Google: "Pode ler tudo")
@app.get("/robots.txt", response_class=Response)
def get_robots_txt():
    content = """User-agent: *
Allow: /
Sitemap: https://financas-news.net.br/sitemap.xml
"""
    return Response(content=content, media_type="text/plain")

# 2. Rota sitemap.xml (Lista todas as notícias para o Google indexar)
@app.get("/sitemap.xml", response_class=Response)
def get_sitemap_xml():
    conn = sqlite3.connect('news.db')
    c = conn.cursor()
    # Pega as últimas 100 notícias
    news = c.execute("SELECT id, data FROM news ORDER BY id DESC LIMIT 100").fetchall()
    conn.close()

    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://financas-news.net.br/</loc>
        <changefreq>hourly</changefreq>
        <priority>1.0</priority>
    </url>
"""
    
    # Como seu site por enquanto é "Single Page" (tudo na home), 
    # o sitemap é simples. Mas se criarmos páginas individuais no futuro,
    # aqui entrará o loop das urls.
    
    xml_content += "</urlset>"
    return Response(content=xml_content, media_type="application/xml")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)