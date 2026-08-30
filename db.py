import gzip
import os
import random
import re
import sqlite3
import ssl
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

import requests


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
        _ = self._conn.execute("PRAGMA journal_mode=WAL")
        _ = self._conn.execute("PRAGMA synchronous=NORMAL")
        _ = self._conn.execute("PRAGMA temp_store=MEMORY")
        # Conexão única compartilhada entre threads — serializa o acesso.
        self._lock = threading.Lock()

    def execute(self, sql: str, args: list[Any] | None = None, **_kwargs: Any) -> QueryResult:
        with self._lock:
            cursor = self._conn.cursor()
            if args:
                _ = cursor.execute(sql, args)
            else:
                _ = cursor.execute(sql)
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
_fts_ready = False
_ssl_x509_relaxed = False
_sentiment_cache: dict[str, tuple[float, str]] = {}
_sentiment_cache_lock = threading.Lock()
_SENTIMENT_CACHE_TTL = 45.0
_LINK_IN_CHUNK = 80


class DatabaseConfigError(ValueError):
    """Credenciais/banco não configurados — rotas devem responder 503."""


class DatabaseUnavailableError(RuntimeError):
    """Turso indisponível após retries — rotas públicas devem responder 503."""


class TursoQuotaError(DatabaseUnavailableError):
    """Cota/plano Turso recusou a query — retry não adianta."""


class TursoProtocolError(RuntimeError):
    """Resposta Hrana 200 sem result, ou pipeline com erro transitório."""


RESTORE_MAX_BYTES = 150 * 1024 * 1024
_COPY_BATCH_SIZE = 200
_SKIP_IMPORT_TABLES = frozenset(
    {
        "sqlite_sequence",
        "sqlite_stat1",
        "sqlite_stat4",
    }
)

_FTS_DUMP_RE = re.compile(
    r"(?:CREATE\s+VIRTUAL\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?news_fts[\s\S]*?;)"
    r"|(?:INSERT\s+INTO\s+['\"]?news_fts[\w]*['\"]?[\s\S]*?;)"
    r"|(?:DROP\s+TRIGGER\s+IF\s+EXISTS\s+news_fts_\w+\s*;)"
    r"|(?:CREATE\s+TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?news_fts_\w+[\s\S]*?END\s*;)",
    re.IGNORECASE,
)


def _http_verify() -> bool:
    return os.getenv("SSL_VERIFY", "true").strip().lower() not in ("0", "false", "no")


def _use_local_db() -> bool:
    flag = os.getenv("USE_LOCAL_DB", "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    if flag in ("0", "false", "no"):
        return False
    if os.getenv("USE_TURSO", "").strip().lower() in ("1", "true", "yes"):
        return False
    # Auto-detecta só no volume Railway — evita pegar um news.db solto no cwd local.
    if not _volume_mount_path():
        return False
    return _sqlite_file_has_news()


def using_local_sqlite() -> bool:
    return _use_local_db()


def db_backend_label() -> str:
    if _use_local_db():
        return f"sqlite:{default_local_database_path()}"
    return "turso"


def _volume_mount_path() -> str:
    return (os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or "").rstrip("/")


def default_local_database_path() -> str:
    """SQLite no volume Railway quando LOCAL_DATABASE_PATH não foi definido."""
    explicit = (os.getenv("LOCAL_DATABASE_PATH") or "").strip()
    if explicit:
        return explicit
    vol = _volume_mount_path()
    if vol:
        return f"{vol}/news.db"
    return "news.db"


def default_article_images_dir() -> str:
    """Capas no volume Railway quando ARTICLE_IMAGES_DIR não foi definido."""
    explicit = (os.getenv("ARTICLE_IMAGES_DIR") or "").strip()
    if explicit:
        return explicit
    vol = _volume_mount_path()
    if vol:
        return f"{vol}/article_images"
    return "static/images/articles"


def _sqlite_file_has_news(path: str | None = None) -> bool:
    dest = path or default_local_database_path()
    if not os.path.isfile(dest):
        return False
    try:
        if os.path.getsize(dest) < 4096:
            return False
    except OSError:
        return False
    try:
        conn = sqlite3.connect(dest)
        try:
            row = conn.execute("SELECT COUNT(*) FROM news").fetchone()
            return bool(row and int(row[0]) > 0)
        finally:
            conn.close()
    except Exception:
        return False


def sqlite_table_counts(path: str | None = None) -> dict[str, int]:
    dest = path or default_local_database_path()
    if not os.path.isfile(dest):
        return {}
    counts: dict[str, int] = {}
    try:
        conn = sqlite3.connect(dest)
        try:
            names = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            for (name,) in names:
                if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)):
                    continue
                if str(name).startswith("sqlite_") or str(name).startswith("news_fts"):
                    continue
                try:
                    row = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
                    counts[str(name)] = int(row[0]) if row else 0
                except sqlite3.Error:
                    continue
        finally:
            conn.close()
    except sqlite3.Error:
        return {}
    return counts


def missing_runtime_config() -> list[str]:
    """Lista vars críticas ausentes (sem valores) para log de startup."""
    missing: list[str] = []
    if not _use_local_db():
        if not (os.environ.get("TURSO_DATABASE_URL") or "").strip():
            missing.append("TURSO_DATABASE_URL")
        if not (os.environ.get("TURSO_AUTH_TOKEN") or "").strip():
            missing.append("TURSO_AUTH_TOKEN")
    if not (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEYS")
        or os.getenv("GEMINI_API_KEYS")
    ):
        missing.append("GOOGLE_API_KEY (ou GEMINI_API_KEY)")
    if not (os.getenv("ROBO_TOKEN") or "").strip():
        missing.append("ROBO_TOKEN")
    if not (os.getenv("SESSION_SECRET") or "").strip():
        missing.append("SESSION_SECRET")
    return missing


