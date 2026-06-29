"""Configuração de monetização — links via variáveis de ambiente."""
import os

DEFAULT_AFFILIATES = [
    {
        "id": "binance",
        "nome": "Binance",
        "titulo": "Lucre com Cripto Hoje",
        "descricao": "Cadastre-se na maior corretora do mundo e ganhe bônus em USDC.",
        "cta": "Resgatar Bônus Agora",
        "url": "https://accounts.binance.com/pt-BR/register",
        "destaque": True,
        "cor": "yellow",
    },
    {
        "id": "xp",
        "nome": "XP Investimentos",
        "titulo": "Invista na Bolsa Brasileira",
        "descricao": "Abra conta na maior corretora do Brasil e acesse fundos, ações e renda fixa.",
        "cta": "Abrir Conta na XP",
        "url": "https://www.xpi.com.br/",
        "destaque": False,
        "cor": "blue",
    },
    {
        "id": "mercado_bitcoin",
        "nome": "Mercado Bitcoin",
        "titulo": "Cripto com Segurança BR",
        "descricao": "A exchange brasileira pioneira em bitcoin e altcoins regulamentada.",
        "cta": "Começar na MB",
        "url": "https://www.mercadobitcoin.com.br/",
        "destaque": False,
        "cor": "green",
    },
    {
        "id": "btg",
        "nome": "BTG Pactual",
        "titulo": "Banco de Investimentos",
        "descricao": "Produtos exclusivos, renda fixa e gestão patrimonial de alto nível.",
        "cta": "Conhecer o BTG",
        "url": "https://www.btgpactual.com/",
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


def get_monetization_config() -> dict:
    amazon_tag = os.getenv("AMAZON_AFFILIATE_TAG", "").strip()
    newsletter_external = os.getenv("NEWSLETTER_URL", "").strip()
    sponsored_url = os.getenv("SPONSORED_SLOT_URL", "").strip()
    sponsored_label = os.getenv("SPONSORED_SLOT_LABEL", "Patrocínio").strip()

    affiliates = []
    for item in DEFAULT_AFFILIATES:
        env_key = ENV_AFFILIATE_KEYS.get(item["id"])
        url = os.getenv(env_key, item["url"]).strip() if env_key else item["url"]
        if url:
            affiliates.append({**item, "url": url})

    amazon_url = ""
    if amazon_tag:
        amazon_url = (
            f"https://www.amazon.com.br/s?k=finanças+investimentos&tag={amazon_tag}"
        )

    return {
        "affiliates": affiliates,
        "amazon_books_url": amazon_url,
        "newsletter_external_url": newsletter_external,
        "newsletter_capture_local": not newsletter_external,
        "sponsored": {
            "enabled": bool(sponsored_url),
            "url": sponsored_url,
            "label": sponsored_label,
            "titulo": os.getenv("SPONSORED_SLOT_TITLE", "Oportunidade para investidores"),
            "descricao": os.getenv(
                "SPONSORED_SLOT_DESC",
                "Conheça produtos e serviços selecionados pela nossa equipe editorial.",
            ),
        },
        "premium_teaser": {
            "enabled": os.getenv("PREMIUM_TEASER_ENABLED", "true").lower() != "false",
            "titulo": "Análises Premium em breve",
            "descricao": (
                "Alertas personalizados, relatórios semanais e cenários exclusivos "
                "para quem quer ir além das manchetes."
            ),
        },
    }
