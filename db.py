import os
import sqlite3
from dataclasses import dataclass

import libsql_client


@dataclass
class QueryResult:
    rows: list


class LocalDbClient:
    """Wrapper SQLite local com a mesma interface do libsql_client sync."""

    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)

    def execute(self, sql: str, args: list | None = None):
        cursor = self._conn.cursor()
        if args:
            cursor.execute(sql, args)
        else:
            cursor.execute(sql)
        if sql.strip().upper().startswith("SELECT"):
            return QueryResult(cursor.fetchall())
        self._conn.commit()
        return QueryResult([])

    def close(self):
        self._conn.close()


def _use_local_db() -> bool:
    return os.getenv("USE_LOCAL_DB", "").lower() in ("1", "true", "yes")


def _configure_ssl_certs():
    try:
        import certifi

        bundle = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    except ImportError:
        pass


def get_db():
    if _use_local_db():
        path = os.getenv("LOCAL_DATABASE_PATH", "news.db")
        return LocalDbClient(path)

    _configure_ssl_certs()

    url = os.environ.get("TURSO_DATABASE_URL", "")
    if url.startswith("wss://"):
        url = url.replace("wss://", "libsql://")

    token = os.environ.get("TURSO_AUTH_TOKEN")
    if not url or not token:
        raise ValueError(
            "Credenciais do Turso não encontradas. "
            "Defina TURSO_DATABASE_URL e TURSO_AUTH_TOKEN, ou USE_LOCAL_DB=true para SQLite local."
        )

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
        ("imagem_url", "TEXT"),
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

    client.execute("""
        CREATE TABLE IF NOT EXISTS newsletter_subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        )
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
