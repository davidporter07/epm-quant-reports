"""PR E: services/send_ledger — per-recipient ledger + counts-only summary."""
import json
from pathlib import Path

import pytest

from services import send_ledger as sl

TODAY = "2026-06-11"
TOMORROW = "2026-06-12"
INTERNAL = "ops@example.com"


# ---------------------------------------------------------------------------
# load_ledger — absent / wrong day / malformed → fresh doc; never raises
# ---------------------------------------------------------------------------

def test_load_ledger_absent_returns_fresh(tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "ledger.json")
    assert ledger["date"] == TODAY
    assert ledger["recipients"] == {}
    assert ledger["attempts"] == 0


def test_load_ledger_wrong_day_returns_fresh(tmp_path):
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps({"date": TOMORROW, "recipients": {}, "attempts": 5}))
    ledger = sl.load_ledger(TODAY, path=p)
    assert ledger["date"] == TODAY
    assert ledger["attempts"] == 0


def test_load_ledger_malformed_returns_fresh(tmp_path):
    p = tmp_path / "ledger.json"
    p.write_text("not json {{")
    ledger = sl.load_ledger(TODAY, path=p)
    assert ledger["date"] == TODAY
    assert ledger["recipients"] == {}


def test_load_ledger_valid_today_returns_existing(tmp_path):
    data = {"date": TODAY, "attempts": 2, "recipients": {"a@b.com": {"ok": True}},
            "fetch_ok": True, "pdf_ok": True, "started_at": None, "finished_at": None}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(data))
    ledger = sl.load_ledger(TODAY, path=p)
    assert ledger["attempts"] == 2
    assert "a@b.com" in ledger["recipients"]


