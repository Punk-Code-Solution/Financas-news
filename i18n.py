"""Internacionalização (pt / en / ja) do Finanças News."""
from __future__ import annotations

import os
from typing import Any, Callable
from urllib.parse import quote, urlencode

from fastapi import Request

# Variações de marca + temas para SEO (meta keywords + schema.org).
SITE_BRAND_KEYWORDS: list[str] = [
    # Marca e grafias
    "finanças",
    "financas",
    "financa",
    "finanças news",
    "financas news",
    "financa news",
    "finanças-news",
    "financas-news",
    "financa-news",
    "portal finanças news",
    "site finanças news",
    "financasnews",
    "finançasnews",
    # Temas de discovery
    "notícias financeiras",
    "noticias financeiras",
    "notícias de economia",
    "noticias de economia",
    "economia brasil",
    "economia brasileira",
    "mercado financeiro",
    "mercado de capitais",
    "análise financeira",
    "analise financeira",
    "investimentos",
    "bolsa de valores",
    "ações",
    "acoes",
    "criptomoedas",
    "bitcoin",
    "dólar",
    "dolar",
    "selic",
    "ipca",
    "inflação",
    "inflacao",
    "juros",
    "banco central",
    "fintech",
    "commodities",
    "renda fixa",
    "câmbio",
    "cambio",
]

