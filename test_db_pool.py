"""Testes do pool de conexão Turso (reconexão concorrente)."""
from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import db


class FakeInner:
    """Client sync falso: falha as N primeiras chamadas e recusa uso apos close()."""

    def __init__(self, fail_times: int = 0):
        self.closed = False
        self._fail_times = fail_times
        self._lock = threading.Lock()

    def execute(self, sql: str, args: list[Any] | None = None):
        if self.closed:
            raise RuntimeError("CLIENT_CLOSED: Client is closed")
        with self._lock:
            if self._fail_times > 0:
                self._fail_times -= 1
                should_fail = True
            else:
                should_fail = False
        if should_fail:
            raise KeyError("result")
        return db.QueryResult([(1,)])

    def close(self) -> None:
        self.closed = True


def setup_function() -> None:
    db.reset_turso_circuit()


def test_client_closed_is_transient():
    db.reset_turso_circuit()
    assert db._is_transient_db_error(RuntimeError("CLIENT_CLOSED: Client is closed"))
    assert db._is_transient_db_error(KeyError("result"))
    assert db._is_transient_db_error(db.TursoProtocolError("STREAM_EXPIRED"))
    assert not db._is_transient_db_error(ValueError("syntax error near SELECT"))
    assert not db._is_transient_db_error(ValueError("no such column: titulo_en"))
    assert not db._is_transient_db_error(db.DatabaseUnavailableError("circuito"))


def test_reconnect_swaps_inner_only_once():
    """Regressao: cada thread fechava o client novo das outras (CLIENT_CLOSED)."""
    db.reset_turso_circuit()
    stale = FakeInner()
    pooled = db.PooledClient(stale)
    created: list[FakeInner] = []

    def fake_create():
        fresh = FakeInner()
        created.append(fresh)
        return db.PooledClient(fresh)

    with patch.object(db, "_create_client", fake_create):
        threads = [threading.Thread(target=pooled._reconnect, args=(stale,)) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(created) == 1, f"reconectou {len(created)}x (esperado 1)"
    assert stale.closed is True
    assert created[0].closed is False
    assert pooled._inner is created[0]


def test_concurrent_execute_survives_reconnect():
    """Threads paralelas nao podem receber CLIENT_CLOSED durante a troca do pool."""
    db.reset_turso_circuit()
    stale = FakeInner(fail_times=3)
    pooled = db.PooledClient(stale)

    def fake_create():
        return db.PooledClient(FakeInner())

    errors: list[BaseException] = []

    def worker():
        try:
            result = pooled.execute("SELECT 1")
            assert result.rows
        except BaseException as exc:
            errors.append(exc)

    with patch.dict("os.environ", {"TURSO_RETRY_BASE_SEC": "0.01"}, clear=False):
        with patch.object(db, "_create_client", fake_create):
            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

    assert not errors, f"falhas inesperadas: {errors}"


def test_execute_reraises_non_transient():
    db.reset_turso_circuit()

    class Boom(FakeInner):
        def execute(self, sql: str, args: list[Any] | None = None):
            raise ValueError("no such column: foo")

    pooled = db.PooledClient(Boom())
    try:
        pooled.execute("SELECT foo FROM news")
    except ValueError:
        pass
    else:
        raise AssertionError("erro de SQL nao deveria virar retry")


def test_exhausted_keyerror_becomes_unavailable():
    db.reset_turso_circuit()
    pooled = db.PooledClient(FakeInner(fail_times=99))
    with patch.dict(
        "os.environ",
        {"TURSO_RETRY_BASE_SEC": "0.01", "TURSO_EXECUTE_RETRIES": "2", "TURSO_CIRCUIT_FAILURES": "99"},
        clear=False,
    ):
        with patch.object(db, "_create_client", lambda: db.PooledClient(FakeInner(fail_times=99))):
            try:
                pooled.execute("SELECT 1")
            except db.DatabaseUnavailableError:
                return
    raise AssertionError("KeyError persistente deveria virar 503 DatabaseUnavailableError")


def test_circuit_fail_fast_after_threshold():
    db.reset_turso_circuit()
    pooled = db.PooledClient(FakeInner(fail_times=99))
    with patch.dict(
        "os.environ",
        {
            "TURSO_RETRY_BASE_SEC": "0.01",
            "TURSO_EXECUTE_RETRIES": "1",
            "TURSO_CIRCUIT_FAILURES": "2",
            "TURSO_CIRCUIT_COOLDOWN_SEC": "30",
        },
        clear=False,
    ):
        with patch.object(db, "_create_client", lambda: db.PooledClient(FakeInner(fail_times=99))):
            for _ in range(2):
                try:
                    pooled.execute("SELECT 1")
                except db.DatabaseUnavailableError:
                    pass
            try:
                pooled.execute("SELECT 1")
            except db.DatabaseUnavailableError as exc:
                assert "circuito" in str(exc).lower() or "indispon" in str(exc).lower()
                return
    raise AssertionError("circuito deveria falhar rápido na 3ª chamada")


def test_pipeline_parses_execute_result():
    client = db.TursoPipelineClient("https://example.turso.io", "token-teste")
    payload = {
        "results": [
            {
                "type": "ok",
                "response": {
                    "type": "execute",
                    "result": {
                        "cols": [{"name": "id"}],
                        "rows": [[{"type": "integer", "value": "7"}]],
                    },
                },
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = payload
    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.execute("SELECT id FROM news WHERE id = ?", [7])
    assert result.rows == [(7,)]


def test_pipeline_error_body_is_protocol_error():
    client = db.TursoPipelineClient("https://example.turso.io", "token-teste")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "results": [{"type": "error", "error": {"message": "STREAM_EXPIRED", "code": "STREAM_EXPIRED"}}]
    }
    with patch.object(client._session, "post", return_value=mock_resp):
        try:
            client.execute("SELECT 1")
        except db.TursoProtocolError as exc:
            assert "STREAM_EXPIRED" in str(exc)
            return
    raise AssertionError("erro de pipeline deveria virar TursoProtocolError")


if __name__ == "__main__":
    test_client_closed_is_transient()
    test_reconnect_swaps_inner_only_once()
    test_concurrent_execute_survives_reconnect()
    test_execute_reraises_non_transient()
    test_exhausted_keyerror_becomes_unavailable()
    test_circuit_fail_fast_after_threshold()
    test_pipeline_parses_execute_result()
    test_pipeline_error_body_is_protocol_error()
    print("PASS: test_db_pool")