def test_load_ledger_never_raises(tmp_path, monkeypatch):
    # Simulate an unreadable file (permission error)
    import builtins
    original_open = builtins.open

    def _bad_open(p, *a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(builtins, "open", _bad_open)
    # Should not raise — returns fresh doc
    ledger = sl.load_ledger(TODAY, path=tmp_path / "ledger.json")
    assert ledger["date"] == TODAY


# ---------------------------------------------------------------------------
# successful_recipients — lowercased emails with ok=True
# ---------------------------------------------------------------------------

def test_successful_recipients_empty():
    ledger = sl.load_ledger(TODAY)  # in-memory only, path not needed here
    # Patch recipients directly
    ledger["recipients"] = {}
    assert sl.successful_recipients(ledger) == set()


def test_successful_recipients_filters_failures():
    ledger = {"recipients": {
        "A@B.com": {"ok": True},
        "C@D.com": {"ok": False},
        "E@F.com": {"ok": True},
    }}
    result = sl.successful_recipients(ledger)
    assert result == {"a@b.com", "e@f.com"}


def test_successful_recipients_lowercases():
    ledger = {"recipients": {"USER@EXAMPLE.COM": {"ok": True}}}
    assert "user@example.com" in sl.successful_recipients(ledger)


# ---------------------------------------------------------------------------
# record_attempt_start — increments attempts, sets flags
# ---------------------------------------------------------------------------

def test_record_attempt_start_increments(tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    ledger = sl.record_attempt_start(ledger, fetch_ok=True, pdf_ok=True)
    assert ledger["attempts"] == 1
    ledger = sl.record_attempt_start(ledger, fetch_ok=False, pdf_ok=False)
    assert ledger["attempts"] == 2
    assert ledger["fetch_ok"] is False
    assert ledger["pdf_ok"] is False


# ---------------------------------------------------------------------------
# record_result — merge, failure→success overwrites, success→failure does not
# ---------------------------------------------------------------------------

def test_record_result_ok_true(tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    ledger = sl.record_result(ledger, "sub@x.com", ok=True, provider="resend", error=None)
    rec = ledger["recipients"]["sub@x.com"]
    assert rec["ok"] is True
    assert rec["provider"] == "resend"
    assert rec["error"] is None


def test_record_result_failure_sets_error(tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    ledger = sl.record_result(ledger, "sub@x.com", ok=False, provider=None, error="timeout" * 50)
    rec = ledger["recipients"]["sub@x.com"]
    assert rec["ok"] is False
    assert len(rec["error"]) <= 200


def test_record_result_failure_to_success_overwrites(tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    ledger = sl.record_result(ledger, "sub@x.com", ok=False, provider=None, error="err1")
    ledger = sl.record_result(ledger, "sub@x.com", ok=True, provider="gmail_fallback", error=None)
    assert ledger["recipients"]["sub@x.com"]["ok"] is True


def test_record_result_success_to_failure_does_not_overwrite(tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    ledger = sl.record_result(ledger, "sub@x.com", ok=True, provider="resend", error=None)
    ledger = sl.record_result(ledger, "sub@x.com", ok=False, provider=None, error="late err")
    assert ledger["recipients"]["sub@x.com"]["ok"] is True


def test_record_result_lowercases_key(tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    ledger = sl.record_result(ledger, "SUB@X.COM", ok=True, provider="resend", error=None)
    assert "sub@x.com" in ledger["recipients"]
    assert "SUB@X.COM" not in ledger["recipients"]


# ---------------------------------------------------------------------------
# write_ledger — atomic tmp→replace; never raises
# ---------------------------------------------------------------------------

def test_write_ledger_roundtrip(tmp_path):
    p = tmp_path / "ledger.json"
    ledger = sl.load_ledger(TODAY, path=p)
    ledger = sl.record_result(ledger, "a@b.com", ok=True, provider="resend", error=None)
    sl.write_ledger(ledger, path=p)
    loaded = json.loads(p.read_text(encoding="utf-8"))
    assert loaded["recipients"]["a@b.com"]["ok"] is True


def test_write_ledger_never_raises(monkeypatch, tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    # Point at an unwritable path (non-existent parent in a read-only location)
    bad_path = Path("Z:/nonexistent/ledger.json")
    sl.write_ledger(ledger, path=bad_path)  # must not raise


# ---------------------------------------------------------------------------
# write_summary — counts only; no @ addresses in output; never raises
# ---------------------------------------------------------------------------

def test_write_summary_counts(tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    ledger = sl.record_attempt_start(ledger, fetch_ok=True, pdf_ok=True)
    ledger = sl.record_result(ledger, INTERNAL, ok=True, provider="resend", error=None)
    ledger = sl.record_result(ledger, "sub1@x.com", ok=True, provider="resend", error=None)
    ledger = sl.record_result(ledger, "sub2@x.com", ok=False, provider=None, error="timeout")
    p = tmp_path / "summary.json"
    sl.write_summary(ledger, internal_email=INTERNAL, path=p)
    summary = json.loads(p.read_text(encoding="utf-8"))
    assert summary["date"] == TODAY
    assert summary["total"] == 3
    assert summary["sent"] == 2
    assert summary["failed"] == 1
    assert summary["internal_ok"] is True
    assert summary["fetch_ok"] is True
    assert summary["fallback_used"] is False
    assert summary["pdf_ok"] is True


def test_write_summary_fallback_used(tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    ledger = sl.record_attempt_start(ledger, fetch_ok=True, pdf_ok=True)
    ledger = sl.record_result(ledger, "sub@x.com", ok=True, provider="gmail_fallback", error=None)
    p = tmp_path / "summary.json"
    sl.write_summary(ledger, internal_email=INTERNAL, path=p)
    summary = json.loads(p.read_text(encoding="utf-8"))
    assert summary["fallback_used"] is True


def test_write_summary_contains_no_email_addresses(tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    ledger = sl.record_attempt_start(ledger, fetch_ok=True, pdf_ok=True)
    ledger = sl.record_result(ledger, INTERNAL, ok=True, provider="resend", error=None)
    ledger = sl.record_result(ledger, "subscriber@secret.com", ok=True, provider="resend", error=None)
    p = tmp_path / "summary.json"
    sl.write_summary(ledger, internal_email=INTERNAL, path=p)
    raw = p.read_text(encoding="utf-8")
    assert "@" not in raw, f"Summary must not contain email addresses, got: {raw}"


def test_write_summary_never_raises(monkeypatch, tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    bad_path = Path("Z:/nonexistent/summary.json")
    sl.write_summary(ledger, internal_email=INTERNAL, path=bad_path)  # must not raise


def test_write_summary_fetch_ok_false(tmp_path):
    ledger = sl.load_ledger(TODAY, path=tmp_path / "l.json")
    ledger = sl.record_attempt_start(ledger, fetch_ok=False, pdf_ok=True)
    ledger = sl.record_result(ledger, INTERNAL, ok=True, provider="resend", error=None)
    p = tmp_path / "summary.json"
    sl.write_summary(ledger, internal_email=INTERNAL, path=p)
    summary = json.loads(p.read_text(encoding="utf-8"))
    assert summary["fetch_ok"] is False
