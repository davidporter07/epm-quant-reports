"""PR F commit 1: users.db must run WAL journal mode with busy_timeout.

Verifies that _get_conn() mirrors the research_store._connect() pattern so
concurrent auth writes don't surface OperationalError("database is locked").
"""
import sqlite3
import threading
import time

import pytest

import services.auth_service as auth


def test_journal_mode_is_wal(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "users.db")
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    conn = auth._get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal", f"expected wal, got {mode!r}"


def test_busy_timeout_is_set(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "users.db")
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    conn = auth._get_conn()
    timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    conn.close()
    assert timeout_ms >= 5000, f"expected >=5000 ms, got {timeout_ms}"


def test_foreign_keys_are_on(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "users.db")
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    conn = auth._get_conn()
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.close()
    assert fk == 1


def test_concurrent_writer_succeeds_within_busy_timeout(tmp_path, monkeypatch):
    """Smoke: conn A holds BEGIN IMMEDIATE; conn B should not raise within busy_timeout."""
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)

    # Bootstrap schema so a writer has a table to touch.
    with auth._get_conn() as setup:
        setup.execute("CREATE TABLE IF NOT EXISTS t (v INTEGER)")

    errors = []

    def _writer_b():
        try:
            # Give writer A time to hold the lock.
            time.sleep(0.05)
            conn = auth._get_conn()
            conn.execute("INSERT INTO t VALUES (2)")
            conn.commit()
            conn.close()
        except Exception as exc:
            errors.append(exc)

    # Writer A: hold an exclusive write lock for 200ms.
    conn_a = auth._get_conn()
    conn_a.execute("BEGIN IMMEDIATE")
    conn_a.execute("INSERT INTO t VALUES (1)")

    thread = threading.Thread(target=_writer_b)
    thread.start()
    time.sleep(0.2)
    conn_a.commit()
    conn_a.close()
    thread.join(timeout=6)

    assert not errors, f"concurrent write raised: {errors}"
