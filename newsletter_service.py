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

SITE_ORIGIN = os.getenv("SITE_ORIGIN", "https://financas-news.net.br").rstrip("/")
NEWSLETTER_FROM = os.getenv("NEWSLETTER_FROM", "newsletter@financas-news.net.br").strip()
DIGEST_TOP_N = 5


def _env(key: str) -> str:
    return os.getenv(key, "").strip()


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
        return {"ok": False, "error": "RESEND_API_KEY nao configurado"}
    payload = {
        "from": NEWSLETTER_FROM,
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
        return {"ok": False, "error": f"Resend HTTP {resp.status_code}", "body": resp.text[:500]}
    return {"ok": True, "provider": "resend", "id": resp.json().get("id")}


def _send_via_smtp(to: list[str], subject: str, html: str, text: str) -> dict[str, Any]:
    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT") or "587")
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    from_addr = _env("SMTP_FROM") or NEWSLETTER_FROM
    if not host or not from_addr:
        return {"ok": False, "error": "SMTP_HOST ou SMTP_FROM nao configurado"}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
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
        return {"ok": False, "error": str(exc)[:300], "provider": "smtp"}


def _send_via_webhook(to: list[str], subject: str, html: str, text: str) -> dict[str, Any]:
    url = _env("NEWSLETTER_WEBHOOK_URL")
    if not url:
        return {"ok": False, "error": "NEWSLETTER_WEBHOOK_URL nao configurado"}
    payload = {"subject": subject, "html": html, "text": text, "to": to, "from": NEWSLETTER_FROM}
    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code >= 400:
        return {"ok": False, "error": f"Webhook HTTP {resp.status_code}", "body": resp.text[:500]}
    return {"ok": True, "provider": "webhook"}


def send_email(to: list[str], subject: str, html: str, text: str) -> dict[str, Any]:
    """Dispara e-mail pelos provedores configurados (Resend → SMTP → webhook)."""
    recipients = [e.strip().lower() for e in to if e and "@" in e]
    if not recipients:
        return {"ok": False, "error": "Nenhum destinatario valido"}
    if not is_send_configured():
        return {"ok": False, "error": "Nenhum provedor de envio configurado"}

    if _env("RESEND_API_KEY"):
        return _send_via_resend(recipients, subject, html, text)
    if _env("SMTP_HOST"):
        return _send_via_smtp(recipients, subject, html, text)
    if _env("NEWSLETTER_WEBHOOK_URL"):
        return _send_via_webhook(recipients, subject, html, text)
    return {"ok": False, "error": "Provedor indisponivel"}


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

    subject = "Finanças News — Resumo semanal do mercado"
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


def build_urgency_alert(
    news_id: int,
    titulo: str,
    tag: str,
    resumo: str,
    priority: int,
) -> dict[str, str]:
    subject = f"Alerta Finanças News — {titulo[:120]}"
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
