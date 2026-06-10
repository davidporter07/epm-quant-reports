"""PR2: /api/health returns aggregated checks and leaks no host/secret.
PR B: last_run, db, ollama.models, watchdog, reasons keys (all additive).
"""
import json
import types

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

try:
    from fastapi.testclient import TestClient
    from app import app, _prev_market_day
except Exception as exc:  # pragma: no cover - env-dependent
    pytest.skip(f"web app deps unavailable: {exc}", allow_module_level=True)

_MOCK_OLLAMA_OK = types.SimpleNamespace(
    ok=True,
    json=lambda: {"models": [{"name": "qwen3.5:4b"}, {"name": "deepseek-r1:8b"}]},
)
_MOCK_OLLAMA_DOWN = types.SimpleNamespace(ok=False, json=lambda: {})


def _client_with_mocks(monkeypatch, ollama_resp=None, watchdog_enabled="0"):
    """Return a TestClient with Ollama and watchdog mocked out."""
    monkeypatch.setenv("WATCHDOG_ENABLED", watchdog_enabled)
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: ollama_resp or _MOCK_OLLAMA_OK)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Legacy shape regression — existing keys must keep exact form
# ---------------------------------------------------------------------------

def test_health_returns_aggregated_checks(monkeypatch):
    client = _client_with_mocks(monkeypatch)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    checks = body["checks"]
    for key in ("commentary", "data_files", "deep_worker", "ollama"):
        assert key in checks
    # Legacy key still present (added models alongside it — not a replacement)
    assert "reachable" in checks["ollama"]
    # New top-level keys
    assert "reasons" in body
    assert isinstance(body["reasons"], list)


def test_health_does_not_leak_ollama_host(monkeypatch):
    client = _client_with_mocks(monkeypatch)
    text = client.get("/api/health").text
    assert "11434" not in text       # no ollama port
    assert "192.168" not in text     # no LAN IP


def test_health_commentary_check_is_self_contained(monkeypatch):
    # Regression: /api/health must not import check_site_freshness
    client = _client_with_mocks(monkeypatch)
    commentary = client.get("/api/health").json()["checks"]["commentary"]
    assert "error" not in commentary
    assert {"present", "report_date", "market_open", "fresh"} <= set(commentary.keys())


def test_health_source_does_not_import_laptop_only_module():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    assert "from check_site_freshness import" not in src


# ---------------------------------------------------------------------------
# last_run check
# ---------------------------------------------------------------------------

def test_last_run_missing_is_info_only(monkeypatch, tmp_path):
    monkeypatch.setattr("app.DATA_DIR", tmp_path)
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    lr = body["checks"]["last_run"]
    assert lr["present"] is False
    # Missing file must NOT mark overall degraded / add to reasons
    assert "last_run_stale" not in body["reasons"]
    assert not any("last_run" in r for r in body["reasons"])


def test_last_run_ok_and_fresh_not_degraded(monkeypatch, tmp_path):
    from datetime import datetime, timezone, date, timedelta
    today = date.today()
    ts = datetime.now(timezone.utc).isoformat()
    status = {"ts": ts, "stage": "ok", "ok": True, "detail": "fresh"}
    (tmp_path / "run_daily_status.json").write_text(json.dumps(status), encoding="utf-8")
    monkeypatch.setattr("app.DATA_DIR", tmp_path)
    # Also write a minimal latest_commentary.json so commentary check passes
    (tmp_path / "latest_commentary.json").write_text(
        json.dumps({"report_date": today.isoformat()}), encoding="utf-8"
    )
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    lr = body["checks"]["last_run"]
    assert lr["present"] is True
    assert lr["ok"] is True
    assert not any("last_run" in r for r in body["reasons"])


