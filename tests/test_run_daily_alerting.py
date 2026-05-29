"""PR2: run_daily alerting hooks — failures must record a non-ok status; the status
file is written; the successful flow still records ok."""
import json

import run_daily


def _runner(results):
    def r(cmd):
        return results.pop(0) if results else 0
    return r


def test_record_status_writes_structured_file_and_marker(tmp_path):
    sf = tmp_path / "run_daily_status.json"
    run_daily._record_status("ok", True, "all good", status_file=sf)
    data = json.loads(sf.read_text(encoding="utf-8"))
    assert data["stage"] == "ok"
    assert data["ok"] is True
    assert data["detail"] == "all good"
    assert "ts" in data
    assert (tmp_path / "run_daily.log").exists()


def test_failed_email_records_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(run_daily, "_record_status",
                        lambda stage, ok, detail, **k: calls.append((stage, ok)))
    rc = run_daily.main([], runner=_runner([1]), fresh_checker=lambda: (True, "fresh"))
    assert rc == 1
    assert ("send_email", False) in calls


def test_stale_site_records_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(run_daily, "_record_status",
                        lambda stage, ok, detail, **k: calls.append((stage, ok)))
    rc = run_daily.main([], runner=_runner([0, 0]), fresh_checker=lambda: (False, "STALE"))
    assert rc == 2
    assert ("freshness", False) in calls


def test_success_records_ok(monkeypatch):
    calls = []
    monkeypatch.setattr(run_daily, "_record_status",
                        lambda stage, ok, detail, **k: calls.append((stage, ok)))
    rc = run_daily.main([], runner=_runner([0, 0]), fresh_checker=lambda: (True, "fresh"))
    assert rc == 0
    assert ("ok", True) in calls
