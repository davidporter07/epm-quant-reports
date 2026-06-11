"""PR0.1: post_run sync must use relative names (no Windows absolute C:\\ paths that
scp parses as host:path) and must exclude server-owned/local-only/managed entries.
PR A: dirty-tree guard, unlisted-py warning, restart+probe after sync."""
import urllib.request

import pytest

pr = pytest.importorskip("post_run")


def _make_local(tmp_path):
    (tmp_path / "latest_commentary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "forecast.csv").write_text("a,b", encoding="utf-8")
    (tmp_path / "users.db").write_text("x", encoding="utf-8")                 # server-managed
    (tmp_path / "jwt_secret.key").write_text("x", encoding="utf-8")           # server-managed
    (tmp_path / "earnings_calendar.json").write_text("{}", encoding="utf-8")  # server-managed
    (tmp_path / "jobs").mkdir()             # server-owned
    (tmp_path / "experiment").mkdir()       # local-only
    (tmp_path / "qlora_training").mkdir()   # local-only
    (tmp_path / "dashboard").mkdir()        # operational subdir -> included
    (tmp_path / "__pycache__").mkdir()
    return tmp_path


def test_scp_dir_names_excludes_managed_and_local_only(tmp_path):
    _make_local(tmp_path)
    names = set(pr._scp_dir_names(tmp_path))
    assert {"latest_commentary.json", "forecast.csv", "dashboard"} <= names
    for excluded in ("users.db", "jwt_secret.key", "earnings_calendar.json",
                     "jobs", "experiment", "qlora_training", "__pycache__"):
        assert excluded not in names


def test_scp_dir_uses_relative_names_and_cwd(tmp_path, monkeypatch):
    _make_local(tmp_path)
    captured = {}

    class _R:
        returncode = 0

    def _fake_run(cmd, cwd=None, timeout=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return _R()

    monkeypatch.setattr(pr.subprocess, "run", _fake_run)
    rc = pr._scp_dir(tmp_path, "user@host:/opt/app/data", ["-i", "key"])

    assert rc == 0
    # scp runs FROM the local dir, so source args are relative names.
    assert captured["cwd"] == str(tmp_path)
    assert "user@host:/opt/app/data/" in captured["cmd"]
    # Source args must be bare names: no drive-colon, no path separators.
    src = [a for a in captured["cmd"]
           if a not in ("scp", "-r", "-i", "key", "user@host:/opt/app/data/")]
    assert src, "expected at least one file to sync"
    for a in src:
        assert ":" not in a, f"source arg looks absolute/host-like: {a!r}"
        assert "\\" not in a and "/" not in a, f"source arg is not a bare name: {a!r}"
    for excluded in ("users.db", "jwt_secret.key", "jobs", "experiment"):
        assert excluded not in captured["cmd"]


def test_scp_dir_empty_returns_zero(tmp_path, monkeypatch):
    called = {"ran": False}

    def _fake_run(*a, **k):
        called["ran"] = True

    monkeypatch.setattr(pr.subprocess, "run", _fake_run)
    rc = pr._scp_dir(tmp_path, "user@host:/opt/app/data", ["-i", "key"])
    assert rc == 0
    assert called["ran"] is False  # nothing to send -> no scp invocation


# --- PR A: dirty guard, unlisted-py warning, restart + probe -----------------

class _OK:
    returncode = 0


def _stub_scp_ok(monkeypatch):
    monkeypatch.setattr(pr.subprocess, "run", lambda *a, **kw: _OK())


def test_sync_refuses_dirty_tree(monkeypatch):
    """Dirty code paths must refuse the deploy before any scp runs."""
    monkeypatch.setattr(pr, "_git_dirty_code_paths", lambda: ["app.py"])
    scp_calls = []
    monkeypatch.setattr(pr.subprocess, "run", lambda cmd, **kw: scp_calls.append(cmd) or _OK())
    assert pr.sync_to_server() is False
    assert not scp_calls, "scp must not run when tree is dirty"


def test_sync_allows_dirty_with_flag(monkeypatch):
    """allow_dirty=True bypasses the dirty guard and proceeds to transfers."""
    monkeypatch.setattr(pr, "_git_dirty_code_paths", lambda: ["app.py"])
    monkeypatch.setattr(pr, "_unlisted_root_py", lambda: [])
    monkeypatch.setattr(pr, "_restart_service", lambda dest, key_args: True)
    monkeypatch.setattr(pr, "_probe_health_origin", lambda **kw: (True, "origin status=ok"))
    monkeypatch.setattr(pr, "_probe_health", lambda **kw: (True, "status=ok"))
    _stub_scp_ok(monkeypatch)
    assert pr.sync_to_server(allow_dirty=True) is True


def test_sync_allows_dirty_via_env_var(monkeypatch):
    """EPM_ALLOW_DIRTY_DEPLOY=1 bypasses the dirty guard."""
    monkeypatch.setattr(pr, "_git_dirty_code_paths", lambda: ["app.py"])
    monkeypatch.setattr(pr, "_unlisted_root_py", lambda: [])
    monkeypatch.setattr(pr, "_restart_service", lambda dest, key_args: True)
    monkeypatch.setattr(pr, "_probe_health_origin", lambda **kw: (True, "origin status=ok"))
    monkeypatch.setattr(pr, "_probe_health", lambda **kw: (True, "status=ok"))
    monkeypatch.setenv(pr._ALLOW_DIRTY_ENV, "1")
    _stub_scp_ok(monkeypatch)
    assert pr.sync_to_server() is True


def test_sync_warns_on_unlisted_py(monkeypatch, capsys):
    """Unlisted root .py emits a warning banner but does NOT fail the deploy."""
    monkeypatch.setattr(pr, "_git_dirty_code_paths", lambda: [])
    monkeypatch.setattr(pr, "_unlisted_root_py", lambda: ["brand_new_module.py"])
    monkeypatch.setattr(pr, "_restart_service", lambda dest, key_args: True)
    monkeypatch.setattr(pr, "_probe_health_origin", lambda **kw: (True, "origin status=ok"))
    monkeypatch.setattr(pr, "_probe_health", lambda **kw: (True, "status=ok"))
    _stub_scp_ok(monkeypatch)
    assert pr.sync_to_server() is True
    out = capsys.readouterr().out
    assert "brand_new_module.py" in out
    assert "WARN" in out


def test_sync_restart_failure_fails_run(monkeypatch):
    """Transfers OK but restart fails → sync_to_server returns False."""
    monkeypatch.setattr(pr, "_git_dirty_code_paths", lambda: [])
    monkeypatch.setattr(pr, "_unlisted_root_py", lambda: [])
    monkeypatch.setattr(pr, "_restart_service", lambda dest, key_args: False)
    monkeypatch.setattr(pr, "_probe_health_origin", lambda **kw: (True, "origin status=ok"))
    monkeypatch.setattr(pr, "_probe_health", lambda **kw: (True, "status=ok"))
    _stub_scp_ok(monkeypatch)
    assert pr.sync_to_server() is False


def test_sync_origin_health_failure_fails_deploy(monkeypatch):
    """Restart OK but origin health unreachable → deploy fails.

    Origin probe is deploy-critical; even if public URL were accessible,
    a dead origin means epm.service did not come up correctly."""
    monkeypatch.setattr(pr, "_git_dirty_code_paths", lambda: [])
    monkeypatch.setattr(pr, "_unlisted_root_py", lambda: [])
    monkeypatch.setattr(pr, "_restart_service", lambda dest, key_args: True)
    monkeypatch.setattr(pr, "_probe_health_origin", lambda **kw: (False, "origin curl exit 7: Connection refused"))
    monkeypatch.setattr(pr, "_probe_health", lambda **kw: (True, "status=ok"))
    _stub_scp_ok(monkeypatch)
    assert pr.sync_to_server() is False


def test_sync_origin_passes_when_public_fails(monkeypatch, capsys):
    """Origin OK but public URL fails → deploy still succeeds with a warning.

    Cloudflare blocks urllib's UA with 403 — this must never fail a deploy
    when the server itself is healthy."""
    monkeypatch.setattr(pr, "_git_dirty_code_paths", lambda: [])
    monkeypatch.setattr(pr, "_unlisted_root_py", lambda: [])
    monkeypatch.setattr(pr, "_restart_service", lambda dest, key_args: True)
    monkeypatch.setattr(pr, "_probe_health_origin", lambda **kw: (True, "origin status=ok"))
    monkeypatch.setattr(pr, "_probe_health", lambda **kw: (False, "HTTP 403 — <html>"))
    _stub_scp_ok(monkeypatch)
    result = pr.sync_to_server()
    assert result is True
    out = capsys.readouterr().out
    assert "WARN" in out
    assert "403" in out


def test_sync_full_success(monkeypatch):
    """Transfer + restart + both probes OK → True."""
    monkeypatch.setattr(pr, "_git_dirty_code_paths", lambda: [])
    monkeypatch.setattr(pr, "_unlisted_root_py", lambda: [])
    monkeypatch.setattr(pr, "_restart_service", lambda dest, key_args: True)
    monkeypatch.setattr(pr, "_probe_health_origin", lambda **kw: (True, "origin status=ok"))
    monkeypatch.setattr(pr, "_probe_health", lambda **kw: (True, "status=ok"))
    _stub_scp_ok(monkeypatch)
    assert pr.sync_to_server() is True


def test_probe_health_degraded_passes_with_warning(monkeypatch, capsys):
    """status=degraded is reachable (True) but prints a loud warning banner."""
    import json

    class _FakeResp:
        status = 200
        def read(self):
            return json.dumps({"status": "degraded"}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: _FakeResp())
    ok, detail = pr._probe_health(url="https://example.com/api/health", attempts=1, delay=0)
    assert ok is True
    assert "degraded" in detail
    out = capsys.readouterr().out
    assert "degraded" in out


def test_probe_health_delayed_startup_eventually_passes(monkeypatch):
    """App unreachable for N-1 attempts then comes up OK — probe returns True.

    Regression guard: the old 6×3s window raced a slow post-scp restart and
    returned (False, 'unreachable') before the app was ready, poisoning
    run_daily_status.json with last_run_failed:post_run on an otherwise clean run.
    """
    import json

    class _FakeResp:
        status = 200
        def read(self):
            return json.dumps({"status": "ok"}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): pass

    calls = {"n": 0}

    def _urlopen(url, timeout=None):
        calls["n"] += 1
        if calls["n"] < 4:  # fail first 3, succeed on 4th
            import urllib.error as _uerr
            raise _uerr.URLError("connection refused")
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(pr.time, "sleep", lambda _: None)
    ok, detail = pr._probe_health(url="https://example.com/api/health", attempts=12, delay=0)
    assert ok is True
    assert "ok" in detail
    assert calls["n"] == 4


def test_probe_health_http_error_detail_surfaced(monkeypatch):
    """HTTPError (e.g. Cloudflare 403) surfaces the status code in the return value.

    Regression guard: HTTPError is a URLError subclass, so before this fix it was
    silently swallowed as 'unreachable', burning all retries with no diagnostic."""
    import urllib.error as _uerr

    class _FakeHTTPError(_uerr.HTTPError):
        def __init__(self):
            super().__init__(url="https://example.com", code=403, msg="Forbidden",
                             hdrs=None, fp=None)
        def read(self, n=256):
            return b"<html>Access denied</html>"

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: (_ for _ in ()).throw(_FakeHTTPError()))
    monkeypatch.setattr(pr.time, "sleep", lambda _: None)
    ok, detail = pr._probe_health(url="https://example.com/api/health", attempts=1, delay=0)
    assert ok is False
    assert "403" in detail


def test_probe_health_origin_succeeds_on_delayed_startup(monkeypatch):
    """Origin probe retries until SSH+curl succeeds — returns (True, 'origin status=ok')."""
    import json

    calls = {"n": 0}

    def _fake_run(cmd, capture_output=False, text=False, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return type("R", (), {"returncode": 7, "stdout": "", "stderr": "Connection refused"})()
        return type("R", (), {
            "returncode": 0,
            "stdout": json.dumps({"status": "ok"}),
            "stderr": "",
        })()

    monkeypatch.setattr(pr.subprocess, "run", _fake_run)
    monkeypatch.setattr(pr.time, "sleep", lambda _: None)
    ok, detail = pr._probe_health_origin(
        ssh_dest="dporter02@127.0.0.1", ssh_key="/dev/null",
        attempts=12, delay=0,
    )
    assert ok is True
    assert "origin status=ok" in detail
    assert calls["n"] == 3


def test_root_py_inventory_classified():
    """Repo invariant: every tracked root .py is in SYNC_PY_FILES or _NOT_DEPLOYED_PY."""
    import subprocess
    from pathlib import Path
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    deployed = set(pr.SYNC_PY_FILES)
    unclassified = [
        name for name in result.stdout.splitlines()
        if "/" not in name and name.endswith(".py")
        and name not in deployed
        and name not in pr._NOT_DEPLOYED_PY
    ]
    assert not unclassified, (
        f"These root .py files are neither deployed nor classified as laptop-only: "
        f"{unclassified}. "
        f"Add to SYNC_PY_FILES (server) or _NOT_DEPLOYED_PY (laptop-only)."
    )


# --- PR B: push_status_file ---------------------------------------------------

def test_push_status_file_builds_correct_scp_cmd(tmp_path, monkeypatch):
    """push_status_file must scp the status file to data/ on the server."""
    status_file = tmp_path / "run_daily_status.json"
    status_file.write_text('{"ts":"2026-06-09T14:00:00Z","stage":"ok","ok":true}', encoding="utf-8")

    captured = {}

    class _OK:
        returncode = 0

    def _fake_run(cmd, capture_output=None, timeout=None):
        captured["cmd"] = cmd
        return _OK()

    monkeypatch.setattr(pr.subprocess, "run", _fake_run)

    result = pr.push_status_file(
        local_status=str(status_file),
        remote_dest="dporter02@server:/opt/epm/data/run_daily_status.json",
    )
    assert result is True
    assert "scp" in captured["cmd"]
    assert any("run_daily_status.json" in a for a in captured["cmd"])
    assert any("data/run_daily_status.json" in a for a in captured["cmd"])
    assert "-O" in captured["cmd"]


def test_push_status_file_missing_file_returns_false(monkeypatch):
    result = pr.push_status_file(
        local_status="/nonexistent/run_daily_status.json",
        remote_dest="user@host:/path",
    )
    assert result is False


def test_push_status_file_scp_failure_returns_false(tmp_path, monkeypatch):
    status_file = tmp_path / "run_daily_status.json"
    status_file.write_text("{}", encoding="utf-8")

    class _Fail:
        returncode = 1

    monkeypatch.setattr(pr.subprocess, "run", lambda *a, **k: _Fail())
    result = pr.push_status_file(local_status=str(status_file), remote_dest="user@host:/path")
    assert result is False


def test_push_status_file_exception_returns_false(tmp_path, monkeypatch):
    status_file = tmp_path / "run_daily_status.json"
    status_file.write_text("{}", encoding="utf-8")

    def _raise(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(pr.subprocess, "run", _raise)
    result = pr.push_status_file(local_status=str(status_file), remote_dest="user@host:/path")
    assert result is False


# --- PR F commit 1: WAL sidecar exclusion ------------------------------------

def test_scp_dir_names_excludes_wal_sidecars(tmp_path):
    """WAL sidecars must never be pushed to the server — they are server-managed."""
    (tmp_path / "latest_commentary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "users.db").write_text("x", encoding="utf-8")
    (tmp_path / "users.db-wal").write_text("x", encoding="utf-8")
    (tmp_path / "users.db-shm").write_text("x", encoding="utf-8")
    (tmp_path / "research_cache.db").write_text("x", encoding="utf-8")
    (tmp_path / "research_cache.db-wal").write_text("x", encoding="utf-8")
    (tmp_path / "research_cache.db-shm").write_text("x", encoding="utf-8")

    names = set(pr._scp_dir_names(tmp_path))
    assert "latest_commentary.json" in names
    for sidecar in (
        "users.db", "users.db-wal", "users.db-shm",
        "research_cache.db", "research_cache.db-wal", "research_cache.db-shm",
    ):
        assert sidecar not in names, f"{sidecar!r} must be excluded from sync"


def test_server_managed_set_contains_wal_sidecars():
    """Regression: _SERVER_MANAGED must include WAL/SHM sidecars (committed constant)."""
    required = {
        "users.db-wal", "users.db-shm",
        "research_cache.db-wal", "research_cache.db-shm",
    }
    assert required <= pr._SERVER_MANAGED, (
        f"Missing from _SERVER_MANAGED: {required - pr._SERVER_MANAGED}"
    )
