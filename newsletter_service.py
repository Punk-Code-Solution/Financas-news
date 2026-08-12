"""Envio de newsletter e alertas — segredos só via variáveis de ambiente."""
from __future__ import annotations

import json
import os
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Any

import requests

# Digests: no máximo 1–2 matérias de urgência Alta (home_priority).
DIGEST_TOP_N = 2
DIGEST_MIN_PRIORITY = 80  # alinhado a core.HOME_HEADLINE_MIN_PRIORITY
DAILY_DIGEST_LOOKBACK_HOURS = 16
WEEKLY_DIGEST_LOOKBACK_DAYS = 7
# Compat legado (antes: 8 links extras no digest diário).
DAILY_DIGEST_EXTRA = 0

# Mensagem de UI quando o mailer falha ou não está configurado (cadastro / reenvio).
MAIL_SEND_FAIL_USER_MSG = (
    "Não foi possível enviar o e-mail. Tente mais tarde ou contate o suporte."
)

BRAND_NAME = "Clareza Capital"


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def site_origin() -> str:
    """Origem pública do site (lida em runtime — após load_dotenv / env do host)."""
    return _env("SITE_ORIGIN", "https://www.financas-news.net.br").rstrip("/")


def newsletter_from() -> str:
    """Remetente com display name Clareza Capital (Resend/SMTP)."""
    raw = _env("NEWSLETTER_FROM", "newsletter@financas-news.net.br")
    if not raw:
        return f"{BRAND_NAME} <newsletter@financas-news.net.br>"
    if "<" in raw:
        return raw
    return f"{BRAND_NAME} <{raw}>"


# Compat: módulos/testes que ainda importam constantes de módulo.
SITE_ORIGIN = site_origin()
NEWSLETTER_FROM = newsletter_from()


def is_send_configured() -> bool:
    if _env("RESEND_API_KEY"):
        return True
    if _env("NEWSLETTER_WEBHOOK_URL"):
        return True
    if _env("SMTP_HOST") and _env("SMTP_FROM"):
        return True
    return False


def _subscriber_emails(client) -> list[str]:
    try:
        result = client.execute(
            "SELECT email FROM newsletter_subscribers ORDER BY id ASC",
        )
        rows = result.rows or []
        return [str(row[0]).strip().lower() for row in rows if row and row[0]]
    except Exception:
        return []


def _send_via_resend(to: list[str], subject: str, html: str, text: str) -> dict[str, Any]:
    api_key = _env("RESEND_API_KEY")
    if not api_key:
        return {"ok": False, "error": "RESEND_API_KEY nao configurado", "not_configured": True}
    payload = {
        "from": newsletter_from(),
        "to": to,
        "subject": subject,
        "html": html,
        "text": text,
    }
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        print(
            f"[newsletter] Resend HTTP {resp.status_code}: {resp.text[:300]}",
            flush=True,
        )
        return {
            "ok": False,
            "error": f"Resend HTTP {resp.status_code}",
            "body": resp.text[:500],
            "status_code": resp.status_code,
        }
    return {"ok": True, "provider": "resend", "id": resp.json().get("id")}


def _send_via_smtp(to: list[str], subject: str, html: str, text: str) -> dict[str, Any]:
    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT") or "587")
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    from_addr = _env("SMTP_FROM") or newsletter_from()
    if not host or not from_addr:
        return {"ok": False, "error": "SMTP_HOST ou SMTP_FROM nao configurado", "not_configured": True}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    msg["Reply-To"] = from_addr
    # Cabeçalhos leves que ajudam filtros a tratar como transacional.
    msg["X-Auto-Response-Suppress"] = "OOF, AutoReply"
    msg["Auto-Submitted"] = "auto-generated"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if _env("SMTP_TLS", "true").lower() not in ("0", "false", "no"):
                server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, to, msg.as_string())
        return {"ok": True, "provider": "smtp", "recipients": len(to)}
    except Exception as exc:
        print(f"[newsletter] SMTP falhou: {exc}", flush=True)
        return {"ok": False, "error": str(exc)[:300], "provider": "smtp"}


