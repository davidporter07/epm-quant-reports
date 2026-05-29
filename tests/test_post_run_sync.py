"""PR0.1: post_run sync must use relative names (no Windows absolute C:\\ paths that
scp parses as host:path) and must exclude server-owned/local-only/managed entries."""
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
