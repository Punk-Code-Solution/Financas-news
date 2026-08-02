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

DIGEST_TOP_N = 5

# Mensagem de UI quando o mailer falha ou não está configurado (cadastro / reenvio).
MAIL_SEND_FAIL_USER_MSG = (
    "Não foi possível enviar o e-mail. Tente mais tarde ou contate o suporte."
)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def site_origin() -> str:
    """Origem pública do site (lida em runtime — após load_dotenv / env do host)."""
    return _env("SITE_ORIGIN", "https://financas-news.net.br").rstrip("/")


def newsletter_from() -> str:
    return _env("NEWSLETTER_FROM", "newsletter@financas-news.net.br")


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
    return " | ".join(lines) if lines else "Painel macro indisponivel no momento."


def build_weekly_digest(client, *, top_n: int = DIGEST_TOP_N) -> dict[str, Any]:
    """Monta digest semanal: top N notícias + painel macro."""
    import core

    result = client.execute(
        """
        SELECT id, titulo, resumo, tag,
               COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao
        FROM news
        ORDER BY id DESC LIMIT ?
        """,
        [max(1, top_n)],
    )
    rows = list(result.rows or [])
    market = core.fetch_market_snapshot(blocking=False)
    bcb = core.fetch_bcb_snapshot(blocking=False)
    macro = _format_macro_panel(bcb, market)

    items: list[dict[str, str]] = []
    for row in rows:
        nid = int(row[0])
        titulo = str(row[1] or "")
        resumo = str(row[2] or "")[:280]
        tag = str(row[3] or "")
        url = f"{SITE_ORIGIN}/noticia/{nid}"
        items.append({"titulo": titulo, "resumo": resumo, "tag": tag, "url": url})

    subject = "Clareza Capital — Resumo semanal do mercado"
    text_parts = [subject, "", f"Painel macro: {macro}", "", "Destaques da semana:"]
    html_parts = [
        f"<h1>{escape(subject)}</h1>",
        f"<p><strong>Painel macro:</strong> {escape(macro)}</p>",
        "<h2>Destaques</h2><ul>",
    ]
    for item in items:
        text_parts.append(f"- {item['titulo']} ({item['tag']})\n  {item['url']}")
        html_parts.append(
            f"<li><a href=\"{escape(item['url'])}\">{escape(item['titulo'])}</a>"
            f" <em>({escape(item['tag'])})</em><br>{escape(item['resumo'])}</li>"
        )
    html_parts.append("</ul>")
    html_parts.append(f'<p><a href="{SITE_ORIGIN}">Ver mais no portal</a></p>')

    return {
        "subject": subject,
        "text": "\n".join(text_parts),
        "html": "".join(html_parts),
        "items": items,
        "macro": macro,
    }


def send_weekly_digest(client) -> dict[str, Any]:
    digest = build_weekly_digest(client)
    recipients = _subscriber_emails(client)
    if not recipients:
        return {"ok": False, "error": "Nenhum inscrito", "digest_preview": digest["subject"]}
    result = send_email(recipients, digest["subject"], digest["html"], digest["text"])
    return {**result, "recipients": len(recipients), "items": len(digest["items"])}


DAILY_DIGEST_EXTRA = 8


