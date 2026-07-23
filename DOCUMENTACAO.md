# Finanças News — Documentação do Projeto

**Portal:** [financas-news.net.br](https://financas-news.net.br)  
**Desenvolvedor:** Punk Code Solution  
**Repositório:** [github.com/Punk-Code-Solution/Financas-news](https://github.com/Punk-Code-Solution/Financas-news)  
**Versão do documento:** junho/2026

---

## 1. Resumo executivo

O **Finanças News** é um portal de notícias financeiras **100% automatizado** que transforma matérias de veículos consolidados em **análises editoriais originais**, enriquecidas com dados de mercado em tempo real e indicadores do Banco Central do Brasil.

O diferencial não é republicar RSS — é produzir conteúdo com **contexto macroeconômico**, **cruzamento de fontes**, **orientação prática ao leitor** e **imagem editorial gerada por IA**, posicionando o portal como mídia de análise, não agregador genérico.

### Proposta de valor

| Para o leitor | Para o negócio |
|---------------|----------------|
| Análises em português, acessíveis e com dados reais | Custo operacional baixo (automação) |
| Impacto direto no bolso de cada matéria | Múltiplas fontes de receita configuráveis |
| 10 categorias do mercado financeiro BR | Escalável sem equipe editorial grande |
| Cotações ao vivo no ticker | SEO e indexação automática |

---

## 2. Como funciona (pipeline automatizado)

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Feeds RSS (~30)│────▶│  Motor core.py   │────▶│  Banco Turso    │
│  G1, InfoMoney… │     │  + Google Gemini │     │  (nuvem)        │
└─────────────────┘     └────────┬─────────┘     └────────┬────────┘
                                 │                         │
                    ┌────────────┼────────────┐            │
                    ▼            ▼            ▼            ▼
              AwesomeAPI    Banco Central   Histórico   Site FastAPI
              (câmbio)      (Selic, IPCA)   editorial   + templates
                    │            │            │            │
                    └────────────┴────────────┴────────────┘
                                 │
                                 ▼
                    Análise JSON + imagem de capa
                                 │
                                 ▼
                         Publicação no portal
```

### Etapas de cada execução do robô

1. **Coleta de dados de mercado** — USD, EUR, BTC (AwesomeAPI) + Selic, IPCA e dólar comercial (API BCB).
2. **Leitura de ~30 feeds RSS** (BR + internacionais) — até 3 notícias/fonte, teto 36/rodada (`ROBOT_MAX_PER_FEED` / `ROBOT_MAX_ARTICLES`).
3. **Dedupe por link** antes da IA (economiza cota).
4. **Contexto editorial** — cruza com o acervo do portal.
5. **Geração de texto** — Gemini nas chaves 1→2→3 (análise 500+ palavras / JSON).
6. **Geração de imagem** — Gemini na varredura; fallback OpenAI/DALL-E no backfill (1/min); lote ordena com capa primeiro.
7. **Publicação** — grava no Turso e exibe no frontend.

### Acionamento

O robô é disparado via HTTP (cron externo, Render Cron Job ou chamada manual):

```
GET /api/rodar-robo
Authorization: Bearer SEU_ROBO_TOKEN
```

(Query `?token=` ainda funciona para cron; preferir header quando possível.)

---

## 3. Stack tecnológica

| Camada | Tecnologia |
|--------|------------|
| Backend | Python 3.13, FastAPI, Uvicorn |
| Frontend | Jinja2, Tailwind CSS (build estático), JavaScript |
| Banco de dados | Turso (libSQL — SQLite distribuído) |
| Inteligência artificial | Google Gemini (texto + imagem) |
| Hospedagem | Render.com (web service + disco persistente) |
| Dados externos | AwesomeAPI, Banco Central do Brasil, RSS |

### Estrutura de arquivos

```
financas_auto/
├── main.py              # App web, rotas, API do robô, SEO
├── core.py              # Pipeline RSS → IA → imagem
├── db.py                # Conexão Turso, schema, FTS5, contexto editorial
├── monetization.py      # Configuração de receita (env-driven)
├── templates/           # Páginas HTML e partials de monetização
├── static/              # Favicon, CSS buildado (app.css) e assets
├── src/styles.css       # Entrada do Tailwind
├── tailwind.config.js   # Conteúdo/templates para purge
├── tools/build-css.js   # Build via CLI standalone
├── requirements.txt     # Dependências Python
├── render.yaml          # Deploy no Render
└── runtime.txt          # Versão Python fixada
```

Para regenerar o CSS após mudar classes nos templates: baixe o [CLI standalone do Tailwind](https://github.com/tailwindlabs/tailwindcss/releases) para `tools/tailwindcss.exe` e rode `npm run build:css` (o arquivo `static/css/app.css` é versionado e usado em produção).

---

## 4. Conteúdo e categorias

### 10 categorias editoriais

Cripto · Economia · Dólar · Ações · Juros · Inflação · Imóveis · Fintech · Commodities · Política Econômica

### Fontes RSS monitoradas

**Brasil:** G1 Economia/Política, Valor, InfoMoney (geral/mercados/economia/investir), Exame, Money Times, NeoFeed, Investing BR/Commodities/Forex, CNN Brasil, Estadão, Folha Mercado, UOL Economia, Poder360, Agência Brasil, Livecoins, Cointelegraph Brasil.

**Internacional:** BBC Business, CNBC, Reuters Business, MarketWatch, Yahoo Finance, The Guardian Business, Investing.com World, CoinDesk, Cointelegraph.

### Formato de cada artigo publicado

- **Título** editorial gerado pela IA
- **Análise completa** (6 parágrafos: cada um amarrado a pelo menos 1 número citado)
- **Painel núcleo** — sempre Selic, IPCA 12 meses, dólar + 1–2 cotações da categoria, com data de coleta e tendência 7d/30d
- **Panorama de mercado** (box com números citados)
- **Impacto no bolso** (3 frases diretas)
- **Sentimento** (Positivo / Negativo / Neutro)
- **Imagem de capa** (quando a API de imagem responde) — OG/Twitter `summary_large_image` para Discover
- **Link para fonte original** (transparência editorial)
- **Data e veículo de origem**
- **Guias núcleo** (`/artigo/selic|ipca|cambio|renda-fixa`) — conjunto fechado; números BCB sincronizados no startup

---

## 5. Modelo de monetização

A monetização é **modular e controlada por variáveis de ambiente**. Enquanto não configuradas, **nenhum bloco publicitário é exibido** — o site mostra apenas conteúdo editorial.

| Canal | Variável de ambiente | Como recebe |
|-------|---------------------|-------------|
| Google AdSense | `GOOGLE_ADSENSE_CLIENT` | CPC/CPM via Google (mín. ~US$ 100) |
| Afiliado Binance | `AFFILIATE_BINANCE_URL` | Comissão por cadastro/operação |
| Afiliado XP | `AFFILIATE_XP_URL` | Comissão por conta aberta |
| Mercado Bitcoin | `AFFILIATE_MERCADO_BITCOIN_URL` | Comissão por indicação |
| BTG Pactual | `AFFILIATE_BTG_URL` | Comissão por indicação |
| Amazon Associados | `AMAZON_AFFILIATE_TAG` | % sobre compras |
| Patrocínio direto | `SPONSORED_SLOT_URL` | Pagamento direto do anunciante |
| Newsletter | `NEWSLETTER_URL` ou `NEWSLETTER_ENABLED` | Base para produto premium futuro |
| Premium (futuro) | `PREMIUM_TEASER_ENABLED=true` | Assinatura / relatórios pagos |

### Status atual da monetização

- **AdSense:** conta criada (`ca-pub-3623062544438213`), aguardando reaprovação por qualidade de conteúdo.
- **Afiliados:** estrutura pronta; links de rastreio pendentes de cadastro nos programas.
- **Amazon:** aguardando tag de associado.

---

## 6. Inteligência artificial

### Modelos de texto (com fallback automático)

Ordem padrão (configurável via `GEMINI_MODELOS`):

1. `gemini-3.1-flash-lite-preview` / `gemini-3.1-flash-lite` — ~500 req/dia
2. `gemini-3.5-flash-lite` — ~500 req/dia (útil na chave 2)
3. `gemini-2.5-flash-lite` / `gemini-2.5-flash` — fallback (~20/dia)
4. `gemini-3-flash` / `gemini-3.5-flash` — fallback (~20/dia)

O sistema **troca de modelo** quando a cota diária esgota e **só faz retry** em limite por minuto (RPM), evitando loops inúteis. Com `GOOGLE_API_KEY_2` / `GOOGLE_API_KEY_3`, esgota a chave atual e passa para a próxima.

### Modelos de imagem

Ordem atual (Gemini Image / Nano Banana):

1. `gemini-3.1-flash-lite-image` / `gemini-3.1-flash-image` / `gemini-2.5-flash-image`
2. `gemini-3.1-flash-image-preview` / `gemini-3-pro-image`
3. **Hugging Face** (fallback) — `black-forest-labs/FLUX.1-schnell` via Inference Providers (`HF_TOKEN`)
4. **OpenAI** (fallback no backfill) — `gpt-image-2` → `gpt-image-1.5` → `gpt-image-1` → `gpt-image-1-mini`

> **Nota:** Imagen 4 (`imagen-4.0-*`) retorna 404 para contas novas e foi removido da fila padrão. Com `HF_TOKEN` / `OPENAI_API_KEY` no Render, o backfill tenta Hugging Face e depois OpenAI quando o Gemini esgota.

### Prioridade de capas

1. ``IMAGE_PROVIDER`` define a ordem dos provedores (ex.: `gemini,huggingface,openai`).
2. Em cada provedor, percorre a fila de modelos (`GEMINI_IMAGE_MODELOS` / `HF_IMAGE_MODELOS` / `OPENAI_IMAGE_MODELOS`).
3. **Notícias novas** na varredura do robô usam a fila sem OpenAI (`use_openai=False`) para não travar no rate limit.
4. **Backfill** (`/api/gerar-imagens` ou pós-robô) usa a fila completa, `ORDER BY id DESC`.
5. Cron recomendado: `/api/gerar-imagens?limit=1` a cada **30 minutos** (~50 RPD OpenAI).

Imagens salvas em disco (`ARTICLE_IMAGES_DIR`) com URL pública `/media/articles/`.

### Custo estimado de API (free tier)

| Recurso | Consumo por artigo | Limite free (referência) |
|---------|-------------------|--------------------------|
| Texto | 1 requisição | 500/dia (3.1 Flash Lite) |
| Imagem | 1 requisição | conforme cota do modelo |
| **Total por rodada (~28 artigos)** | ~56 chamadas | monitorar no painel Google AI |

> **Atenção:** cotas somam por projeto Google Cloud / AI Studio. Use `GOOGLE_API_KEY_2` e `GOOGLE_API_KEY_3` (outros projetos/contas) para fallback de texto/imagem quando a chave anterior esgotar.

---

## 7. Infraestrutura e custos

### Render.com

| Item | Configuração |
|------|-------------|
| Serviço | Web service Python |
| Runtime | Python 3.13.7 |
| Disco persistente | 1 GB em `/var/data` (imagens de artigos) |
| Health check | `GET /ping` |

### Turso (banco)

- SQLite distribuído na nuvem
- Sem servidor para gerenciar
- Plano gratuito generoso para o volume atual

### Custos mensais estimados

| Serviço | Custo |
|---------|-------|
| Render (starter) | ~US$ 7/mês |
| Turso | Gratuito (tier inicial) |
| Google Gemini API | Gratuito (free tier) |
| Domínio | ~R$ 40/ano |
| **Total operacional** | **~US$ 7–15/mês** |

---

## 8. Banco de dados

### Tabela `news`

| Coluna | Descrição |
|--------|-----------|
| `id` | Identificador único |
| `titulo` | Título editorial (IA) |
| `resumo` | Análise completa |
| `impacto` | Impacto no bolso |
| `link` | URL original (deduplicação) |
| `tag` | Categoria |
| `sentimento` | Positivo / Negativo / Neutro |
| `published_at` | Data de publicação |
| `fonte` | Veículo RSS de origem |
| `dados_mercado` | JSON com cotações e indicadores usados |
| `contexto_editorial` | Box de panorama de mercado |
| `imagem_url` | Caminho da capa gerada |
| `created_at` | Timestamp de criação |

### Tabela `newsletter_subscribers`

Armazena e-mails capturados localmente quando a newsletter está ativa.

---

## 9. Rotas e endpoints

### Páginas públicas

| Rota | Função |
|------|--------|
| `/` | Home com listagem, filtros e busca (FTS5 em título/resumo; combina `q` + `categoria`) |
| `/noticia/{id}` | Artigo completo |
| `/quem-somos` | Sobre o portal |
| `/privacidade` | Política de privacidade |
| `/termos` | Termos de uso |

### SEO

| Rota | Função |
|------|--------|
| `/sitemap.xml` | Home, institucionais, guias `/artigo/*` e até 500 notícias (`lastmod`, sem duplicar guias) |
| `/robots.txt` | Allow público; `Disallow` em `/api/` e `/ping`; aponta sitemap |
| `/ads.txt` | Verificação Google AdSense |

Sinais on-page: `rel=canonical`, meta description, JSON-LD (`WebSite` na home, `NewsArticle` + `FAQPage` nos artigos), OG/Twitter, guias no rodapé e redirect 301 de `/noticia/{id}` → `/artigo/{slug}` quando for guia evergreen.

### API interna

| Rota | Função |
|------|--------|
| `GET /api/rodar-robo` | Dispara pipeline (auth: Bearer / X-Robo-Token / ?token=) |
| `GET /api/gerar-imagens` | Backfill de capas (mesma auth) |
| `GET /api/atualizar-artigos` | Atualiza dados de mercado (mesma auth) |
| `POST /api/newsletter` | Captura de e-mail |
| `GET /ping` | Health check |

---

## 10. Variáveis de ambiente

### Obrigatórias (produção)

```env
GOOGLE_API_KEY=           # ou GEMINI_API_KEY (chave 1)
GOOGLE_API_KEY_2=         # opcional: segunda chave (fallback de cota)
GOOGLE_API_KEY_3=         # opcional: terceira chave (fallback de cota)
ROBO_TOKEN=               # obrigatório: /api/rodar-robo, /api/gerar-imagens, /api/atualizar-artigos
ROBOT_MAX_PER_FEED=3
ROBOT_MAX_ARTICLES=36
# GOOGLE_API_KEYS=key1,key2,key3   # alternativa: lista de chaves
TURSO_DATABASE_URL=       # URL libsql:// do Turso
TURSO_AUTH_TOKEN=         # Token de autenticação Turso
```

### Autenticação das rotas do robô

`ROBO_TOKEN` vem só do ambiente (nunca hardcoded). Ordem de leitura do segredo na request:

1. `Authorization: Bearer <token>` (preferencial)
2. `X-Robo-Token: <token>`
3. Query `?token=` (cron; evita expor em docs públicas)

Sem env → HTTP 503. Ausente/errado → HTTP 401 (comparação com `hmac.compare_digest`).

### IA (opcionais)

```env
GEMINI_MODELOS=gemini-3.1-flash-lite-preview,gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-2.5-flash-lite,gemini-2.5-flash,gemini-3-flash,gemini-3.5-flash
GEMINI_IMAGE_MODELOS=gemini-3.1-flash-lite-image,gemini-3.1-flash-image,gemini-2.5-flash-image,gemini-3.1-flash-image-preview,gemini-3-pro-image
# Produção (Render): gemini (+ Hugging Face + OpenAI no backfill). Local: gemini | huggingface | openai | cursor | auto.
# Um ou vários provedores (ordem = prioridade). Ex.: gemini,huggingface,openai | openai,gemini | auto
IMAGE_PROVIDER=gemini,huggingface,openai
HF_TOKEN=
HF_IMAGE_MODELOS=black-forest-labs/FLUX.1-schnell
OPENAI_API_KEY=
OPENAI_IMAGE_MODELOS=gpt-image-2,gpt-image-1.5,gpt-image-1,gpt-image-1-mini
OPENAI_IMAGE_MIN_INTERVAL=65
ARTICLE_IMAGES_DIR=/var/data/article_images
```

> No Render, use `IMAGE_PROVIDER=gemini,huggingface,openai`. Cole `HF_TOKEN` e `ROBO_TOKEN` no painel (`sync: false`). `auto`/`cursor` no Render ignoram Cursor. Cada provedor percorre a própria fila (`GEMINI_IMAGE_MODELOS` / `HF_IMAGE_MODELOS` / `OPENAI_IMAGE_MODELOS`).
### Monetização (opcionais — só exibe se preenchidas)

```env
GOOGLE_ADSENSE_CLIENT=ca-pub-3623062544438213
ADSENSE_AD_SLOT=XXXXXXXX
ADSENSE_FLUID_SLOT=5920613886
ADSENSE_FLUID_LAYOUT_KEY=-gp+18-5a-gr+1eg
ADSENSE_FLUID2_SLOT=5003238179
ADSENSE_FLUID2_LAYOUT_KEY=-fd-l+6i-lx+n1
ADSENSE_IN_ARTICLE_SLOT=3294450543
ADSENSE_SIDEBAR_SLOT=1019761130
ADSENSE_AUTORELAXED_SLOT=2568646523
AFFILIATE_BINANCE_URL=
AFFILIATE_XP_URL=
AFFILIATE_MERCADO_BITCOIN_URL=
AFFILIATE_BTG_URL=
AMAZON_AFFILIATE_TAG=
SPONSORED_SLOT_URL=
NEWSLETTER_URL=
NEWSLETTER_ENABLED=false
PREMIUM_TEASER_ENABLED=false
```

---

## 11. Operação do dia a dia

### Publicar notícias

Agendar chamada ao robô a cada 2–3 horas (cron no Render ou cron-job.org):

```
https://financas-news.net.br/api/rodar-robo?token=SEU_ROBO_TOKEN
```

Preferencial (menos vazamento em logs): header `Authorization: Bearer SEU_ROBO_TOKEN`.  
Variáveis úteis: `ROBO_TOKEN`, `ROBOT_MAX_PER_FEED=3`, `ROBOT_MAX_ARTICLES=36`, `GOOGLE_API_KEY` / `_2` / `_3`.

Se não houver notícias novas, o robô gera **1 capa** para o artigo pendente mais recente (senão, antigos sem capa).

### Capas (backfill contínuo)

Com Hugging Face / OpenAI e limite de 1 imagem por execução, agendar a cada **30 minutos**:

```
https://financas-news.net.br/api/gerar-imagens?token=SEU_ROBO_TOKEN&limit=1
```

A fila prioriza `id DESC` (notícias novas sem capa primeiro).

### Limpar acervo (após mudança de prompt)

```bash
python limpar_banco.py
```

### Rodar localmente

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
# Criar .env com as variáveis
uvicorn main:app --reload
```

---

## 12. Roadmap sugerido

### Curto prazo (0–30 dias)

- [x] Mover token do robô para variável de ambiente (`ROBO_TOKEN`)
- [ ] Agendar robô automaticamente no Render
- [ ] Reaplicar ao Google AdSense com acervo de 30+ análises de qualidade
- [ ] Cadastrar programas de afiliados (Binance, Amazon)

### Médio prazo (1–3 meses)

- [ ] Newsletter ativa (Beehiiv ou Mailchimp)
- [ ] Relatório semanal premium (assinatura)
- [ ] Métricas de tráfego (Google Analytics / Plausible)
- [ ] Painel admin para revisar artigos antes de publicar

### Longo prazo (3–6 meses)

- [ ] App ou bot Telegram com alertas personalizados
- [ ] API pública de cotações e análises
- [ ] Parcerias com corretoras para conteúdo patrocinado
- [ ] Expansão para mercado latino-americano

---

## 13. Riscos e mitigações

| Risco | Mitigação |
|-------|-----------|
| Google rejeitar AdSense (conteúdo IA) | Análises longas com dados reais; transparência; acervo robusto |
| Cota Gemini esgotada | Fallback de modelos; modelos lite (500 RPD); chaves separadas por projeto |
| Feed RSS fora do ar | ~30 fontes redundantes (BR + intl); logs por feed |
| Conteúdo duplicado | Deduplicação por URL + contexto editorial no prompt |
| Dependência de API Google | Arquitetura permite trocar provedor de IA |

---

## 14. Métricas de sucesso (KPIs sugeridos)

| KPI | Meta inicial (90 dias) |
|-----|------------------------|
| Artigos publicados | 200+ |
| Visitas/mês | 5.000+ |
| Tempo médio na página | > 2 min |
| Inscritos newsletter | 500+ |
| Receita AdSense + afiliados | > custo operacional |

---

## 15. Contato e propriedade

**Finanças News** é um projeto da **Punk Code Solution**.  
Liderança técnica: Thiago de Freitas Gonçalves.

- Site: [financas-news.net.br](https://financas-news.net.br)
- Empresa: [punkcodesolution.com.br](https://www.punkcodesolution.com.br)

---

*Documento gerado para apresentação a sócios e investidores. Para detalhes técnicos de implementação, consulte o código-fonte nos módulos `core.py`, `main.py`, `db.py` e `monetization.py`.*