def _send_via_webhook(to: list[str], subject: str, html: str, text: str) -> dict[str, Any]:
    url = _env("NEWSLETTER_WEBHOOK_URL")
    if not url:
        return {"ok": False, "error": "NEWSLETTER_WEBHOOK_URL nao configurado", "not_configured": True}
    payload = {"subject": subject, "html": html, "text": text, "to": to, "from": newsletter_from()}
    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code >= 400:
        print(
            f"[newsletter] Webhook HTTP {resp.status_code}: {resp.text[:300]}",
            flush=True,
        )
        return {
            "ok": False,
            "error": f"Webhook HTTP {resp.status_code}",
            "body": resp.text[:500],
            "status_code": resp.status_code,
        }
    return {"ok": True, "provider": "webhook"}


def send_email(to: list[str], subject: str, html: str, text: str) -> dict[str, Any]:
    """Dispara e-mail pelos provedores configurados (Resend → SMTP → webhook)."""
    recipients = [e.strip().lower() for e in to if e and "@" in e]
    if not recipients:
        return {"ok": False, "error": "Nenhum destinatario valido"}
    if not is_send_configured():
        print("[newsletter] mailer nao configurado", flush=True)
        return {
            "ok": False,
            "error": "Nenhum provedor de envio configurado",
            "not_configured": True,
        }

    if _env("RESEND_API_KEY"):
        return _send_via_resend(recipients, subject, html, text)
    if _env("SMTP_HOST"):
        return _send_via_smtp(recipients, subject, html, text)
    if _env("NEWSLETTER_WEBHOOK_URL"):
        return _send_via_webhook(recipients, subject, html, text)
    print("[newsletter] mailer nao configurado", flush=True)
    return {"ok": False, "error": "Provedor indisponivel", "not_configured": True}


def build_verification_email(*, name: str, token: str, ttl_hours: int = 48) -> dict[str, str]:
    display_name = (name or "").strip() or "leitor"
    safe_name = escape(display_name)
    origin = site_origin()
    verify_url = f"{origin}/verificar-email?token={token}"
    # Assunto sóbrio (menos gatilhos de spam) + preheader no HTML.
    subject = "Ative sua conta na comunidade Clareza Capital"
    text = (
        f"Olá, {display_name},\n\n"
        "Você se cadastrou na comunidade do Clareza Capital (comentários e perfil).\n"
        "Para concluir, confirme este endereço de e-mail abrindo o link abaixo:\n\n"
        f"{verify_url}\n\n"
        f"Validade: {ttl_hours} horas · uso único.\n\n"
        "Não encontrou o e-mail na caixa de entrada?\n"
        "• Verifique a pasta Spam / Lixo eletrônico / Promoções\n"
        "• Marque a mensagem como confiável para receber os próximos avisos\n"
        "• Se precisar, use “Reenviar link” na página de entrar\n\n"
        "Não foi você? Ignore este e-mail — nenhuma ação será tomada.\n\n"
        "Clareza Capital · análises com dados de mercado\n"
        f"{origin}\n"
        "Este é um e-mail transacional de confirmação de cadastro."
    )
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,Helvetica,sans-serif;color:#0f172a;">
  <span style="display:none!important;visibility:hidden;opacity:0;height:0;width:0;overflow:hidden;">
    Confirme seu e-mail para ativar comentários e perfil no Clareza Capital. Link válido por {ttl_hours}h.
  </span>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" style="max-width:560px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;">
        <tr><td style="padding:28px 32px;">
          <p style="margin:0 0 8px;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#16a34a;">Clareza Capital</p>
          <h1 style="margin:0 0 16px;font-size:22px;font-weight:700;color:#0f172a;">Ative sua conta</h1>
          <p style="margin:0 0 12px;font-size:15px;line-height:1.6;">Olá, <strong>{safe_name}</strong>,</p>
          <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#475569;">
            Recebemos seu cadastro na comunidade. Confirme este e-mail para comentar nas análises,
            gerenciar o perfil e receber avisos da conta.
          </p>
          <p style="margin:0 0 24px;">
            <a href="{escape(verify_url)}" style="display:inline-block;padding:12px 22px;background:#2563eb;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:700;font-size:14px;">
              Confirmar e-mail e ativar conta
            </a>
          </p>
          <p style="margin:0 0 16px;font-size:13px;line-height:1.5;color:#64748b;">
            O link é de uso único e expira em <strong>{ttl_hours} horas</strong>.
          </p>
          <p style="margin:0 0 8px;font-size:12px;line-height:1.5;color:#64748b;">
            Se o botão não abrir, copie e cole no navegador:<br>
            <a href="{escape(verify_url)}" style="color:#2563eb;word-break:break-all;">{escape(verify_url)}</a>
          </p>
          <hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0;">
          <p style="margin:0 0 8px;font-size:12px;line-height:1.55;color:#64748b;">
            <strong>Não achou este e-mail?</strong> Olhe em Spam, Lixo eletrônico ou Promoções e
            marque como confiável. Na página de entrar você também pode solicitar um novo link.
          </p>
          <p style="margin:0;font-size:11px;line-height:1.5;color:#94a3b8;">
            Você recebeu esta mensagem porque alguém usou este endereço no cadastro do Clareza Capital.
            Se não foi você, ignore — nenhuma conta será ativada sem esta confirmação.<br><br>
            Clareza Capital · {escape(origin)}
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return {"subject": subject, "text": text, "html": html, "verify_url": verify_url}