SITE_BRAND_ALTERNATE_NAMES: list[str] = [
    "Finanças News",
    "Financas News",
    "Financa News",
    "finanças news",
    "financas news",
    "financa news",
    "finanças-news",
    "financas-news",
    "financa-news",
    "FinançasNews",
    "FinancasNews",
    "Portal Finanças News",
    "Finanças News Brasil",
    "financasnews.net.br",
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

SENTIMENT_LABELS = {
    "pt": {"Positivo": "Positivo", "Negativo": "Negativo", "Neutro": "Neutro"},
    "en": {"Positivo": "Positive", "Negativo": "Negative", "Neutro": "Neutral"},
    "ja": {"Positivo": "強気", "Negativo": "弱気", "Neutro": "中立"},
}

# Strings de UI compartilhadas (nav, home, artigo, footer, overlays).
UI: dict[str, dict[str, str]] = {
    "pt": {
        "brand_finance": "FINANÇAS",
        "brand_news": "NEWS",
        "site_name": "Finanças News",
        "meta_home_title": "Finanças News | Notícias Financeiras, Economia e Mercado em Tempo Real",
        "meta_home_og_title": "Finanças News | Economia, Investimentos e Cripto",
        "meta_home_description": "Finanças News (financas news / financas-news): notícias financeiras, economia Brasil, dólar, Selic, IPCA, ações, criptomoedas e análises com dados do Banco Central.",
        "meta_brand_keywords": ", ".join(SITE_BRAND_KEYWORDS),
        "seo_topics_title": "Temas em destaque",
        "seo_discover_blurb": "Encontre no Finanças News análises sobre economia brasileira, mercado financeiro, investimentos, dólar, juros, inflação, criptomoedas, fintech e commodities — atualizadas com dados oficiais.",
        "search_placeholder": "Pesquisar...",
        "latest": "Últimas",
        "editorial_selection": "Seleção editorial",
        "highlights_market": "Destaques do mercado",
        "highlights_in": "Destaques em {tag}",
        "analyses_with_data": "Análises com dados e contexto",
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
        "back": "Voltar",
        "footer_developed": "Desenvolvido por",
        "footer_tagline": "Análises financeiras com dados do Banco Central, cotações e cruzamento de fontes — Finanças News, financas news e financas-news.",
        "footer_portal": "Portal",
        "footer_connect": "Conecte-se",
        "footer_guides": "Guias essenciais",
        "footer_about_title": "Sobre nós",
        "footer_about_blurb": "O Finanças News (também buscado como financas news, financa news e financas-news) publica análises com dados de mercado e indicadores oficiais para ajudar você a entender o que move a economia.",
        "footer_rights": "Todos os direitos reservados.",
        "footer_developer": "Punk Code Solution",
        "footer_guide_selic": "O que é a Selic",
        "footer_guide_ipca": "O que é o IPCA",
        "footer_guide_cambio": "Câmbio e dólar",
        "footer_guide_renda_fixa": "Renda fixa",
        "nav_about": "Quem Somos",
        "nav_terms": "Termos de Uso",
        "nav_privacy": "Privacidade",
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
        "analysis_team": "Equipe de Análise · Finanças News",
        "source": "Fonte",
        "read_original": "Ler matéria original",
        "related": "Leia também",
        "faq_title": "Perguntas frequentes",
        "affiliate_disclaimer": "Link de afiliado/parceiro",
        "recommended_reading": "📚 Leitura Recomendada",
        "amazon_books_blurb": "Livros sobre finanças e investimentos na Amazon Brasil.",
        "amazon_books_cta": "Ver livros na Amazon →",
        "newsletter_title": "📬 Newsletter Finanças News",
        "newsletter_blurb": "Receba as principais análises e alertas de mercado no seu e-mail. Grátis.",
        "newsletter_subscribe": "Inscrever-se",
        "newsletter_cta": "Quero receber análises",
        "premium_teaser": "Inscreva-se na newsletter para ser avisado no lançamento.",
        "about_title": "Quem Somos",
        "about_meta_title": "Quem Somos | Finanças News — Economia e Mercado",
        "about_meta_description": "Conheça o Finanças News (financas news / financas-news): notícias financeiras, economia Brasil, Selic, IPCA, dólar, ações e criptomoedas com dados do Banco Central.",
        "privacy_title": "Política de Privacidade",
        "privacy_meta_title": "Política de Privacidade | Finanças News",
        "privacy_meta_description": "Saiba como o Finanças News (financas news) coleta, utiliza e protege dados pessoais.",
        "privacy_eyebrow": "Transparência e LGPD",
        "privacy_updated": "Última atualização: 17 de julho de 2026",
        "terms_title": "Termos de Uso",
        "terms_meta_title": "Termos de Uso | Finanças News",
        "terms_meta_description": "Condições de uso do portal Finanças News.",
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
        "original_site": "site original",
        "open_original": "Abrir reportagem original",
        "market_evidence": "Evidência de mercado",
        "data_at_analysis": "Dados no momento da análise",
        "collected_at": "Coletado em",
        "core_panel_hint": "Painel padrão: Selic, IPCA 12 meses, dólar e cotações da categoria — com tendência 7 e 30 dias.",
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
        "brand_finance": "FINANÇAS",
        "brand_news": "NEWS",
        "site_name": "Finanças News",
        "meta_home_title": "Finanças News | Financial News, Markets and Economy",
        "meta_home_og_title": "Finanças News | Economy, Investing and Crypto",
        "meta_home_description": "Finanças News (financas news / financas-news): financial news, Brazilian economy, FX, rates, stocks, crypto and analysis with official market data.",
        "meta_brand_keywords": ", ".join(SITE_BRAND_KEYWORDS),
        "seo_topics_title": "Featured topics",
        "seo_discover_blurb": "On Finanças News find analysis of the Brazilian economy, financial markets, investing, USD/BRL, interest rates, inflation, crypto, fintech and commodities — with official data.",
        "search_placeholder": "Search...",
        "latest": "Latest",
        "editorial_selection": "Editorial picks",
        "highlights_market": "Market highlights",
        "highlights_in": "Highlights in {tag}",
        "analyses_with_data": "Data-backed analysis",
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
        "back": "Back",
        "footer_developed": "Built by",
        "footer_tagline": "Financial news and analysis with central-bank data, FX, rates, stocks and crypto — Finanças News / financas news / financas-news.",
        "footer_portal": "Site",
        "footer_connect": "Connect",
        "footer_guides": "Essential guides",
        "footer_about_title": "About us",
        "footer_about_blurb": "Finanças News (also searched as financas news, financa news and financas-news) covers Brazilian economy, markets, investing, USD/BRL, Selic, IPCA and crypto with official data.",
        "footer_rights": "All rights reserved.",
        "footer_developer": "Punk Code Solution",
        "footer_guide_selic": "What is Selic",
        "footer_guide_ipca": "What is IPCA",
        "footer_guide_cambio": "FX and the dollar",
        "footer_guide_renda_fixa": "Fixed income",
        "nav_about": "About Us",
        "nav_terms": "Terms of Use",
        "nav_privacy": "Privacy",
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
        "analysis_team": "Analysis Desk · Finanças News",
        "source": "Source",
        "read_original": "Read original story",
        "related": "Related reading",
        "faq_title": "Frequently asked questions",
        "affiliate_disclaimer": "Affiliate / partner link",
        "recommended_reading": "📚 Recommended Reading",
        "amazon_books_blurb": "Finance and investing books on Amazon Brazil.",
        "amazon_books_cta": "See books on Amazon →",
        "newsletter_title": "📬 Finanças News Newsletter",
        "newsletter_blurb": "Get the main market analyses and alerts in your inbox. Free.",
        "newsletter_subscribe": "Subscribe",
        "newsletter_cta": "Send me analyses",
        "premium_teaser": "Subscribe to the newsletter to get launch updates.",
        "about_title": "About Us",
        "about_meta_title": "About Us | Finanças News — Markets and Economy",
        "about_meta_description": "About Finanças News (financas news / financas-news): financial news, Brazilian economy, FX, rates, stocks and crypto with official market data.",
        "privacy_title": "Privacy Policy",
        "privacy_meta_title": "Privacy Policy | Finanças News",
        "privacy_meta_description": "How Finanças News collects, uses and protects personal data.",
        "privacy_eyebrow": "Transparency & data protection",
        "privacy_updated": "Last updated: July 17, 2026",
        "terms_title": "Terms of Use",
        "terms_meta_title": "Terms of Use | Finanças News",
        "terms_meta_description": "Terms governing the use of Finanças News.",
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
        "original_site": "original site",
        "open_original": "Open original story",
        "market_evidence": "Market evidence",
        "data_at_analysis": "Data at analysis time",
        "collected_at": "Collected at",
        "core_panel_hint": "Standard panel: Selic, 12-month IPCA, USD and category quotes — with 7d/30d trend.",
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
        "brand_finance": "FINANÇAS",
        "brand_news": "NEWS",
        "site_name": "Finanças News",
        "meta_home_title": "Finanças News | 金融ニュース・経済・市場",
        "meta_home_og_title": "Finanças News | 経済・投資・暗号資産",
        "meta_home_description": "Finanças News（financas news / financas-news）：ブラジル経済、為替、金利、株式、暗号資産のニュースと公式データに基づく分析。",
        "meta_brand_keywords": ", ".join(SITE_BRAND_KEYWORDS),
        "seo_topics_title": "注目トピック",
        "seo_discover_blurb": "Finanças Newsではブラジル経済、金融市場、投資、ドル、金利、インフレ、暗号資産、フィンテック、コモディティの分析を公式データとともに配信します。",
        "search_placeholder": "検索...",
        "latest": "最新",
        "editorial_selection": "編集部セレクト",
        "highlights_market": "市場の注目記事",
        "highlights_in": "{tag}の注目記事",
        "analyses_with_data": "データに基づく分析",
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
        "back": "戻る",
        "footer_developed": "開発:",
        "footer_tagline": "ブラジル経済、為替、金利、株式、暗号資産のニュースと分析 — Finanças News / financas news / financas-news。",
        "footer_portal": "サイト",
        "footer_connect": "つながる",
        "footer_guides": "基本ガイド",
        "footer_about_title": "私たちについて",
        "footer_about_blurb": "Finanças News（financas news / financas-news）はブラジル経済、市場、投資、ドル、Selic、IPCA、暗号資産を公式データとともに解説します。",
        "footer_rights": "全著作権所有。",
        "footer_developer": "Punk Code Solution",
        "footer_guide_selic": "Selicとは",
        "footer_guide_ipca": "IPCAとは",
        "footer_guide_cambio": "為替とドル",
        "footer_guide_renda_fixa": "固定金利",
        "nav_about": "私たちについて",
        "nav_terms": "利用規約",
        "nav_privacy": "プライバシー",
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
        "analysis_team": "分析チーム · Finanças News",
        "source": "出典",
        "read_original": "元記事を読む",
        "related": "関連記事",
        "faq_title": "よくある質問",
        "affiliate_disclaimer": "アフィリエイト／提携リンク",
        "recommended_reading": "📚 おすすめの読書",
        "amazon_books_blurb": "Amazonブラジルの金融・投資関連書籍。",
        "amazon_books_cta": "Amazonで本を見る →",
        "newsletter_title": "📬 Finanças News ニュースレター",
        "newsletter_blurb": "主要分析と市場アラートをメールで無料配信。",
        "newsletter_subscribe": "登録する",
        "newsletter_cta": "分析を受け取る",
        "premium_teaser": "ローンチ情報を受け取るにはニュースレターに登録してください。",
        "about_title": "私たちについて",
        "about_meta_title": "私たちについて | Finanças News — 経済と市場",
        "about_meta_description": "Finanças News（financas news / financas-news）：ブラジル経済、為替、金利、株式、暗号資産のニュースと公式データに基づく分析。",
        "privacy_title": "プライバシーポリシー",
        "privacy_meta_title": "プライバシーポリシー | Finanças News",
        "privacy_meta_description": "Finanças Newsによる個人データの収集・利用・保護について。",
        "privacy_eyebrow": "透明性とデータ保護",
        "privacy_updated": "最終更新: 2026年7月17日",
        "terms_title": "利用規約",
        "terms_meta_title": "利用規約 | Finanças News",
        "terms_meta_description": "Finanças Newsポータルの利用条件。",
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
        "original_site": "元サイト",
        "open_original": "元記事を開く",
        "market_evidence": "市場の根拠",
        "data_at_analysis": "分析時点のデータ",
        "collected_at": "取得日時",
        "core_panel_hint": "標準パネル：Selic、IPCA（12か月）、ドル、カテゴリ相場 — 7日/30日の推移付き。",
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


def lang_switch_url(request: Request, target_lang: str) -> str:
    path = request.url.path or "/"
    params = dict(request.query_params)
    params["lang"] = target_lang
    query = urlencode(params)
    return f"{path}?{query}" if query else f"{path}?lang={target_lang}"


def build_i18n_context(request: Request) -> dict[str, Any]:
    lang = resolve_lang(request)
    t: Callable[..., str] = lambda key, **kwargs: translate(lang, key, **kwargs)
    site_origin = os.getenv("SITE_ORIGIN", "https://financas-news.net.br").rstrip("/")
    path = request.url.path or "/"
    canonical_url = f"{site_origin}{path}"

    return {
        "lang": lang,
        "html_lang": HTML_LANG.get(lang, "pt-BR"),
        "number_locale": LOCALE_FOR_NUMBERS.get(lang, "pt-BR"),
        "site_origin": site_origin,
        "canonical_path": path,
        "canonical_url": canonical_url,
        "default_og_image": f"{site_origin}/media/default/economia.svg?v=3",
        # Artigos editoriais são PT; UI institucional pode usar variantes.
        "hreflang_full": True,
        "t": t,
        "tr_tag": lambda tag: translate_tag(lang, tag),
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
                "href": f"/?categoria={quote(tag)}&lang={lang}",
                "label": translate_tag(lang, tag),
            }
            for tag in SITE_TOPIC_KEYWORDS
        ],
        "footer_guide_links": [
            {"href": f"/artigo/selic?lang={lang}", "label": t("footer_guide_selic")},
            {"href": f"/artigo/ipca?lang={lang}", "label": t("footer_guide_ipca")},
            {"href": f"/artigo/cambio?lang={lang}", "label": t("footer_guide_cambio")},
            {"href": f"/artigo/renda-fixa?lang={lang}", "label": t("footer_guide_renda_fixa")},
        ],
    }
