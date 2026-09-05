"""Internacionalização (pt / en / ja) do Clareza Capital."""
from __future__ import annotations

import os
from typing import Any, Callable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from fastapi import Request

# Marca + pilares para SEO (meta keywords + schema.org). Legado leve = equity de busca.
SITE_BRAND_KEYWORDS: list[str] = [
    # Marca atual
    "clareza capital",
    "clareza",
    "clarezacapital",
    # Equity legado (sem stuffing)
    "finanças news",
    "financas news",
    "financas-news",
    # Pilares do produto
    "notícias financeiras",
    "análise financeira",
    "analise financeira",
    "radar de mercado",
    "painel de mercado",
    "economia brasil",
    "economia brasileira",
    "mercado financeiro",
    "mercado de capitais",
    "investimentos",
    "ações",
    "acoes",
    "criptomoedas",
    "bitcoin",
    "dólar",
    "dolar",
    "euro",
    "selic",
    "ipca",
    "inflação",
    "inflacao",
    "juros",
    "banco central",
    "newsletter financeira",
    "metodologia editorial",
    "fintech",
    "commodities",
    "renda fixa",
    "câmbio",
    "cambio",
]

SITE_BRAND_ALTERNATE_NAMES: list[str] = [
    "Finanças News",
    "Financas News",
    "financas news",
    "financas-news",
    "ClarezaCapital",
]

SITE_TOPIC_KEYWORDS: list[str] = [
    "Cripto",
    "Economia",
    "Dólar",
    "Ações",
    "Juros",
    "Inflação",
    "Imóveis",
    "Fintech",
    "Commodities",
    "Política Econômica",
]

SUPPORTED_LANGS = ("pt", "en", "ja")
DEFAULT_LANG = "pt"
COOKIE_NAME = "lang"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365

HTML_LANG = {
    "pt": "pt-BR",
    "en": "en",
    "ja": "ja",
}

TAG_LABELS = {
    "pt": {
        "Cripto": "Cripto",
        "Economia": "Economia",
        "Dólar": "Dólar",
        "Ações": "Ações",
        "Juros": "Juros",
        "Inflação": "Inflação",
        "Imóveis": "Imóveis",
        "Fintech": "Fintech",
        "Commodities": "Commodities",
        "Política Econômica": "Política Econômica",
    },
    "en": {
        "Cripto": "Crypto",
        "Economia": "Economy",
        "Dólar": "Dollar",
        "Ações": "Stocks",
        "Juros": "Interest Rates",
        "Inflação": "Inflation",
        "Imóveis": "Real Estate",
        "Fintech": "Fintech",
        "Commodities": "Commodities",
        "Política Econômica": "Economic Policy",
    },
    "ja": {
        "Cripto": "暗号資産",
        "Economia": "経済",
        "Dólar": "ドル",
        "Ações": "株式",
        "Juros": "金利",
        "Inflação": "インフレ",
        "Imóveis": "不動産",
        "Fintech": "フィンテック",
        "Commodities": "コモディティ",
        "Política Econômica": "経済政策",
    },
}

# Textos introdutórios editoriais por categoria (home com ?categoria=).
CATEGORY_INTROS: dict[str, dict[str, str]] = {
    "pt": {
        "Cripto": (
            "Bitcoin, altcoins, ETFs e regulação cripto no Brasil — com contexto de mercado, "
            "risco e impacto no bolso, sem hype."
        ),
        "Economia": (
            "PIB, emprego, fiscal e indicadores que movem o dia a dia da economia brasileira, "
            "com leitura clara para investidor e consumidor."
        ),
        "Dólar": (
            "Câmbio, fluxo externo e dólar no bolso: entenda o que pressiona o USD/BRL "
            "e como isso afeta preços e investimentos."
        ),
        "Ações": (
            "Bolsa, empresas listadas, resultados e setores em destaque — análises com "
            "dados de mercado e contexto macro."
        ),
        "Juros": (
            "Selic, Copom e curva de juros: acompanhe decisões do Banco Central e o efeito "
            "no crédito, na poupança e na renda fixa."
        ),
        "Inflação": (
            "IPCA, preços ao consumidor e expectativas de inflação — o termômetro que orienta "
            "juros, salários e planejamento financeiro."
        ),
        "Imóveis": (
            "Financiamento, aluguel, crédito imobiliário e tendências do mercado de moradia "
            "no Brasil."
        ),
        "Fintech": (
            "Bancos digitais, pagamentos, open finance e inovação financeira com impacto "
            "direto na sua carteira."
        ),
        "Commodities": (
            "Petróleo, minério, agronegócio e commodities que influenciam exportações, "
            "câmbio e inflação no país."
        ),
        "Política Econômica": (
            "Reformas, arcabouço fiscal, gastos públicos e decisões de Brasília que "
            "repercutem nos mercados."
        ),
    },
    "en": {
        "Cripto": (
            "Bitcoin, altcoins, ETFs and crypto regulation in Brazil — market context, "
            "risk and real-world impact, without hype."
        ),
        "Economia": (
            "GDP, jobs, fiscal policy and indicators shaping the Brazilian economy, "
            "explained for investors and consumers."
        ),
        "Dólar": (
            "FX flows and USD/BRL drivers — what moves the exchange rate and how it "
            "affects prices and portfolios."
        ),
        "Ações": (
            "Equities, earnings and sectors in focus — analysis with market data and "
            "macro context."
        ),
        "Juros": (
            "Selic, Copom and the yield curve — Central Bank decisions and their effect "
            "on credit, savings and fixed income."
        ),
        "Inflação": (
            "IPCA, consumer prices and inflation expectations — the gauge behind rates, "
            "wages and financial planning."
        ),
        "Imóveis": (
            "Mortgages, rents and housing market trends across Brazil."
        ),
        "Fintech": (
            "Digital banks, payments, open finance and financial innovation that affects "
            "your wallet."
        ),
        "Commodities": (
            "Oil, metals, agribusiness and commodities that sway exports, FX and inflation."
        ),
        "Política Econômica": (
            "Reforms, fiscal rules and policy decisions from Brasília that ripple through markets."
        ),
    },
    "ja": {
        "Cripto": (
            "ビットコイン、オルトコイン、ETF、ブラジルの暗号資産規制を市場文脈とリスクの観点から解説します。"
        ),
        "Economia": (
            "GDP、雇用、財政、ブラジル経済の主要指標を投資家と消費者向けにわかりやすくまとめます。"
        ),
        "Dólar": (
            "為替フローとUSD/BRLの要因、物価と投資への影響を追います。"
        ),
        "Ações": (
            "株式、決算、注目セクターをマクロ文脈と市場データで分析します。"
        ),
        "Juros": (
            "セリック、コポム、イールドカーブと金融政策が与えるクレジット・貯蓄への影響を解説します。"
        ),
        "Inflação": (
            "IPCA、消費者物価、インフレ期待が金利と家計に与える影響を追跡します。"
        ),
        "Imóveis": (
            "住宅ローン、賃貸、ブラジルの不動産市場トレンドをカバーします。"
        ),
        "Fintech": (
            "デジタルバンク、決済、オープンファイナンスなど金融イノベーションを紹介します。"
        ),
        "Commodities": (
            "原油、金属、農産物など輸出・為替・インフレに効くコモディティを追います。"
        ),
        "Política Econômica": (
            "改革、財政ルール、政府の経済政策が市場に与える影響を解説します。"
        ),
    },
}

SENTIMENT_LABELS = {
    "pt": {"Positivo": "Positivo", "Negativo": "Negativo", "Neutro": "Neutro"},
    "en": {"Positivo": "Positive", "Negativo": "Negative", "Neutro": "Neutral"},
    "ja": {"Positivo": "強気", "Negativo": "弱気", "Neutro": "中立"},
}

