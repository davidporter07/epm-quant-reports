"""PR2: deep_analysis_worker.worker_status() + conservative prune_old_jobs()."""
import json
from datetime import datetime, timedelta

import pytest

daw = pytest.importorskip("deep_analysis_worker")


def _write(d, name, obj):
    (d / name).write_text(json.dumps(obj), encoding="utf-8")


def test_worker_status_shape():
    s = daw.worker_status()
    assert {"alive", "stop_requested"} <= set(s.keys())
    assert isinstance(s["alive"], bool)


def test_prune_removes_only_old_terminal_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(daw, "JOBS_DIR", tmp_path)
    old = (datetime.utcnow() - timedelta(days=40)).isoformat()
    recent = (datetime.utcnow() - timedelta(days=5)).isoformat()

    _write(tmp_path, "old_done.json",    {"job_id": "a", "status": "completed", "completed_at": old})
    _write(tmp_path, "recent_done.json", {"job_id": "b", "status": "completed", "completed_at": recent})
    _write(tmp_path, "old_queued.json",  {"job_id": "c", "status": "queued",    "updated_at": old})
    _write(tmp_path, "old_running.json", {"job_id": "d", "status": "running",   "updated_at": old})
    _write(tmp_path, "old_no_ts.json",   {"job_id": "e", "status": "failed"})  # no timestamp

    removed = daw.prune_old_jobs(max_age_days=30)
    assert removed == 1  # only old_done.json qualifies

    names = {p.name for p in tmp_path.glob("*.json")}
    assert "old_done.json" not in names      # removed (old + terminal)
    assert "recent_done.json" in names       # kept (recent)
    assert "old_queued.json" in names        # kept (not terminal — never delete in-flight)
    assert "old_running.json" in names       # kept (not terminal)
    assert "old_no_ts.json" in names         # kept (no timestamp -> when in doubt, keep)


def test_prune_empty_dir_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(daw, "JOBS_DIR", tmp_path)
    assert daw.prune_old_jobs() == 0
