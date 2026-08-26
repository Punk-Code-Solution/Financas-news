# Crons — Railway (Clareza Capital)

Produção: **https://financas-news.net.br**  
Host: **Railway** (serviço web uvicorn sempre ligado).

Schedules em **UTC** (cron-job.org e Railway Cron usam UTC). BRT = UTC−3.

**Auth:** `Authorization: Bearer <ROBO_TOKEN>`  
(nunca `?token=` na URL — vaza em logs)

**Variable no serviço web:**  
`SITE_ORIGIN=https://financas-news.net.br`

---

## Agenda

| Job | Método | Path | Cron (UTC) | Equiv. BRT | Timeout |
|-----|--------|------|------------|------------|---------|
| Robô | GET | `/api/rodar-robo` | `0 */3 * * *` | a cada 3 h | 60 s (responde 202; o trabalho segue no servidor) |
| Capas | GET | `/api/gerar-imagens?limit=5` | `*/20 * * * *` | a cada 20 min | 5–10 min |
| Mercado nos artigos | GET | `/api/atualizar-artigos?limit=20` | `15 */6 * * *` | a cada 6 h | 5 min |
| Macro-watch | GET | `/api/macro-watch` | `0 12 * * *` | 09:00 BRT | 5 min |
| Traduzir EN/JA | GET | `/api/traduzir-pendentes?limit=10` | `30 12 * * *` | 09:30 BRT | 10 min |
| Digest diário | GET | `/api/newsletter-digest-diario` | `0 11,20 * * *` | 08:00 e 17:00 BRT | 3 min |
| Digest semanal | GET | `/api/newsletter-digest` | `0 13 * * 0` | dom 10:00 BRT | 3 min |
| Radar | GET | `/api/radar-semanal` | `0 14 * * 1` | seg 11:00 BRT | 10 min |
| Sync FTS | GET | `/api/sync-news-fts` | `0 6 * * *` | 03:00 BRT | 5 min |
| Crédito colunistas | POST | `/api/columnists/credit-daily` | `30 2 * * *` | 23:30 BRT | 2 min |
| Expirar boosts | POST | `/api/columnists/expire-boosts` | `10 * * * *` | a cada hora | 1 min |

---

## Como agendar (recomendado: cron-job.org)

Para cada job:

1. URL = base + path (lista abaixo)  
2. Método GET ou POST  
3. Header `Authorization` = `Bearer ` + `ROBO_TOKEN` (Variables da Railway)  
4. Schedule = cron UTC da tabela  
5. Timeout ≥ valor sugerido (no robô, 60 s basta depois do deploy com 202)  

### URLs

```
https://www.financas-news.net.br/api/rodar-robo
https://www.financas-news.net.br/api/gerar-imagens?limit=5
https://www.financas-news.net.br/api/atualizar-artigos?limit=20
https://www.financas-news.net.br/api/macro-watch
https://www.financas-news.net.br/api/traduzir-pendentes?limit=10
https://www.financas-news.net.br/api/newsletter-digest-diario
https://www.financas-news.net.br/api/newsletter-digest
https://www.financas-news.net.br/api/radar-semanal
https://www.financas-news.net.br/api/sync-news-fts
https://www.financas-news.net.br/api/columnists/credit-daily
https://www.financas-news.net.br/api/columnists/expire-boosts
```

### cron-job.org — o que preencher em cada job

Timezone: **UTC**.  
Request headers → Add header:  
- Name: `Authorization`  
- Value: `Bearer ` + seu `ROBO_TOKEN` (sem aspas)

| Title (sugerido) | URL | Method | Schedule (UTC) | Timeout |
|------------------|-----|--------|----------------|---------|
| FN rodar-robo | `https://www.financas-news.net.br/api/rodar-robo` | GET | `0 */3 * * *` | 60s |
| FN gerar-imagens | `https://www.financas-news.net.br/api/gerar-imagens?limit=5` | GET | `*/20 * * * *` | 600s |
| FN atualizar-artigos | `https://www.financas-news.net.br/api/atualizar-artigos?limit=20` | GET | `15 */6 * * *` | 300s |
| FN macro-watch | `https://www.financas-news.net.br/api/macro-watch` | GET | `0 12 * * *` | 300s |
| FN traduzir-pendentes | `https://www.financas-news.net.br/api/traduzir-pendentes?limit=10` | GET | `30 12 * * *` | 600s |
| FN digest-diario | `https://www.financas-news.net.br/api/newsletter-digest-diario` | GET | `0 11,20 * * *` | 180s |
| FN digest-semanal | `https://www.financas-news.net.br/api/newsletter-digest` | GET | `0 13 * * 0` | 180s |
| FN radar-semanal | `https://www.financas-news.net.br/api/radar-semanal` | GET | `0 14 * * 1` | 600s |
| FN sync-news-fts | `https://www.financas-news.net.br/api/sync-news-fts` | GET | `0 6 * * *` | 300s |
| FN columnists-credit | `https://www.financas-news.net.br/api/columnists/credit-daily` | POST | `30 2 * * *` | 120s |
| FN columnists-boosts | `https://www.financas-news.net.br/api/columnists/expire-boosts` | POST | `10 * * * *` | 60s |

