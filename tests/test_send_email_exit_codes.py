"""PR2: send_email.main() must return non-zero on real failures (monitor / SMTP)
and a clean 0 for the already-sent / market-closed skips."""
import subprocess
import types

import pytest

# send_email runs some module-level code (subject build, logging). Skip cleanly if
# the environment can't import it.
se = pytest.importorskip("send_email")


def _ok_run(*a, **k):
    return types.SimpleNamespace(returncode=0)


@pytest.fixture(autouse=True)
def _no_real_io(monkeypatch):
    # Never write the real sent-log or build a real email during these tests.
    monkeypatch.setattr(se, "mark_sent_today", lambda: None)
    monkeypatch.setattr(se, "build_email",
                        lambda *a, **k: types.SimpleNamespace(as_string=lambda: "msg"))
    # Single internal recipient so the send loop never touches the network for the list.
    monkeypatch.setattr(se, "get_daily_recipients",
                        lambda: [{"email": se.TO, "unsubscribe_url": None}])


def test_already_sent_returns_zero_and_does_not_run(monkeypatch):
    monkeypatch.setattr(se, "already_sent_today", lambda: True)
    called = {"ran": False}
    monkeypatch.setattr(se.subprocess, "run", lambda *a, **k: called.__setitem__("ran", True))
    assert se.main([]) == 0
    assert called["ran"] is False  # no monitor / send attempted


def test_market_closed_returns_zero(monkeypatch):
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: False)
    assert se.main([]) == 0


def test_monitor_failure_returns_nonzero(monkeypatch):
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)

    def _boom(*a, **k):
        raise subprocess.CalledProcessError(1, "monitor.py")

    monkeypatch.setattr(se.subprocess, "run", _boom)
    assert se.main([]) == 1


def test_stale_commentary_returns_nonzero(monkeypatch):
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: "[BLOCK] stale")
    assert se.main([]) == 1


def test_smtp_failure_returns_nonzero(monkeypatch):
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)  # fresh

    def _send_boom(*a, **k):
        raise OSError("smtp down")

    monkeypatch.setattr(se.email_service, "send_raw", _send_boom)
    assert se.main([]) == 1


def test_success_returns_zero_and_marks_sent(monkeypatch):
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)

    marked = {"v": False}
    monkeypatch.setattr(se, "mark_sent_today", lambda: marked.__setitem__("v", True))

    sent = {"n": 0}
    monkeypatch.setattr(se.email_service, "send_raw",
                        lambda *a, **k: sent.__setitem__("n", sent["n"] + 1))
    assert se.main([]) == 0
    assert marked["v"] is True
    assert sent["n"] == 1
