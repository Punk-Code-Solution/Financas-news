"""Artigos evergreen educativos (molde de notícia) para palavras-chave internas.

Mantém o conjunto pequeno e estável: só os temas mais citados no site.
"""

from __future__ import annotations

import json
from typing import Any

from db import DbClient

GUIDE_LINK_PREFIX = "internal://artigo/"
GUIDE_FONTE = "Finanças News"

# Quatro guias — não expandir sem necessidade editorial.
EDUCATIONAL_GUIDES: list[dict[str, Any]] = [
    {
        "slug": "selic",
        "titulo": "O que é a Selic e como ela muda o crédito, a poupança e a renda fixa",
        "tag": "Juros",
        "sentimento": "Neutro",
        "impacto": (
            "Quando a Selic sobe, o crédito e o financiamento ficam mais caros. "
            "Quando cai, a renda fixa pós-fixada rende menos, mas o consumo tende a reagir. "
            "Acompanhar a meta ajuda a calibrar reserva de emergência e prazos de investimento."
        ),
        "resumo": (
            "A Selic é a taxa básica de juros da economia brasileira, definida pelo Comitê de Política "
            "Monetária (Copom) do Banco Central. Ela funciona como referência para o custo do dinheiro: "
            "bancos, tesouro e boa parte dos produtos de renda fixa se orientam por essa meta. "
            "Por isso, quando uma notícia cita a Selic, o leitor está vendo o principal termômetro "
            "da política monetária do país.\n\n"
            "Na prática, a Selic influencia o spread do crédito pessoal, o custo do cartão, o "
            "financiamento imobiliário e a remuneração de aplicações atreladas ao CDI. Em ciclos de "
            "alta, o objetivo do Banco Central costuma ser conter a demanda e ancorar expectativas "
            "de IPCA. Em ciclos de corte, a intenção é aliviar o custo financeiro sem desancorar "
            "a inflação.\n\n"
            "O câmbio também reage à diferença de juros entre o Brasil e o exterior: juros reais "
            "mais altos tendem a atrair fluxo para ativos em reais, enquanto cortes rápidos podem "
            "pressionar o dólar. Nada disso é automático — o mercado precifica cenário fiscal, "
            "risco-país e dados globais ao mesmo tempo.\n\n"
            "Para o investidor de varejo, a leitura útil é simples. Selic elevada favorece liquidez "
            "em pós-fixados (Tesouro Selic, CDBs e fundos DI) e exige cautela com prefixados longos "
            "se ainda houver risco de novas altas. Selic em queda abre espaço para alongar prazo "
            "com critério, sempre confrontando o prêmio com a trajetória esperada da inflação.\n\n"
            "No dia a dia do portal, a Selic aparece cruzada com cotações e indicadores do BCB "
            "para explicar o impacto no bolso — não como dica de compra, mas como contexto. "
            "Uma decisão de juros altera o custo de viver no crédito e a remuneração de quem "
            "está na renda fixa; o restante do portfólio precisa ser reavaliado com esse pano de fundo.\n\n"
            "Guia prático: acompanhe a meta Selic e a curva de juros implícita nas matérias de "
            "Juros; compare com o IPCA em 12 meses antes de travar prazo longo; e use a reserva "
            "de emergência em instrumentos líquidos enquanto o ciclo monetário estiver incerto."
        ),
        "contexto_mercado": (
            "A Selic é a âncora da política monetária brasileira. Mudanças na meta alteram o custo "
            "do crédito e a atratividade relativa da renda fixa frente a risco e câmbio."
        ),
        "pontos_chave": [
            {
                "titulo": "Taxa básica",
                "descricao": "Referência do Copom para o custo do dinheiro na economia.",
                "categoria": "Juros",
            },
            {
                "titulo": "Crédito e consumo",
                "descricao": "Selic mais alta encarece empréstimos e freia demanda agregada.",
                "categoria": "Juros",
            },
            {
                "titulo": "Renda fixa",
                "descricao": "Pós-fixados acompanham o ciclo; prefixados dependem da trajetória esperada.",
                "categoria": "Juros",
            },
        ],
        "glossario": [
            {
                "termo": "Copom",
                "definicao": "Comitê do Banco Central que define a meta da Selic periodicamente.",
            },
            {
                "termo": "CDI",
                "definicao": "Taxa interbancária próxima da Selic; base de muitos produtos de renda fixa.",
            },
        ],
        "faq": [
            {
                "pergunta": "Selic alta é boa ou ruim para o investidor?",
                "resposta": (
                    "Depende do perfil. Favorece quem está em pós-fixados líquidos; pressiona quem "
                    "precisa de crédito e pode pesar sobre ações sensíveis a juros."
                ),
            },
            {
                "pergunta": "Qual a diferença entre Selic meta e Selic over?",
                "resposta": (
                    "A meta é o alvo do Copom; a Selic over é a taxa efetiva das operações diárias "
                    "no mercado interbancário, em geral muito próxima da meta."
                ),
            },
        ],
    },
    {
        "slug": "ipca",
        "titulo": "O que é o IPCA e por que a inflação oficial mexe com o seu poder de compra",
        "tag": "Inflação",
        "sentimento": "Neutro",
        "impacto": (
            "IPCA alto corrói o poder de compra do salário e da poupança sem proteção. "
            "Contratos, aluguéis e benefícios indexados reagem ao índice com defasagem. "
            "Na renda fixa, títulos IPCA+ buscam preservar o valor real do capital."
        ),
        "resumo": (
            "O IPCA — Índice Nacional de Preços ao Consumidor Amplo — é o indicador oficial de "
            "inflação no Brasil, calculado pelo IBGE. Ele mede a variação média de uma cesta de "
            "produtos e serviços para famílias com renda de 1 a 40 salários mínimos. Quando o "
            "portal cita o IPCA acumulado em 12 meses, está falando da perda (ou ganho) de poder "
            "de compra ao longo de um ano.\n\n"
            "A meta de inflação do Banco Central usa o IPCA como referência. Se o índice corre "
            "acima da meta, a tendência de política monetária é manter a Selic restritiva por "
            "mais tempo. Se converge, abre-se espaço para cortes de juros. Por isso IPCA e Selic "
            "aparecem juntos na maior parte das análises macro do site.\n\n"
            "No bolso, a inflação não é só 'preço subindo': ela redistribui renda entre quem "
            "consegue reajustar receitas e quem fica defasado. Alimentação, energia e transportes "
            "costumam dominar a percepção do consumidor, mesmo quando o núcleo do índice mostra "
            "outra dinâmica.\n\n"
            "Investidores usam o IPCA para avaliar se a rentabilidade nominal de um CDB ou fundo "
            "está realmente ganhando da inflação. Produtos IPCA+ pagam um cupom real acima do "
            "índice, útil para objetivos de longo prazo — desde que o investidor aceite a "
            "marcação a mercado no caminho.\n\n"
            "O câmbio entra na conta quando itens importados ou commoditizados pesam na cesta. "
            "Um dólar mais forte pode pressionar o IPCA com defasagem; um alívio cambial ajuda, "
            "mas não apaga choques climáticos ou fiscais.\n\n"
            "Guia prático: leia o IPCA em 12 meses junto com o núcleo e com a Selic; desconfie de "
            "rentabilidade só nominal; e, para metas longas (aposentadoria, imóvel), compare "
            "alternativas em termos reais, não apenas em percentual de CDI."
        ),
        "contexto_mercado": (
            "O IPCA é o termômetro oficial de preços. Ele ancora a meta de inflação, influencia "
            "a Selic e serve de base para títulos e contratos indexados."
        ),
        "pontos_chave": [
            {
                "titulo": "Inflação oficial",
                "descricao": "Índice do IBGE usado na meta do Banco Central.",
                "categoria": "Inflação",
            },
            {
                "titulo": "Poder de compra",
                "descricao": "IPCA alto reduz o que o mesmo salário consegue adquirir.",
                "categoria": "Inflação",
            },
            {
                "titulo": "IPCA+",
                "descricao": "Títulos que buscam retorno real acima da inflação oficial.",
                "categoria": "Juros",
            },
        ],
        "glossario": [
            {
                "termo": "Meta de inflação",
                "definicao": "Alvo de IPCA perseguido pelo Banco Central via política de juros.",
            },
            {
                "termo": "Núcleo de inflação",
                "definicao": "Medidas que excluem itens voláteis para ler a tendência subjacente de preços.",
            },
        ],
        "faq": [
            {
                "pergunta": "IPCA e INPC são a mesma coisa?",
                "resposta": (
                    "Não. O IPCA cobre uma faixa mais ampla de renda; o INPC foca famílias de "
                    "menor renda e é usado em vários reajustes trabalhistas."
                ),
            },
            {
                "pergunta": "Por que o IPCA de um mês pode cair e eu ainda sentir tudo caro?",
                "resposta": (
                    "O índice mensal mede variação, não o nível absoluto de preços. Uma desaceleração "
                    "significa que os preços sobem menos rápido — não que voltaram ao patamar anterior."
                ),
            },
        ],
    },
    {
        "slug": "cambio",
        "titulo": "O que é o câmbio e como o valor do dólar chega no seu bolso",
        "tag": "Dólar",
        "sentimento": "Neutro",
        "impacto": (
            "Dólar mais alto encarece importados, eletrônicos, viagens e parte dos combustíveis. "
            "Empresas com receita ou dívida em moeda forte sentem o efeito no resultado. "
            "Para o investidor, câmbio é risco e, às vezes, proteção — nunca um atalho sem volatilidade."
        ),
        "resumo": (
            "Câmbio é o preço de uma moeda em relação a outra. No Brasil, a cotação mais citada "
            "no dia a dia é a do dólar comercial frente ao real. Quando o portal fala em 'valor "
            "do câmbio', está tratando dessa relação — e das consequências para preços, juros e "
            "ativos financeiros.\n\n"
            "O preço do dólar sobe ou desce conforme oferta e demanda: fluxo de comércio, juros "
            "relativos (Selic versus Fed), risco fiscal, apetite global por emergentes e choques "
            "geopolíticos. Não existe um 'valor justo' fixo visível na vitrine; o mercado "
            "negocia expectativas o tempo todo.\n\n"
            "No consumo, o câmbio aparece com defasagem. Itens com componente importado, "
            "eletrônicos, remédios e viagens internacionais reagem mais depressa. Alimentos e "
            "serviços locais podem demorar, mas commodities precificadas em dólar — como trigo "
            "ou petróleo — conectam o exterior à mesa do brasileiro.\n\n"
            "Na renda fixa e na bolsa, o câmbio altera o apetite estrangeiro por títulos e ações "
            "brasileiras. Juros reais atrativos podem sustentar o real; ruído fiscal ou queda "
            "rápida da Selic pode enfraquecê-lo. Empresas exportadoras e endividadas em dólar "
            "ficam em lados opostos da mesma notícia.\n\n"
            "Há também o dólar turismo e spreads de cartão, normalmente acima da PTAX. Para "
            "planejamento pessoal, o que importa é a taxa efetiva que você paga — não só a "
            "manchete do comercial.\n\n"
            "Guia prático: leia o câmbio junto com Selic e IPCA; evite transformar previsão de "
            "dólar em aposta alavancada; e, se precisar de proteção (viagem, mensalidade no "
            "exterior), prefira instrumentos e prazos alinhados ao objetivo real, não ao "
            "ruído do dia."
        ),
        "contexto_mercado": (
            "O câmbio resume o preço relativo do real. Ele transmite choques externos aos preços "
            "locais e altera o retorno de quem investe com exposição à moeda forte."
        ),
        "pontos_chave": [
            {
                "titulo": "Dólar comercial",
                "descricao": "Cotação de referência para fluxo comercial e financeiro.",
                "categoria": "Dólar",
            },
            {
                "titulo": "Pass-through",
                "descricao": "Canal pelo qual o câmbio chega aos preços internos e ao IPCA.",
                "categoria": "Inflação",
            },
            {
                "titulo": "Juros relativos",
                "descricao": "Diferença entre Selic e juros externos influencia o fluxo cambial.",
                "categoria": "Juros",
            },
        ],
        "glossario": [
            {
                "termo": "PTAX",
                "definicao": "Taxa de referência do dólar calculada pelo Banco Central com base em negócios do dia.",
            },
            {
                "termo": "Dólar turismo",
                "definicao": "Cotação para pessoa física em espécie ou cartão, em geral com spread sobre o comercial.",
            },
        ],
        "faq": [
            {
                "pergunta": "Por que o dólar sobe se a Selic está alta?",
                "resposta": (
                    "Juros altos ajudam, mas não sozinhos. Risco fiscal, cenário externo ou saída "
                    "de fluxo podem dominar o movimento de curto prazo."
                ),
            },
            {
                "pergunta": "Comprar dólar protege da inflação?",
                "resposta": (
                    "Pode reduzir parte do risco de desvalorização do real, mas o dólar também "
                    "oscila e não acompanha automaticamente o IPCA. É exposição cambial, não "
                    "substituto perfeito de proteção inflacionária."
                ),
            },
        ],
    },
    {
        "slug": "renda-fixa",
        "titulo": "O que é renda fixa: Tesouro, CDI, prefixados e IPCA+ sem enrolação",
        "tag": "Juros",
        "sentimento": "Neutro",
        "impacto": (
            "Renda fixa não significa renda sem risco: há risco de crédito, liquidez e marcação a mercado. "
            "O ciclo da Selic muda a atratividade entre pós, prefixado e IPCA+. "
            "Reserve emergência em liquidez; use prazos longos só com objetivo claro."
        ),
        "resumo": (
            "Renda fixa é a família de investimentos em que as regras de remuneração são "
            "conhecidas no momento da aplicação — indexador, taxa ou combinação dos dois. "
            "Não quer dizer que o preço de mercado seja estável nem que todo emissor seja "
            "igual. Tesouro Direto, CDBs, LCIs/LCAs e debêntures cabem nesse guarda-chuva, "
            "cada um com seu risco.\n\n"
            "Os pós-fixados (Tesouro Selic, CDB a % do CDI) acompanham o ciclo da Selic. "
            "São a base clássica da reserva de emergência. Os prefixados travam uma taxa "
            "nominal: se a Selic cair além do esperado, tendem a se valorizar; se a trajetória "
            "de juros for revista para cima, sofrem na marcação a mercado.\n\n"
            "Os títulos IPCA+ pagam inflação oficial mais um cupom real. Fazem sentido para "
            "objetivos longos em que preservar poder de compra importa mais do que oscilar "
            "menos no extrato. Já o crédito privado pode oferecer prêmio acima do Tesouro — "
            "com risco do emissor e, em muitos casos, menor liquidez.\n\n"
            "A política monetária é o pano de fundo. Selic alta valoriza a liquidez pós-fixada; "
            "expectativa de cortes anima alongamento e prefixados. O IPCA define se a taxa "
            "contratada está ganhando da inflação. O câmbio entra quando o investidor compara "
            "retorno local com ativos dolarizados.\n\n"
            "Erros comuns: chasing de rentabilidade sem bater o índice de referência, concentrar "
            "em um único emissor fora do FGC, e vender prefixado/IPCA+ no pior momento da "
            "curva por precisar de caixa. Liquidez e objetivo vêm antes do rendimento da "
            "prateleira.\n\n"
            "Guia prático: separe emergência (pós líquido) de metas com prazo; leia Selic e "
            "IPCA antes de travar taxa; e trate 'renda fixa' como ferramenta — não como "
            "sinônimo de ausência de risco."
        ),
        "contexto_mercado": (
            "Renda fixa conecta o investidor ao ciclo de juros e à inflação. A escolha entre "
            "pós, prefixado e IPCA+ depende da Selic, do IPCA e do horizonte de uso do dinheiro."
        ),
        "pontos_chave": [
            {
                "titulo": "Pós-fixados",
                "descricao": "Acompanham Selic/CDI; base da reserva de liquidez.",
                "categoria": "Juros",
            },
            {
                "titulo": "Prefixados",
                "descricao": "Travamm taxa nominal; sensíveis à revisão da curva de juros.",
                "categoria": "Juros",
            },
            {
                "titulo": "IPCA+",
                "descricao": "Buscam retorno real acima da inflação oficial.",
                "categoria": "Inflação",
            },
        ],
        "glossario": [
            {
                "termo": "Marcação a mercado",
                "definicao": "Ajuste diário do preço do título conforme a curva de juros, mesmo que você não venda.",
            },
            {
                "termo": "FGC",
                "definicao": "Fundo Garantidor de Créditos; cobre certos depósitos até o limite vigente por CPF/CNPJ e conglomerado.",
            },
        ],
        "faq": [
            {
                "pergunta": "Tesouro Selic pode render negativo?",
                "resposta": (
                    "Em condições normais a rentabilidade acompanha a taxa básica com baixíssima "
                    "volatilidade. Em situações extremas de liquidez/mercado pode haver ruído "
                    "pontual, mas o desenho do título é de baixíssimo risco de mercado frente a "
                    "prefixados longos."
                ),
            },
            {
                "pergunta": "LCI/LCA são sempre melhores que CDB?",
                "resposta": (
                    "São isentas de IR para pessoa física, o que ajuda na comparação líquida, "
                    "mas liquidez, emissor e prazo pesam. Compare sempre o retorno líquido ao "
                    "prazo em que você realmente precisa do dinheiro."
                ),
            },
        ],
    },
]


