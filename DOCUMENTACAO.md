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
│  Feeds RSS (14) │────▶│  Motor core.py   │────▶│  Banco Turso    │
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
2. **Leitura de 14 feeds RSS** — até 2 notícias por feed por execução (~28 artigos máx.).
3. **Contexto editorial** — consulta notícias já publicadas no banco para cruzar tendências e evitar repetição.
4. **Geração de texto** — Gemini produz análise de 500+ palavras em 6 blocos estruturados (JSON).
5. **Geração de imagem** — capa editorial 16:9 via modelos de imagem Gemini/Imagen.
6. **Deduplicação** — ignora matérias com o mesmo link de origem.
7. **Publicação** — grava no Turso e exibe no frontend.

### Acionamento

O robô é disparado via HTTP (cron externo, Render Cron Job ou chamada manual):

```
GET /api/rodar-robo?token=SEU_TOKEN
```

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
├── db.py                # Conexão Turso, schema, contexto editorial
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

| Fonte | Categoria |
|-------|-----------|
| Livecoins | Cripto |
| G1 Economia | Economia |
| InfoMoney | Economia |
| Investing.com Brasil | Ações |
| Exame | Economia |
| Money Times | Ações |
| NeoFeed | Fintech |
| Valor Econômico | Economia |
| InfoMoney Imóveis | Imóveis |
| Investing Commodities | Commodities |
| G1 Política | Política Econômica |
| InfoMoney Inflação | Inflação |
| InfoMoney Juros | Juros |
| Investing Forex | Dólar |

### Formato de cada artigo publicado

- **Título** editorial gerado pela IA
- **Análise completa** (6 parágrafos: cenário, dados, cruzamento, opinião, projeção, guia prático)
- **Panorama de mercado** (box com números citados)
- **Impacto no bolso** (3 frases diretas)
- **Sentimento** (Positivo / Negativo / Neutro)
- **Imagem de capa** (quando a API de imagem responde)
- **Link para fonte original** (transparência editorial)
- **Data e veículo de origem**

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

1. `gemini-3.1-flash-lite-preview` — 500 req/dia (free tier)
2. `gemini-2.5-flash-lite` — fallback
3. `gemini-2.5-flash` — fallback

O sistema **troca de modelo** quando a cota diária esgota e **só faz retry** em limite por minuto (RPM), evitando loops inúteis.

### Modelos de imagem

Tentativa em ordem (Nano Banana / Gemini Image):

1. `gemini-2.5-flash-image`
2. `gemini-3.1-flash-image-preview`
3. `gemini-3.1-flash-lite-image-preview`

> **Nota:** Imagen 4 (`imagen-4.0-*`) foi descontinuado na API Gemini. Não usar mais em `GEMINI_IMAGE_MODELOS`.

Imagens salvas em disco (`ARTICLE_IMAGES_DIR`) com URL pública `/media/articles/`.

### Custo estimado de API (free tier)

| Recurso | Consumo por artigo | Limite free (referência) |
|---------|-------------------|--------------------------|
| Texto | 1 requisição | 500/dia (3.1 Flash Lite) |
| Imagem | 1 requisição | conforme cota do modelo |
| **Total por rodada (~28 artigos)** | ~56 chamadas | monitorar no painel Google AI |

> **Atenção:** a mesma `GOOGLE_API_KEY` pode ser compartilhada com outros projetos (ex.: automação de cortes). Cotas somam no mesmo projeto Google.

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
| `/` | Home com listagem, filtros e busca |
| `/noticia/{id}` | Artigo completo |
| `/quem-somos` | Sobre o portal |
| `/privacidade` | Política de privacidade |
| `/termos` | Termos de uso |

### SEO

| Rota | Função |
|------|--------|
| `/sitemap.xml` | Mapa com últimas 500 notícias |
| `/robots.txt` | Instruções para crawlers |
| `/ads.txt` | Verificação Google AdSense |

### API interna

| Rota | Função |
|------|--------|
| `GET /api/rodar-robo?token=` | Dispara pipeline de notícias |
| `POST /api/newsletter` | Captura de e-mail |
| `GET /ping` | Health check |

---

## 10. Variáveis de ambiente

### Obrigatórias (produção)

```env
GOOGLE_API_KEY=           # ou GEMINI_API_KEY
TURSO_DATABASE_URL=       # URL libsql:// do Turso
TURSO_AUTH_TOKEN=         # Token de autenticação Turso
```

### IA (opcionais)

```env
GEMINI_MODELOS=gemini-3.1-flash-lite-preview,gemini-2.5-flash-lite,gemini-2.5-flash
GEMINI_IMAGE_MODELOS=gemini-2.5-flash-image,gemini-3.1-flash-image-preview,gemini-3.1-flash-lite-image-preview
# Produção (Render): sempre Gemini (já forçado no código quando RENDER=true).
# Local: gemini | cursor | auto (Cursor → fallback Gemini).
IMAGE_PROVIDER=gemini
ARTICLE_IMAGES_DIR=/var/data/article_images
```

> No Render, `IMAGE_PROVIDER` já está como `gemini` no `render.yaml`. Mesmo se estiver `auto` ou `cursor`, o código força Gemini porque o Cursor SDK não roda lá.
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

Agendar chamada ao robô a cada 4–6 horas (cron no Render ou serviço externo como cron-job.org):

```
https://financas-news.net.br/api/rodar-robo?token=SEU_TOKEN
```

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

- [ ] Reaplicar ao Google AdSense com acervo de 30+ análises de qualidade
- [ ] Cadastrar programas de afiliados (Binance, Amazon)
- [ ] Agendar robô automaticamente no Render
- [ ] Mover token do robô para variável de ambiente (`ROBO_TOKEN`)

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
| Feed RSS fora do ar | 14 fontes redundantes; logs por feed |
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