def send_verification_email(*, email: str, name: str, token: str, ttl_hours: int = 48) -> dict[str, Any]:
    payload = build_verification_email(name=name, token=token, ttl_hours=ttl_hours)
    result = send_email([email], payload["subject"], payload["html"], payload["text"])
    if result.get("ok"):
        print(
            f"[newsletter] verificacao enviada para={email} provider={result.get('provider')}",
            flush=True,
        )
    else:
        err = result.get("error") or "falha desconhecida"
        print(f"[newsletter] verificacao NAO enviada para={email}: {err}", flush=True)
    return {**result, "verify_url": payload["verify_url"]}


def _format_macro_panel(bcb: dict[str, dict[str, Any]], market: dict[str, Any]) -> str:
    lines: list[str] = []
    selic = (bcb.get("Selic meta (% a.a.)") or {}).get("valor")
    ipca = (bcb.get("IPCA acumulado 12 meses (%)") or {}).get("valor")
    if selic:
        lines.append(f"Selic meta: {selic}% a.a.")
    if ipca:
        lines.append(f"IPCA 12m: {ipca}%")
    usd = market.get("Dólar (USD/BRL)") or market.get("Dolar (USD/BRL)")
    if isinstance(usd, dict) and usd.get("cotacao"):
        lines.append(f"USD/BRL: {usd.get('cotacao')} ({usd.get('variacao_24h', '')})")
    btc = market.get("Bitcoin (BTC/BRL)") or market.get("Bitcoin (BTC/BRL)")
    if isinstance(btc, dict) and btc.get("cotacao"):
        lines.append(f"BTC/BRL: {btc.get('cotacao')}")
    return " | ".join(lines) if lines else "Painel macro indisponível no momento."


def datetime_hour_local() -> int:
    from datetime import datetime

    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Sao_Paulo")).hour
    except Exception:
        return datetime.now().hour


def _now_local():
    from datetime import datetime

    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _privacy_url() -> str:
    return f"{site_origin()}/privacidade"


def _fetch_important_news(
    client,
    *,
    max_items: int = DIGEST_TOP_N,
    min_priority: int = DIGEST_MIN_PRIORITY,
    lookback_hours: int,
) -> list[dict[str, str]]:
    """Seleciona até max_items matérias Alta (home_priority) na janela recente."""
    import core

    limit = max(20, max_items * 10)
    try:
        result = client.execute(
            """
            SELECT id, titulo, resumo, tag,
                   COALESCE(home_priority, 0) AS prio,
                   COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao
            FROM news
            WHERE COALESCE(home_priority, 0) >= ?
              AND LENGTH(COALESCE(resumo, '')) >= 200
            ORDER BY COALESCE(home_priority, 0) DESC, id DESC
            LIMIT ?
            """,
            [min_priority, limit],
        )
    except Exception:
        return []

    cutoff = _now_local().timestamp() - max(1, lookback_hours) * 3600
    items: list[dict[str, str]] = []
    origin = site_origin()
    for row in result.rows or []:
        prio = int(row[4] or 0)
        if prio < min_priority:
            continue
        published = core.parse_article_datetime(row[5] if len(row) > 5 else None)
        if published is not None and published.timestamp() < cutoff:
            continue
        nid = int(row[0])
        titulo = str(row[1] or "").strip()
        if not titulo:
            continue
        resumo = str(row[2] or "").strip()
        if len(resumo) > 320:
            resumo = resumo[:317].rstrip() + "…"
        items.append(
            {
                "titulo": titulo,
                "resumo": resumo,
                "tag": str(row[3] or "Economia"),
                "url": f"{origin}/noticia/{nid}",
                "priority": str(prio),
            }
        )
        if len(items) >= max(1, max_items):
            break
    return items


