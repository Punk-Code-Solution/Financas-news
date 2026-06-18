from google import genai
from google.genai import types
import feedparser
import os
from bs4 import BeautifulSoup
from datetime import datetime
import json
from dotenv import load_dotenv
import requests

from db import get_editorial_context

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("❌ ERRO CRÍTICO: Chave API não encontrada no .env")
    client = None
else:
    client = genai.Client(api_key=api_key)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

RSS_FEEDS = [
    {
        "url": "https://br.cointelegraph.com/rss",
        "fonte": "Cointelegraph Brasil",
        "tag_hint": "Cripto",
    },
    {
        "url": "https://g1.globo.com/dynamo/economia/rss2.xml",
        "fonte": "G1 Economia",
        "tag_hint": "Economia",
    },
    {
        "url": "https://www.infomoney.com.br/feed/",
        "fonte": "InfoMoney",
        "tag_hint": "Economia",
    },
    {
        "url": "https://br.investing.com/rss/news.rss",
        "fonte": "Investing.com Brasil",
        "tag_hint": "Ações",
    },
    {
        "url": "https://exame.com/feed/",
        "fonte": "Exame",
        "tag_hint": "Economia",
    },
]

BCB_SERIES = {
    "selic_meta": 432,
    "ipca_12m": 13522,
    "dolar_comercial": 1,
}


def clean_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator=" ").strip()


def _format_pct(value):
    try:
        pct = float(value)
        return f"+{pct:.2f}%" if pct >= 0 else f"{pct:.2f}%"
    except (TypeError, ValueError):
        return "n/d"


def _format_brl(value):
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def fetch_market_snapshot():
    """Cotações em tempo real via AwesomeAPI."""
    snapshot = {"coletado_em": datetime.now().strftime("%d/%m/%Y %H:%M")}
    try:
        res = requests.get(
            "https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL",
            headers=HEADERS,
            timeout=10,
        )
        if res.status_code == 200:
            data = res.json()
            for key, label in [("USDBRL", "Dólar (USD/BRL)"), ("EURBRL", "Euro (EUR/BRL)"), ("BTCBRL", "Bitcoin (BTC/BRL)")]:
                if key in data:
                    item = data[key]
                    snapshot[label] = {
                        "cotacao": _format_brl(item.get("bid")),
                        "variacao_24h": _format_pct(item.get("pctChange")),
                        "maxima": _format_brl(item.get("high")),
                        "minima": _format_brl(item.get("low")),
                    }
    except Exception as e:
        snapshot["erro_cotacoes"] = str(e)
    return snapshot


def fetch_bcb_snapshot():
    """Indicadores macro do Banco Central do Brasil."""
    snapshot = {}
    labels = {
        "selic_meta": "Selic meta (% a.a.)",
        "ipca_12m": "IPCA acumulado 12 meses (%)",
        "dolar_comercial": "Dólar comercial (R$/US$)",
    }
    for key, series_id in BCB_SERIES.items():
        try:
            url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_id}/dados/ultimos/1?formato=json"
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                dados = res.json()
                if dados:
                    snapshot[labels[key]] = {
                        "valor": dados[0].get("valor"),
                        "data": dados[0].get("data"),
                    }
        except Exception:
            continue
    return snapshot


def format_data_context(market, bcb, db_context):
    """Monta bloco de dados para injetar no prompt da IA."""
    lines = [
        "=== DADOS DE MERCADO EM TEMPO REAL (cite números específicos na análise) ===",
        f"Coletado em: {market.get('coletado_em', 'agora')}",
    ]
    for key, val in market.items():
        if key in ("coletado_em", "erro_cotacoes"):
            continue
        if isinstance(val, dict):
            lines.append(
                f"- {key}: {val.get('cotacao')} (var. 24h: {val.get('variacao_24h')}, "
                f"máx: {val.get('maxima')}, mín: {val.get('minima')})"
            )

    if bcb:
        lines.append("\n=== INDICADORES MACROECONÔMICOS (Banco Central do Brasil) ===")
        for key, val in bcb.items():
            lines.append(f"- {key}: {val.get('valor')} (ref. {val.get('data')})")

    lines.append("\n=== ACERVO EDITORIAL DO PORTAL (cruze tendências, evite repetir) ===")
    lines.append(db_context)

    return "\n".join(lines)


