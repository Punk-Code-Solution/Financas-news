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


def get_monetization_config() -> dict[str, object]:
    adsense_client = _env("GOOGLE_ADSENSE_CLIENT")
    adsense_slot = _env("ADSENSE_AD_SLOT")
    adsense_enabled = bool(adsense_client)

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

    sidebar_visible = (
        adsense_enabled
        or bool(affiliates)
        or bool(amazon_url)
        or newsletter_enabled
    )

    article_extras_visible = sponsored_enabled or premium_enabled or adsense_enabled

    return {
        "adsense": {
            "enabled": adsense_enabled,
            "client": adsense_client,
            "slot": adsense_slot or "1234567890",
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
        "article_extras_visible": article_extras_visible,
    }