# Strings de UI compartilhadas (nav, home, artigo, footer, overlays).
UI: dict[str, dict[str, str]] = {
    "pt": {
        "brand_finance": "CLAREZA",
        "brand_news": "CAPITAL",
        "site_name": "Clareza Capital",
        "meta_home_title": "Clareza Capital — análise e radar do mercado financeiro",
        "meta_home_og_title": "Clareza Capital — clareza no mercado de capitais",
        "meta_home_description": "Análises financeiras originais com dados do Banco Central, painel de mercado (Selic, IPCA, dólar, BTC), newsletter e metodologia transparente — Clareza Capital.",
        "meta_category_title": "{tag} | Clareza Capital — notícias e análises",
        "meta_category_og_title": "{tag} | Clareza Capital",
        "meta_category_description": "Cobertura de {tag} no Clareza Capital: análises com dados oficiais, contexto de mercado e impacto no bolso.",
        "meta_search_title": "Busca | Clareza Capital",
        "meta_brand_keywords": ", ".join(SITE_BRAND_KEYWORDS),
        "seo_topics_title": "Temas em destaque",
        "seo_discover_blurb": "No Clareza Capital: análises enriquecidas, radar /mercado (Selic, IPCA, dólar, euro, BTC), metodologia transparente, newsletter e cobertura PT/EN/JA.",
        "search_placeholder": "Pesquisar...",
        "latest": "Últimas",
        "editorial_selection": "Seleção editorial",
        "highlights_market": "Destaques do mercado",
        "highlights_in": "Destaques em {tag}",
        "analyses_with_data": "Análises com dados e contexto",
        "read_also": "Leia também",
        "headline_badge": "Importante",
        "headline_carousel_prev": "Manchete anterior",
        "headline_carousel_next": "Próxima manchete",
        "headline_carousel_aria": "Manchetes em destaque",
        "headline_carousel_go": "Ir para manchete {n}",
        "latest_analyses": "Últimas análises",
        "news_found": "Notícias encontradas",
        "most_recent_first": "Mais recentes primeiro",
        "results_for": "Resultados para:",
        "newsletter_ok": "✅ Inscrição registrada! Em breve você receberá nossas análises.",
        "no_news": "Nenhuma notícia encontrada",
        "no_news_in": " em ",
        "no_news_for": " para ",
        "see_other": "Confira outras análises recentes do portal:",
        "other_analyses": "Outras análises para você",
        "see_all": "Ver todas",
        "load_more": "Carregar mais",
        "loading": "Carregando...",
        "loading_market": "Carregando mercado...",
        "loading_quotes": "Carregando cotações do mercado...",
        "refining_title": "Refinando a análise",
        "refining_status": "Cruzando indicadores do período...",
        "ticker_aria": "Cotações do mercado",
        "back_home": "Voltar para a Home",
        "db_unavailable_title": "Portal temporariamente indisponível",
        "db_unavailable_body": "Não foi possível carregar as análises agora. Tente de novo em alguns segundos.",
        "db_unavailable_retry": "Tentar novamente",
        "db_stale_banner": "O banco está lento neste momento. Exibindo as últimas análises já carregadas.",
        "back": "Voltar",
        "footer_developed": "Desenvolvido por",
        "footer_tagline": "Análises financeiras com dados do Banco Central, cotações e cruzamento de fontes — Clareza Capital.",
        "footer_portal": "Portal",
        "footer_connect": "Conecte-se",
        "footer_guides": "Guias essenciais",
        "footer_about_title": "Sobre nós",
        "footer_about_blurb": "O Clareza Capital publica análises originais com dados de mercado e indicadores oficiais — clareza para entender o que move a economia e o mercado de capitais.",
        "footer_rights": "Todos os direitos reservados.",
        "footer_developer": "Punk Code Solution",
        "footer_guide_selic": "O que é a Selic",
        "footer_guide_ipca": "O que é o IPCA",
        "footer_guide_cambio": "Câmbio e dólar",
        "footer_guide_renda_fixa": "Renda fixa",
        "nav_about": "Quem Somos",
        "nav_methodology": "Metodologia",
        "nav_contact": "Contato",
        "editorial_byline": "Redação Clareza Capital — análise assistida por IA, cruzada com dados BCB/mercado",
        "editorial_byline_link": "Ver metodologia",
        "contact_page_meta_title": "Contato — Clareza Capital",
        "contact_page_meta_description": "Fale com a redação do Clareza Capital e com a Punk Code Solution. Canais oficiais, privacidade e metodologia editorial.",
        "contact_page_eyebrow": "Atendimento",
        "contact_page_title": "Contato",
        "contact_page_intro": "Use esta página para falar com a equipe responsável pelo portal Clareza Capital — correções, dúvidas editoriais, privacidade ou parcerias.",
        "contact_page_org": "Responsável técnico e jurídico",
        "contact_page_org_blurb": "O portal é desenvolvido e mantido pela Punk Code Solution. Contatos institucionais e site da empresa:",
        "contact_page_editorial": "Responsabilidade editorial",
        "contact_page_editorial_blurb": "Análises são produzidas com assistência de IA e cruzamento de dados oficiais (BCB, cotações). Correções e pedidos de esclarecimento podem ser enviados pelo formulário abaixo. Detalhes em Metodologia e Quem somos.",
        "contact_page_form_title": "Enviar mensagem",
        "contact_page_form_blurb": "O formulário abre um canal direto com a equipe. Não envie senhas nem dados sensíveis desnecessários.",
        "contact_page_policies": "Políticas",
        "nav_terms": "Termos de Uso",
        "nav_privacy": "Privacidade",
        "nav_market": "Mercado",
        "meta_market_title": "Mercado em tempo real | Selic, IPCA, dólar e Bitcoin — Clareza Capital",
        "meta_market_description": "Painel /mercado do Clareza Capital: Selic, IPCA, dólar, Bitcoin e histórico recente com dados oficiais do Banco Central.",
        "market_page_eyebrow": "Painel ao vivo",
        "market_page_title": "Mercado em tempo real",
        "market_page_blurb": "Selic, IPCA, câmbio e cripto com histórico recente — dados do Banco Central e cotações de mercado.",
        "market_selic": "Selic meta",
        "market_ipca": "IPCA 12 meses",
        "market_usd": "Dólar (USD/BRL)",
        "market_btc": "Bitcoin (BTC/BRL)",
        "market_history": "Histórico recente",
        "market_updated": "Atualizado em",
        "reading_time": "{n} min de leitura",
        "internal_refs_title": "Matérias relacionadas",
        "internal_refs_blurb": "Leituras do acervo citadas nesta análise",
        "affiliate_disclaimer": "Conteúdo patrocinado / afiliado",
        "lang_label": "Idioma",
        "lang_pt": "PT",
        "lang_en": "EN",
        "lang_ja": "JA",
        "content_original_notice": "Esta análise foi publicada originalmente em português. A interface está em {language}.",
        "content_lang_name": "português",
        "market_positive": "Mercado Positivo",
        "market_negative": "Mercado Negativo",
        "market_neutral": "Mercado Neutro",
        "market_overview": "Panorama de Mercado no Momento da Análise",
        "full_analysis": "Análise Completa",
        "pocket_impact": "Impacto no seu Bolso",
        "analysis_team": "Equipe de Análise · Clareza Capital",
        "source": "Fonte",
        "read_original": "Ler matéria original",
        "related": "Leia também",
        "faq_title": "Perguntas frequentes",
        "affiliate_disclaimer": "Link de afiliado/parceiro",
        "recommended_reading": "📚 Leitura Recomendada",
        "amazon_books_blurb": "Livros sobre finanças e investimentos na Amazon Brasil.",
        "amazon_books_cta": "Ver livros na Amazon →",
        "newsletter_title": "📬 Newsletter Clareza Capital",
        "newsletter_blurb": "Receba as principais análises e alertas de mercado no seu e-mail. Grátis.",
        "newsletter_subscribe": "Inscrever-se",
        "newsletter_cta": "Quero receber análises",
        "premium_teaser": "Inscreva-se na newsletter para ser avisado no lançamento.",
        "category_related_guides": "Guias para entender {tag}",
        "category_hub_heading": "Cobertura de {tag}",
        "about_title": "Quem Somos",
        "about_meta_title": "Quem somos | Clareza Capital — clareza no mercado",
        "about_meta_description": "Conheça o Clareza Capital: análises financeiras originais, painel de mercado, metodologia transparente e newsletter. Anteriormente Finanças News.",
        "privacy_title": "Política de Privacidade",
        "privacy_meta_title": "Política de Privacidade | Clareza Capital",
        "privacy_meta_description": "Saiba como o Clareza Capital coleta, utiliza e protege dados pessoais (LGPD).",
        "privacy_eyebrow": "Transparência e LGPD",
        "privacy_updated": "Última atualização: 17 de julho de 2026",
        "terms_title": "Termos de Uso",
        "terms_meta_title": "Termos de Uso | Clareza Capital",
        "terms_meta_description": "Condições de uso do portal Clareza Capital.",
        "terms_eyebrow": "Condições de uso",
        "terms_updated": "Última atualização: 17 de julho de 2026",
        "not_found": "Notícia não encontrada",
        "theme_toggle": "Alternar tema claro ou escuro",
        "try_again": "Tentar novamente",
        "customize_reading": "Personalize sua leitura",
        "customize_hint": "Escolha seu perfil para destacar orientações relevantes.",
        "profile_aria": "Perfil do leitor",
        "profile_beginner": "Iniciante",
        "profile_intermediate": "Intermediário",
        "profile_advanced": "Avançado",
        "profile_active": "Perfil ativo: {profile}. Clique em outro para alterar.",
        "published_on": "Publicado em",
        "data_backed_where": "Onde a análise se apoia nos dados",
        "practical_guide": "Guia prático",
        "pocket_impact_sub": "O que muda na sua carteira e no dia a dia",
        "listen_summary": "Ouvir resumo",
        "next_step_partner": "Próximo passo · Parceiro",
        "cross_links": "Links cruzados",
        "see_on_source": "Ver no {source}",
        "contact_us": "Fale conosco",
        "columnist_byline": "Coluna · {name}",
        "columnist_badge": "Colunista",
        "columnist_disclaimer_short": "Opinião do colunista. Não é recomendação de investimento. Conteúdo sujeito à moderação do Clareza Capital.",
        "columnist_apply_title": "Quero ser colunista",
        "columnist_apply_blurb": "Publique análises financeiras no Clareza Capital. Após aprovação, seus artigos passam por revisão editorial antes de ir ao ar.",
        "columnist_terms_link": "Leia os termos do programa",
        "columnist_pitch_label": "Apresentação",
        "columnist_pitch_placeholder": "Conte sua experiência e o tipo de análise que pretende publicar…",
        "columnist_apply_submit": "Enviar candidatura",
        "columnist_dashboard_title": "Painel do colunista",
        "columnist_dashboard_blurb": "Gerencie artigos, destaque pago e participação estimada na receita publicitária.",
        "columnist_new_article": "Novo artigo",
        "columnist_balance": "Saldo estimado",
        "columnist_share_note": "Participação estimada de cerca de {pct}% (pageviews × RPM do site).",
        "columnist_request_payout": "Solicitar saque PIX",
        "columnist_my_articles": "Meus artigos",
        "columnist_no_articles": "Nenhum artigo ainda.",
        "columnist_ledger": "Extrato da carteira",
        "columnist_editor_title": "Escrever análise",
        "columnist_boost": "Impulsionar",
        "nav_columnist": "Colunista",
        "contact_subject": "Assunto",
        "contact_description": "Descrição",
        "contact_send": "Enviar",
        "contact_close": "Fechar",
        "contact_cancel": "Cancelar",
        "contact_subject_placeholder": "Resumo em poucas palavras",
        "contact_description_placeholder": "Descreva sua mensagem",
        "contact_success": "Mensagem enviada.",
        "contact_error": "Não foi possível enviar. Tente novamente.",
        "contact_sending": "Enviando…",
        "contact_rate_limited": "Aguarde um momento antes de enviar novamente.",
        "contact_required": "Preencha todos os campos.",
        "contact_too_long": "Texto excede o limite permitido.",
        "original_site": "site original",
        "open_original": "Abrir reportagem original",
        "market_evidence": "Evidência de mercado",
        "data_at_analysis": "Dados no momento da análise",
        "collected_at": "Coletado em",
        "core_panel_hint": "Painel de referência: use Selic, IPCA, dólar e cotações da categoria só quando forem relevantes ao fato — com tendência 7 e 30 dias.",
        "analytical_lenses": "Lentes analíticas",
        "analytical_lenses_disclaimer": "Enquadramentos inspirados em escolas clássicas de investimento — paráfrase editorial original, sem citações literais.",
        "core_badge": "núcleo",
        "live_quotes": "Cotações em tempo real",
        "quotes_realtime": "Cotações em tempo real...",
        "key_points": "Pontos-chave da análise",
        "editorial_method": "Método editorial",
        "see_more_in": "Ver mais em {tag}",
        "urgency": "Urgência",
        "audience": "Público",
        "horizon": "Horizonte",
        "confidence": "Confiança",
        "editorial_methodology": "Metodologia editorial",
        "sources_cited": "fontes de dados citadas",
        "analyses_in_archive": "análises no acervo desta categoria",
        "collection_at": "Coleta em",
        "market_update": "Atualização de mercado",
        "analysis_version": "Versão da análise: v{version}",
        "snapshot_at_publish": "Snapshot na publicação",
        "var_24h": "Var. 24h",
        "values_collected_at": "Valores coletados em",
        "timeline": "Linha do tempo",
        "projected_scenarios": "Cenários projetados",
        "investor_guidance": "Orientação por perfil de investidor",
        "comparative": "Comparativo",
        "glossary": "Glossário",
        "archive_context": "Contexto do acervo",
        "analyses_about": "{count} análises sobre",
        "related_stories": "Matérias relacionadas",
        "see_category": "Ver categoria →",
        "positive_count": "positivas",
        "negative_count": "negativas",
        "neutral_count": "neutras",
        "read_also_deepen": "Para aprofundar — leia também",
        "no_other_in_category": "Ainda não há outras matérias nesta categoria para comparar — volte após novas publicações.",
        "archive_sentiment": "Sentimento no acervo",
        "dominant_tone": "Tom dominante:",
        "explore_by_theme": "Explore por tema",
        "related_themes": "Temas relacionados",
        "premium_soon": "Em breve · Premium",
        "refining_step_1": "Cruzando indicadores do período...",
        "refining_step_2": "Alinhando cotações à data da análise...",
        "refining_step_3": "Organizando pontos-chave e contexto...",
        "refining_step_4": "Quase pronto — abrindo a leitura...",
        "prob_high": "alta",
        "prob_medium": "média",
        "prob_low": "baixa",
        "urgency_high": "Alta",
        "urgency_medium": "Média",
        "urgency_low": "Baixa",
        "ref_label": "Ref.",
        "chart_base": "Base gráfica da análise",
        "chart_history": "Histórico que sustentou o raciocínio",
        "listen_stop": "Parar",
        "highlighting_profile": "Destacando: {profile}",
        "learn_more": "Saiba mais →",
    },
    "en": {
        "brand_finance": "CLAREZA",
        "brand_news": "CAPITAL",
        "site_name": "Clareza Capital",
        "meta_home_title": "Clareza Capital — financial analysis and market radar",
        "meta_home_og_title": "Clareza Capital — clarity for capital markets",
        "meta_home_description": "Original financial analysis with Central Bank data, live market board (Selic, IPCA, USD, BTC), newsletter and transparent methodology — Clareza Capital.",
        "meta_category_title": "{tag} | Clareza Capital — news and analysis",
        "meta_category_og_title": "{tag} | Clareza Capital",
        "meta_category_description": "{tag} coverage on Clareza Capital: data-backed analysis, market context and practical impact.",
        "meta_search_title": "Search | Clareza Capital",
        "meta_brand_keywords": ", ".join(SITE_BRAND_KEYWORDS),
        "seo_topics_title": "Featured topics",
        "seo_discover_blurb": "On Clareza Capital: enriched analysis, /mercado radar (Selic, IPCA, USD, EUR, BTC), transparent methodology, newsletter and PT/EN/JA coverage.",
        "search_placeholder": "Search...",
        "latest": "Latest",
        "editorial_selection": "Editorial picks",
        "highlights_market": "Market highlights",
        "highlights_in": "Highlights in {tag}",
        "analyses_with_data": "Data-backed analysis",
        "read_also": "Read also",
        "headline_badge": "Breaking",
        "headline_carousel_prev": "Previous headline",
        "headline_carousel_next": "Next headline",
        "headline_carousel_aria": "Featured headlines",
        "headline_carousel_go": "Go to headline {n}",
        "latest_analyses": "Latest analysis",
        "news_found": "Matching stories",
        "most_recent_first": "Newest first",
        "results_for": "Results for:",
        "newsletter_ok": "✅ Subscription saved! You will receive our analyses soon.",
        "no_news": "No stories found",
        "no_news_in": " in ",
        "no_news_for": " for ",
        "see_other": "Check other recent analyses on the portal:",
        "other_analyses": "More analysis for you",
        "see_all": "See all",
        "load_more": "Load more",
        "loading": "Loading...",
        "loading_market": "Loading markets...",
        "loading_quotes": "Loading market quotes...",
        "refining_title": "Refining the analysis",
        "refining_status": "Cross-checking period indicators...",
        "ticker_aria": "Market quotes",
        "back_home": "Back to Home",
        "db_unavailable_title": "Site temporarily unavailable",
        "db_unavailable_body": "We could not load the latest analysis right now. Please try again in a few seconds.",
        "db_unavailable_retry": "Try again",
        "db_stale_banner": "The database is slow right now. Showing the latest analyses already loaded.",
        "back": "Back",
        "footer_developed": "Built by",
        "footer_tagline": "Financial analysis with central-bank data, market quotes and multi-source context — Clareza Capital.",
        "footer_portal": "Site",
        "footer_connect": "Connect",
        "footer_guides": "Essential guides",
        "footer_about_title": "About us",
        "footer_about_blurb": "Clareza Capital publishes original analysis with market data and official indicators — clarity to understand what moves the economy and capital markets.",
        "footer_rights": "All rights reserved.",
        "footer_developer": "Punk Code Solution",
        "footer_guide_selic": "What is Selic",
        "footer_guide_ipca": "What is IPCA",
        "footer_guide_cambio": "FX and the dollar",
        "footer_guide_renda_fixa": "Fixed income",
        "nav_about": "About Us",
        "nav_methodology": "Methodology",
        "nav_contact": "Contact",
        "editorial_byline": "Clareza Capital desk — AI-assisted analysis cross-checked with central-bank and market data",
        "editorial_byline_link": "See methodology",
        "contact_page_meta_title": "Contact — Clareza Capital",
        "contact_page_meta_description": "Reach the Clareza Capital editorial team and Punk Code Solution. Official channels, privacy and editorial methodology.",
        "contact_page_eyebrow": "Support",
        "contact_page_title": "Contact",
        "contact_page_intro": "Use this page to contact the team behind Clareza Capital — corrections, editorial questions, privacy or partnerships.",
        "contact_page_org": "Technical and legal contact",
        "contact_page_org_blurb": "The portal is built and maintained by Punk Code Solution. Company site:",
        "contact_page_editorial": "Editorial responsibility",
        "contact_page_editorial_blurb": "Analyses are produced with AI assistance and official data (central bank, market quotes). Corrections can be sent via the form below. Details in Methodology and About.",
        "contact_page_form_title": "Send a message",
        "contact_page_form_blurb": "The form opens a direct channel with the team. Do not send passwords or unnecessary sensitive data.",
        "contact_page_policies": "Policies",
        "nav_terms": "Terms of Use",
        "nav_privacy": "Privacy",
        "nav_market": "Markets",
        "meta_market_title": "Live markets | Selic, IPCA, USD and Bitcoin — Clareza Capital",
        "meta_market_description": "Clareza Capital /mercado board: Selic, IPCA, USD/BRL, Bitcoin and recent history from official sources.",
        "market_page_eyebrow": "Live board",
        "market_page_title": "Markets in real time",
        "market_page_blurb": "Selic, IPCA, FX and crypto with recent history — Central Bank data and market quotes.",
        "market_selic": "Selic target",
        "market_ipca": "IPCA 12 months",
        "market_usd": "US Dollar (USD/BRL)",
        "market_btc": "Bitcoin (BTC/BRL)",
        "market_history": "Recent history",
        "market_updated": "Updated at",
        "reading_time": "{n} min read",
        "internal_refs_title": "Related stories",
        "internal_refs_blurb": "Archive pieces cited in this analysis",
        "affiliate_disclaimer": "Sponsored / affiliate content",
        "lang_label": "Language",
        "lang_pt": "PT",
        "lang_en": "EN",
        "lang_ja": "JA",
        "content_original_notice": "This analysis was originally published in Portuguese. The interface is in {language}.",
        "content_lang_name": "English",
        "market_positive": "Positive Market",
        "market_negative": "Negative Market",
        "market_neutral": "Neutral Market",
        "market_overview": "Market Snapshot at Analysis Time",
        "full_analysis": "Full Analysis",
        "pocket_impact": "Impact on Your Wallet",
        "analysis_team": "Analysis Desk · Clareza Capital",
        "source": "Source",
        "read_original": "Read original story",
        "related": "Related reading",
        "faq_title": "Frequently asked questions",
        "affiliate_disclaimer": "Affiliate / partner link",
        "recommended_reading": "📚 Recommended Reading",
        "amazon_books_blurb": "Finance and investing books on Amazon Brazil.",
        "amazon_books_cta": "See books on Amazon →",
        "newsletter_title": "📬 Clareza Capital Newsletter",
        "newsletter_blurb": "Get the main market analyses and alerts in your inbox. Free.",
        "newsletter_subscribe": "Subscribe",
        "newsletter_cta": "Send me analyses",
        "premium_teaser": "Subscribe to the newsletter to get launch updates.",
        "category_related_guides": "Guides to understand {tag}",
        "category_hub_heading": "{tag} coverage",
        "about_title": "About Us",
        "about_meta_title": "About us | Clareza Capital — clarity for markets",
        "about_meta_description": "About Clareza Capital: original financial analysis, market board, transparent methodology and newsletter. Formerly Finanças News.",
        "privacy_title": "Privacy Policy",
        "privacy_meta_title": "Privacy Policy | Clareza Capital",
        "privacy_meta_description": "How Clareza Capital collects, uses and protects personal data.",
        "privacy_eyebrow": "Transparency & data protection",
        "privacy_updated": "Last updated: July 17, 2026",
        "terms_title": "Terms of Use",
        "terms_meta_title": "Terms of Use | Clareza Capital",
        "terms_meta_description": "Terms governing the use of Clareza Capital.",
        "terms_eyebrow": "Terms of use",
        "terms_updated": "Last updated: July 17, 2026",
        "not_found": "Story not found",
        "theme_toggle": "Toggle light or dark theme",
        "try_again": "Try again",
        "customize_reading": "Personalize your reading",
        "customize_hint": "Choose your profile to highlight relevant guidance.",
        "profile_aria": "Reader profile",
        "profile_beginner": "Beginner",
        "profile_intermediate": "Intermediate",
        "profile_advanced": "Advanced",
        "profile_active": "Active profile: {profile}. Click another to change.",
        "published_on": "Published on",
        "data_backed_where": "Where the analysis draws on data",
        "practical_guide": "Practical guide",
        "pocket_impact_sub": "What changes in your portfolio and daily life",
        "listen_summary": "Listen to summary",
        "next_step_partner": "Next step · Partner",
        "cross_links": "Cross links",
        "see_on_source": "View on {source}",
        "contact_us": "Contact us",
        "columnist_byline": "Column · {name}",
        "columnist_badge": "Columnist",
        "columnist_disclaimer_short": "Columnist opinion. Not investment advice. Moderated by Clareza Capital.",
        "columnist_apply_title": "Become a columnist",
        "columnist_apply_blurb": "Publish financial analysis on Clareza Capital. After approval, articles are reviewed before going live.",
        "columnist_terms_link": "Read the program terms",
        "columnist_pitch_label": "Pitch",
        "columnist_pitch_placeholder": "Share your background and the analysis you want to publish…",
        "columnist_apply_submit": "Submit application",
        "columnist_dashboard_title": "Columnist dashboard",
        "columnist_dashboard_blurb": "Manage articles, paid boosts and estimated ad-revenue share.",
        "columnist_new_article": "New article",
        "columnist_balance": "Estimated balance",
        "columnist_share_note": "Estimated share around {pct}% (pageviews × site RPM).",
        "columnist_request_payout": "Request PIX payout",
        "columnist_my_articles": "My articles",
        "columnist_no_articles": "No articles yet.",
        "columnist_ledger": "Wallet ledger",
        "columnist_editor_title": "Write analysis",
        "columnist_boost": "Boost",
        "nav_columnist": "Columnist",
        "contact_subject": "Subject",
        "contact_description": "Description",
        "contact_send": "Send",
        "contact_close": "Close",
        "contact_cancel": "Cancel",
        "contact_subject_placeholder": "Short summary",
        "contact_description_placeholder": "Describe your message",
        "contact_success": "Message sent.",
        "contact_error": "Could not send. Please try again.",
        "contact_sending": "Sending…",
        "contact_rate_limited": "Please wait a moment before sending again.",
        "contact_required": "Please fill in all fields.",
        "contact_too_long": "Text exceeds the allowed limit.",
        "original_site": "original site",
        "open_original": "Open original story",
        "market_evidence": "Market evidence",
        "data_at_analysis": "Data at analysis time",
        "collected_at": "Collected at",
        "core_panel_hint": "Reference panel: use Selic, IPCA, USD and category quotes only when relevant to the story — with 7d/30d trend.",
        "analytical_lenses": "Analytical lenses",
        "analytical_lenses_disclaimer": "Frameworks inspired by classic investment schools — original editorial paraphrase, no literal quotes.",
        "core_badge": "core",
        "live_quotes": "Live quotes",
        "quotes_realtime": "Live market quotes...",
        "key_points": "Key takeaways",
        "editorial_method": "Editorial method",
        "see_more_in": "See more in {tag}",
        "urgency": "Urgency",
        "audience": "Audience",
        "horizon": "Horizon",
        "confidence": "Confidence",
        "editorial_methodology": "Editorial methodology",
        "sources_cited": "cited data sources",
        "analyses_in_archive": "analyses in this category archive",
        "collection_at": "Collected at",
        "market_update": "Market update",
        "analysis_version": "Analysis version: v{version}",
        "snapshot_at_publish": "Snapshot at publication",
        "var_24h": "24h change",
        "values_collected_at": "Values collected at",
        "timeline": "Timeline",
        "projected_scenarios": "Projected scenarios",
        "investor_guidance": "Guidance by investor profile",
        "comparative": "Comparison",
        "glossary": "Glossary",
        "archive_context": "Archive context",
        "analyses_about": "{count} analyses on",
        "related_stories": "Related stories",
        "see_category": "View category →",
        "positive_count": "positive",
        "negative_count": "negative",
        "neutral_count": "neutral",
        "read_also_deepen": "Go deeper — related reading",
        "no_other_in_category": "No other stories in this category yet — check back after new publications.",
        "archive_sentiment": "Archive sentiment",
        "dominant_tone": "Dominant tone:",
        "explore_by_theme": "Explore by theme",
        "related_themes": "Related themes",
        "premium_soon": "Coming soon · Premium",
        "refining_step_1": "Cross-checking period indicators...",
        "refining_step_2": "Aligning quotes to the analysis date...",
        "refining_step_3": "Organizing key points and context...",
        "refining_step_4": "Almost ready — opening the story...",
        "prob_high": "high",
        "prob_medium": "medium",
        "prob_low": "low",
        "urgency_high": "High",
        "urgency_medium": "Medium",
        "urgency_low": "Low",
        "ref_label": "As of",
        "chart_base": "Chart basis of the analysis",
        "chart_history": "History that supported the reasoning",
        "listen_stop": "Stop",
        "highlighting_profile": "Highlighting: {profile}",
        "learn_more": "Learn more →",
    },
    "ja": {
        "brand_finance": "CLAREZA",
        "brand_news": "CAPITAL",
        "site_name": "Clareza Capital",
        "meta_home_title": "Clareza Capital — 金融分析とマーケットレーダー",
        "meta_home_og_title": "Clareza Capital — 資本市場への明瞭さ",
        "meta_home_description": "中央銀行データに基づく独自の金融分析、市場パネル（Selic・IPCA・ドル・BTC）、ニュースレターと透明な手法 — Clareza Capital。",
        "meta_category_title": "{tag} | Clareza Capital — ニュースと分析",
        "meta_category_og_title": "{tag} | Clareza Capital",
        "meta_category_description": "Clareza Capitalの{tag}：公式データに基づく分析、市場コンテキスト、実務への影響。",
        "meta_search_title": "検索 | Clareza Capital",
        "meta_brand_keywords": ", ".join(SITE_BRAND_KEYWORDS),
        "seo_topics_title": "注目トピック",
        "seo_discover_blurb": "Clareza Capital：充実した分析、/mercadoレーダー（Selic・IPCA・ドル・ユーロ・BTC）、透明な手法、ニュースレター、PT/EN/JA対応。",
        "search_placeholder": "検索...",
        "latest": "最新",
        "editorial_selection": "編集部セレクト",
        "highlights_market": "市場の注目記事",
        "highlights_in": "{tag}の注目記事",
        "analyses_with_data": "データに基づく分析",
        "read_also": "あわせて読みたい",
        "headline_badge": "重要",
        "headline_carousel_prev": "前の見出し",
        "headline_carousel_next": "次の見出し",
        "headline_carousel_aria": "注目の見出し",
        "headline_carousel_go": "見出し {n} へ",
        "latest_analyses": "最新の分析",
        "news_found": "検索結果",
        "most_recent_first": "新しい順",
        "results_for": "検索結果:",
        "newsletter_ok": "✅ 登録が完了しました。まもなく分析をお届けします。",
        "no_news": "記事が見つかりませんでした",
        "no_news_in": "（カテゴリ: ",
        "no_news_for": "（検索: ",
        "see_other": "ポータルの他の最新分析をご覧ください:",
        "other_analyses": "おすすめの分析",
        "see_all": "すべて見る",
        "load_more": "もっと読み込む",
        "loading": "読み込み中...",
        "loading_market": "市場を読み込み中...",
        "loading_quotes": "相場を読み込み中...",
        "refining_title": "分析を精緻化中",
        "refining_status": "期間の指標を照合しています...",
        "ticker_aria": "市場相場",
        "back_home": "ホームに戻る",
        "db_unavailable_title": "サイトは一時的に利用できません",
        "db_unavailable_body": "分析を読み込めませんでした。数秒後にもう一度お試しください。",
        "db_unavailable_retry": "再試行",
        "db_stale_banner": "データベースが遅いため、すでに読み込まれた最新の分析を表示しています。",
        "back": "戻る",
        "footer_developed": "開発:",
        "footer_tagline": "中央銀行データ・相場・複数ソースに基づく金融分析 — Clareza Capital。",
        "footer_portal": "サイト",
        "footer_connect": "つながる",
        "footer_guides": "基本ガイド",
        "footer_about_title": "私たちについて",
        "footer_about_blurb": "Clareza Capitalは市場データと公式指標に基づく独自分析を公開し、経済と資本市場の動きを明瞭に伝えます。",
        "footer_rights": "全著作権所有。",
        "footer_developer": "Punk Code Solution",
        "footer_guide_selic": "Selicとは",
        "footer_guide_ipca": "IPCAとは",
        "footer_guide_cambio": "為替とドル",
        "footer_guide_renda_fixa": "固定金利",
        "nav_about": "私たちについて",
        "nav_methodology": "編集方針",
        "nav_contact": "お問い合わせ",
        "editorial_byline": "Clareza Capital編集部 — AI支援の分析を中央銀行・市場データと照合",
        "editorial_byline_link": "編集方針を見る",
        "contact_page_meta_title": "お問い合わせ — Clareza Capital",
        "contact_page_meta_description": "Clareza Capital編集部とPunk Code Solutionへの連絡先。プライバシーと編集方針。",
        "contact_page_eyebrow": "サポート",
        "contact_page_title": "お問い合わせ",
        "contact_page_intro": "訂正、編集に関する質問、プライバシー、提携など、Clareza Capital運営へのご連絡はこちらから。",
        "contact_page_org": "技術・法務の窓口",
        "contact_page_org_blurb": "本サイトはPunk Code Solutionが開発・運営しています。企業サイト：",
        "contact_page_editorial": "編集責任",
        "contact_page_editorial_blurb": "分析はAI支援と公式データ（中央銀行・相場）を組み合わせて作成します。訂正は下記フォームから。詳細は編集方針と会社概要をご覧ください。",
        "contact_page_form_title": "メッセージを送る",
        "contact_page_form_blurb": "フォームからチームに直接送れます。パスワードなど不要な機微情報は送らないでください。",
        "contact_page_policies": "ポリシー",
        "nav_terms": "利用規約",
        "nav_privacy": "プライバシー",
        "nav_market": "マーケット",
        "meta_market_title": "リアルタイム市場 | Selic・IPCA・ドル・ビットコイン — Clareza Capital",
        "meta_market_description": "Clareza Capitalの/mercadoパネル：Selic、IPCA、ドル、ビットコインと公式データの履歴。",
        "market_page_eyebrow": "ライブパネル",
        "market_page_title": "リアルタイム市場",
        "market_page_blurb": "Selic、IPCA、為替、暗号資産の最新データと履歴。",
        "market_selic": "Selic目標",
        "market_ipca": "IPCA 12ヶ月",
        "market_usd": "ドル (USD/BRL)",
        "market_btc": "ビットコイン (BTC/BRL)",
        "market_history": "直近の推移",
        "market_updated": "更新日時",
        "reading_time": "読了目安 {n} 分",
        "internal_refs_title": "関連記事",
        "internal_refs_blurb": "この分析で参照したアーカイブ記事",
        "affiliate_disclaimer": "スポンサード / アフィリエイト",
        "lang_label": "言語",
        "lang_pt": "PT",
        "lang_en": "EN",
        "lang_ja": "JA",
        "content_original_notice": "この分析はポルトガル語で公開されています。現在の表示言語は{language}です。",
        "content_lang_name": "日本語",
        "market_positive": "強気相場",
        "market_negative": "弱気相場",
        "market_neutral": "中立相場",
        "market_overview": "分析時点の市場概況",
        "full_analysis": "詳細分析",
        "pocket_impact": "家計への影響",
        "analysis_team": "分析チーム · Clareza Capital",
        "source": "出典",
        "read_original": "元記事を読む",
        "related": "関連記事",
        "faq_title": "よくある質問",
        "affiliate_disclaimer": "アフィリエイト／提携リンク",
        "recommended_reading": "📚 おすすめの読書",
        "amazon_books_blurb": "Amazonブラジルの金融・投資関連書籍。",
        "amazon_books_cta": "Amazonで本を見る →",
        "newsletter_title": "📬 Clareza Capital ニュースレター",
        "newsletter_blurb": "主要分析と市場アラートをメールで無料配信。",
        "newsletter_subscribe": "登録する",
        "newsletter_cta": "分析を受け取る",
        "premium_teaser": "ローンチ情報を受け取るにはニュースレターに登録してください。",
        "category_related_guides": "{tag}を理解するためのガイド",
        "category_hub_heading": "{tag}の特集",
        "about_title": "私たちについて",
        "about_meta_title": "私たちについて | Clareza Capital — 市場への明瞭さ",
        "about_meta_description": "Clareza Capital：独自の金融分析、市場パネル、透明な手法、ニュースレター。旧称 Finanças News。",
        "privacy_title": "プライバシーポリシー",
        "privacy_meta_title": "プライバシーポリシー | Clareza Capital",
        "privacy_meta_description": "Clareza Capitalによる個人データの収集・利用・保護について。",
        "privacy_eyebrow": "透明性とデータ保護",
        "privacy_updated": "最終更新: 2026年7月17日",
        "terms_title": "利用規約",
        "terms_meta_title": "利用規約 | Clareza Capital",
        "terms_meta_description": "Clareza Capitalポータルの利用条件。",
        "terms_eyebrow": "利用条件",
        "terms_updated": "最終更新: 2026年7月17日",
        "not_found": "記事が見つかりません",
        "theme_toggle": "ライト／ダークテーマを切り替え",
        "try_again": "再試行",
        "customize_reading": "読み方をカスタマイズ",
        "customize_hint": "プロフィールを選ぶと、関連する指針が強調されます。",
        "profile_aria": "読者プロフィール",
        "profile_beginner": "初心者",
        "profile_intermediate": "中級",
        "profile_advanced": "上級",
        "profile_active": "有効プロフィール: {profile}。別のものをクリックして変更。",
        "published_on": "公開日",
        "data_backed_where": "分析が依拠するデータ",
        "practical_guide": "実践ガイド",
        "pocket_impact_sub": "資産と日常への影響",
        "listen_summary": "要約を聞く",
        "next_step_partner": "次の一歩 · パートナー",
        "cross_links": "関連リンク",
        "see_on_source": "{source}で見る",
        "contact_us": "お問い合わせ",
        "columnist_byline": "コラム · {name}",
        "columnist_badge": "コラムニスト",
        "columnist_disclaimer_short": "コラムニストの見解です。投資助言ではありません。Clareza Capitalが審査します。",
        "columnist_apply_title": "コラムニストになる",
        "columnist_apply_blurb": "Clareza Capitalで金融分析を公開できます。承認後、公開前に編集審査があります。",
        "columnist_terms_link": "プログラム規約を読む",
        "columnist_pitch_label": "自己紹介",
        "columnist_pitch_placeholder": "経験と書きたい分析について…",
        "columnist_apply_submit": "応募する",
        "columnist_dashboard_title": "コラムニスト管理",
        "columnist_dashboard_blurb": "記事、有料ブースト、推定広告収益の分配を管理します。",
        "columnist_new_article": "新規記事",
        "columnist_balance": "推定残高",
        "columnist_share_note": "推定分配は約{pct}%（PV×サイトRPM）。",
        "columnist_request_payout": "PIX出金を申請",
        "columnist_my_articles": "自分の記事",
        "columnist_no_articles": "まだ記事がありません。",
        "columnist_ledger": "ウォレット明細",
        "columnist_editor_title": "分析を書く",
        "columnist_boost": "ブースト",
        "nav_columnist": "コラム",
        "contact_subject": "件名",
        "contact_description": "内容",
        "contact_send": "送信",
        "contact_close": "閉じる",
        "contact_cancel": "キャンセル",
        "contact_subject_placeholder": "短い要約",
        "contact_description_placeholder": "メッセージを書いてください",
        "contact_success": "メッセージを送信しました。",
        "contact_error": "送信できませんでした。もう一度お試しください。",
        "contact_sending": "送信中…",
        "contact_rate_limited": "しばらく待ってから再度送信してください。",
        "contact_required": "すべての項目を入力してください。",
        "contact_too_long": "文字数の上限を超えています。",
        "original_site": "元サイト",
        "open_original": "元記事を開く",
        "market_evidence": "市場の根拠",
        "data_at_analysis": "分析時点のデータ",
        "collected_at": "取得日時",
        "core_panel_hint": "参照パネル：記事に関連する場合のみ Selic、IPCA、ドル、カテゴリ相場を使用 — 7日/30日の推移付き。",
        "analytical_lenses": "分析レンズ",
        "analytical_lenses_disclaimer": "古典的な投資学派に着想を得た枠組み — 独自の編集要約であり、逐語引用はありません。",
        "core_badge": "核心",
        "live_quotes": "リアルタイム相場",
        "quotes_realtime": "リアルタイム相場を読み込み中...",
        "key_points": "分析の要点",
        "editorial_method": "編集手法",
        "see_more_in": "{tag}でもっと見る",
        "urgency": "緊急度",
        "audience": "対象",
        "horizon": "時間軸",
        "confidence": "信頼度",
        "editorial_methodology": "編集の方法論",
        "sources_cited": "件のデータソースを引用",
        "analyses_in_archive": "件の同カテゴリ分析",
        "collection_at": "取得",
        "market_update": "市場アップデート",
        "analysis_version": "分析バージョン: v{version}",
        "snapshot_at_publish": "公開時スナップショット",
        "var_24h": "24時間変動",
        "values_collected_at": "数値取得日時",
        "timeline": "タイムライン",
        "projected_scenarios": "想定シナリオ",
        "investor_guidance": "投資家プロフィール別の指針",
        "comparative": "比較",
        "glossary": "用語集",
        "archive_context": "アーカイブの文脈",
        "analyses_about": "{count}件の分析:",
        "related_stories": "関連記事",
        "see_category": "カテゴリを見る →",
        "positive_count": "強気",
        "negative_count": "弱気",
        "neutral_count": "中立",
        "read_also_deepen": "さらに深く — 関連記事",
        "no_other_in_category": "このカテゴリに比較できる他の記事はまだありません。新しい公開をお待ちください。",
        "archive_sentiment": "アーカイブのセンチメント",
        "dominant_tone": "支配的なトーン:",
        "explore_by_theme": "テーマで探す",
        "related_themes": "関連テーマ",
        "premium_soon": "近日公開 · Premium",
        "refining_step_1": "期間の指標を照合しています...",
        "refining_step_2": "分析日の相場を揃えています...",
        "refining_step_3": "要点と文脈を整理しています...",
        "refining_step_4": "まもなく完了 — 記事を開きます...",
        "prob_high": "高",
        "prob_medium": "中",
        "prob_low": "低",
        "urgency_high": "高",
        "urgency_medium": "中",
        "urgency_low": "低",
        "ref_label": "基準",
        "chart_base": "分析のチャート根拠",
        "chart_history": "推論を支えた履歴",
        "listen_stop": "停止",
        "highlighting_profile": "強調中: {profile}",
        "learn_more": "詳しく見る →",
    },
}

