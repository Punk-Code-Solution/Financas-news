import html
import re
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

INTERNAL_KEYWORDS: dict[str, str] = {
    "Selic": "/?categoria=Juros",
    "IPCA": "/?categoria=Inflação",
    "Bitcoin": "/?categoria=Cripto",
    "BTC": "/?categoria=Cripto",
    "Cripto": "/?categoria=Cripto",
    "Dólar": "/?categoria=Dólar",
    "Dolar": "/?categoria=Dólar",
    "USD": "/?categoria=Dólar",
    "Bolsa": "/?categoria=Ações",
    "B3": "/?categoria=Ações",
    "Ações": "/?categoria=Ações",
    "Ibovespa": "/?categoria=Ações",
    "Inflação": "/?categoria=Inflação",
    "Juros": "/?categoria=Juros",
    "Imóveis": "/?categoria=Imóveis",
    "Fintech": "/?categoria=Fintech",
    "Commodities": "/?categoria=Commodities",
    "Renda fixa": "/?categoria=Juros",
    "Tesouro": "/?categoria=Juros",
}

SOURCE_HOST_NAMES: dict[str, str] = {
    "br.cointelegraph.com": "Cointelegraph",
    "cointelegraph.com": "Cointelegraph",
    "g1.globo.com": "G1 Economia",
    "www.infomoney.com.br": "InfoMoney",
    "infomoney.com.br": "InfoMoney",
    "www.investing.com": "Investing.com",
    "br.investing.com": "Investing.com",
    "exame.com": "Exame",
    "www.exame.com": "Exame",
    "www.moneytimes.com.br": "Money Times",
    "neofeed.com.br": "NeoFeed",
    "valor.globo.com": "Valor Econômico",
    "www.valor.com.br": "Valor Econômico",
}

# Subdomínios mortos/redirecionados → host canônico que ainda abre.
SOURCE_HOST_REWRITES: dict[str, str] = {
    "br.cointelegraph.com": "cointelegraph.com",
    "www.cointelegraph.com": "cointelegraph.com",
}

SOURCE_HOMEPAGES: dict[str, str] = {
    "Cointelegraph": "https://cointelegraph.com/",
    "G1 Economia": "https://g1.globo.com/economia/",
    "InfoMoney": "https://www.infomoney.com.br/",
    "Investing.com": "https://br.investing.com/",
    "Exame": "https://exame.com/",
    "Money Times": "https://www.moneytimes.com.br/",
    "NeoFeed": "https://neofeed.com.br/",
    "Valor Econômico": "https://valor.globo.com/",
    "Livecoins": "https://livecoins.com.br/",
}

DATA_SOURCE_LINKS = [
    {
        "nome": "AwesomeAPI",
        "url": "https://docs.awesomeapi.com.br/api-de-moedas",
        "externo": True,
    },
    {
        "nome": "BCB",
        "url": "https://dadosabertos.bcb.gov.br/",
        "externo": True,
    },
    {
        "nome": "IA editorial",
        "url": "/quem-somos",
        "externo": False,
    },
]

CATEGORY_DISCLAIMERS: dict[str, str] = {
    "Cripto": (
        "Criptoativos são voláteis e não contam com garantia do FGC. "
        "Investimentos em cripto podem resultar em perda total do capital."
    ),
    "Ações": (
        "Investimentos em ações envolvem risco de mercado. Rentabilidade passada não garante resultados futuros."
    ),
    "Juros": (
        "Taxas de juros e títulos de renda fixa variam conforme política monetária. "
        "Consulte condições atuais antes de investir."
    ),
    "Inflação": (
        "Projeções de inflação são estimativas e podem ser revisadas pelo mercado e pelo BCB."
    ),
    "Dólar": (
        "O câmbio é influenciado por fatores globais e locais. Variações podem ser abruptas."
    ),
    "Imóveis": (
        "O mercado imobiliário tem liquidez reduzida. Custos de transação e manutenção devem ser considerados."
    ),
    "Fintech": (
        "Produtos fintech podem ter regras específicas de regulação. Verifique a instituição no Banco Central."
    ),
    "Commodities": (
        "Commodities são sensíveis a choques geopolíticos e ciclos globais de oferta e demanda."
    ),
    "Política Econômica": (
        "Decisões políticas podem alterar rapidamente o cenário fiscal e regulatório."
    ),
    "Economia": (
        "Análises macroeconômicas são interpretações editoriais baseadas em dados públicos disponíveis."
    ),
}