def test_last_run_ok_false_marks_degraded(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    status = {"ts": ts, "stage": "send_email", "ok": False, "detail": "smtp error"}
    (tmp_path / "run_daily_status.json").write_text(json.dumps(status), encoding="utf-8")
    monkeypatch.setattr("app.DATA_DIR", tmp_path)
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    assert body["checks"]["last_run"]["ok"] is False
    assert "last_run_failed:send_email" in body["reasons"]


def test_last_run_stale_fri_to_mon_not_degraded(monkeypatch, tmp_path):
    """A Friday run seen on Monday should NOT be stale (previous market day = Friday)."""
    from datetime import datetime, timezone, date, timedelta
    # Find the most recent Monday (or use a fixed Monday)
    today = date(2026, 6, 8)  # known Monday
    friday = date(2026, 6, 5)
    ts = datetime(2026, 6, 5, 14, 0, tzinfo=timezone.utc).isoformat()
    status = {"ts": ts, "stage": "ok", "ok": True, "detail": "fresh"}
    (tmp_path / "run_daily_status.json").write_text(json.dumps(status), encoding="utf-8")
    monkeypatch.setattr("app.DATA_DIR", tmp_path)
    # Inject Monday as "today" for the prev_market_day calc
    import app as _app
    monkeypatch.setattr(_app, "_prev_market_day", lambda d, **k: friday)
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    assert "last_run_stale" not in body["reasons"]


def test_last_run_stale_two_days_old_marks_degraded(monkeypatch, tmp_path):
    from datetime import datetime, timezone, date, timedelta
    ts = datetime(2026, 6, 5, 14, 0, tzinfo=timezone.utc).isoformat()
    status = {"ts": ts, "stage": "ok", "ok": True, "detail": "fresh"}
    (tmp_path / "run_daily_status.json").write_text(json.dumps(status), encoding="utf-8")
    monkeypatch.setattr("app.DATA_DIR", tmp_path)
    # Simulate today being Wednesday June 10 → prev market day is Tuesday June 9
    # so Friday June 5 run IS older than Tuesday June 9 → stale
    import app as _app
    monkeypatch.setattr(_app, "_prev_market_day", lambda d, **k: date(2026, 6, 9))
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    assert "last_run_stale" in body["reasons"]


# ---------------------------------------------------------------------------
# db check
# ---------------------------------------------------------------------------

def test_db_readonly_marks_degraded(monkeypatch, tmp_path):
    import sqlite3
    import app as _app
    from services.auth_service import DB_PATH as _orig_db
    # Patch the import inside health() by redirecting auth_service.DB_PATH
    fake_db = tmp_path / "users.db"
    fake_db.write_bytes(b"")  # exists but triggers our mock
    monkeypatch.setattr("services.auth_service.DB_PATH", fake_db)
    monkeypatch.setenv("RESEARCH_DB_PATH", str(tmp_path / "nonexistent_research.db"))

    def _raise_readonly(*a, **k):
        raise sqlite3.OperationalError("attempt to write a readonly database")

    monkeypatch.setattr(sqlite3, "connect", _raise_readonly)
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    assert "db_readonly:users" in body["reasons"]
    assert body["status"] == "degraded"


def test_db_locked_is_not_degraded(monkeypatch, tmp_path):
    import sqlite3
    fake_db = tmp_path / "users.db"
    fake_db.write_bytes(b"")
    monkeypatch.setattr("services.auth_service.DB_PATH", fake_db)
    monkeypatch.setenv("RESEARCH_DB_PATH", str(tmp_path / "nonexistent_research.db"))

    call_count = [0]

    def _raise_locked(*a, **k):
        call_count[0] += 1
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(sqlite3, "connect", _raise_locked)
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    assert not any("db_readonly" in r for r in body["reasons"])
    assert body["checks"]["db"]["users"] == {"writable": True, "busy": True}


# ---------------------------------------------------------------------------
# ollama.models check
# ---------------------------------------------------------------------------

def test_ollama_missing_council_model_marks_degraded(monkeypatch):
    missing_council = types.SimpleNamespace(
        ok=True,
        json=lambda: {"models": [{"name": "qwen3.5:4b"}]},  # chat ok, council missing
    )
    monkeypatch.setenv("COUNCIL_OLLAMA_MODEL", "deepseek-r1:8b")
    client = _client_with_mocks(monkeypatch, ollama_resp=missing_council)
    body = client.get("/api/health").json()
    assert "ollama_model_missing:deepseek-r1:8b" in body["reasons"]
    assert body["status"] == "degraded"
    assert body["checks"]["ollama"]["reachable"] is True  # legacy key still present


def test_ollama_all_models_present_not_degraded(monkeypatch):
    monkeypatch.setenv("COUNCIL_OLLAMA_MODEL", "deepseek-r1:8b")
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    assert not any("ollama_model_missing" in r for r in body["reasons"])
    assert body["checks"]["ollama"]["models"]["chat"] is True
    assert body["checks"]["ollama"]["models"]["council"] is True


# ---------------------------------------------------------------------------
# watchdog check
# ---------------------------------------------------------------------------

def test_watchdog_status_present_in_health(monkeypatch):
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    wdog = body["checks"]["watchdog"]
    assert "alive" in wdog
    assert "last_check_ts" in wdog
    assert "last_alert_date" in wdog


# ---------------------------------------------------------------------------
# _prev_market_day pure helper
# ---------------------------------------------------------------------------

def test_prev_market_day_skips_weekend():
    from datetime import date
    # Monday Jun 8 → prev market day = Friday Jun 5
    result = _prev_market_day(date(2026, 6, 8), _us_holidays=frozenset())
    assert result == date(2026, 6, 5)


def test_prev_market_day_skips_holiday():
    from datetime import date
    memorial_day = date(2026, 5, 25)  # Monday
    result = _prev_market_day(date(2026, 5, 26), _us_holidays={memorial_day})
    assert result == date(2026, 5, 22)  # prev Friday


# ---------------------------------------------------------------------------
# data_freshness check (PR D)
# ---------------------------------------------------------------------------

def _df_report(*, enforce: bool, critical_failing: list, failing: list = None) -> str:
    """Build a minimal data_freshness.json payload string for tests."""
    from datetime import datetime, timezone
    results = []
    for name in (critical_failing or []):
        results.append({"name": name, "critical": True, "ok": False,
                        "detail": f"{name} stale", "status": "stale"})
    for name in (failing or []):
        if name not in (critical_failing or []):
            results.append({"name": name, "critical": False, "ok": False,
                            "detail": f"{name} missing", "status": "missing"})
    return json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "today": "2026-06-10",
        "enforce": enforce,
        "results": results,
    })