LOCALE_FOR_NUMBERS = {
    "pt": "pt-BR",
    "en": "en-US",
    "ja": "ja-JP",
}


def normalize_lang(raw: str | None) -> str:
    if not raw:
        return DEFAULT_LANG
    code = raw.strip().lower().replace("_", "-")
    if code.startswith("pt"):
        return "pt"
    if code.startswith("en"):
        return "en"
    if code.startswith("ja") or code.startswith("jp"):
        return "ja"
    if code in SUPPORTED_LANGS:
        return code
    return DEFAULT_LANG


def resolve_lang(request: Request) -> str:
    query_lang = request.query_params.get("lang")
    if query_lang:
        return normalize_lang(query_lang)

    cookie_lang = request.cookies.get(COOKIE_NAME)
    if cookie_lang:
        return normalize_lang(cookie_lang)

    accept = request.headers.get("accept-language", "")
    for part in accept.split(","):
        token = part.split(";")[0].strip()
        if not token:
            continue
        candidate = normalize_lang(token)
        if candidate in SUPPORTED_LANGS and token.lower().startswith(candidate):
            return candidate
        if token.lower().startswith("ja") or token.lower().startswith("en") or token.lower().startswith("pt"):
            return normalize_lang(token)
    return DEFAULT_LANG


def translate(lang: str, key: str, **kwargs: Any) -> str:
    bundle = UI.get(lang) or UI[DEFAULT_LANG]
    text = bundle.get(key) or UI[DEFAULT_LANG].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def translate_tag(lang: str, tag: object) -> str:
    raw = str(tag or "Economia")
    return TAG_LABELS.get(lang, TAG_LABELS[DEFAULT_LANG]).get(raw, raw)