def _parse_br_number(text: str) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d,.-]", "", str(text))
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_pct(text: str) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d,.-]", "", str(text)).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def clean_source_url(url: object) -> str | None:
    """Remove UTM/tracking e normaliza hosts mortos (ex.: br.cointelegraph.com → 410)."""
    if not url or not isinstance(url, str):
        return None
    raw = url.strip()
    if not raw.startswith(("http://", "https://")):
        return None
    try:
        parsed = urlparse(raw)
        host = parsed.netloc.lower()
        host = SOURCE_HOST_REWRITES.get(host, host)
        query = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")
            and k.lower() not in ("fbclid", "gclid", "mc_cid", "mc_eid")
        ]
        cleaned = parsed._replace(
            netloc=host,
            query=urlencode(query, doseq=True),
            fragment="",
        )
        return urlunparse(cleaned)
    except Exception:
        return raw


def source_homepage(fonte_nome: str | None, url: object = None) -> str | None:
    if fonte_nome and fonte_nome in SOURCE_HOMEPAGES:
        return SOURCE_HOMEPAGES[fonte_nome]
    cleaned = clean_source_url(url)
    if not cleaned:
        return None
    host = urlparse(cleaned).netloc.lower()
    return f"https://{host}/"


def infer_source_name(fonte: object, url: object) -> str:
    if fonte and str(fonte).strip():
        return str(fonte).strip()
    cleaned = clean_source_url(url) or ""
    host = urlparse(cleaned).netloc.lower().removeprefix("www.")
    if host in SOURCE_HOST_NAMES:
        return SOURCE_HOST_NAMES[host]
    for known, name in SOURCE_HOST_NAMES.items():
        if host.endswith(known.removeprefix("www.")):
            return name
    return host or "Fonte original"


def build_cross_links(
    dados_mercado: dict[str, Any],
    related_articles: list[dict[str, Any]],
    tag: str,
) -> list[dict[str, Any]]:
    """Links cruzados: referências internas, temas e matérias relacionadas."""
    links: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(label: str, href: str, kind: str = "interno"):
        key = href.lower()
        if not label or not href or key in seen:
            return
        seen.add(key)
        links.append({"label": label, "url": href, "tipo": kind})

    for ref in dados_mercado.get("referencias_internas") or []:
        nid = ref.get("noticia_id")
        if not nid:
            continue
        label = (ref.get("titulo") or ref.get("trecho") or f"Notícia #{nid}").strip()
        _add(label[:80], f"/noticia/{nid}", "acervo")

    for art in related_articles or []:
        nid = art.get("id")
        if not nid:
            continue
        _add(art.get("titulo") or f"Notícia #{nid}", f"/noticia/{nid}", "relacionada")

    if tag:
        _add(f"Mais em {tag}", f"/?categoria={quote(str(tag))}", "categoria")

    for kw, url in INTERNAL_KEYWORDS.items():
        texto = json_safe_lower_blob(dados_mercado)
        if kw.lower() in texto:
            _add(kw, url, "tema")

    return links[:10]


def json_safe_lower_blob(dados_mercado: dict[str, Any]) -> str:
    chunks: list[str] = []
    for key in ("pontos_chave", "faq", "glossario", "timeline"):
        val = dados_mercado.get(key)
        if val:
            chunks.append(str(val).lower())
    for ref in dados_mercado.get("referencias_internas") or []:
        chunks.append(str(ref.get("trecho", "")).lower())
    return " ".join(chunks)


