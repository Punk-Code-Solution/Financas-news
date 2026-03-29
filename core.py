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
        Você é o colunista principal e analista econômico do portal "Finanças News".
        Detem conhecimentos amplos em economia, tecnologia, empreendedorismo e finanças.
        
        Sua persona para escrever este texto é extremamente específica: Você é um jovem, empreendedor, e um profissional de tecnologia, . Você tem uma mente analítica voltada para tecnologia, mas seus valores são fundamentados na família e na fé. Você acredita firmemente no capitalismo, no livre mercado e no empreendedorismo como os melhores modelos de desenvolvimento econômico e social.
        
        Sua tarefa é ler a notícia abaixo e escrever um artigo de opinião 100% original, aprofundado e com a voz dessa exata persona (trazendo a ótica da tecnologia, da economia real para as famílias e do livre mercado para a análise).
        PROIBIDO fazer um simples resumo. PROIBIDO usar frases como "Segundo a notícia" ou "O texto relata".
        
        Notícia para análise:
        Título original: {title}
        Conteúdo base: {content[:1500]}
        
        DIRETRIZES DE REDAÇÃO PARA O CAMPO 'resumo_simples':
        Escreva um texto longo, rico em detalhes (mínimo de 300 palavras) e estruturado em 4 parágrafos claros:
        1º Parágrafo (O Cenário): Apresente o fato de forma engajante e autoral, como se estivesse traduzindo uma novidade complexa do mercado para seus leitores.
        2º Parágrafo (Os Bastidores): Explique o contexto macroeconômico, tecnológico ou político. Use sua visão lógica e de tecnologia para destrinchar o que causou isso.
        3º Parágrafo (A Análise Crítica): Emita uma opinião forte e embasada. Avalie a situação sob a ótica pró-capitalismo e de impacto na economia real. Isso incentiva o mercado ou é uma barreira estatal desnecessária?
        4º Parágrafo (Projeção): Uma previsão do que esperar para o futuro e uma dica de visão de longo prazo para o investidor ou chefe de família comum.
        
        ATENÇÃO: Use obrigatoriamente a quebra de linha '\\n\\n' para separar cada parágrafo.
        
        Retorne APENAS um objeto JSON válido, seguindo estritamente este formato (NÃO adicione a marcação ```json):
        {{
            "titulo_viral": "Crie um título curto, muito chamativo e com tom de artigo de opinião jornalístico",
            "resumo_simples": "Escreva aqui o seu artigo completo de 4 parágrafos, formatado com \\n\\n entre eles.",
            "impacto_bolso": "Explique em 2 frases diretas como isso afeta o poder de compra, investimentos ou finanças das famílias.",
            "tag": "Escolha UMA: Cripto, Economia, Dólar, Ações",
            "sentimento": "Escolha UM: Positivo, Negativo ou Neutro"
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