def _subject_from_items(items: list[dict[str, str]], *, fallback: str) -> str:
    if not items:
        return fallback
    title = items[0]["titulo"].strip()
    if len(items) == 1:
        return f"{BRAND_NAME}: {title[:110]}"
    return f"{BRAND_NAME}: {title[:70]} · e mais 1 destaque"


def _digest_intro(items: list[dict[str, str]], *, kind: str) -> str:
    n = len(items)
    if kind == "weekly":
        if n <= 1:
            return (
                "Selecionamos o destaque mais importante da semana — "
                "urgência editorial Alta, com impacto direto no mercado."
            )
        return (
            "Dois destaques de urgência Alta da semana: o essencial para acompanhar "
            "sem ruído, com leitura objetiva."
        )
    # daily
    period = "manhã" if datetime_hour_local() < 14 else "tarde"
    if n <= 1:
        return (
            f"Um alerta da {period}: matéria de urgência Alta que vale sua atenção agora. "
            "Priorizamos o que move o mercado — não a lista completa do dia."
        )
    return (
        f"Dois pontos da {period} com urgência Alta. "
        "Só o que mais importa neste momento, sem sobrecarregar sua caixa de entrada."
    )


def _lgpd_footer_text() -> str:
    return (
        f"Você recebe este e-mail por estar inscrito na newsletter do {BRAND_NAME}. "
        f"Para exercer direitos LGPD (acesso, correção, eliminação ou revogação), "
        f"consulte: {_privacy_url()}"
    )


def _render_digest_email(
    *,
    subject: str,
    intro: str,
    items: list[dict[str, str]],
    macro: str,
    eyebrow: str,
) -> tuple[str, str]:
    """Retorna (text, html) com layout limpo Clareza Capital + rodapé LGPD."""
    origin = site_origin()
    privacy = _privacy_url()
    text_parts = [
        subject,
        "",
        intro,
        "",
        f"Contexto de mercado: {macro}",
        "",
    ]
    for i, item in enumerate(items, start=1):
        text_parts.extend(
            [
                f"{i}. {item['titulo']} ({item['tag']})",
                item["resumo"],
                f"Ler: {item['url']}",
                "",
            ]
        )
    text_parts.extend([f"Portal: {origin}", "", _lgpd_footer_text()])

    articles_html: list[str] = []
    for item in items:
        articles_html.append(
            f"""
          <tr><td style="padding:0 0 20px;">
            <p style="margin:0 0 6px;font-size:12px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">
              {escape(item['tag'])}
            </p>
            <h2 style="margin:0 0 10px;font-size:18px;line-height:1.35;color:#0f172a;">
              <a href="{escape(item['url'])}" style="color:#0f172a;text-decoration:none;">{escape(item['titulo'])}</a>
            </h2>
            <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#475569;">{escape(item['resumo'])}</p>
            <a href="{escape(item['url'])}" style="display:inline-block;padding:10px 18px;background:#0f766e;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:700;font-size:13px;">
              Ler análise completa
            </a>
          </td></tr>"""
        )

    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,Helvetica,sans-serif;color:#0f172a;">
  <span style="display:none!important;visibility:hidden;opacity:0;height:0;width:0;overflow:hidden;">
    {escape(intro[:140])}
  </span>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" style="max-width:560px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;">
        <tr><td style="padding:28px 32px;">
          <p style="margin:0 0 8px;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#0f766e;">{escape(BRAND_NAME)}</p>
          <p style="margin:0 0 6px;font-size:12px;color:#64748b;">{escape(eyebrow)}</p>
          <h1 style="margin:0 0 14px;font-size:20px;font-weight:700;color:#0f172a;line-height:1.3;">{escape(subject)}</h1>
          <p style="margin:0 0 18px;font-size:15px;line-height:1.6;color:#475569;">{escape(intro)}</p>
          <p style="margin:0 0 22px;padding:12px 14px;background:#f1f5f9;border-radius:8px;font-size:13px;line-height:1.5;color:#334155;">
            <strong>Contexto:</strong> {escape(macro)}
          </p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
            {"".join(articles_html)}
          </table>
          <hr style="border:none;border-top:1px solid #e2e8f0;margin:8px 0 16px;">
          <p style="margin:0 0 8px;font-size:13px;">
            <a href="{escape(origin)}" style="color:#0f766e;font-weight:700;text-decoration:none;">Abrir o portal {escape(BRAND_NAME)}</a>
          </p>
          <p style="margin:0;font-size:11px;line-height:1.55;color:#94a3b8;">
            Você recebe este e-mail por estar inscrito na newsletter do {escape(BRAND_NAME)}.
            Para exercer direitos LGPD (acesso, correção, eliminação ou revogação do consentimento),
            acesse a <a href="{escape(privacy)}" style="color:#64748b;">política de privacidade</a>.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return "\n".join(text_parts), html