def resolve_referencias_internas(client, referencias: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve referências da IA para IDs reais no banco."""
    resolved: list[dict[str, Any]] = []
    for ref in referencias or []:
        trecho = (ref.get("trecho") or "").strip()
        busca = (ref.get("titulo_busca") or ref.get("titulo") or trecho).strip()
        if not trecho:
            continue
        noticia_id = ref.get("noticia_id")
        titulo_match = None
        if not noticia_id and busca:
            result = client.execute(
                "SELECT id, titulo FROM news WHERE titulo LIKE ? ORDER BY id DESC LIMIT 1",
                [f"%{busca[:60]}%"],
            )
            if result.rows:
                noticia_id, titulo_match = result.rows[0][0], result.rows[0][1]
        resolved.append({
            "trecho": trecho,
            "noticia_id": noticia_id,
            "titulo": titulo_match or busca,
        })
    return resolved


def _sub_outside_tags(text: str, pattern: re.Pattern[str], repl: str, count: int = 1) -> str:
    """Substitui apenas em trechos fora de tags HTML (evita links aninhados/quebrados)."""
    parts = re.split(r"(<[^>]+>)", text)
    remaining = count
    for i, part in enumerate(parts):
        if remaining <= 0:
            break
        if part.startswith("<"):
            continue
        parts[i], n = pattern.subn(repl, part, count=remaining)
        remaining -= n
    return "".join(parts)


def link_text_parts(text: str, referencias: list[dict[str, Any]] | None = None) -> list[str]:
    """Aplica links internos e devolve cada parágrafo como HTML."""
    if not text:
        return []

    escaped = html.escape(text)
    refs = referencias or []

    for ref in sorted(refs, key=lambda r: len(r.get("trecho", "")), reverse=True):
        trecho = ref.get("trecho", "")
        nid = ref.get("noticia_id")
        if not trecho or not nid:
            continue
        safe_trecho = html.escape(trecho)
        link = (
            f'<a href="/noticia/{nid}" class="text-blue-600 dark:text-[#4ade80] '
            f'font-semibold hover:underline">{safe_trecho}</a>'
        )
        pattern = re.compile(re.escape(safe_trecho), re.IGNORECASE)
        escaped = _sub_outside_tags(escaped, pattern, link, count=1)

    for keyword in sorted(INTERNAL_KEYWORDS.keys(), key=len, reverse=True):
        url = INTERNAL_KEYWORDS[keyword]
        safe_kw = html.escape(keyword)
        link = (
            f'<a href="{url}" class="text-blue-600 dark:text-[#4ade80] '
            f'font-semibold hover:underline">{safe_kw}</a>'
        )
        pattern = re.compile(rf"(?<![\w>]){re.escape(safe_kw)}(?![\w<])", re.IGNORECASE)
        escaped = _sub_outside_tags(escaped, pattern, link, count=1)

    parts = escaped.split("\n\n")
    return [
        f'<p class="analise-p mb-5 md:mb-6">{part.replace(chr(10), "<br>")}</p>'
        for part in parts
        if part.strip()
    ]


def link_text_html(text: str, referencias: list[dict[str, Any]] | None = None) -> str:
    """Aplica links internos por palavra-chave e referências a artigos."""
    return "".join(link_text_parts(text, referencias))


def link_inline_html(text: str, referencias: list[dict[str, Any]] | None = None) -> str:
    """Mesmos links do resumo, sem wrappers de parágrafo (FAQ, legendas etc.)."""
    if not text:
        return ""
    parts = link_text_parts(text, referencias)
    # Remove o <p class="analise-p ...">...</p> externo.
    cleaned: list[str] = []
    for part in parts:
        inner = re.sub(r'^<p[^>]*>|</p>$', '', part.strip())
        cleaned.append(inner)
    return "<br><br>".join(cleaned) if cleaned else html.escape(text)


def build_before_after(dados_mercado: dict[str, Any]) -> dict[str, Any] | None:
    """Compara cotações atuais vs snapshot original do artigo."""
    cotacoes = dados_mercado.get("cotacoes") or {}
    if not cotacoes or cotacoes.get("coletado_em") is None:
        return None

    items: list[dict[str, Any]] = []
    for label, info in cotacoes.items():
        if label in ("coletado_em", "erro_cotacoes") or not isinstance(info, dict):
            continue
        atual = _parse_br_number(info.get("cotacao", ""))
        var_pct = _parse_pct(info.get("variacao_24h", ""))
        items.append({
            "label": label,
            "valor_publicacao": info.get("cotacao", "n/d"),
            "variacao_24h": info.get("variacao_24h", "n/d"),
            "valor_numerico": atual,
            "positivo": var_pct is None or var_pct >= 0,
        })

    if not items:
        return None

    return {
        "coletado_em": cotacoes.get("coletado_em"),
        "items": items,
    }


def build_historical_charts(historico: dict[str, Any], tag: str = "Economia") -> list[dict[str, Any]]:
    """Prepara dados para Chart.js a partir do histórico armazenado."""
    if not historico:
        return []

    tag_series_map = {
        "Cripto": ["Bitcoin (BTC/BRL)"],
        "Dólar": ["Dólar (USD/BRL)", "Dólar comercial (R$/US$)"],
        "Ações": ["Dólar (USD/BRL)"],
        "Juros": ["Selic meta (% a.a.)"],
        "Inflação": ["IPCA 12 meses (%)"],
    }
    preferred = tag_series_map.get(tag, [])
    charts: list[dict[str, Any]] = []

    for period_key, label_suffix in [("30d", "30 dias"), ("90d", "90 dias")]:
        period_data = historico.get(period_key) or {}
        for series_name, series in period_data.items():
            if not isinstance(series, dict) or not series.get("values"):
                continue
            if preferred and series_name not in preferred and len(charts) >= 2:
                continue
            charts.append({
                "id": re.sub(r"[^a-z0-9]", "-", series_name.lower()) + f"-{period_key}",
                "label": f"{series_name} — {label_suffix}",
                "labels": series.get("labels", []),
                "values": series.get("values", []),
                "fonte": series.get("fonte", ""),
                "periodo": label_suffix,
            })
            if len(charts) >= 4:
                break
        if len(charts) >= 4:
            break

    if not charts:
        for period_key, label_suffix in [("30d", "30 dias"), ("90d", "90 dias")]:
            period_data = historico.get(period_key) or {}
            for series_name, series in list(period_data.items())[:2]:
                if isinstance(series, dict) and series.get("values"):
                    charts.append({
                        "id": re.sub(r"[^a-z0-9]", "-", series_name.lower()) + f"-{period_key}",
                        "label": f"{series_name} — {label_suffix}",
                        "labels": series.get("labels", []),
                        "values": series.get("values", []),
                        "fonte": series.get("fonte", ""),
                        "periodo": label_suffix,
                    })

    return charts[:4]


def build_relevance_meta(dados_mercado: dict[str, Any]) -> dict[str, Any]:
    return {
        "urgencia": dados_mercado.get("urgencia", "Média"),
        "publico_alvo": dados_mercado.get("publico_alvo", "Geral"),
        "horizonte": dados_mercado.get("horizonte", "Médio prazo"),
        "confianca_dados": dados_mercado.get("confianca_dados", "Média"),
    }


def build_trust_box(dados_mercado: dict[str, Any], acervo_total: int, tag: str) -> dict[str, Any]:
    bcb = dados_mercado.get("bcb") or {}
    bcb_dates = [
        info.get("data", "")
        for info in bcb.values()
        if isinstance(info, dict) and info.get("data")
    ]
    cotacoes = dados_mercado.get("cotacoes") or {}
    dados_citados = dados_mercado.get("dados_citados") or []
    fontes_count = len(dados_citados) + len(bcb) + max(0, len(cotacoes) - 2)

    return {
        "fontes_count": fontes_count,
        "bcb_data": bcb_dates[0] if bcb_dates else None,
        "coletado_em": cotacoes.get("coletado_em") or dados_mercado.get("historico", {}).get("coletado_em"),
        "acervo_count": acervo_total,
        "disclaimer": CATEGORY_DISCLAIMERS.get(tag, CATEGORY_DISCLAIMERS["Economia"]),
    }


def build_related_entities(dados_mercado: dict[str, Any], tag: str) -> list[dict[str, str]]:
    entities: list[dict[str, str]] = []
    seen: set[str] = set()

    for ref in dados_mercado.get("referencias_internas") or []:
        trecho = (ref.get("trecho") or ref.get("titulo") or "").strip()
        if not trecho or trecho.lower() in seen:
            continue
        seen.add(trecho.lower())
        entry: dict[str, str] = {"nome": trecho, "tipo": "referência"}
        if ref.get("noticia_id"):
            entry["url"] = f"/noticia/{ref['noticia_id']}"
        entities.append(entry)

    for kw, url in INTERNAL_KEYWORDS.items():
        if kw.lower() in seen:
            continue
        if tag in ("Cripto",) and kw in ("Bitcoin", "BTC", "Cripto"):
            entities.append({"nome": kw, "tipo": "tema", "url": url})
            seen.add(kw.lower())
        elif tag in ("Dólar",) and kw in ("Dólar", "USD"):
            entities.append({"nome": kw, "tipo": "tema", "url": url})
            seen.add(kw.lower())
        elif tag in ("Economia", "Inflação", "Juros") and kw in ("Selic", "IPCA", "Inflação", "Juros"):
            entities.append({"nome": kw, "tipo": "tema", "url": url})
            seen.add(kw.lower())

    for ponto in dados_mercado.get("pontos_chave") or []:
        titulo = ponto.get("titulo", "")
        if titulo and titulo.lower() not in seen:
            seen.add(titulo.lower())
            href = ponto.get("url") or f"/?categoria={quote(str(ponto.get('categoria', tag)))}"
            entities.append({
                "nome": titulo,
                "tipo": "ponto-chave",
                "url": href,
            })

    return entities[:8]


def build_market_stats(dados_mercado: dict[str, Any], tag: str = "Economia") -> dict[str, Any]:
    cotacoes: list[dict[str, Any]] = []
    cot_data = dados_mercado.get("cotacoes") or {}

    for label, info in cot_data.items():
        if label in ("coletado_em", "erro_cotacoes") or not isinstance(info, dict):
            continue
        pct = _parse_pct(info.get("variacao_24h", ""))
        cotacoes.append(
            {
                "label": label,
                "valor": info.get("cotacao", "n/d"),
                "variacao": info.get("variacao_24h", "n/d"),
                "maxima": info.get("maxima"),
                "minima": info.get("minima"),
                "positivo": pct is None or pct >= 0,
                "bar": min(abs(pct or 0) * 12, 100) if pct is not None else 35,
            }
        )

    indicadores: list[dict[str, Any]] = []
    bcb = dados_mercado.get("bcb") or {}
    numeric_values = [
        n
        for info in bcb.values()
        if isinstance(info, dict)
        for n in [_parse_br_number(str(info.get("valor", "")))]
        if n is not None
    ]
    max_val = max(numeric_values) if numeric_values else 1

    for label, info in bcb.items():
        if not isinstance(info, dict):
            continue
        num = _parse_br_number(str(info.get("valor", "")))
        indicadores.append(
            {
                "label": label,
                "valor": info.get("valor", "n/d"),
                "data": info.get("data", ""),
                "bar": int((num / max_val) * 100) if num is not None else 45,
            }
        )

    pontos = dados_mercado.get("pontos_chave") or []
    if not pontos:
        citados = dados_mercado.get("dados_citados") or []
        if citados:
            pontos = [
                {"titulo": dado, "descricao": "", "categoria": tag}
                for dado in citados[:6]
            ]
        else:
            pontos = [
                {
                    "titulo": f"Tendências em {tag}",
                    "descricao": "Compare esta análise com outras matérias da mesma categoria no acervo.",
                    "categoria": tag,
                },
                {
                    "titulo": "Indicadores macro",
                    "descricao": "Selic, IPCA e câmbio contextualizam o impacto desta notícia no bolso.",
                    "categoria": "Economia",
                },
            ]

    # Artigos antigos podem ter salvo apenas números ("14.25", "4.64",
    # "5.0975"). Relaciona-os aos indicadores coletados para não exibir
    # valores sem contexto ao leitor.
    indicator_context = {
        "selic": {
            "nome": "Taxa Selic",
            "sufixo": "% ao ano",
            "descricao": "Taxa básica de juros; influencia crédito, financiamentos e a rentabilidade da renda fixa.",
            "categoria": "Juros",
        },
        "ipca": {
            "nome": "IPCA em 12 meses",
            "sufixo": "%",
            "descricao": "Índice oficial de inflação; indica a variação média dos preços para o consumidor.",
            "categoria": "Inflação",
        },
        "dólar": {
            "nome": "Dólar comercial",
            "prefixo": "R$ ",
            "descricao": "Cotação do dólar; afeta importados, viagens, combustíveis e empresas expostas ao câmbio.",
            "categoria": "Dólar",
        },
    }

    known_values: list[tuple[float, str, dict[str, str]]] = []
    for label, info in bcb.items():
        if not isinstance(info, dict):
            continue
        value = _parse_br_number(str(info.get("valor", "")))
        if value is None:
            continue
        label_lower = label.lower()
        context_key = next((key for key in indicator_context if key in label_lower), None)
        if context_key:
            known_values.append((value, str(info.get("valor", value)), indicator_context[context_key]))

    for ponto in pontos:
        if not isinstance(ponto, dict):
            continue
        titulo = str(ponto.get("titulo", "")).strip()
        numeric = _parse_br_number(titulo)
        # Só interpreta como número isolado quando não há palavras explicativas.
        if numeric is None or re.search(r"[A-Za-zÀ-ÿ]", titulo):
            continue
        match = next(
            (
                (raw_value, context)
                for value, raw_value, context in known_values
                if abs(value - numeric) < 0.0001
            ),
            None,
        )
        if not match:
            continue
        raw_value, context = match
        formatted = raw_value.replace(".", ",")
        ponto["titulo"] = (
            f"{context.get('nome')}: "
            f"{context.get('prefixo', '')}{formatted}{context.get('sufixo', '')}"
        )
        ponto["descricao"] = context["descricao"]
        ponto["categoria"] = context["categoria"]

    return {
        "coletado_em": cot_data.get("coletado_em"),
        "cotacoes": cotacoes,
        "indicadores": indicadores,
        "pontos_chave": pontos,
    }


def get_related_articles(client, tag: str, exclude_id: int, limit: int = 4) -> list[dict[str, Any]]:
    result = client.execute(
        """
        SELECT id, titulo, tag, sentimento,
               COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao,
               resumo
        FROM news
        WHERE tag = ? AND id != ?
        ORDER BY id DESC
        LIMIT ?
        """,
        [tag, exclude_id, limit],
    )
    articles: list[dict[str, Any]] = []
    for row in result.rows:
        resumo = (row[5] or "").strip().replace("\n", " ")
        if len(resumo) > 140:
            resumo = resumo[:137].rsplit(" ", 1)[0] + "…"
        articles.append(
            {
                "id": row[0],
                "titulo": row[1],
                "tag": row[2],
                "sentimento": row[3] or "Neutro",
                "data": row[4],
                "trecho": resumo,
            }
        )
    return articles


def resolve_pontos_chave_links(
    client,
    pontos: list[dict[str, Any]],
    default_tag: str,
    exclude_id: int,
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    fallback_href = f"/?categoria={quote(default_tag)}" if default_tag else "/"

    for ponto in pontos:
        item = dict(ponto)
        categoria = (item.get("categoria") or default_tag or "").strip()
        href = fallback_href

        if categoria:
            result = client.execute(
                """
                SELECT id
                FROM news
                WHERE tag = ? AND id != ?
                ORDER BY id DESC
                LIMIT 1
                """,
                [categoria, exclude_id],
            )
            if result.rows:
                href = f"/noticia/{result.rows[0][0]}"
            else:
                count_result = client.execute(
                    "SELECT COUNT(*) FROM news WHERE tag = ?",
                    [categoria],
                )
                count = int(count_result.rows[0][0]) if count_result.rows else 0
                href = f"/?categoria={quote(categoria)}" if count else "/"

        item["href"] = href
        item["cta_categoria"] = categoria or default_tag or "mercado"
        resolved.append(item)

    return resolved


def get_acervo_stats(client, tag: str) -> dict[str, Any]:
    result = client.execute(
        "SELECT sentimento, COUNT(*) FROM news WHERE tag = ? GROUP BY sentimento",
        [tag],
    )
    by_sentiment: dict[str, int] = {}
    for sentimento, count in result.rows:
        by_sentiment[sentimento or "Neutro"] = count

    total = sum(by_sentiment.values())
    positivo = by_sentiment.get("Positivo", 0)
    negativo = by_sentiment.get("Negativo", 0)
    neutro = by_sentiment.get("Neutro", 0)

    if total == 0:
        insight = "Ainda não há histórico suficiente nesta categoria."
        tom = "Neutro"
    elif negativo > positivo and negativo >= neutro:
        insight = (
            f"O tom recente em {tag} está mais cauteloso: {negativo} de {total} "
            f"análises com viés negativo. Vale cruzar com as matérias abaixo."
        )
        tom = "Negativo"
    elif positivo > negativo and positivo >= neutro:
        insight = (
            f"O acervo em {tag} pende ao otimismo: {positivo} de {total} "
            f"análises positivas. Confira o que sustentou esse viés."
        )
        tom = "Positivo"
    else:
        insight = (
            f"O histórico em {tag} está equilibrado/neutro ({neutro} neutras de {total}). "
            f"Use as matérias relacionadas para ver o que mudou entre as publicações."
        )
        tom = "Neutro"

    return {
        "total": total,
        "positivo": positivo,
        "negativo": negativo,
        "neutro": neutro,
        "tom": tom,
        "insight": insight,
        "chart": [
            {"label": "Positivo", "count": positivo, "color": "#4ade80"},
            {"label": "Negativo", "count": negativo, "color": "#f87171"},
            {"label": "Neutro", "count": neutro, "color": "#94a3b8"},
        ],
    }


def build_perfil_investidor(tag: str, dados_mercado: dict[str, Any] | None = None) -> dict[str, str]:
    """Garante orientação por perfil — usa IA se houver; senão fallback editorial por categoria."""
    existing = (dados_mercado or {}).get("perfil_investidor") or {}
    if isinstance(existing, dict):
        filled = {
            k: str(v).strip()
            for k, v in existing.items()
            if k in ("conservador", "moderado", "arrojado") and str(v).strip()
        }
        if len(filled) == 3:
            return filled

    defaults: dict[str, dict[str, str]] = {
        "Cripto": {
            "conservador": (
                "Trate cripto como satélite da carteira (no máximo 1–5%). Priorize exchanges "
                "reguladas, evite alavancagem e foque em entender custódia e volatilidade antes de aportar."
            ),
            "moderado": (
                "Você pode diversificar com BTC/ETH em aportes periódicos (DCA), mantendo reserva de "
                "emergência em reais. Defina um teto de risco e revise a exposição a cada trimestre."
            ),
            "arrojado": (
                "Há espaço para posições táticos e altcoins, mas com stop mental e tamanho de lote "
                "disciplinado. Volatilidade alta pode amplificar ganhos e perdas — não use capital essencial."
            ),
        },
        "Economia": {
            "conservador": (
                "Acompanhe Selic e IPCA para calibrar renda fixa pós/pré. Prefira liquidez e proteção "
                "do poder de compra; evite decisões impulsivas com base em uma única manchete."
            ),
            "moderado": (
                "Equilibre renda fixa e variável conforme o ciclo de juros. Use o cenário macro para "
                "ajustar duration e exposição a ações, sem concentrar em um único tema."
            ),
            "arrojado": (
                "Oportunidades táticas em duração, câmbio e setores cíclicos fazem sentido se houver "
                "colchão de liquidez. Monitore revisões do Focus e sinais do Banco Central."
            ),
        },
        "Dólar": {
            "conservador": (
                "Exposição cambial pequena via fundos cambiais ou conta internacional pode proteger "
                "parte do patrimônio. Evite alavancagem em forex."
            ),
            "moderado": (
                "Diversifique com uma parcela em dólar alinhada a gastos futuros (viagens, estudos). "
                "Rebalanceie quando o câmbio se deslocar muito da média recente."
            ),
            "arrojado": (
                "Posições táticas em câmbio e ativos dolarizados são viáveis com limites claros de perda. "
                "Acompanhe juros EUA e fluxo de risco global."
            ),
        },
        "Ações": {
            "conservador": (
                "Prefira ETFs amplos e empresas sólidas com histórico de dividendos. Evite concentração "
                "em um único papel e mantenha horizonte longo."
            ),
            "moderado": (
                "Monte um núcleo em índices/blue chips e uma parcela satellite em setores com tese clara. "
                "Use correções para aportes programados."
            ),
            "arrojado": (
                "Há espaço para small caps e temas cíclicos, com gestão ativa de risco. Defina stops e "
                "não aumente posição em papéis já muito esticados."
            ),
        },
        "Juros": {
            "conservador": (
                "Priorize Tesouro Selic e crédito de alta qualidade para preservar capital enquanto "
                "acompanha o ciclo de corte/alta da Selic."
            ),
            "moderado": (
                "Combine pós-fixados com prefixados/IPCA+ de prazos intermediários conforme a curva. "
                "Evite travar tudo em um único vencimento."
            ),
            "arrojado": (
                "Duration mais longa e crédito privado podem turbinar retorno se a tese de juros estiver "
                "clara — monitore prêmios e liquidez diária."
            ),
        },
        "Inflação": {
            "conservador": (
                "IPCA+ curto e produtos atrelados à inflação ajudam a proteger o poder de compra. "
                "Mantenha reserva emergencial líquida."
            ),
            "moderado": (
                "Misture IPCA+, pós-fixados e uma fatia de renda variável real (ações/FIIs selecionados) "
                "para equilibrar proteção e crescimento."
            ),
            "arrojado": (
                "Surpresas de inflação criam assimetrias em duration e setores defensivos/cíclicos. "
                "Ajuste rápido a alocação quando o Focus revisar projeções."
            ),
        },
    }

    base = defaults.get(tag) or {
        "conservador": (
            f"Em {tag}, preserve capital: priorize liquidez, diversificação e tickets pequenos até "
            "dominar os riscos específicos do tema."
        ),
        "moderado": (
            f"Para {tag}, combine um núcleo conservador com exposição gradual ao tema, revisando "
            "a tese quando novos dados de mercado forem publicados."
        ),
        "arrojado": (
            f"Em {tag}, posições mais agressivas exigem disciplina de risco, monitoramento frequente "
            "e capital que você possa perder sem comprometer objetivos essenciais."
        ),
    }

    result = dict(base)
    result.update(filled if isinstance(existing, dict) else {})
    return {
        "conservador": result.get("conservador") or base["conservador"],
        "moderado": result.get("moderado") or base["moderado"],
        "arrojado": result.get("arrojado") or base["arrojado"],
    }


def build_article_enrichment(
    client,
    noticia_id: int,
    tag: str,
    dados_mercado: dict[str, Any],
    resumo: str = "",
    published_at: object = None,
    created_at: object = None,
) -> dict[str, Any]:
    import core

    # Dados do período da análise — nunca injeta cotações de "hoje".
    market_data = core.resolve_article_market_data(
        dados_mercado,
        published_at=published_at,
        created_at=created_at,
        blocking_hist=False,
    )

    refs = market_data.get("referencias_internas") or []
    if refs:
        market_data["referencias_internas"] = resolve_referencias_internas(client, refs)

    acervo = get_acervo_stats(client, tag)
    related_articles = get_related_articles(client, tag, noticia_id)
    linked_parts = link_text_parts(resumo, market_data.get("referencias_internas"))

    market_stats = build_market_stats(market_data, tag)
    market_stats["pontos_chave"] = resolve_pontos_chave_links(
        client,
        market_stats.get("pontos_chave") or [],
        tag,
        noticia_id,
    )
    if market_data.get("periodo_analise"):
        market_stats["periodo_analise"] = market_data["periodo_analise"]

    faq_items = []
    for item in market_data.get("faq") or []:
        pergunta = (item.get("pergunta") or "").strip()
        resposta = (item.get("resposta") or "").strip()
        if not pergunta or not resposta:
            continue
        faq_items.append({
            "pergunta": pergunta,
            "resposta": resposta,
            "resposta_html": link_inline_html(resposta, market_data.get("referencias_internas")),
        })

    charts = build_historical_charts(market_data.get("historico", {}), tag)
    periodo = market_data.get("periodo_analise")
    if periodo:
        for chart in charts:
            if "até" not in (chart.get("label") or ""):
                chart["label"] = f"{chart.get('label', '')} (até {periodo})"

    return {
        "market_stats": market_stats,
        "related_articles": related_articles,
        "acervo_stats": acervo,
        "historical_charts": charts,
        "before_after": build_before_after(market_data),
        "relevance": build_relevance_meta(market_data),
        "trust": build_trust_box(market_data, acervo["total"], tag),
        "timeline": market_data.get("timeline") or [],
        "cenarios": market_data.get("cenarios") or [],
        "perfil_investidor": build_perfil_investidor(tag, market_data),
        "glossario": market_data.get("glossario") or [],
        "faq": faq_items,
        "tabela_comparativa": market_data.get("tabela_comparativa"),
        "atualizacao": market_data.get("atualizacao"),
        "related_entities": build_related_entities(market_data, tag),
        "cross_links": build_cross_links(market_data, related_articles, tag),
        "data_source_links": DATA_SOURCE_LINKS,
        "linked_resumo": "".join(linked_parts),
        "linked_resumo_parts": linked_parts,
        "periodo_analise": periodo,
    }