def test_data_freshness_absent_not_degraded(monkeypatch, tmp_path):
    """No data_freshness.json = present:false, health not degraded."""
    monkeypatch.setattr("app.DATA_DIR", tmp_path)
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    df = body["checks"]["data_freshness"]
    assert df["present"] is False
    assert not any("data_freshness" in r for r in body["reasons"])


def test_data_freshness_all_passing_not_degraded(monkeypatch, tmp_path):
    (tmp_path / "data_freshness.json").write_text(
        _df_report(enforce=True, critical_failing=[], failing=[]), encoding="utf-8"
    )
    monkeypatch.setattr("app.DATA_DIR", tmp_path)
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    df = body["checks"]["data_freshness"]
    assert df["present"] is True
    assert df["critical_failing"] == []
    assert not any("data_freshness" in r for r in body["reasons"])


def test_data_freshness_enforce_on_critical_fail_market_open_degrades(monkeypatch, tmp_path):
    (tmp_path / "data_freshness.json").write_text(
        _df_report(enforce=True, critical_failing=["ycharts_scrape"]), encoding="utf-8"
    )
    monkeypatch.setattr("app.DATA_DIR", tmp_path)
    # Force market open
    import app as _app
    monkeypatch.setattr(_app, "mkt_open", True, raising=False)
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    assert "data_freshness:ycharts_scrape" in body["reasons"]
    assert body["status"] == "degraded"


def test_data_freshness_enforce_off_critical_fail_not_degraded(monkeypatch, tmp_path):
    (tmp_path / "data_freshness.json").write_text(
        _df_report(enforce=False, critical_failing=["ycharts_scrape"]), encoding="utf-8"
    )
    monkeypatch.setattr("app.DATA_DIR", tmp_path)
    client = _client_with_mocks(monkeypatch)
    body = client.get("/api/health").json()
    df = body["checks"]["data_freshness"]
    assert df["enforce"] is False
    assert "ycharts_scrape" in df["critical_failing"]
    assert not any("data_freshness" in r for r in body["reasons"])