### curl one-liner (teste manual = mesma request do cron-job.org)

```bash
# export ROBO_TOKEN=...

curl -fsS -X GET -H "Authorization: Bearer $ROBO_TOKEN" --max-time 60 "https://www.financas-news.net.br/api/rodar-robo"
curl -fsS -X GET -H "Authorization: Bearer $ROBO_TOKEN" --max-time 600 "https://www.financas-news.net.br/api/gerar-imagens?limit=5"
curl -fsS -X GET -H "Authorization: Bearer $ROBO_TOKEN" --max-time 300 "https://www.financas-news.net.br/api/atualizar-artigos?limit=20"
curl -fsS -X GET -H "Authorization: Bearer $ROBO_TOKEN" --max-time 300 "https://www.financas-news.net.br/api/macro-watch"
curl -fsS -X GET -H "Authorization: Bearer $ROBO_TOKEN" --max-time 600 "https://www.financas-news.net.br/api/traduzir-pendentes?limit=10"
curl -fsS -X GET -H "Authorization: Bearer $ROBO_TOKEN" --max-time 180 "https://www.financas-news.net.br/api/newsletter-digest-diario"
curl -fsS -X GET -H "Authorization: Bearer $ROBO_TOKEN" --max-time 180 "https://www.financas-news.net.br/api/newsletter-digest"
curl -fsS -X GET -H "Authorization: Bearer $ROBO_TOKEN" --max-time 600 "https://www.financas-news.net.br/api/radar-semanal"
curl -fsS -X GET -H "Authorization: Bearer $ROBO_TOKEN" --max-time 300 "https://www.financas-news.net.br/api/sync-news-fts"
curl -fsS -X POST -H "Authorization: Bearer $ROBO_TOKEN" --max-time 120 "https://www.financas-news.net.br/api/columnists/credit-daily"
curl -fsS -X POST -H "Authorization: Bearer $ROBO_TOKEN" --max-time 60 "https://www.financas-news.net.br/api/columnists/expire-boosts"
```

Esperado: **202** no robô (`Aceito` ou `Ignorado` se já estiver rodando). Demais jobs: **200**. Sem token → **401**. Abrir a URL no Chrome **sempre** dá 401 (não envia o header).

### Job do robô no cron-job.org (o que estava falhando)

O print de **500 em ~7 s** não é “timeout de 20 min”. O portal corta a request cedo; o robô precisa de muitos minutos. Com o endpoint em segundo plano, o cron só precisa autenticar e receber **202**.

Preencha assim:

1. **Title:** `FN rodar-robo`
2. **Address:** `https://www.financas-news.net.br/api/rodar-robo` (sem `?token=`)
3. **Request method:** GET
4. **Schedule:** `0 */3 * * *` · timezone **UTC**
5. **Request timeout:** 60 segundos (ou o máximo do plano; não precisa 1200)
6. **Request headers → Add header**
   - Name: `Authorization`
   - Value: `Bearer ` + o mesmo `ROBO_TOKEN` da Variable Railway (espaço depois de Bearer, sem aspas)
7. **Expected HTTP status:** `202` (se o painel exigir um código; 2xx já conta como sucesso)
8. **Não** marque “save response body” com o token — o token não vai na URL

Verde no cron-job.org = “aceito”. Se a matéria não aparecer no site, o erro está nos **logs Railway** (`[robo] falha em background`), não no HTTP do cron.

---

## Railway — regras

1. **Não** ative “Cron Schedule” no serviço **web** (uvicorn precisa ficar up 24/7).  
2. Use cron-job.org **ou** um serviço Railway separado por job (`python tools/cron_http.py <job>` e exit).  
3. Template Railway “Cron Webhook Trigger”: `ENDPOINT_URL` = URL da lista; `CRON_SECRET` = mesmo valor de `ROBO_TOKEN`.

Runner local/one-shot:

```bash
SITE_ORIGIN=https://financas-news.net.br ROBO_TOKEN=... python tools/cron_http.py rodar-robo
```