def guide_link(slug: str) -> str:
    return f"{GUIDE_LINK_PREFIX}{slug}"


def guide_path(slug: str) -> str:
    return f"/artigo/{slug}"


def get_guide_by_slug(slug: str) -> dict[str, Any] | None:
    for guide in EDUCATIONAL_GUIDES:
        if guide["slug"] == slug:
            return guide
    return None


def _dados_mercado_payload(guide: dict[str, Any]) -> str:
    return json.dumps(
        {
            "contexto_mercado": guide["contexto_mercado"],
            "pontos_chave": guide["pontos_chave"],
            "glossario": guide["glossario"],
            "faq": guide["faq"],
            "dados_citados": ["Selic", "IPCA", "câmbio", "renda fixa"],
        },
        ensure_ascii=False,
    )


def ensure_educational_guides(client: DbClient) -> int:
    """Insere ou atualiza os guias evergreen. Retorna quantos foram gravados."""
    written = 0
    published_at = "15/01/2026 09:00"
    for guide in EDUCATIONAL_GUIDES:
        link = guide_link(guide["slug"])
        dados = _dados_mercado_payload(guide)
        existing = client.execute("SELECT id FROM news WHERE link = ?", [link])
        if existing.rows:
            client.execute(
                """
                UPDATE news
                SET titulo = ?, resumo = ?, impacto = ?, tag = ?, sentimento = ?,
                    fonte = ?, dados_mercado = ?, contexto_editorial = ?,
                    updated_at = ?, versao_analise = ?
                WHERE link = ?
                """,
                [
                    guide["titulo"],
                    guide["resumo"],
                    guide["impacto"],
                    guide["tag"],
                    guide["sentimento"],
                    GUIDE_FONTE,
                    dados,
                    guide["contexto_mercado"],
                    published_at,
                    1,
                    link,
                ],
            )
        else:
            client.execute(
                """
                INSERT INTO news (
                    titulo, resumo, impacto, link, tag, sentimento,
                    published_at, fonte, dados_mercado, contexto_editorial,
                    created_at, imagem_url, versao_analise
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    guide["titulo"],
                    guide["resumo"],
                    guide["impacto"],
                    link,
                    guide["tag"],
                    guide["sentimento"],
                    published_at,
                    GUIDE_FONTE,
                    dados,
                    guide["contexto_mercado"],
                    published_at,
                    None,
                    1,
                ],
            )
        written += 1
    return written


def find_guide_noticia_id(client: DbClient, slug: str) -> int | None:
    result = client.execute(
        "SELECT id FROM news WHERE link = ? LIMIT 1",
        [guide_link(slug)],
    )
    if not result.rows:
        return None
    return int(result.rows[0][0])
