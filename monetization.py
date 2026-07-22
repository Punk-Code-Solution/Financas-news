"""Configuração de monetização — só exibe blocos com variáveis de ambiente definidas."""
import os
from typing import TypedDict


class AffiliateItem(TypedDict):
    id: str
    nome: str
    titulo: str
    descricao: str
    cta: str
    url: str
    destaque: bool
    cor: str


DEFAULT_AFFILIATES: list[AffiliateItem] = [
    {
        "id": "binance",
        "nome": "Binance",
        "titulo": "Lucre com Cripto Hoje",
        "descricao": "Cadastre-se na maior corretora do mundo e ganhe bônus em USDC.",
        "cta": "Resgatar Bônus Agora",
        "url": "",
        "destaque": True,
        "cor": "yellow",
    },
    {
        "id": "xp",
        "nome": "XP Investimentos",
        "titulo": "Invista na Bolsa Brasileira",
        "descricao": "Abra conta na maior corretora do Brasil e acesse fundos, ações e renda fixa.",
        "cta": "Abrir Conta na XP",
        "url": "",
        "destaque": False,
        "cor": "blue",
    },
    {
        "id": "mercado_bitcoin",
        "nome": "Mercado Bitcoin",
        "titulo": "Cripto com Segurança BR",
        "descricao": "A exchange brasileira pioneira em bitcoin e altcoins regulamentada.",
        "cta": "Começar na MB",
        "url": "",
        "destaque": False,
        "cor": "green",
    },
    {
        "id": "btg",
        "nome": "BTG Pactual",
        "titulo": "Banco de Investimentos",
        "descricao": "Produtos exclusivos, renda fixa e gestão patrimonial de alto nível.",
        "cta": "Conhecer o BTG",
        "url": "",
        "destaque": False,
        "cor": "slate",
    },
]

ENV_AFFILIATE_KEYS = {
    "binance": "AFFILIATE_BINANCE_URL",
    "xp": "AFFILIATE_XP_URL",
    "mercado_bitcoin": "AFFILIATE_MERCADO_BITCOIN_URL",
    "btg": "AFFILIATE_BTG_URL",
}


def _env(key: str) -> str:
    return os.getenv(key, "").strip()


TAG_AFFILIATE_MAP: dict[str, str] = {
    "Cripto": "binance",
    "Ações": "xp",
    "Economia": "xp",
    "Dólar": "xp",
    "Juros": "btg",
    "Inflação": "btg",
    "Imóveis": "btg",
    "Fintech": "mercado_bitcoin",
    "Commodities": "xp",
    "Política Econômica": "btg",
}


def get_contextual_affiliate(tag: str) -> dict[str, object] | None:
    """Retorna afiliado relevante para a tag, somente se URL estiver configurada."""
    affiliate_id = TAG_AFFILIATE_MAP.get(tag, "xp")
    env_key = ENV_AFFILIATE_KEYS.get(affiliate_id)
    if not env_key:
        return None
    url = _env(env_key)
    if not url:
        return None
    for item in DEFAULT_AFFILIATES:
        if item["id"] == affiliate_id:
            return {**item, "url": url}
    return None


