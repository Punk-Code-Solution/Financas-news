import os
import sqlite3
import ssl
import threading
from dataclasses import dataclass
from typing import Any, Protocol

import libsql_client


@dataclass
class QueryResult:
    rows: list[Any]


class DbClient(Protocol):
    def execute(self, sql: str, args: list[Any] | None = None) -> QueryResult: ...
    def close(self) -> None: ...


def _as_query_result(result: object) -> QueryResult:
    if isinstance(result, QueryResult):
        return result
    rows = getattr(result, "rows", None)
    if rows is None:
        return QueryResult([])
    return QueryResult(list(rows))


class LocalDbClient:
    """Wrapper SQLite local com a mesma interface do libsql_client sync."""

    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA temp_store=MEMORY")
        # Conexão única compartilhada entre threads — serializa o acesso.
        self._lock = threading.Lock()

    def execute(self, sql: str, args: list[Any] | None = None) -> QueryResult:
        with self._lock:
            cursor = self._conn.cursor()
            if args:
                cursor.execute(sql, args)
            else:
                cursor.execute(sql)
            if sql.strip().upper().startswith("SELECT"):
                return QueryResult(cursor.fetchall())
            self._conn.commit()
            return QueryResult([])

    def close(self) -> None:
        # Conexão reutilizada via pool — close() é no-op seguro.
        pass

    def close_hard(self) -> None:
        self._conn.close()


_client: Any = None
_client_lock = threading.Lock()
_schema_ready = False
_schema_lock = threading.Lock()


def _use_local_db() -> bool:
    return os.getenv("USE_LOCAL_DB", "").lower() in ("1", "true", "yes")


def _configure_ssl_certs() -> None:
    try:
        import certifi

        bundle = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    except ImportError:
        pass

    # Python 3.13+ ativa VERIFY_X509_STRICT e rejeita CAs com Basic Constraints
    # sem flag critical (comum em Windows com antivírus/proxy corporativo).
    # O aiohttp cria o SSLContext na importação — precisamos alterar o cache.
    if not hasattr(ssl, "VERIFY_X509_STRICT"):
        return

    if not getattr(ssl.create_default_context, "_financas_x509_relaxed", False):
        _original = ssl.create_default_context

        def create_default_context(*args, **kwargs):
            ctx = _original(*args, **kwargs)
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
            return ctx

        create_default_context._financas_x509_relaxed = True  # type: ignore[attr-defined]
        ssl.create_default_context = create_default_context  # type: ignore[assignment]

    try:
        import aiohttp.connector as aio_connector

        for name in ("_SSL_CONTEXT_VERIFIED", "_SSL_CONTEXT_UNVERIFIED"):
            ctx = getattr(aio_connector, name, None)
            if isinstance(ctx, ssl.SSLContext):
                ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    except Exception:
        pass


class PooledClient:
    """Proxy que reutiliza o client remoto sem fechar a cada request."""

    def __init__(self, inner: Any):
        self._inner = inner

    def execute(self, sql: str, args: list[Any] | None = None) -> QueryResult:
        if args is None:
            return _as_query_result(self._inner.execute(sql))
        return _as_query_result(self._inner.execute(sql, args))

    def close(self) -> None:
        pass

    def close_hard(self) -> None:
        try:
            self._inner.close()
        except Exception:
            pass


def _create_client() -> LocalDbClient | PooledClient:
    if _use_local_db():
        path = os.getenv("LOCAL_DATABASE_PATH", "news.db")
        return LocalDbClient(path)

    _configure_ssl_certs()

    url = os.environ.get("TURSO_DATABASE_URL", "")
    # Preferir HTTPS: o handshake WSS do Hrana falha em alguns ambientes
    # (proxy/antivírus). O cliente HTTP do libsql_client é equivalente.
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://") :]
    elif url.startswith("wss://"):
        url = "https://" + url[len("wss://") :]
    elif url.startswith("ws://"):
        url = "http://" + url[len("ws://") :]

    token = os.environ.get("TURSO_AUTH_TOKEN")
    if not url or not token:
        raise ValueError(
            "Credenciais do Turso não encontradas. "
            "Defina TURSO_DATABASE_URL e TURSO_AUTH_TOKEN, ou USE_LOCAL_DB=true para SQLite local."
        )

    return PooledClient(libsql_client.create_client_sync(url=url, auth_token=token))


def get_db() -> LocalDbClient | PooledClient:
    """Reutiliza um único client global.

    Um client por thread vazava sessões aiohttp: as threads do pool do FastAPI
    (e a de warmup) morrem e o client era coletado sem close() — gerando os
    avisos "Unclosed client session". O client sync do libsql roda seu próprio
    event loop em background e aceita chamadas de várias threads.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _create_client()
    return _client


def ensure_schema(client: DbClient) -> None:
    global _schema_ready
    if _schema_ready:
        return

    with _schema_lock:
        if _schema_ready:
            return

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
            ("conteudo_extra", "TEXT"),
            ("updated_at", "TEXT"),
            ("versao_analise", "INTEGER"),
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

        # Índices para listagens / filtros da home e relacionados.
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_news_id_desc ON news(id DESC)",
            "CREATE INDEX IF NOT EXISTS idx_news_tag_id ON news(tag, id DESC)",
        ):
            try:
                client.execute(sql)
            except Exception:
                pass

        _schema_ready = True


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

        if not rows:
            return "sem histórico suficiente"

        parts = [f"{s or 'Neutro'}: {c}" for s, c in rows]
        return ", ".join(parts)
    except Exception:
        return "indisponível"