def log_runtime_config_checklist() -> None:
    missing = missing_runtime_config()
    if not missing:
        return
    host = "Railway" if (
        os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("RAILWAY_PROJECT_ID")
        or os.getenv("RENDER")
    ) else "local"
    print(
        "AVISO: configuração incompleta ("
        + host
        + "). Defina no painel de Variables (não use .env no deploy): "
        + ", ".join(missing)
    )
    if not _use_local_db() and (
        "TURSO_DATABASE_URL" in missing or "TURSO_AUTH_TOKEN" in missing
    ):
        print(
            "   Produção usa SQLite no volume (USE_LOCAL_DB=true e "
            "RAILWAY_VOLUME_MOUNT_PATH/news.db). TURSO_* só entra "
            "no import pontual /api/import-from-turso."
        )


def _configure_ssl_certs() -> None:
    try:
        import certifi

        bundle = certifi.where()
        _ = os.environ.setdefault("SSL_CERT_FILE", bundle)
        _ = os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    except ImportError:
        pass

    # Python 3.13+ ativa VERIFY_X509_STRICT e rejeita CAs com Basic Constraints
    # sem flag critical (comum em Windows com antivírus/proxy corporativo).
    # O aiohttp cria o SSLContext na importação — precisamos alterar o cache.
    if not hasattr(ssl, "VERIFY_X509_STRICT"):
        return

    global _ssl_x509_relaxed
    if not _ssl_x509_relaxed:
        _original = ssl.create_default_context

        def create_default_context(
            purpose: ssl.Purpose = ssl.Purpose.SERVER_AUTH,
            *,
            cafile: str | None = None,
            capath: str | None = None,
            cadata: str | None = None,
        ) -> ssl.SSLContext:
            ctx = _original(purpose, cafile=cafile, capath=capath, cadata=cadata)
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
            return ctx

        ssl.create_default_context = create_default_context  # type: ignore[assignment]
        _ssl_x509_relaxed = True

    try:
        import aiohttp.connector as aio_connector

        for name in ("_SSL_CONTEXT_VERIFIED", "_SSL_CONTEXT_UNVERIFIED"):
            ctx = getattr(aio_connector, name, None)
            if isinstance(ctx, ssl.SSLContext):
                ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    except Exception:
        pass


def _is_quota_block(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        n in msg
        for n in (
            "reads are blocked",
            "upgrade your plan",
            "sql read operations are forbidden",
            "code: blocked",
            "blocked: sql",
        )
    ) or (
        isinstance(exc, TursoQuotaError)
        or (isinstance(exc, TursoProtocolError) and "blocked" in msg)
    )


def _is_sql_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        n in msg
        for n in (
            "no such column",
            "no such table",
            "syntax error",
            "sqlite_",
            "constraint failed",
            "unique constraint",
        )
    )


