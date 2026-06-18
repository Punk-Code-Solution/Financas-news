import os
import libsql_client


def get_db():
    url = os.environ.get("TURSO_DATABASE_URL", "")
    if url.startswith("wss://"):
        url = url.replace("wss://", "libsql://")

    token = os.environ.get("TURSO_AUTH_TOKEN")
    if not url or not token:
        raise ValueError("Credenciais do Turso não encontradas.")

    return libsql_client.create_client_sync(url=url, auth_token=token)


def ensure_schema(client):
    client.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT,
            resumo TEXT,
            impacto TEXT,
            link TEXT,
            tag TEXT
        )
    """)
    for col, col_type in [
        ("sentimento", "TEXT"),
        ("published_at", "TEXT"),
        ("fonte", "TEXT"),
        ("dados_mercado", "TEXT"),
        ("contexto_editorial", "TEXT"),
        ("created_at", "TEXT"),
    ]:
        try:
            client.execute(f"ALTER TABLE news ADD COLUMN {col} {col_type}")
        except Exception:
            pass

    client.execute("""
        UPDATE news
        SET created_at = published_at
        WHERE (created_at IS NULL OR created_at = '')
          AND published_at IS NOT NULL AND published_at != ''
    """)


def get_editorial_context(tag_hint=None, limit=6):
    """Busca notícias recentes do banco para cruzar tendências e evitar repetição."""
    try:
        client = get_db()
        if tag_hint:
            result = client.execute(
                "SELECT titulo, tag, sentimento, impacto FROM news WHERE tag = ? ORDER BY id DESC LIMIT ?",
                [tag_hint, limit],
            )
        else:
            result = client.execute(
                "SELECT titulo, tag, sentimento, impacto FROM news ORDER BY id DESC LIMIT ?",
                [limit],
            )

        rows = result.rows
        client.close()

        if not rows:
            return "Nenhuma notícia anterior no acervo do portal."

        lines = []
        for row in rows:
            titulo, tag, sentimento, impacto = row[0], row[1], row[2] or "Neutro", row[3] or ""
            lines.append(f"- [{tag}] {titulo} (sentimento: {sentimento})")

        sentiment_result = client_sentiment_summary(tag_hint)
        return (
            "NOTÍCIAS RECENTES JÁ PUBLICADAS NO PORTAL (use para contextualizar tendências, NÃO repita):\n"
            + "\n".join(lines)
            + f"\n\nPANORAMA DE SENTIMENTO RECENTE: {sentiment_result}"
        )
    except Exception as e:
        return f"Histórico do portal indisponível: {e}"


def client_sentiment_summary(tag_hint=None):
    try:
        client = get_db()
        if tag_hint:
            result = client.execute(
                "SELECT sentimento, COUNT(*) FROM news WHERE tag = ? GROUP BY sentimento",
                [tag_hint],
            )
        else:
            result = client.execute(
                "SELECT sentimento, COUNT(*) FROM news GROUP BY sentimento",
            )
        rows = result.rows
        client.close()

        if not rows:
            return "sem histórico suficiente"

        parts = [f"{s or 'Neutro'}: {c}" for s, c in rows]
        return ", ".join(parts)
    except Exception:
        return "indisponível"