def build_weekly_digest(client, *, top_n: int = DIGEST_TOP_N) -> dict[str, Any]:
    """Digest semanal: no máximo 1–2 matérias de urgência Alta + painel macro."""
    import core

    items = _fetch_important_news(
        client,
        max_items=max(1, min(top_n, DIGEST_TOP_N)),
        lookback_hours=WEEKLY_DIGEST_LOOKBACK_DAYS * 24,
    )
    market = core.fetch_market_snapshot(blocking=False)
    bcb = core.fetch_bcb_snapshot(blocking=False)
    macro = _format_macro_panel(bcb, market)
    intro = _digest_intro(items, kind="weekly")
    subject = _subject_from_items(
        items,
        fallback=f"{BRAND_NAME} — Resumo semanal do mercado",
    )
    text, html = _render_digest_email(
        subject=subject,
        intro=intro,
        items=items,
        macro=macro,
        eyebrow="Resumo semanal · só o essencial",
    )
    return {
        "subject": subject,
        "text": text,
        "html": html,
        "items": items,
        "macro": macro,
        "skip_send": len(items) == 0,
    }


def send_weekly_digest(client) -> dict[str, Any]:
    digest = build_weekly_digest(client)
    if digest.get("skip_send"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "sem noticias de alta importancia na janela",
            "items": 0,
        }
    recipients = _subscriber_emails(client)
    if not recipients:
        return {"ok": False, "error": "Nenhum inscrito", "digest_preview": digest["subject"]}
    result = send_email(recipients, digest["subject"], digest["html"], digest["text"])
    return {**result, "recipients": len(recipients), "items": len(digest["items"])}


def build_daily_digest(client, *, max_items: int = DIGEST_TOP_N, extra_n: int | None = None) -> dict[str, Any]:
    """Digest (cron até 2x/dia): 1–2 matérias Alta na janela recente; sem lista longa."""
    import core

    # extra_n legado ignorado — volume reduzido de propósito.
    _ = extra_n
    cap = max(1, min(max_items, DIGEST_TOP_N))
    items = _fetch_important_news(
        client,
        max_items=cap,
        lookback_hours=DAILY_DIGEST_LOOKBACK_HOURS,
    )
    market = core.fetch_market_snapshot(blocking=False)
    bcb = core.fetch_bcb_snapshot(blocking=False)
    macro = _format_macro_panel(bcb, market)
    period = "manhã" if datetime_hour_local() < 14 else "tarde"
    intro = _digest_intro(items, kind="daily")
    subject = _subject_from_items(
        items,
        fallback=f"{BRAND_NAME} — Destaque da {period}",
    )
    text, html = _render_digest_email(
        subject=subject,
        intro=intro,
        items=items,
        macro=macro,
        eyebrow=f"Destaque da {period} · urgência Alta",
    )
    headline = items[0] if items else None
    return {
        "subject": subject,
        "text": text,
        "html": html,
        "items": items,
        "headline": headline,
        "links": [],
        "macro": macro,
        "period": period,
        "skip_send": len(items) == 0,
    }


def send_daily_digest(client) -> dict[str, Any]:
    digest = build_daily_digest(client)
    if digest.get("skip_send"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "sem noticias de alta importancia na janela",
            "items": 0,
            "links": 0,
            "has_headline": False,
            "period": digest["period"],
        }
    recipients = _subscriber_emails(client)
    if not recipients:
        return {"ok": False, "error": "Nenhum inscrito", "digest_preview": digest["subject"]}
    result = send_email(recipients, digest["subject"], digest["html"], digest["text"])
    return {
        **result,
        "recipients": len(recipients),
        "items": len(digest["items"]),
        "links": 0,
        "has_headline": bool(digest["headline"]),
        "period": digest["period"],
    }