def build_daily_digest(client, *, extra_n: int = DAILY_DIGEST_EXTRA) -> dict[str, Any]:
    """Digest 2x/dia: notícia principal (home_priority) + links das demais recentes."""
    import core

    main_row = client.execute(
        """
        SELECT id, titulo, resumo, tag,
               COALESCE(home_priority, 0) AS prio,
               COALESCE(NULLIF(published_at, ''), created_at) AS data_publicacao
        FROM news
        WHERE LENGTH(COALESCE(resumo, '')) >= 400
        ORDER BY COALESCE(home_priority, 0) DESC, id DESC
        LIMIT 1
        """
    ).rows
    others = client.execute(
        """
        SELECT id, titulo, tag
        FROM news
        WHERE LENGTH(COALESCE(resumo, '')) >= 400
        ORDER BY id DESC
        LIMIT ?
        """,
        [max(1, extra_n) + 1],
    ).rows

    market = core.fetch_market_snapshot(blocking=False)
    bcb = core.fetch_bcb_snapshot(blocking=False)
    macro = _format_macro_panel(bcb, market)

    headline: dict[str, str] | None = None
    main_id: int | None = None
    if main_row:
        r = main_row[0]
        main_id = int(r[0])
        headline = {
            "titulo": str(r[1] or ""),
            "resumo": str(r[2] or "")[:400],
            "tag": str(r[3] or ""),
            "url": f"{SITE_ORIGIN}/noticia/{main_id}",
        }

    links: list[dict[str, str]] = []
    for row in others or []:
        nid = int(row[0])
        if main_id is not None and nid == main_id:
            continue
        if len(links) >= max(1, extra_n):
            break
        links.append(
            {
                "titulo": str(row[1] or ""),
                "tag": str(row[2] or ""),
                "url": f"{SITE_ORIGIN}/noticia/{nid}",
            }
        )

    period = "manhã" if datetime_hour_local() < 14 else "tarde"
    subject = f"Clareza Capital — Destaque da {period}"
    text_parts = [subject, "", f"Painel macro: {macro}", ""]
    html_parts = [
        f"<h1>{escape(subject)}</h1>",
        f"<p><strong>Painel macro:</strong> {escape(macro)}</p>",
    ]
    if headline:
        text_parts.extend(
            [
                "Notícia principal:",
                f"{headline['titulo']} ({headline['tag']})",
                headline["resumo"],
                headline["url"],
                "",
            ]
        )
        html_parts.extend(
            [
                "<h2>Notícia principal</h2>",
                f"<p><a href=\"{escape(headline['url'])}\"><strong>{escape(headline['titulo'])}</strong></a>"
                f" <em>({escape(headline['tag'])})</em></p>",
                f"<p>{escape(headline['resumo'])}</p>",
            ]
        )
    if links:
        text_parts.append("Outras análises:")
        html_parts.append("<h2>Outras análises</h2><ul>")
        for item in links:
            text_parts.append(f"- {item['titulo']} ({item['tag']}) — {item['url']}")
            html_parts.append(
                f"<li><a href=\"{escape(item['url'])}\">{escape(item['titulo'])}</a>"
                f" <em>({escape(item['tag'])})</em></li>"
            )
        html_parts.append("</ul>")
    html_parts.append(f'<p><a href="{SITE_ORIGIN}">Abrir o portal</a></p>')

    return {
        "subject": subject,
        "text": "\n".join(text_parts),
        "html": "".join(html_parts),
        "headline": headline,
        "links": links,
        "macro": macro,
        "period": period,
    }


def datetime_hour_local() -> int:
    from datetime import datetime

    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Sao_Paulo")).hour
    except Exception:
        return datetime.now().hour


def send_daily_digest(client) -> dict[str, Any]:
    digest = build_daily_digest(client)
    recipients = _subscriber_emails(client)
    if not recipients:
        return {"ok": False, "error": "Nenhum inscrito", "digest_preview": digest["subject"]}
    result = send_email(recipients, digest["subject"], digest["html"], digest["text"])
    return {
        **result,
        "recipients": len(recipients),
        "links": len(digest["links"]),
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
    subject = f"Alerta Clareza Capital — {titulo[:120]}"
    url = f"{SITE_ORIGIN}/noticia/{news_id}"
    text = (
        f"{subject}\n\n"
        f"Categoria: {tag}\n"
        f"Prioridade editorial: {priority}\n\n"
        f"{resumo[:400]}\n\n"
        f"Leia: {url}"
    )
    html = (
        f"<h1>{escape(subject)}</h1>"
        f"<p><strong>Categoria:</strong> {escape(tag)}</p>"
        f"<p>{escape(resumo[:400])}</p>"
        f'<p><a href="{escape(url)}">Ler matéria completa</a></p>'
    )
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