def category_intro(lang: str, tag: object) -> str | None:
    """Texto introdutório editorial da categoria ativa na home."""
    raw = str(tag or "").strip()
    if not raw:
        return None
    bundle = CATEGORY_INTROS.get(lang) or CATEGORY_INTROS[DEFAULT_LANG]
    return bundle.get(raw) or CATEGORY_INTROS[DEFAULT_LANG].get(raw)


def translate_sentiment(lang: str, sentiment: object) -> str:
    raw = str(sentiment or "Neutro").strip()
    # Aceita variações já traduzidas ou minúsculas.
    for source, labels in SENTIMENT_LABELS.items():
        for pt_key, label in labels.items():
            if raw.lower() == pt_key.lower() or raw.lower() == label.lower():
                return SENTIMENT_LABELS.get(lang, SENTIMENT_LABELS[DEFAULT_LANG]).get(pt_key, raw)
    # Heurística para strings compostas ("Mercado Positivo").
    lowered = raw.lower()
    if "positiv" in lowered or "positive" in lowered or "強気" in raw:
        return SENTIMENT_LABELS[lang]["Positivo"]
    if "negativ" in lowered or "negative" in lowered or "弱気" in raw:
        return SENTIMENT_LABELS[lang]["Negativo"]
    return SENTIMENT_LABELS[lang]["Neutro"]


