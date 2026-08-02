# Finanças News — Documentação do Projeto

**Portal:** [financas-news.net.br](https://financas-news.net.br)  
**Desenvolvedor:** Punk Code Solution  
**Repositório:** [github.com/Punk-Code-Solution/Financas-news](https://github.com/Punk-Code-Solution/Financas-news)  
**Versão do documento:** agosto/2026

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
2. **Análises próprias (cota reservada)** — gera pelo menos `ROBOT_OWN_ANALYSES` (default 3) matérias autorais a partir do acervo do banco (`internal://analise/...`), antes do RSS, para não perder a cota Gemini.
3. **Leitura de ~30 feeds RSS** (BR + internacionais) — até 3 notícias/fonte, teto 36/rodada (`ROBOT_MAX_PER_FEED` / `ROBOT_MAX_ARTICLES`), com teto reduzido pelo que ainda falta da meta própria.
4. **Dedupe por link** antes da IA (economiza cota).
5. **Contexto editorial** — cruza com o acervo do portal.
6. **Geração de texto** — Gemini nas chaves 1→2→3 (análise 500+ palavras / JSON).
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
├── main.py                 # App web, rotas, API do robô, SEO, CSP
├── core.py                 # Pipeline RSS → IA → imagem, radar, macro-watch, i18n IA
├── db.py                   # Conexão Turso, schema, FTS5, contexto editorial
├── monetization.py         # Receita + afiliados contextuais (env-driven)
├── newsletter_service.py   # Digest semanal e alertas de urgência
├── article_enrichment.py   # Relacionados, entidades, painéis do artigo
├── educational_guides.py   # Guias evergreen (Selic, IPCA, câmbio, renda fixa)
├── i18n.py                 # PT/EN/JA, intros de categoria, canônicas
├── templates/              # Páginas HTML e partials (incl. mercado, afiliado)
├── static/                 # Favicon, CSS buildado (app.css) e assets
├── src/styles.css          # Entrada do Tailwind
├── tailwind.config.js      # Conteúdo/templates para purge
├── tools/build-css.js      # Build via CLI standalone
├── requirements.txt        # Dependências Python
├── render.yaml             # Deploy no Render
└── runtime.txt             # Versão Python fixada
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
- **Tempo de leitura** estimado no artigo (`estimate_reading_minutes`)
- **Matérias relacionadas** e temas cruzados (`article_enrichment.py`)
- **Afiliado contextual** por categoria (só se a URL do programa estiver no env)

### Enriquecimento do portal (ONDAs 1–3)

Entregas recentes que expandem retenção, distribuição e operação editorial:

| Onda | Entrega | Onde |
|------|---------|------|
| 1 | Intro de categoria + guias relacionados na home filtrada; feed RSS/Atom; newsletter digest/alerta | `i18n.py`, `/`, `/feed.xml`, `/feed.atom`, `newsletter_service.py` |
| 2 | Painel `/mercado` (Selic, IPCA, USD, BTC + charts); tempo de leitura e relacionados no artigo; afiliados contextuais | `mercado.html`, `noticia.html`, `monetization.py` |
| 3 | Radar da semana; Macro Watch (matéria se Selic/IPCA mudar); tradução pendente EN/JA; CSP + headers de segurança | `/api/radar-semanal`, `/api/macro-watch`, `/api/traduzir-pendentes`, middleware em `main.py` |

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
| Newsletter (captura) | `NEWSLETTER_URL` ou `NEWSLETTER_ENABLED` | Formulário local ou redirect externo |
| Newsletter (envio) | `RESEND_API_KEY` / SMTP / `NEWSLETTER_WEBHOOK_URL` | Digest semanal e alertas de urgência |
| Premium (futuro) | `PREMIUM_TEASER_ENABLED=true` | Assinatura / relatórios pagos |

### Afiliados contextuais

Na página do artigo, o bloco de afiliado escolhe o programa conforme a **tag** da matéria (ex.: Cripto → Binance; Juros/Inflação → BTG; padrão → XP). Só aparece se a URL correspondente estiver configurada — copy e CTA mudam por categoria (`get_contextual_affiliate` em `monetization.py`).

### Status atual da monetização

- **AdSense:** conta criada (`ca-pub-3623062544438213`), aguardando reaprovação por qualidade de conteúdo.
- **Afiliados:** estrutura + mapeamento contextual prontos; links de rastreio pendentes de cadastro nos programas.
- **Amazon:** aguardando tag de associado.
- **Newsletter:** captura local/externa pronta; envio (digest/alerta) exige provedor configurado (Resend, SMTP ou webhook).

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

Ordem recomendada (híbrido stock + IA):

0. **Pexels** (stock gratuito) — foto landscape relacionada ao título/tag (`PEXELS_API_KEY`)
1. `gemini-3.1-flash-lite-image` / `gemini-3.1-flash-image` / `gemini-2.5-flash-image`
2. `gemini-3.1-flash-image-preview` / `gemini-3-pro-image`
3. **Hugging Face** (fallback) — `black-forest-labs/FLUX.1-schnell` via Inference Providers (`HF_TOKEN`)
4. **OpenAI** (fallback no backfill) — `gpt-image-2` → `gpt-image-1.5` → `gpt-image-1` → `gpt-image-1-mini`

> **Nota:** Imagen 4 (`imagen-4.0-*`) retorna 404 para contas novas e foi removido da fila padrão. Com `PEXELS_API_KEY` / `HF_TOKEN` / `OPENAI_API_KEY` no Render, o backfill tenta stock e depois IA.

### Prioridade de capas

1. ``IMAGE_PROVIDER`` define a ordem dos provedores (ex.: `pexels,gemini,huggingface,openai`).
2. Em cada provedor de IA, percorre a fila de modelos (`GEMINI_IMAGE_MODELOS` / `HF_IMAGE_MODELOS` / `OPENAI_IMAGE_MODELOS`).
3. **Notícias novas** na varredura do robô usam a fila sem OpenAI (`use_openai=False`) — Pexels/Gemini/HF ainda entram.
4. **Backfill** (`/api/gerar-imagens` ou pós-robô) usa a fila completa, prioriza IDs novos sem capa (varredura profunda).
5. Cron recomendado: `/api/gerar-imagens?limit=5` a cada **15–30 minutos** (stock é rápido; OpenAI ainda ~1/min se cair no fallback).

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
| `home_priority` | Prioridade na manchete da home (urgência) |
| `titulo_en` / `resumo_en` | Tradução EN (quando preenchida) |
| `titulo_ja` / `resumo_ja` | Tradução JA (quando preenchida) |
| `created_at` | Timestamp de criação |
| `updated_at` | Última atualização |

### Tabela `newsletter_subscribers`

Armazena e-mails capturados localmente quando a newsletter está ativa.

### Tabela `newsletter_alert_log`

Evita reenvio duplicado de alerta de urgência por `news_id`.

### Tabela `macro_watch_state`

Snapshot anterior de indicadores macro (Selic, IPCA) para detectar mudanças e gerar matéria.

---

## 9. Rotas e endpoints

### Páginas públicas

| Rota | Função |
|------|--------|
| `/` | Home com listagem, filtros e busca (FTS5 em título/resumo; combina `q` + `categoria`). Com `?categoria=` exibe intro editorial e guias relacionados |
| `/noticia/{id}` | Artigo completo (tempo de leitura, relacionados, afiliado contextual) |
| `/artigo/{slug}` | Guias evergreen (selic, ipca, cambio, renda-fixa) |
| `/mercado` | Painel público: Selic, IPCA, dólar, BTC + histórico + links para análises |
| `/metodologia` | Transparência editorial (não republicação RSS) |
| `/quem-somos` | Sobre o portal |
| `/login` `/cadastro` `/perfil` | Comunidade (sessão cookie; noindex) |
| `/privacidade` | Política de privacidade |
| `/termos` | Termos de uso |

### SEO e distribuição

| Rota | Função |
|------|--------|
| `/sitemap.xml` | Home, institucionais, guias `/artigo/*` e até 500 notícias (`lastmod`, sem duplicar guias) |
| `/robots.txt` | Allow público; `Disallow` em `/api/`, `/ping`, `?q=` e `?page=`; aponta sitemap e feed |
| `/feed.xml` | Feed RSS 2.0 das notícias recentes |
| `/feed.atom` | Feed Atom equivalente |
| `/ads.txt` | Verificação Google AdSense |

Sinais on-page: `rel=canonical`, meta description, JSON-LD (`WebSite` na home, `NewsArticle` + `FAQPage` nos artigos), OG/Twitter, guias no rodapé e redirect 301 de `/noticia/{id}` → `/artigo/{slug}` quando for guia evergreen.

### Segurança HTTP (middleware)

Todas as respostas recebem:

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-Frame-Options: SAMEORIGIN`
- `Content-Security-Policy` (self + AdSense, Google Fonts, Chart.js CDN, analytics; `script-src`/`style-src` com `'unsafe-inline'` por scripts do portal)
- `Strict-Transport-Security` quando a request é HTTPS

### API interna

| Rota | Função |
|------|--------|
| `GET /api/rodar-robo` | Dispara pipeline (auth: Bearer / X-Robo-Token / ?token=) |
| `GET /api/gerar-analises-proprias` | Gera análises próprias a partir do acervo (mesma auth; meta diária `ROBOT_OWN_ANALYSES`) |
| `GET /api/gerar-imagens` | Backfill de capas (mesma auth) |
| `GET /api/atualizar-artigos` | Atualiza dados de mercado (mesma auth) |
| `GET /api/radar-semanal` | Gera o Radar da semana (análise própria do acervo; `force=1` regenera) |
| `GET /api/macro-watch` | Compara Selic/IPCA com snapshot anterior; gera matéria se mudou |
| `GET /api/traduzir-pendentes` | Traduz título+resumo pendentes para EN/JA (`limit`, default 10) |
| `GET /api/newsletter-digest` | Envia digest semanal aos inscritos (exige provedor de envio) |
| `GET /api/newsletter-digest-diario` | Digest 2x/dia: manchete (`home_priority`) + links das demais |
| `GET /api/newsletter-alerta` | Reenvio manual de alerta de urgência (`news_id` obrigatório) |
| `POST /api/newsletter` | Captura de e-mail (local ou redirect externo) |
| `GET /ping` | Health check |

Auth das rotas de robô/newsletter de envio: mesma regra de `ROBO_TOKEN` (Bearer preferencial).

---

## 10. Variáveis de ambiente

### Obrigatórias (produção)

```env
GOOGLE_API_KEY=           # ou GEMINI_API_KEY (chave 1)
GOOGLE_API_KEY_2=         # opcional: segunda chave (fallback de cota)
GOOGLE_API_KEY_3=         # opcional: terceira chave (fallback de cota)
ROBO_TOKEN=               # obrigatório: rotas /api do robô, radar, macro-watch, traduzir, newsletter digest/alerta, capas
SESSION_SECRET=           # cookie de sessão da comunidade (httpOnly)
IP_HASH_SALT=             # salt para hash de IP em comentários (LGPD)
GOOGLE_OAUTH_CLIENT_ID=   # opcional: login Google
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URI=  # ex.: https://financas-news.net.br/auth/google/callback
# SESSION_HTTPS_ONLY=false  # local HTTP; em produção/Render cookies Secure
SITE_ORIGIN=https://financas-news.net.br  # obrigatório em produção: links de verificação (nunca 127.0.0.1)
# Verificação de conta também exige mailer: RESEND_API_KEY + NEWSLETTER_FROM (ou SMTP_*) — ver seção Newsletter
# EMAIL_VERIFY_TTL_HOURS=48
# EMAIL_VERIFY_RESEND_COOLDOWN_SEC=120
ROBOT_MAX_PER_FEED=3
ROBOT_MAX_ARTICLES=36
ROBOT_OWN_ANALYSES=3      # mínimo diário de análises próprias a partir do acervo (0=desliga)
# GOOGLE_API_KEYS=key1,key2,key3   # alternativa: lista de chaves
TURSO_DATABASE_URL=       # URL libsql:// do Turso
TURSO_AUTH_TOKEN=         # Token de autenticação Turso
```

### Newsletter 2x/dia (cron sugerido)

Agendar no Render (ou similar), com `Authorization: Bearer $ROBO_TOKEN`:

- Manhã (ex. 08:00 America/Sao_Paulo): `GET /api/newsletter-digest-diario`
- Tarde (ex. 17:00): `GET /api/newsletter-digest-diario`
- Semanal (opcional): `GET /api/newsletter-digest`

### Thin content

- Sitemap e `noindex` de artigo: resumo &lt; **800** caracteres.
- Ferramenta: `PYTHONPATH=. python tools/purge_thin_news.py` (default `--min-resumo 800`; `--apply` para apagar).

---

## 11b. Checklist — reconsideração Google (conteúdo de baixo valor / spam)

Use no Search Console ao pedir reconsideração. Evidências no código/site:

| Item | Situação | Onde |
|------|----------|------|
| Sem landings só-afiliado | OK — afiliado só em artigo editorial | `contextual_affiliate.html`, `monetization.get_contextual_affiliate` |
| Disclaimer afiliado + copy sóbrio | OK | partial + `DEFAULT_AFFILIATES` |
| Originalidade (dados BCB, lentes, impacto, tempo leitura) | OK / reforçado | enrichment + `/metodologia` + quem-somos |
| `/mercado` com valor (dados + links análises) | OK | `mercado.html` + sitemap |
| Thin fora do índice | OK — purge 800 = sitemap; noindex thin | `purge_thin_news.py`, `_render_noticia_page` |
| Doorways busca/paginação/conta | OK — noindex + robots Disallow | `robots.txt`, i18n canônica |
| Categorias vazias | OK — noindex | `index()` |
| Exemplos de qualidade | Análises com LENGTH(resumo)≥800, guias `/artigo/*`, painel `/mercado`, `/metodologia` | produção |

Texto sugerido (adaptar): *Corrigimos páginas afiliadas thin (afiliados só em contexto editorial), alinhamos limiar de conteúdo fino (800), reforçamos metodologia original com dados oficiais, enriquecemos /mercado, e bloqueamos indexação de busca/paginação/contas/thin.*

---

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
# Produção (Render): pexels (+ Gemini/HF/OpenAI). Local: pexels | gemini | huggingface | openai | cursor | auto.
# Um ou vários provedores (ordem = prioridade). Ex.: pexels,gemini,huggingface,openai | openai,gemini | auto
IMAGE_PROVIDER=pexels,gemini,huggingface,openai
PEXELS_API_KEY=
HF_TOKEN=
HF_IMAGE_MODELOS=black-forest-labs/FLUX.1-schnell
OPENAI_API_KEY=
OPENAI_IMAGE_MODELOS=gpt-image-2,gpt-image-1.5,gpt-image-1,gpt-image-1-mini
OPENAI_IMAGE_MIN_INTERVAL=65
ARTICLE_IMAGES_DIR=/var/data/article_images
```

> No Render, use `IMAGE_PROVIDER=pexels,gemini,huggingface,openai`. Cole `PEXELS_API_KEY`, `HF_TOKEN` e `ROBO_TOKEN` no painel (`sync: false`). Chave Pexels gratuita: https://www.pexels.com/api/. `auto`/`cursor` no Render ignoram Cursor.

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

### Newsletter — envio (obrigatório para verificação de conta)

Pelo menos um provedor precisa estar configurado para:
- e-mail de **verificação de conta** (cadastro / `POST /reenviar-verificacao`);
- `/api/newsletter-digest` e `/api/newsletter-alerta` (senão HTTP 503).

Sem provedor, o app **não finge** que enviou: log `[newsletter] mailer nao configurado` e a UI mostra erro honesto pedindo tentar mais tarde ou contatar o suporte.

Ordem de preferência no código: Resend → SMTP → webhook.

**Render (checklist verificação de e-mail):**

| Variável | Obrigatório? | Notas |
|----------|--------------|--------|
| `RESEND_API_KEY` | Sim (ou SMTP_*) | Preferencial — API Resend |
| `NEWSLETTER_FROM` | Sim com Resend | Remetente em domínio **verificado** no Resend (ex.: `newsletter@financas-news.net.br`) |
| `SITE_ORIGIN` | Sim em produção | Deve ser `https://financas-news.net.br` (links do e-mail de verificação). Não use `127.0.0.1`. |
| `SMTP_HOST` + `SMTP_FROM` (+ user/pass) | Alternativa | Se não usar Resend |
| `NEWSLETTER_WEBHOOK_URL` | Alternativa | POST JSON `{subject,html,text,to,from}` |

```env
SITE_ORIGIN=https://financas-news.net.br
NEWSLETTER_FROM=newsletter@financas-news.net.br
RESEND_API_KEY=                 # preferencial (API Resend) — verificação de conta + newsletter
NEWSLETTER_WEBHOOK_URL=         # alternativa: POST JSON {subject,html,text,to,from}
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_TLS=true
```

Cadastro local cria `email_verified=0`, gera `email_verify_token` (TTL 48h, uso único) e envia link `SITE_ORIGIN/verificar-email?token=...`. Login bloqueia até confirmar; reenvio em `POST /reenviar-verificacao` (cooldown ~2 min). Google OAuth marca o e-mail como já verificado. Contas existentes são grandfathered (`email_verified=1` no `ALTER`).

Não documente nem versione o valor real das chaves — só os nomes das variáveis no painel do host (`sync: false`).

---

## 11. Operação do dia a dia

### Publicar notícias

Agendar chamada ao robô a cada 2–3 horas (cron no Render ou cron-job.org):

```
https://financas-news.net.br/api/rodar-robo?token=SEU_ROBO_TOKEN
```

Preferencial (menos vazamento em logs): header `Authorization: Bearer SEU_ROBO_TOKEN`.  
Variáveis úteis: `ROBO_TOKEN`, `ROBOT_MAX_PER_FEED=3`, `ROBOT_MAX_ARTICLES=36`, `ROBOT_OWN_ANALYSES=3`, `GOOGLE_API_KEY` / `_2` / `_3`.

O robô prioriza a meta diária de **análises próprias** (síntese do acervo, sem RSS). Se ainda faltar, tenta de novo após os feeds. Endpoint dedicado: `/api/gerar-analises-proprias`.

Se não houver notícias novas, o robô gera **1 capa** para o artigo pendente mais recente (senão, antigos sem capa).

### Radar, macro e tradução (cron recomendado)

Além do robô principal, agendar (mesma auth `ROBO_TOKEN`):

| Endpoint | Frequência sugerida | Notas |
|----------|---------------------|-------|
| `/api/radar-semanal` | 1× por semana | `force=1` só se quiser regenerar |
| `/api/macro-watch` | diário ou após decisões do Copom/IBGE | só publica se Selic/IPCA mudarem |
| `/api/traduzir-pendentes?limit=10` | diário | preenche EN/JA pendentes |
| `/api/newsletter-digest` | 1× por semana | exige `RESEND_API_KEY`, SMTP ou webhook |

### Capas (backfill contínuo)

Com Hugging Face / OpenAI e limite de 1 imagem por execução, agendar a cada **30 minutos**:

```
https://financas-news.net.br/api/gerar-imagens?token=SEU_ROBO_TOKEN&limit=1
```

A fila prioriza `id DESC` (notícias novas sem capa primeiro).

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

### Entregue (ONDAs 1–3 — ago/2026)

- [x] Intro de categoria + guias na home filtrada
- [x] Feeds `/feed.xml` e `/feed.atom` + menção no `robots.txt`
- [x] Painel público `/mercado`
- [x] Tempo de leitura, relacionados e afiliados contextuais no artigo
- [x] Radar da semana, Macro Watch e tradução EN/JA (rotas autenticadas)
- [x] Newsletter digest/alerta (provedor env-driven)
- [x] CSP + headers de segurança no middleware
- [x] Mover token do robô para variável de ambiente (`ROBO_TOKEN`)
- [x] Mitigações anti-spam Google (thin 800, metodologia, mercado editorial, afiliados)
- [x] Comunidade: users, login/OAuth Google, comentários, cookies LGPD
- [x] Verificação de e-mail no cadastro local (link + bloqueio de login)
- [x] Newsletter digest 2x/dia (`/api/newsletter-digest-diario`)

### Curto prazo (0–30 dias)

- [ ] Agendar no Render: robô, capas, radar, macro-watch, traduzir, digest diário (manhã/tarde)
- [ ] Configurar `SESSION_SECRET`, `IP_HASH_SALT` e `GOOGLE_OAUTH_*` em produção
- [ ] Migrar crons restantes de `?token=` para `Authorization: Bearer` (e rotacionar se houve vazamento em logs)
- [ ] Reaplicar ao Google AdSense / reconsideração Search Console (§11b)
- [ ] Cadastrar programas de afiliados (Binance, Amazon) e preencher URLs no env

### Médio prazo (1–3 meses)

- [ ] Newsletter ativa em produção (Beehiiv/Mailchimp via webhook ou Resend)
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