def get_monetization_config() -> dict[str, object]:
    adsense_client = _env("GOOGLE_ADSENSE_CLIENT") or "ca-pub-3623062544438213"
    adsense_slot = _env("ADSENSE_AD_SLOT")
    adsense_fluid_slot = _env("ADSENSE_FLUID_SLOT") or "5920613886"
    adsense_fluid_layout = _env("ADSENSE_FLUID_LAYOUT_KEY") or "-gp+18-5a-gr+1eg"
    adsense_fluid2_slot = _env("ADSENSE_FLUID2_SLOT") or "5003238179"
    adsense_fluid2_layout = _env("ADSENSE_FLUID2_LAYOUT_KEY") or "-fd-l+6i-lx+n1"
    adsense_in_article_slot = _env("ADSENSE_IN_ARTICLE_SLOT") or "3294450543"
    adsense_sidebar_slot = _env("ADSENSE_SIDEBAR_SLOT") or "1019761130"
    # Margens HLTV: slot próprio ou reutiliza o da sidebar.
    adsense_skyscraper_slot = _env("ADSENSE_SKYSCRAPER_SLOT") or adsense_sidebar_slot
    adsense_autorelaxed_slot = _env("ADSENSE_AUTORELAXED_SLOT") or "2568646523"
    adsense_enabled = bool(adsense_client)
    adsense_display_enabled = adsense_enabled and bool(adsense_slot)

    affiliates: list[dict[str, object]] = []
    for item in DEFAULT_AFFILIATES:
        env_key = ENV_AFFILIATE_KEYS.get(item["id"])
        if not env_key:
            continue
        url = _env(env_key)
        if url:
            affiliates.append({**item, "url": url})

    amazon_tag = _env("AMAZON_AFFILIATE_TAG")
    amazon_url = (
        f"https://www.amazon.com.br/s?k=finanças+investimentos&tag={amazon_tag}"
        if amazon_tag
        else ""
    )

    newsletter_external = _env("NEWSLETTER_URL")
    newsletter_enabled = bool(newsletter_external) or _env("NEWSLETTER_ENABLED").lower() == "true"

    sponsored_url = _env("SPONSORED_SLOT_URL")
    sponsored_enabled = bool(sponsored_url)

    premium_enabled = _env("PREMIUM_TEASER_ENABLED").lower() == "true"

    sidebar_widgets_visible = (
        bool(affiliates)
        or bool(amazon_url)
        or newsletter_enabled
    )
    # Anúncios laterais usam skins/faixas; a coluna interna só aparece com widgets reais.
    sidebar_visible = sidebar_widgets_visible

    article_extras_visible = sponsored_enabled or premium_enabled or adsense_enabled

    return {
        "adsense": {
            "enabled": adsense_enabled,
            "display_enabled": adsense_display_enabled,
            "client": adsense_client,
            "slot": adsense_slot or "",
            "fluid_slot": adsense_fluid_slot,
            "fluid_layout_key": adsense_fluid_layout,
            "fluid2_slot": adsense_fluid2_slot,
            "fluid2_layout_key": adsense_fluid2_layout,
            "in_article_slot": adsense_in_article_slot,
            "sidebar_slot": adsense_sidebar_slot,
            "skyscraper_slot": adsense_skyscraper_slot,
            "autorelaxed_slot": adsense_autorelaxed_slot,
            # Reuso dos slots existentes para mais faixas (mesmo design).
            "feed_top_slot": adsense_fluid_slot,
            "feed_bottom_slot": adsense_fluid2_slot or adsense_fluid_slot,
            "article_top_slot": adsense_fluid2_slot or adsense_fluid_slot,
            "article_mid_slot": adsense_sidebar_slot or adsense_fluid_slot,
        },
        "affiliates": affiliates,
        "amazon_books_url": amazon_url,
        "newsletter_external_url": newsletter_external,
        "newsletter_enabled": newsletter_enabled,
        "newsletter_capture_local": newsletter_enabled and not newsletter_external,
        "sponsored": {
            "enabled": sponsored_enabled,
            "url": sponsored_url,
            "label": _env("SPONSORED_SLOT_LABEL") or "Patrocínio",
            "titulo": _env("SPONSORED_SLOT_TITLE") or "Oportunidade para investidores",
            "descricao": _env("SPONSORED_SLOT_DESC")
            or "Conheça produtos e serviços selecionados pela nossa equipe editorial.",
        },
        "premium_teaser": {
            "enabled": premium_enabled,
            "titulo": "Análises Premium em breve",
            "descricao": (
                "Alertas personalizados, relatórios semanais e cenários exclusivos "
                "para quem quer ir além das manchetes."
            ),
        },
        "sidebar_visible": sidebar_visible,
        "sidebar_widgets_visible": sidebar_widgets_visible,
        "article_extras_visible": article_extras_visible,
    }
