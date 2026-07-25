"""Testes do pool de conexão Turso (reconexão concorrente)."""
from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch

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


def test_client_closed_is_transient():
    assert db._is_transient_db_error(RuntimeError("CLIENT_CLOSED: Client is closed"))
    assert db._is_transient_db_error(KeyError("result"))
    assert not db._is_transient_db_error(ValueError("syntax error near SELECT"))


def test_reconnect_swaps_inner_only_once():
    """Regressao: cada thread fechava o client novo das outras (CLIENT_CLOSED)."""
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


if __name__ == "__main__":
    test_client_closed_is_transient()
    test_reconnect_swaps_inner_only_once()
    test_concurrent_execute_survives_reconnect()
    test_execute_reraises_non_transient()
    print("PASS: test_db_pool")
