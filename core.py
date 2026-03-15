from google import genai
from google.genai import types
import feedparser
import os
from bs4 import BeautifulSoup
from datetime import datetime
import json
from dotenv import load_dotenv
import requests

# Carrega ambiente
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("❌ ERRO CRÍTICO: Chave API não encontrada no .env")
    client = None
else:
    # --- NOVA CONFIGURAÇÃO (GOOGLE GENAI SDK) ---
    client = genai.Client(api_key=api_key)

# Cabeçalhos para fingir ser um navegador
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

RSS_FEEDS = [
    "https://br.cointelegraph.com/rss",
    "https://g1.globo.com/dynamo/economia/rss2.xml"
]

def clean_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator=' ').strip()

def process_news_with_ai(title, content):
    if not client: return None
    
    print(f"   🤖 Enviando para IA: {title[:30]}...")
    
    prompt = f"""
    Analise esta notícia financeira:
    Título: {title}
    Conteúdo: {content[:1500]}

    Retorne APENAS um JSON válido neste formato exato (sem ```json):
    {{
        "titulo_viral": "título curto chamativo",
        "resumo_simples": "Aja como um analista financeiro sênior. Leia esta notícia e crie um artigo autoral completo. O campo 'resumo_simples' DEVE ter no mínimo 3 parágrafos bem detalhados (mais de 300 palavras), explicando o contexto do mercado, o que aconteceu e as projeções futuras. Não use frases curtas. Separe os parágrafos com quebras de linha.",
        "impacto_bolso": "efeito no dinheiro das pessoas",
        "tag": "escolha entre: Cripto, Economia, Dólar, Ações",
        "sentimento": "Positivo, Negativo ou Neutro"
    }}
    """
    
    try:
        # --- NOVA CHAMADA DE API ---
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json" # Força resposta JSON nativa
            )
        )
        
        # O novo SDK já pode retornar JSON limpo se configurado, mas vamos garantir
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
        
    except Exception as e:
        print(f"   ❌ Erro na IA: {e}")
        return None

def fetch_and_process():
    noticias_processadas = []
    print(f"\n--- Iniciando Varredura: {datetime.now()} ---")
    
    for feed_url in RSS_FEEDS:
        print(f"🔍 Acessando: {feed_url}")
        try:
            response = requests.get(feed_url, headers=HEADERS, timeout=10)
            if response.status_code != 200:
                print(f"   ❌ Erro HTTP {response.status_code}")
                continue

            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                print("   ⚠️ Feed vazio.")
                continue

            # Pega a 1ª notícia
            entry = feed.entries[0]
            print(f"   📄 Encontrada: {entry.title}")
            
            raw_content = entry.get('summary', '') or entry.get('content', [{'value': ''}])[0]['value']
            clean_text = clean_html(raw_content)
            
            if len(clean_text) < 50:
                print("   ⚠️ Texto muito curto.")
                continue

            ai_data = process_news_with_ai(entry.title, clean_text)
            
            if ai_data:
                news_item = {
                    "original_link": entry.link,
                    "published_at": datetime.now().strftime("%d/%m %H:%M"),
                    **ai_data
                }
                noticias_processadas.append(news_item)
                print("   ✅ Processado com sucesso!")

        except Exception as e:
            print(f"   ❌ Erro Crítico: {e}")
            
    return noticias_processadas

if __name__ == "__main__":
    print("🚀 Modo de Teste Manual Iniciado (Novo SDK)...")
    resultado = fetch_and_process()
    print(f"\n📊 Total processado: {len(resultado)}")
    if len(resultado) > 0:
        print("🎉 SUCESSO! JSON gerado:")
        print(json.dumps(resultado[0], indent=2, ensure_ascii=False))