def _is_transient_db_error(exc: BaseException) -> bool:
    """Timeouts / queda de rede / protocolo Hrana instável."""
    if isinstance(exc, (DatabaseUnavailableError, TursoQuotaError)):
        return False
    if _is_quota_block(exc):
        return False
    if _is_sql_error(exc):
        return False
    if isinstance(exc, TursoProtocolError):
        return True
    if isinstance(exc, KeyError) and exc.args and exc.args[0] == "result":
        return True
    if isinstance(
        exc,
        (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    ):
        return True
    name = type(exc).__name__
    if name in {
        "ClientConnectorError",
        "ClientOSError",
        "ServerTimeoutError",
        "ServerDisconnectedError",
        "ClientConnectionError",
        "TimeoutError",
        "CancelledError",
        "ConnectTimeout",
        "ReadTimeout",
    }:
        return True
    msg = str(exc).lower()
    needles = (
        "tempo limite do semáforo",
        "semaphore timeout",
        "winerror 121",
        "cannot connect to host",
        "connection reset",
        "temporarily unavailable",
        "timed out",
        "timeout",
        "network is unreachable",
        "client_closed",
        "client is closed",
        "server disconnected",
        "remote disconnected",
        "429",
        "502",
        "503",
        "504",
        "stream_",
        "baton",
    )
    return any(n in msg for n in needles)


class _TursoCircuit:
    """Fail-fast quando o Turso falha em sequência — evita tempestade de retry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_until = 0.0
        self._open_logged = False

    def reset(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_until = 0.0
            self._open_logged = False

    def before_execute(self) -> None:
        with self._lock:
            if time.time() < self._opened_until:
                raise DatabaseUnavailableError(
                    "Turso em circuito aberto. Tente de novo em instantes."
                )

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_until = 0.0
            self._open_logged = False

    def trip_open(self, exc: BaseException, *, cooldown_sec: float | None = None) -> None:
        """Abre o circuito imediatamente (cota BLOCKED — não adianta martelar)."""
        cooldown = float(
            cooldown_sec
            if cooldown_sec is not None
            else os.getenv("TURSO_QUOTA_COOLDOWN_SEC", "60")
        )
        with self._lock:
            self._failures = max(self._failures, 99)
            self._opened_until = time.time() + cooldown
            if self._open_logged:
                return
            self._open_logged = True
            print(
                f"   [db] circuito Turso aberto por {cooldown:.0f}s "
                f"({type(exc).__name__}: {str(exc)[:120]})",
                flush=True,
            )

    def failure(self, exc: BaseException) -> None:
        threshold = max(1, int(os.getenv("TURSO_CIRCUIT_FAILURES", "4")))
        cooldown = float(os.getenv("TURSO_CIRCUIT_COOLDOWN_SEC", "20"))
        with self._lock:
            self._failures += 1
            if self._failures < threshold:
                return
            self._opened_until = time.time() + cooldown
            if self._open_logged:
                return
            self._open_logged = True
            print(
                f"   [db] circuito Turso aberto por {cooldown:.0f}s "
                f"({type(exc).__name__}: {str(exc)[:120]})",
                flush=True,
            )


_turso_circuit = _TursoCircuit()


def reset_turso_circuit() -> None:
    _turso_circuit.reset()


def _pipeline_cell(value: Any) -> Any:
    if isinstance(value, dict) and value.get("type"):
        from libsql_client.hrana.convert import _value_from_proto

        return _value_from_proto(value)
    return value


def _pipeline_result_to_query(result: dict[str, Any]) -> QueryResult:
    rows: list[Any] = []
    for proto_row in result.get("rows") or []:
        if isinstance(proto_row, (list, tuple)):
            rows.append(tuple(_pipeline_cell(cell) for cell in proto_row))
        else:
            rows.append((proto_row,))
    return QueryResult(rows)


def _raise_pipeline_error(payload: Any) -> None:
    err = payload
    if isinstance(payload, dict):
        err = payload.get("error") or payload.get("message") or payload
    if isinstance(err, dict):
        message = str(err.get("message") or err.get("error") or err)[:300]
        code = str(err.get("code") or "UNKNOWN")
    else:
        message = str(err)[:300]
        code = "UNKNOWN"
    wrapped = TursoProtocolError(f"{code}: {message}")
    if _is_quota_block(wrapped):
        raise TursoQuotaError(
            "Turso bloqueou leituras (cota/plano). Confira o painel Turso."
        ) from wrapped
    if _is_sql_error(wrapped):
        raise RuntimeError(message) from wrapped
    raise wrapped


class TursoPipelineClient:
    """Cliente HTTP síncrono via Hrana ``/v2/pipeline``.

    O ``libsql-client`` usa ``/v1/execute`` e assume ``response['result']``.
    O Turso frequentemente responde 200 com ``error`` (quota, baton, SQL) e
    o client antigo vira ``KeyError: 'result'`` — 500 no portal.
    """

    def __init__(self, url: str, auth_token: str):
        base = url.rstrip("/")
        if base.endswith("/v2/pipeline"):
            self._url = base
        else:
            self._url = base + "/v2/pipeline"
        timeout_sec = float(os.getenv("TURSO_HTTP_TIMEOUT_SEC", "20"))
        self._timeout = (5.0, timeout_sec)
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {auth_token}"
        self._session.headers["Content-Type"] = "application/json"
        verify = os.getenv("SSL_VERIFY", "true").strip().lower() not in ("0", "false", "no")
        self._session.verify = verify

    def execute(self, sql: str, args: list[Any] | None = None, **_kwargs: Any) -> QueryResult:
        from libsql_client.hrana.convert import _stmt_to_proto

        stmt = _stmt_to_proto(sql, args)
        if not stmt.get("named_args"):
            stmt.pop("named_args", None)
        body = {
            "requests": [
                {"type": "execute", "stmt": stmt},
                {"type": "close"},
            ]
        }
        try:
            resp = self._session.post(self._url, json=body, timeout=self._timeout)
        except requests.RequestException as exc:
            raise TursoProtocolError(f"falha de rede no pipeline: {exc}") from exc

        if resp.status_code in {429, 500, 502, 503, 504}:
            preview = (resp.text or "")[:180]
            raise TursoProtocolError(f"HTTP {resp.status_code}: {preview}")
        if resp.status_code == 401:
            raise RuntimeError("Turso recusou o token (HTTP 401). Confira TURSO_AUTH_TOKEN.")
        if not resp.ok:
            preview = (resp.text or "")[:180]
            raise RuntimeError(f"Turso HTTP {resp.status_code}: {preview}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise TursoProtocolError("resposta Turso não-JSON") from exc

        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or not results:
            _raise_pipeline_error(data)
            raise TursoProtocolError("pipeline sem results")

        first = results[0]
        if not isinstance(first, dict):
            raise TursoProtocolError("item de pipeline inválido")
        if first.get("type") == "error":
            _raise_pipeline_error(first)

        response = first.get("response") or first.get("result")
        if not isinstance(response, dict):
            _raise_pipeline_error(first)

        result = response.get("result") if response.get("type") in {None, "execute"} else None
        if result is None and "cols" in response:
            result = response
        if not isinstance(result, dict):
            _raise_pipeline_error(response)
        return _pipeline_result_to_query(result)

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass


def turso_http_base_url() -> str:
    url = (os.environ.get("TURSO_DATABASE_URL") or "").strip().rstrip("/")
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://") :]
    elif url.startswith("wss://"):
        url = "https://" + url[len("wss://") :]
    elif url.startswith("ws://"):
        url = "http://" + url[len("ws://") :]
    for suffix in ("/v2/pipeline", "/v1/execute"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url.rstrip("/")


def _turso_client_for_import() -> "TursoPipelineClient":
    url = turso_http_base_url()
    token = (os.environ.get("TURSO_AUTH_TOKEN") or "").strip()
    if not url or not token:
        raise DatabaseConfigError(
            "TURSO_DATABASE_URL e TURSO_AUTH_TOKEN sao necessarios para o import."
        )
    return TursoPipelineClient(url, token)


def _strip_fts_from_dump(sql: str) -> str:
    return _FTS_DUMP_RE.sub("\n", sql)


def _remove_sqlite_sidecars(dest: str) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        extra = dest + suffix
        try:
            if os.path.isfile(extra):
                os.remove(extra)
        except OSError:
            pass


def _atomic_replace_sqlite(tmp_path: str, dest: str) -> None:
    dest_dir = os.path.dirname(dest) or "."
    os.makedirs(dest_dir, exist_ok=True)
    _remove_sqlite_sidecars(dest)
    os.replace(tmp_path, dest)


def apply_sql_dump_to_sqlite(sql_text: str, dest_path: str) -> dict[str, Any]:
    """Aplica dump SQL (Turso/SQLite) num arquivo novo, sem FTS legado."""
    cleaned = _strip_fts_from_dump(sql_text)
    dest_dir = os.path.dirname(dest_path) or "."
    os.makedirs(dest_dir, exist_ok=True)
    tmp = dest_path + ".importing"
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp)
    try:
        _ = conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript(cleaned)
        try:
            _ = conn.execute("DROP TABLE IF EXISTS news_fts")
        except sqlite3.Error:
            pass
        conn.commit()
    except sqlite3.Error as exc:
        conn.close()
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError(f"dump SQL invalido: {exc}") from exc
    conn.close()
    _atomic_replace_sqlite(tmp, dest_path)
    return {"bytes": os.path.getsize(dest_path)}


def install_sqlite_bytes(data: bytes, dest_path: str) -> dict[str, Any]:
    if not data.startswith(b"SQLite format 3"):
        raise ValueError("arquivo nao e um banco SQLite")
    dest_dir = os.path.dirname(dest_path) or "."
    os.makedirs(dest_dir, exist_ok=True)
    tmp = dest_path + ".importing"
    with open(tmp, "wb") as handle:
        handle.write(data)
    _atomic_replace_sqlite(tmp, dest_path)
    return {"bytes": len(data)}


def _maybe_gunzip(data: bytes) -> bytes:
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    if len(data) > RESTORE_MAX_BYTES:
        raise ValueError("arquivo restaurado excede o limite")
    return data


def restore_sqlite_payload(data: bytes, dest_path: str) -> dict[str, Any]:
    payload = _maybe_gunzip(data)
    if payload.startswith(b"SQLite format 3"):
        result = install_sqlite_bytes(payload, dest_path)
        result["format"] = "sqlite"
        return result
    text = payload.decode("utf-8-sig")
    result = apply_sql_dump_to_sqlite(text, dest_path)
    result["format"] = "sql"
    return result


def fetch_turso_sql_dump(*, timeout_sec: float = 180.0) -> str:
    base = turso_http_base_url()
    token = (os.environ.get("TURSO_AUTH_TOKEN") or "").strip()
    if not base or not token:
        raise DatabaseConfigError(
            "TURSO_DATABASE_URL e TURSO_AUTH_TOKEN sao necessarios para o dump."
        )
    dump_url = base + "/dump"
    try:
        resp = requests.get(
            dump_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_sec,
            verify=_http_verify(),
        )
    except requests.RequestException as exc:
        raise TursoProtocolError(f"falha de rede no dump: {exc}") from exc

    body = resp.text or ""
    if (
        resp.status_code in {401, 403}
        or _is_quota_block(RuntimeError(body))
        or "BLOCKED" in body.upper()
    ):
        raise TursoQuotaError("Turso recusou o dump (cota/plano).")
    if not resp.ok:
        preview = body[:180]
        raise TursoProtocolError(f"dump HTTP {resp.status_code}: {preview}")
    raw = resp.content or b""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8-sig")


def _should_skip_import_table(name: str) -> bool:
    lowered = name.lower()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return True
    if lowered in _SKIP_IMPORT_TABLES:
        return True
    if lowered.startswith("sqlite_"):
        return True
    if lowered.startswith("news_fts"):
        return True
    return False


def copy_turso_tables_into_sqlite(dest_path: str) -> dict[str, Any]:
    """Copia tabelas do Turso para um SQLite novo (quando /dump falha)."""
    remote = _turso_client_for_import()
    dest_dir = os.path.dirname(dest_path) or "."
    os.makedirs(dest_dir, exist_ok=True)
    tmp = dest_path + ".importing"
    if os.path.exists(tmp):
        os.remove(tmp)
    local = sqlite3.connect(tmp)
    copied: dict[str, int] = {}
    try:
        _ = local.execute("PRAGMA foreign_keys=OFF")
        master = remote.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND sql IS NOT NULL ORDER BY name"
        )
        for name, ddl in master.rows:
            table = str(name)
            if _should_skip_import_table(table):
                continue
            create_sql = str(ddl or "").strip()
            if not create_sql:
                continue
            _ = local.execute(create_sql)
            info = remote.execute(f'PRAGMA table_info("{table}")')
            cols = [str(row[1]) for row in info.rows if row and row[1]]
            if not cols:
                copied[table] = 0
                continue
            col_list = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join("?" for _ in cols)
            insert_sql = (
                f'INSERT OR REPLACE INTO "{table}" ({col_list}) VALUES ({placeholders})'
            )
            offset = 0
            total = 0
            while True:
                batch = remote.execute(
                    f'SELECT {col_list} FROM "{table}" LIMIT {_COPY_BATCH_SIZE} OFFSET {offset}'
                )
                rows = list(batch.rows or [])
                if not rows:
                    break
                local.executemany(insert_sql, rows)
                total += len(rows)
                offset += _COPY_BATCH_SIZE
                if len(rows) < _COPY_BATCH_SIZE:
                    break
            copied[table] = total
        try:
            seq = remote.execute("SELECT name, seq FROM sqlite_sequence")
            for seq_name, seq_val in seq.rows:
                _ = local.execute(
                    "INSERT OR REPLACE INTO sqlite_sequence(name, seq) VALUES (?, ?)",
                    (seq_name, seq_val),
                )
        except Exception:
            pass
        local.commit()
    except Exception:
        local.close()
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    finally:
        try:
            remote.close()
        except Exception:
            pass
    local.close()
    _atomic_replace_sqlite(tmp, dest_path)
    return {"copied": copied, "bytes": os.path.getsize(dest_path)}


def activate_local_sqlite() -> None:
    """Passa o processo a usar o SQLite do volume (sem persistir no painel)."""
    os.environ["USE_LOCAL_DB"] = "true"
    reset_db_client()


def import_turso_into_sqlite(
    dest_path: str | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    dest = dest_path or default_local_database_path()
    if (not force) and _sqlite_file_has_news(dest):
        activate_local_sqlite()
        return {
            "ok": True,
            "skipped": True,
            "reason": "sqlite ja tem noticias",
            "path": dest,
            "counts": sqlite_table_counts(dest),
        }

    method = "dump"
    extra: dict[str, Any] = {}
    try:
        sql = fetch_turso_sql_dump()
        extra = apply_sql_dump_to_sqlite(sql, dest)
    except TursoQuotaError:
        raise
    except Exception as dump_exc:
        try:
            extra = copy_turso_tables_into_sqlite(dest)
            method = "copy"
            extra["dump_error"] = type(dump_exc).__name__
        except TursoQuotaError:
            raise
        except Exception as copy_exc:
            raise dump_exc from copy_exc

    if not _sqlite_file_has_news(dest):
        raise RuntimeError("import concluiu sem linhas em news")

    marker = dest + ".migrated"
    try:
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("ok\n")
    except OSError:
        pass

    activate_local_sqlite()
    return {
        "ok": True,
        "skipped": False,
        "method": method,
        "path": dest,
        "counts": sqlite_table_counts(dest),
        **extra,
    }


def reset_db_client() -> None:
    """Fecha e descarta o client global (força reconexão no próximo get_db)."""
    global _client, _schema_ready, _fts_ready
    _schema_ready = False
    _fts_ready = False
    reset_turso_circuit()
    with _client_lock:
        old = _client
        _client = None
    if old is None:
        return
    try:
        close_hard = getattr(old, "close_hard", None)
        if callable(close_hard):
            _ = close_hard()
        else:
            old.close()
    except Exception:
        pass


class PooledClient:
    """Proxy que reutiliza o client remoto sem fechar a cada request."""

    def __init__(self, inner: Any):
        self._inner: Any = inner
        self._swap_lock = threading.Lock()

    def _reconnect(self, stale: Any) -> None:
        """Substitui o client interno uma única vez por falha compartilhada.

        Todas as threads do FastAPI usam o mesmo ``_inner``. Sem o guard de
        identidade, cada thread que falhasse fecharia o client recém-criado
        pelas outras, derrubando requests saudáveis com ``CLIENT_CLOSED``.
        """
        with self._swap_lock:
            if self._inner is not stale:
                return
            fresh = _create_client()
            if not isinstance(fresh, PooledClient):
                raise RuntimeError("Reconexão do Turso retornou client não pooled.")
            self._inner = fresh._inner
        try:
            stale.close()
        except Exception:
            pass

    def execute(
        self,
        sql: str,
        args: list[Any] | None = None,
        *,
        max_attempts: int | None = None,
    ) -> QueryResult:
        # Defaults curtos: páginas de artigo fazem várias queries; backoff longo
        # (ex.: 1.5+3+6s × N queries) vira timeout de request mesmo com fail-soft.
        # Enrichment opcional deve passar max_attempts=1.
        _turso_circuit.before_execute()
        if max_attempts is not None:
            attempts = max(1, int(max_attempts))
        else:
            attempts = max(1, int(os.getenv("TURSO_EXECUTE_RETRIES", "3")))
        delay = float(os.getenv("TURSO_RETRY_BASE_SEC", "0.8"))
        last_exc: BaseException | None = None
        for attempt in range(1, attempts + 1):
            inner = self._inner
            try:
                if args is None:
                    result = _as_query_result(inner.execute(sql))
                else:
                    result = _as_query_result(inner.execute(sql, args))
                _turso_circuit.success()
                return result
            except TursoQuotaError as exc:
                _turso_circuit.trip_open(exc)
                print(
                    "   [db] Turso BLOCKED: leituras recusadas (cota/plano). "
                    "Verifique o dashboard Turso — retry não resolve.",
                    flush=True,
                )
                raise DatabaseUnavailableError(
                    "Turso recusou leituras (cota/plano)."
                ) from exc
            except DatabaseUnavailableError:
                raise
            except Exception as exc:
                last_exc = exc
                if _is_quota_block(exc):
                    _turso_circuit.trip_open(exc)
                    print(
                        "   [db] Turso BLOCKED: leituras recusadas (cota/plano). "
                        "Verifique o dashboard Turso — retry não resolve.",
                        flush=True,
                    )
                    raise DatabaseUnavailableError(
                        "Turso recusou leituras (cota/plano)."
                    ) from exc
                transient = _is_transient_db_error(exc)
                if not transient or attempt >= attempts:
                    if transient:
                        _turso_circuit.failure(exc)
                        raise DatabaseUnavailableError(
                            "Turso indisponível. Tente de novo em instantes."
                        ) from exc
                    raise
                if self._inner is not inner:
                    # Outra thread já trocou o client — repete direto no novo.
                    continue
                wait = delay * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
                print(
                    f"   [db] Turso instável ({type(exc).__name__}): "
                    + f"retry {attempt}/{attempts} em {wait:.1f}s…",
                    flush=True,
                )
                time.sleep(wait)
                self._reconnect(inner)
        assert last_exc is not None
        _turso_circuit.failure(last_exc)
        raise DatabaseUnavailableError(
            "Turso indisponível. Tente de novo em instantes."
        ) from last_exc

    def close(self) -> None:
        pass

    def close_hard(self) -> None:
        try:
            self._inner.close()
        except Exception:
            pass


def _create_client() -> LocalDbClient | PooledClient:
    if _use_local_db():
        path = default_local_database_path()
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
        raise DatabaseConfigError(
            "Banco nao configurado. Na Railway, use USE_LOCAL_DB=true "
            "com volume (news.db) ou defina TURSO_* so para o import."
        )

    return PooledClient(TursoPipelineClient(url, token))


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


def ensure_schema(client: DbClient, *, force: bool = False) -> None:
    global _schema_ready
    if _schema_ready and not force:
        return

    with _schema_lock:
        if _schema_ready and not force:
            return

        try:
            _ = client.execute("""
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
                ("home_priority", "INTEGER"),
                ("titulo_en", "TEXT"),
                ("resumo_en", "TEXT"),
                ("titulo_ja", "TEXT"),
                ("resumo_ja", "TEXT"),
                ("author_id", "INTEGER"),
                ("content_origin", "TEXT"),
                ("moderation_status", "TEXT"),
                ("boost_until", "TEXT"),
            ]:
                try:
                    _ = client.execute(f"ALTER TABLE news ADD COLUMN {col} {col_type}")
                except Exception:
                    pass

            try:
                _ = client.execute("""
                    UPDATE news
                    SET created_at = published_at
                    WHERE (created_at IS NULL OR created_at = '')
                      AND published_at IS NOT NULL AND published_at != ''
                """)
            except Exception as exc:
                print(f"Aviso: backfill created_at: {exc}", flush=True)

            _ = client.execute("""
                CREATE TABLE IF NOT EXISTS newsletter_subscribers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            _ = client.execute("""
                CREATE TABLE IF NOT EXISTS newsletter_alert_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id INTEGER NOT NULL UNIQUE,
                    sent_at TEXT NOT NULL
                )
            """)

            _ = client.execute("""
                CREATE TABLE IF NOT EXISTS macro_watch_state (
                    key TEXT PRIMARY KEY NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            _ = client.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT,
                    google_id TEXT,
                    avatar_url TEXT,
                    created_at TEXT NOT NULL,
                    consent_at TEXT,
                    email_verified INTEGER NOT NULL DEFAULT 0,
                    email_verify_token TEXT,
                    email_verify_sent_at TEXT
                )
            """)
            for col, col_type in (
                ("google_id", "TEXT"),
                ("avatar_url", "TEXT"),
                ("consent_at", "TEXT"),
                ("password_hash", "TEXT"),
                # DEFAULT 1 no ALTER: contas já existentes ficam verificadas (grandfather).
                ("email_verified", "INTEGER DEFAULT 1"),
                ("email_verify_token", "TEXT"),
                ("email_verify_sent_at", "TEXT"),
                ("role", "TEXT"),
                ("pix_key", "TEXT"),
            ):
                try:
                    _ = client.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                except Exception:
                    pass

            _ = client.execute("""
                CREATE TABLE IF NOT EXISTS columnist_applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    pitch TEXT NOT NULL,
                    status TEXT NOT NULL,
                    admin_note TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                )
            """)

            _ = client.execute("""
                CREATE TABLE IF NOT EXISTS page_views (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    viewer_hash TEXT NOT NULL,
                    viewer_user_id INTEGER,
                    day TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(news_id, viewer_hash, day)
                )
            """)

            _ = client.execute("""
                CREATE TABLE IF NOT EXISTS wallet_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    amount_brl REAL NOT NULL,
                    news_id INTEGER,
                    meta_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            _ = client.execute("""
                CREATE TABLE IF NOT EXISTS payout_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount_brl REAL NOT NULL,
                    pix_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    admin_note TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                )
            """)

            _ = client.execute("""
                CREATE TABLE IF NOT EXISTS boost_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    news_id INTEGER NOT NULL,
                    plan_id TEXT NOT NULL,
                    amount_brl REAL NOT NULL,
                    status TEXT NOT NULL,
                    external_ref TEXT UNIQUE,
                    mp_payment_id TEXT,
                    boost_until TEXT,
                    created_at TEXT NOT NULL,
                    paid_at TEXT
                )
            """)

            _ = client.execute("""
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    parent_id INTEGER,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    consent_at TEXT,
                    ip_hash TEXT,
                    geo_country TEXT,
                    upvotes INTEGER DEFAULT 0
                )
            """)

            _ = client.execute("""
                CREATE TABLE IF NOT EXISTS comment_votes (
                    comment_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (comment_id, user_id)
                )
            """)

            # Índices para listagens / filtros da home, relacionados e dedupe.
            for sql in (
                "CREATE INDEX IF NOT EXISTS idx_news_id_desc ON news(id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_news_tag_id ON news(tag, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_news_link ON news(link)",
                "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
                "CREATE INDEX IF NOT EXISTS idx_users_google ON users(google_id)",
                "CREATE INDEX IF NOT EXISTS idx_users_verify_token ON users(email_verify_token)",
                "CREATE INDEX IF NOT EXISTS idx_comments_news ON comments(news_id, id)",
                "CREATE INDEX IF NOT EXISTS idx_news_author ON news(author_id, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_news_moderation ON news(moderation_status, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_page_views_day ON page_views(day, author_id)",
                "CREATE INDEX IF NOT EXISTS idx_wallet_user ON wallet_ledger(user_id, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_boost_ref ON boost_orders(external_ref)",
            ):
                try:
                    _ = client.execute(sql)
                except Exception:
                    pass

            try:
                _ensure_fts(client)
            except Exception as exc:
                print(f"Aviso: FTS no schema: {exc}", flush=True)
        except Exception as exc:
            # Não deixar cada /noticia reexecutar migração completa no Turso.
            print(f"Aviso: ensure_schema parcial: {exc}", flush=True)
        finally:
            _schema_ready = True


