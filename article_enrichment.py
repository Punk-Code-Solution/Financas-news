import html
import re
from typing import Any
from urllib.parse import quote

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
        trecho = ref.get("trecho", "")
        if trecho and trecho.lower() not in seen:
            seen.add(trecho.lower())
            entities.append({"nome": trecho, "tipo": "referência"})

    for kw, url in INTERNAL_KEYWORDS.items():
        if kw.lower() in seen:
            continue
        if tag in ("Cripto",) and kw in ("Bitcoin", "BTC", "Cripto"):
            entities.append({"nome": kw, "tipo": "tema", "url": url})
            seen.add(kw.lower())
        elif tag in ("Dólar",) and kw in ("Dólar", "USD"):
            entities.append({"nome": kw, "tipo": "tema", "url": url})
            seen.add(kw.lower())

    for ponto in dados_mercado.get("pontos_chave") or []:
        titulo = ponto.get("titulo", "")
        if titulo and titulo.lower() not in seen:
            seen.add(titulo.lower())
            cat = ponto.get("categoria", tag)
            entities.append({
                "nome": titulo,
                "tipo": "ponto-chave",
                "url": f"/?categoria={cat}",
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


def build_article_enrichment(
    client,
    noticia_id: int,
    tag: str,
    dados_mercado: dict[str, Any],
    resumo: str = "",
) -> dict[str, Any]:
    market_data = dict(dados_mercado)
    if not market_data.get("cotacoes") and not market_data.get("bcb"):
        import core

        market_data["cotacoes"] = core.fetch_market_snapshot()
        market_data["bcb"] = core.fetch_bcb_snapshot()

    if not market_data.get("historico"):
        import core

        market_data["historico"] = core.fetch_market_historical()

    refs = market_data.get("referencias_internas") or []
    if refs and not any(r.get("noticia_id") for r in refs):
        market_data["referencias_internas"] = resolve_referencias_internas(client, refs)

    acervo = get_acervo_stats(client, tag)
    linked_parts = link_text_parts(resumo, market_data.get("referencias_internas"))

    market_stats = build_market_stats(market_data, tag)
    market_stats["pontos_chave"] = resolve_pontos_chave_links(
        client,
        market_stats.get("pontos_chave") or [],
        tag,
        noticia_id,
    )

    return {
        "market_stats": market_stats,
        "related_articles": get_related_articles(client, tag, noticia_id),
        "acervo_stats": acervo,
        "historical_charts": build_historical_charts(market_data.get("historico", {}), tag),
        "before_after": build_before_after(market_data),
        "relevance": build_relevance_meta(market_data),
        "trust": build_trust_box(market_data, acervo["total"], tag),
        "timeline": market_data.get("timeline") or [],
        "cenarios": market_data.get("cenarios") or [],
        "perfil_investidor": market_data.get("perfil_investidor") or {},
        "glossario": market_data.get("glossario") or [],
        "faq": market_data.get("faq") or [],
        "tabela_comparativa": market_data.get("tabela_comparativa"),
        "atualizacao": market_data.get("atualizacao"),
        "related_entities": build_related_entities(market_data, tag),
        "linked_resumo": "".join(linked_parts),
        "linked_resumo_parts": linked_parts,
    }