def market_sentiment_label(lang: str, sentiment: object) -> str:
    base = translate_sentiment(lang, sentiment)
    mapping = {
        "pt": {"Positivo": "market_positive", "Negativo": "market_negative", "Neutro": "market_neutral"},
        "en": {"Positive": "market_positive", "Negative": "market_negative", "Neutral": "market_neutral"},
        "ja": {"強気": "market_positive", "弱気": "market_negative", "中立": "market_neutral"},
    }
    keys = mapping.get(lang, mapping["pt"])
    for label, key in keys.items():
        if base == label:
            return translate(lang, key)
    return translate(lang, "market_neutral")


def translate_probability(lang: str, value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("alta", "high", "高"):
        return translate(lang, "prob_high")
    if raw in ("baixa", "low", "低"):
        return translate(lang, "prob_low")
    if raw in ("média", "media", "medium", "中"):
        return translate(lang, "prob_medium")
    return str(value or "")


def translate_urgency(lang: str, value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("alta", "high", "高"):
        return translate(lang, "urgency_high")
    if raw in ("baixa", "low", "低"):
        return translate(lang, "urgency_low")
    if raw in ("média", "media", "medium", "中"):
        return translate(lang, "urgency_medium")
    return str(value or "")


def apply_lang_to_relative_url(url: str, lang: str) -> str:
    """Mantém path+query; PT remove lang; EN/JA definem ?lang=."""
    raw = (url or "/").strip() or "/"
    parts = urlsplit(raw)
    path = parts.path or "/"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k != "lang"
    ]
    code = normalize_lang(lang)
    if code != DEFAULT_LANG:
        query.append(("lang", code))
    encoded = urlencode(query)
    return urlunsplit(("", "", path, encoded, ""))


def lang_switch_url(request: Request, target_lang: str) -> str:
    """Seletor: /idioma/{code} grava cookie e redireciona (vence Accept-Language)."""
    path = request.url.path or "/"
    if path.startswith("/idioma"):
        path = "/"
    params = {k: v for k, v in request.query_params.items() if k != "lang"}
    current = f"{path}?{urlencode(params)}" if params else path
    code = normalize_lang(target_lang)
    return f"/idioma/{code}?{urlencode({'next': current})}"


def localized_path(path: str, lang: str) -> str:
    """Link interno: PT sem query; EN/JA com ?lang=."""
    base = (path or "/").strip() or "/"
    if not lang or lang == DEFAULT_LANG:
        return base
    sep = "&" if "?" in base else "?"
    if "lang=" in base:
        return base
    return f"{base}{sep}lang={lang}"


def absolute_url(site_origin: str, path: str, query: dict[str, str] | None = None) -> str:
    """Monta URL absoluta; query vazia → sem '?'."""
    normalized = path if path.startswith("/") else f"/{path}"
    if not query:
        return f"{site_origin}{normalized}"
    return f"{site_origin}{normalized}?{urlencode(query)}"


def canonical_query_params(request: Request, path: str) -> tuple[dict[str, str], bool]:
    """Query permitida na canônica + flag noindex.

    - Busca (?q=) ou paginação legada (?page=): noindex; canônica limpa.
    - Categoria válida só na home: mantém ?categoria= na canônica.
    - lang/utm/newsletter/page: nunca entram na canônica.
    """
    params = request.query_params
    q = (params.get("q") or "").strip()
    page = (params.get("page") or "").strip()
    if q or page:
        # Paginação antiga (?page=) e busca: não indexar; consolidar sinais na URL limpa.
        out: dict[str, str] = {}
        if path == "/" and not q:
            categoria = (params.get("categoria") or "").strip()
            if categoria in SITE_TOPIC_KEYWORDS:
                out["categoria"] = categoria
        return out, True

    out = {}
    if path == "/":
        categoria = (params.get("categoria") or "").strip()
        if categoria in SITE_TOPIC_KEYWORDS:
            out["categoria"] = categoria
    return out, False


def build_hreflang_map(
    site_origin: str,
    path: str,
    base_query: dict[str, str],
    *,
    full: bool,
) -> dict[str, str]:
    """pt-BR e x-default = canônica (sem ?lang=). EN/JA só se full=True."""
    canonical = absolute_url(site_origin, path, base_query or None)
    urls = {"pt-BR": canonical, "x-default": canonical}
    if full:
        for code in ("en", "ja"):
            q = dict(base_query)
            q["lang"] = code
            urls[code] = absolute_url(site_origin, path, q)
    return urls


def build_i18n_context(request: Request) -> dict[str, Any]:
    lang = resolve_lang(request)
    t: Callable[..., str] = lambda key, **kwargs: translate(lang, key, **kwargs)
    site_origin = os.getenv("SITE_ORIGIN", "https://financas-news.net.br").rstrip("/")
    path = request.url.path or "/"
    base_query, robots_noindex = canonical_query_params(request, path)
    canonical_url = absolute_url(site_origin, path, base_query or None)
    hreflang_urls = build_hreflang_map(site_origin, path, base_query, full=True)

    return {
        "lang": lang,
        "html_lang": HTML_LANG.get(lang, "pt-BR"),
        "number_locale": LOCALE_FOR_NUMBERS.get(lang, "pt-BR"),
        "site_origin": site_origin,
        "canonical_path": path,
        "canonical_query": base_query,
        "canonical_url": canonical_url,
        "robots_noindex": robots_noindex,
        "hreflang_urls": hreflang_urls,
        "default_og_image": f"{site_origin}/media/default/economia.svg?v=3",
        # Institucionais: hreflang EN/JA. Artigos sobrescrevem via _render_noticia_page.
        "hreflang_full": True,
        "lp": lambda path, current=lang: localized_path(path, current),
        "t": t,
        "tr_tag": lambda tag: translate_tag(lang, tag),
        "category_intro": lambda tag: category_intro(lang, tag),
        "tr_sentiment": lambda s: translate_sentiment(lang, s),
        "tr_market_sentiment": lambda s: market_sentiment_label(lang, s),
        "tr_prob": lambda v: translate_probability(lang, v),
        "tr_urgency": lambda v: translate_urgency(lang, v),
        "lang_urls": {code: lang_switch_url(request, code) for code in SUPPORTED_LANGS},
        "supported_langs": SUPPORTED_LANGS,
        # Textos do rodapé resolvidos no contexto (evita chave crua se o worker atrasar o reload).
        "footer_tagline": t("footer_tagline"),
        "footer_portal_label": t("footer_portal"),
        "footer_connect_label": t("footer_connect"),
        "footer_guides_label": t("footer_guides"),
        "footer_about_title": t("footer_about_title"),
        "footer_about_blurb": t("footer_about_blurb"),
        "footer_rights": t("footer_rights"),
        "footer_developer": t("footer_developer"),
        "site_brand_keywords": SITE_BRAND_KEYWORDS,
        "site_brand_keywords_meta": ", ".join(SITE_BRAND_KEYWORDS),
        "site_brand_alternate_names": SITE_BRAND_ALTERNATE_NAMES,
        "site_topic_keywords": SITE_TOPIC_KEYWORDS,
        "seo_topic_links": [
            {
                "href": (
                    f"/?categoria={quote(tag)}&lang={lang}"
                    if lang != DEFAULT_LANG
                    else f"/?categoria={quote(tag)}"
                ),
                "label": translate_tag(lang, tag),
            }
            for tag in SITE_TOPIC_KEYWORDS
        ],
        "footer_guide_links": [
            {
                "href": f"/artigo/selic?lang={lang}" if lang != DEFAULT_LANG else "/artigo/selic",
                "label": t("footer_guide_selic"),
            },
            {
                "href": f"/artigo/ipca?lang={lang}" if lang != DEFAULT_LANG else "/artigo/ipca",
                "label": t("footer_guide_ipca"),
            },
            {
                "href": f"/artigo/cambio?lang={lang}" if lang != DEFAULT_LANG else "/artigo/cambio",
                "label": t("footer_guide_cambio"),
            },
            {
                "href": f"/artigo/renda-fixa?lang={lang}" if lang != DEFAULT_LANG else "/artigo/renda-fixa",
                "label": t("footer_guide_renda_fixa"),
            },
        ],
    }