def process_news_with_ai(title, content, fonte, tag_hint, market_context):
    if not client:
        return None

    print(f"   🤖 Enviando para IA: {title[:40]}...")

    prompt = f"""
Você é o editor-chefe de análise do portal "Finanças News" (financas-news.net.br), especializado em economia brasileira, mercado de capitais e criptoativos.

Sua missão é produzir uma ANÁLISE EDITORIAL ORIGINAL de alto valor — não um resumo, não uma paráfrase da notícia fonte. O Google e leitores exigem conteúdo com dados concretos, contexto histórico e utilidade prática.

## REGRAS INEGOCIÁVEIS
- PROIBIDO: resumir a notícia, usar "segundo a matéria", "o texto relata", "conforme publicado".
- OBRIGATÓRIO: citar pelo menos 3 números reais dos DADOS DE MERCADO fornecidos abaixo (cotações, variações, Selic, IPCA).
- OBRIGATÓRIO: conectar o fato da notícia com o cenário macro brasileiro (inflação, juros, câmbio, bolsa).
- OBRIGATÓRIO: cruzar com o ACERVO EDITORIAL — mencione se há tendência (ex.: "terceira notícia negativa sobre X esta semana").
- OBRIGATÓRIO: dar orientação prática para o leitor comum (investidor iniciante ou chefe de família).
- Mínimo de 500 palavras no campo resumo_simples.
- Tom: jornalístico, analítico, acessível. Você domina tecnologia e finanças, com visão de livre mercado e empreendedorismo.

## NOTÍCIA FONTE
Fonte RSS: {fonte}
Categoria sugerida: {tag_hint}
Título original: {title}
Conteúdo base (use como ponto de partida, não como texto a reescrever):
{content[:2500]}

## DADOS PARA CRUZAMENTO (use estes números na análise)
{market_context}

## ESTRUTURA DO ARTIGO (campo resumo_simples — 6 parágrafos separados por \\n\\n)
1. **Abertura**: O fato em uma frase forte + por que importa AGORA para o brasileiro.
2. **Contexto com dados**: Selic, IPCA, câmbio ou cripto — números reais dos dados fornecidos.
3. **Cruzamento de fontes**: Relacione com tendências do acervo editorial do portal.
4. **Análise aprofundada**: Causas, atores do mercado, riscos e oportunidades. Opinião embasada.
5. **Cenários**: O que pode acontecer em 30, 90 e 180 dias (seja específico).
6. **Guia prático**: 2-3 ações concretas para o leitor (diversificar, cautela, oportunidade, etc.).

Retorne APENAS JSON válido (sem ```json):
{{
    "titulo_viral": "Título jornalístico, informativo e específico (máx. 90 caracteres). Evite clickbait vazio.",
    "resumo_simples": "Artigo completo de 6 parágrafos com \\n\\n entre eles. Mínimo 500 palavras.",
    "contexto_mercado": "Box de 3-4 frases com os principais números citados (cotações, Selic, IPCA) formatados para leitura rápida.",
    "impacto_bolso": "3 frases diretas: impacto no bolso, na poupança/investimentos e no custo de vida.",
    "tag": "UMA de: Cripto, Economia, Dólar, Ações",
    "sentimento": "UM de: Positivo, Negativo, Neutro",
    "dados_citados": ["lista dos dados numéricos que você efetivamente usou no texto"]
}}
"""

    try:
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.7,
            ),
        )
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"   ❌ Erro na IA: {e}")
        return None


def fetch_and_process(max_per_feed=2):
    noticias_processadas = []
    print(f"\n--- Iniciando Varredura: {datetime.now()} ---")

    market = fetch_market_snapshot()
    bcb = fetch_bcb_snapshot()
    print(f"   📊 Dados de mercado coletados: {len(market)} cotações, {len(bcb)} indicadores BCB")

    for feed_config in RSS_FEEDS:
        feed_url = feed_config["url"]
        fonte = feed_config["fonte"]
        tag_hint = feed_config["tag_hint"]

        print(f"🔍 Acessando: {fonte} ({feed_url})")
        try:
            response = requests.get(feed_url, headers=HEADERS, timeout=15)
            if response.status_code != 200:
                print(f"   ❌ Erro HTTP {response.status_code}")
                continue

            feed = feedparser.parse(response.content)
            if not feed.entries:
                print("   ⚠️ Feed vazio.")
                continue

            db_context = get_editorial_context(tag_hint=tag_hint)
            data_context = format_data_context(market, bcb, db_context)

            for entry in feed.entries[:max_per_feed]:
                print(f"   📄 Encontrada: {entry.title[:60]}...")

                raw_content = entry.get("summary", "") or entry.get("content", [{"value": ""}])[0]["value"]
                clean_text = clean_html(raw_content)

                if len(clean_text) < 80:
                    print("   ⚠️ Texto muito curto, pulando.")
                    continue

                ai_data = process_news_with_ai(entry.title, clean_text, fonte, tag_hint, data_context)

                if ai_data:
                    published = datetime.now().strftime("%d/%m/%Y %H:%M")
                    news_item = {
                        "original_link": entry.link,
                        "fonte": fonte,
                        "published_at": published,
                        "dados_mercado": json.dumps(
                            {"cotacoes": market, "bcb": bcb, "dados_citados": ai_data.get("dados_citados", [])},
                            ensure_ascii=False,
                        ),
                        "contexto_editorial": ai_data.get("contexto_mercado", ""),
                        **ai_data,
                    }
                    noticias_processadas.append(news_item)
                    print("   ✅ Processado com sucesso!")

        except Exception as e:
            print(f"   ❌ Erro Crítico: {e}")

    return noticias_processadas


if __name__ == "__main__":
    print("🚀 Modo de Teste Manual Iniciado...")
    resultado = fetch_and_process(max_per_feed=1)
    print(f"\n📊 Total processado: {len(resultado)}")
    if resultado:
        print("🎉 SUCESSO! JSON gerado:")
        print(json.dumps(resultado[0], indent=2, ensure_ascii=False))