def build_urgency_alert(
    news_id: int,
    titulo: str,
    tag: str,
    resumo: str,
    priority: int,
) -> dict[str, str]:
    _ = priority  # limiar aplicado em send_urgency_alert
    origin = site_origin()
    privacy = _privacy_url()
    title = (titulo or "").strip() or "Atualização de mercado"
    subject = f"{BRAND_NAME}: {title[:110]}"
    url = f"{origin}/noticia/{news_id}"
    summary = (resumo or "").strip()
    if len(summary) > 320:
        summary = summary[:317].rstrip() + "…"
    intro = (
        "Alerta de urgência Alta: publicamos uma análise que pode afetar decisões "
        "no curto prazo. Leitura rápida abaixo."
    )
    text = (
        f"{subject}\n\n"
        f"{intro}\n\n"
        f"{title} ({tag})\n"
        f"{summary}\n\n"
        f"Ler: {url}\n\n"
        f"{_lgpd_footer_text()}"
    )
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,Helvetica,sans-serif;color:#0f172a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" style="max-width:560px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;">
        <tr><td style="padding:28px 32px;">
          <p style="margin:0 0 8px;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#0f766e;">{escape(BRAND_NAME)}</p>
          <p style="margin:0 0 8px;font-size:12px;font-weight:700;color:#b91c1c;">Alerta · urgência Alta</p>
          <h1 style="margin:0 0 12px;font-size:20px;font-weight:700;line-height:1.3;">{escape(title)}</h1>
          <p style="margin:0 0 10px;font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">{escape(tag or "Economia")}</p>
          <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#475569;">{escape(intro)}</p>
          <p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:#334155;">{escape(summary)}</p>
          <p style="margin:0 0 20px;">
            <a href="{escape(url)}" style="display:inline-block;padding:12px 20px;background:#0f766e;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:700;font-size:14px;">
              Ler análise completa
            </a>
          </p>
          <hr style="border:none;border-top:1px solid #e2e8f0;margin:8px 0 16px;">
          <p style="margin:0;font-size:11px;line-height:1.55;color:#94a3b8;">
            Você recebe este alerta por estar inscrito na newsletter do {escape(BRAND_NAME)}.
            Direitos LGPD: <a href="{escape(privacy)}" style="color:#64748b;">política de privacidade</a>.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return {"subject": subject, "text": text, "html": html}


def _alert_already_sent(client, news_id: int) -> bool:
    try:
        result = client.execute(
            "SELECT 1 FROM newsletter_alert_log WHERE news_id = ? LIMIT 1",
            [news_id],
        )
        return bool(result.rows)
    except Exception:
        return False


def _mark_alert_sent(client, news_id: int, agora: str) -> None:
    try:
        client.execute(
            "INSERT OR IGNORE INTO newsletter_alert_log (news_id, sent_at) VALUES (?, ?)",
            [news_id, agora],
        )
    except Exception:
        pass


def send_urgency_alert(
    client,
    news_id: int,
    titulo: str,
    tag: str,
    resumo: str,
    priority: int,
    *,
    agora: str | None = None,
) -> dict[str, Any]:
    """Envia alerta de urgência alta (home_priority >= 80) aos inscritos."""
    from datetime import datetime

    if priority < 80:
        return {"ok": False, "skipped": True, "reason": "prioridade abaixo do limiar"}
    if _alert_already_sent(client, news_id):
        return {"ok": False, "skipped": True, "reason": "alerta ja enviado"}
    if not is_send_configured():
        return {"ok": False, "error": "Envio nao configurado"}

    recipients = _subscriber_emails(client)
    if not recipients:
        return {"ok": False, "error": "Nenhum inscrito"}

    payload = build_urgency_alert(news_id, titulo, tag, resumo, priority)
    result = send_email(recipients, payload["subject"], payload["html"], payload["text"])
    if result.get("ok"):
        ts = agora or datetime.now().strftime("%d/%m/%Y %H:%M")
        _mark_alert_sent(client, news_id, ts)
    return {**result, "news_id": news_id, "recipients": len(recipients)}


