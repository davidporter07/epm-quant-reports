"""Tests for services/watchdog_service.py — pure function + thread integration."""
from datetime import date, datetime, time as dtime

import pytest

import services.watchdog_service as ws

_CUTOFF = dtime(10, 30)

# June 8, 2026 = Monday; June 7, 2026 = Sunday; June 9, 2026 = Tuesday


def _always_open(_d):
    return True


def _always_closed(_d):
    return False


# ---------------------------------------------------------------------------
# _should_alert — pure function tests
# ---------------------------------------------------------------------------

def test_market_day_after_cutoff_stale_fires():
    now = datetime(2026, 6, 8, 11, 0)  # Monday 11:00 (naive)
    assert ws._should_alert(now, "2026-06-07", None, cutoff=_CUTOFF, is_market_open=_always_open)


def test_second_tick_same_day_no_duplicate():
    now = datetime(2026, 6, 8, 11, 0)
    assert not ws._should_alert(now, "2026-06-07", date(2026, 6, 8), cutoff=_CUTOFF, is_market_open=_always_open)


def test_before_cutoff_no_alert():
    now = datetime(2026, 6, 8, 10, 0)  # 10:00, before 10:30
    assert not ws._should_alert(now, "2026-06-07", None, cutoff=_CUTOFF, is_market_open=_always_open)


def test_weekend_no_alert():
    now = datetime(2026, 6, 7, 11, 0)  # Sunday
    assert not ws._should_alert(now, "2026-06-05", None, cutoff=_CUTOFF, is_market_open=lambda d: d.weekday() < 5)


def test_holiday_no_alert():
    now = datetime(2026, 5, 25, 11, 0)  # Memorial Day 2026
    assert not ws._should_alert(now, "2026-05-22", None, cutoff=_CUTOFF, is_market_open=_always_closed)


def test_fresh_report_no_alert():
    now = datetime(2026, 6, 8, 11, 0)
    assert not ws._should_alert(now, "2026-06-08", None, cutoff=_CUTOFF, is_market_open=_always_open)


def test_exactly_at_cutoff_fires():
    now = datetime(2026, 6, 8, 10, 30)  # exactly at cutoff
    assert ws._should_alert(now, "2026-06-07", None, cutoff=_CUTOFF, is_market_open=_always_open)


def test_one_minute_before_cutoff_no_alert():
    now = datetime(2026, 6, 8, 10, 29)
    assert not ws._should_alert(now, "2026-06-07", None, cutoff=_CUTOFF, is_market_open=_always_open)


# ---------------------------------------------------------------------------
# _run_tick — integration (module globals, injected send_fn)
# ---------------------------------------------------------------------------

def test_run_tick_sends_alert_and_marks_dedup(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    monkeypatch.setattr(ws, "_last_alert_date", None)

    import services.email_service as _es
    monkeypatch.setattr(_es, "gmail_configured", lambda: True)

    sent_to = []
    now = datetime(2026, 6, 8, 11, 0)
    result = ws._run_tick(
        now,
        _CUTOFF,
        load_fn=lambda: "2026-06-07",
        send_fn=lambda rpt, to: sent_to.append(to),
    )
    assert result is True
    assert sent_to == ["ops@example.com"]
    assert ws._last_alert_date == date(2026, 6, 8)


def test_run_tick_sender_raises_no_dedup(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    monkeypatch.setattr(ws, "_last_alert_date", None)

    import services.email_service as _es
    monkeypatch.setattr(_es, "gmail_configured", lambda: True)

    def _explode(rpt, to):
        raise RuntimeError("SMTP timeout")

    now = datetime(2026, 6, 8, 11, 0)
    result = ws._run_tick(
        now,
        _CUTOFF,
        load_fn=lambda: "2026-06-07",
        send_fn=_explode,
    )
    assert result is False
    assert ws._last_alert_date is None  # retry allowed on next tick


def test_run_tick_no_email_env_skips(monkeypatch):
    monkeypatch.delenv("ALERT_EMAIL", raising=False)
    monkeypatch.setattr(ws, "_last_alert_date", None)

    sent = []
    now = datetime(2026, 6, 8, 11, 0)
    result = ws._run_tick(
        now,
        _CUTOFF,
        load_fn=lambda: "2026-06-07",
        send_fn=lambda rpt, to: sent.append(to),
    )
    assert result is False
    assert sent == []


# ---------------------------------------------------------------------------
# start_watchdog — WATCHDOG_ENABLED=0 no-ops
# ---------------------------------------------------------------------------

def test_start_watchdog_disabled(monkeypatch):
    monkeypatch.setenv("WATCHDOG_ENABLED", "0")
    ws.stop_watchdog()
    ws.start_watchdog()
    status = ws.watchdog_status()
    assert status["alive"] is False
