"""Testes da migracao Turso → SQLite no volume (sem tocar producao)."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import db


def test_apply_sql_dump_preserves_news_ids(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    dest = str(tmp_path / "news.db")
    dump = """
    PRAGMA foreign_keys=OFF;
    BEGIN TRANSACTION;
    CREATE TABLE news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT,
        resumo TEXT
    );
    INSERT INTO news(id, titulo, resumo) VALUES(15475, 'Selic', 'texto');
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL
    );
    INSERT INTO users(id, name, email, created_at)
    VALUES(1, 'QA', 'qa@example.com', '2026-08-18');
    CREATE VIRTUAL TABLE news_fts USING fts5(titulo, resumo, content='news', content_rowid='id');
    INSERT INTO news_fts(rowid, titulo, resumo) VALUES(15475, 'Selic', 'texto');
    COMMIT;
    """
    result = db.apply_sql_dump_to_sqlite(dump, dest)
    assert result["bytes"] > 0
    conn = sqlite3.connect(dest)
    row = conn.execute("SELECT id, titulo FROM news").fetchone()
    assert row == (15475, "Selic")
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    assert users[0] == 1
    fts = conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'news_fts%'"
    ).fetchall()
    conn.close()
    assert fts == []
    counts = db.sqlite_table_counts(dest)
    assert counts["news"] == 1
    assert counts["users"] == 1


def test_restore_sqlite_bytes(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "src.db"
    conn = sqlite3.connect(src)
    conn.execute("CREATE TABLE news (id INTEGER PRIMARY KEY, titulo TEXT)")
    conn.execute("INSERT INTO news(id, titulo) VALUES (9, 'ok')")
    conn.commit()
    conn.close()
    data = src.read_bytes()
    dest = str(tmp_path / "out.db")
    result = db.restore_sqlite_payload(data, dest)
    assert result["format"] == "sqlite"
    assert db._sqlite_file_has_news(dest)


def test_use_local_db_autodetect_only_on_volume(tmp_path: Path, monkeypatch) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    dest = tmp_path / "news.db"
    conn = sqlite3.connect(dest)
    conn.execute("CREATE TABLE news (id INTEGER PRIMARY KEY, titulo TEXT)")
    conn.execute("INSERT INTO news(id, titulo) VALUES (1, 'x')")
    conn.commit()
    conn.close()
    monkeypatch.delenv("USE_LOCAL_DB", raising=False)
    monkeypatch.delenv("USE_TURSO", raising=False)
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH", raising=False)
    monkeypatch.setenv("LOCAL_DATABASE_PATH", str(dest))
    assert db._use_local_db() is False

    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    monkeypatch.delenv("LOCAL_DATABASE_PATH", raising=False)
    assert db._use_local_db() is True

    monkeypatch.setenv("USE_LOCAL_DB", "0")
    assert db._use_local_db() is False


def test_import_skips_when_sqlite_has_news(tmp_path: Path, monkeypatch) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    dest = str(tmp_path / "news.db")
    conn = sqlite3.connect(dest)
    conn.execute("CREATE TABLE news (id INTEGER PRIMARY KEY, titulo TEXT)")
    conn.execute("INSERT INTO news VALUES (1, 'ja existe')")
    conn.commit()
    conn.close()
    monkeypatch.setenv("USE_LOCAL_DB", "0")
    with patch.object(db, "fetch_turso_sql_dump", side_effect=AssertionError("nao deve dump")):
        result = db.import_turso_into_sqlite(dest, force=False)
    assert result["skipped"] is True
    assert result["counts"]["news"] == 1
    assert os.environ.get("USE_LOCAL_DB") == "true"


def test_migrate_routes_require_robo_token(tmp_path: Path, monkeypatch) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("USE_LOCAL_DB", "1")
    monkeypatch.setenv("LOCAL_DATABASE_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("ROBO_TOKEN", "test-robo-token-local")
    db.reset_db_client()
    from fastapi.testclient import TestClient

    import main as appmod

    with TestClient(appmod.app) as client:
        r = client.get("/api/import-from-turso")
        assert r.status_code == 401
        r = client.get("/api/import-from-turso", params={"token": "errado"})
        assert r.status_code == 401
        r = client.post("/api/restore-sqlite")
        assert r.status_code == 401
        r = client.post("/api/restore-sqlite", params={"token": "errado"})
        assert r.status_code == 401


if __name__ == "__main__":
    import shutil
    from pathlib import Path as _Path

    root = _Path(".tmp-migrate-test")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir()
    try:
        test_apply_sql_dump_preserves_news_ids(root / "dump")
        test_restore_sqlite_bytes(root / "bytes")

        class _Mp:
            def setenv(self, k, v):
                os.environ[k] = v

            def delenv(self, k, raising=False):
                os.environ.pop(k, None)

        test_use_local_db_autodetect_only_on_volume(root / "auto", _Mp())
        test_import_skips_when_sqlite_has_news(root / "skip", _Mp())
        test_migrate_routes_require_robo_token(root / "auth", _Mp())
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("PASS: test_sqlite_migrate")