def enqueue_urgency_alert(
    client,
    news_id: int,
    titulo: str,
    tag: str,
    resumo: str,
    priority: int,
) -> None:
    """Dispara alerta em thread daemon para não bloquear persistência."""

    def _worker() -> None:
        try:
            send_urgency_alert(client, news_id, titulo, tag, resumo, priority)
        except Exception as exc:
            print(f"   [newsletter] alerta urgencia falhou (id={news_id}): {exc}")

    threading.Thread(target=_worker, daemon=True, name=f"newsletter-alert-{news_id}").start()


CONTACT_SUBJECT_MAX = 200
CONTACT_BODY_MAX = 2000


def contact_inbox() -> str:
    """Destinatário do formulário Fale conosco (CONTACT_EMAIL → NEWSLETTER_FROM)."""
    explicit = _env("CONTACT_EMAIL")
    if explicit and "@" in explicit:
        return explicit.lower()
    raw = _env("NEWSLETTER_FROM", "newsletter@financas-news.net.br")
    if "<" in raw and ">" in raw:
        inner = raw.split("<", 1)[1].split(">", 1)[0].strip()
        if "@" in inner:
            return inner.lower()
    if "@" in raw:
        return raw.lower()
    return "newsletter@financas-news.net.br"


def send_contact_message(
    *,
    subject: str,
    body: str,
    page_url: str = "",
    user_email: str = "",
    user_name: str = "",
    client_ip: str = "",
) -> dict[str, Any]:
    """Envia mensagem do formulário público Fale conosco para a caixa de contato."""
    subj = (subject or "").strip()
    text_body = (body or "").strip()
    if not subj or not text_body:
        return {"ok": False, "error": "empty"}
    if len(subj) > CONTACT_SUBJECT_MAX or len(text_body) > CONTACT_BODY_MAX:
        return {"ok": False, "error": "too_long"}

    to_addr = contact_inbox()
    safe_subj = escape(subj)
    safe_body = escape(text_body).replace("\n", "<br>\n")
    meta_pairs = []
    if user_name:
        meta_pairs.append(("Nome", user_name))
    if user_email:
        meta_pairs.append(("E-mail", user_email))
    if page_url:
        meta_pairs.append(("Página", page_url))
    if client_ip:
        meta_pairs.append(("IP", client_ip))
    meta_html = "<br>\n".join(f"{escape(k)}: {escape(v)}" for k, v in meta_pairs)
    meta_text = "\n".join(f"{k}: {v}" for k, v in meta_pairs)

    mail_subject = f"[Clareza Capital] Contato: {subj}"
    text = (
        f"Nova mensagem pelo formulário Fale conosco\n\n"
        f"Assunto: {subj}\n\n"
        f"{text_body}\n\n"
        f"---\n{meta_text}\n"
        f"{BRAND_NAME}\n"
    )
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>{escape(mail_subject)}</title></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,Helvetica,sans-serif;color:#0f172a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" style="max-width:560px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;">
        <tr><td style="padding:28px 32px;">
          <p style="margin:0 0 8px;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#16a34a;">{escape(BRAND_NAME)}</p>
          <h1 style="margin:0 0 16px;font-size:20px;font-weight:700;">Fale conosco</h1>
          <p style="margin:0 0 8px;font-size:14px;color:#64748b;"><strong>Assunto:</strong> {safe_subj}</p>
          <p style="margin:0 0 20px;font-size:15px;line-height:1.6;">{safe_body}</p>
          <p style="margin:0;font-size:12px;line-height:1.5;color:#94a3b8;">{meta_html}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    result = send_email([to_addr], mail_subject, html, text)
    if not result.get("ok"):
        # Fallback: registra para não perder a mensagem se o mailer falhar.
        print(
            f"[contact] falha no envio subject={subj[:40]!r} to={to_addr} "
            f"err={result.get('error')}",
            flush=True,
        )
        print(
            f"[contact] mensagem recebida subject={subj!r} body_len={len(text_body)} "
            f"page={page_url!r} user={user_email or '-'}",
            flush=True,
        )
        if result.get("not_configured"):
            # Sem provedor: consideramos "aceito" após log (não perde o lead).
            return {"ok": True, "logged": True, "not_configured": True}
    return result
