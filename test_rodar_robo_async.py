"""GET /api/rodar-robo em modo assincrono (cron-job.org recebe 202)."""
from __future__ import annotations

import os
import threading
import time
from unittest.mock import patch

os.environ.setdefault("ROBO_TOKEN", "test-robo-token-local")

from fastapi.testclient import TestClient

import main


def test_robo_runs_async_flag(monkeypatch) -> None:
    monkeypatch.setenv("ROBO_ASYNC", "1")
    assert main._robo_runs_async() is True
    monkeypatch.setenv("ROBO_ASYNC", "true")
    assert main._robo_runs_async() is True
    monkeypatch.setenv("ROBO_ASYNC", "0")
    assert main._robo_runs_async() is False
    monkeypatch.setenv("ROBO_ASYNC", "false")
    assert main._robo_runs_async() is False


def test_rodar_robo_async_returns_202_and_skips_overlap(monkeypatch) -> None:
    monkeypatch.setenv("ROBO_TOKEN", "test-robo-token-local")
    monkeypatch.setenv("ROBO_ASYNC", "1")
    started = threading.Event()
    release = threading.Event()

    def _slow() -> dict:
        started.set()
        release.wait(timeout=5)
        return {"status": "Sucesso"}

    auth = {"Authorization": "Bearer test-robo-token-local"}
    with patch.object(main, "_execute_robot_pipeline", side_effect=_slow):
        client = TestClient(main.app)
        try:
            first = client.get("/api/rodar-robo", headers=auth)
            assert first.status_code == 202
            assert first.json()["status"] == "Aceito"
            second = client.get("/api/rodar-robo", headers=auth)
            assert second.status_code == 202
            assert second.json()["status"] == "Ignorado"
            assert started.wait(timeout=2)
        finally:
            release.set()
            deadline = time.time() + 2
            while main._robo_job_lock.locked() and time.time() < deadline:
                time.sleep(0.02)
        assert not main._robo_job_lock.locked()


def test_rodar_robo_async_still_requires_token(monkeypatch) -> None:
    monkeypatch.setenv("ROBO_TOKEN", "test-robo-token-local")
    monkeypatch.setenv("ROBO_ASYNC", "1")
    client = TestClient(main.app)
    r = client.get("/api/rodar-robo")
    assert r.status_code == 401
    r = client.get("/api/rodar-robo", params={"token": "errado"})
    assert r.status_code == 401