def _ensure_fts(client: DbClient) -> None:
    """Índice full-text para busca (FTS5).

    No Turso/libSQL HTTP, triggers FTS quebram o protocolo do client
    (KeyError: 'result' no UPDATE/INSERT). Por isso triggers só no SQLite local;
    rebuild completo no remoto fica para ``sync_news_fts`` (ops), não no hot path.
    """
    global _fts_ready
    try:
        _ = client.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
                titulo,
                resumo,
                content='news',
                content_rowid='id',
                tokenize='unicode61'
            )
            """
        )

        # Remove triggers legados que quebram o client HTTP do Turso.
        for trigger in ("news_fts_ai", "news_fts_ad", "news_fts_au"):
            try:
                _ = client.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            except Exception:
                pass

        if _use_local_db():
            for sql in (
                """
                CREATE TRIGGER IF NOT EXISTS news_fts_ai AFTER INSERT ON news BEGIN
                    INSERT INTO news_fts(rowid, titulo, resumo)
                    VALUES (new.id, new.titulo, new.resumo);
                END
                """,
                """
                CREATE TRIGGER IF NOT EXISTS news_fts_ad AFTER DELETE ON news BEGIN
                    INSERT INTO news_fts(news_fts, rowid, titulo, resumo)
                    VALUES ('delete', old.id, old.titulo, old.resumo);
                END
                """,
                """
                CREATE TRIGGER IF NOT EXISTS news_fts_au AFTER UPDATE OF titulo, resumo ON news BEGIN
                    INSERT INTO news_fts(news_fts, rowid, titulo, resumo)
                    VALUES ('delete', old.id, old.titulo, old.resumo);
                    INSERT INTO news_fts(rowid, titulo, resumo)
                    VALUES (new.id, new.titulo, new.resumo);
                END
                """,
            ):
                _ = client.execute(sql)

            count = client.execute("SELECT COUNT(*) FROM news_fts")
            fts_rows = int(count.rows[0][0]) if count.rows else 0
            news_count = client.execute("SELECT COUNT(*) FROM news")
            news_rows = int(news_count.rows[0][0]) if news_count.rows else 0
            if news_rows and fts_rows < max(1, int(news_rows * 0.9)):
                _ = client.execute("INSERT INTO news_fts(news_fts) VALUES('rebuild')")
        _fts_ready = True
    except Exception:
        _fts_ready = False


def sync_news_fts(client: DbClient | None = None) -> dict[str, Any]:
    """Reconstrói o índice FTS quando não há triggers (Turso)."""
    if _use_local_db():
        return {"ok": True, "skipped": "local_db"}
    db = client or get_db()
    try:
        _ = db.execute("INSERT INTO news_fts(news_fts) VALUES('rebuild')")
        return {"ok": True, "rebuilt": True}
    except Exception as exc:
        print(f"Aviso: sync_news_fts: {exc}", flush=True)
        return {"ok": False, "error": str(exc)[:180]}


def fts_available() -> bool:
    if not _schema_ready:
        return False
    return _fts_ready


def _fold_fts_token(token: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (token or "").lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


# Sinônimos leves (token dobrado → extras). Não explodir o MATCH.
_FTS_SYNONYMS: dict[str, tuple[str, ...]] = {
    "selic": ("copom", "juros"),
    "copom": ("selic",),
    "ipca": ("inflacao",),
    "inflacao": ("ipca",),
    "dolar": ("cambio", "usd"),
    "cambio": ("dolar",),
    "bitcoin": ("btc", "cripto"),
    "btc": ("bitcoin",),
    "cripto": ("bitcoin", "btc"),
}


def build_fts_match_query(q: str) -> str | None:
    """Monta expressão FTS5 segura (prefixos + sinônimos de mercado)."""
    tokens = re.findall(r"[0-9A-Za-zÀ-ÿ]{2,}", (q or "").strip(), flags=re.UNICODE)
    if not tokens:
        return None
    cleaned: list[str] = []
    seen: set[str] = set()

    def _add_term(raw: str) -> None:
        safe = re.sub(r"[^\w]", "", raw, flags=re.UNICODE)
        if len(safe) < 2:
            return
        key = safe.lower()
        if key in seen:
            return
        seen.add(key)
        cleaned.append(f'"{safe}"*')

    for token in tokens[:8]:
        _add_term(token)
        folded = _fold_fts_token(token)
        if folded:
            _add_term(folded)
            for extra in _FTS_SYNONYMS.get(folded, ()):
                if len(cleaned) >= 16:
                    break
                _add_term(extra)
        if len(cleaned) >= 16:
            break
    if not cleaned:
        return None
    return " OR ".join(cleaned)


def upsert_news_fts(client: DbClient | None, news_id: int, titulo: object, resumo: object) -> bool:
    """Atualiza uma linha no índice FTS (Turso sem triggers). No-op no SQLite local."""
    if _use_local_db() or not news_id:
        return True
    if not fts_available():
        return False
    db = client or get_db()
    title = str(titulo or "")
    summary = str(resumo or "")
    try:
        try:
            _ = db.execute(
                "INSERT INTO news_fts(news_fts, rowid, titulo, resumo) VALUES('delete', ?, ?, ?)",
                [int(news_id), title, summary],
            )
        except Exception:
            pass
        _ = db.execute(
            "INSERT INTO news_fts(rowid, titulo, resumo) VALUES (?, ?, ?)",
            [int(news_id), title, summary],
        )
        return True
    except Exception as exc:
        print(f"Aviso: upsert news_fts id={news_id}: {exc}", flush=True)
        return False


def index_news_by_id(client: DbClient | None, news_id: int) -> bool:
    db = client or get_db()
    try:
        result = db.execute(
            "SELECT id, titulo, resumo FROM news WHERE id = ? LIMIT 1",
            [int(news_id)],
        )
    except Exception:
        return False
    if not result.rows:
        return False
    row = result.rows[0]
    return upsert_news_fts(db, int(row[0]), row[1], row[2])


def index_news_by_link(client: DbClient | None, link: str) -> bool:
    href = (link or "").strip()
    if not href:
        return False
    db = client or get_db()
    try:
        result = db.execute(
            "SELECT id, titulo, resumo FROM news WHERE link = ? LIMIT 1",
            [href],
        )
    except Exception:
        return False
    if not result.rows:
        return False
    row = result.rows[0]
    return upsert_news_fts(db, int(row[0]), row[1], row[2])


def existing_news_links(links: list[str]) -> set[str]:
    """Retorna o subconjunto de links já publicados (1 query por lote)."""
    cleaned = [str(link).strip() for link in links if link and str(link).strip()]
    if not cleaned:
        return set()
    client = get_db()
    found: set[str] = set()
    for i in range(0, len(cleaned), _LINK_IN_CHUNK):
        chunk = cleaned[i : i + _LINK_IN_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        try:
            result = client.execute(
                f"SELECT link FROM news WHERE link IN ({placeholders})",
                chunk,
            )
            found.update(str(row[0]) for row in result.rows if row and row[0])
        except Exception:
            continue
    return found


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
        recent_counts: dict[str, int] = {}
        selic_hook_count = 0
        for row in rows:
            titulo, tag, sentimento, impacto = row[0], row[1], row[2] or "Neutro", row[3] or ""
            titulo_l = (titulo or "").lower()
            if any(k in titulo_l for k in ("selic", "copom", "juros", "taxa de juros")):
                selic_hook_count += 1
            lines.append(f"- [{tag}] {titulo} (sentimento: {sentimento})")
            recent_counts[sentimento] = recent_counts.get(sentimento, 0) + 1

        # Usa o mesmo lote já carregado — evita 2ª round-trip ao Turso.
        panorama = ", ".join(f"{s}: {c}" for s, c in recent_counts.items())
        out = (
            "NOTÍCIAS RECENTES JÁ PUBLICADAS NO PORTAL (use para contextualizar tendências, NÃO repita):\n"
            + "\n".join(lines)
            + f"\n\nPANORAMA DE SENTIMENTO RECENTE: {panorama}"
        )
        if selic_hook_count >= 3:
            out += (
                "\n\nALERTA ANTI-REPETIÇÃO: várias matérias recentes já abriram com Selic/juros. "
                "Nesta análise, só use Selic se for CENTRAL ao fato; prefira ângulo setorial, "
                "comportamental, fiscal ou internacional."
            )
        return out
    except Exception as e:
        return f"Histórico do portal indisponível: {e}"


def client_sentiment_summary(tag_hint=None):
    cache_key = tag_hint or "__all__"
    now = time.time()
    with _sentiment_cache_lock:
        cached = _sentiment_cache.get(cache_key)
        if cached and now < cached[0]:
            return cached[1]

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
            summary = "sem histórico suficiente"
        else:
            parts = [f"{s or 'Neutro'}: {c}" for s, c in rows]
            summary = ", ".join(parts)

        with _sentiment_cache_lock:
            _sentiment_cache[cache_key] = (now + _SENTIMENT_CACHE_TTL, summary)
        return summary
    except Exception:
        return "indisponível"


def invalidate_sentiment_cache() -> None:
    with _sentiment_cache_lock:
        _sentiment_cache.clear()
