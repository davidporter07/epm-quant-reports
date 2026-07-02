"""PR2: send_email.main() must return non-zero on real failures (monitor / SMTP)
and a clean 0 for the already-sent / market-closed skips.
PR E: ledger idempotency, exit 6 (partial / fetch failure), PDF gate.
"""
import json
import subprocess
import types

import pytest

# send_email runs some module-level code (subject build, logging). Skip cleanly if
# the environment can't import it.
se = pytest.importorskip("send_email")

from services import send_ledger as _sl


def _ok_run(*a, **k):
    return types.SimpleNamespace(returncode=0)


def _make_recipients(fetch_ok=True):
    """Return (recipients_list, fetch_ok) — matches fetch_daily_recipients() signature."""
    return [{"email": se.TO, "unsubscribe_url": None}], fetch_ok


@pytest.fixture(autouse=True)
def _no_real_io(monkeypatch, tmp_path):
    """Isolate every test from real filesystem, network, and subprocess side effects."""
    monkeypatch.setattr(se, "mark_sent_today", lambda: None)
    monkeypatch.setattr(se, "build_email",
                        lambda *a, **k: types.SimpleNamespace(as_string=lambda: "msg"))
    # main() calls fetch_daily_recipients(); wire a default of (internal, fetch_ok=True)
    monkeypatch.setattr(se, "fetch_daily_recipients", lambda: _make_recipients(True))
    # PDF is always ok by default
    monkeypatch.setattr(se, "_check_pdf", lambda today: (True, "PDF fresh"))
    # Route ledger/summary writes to tmp_path so tests stay isolated
    ledger_path = tmp_path / "ledger.json"
    summary_path = tmp_path / "summary.json"
    import services.send_ledger as _sl_mod
    monkeypatch.setattr(_sl_mod, "_LEDGER_PATH", ledger_path)
    monkeypatch.setattr(_sl_mod, "_SUMMARY_PATH", summary_path)


# ---------------------------------------------------------------------------
# Legacy fast-path tests (PR2 — unchanged behaviour)
# ---------------------------------------------------------------------------

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
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)

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
                        lambda *a, **k: sent.__setitem__("n", sent["n"] + 1) or "resend")
    assert se.main([]) == 0
    assert marked["v"] is True
    assert sent["n"] == 1


# ---------------------------------------------------------------------------
# PR E: partial send → exit 6, no mark_sent_today
# ---------------------------------------------------------------------------

def _two_recipients():
    return [
        {"email": se.TO, "unsubscribe_url": None},
        {"email": "sub@example.com", "unsubscribe_url": "https://x.com/unsub"},
    ], True


def test_partial_send_exits_6_no_legacy_mark(monkeypatch):
    """First recipient succeeds, second fails → exit 6, mark_sent_today NOT called."""
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)
    monkeypatch.setattr(se, "fetch_daily_recipients", _two_recipients)

    results = iter(["resend", OSError("smtp error")])

    def _mixed(*a, **k):
        r = next(results)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(se.email_service, "send_raw", _mixed)

    marked = {"v": False}
    monkeypatch.setattr(se, "mark_sent_today", lambda: marked.__setitem__("v", True))

    rc = se.main([])
    assert rc == se.EXIT_PARTIAL_SEND
    assert marked["v"] is False


def test_all_fail_exits_1(monkeypatch):
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)

    monkeypatch.setattr(se.email_service, "send_raw", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert se.main([]) == 1


# ---------------------------------------------------------------------------
# PR E: idempotent retry via ledger
# ---------------------------------------------------------------------------

def test_idempotent_retry_sends_only_failed_recipients(monkeypatch, tmp_path):
    """Pre-seed ledger with internal recipient ok → only sub@example.com is sent."""
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)
    monkeypatch.setattr(se, "fetch_daily_recipients", _two_recipients)

    import services.send_ledger as _sl_mod
    from datetime import datetime, timezone
    today = datetime.now().strftime("%Y-%m-%d")
    # Pre-seed: internal already sent ok
    ledger = _sl_mod._empty_ledger(today)
    ledger["recipients"][se.TO.lower()] = {"ok": True, "provider": "resend", "error": None, "ts": "x"}
    _sl_mod._LEDGER_PATH.write_text(json.dumps(ledger), encoding="utf-8")

    sent_to = []
    monkeypatch.setattr(se.email_service, "send_raw",
                        lambda msg, addrs, **k: sent_to.extend(addrs) or "resend")

    marked = {"v": False}
    monkeypatch.setattr(se, "mark_sent_today", lambda: marked.__setitem__("v", True))

    rc = se.main([])
    assert rc == 0
    assert marked["v"] is True
    assert sent_to == ["sub@example.com"]  # only the pending recipient


def test_complete_ledger_skips_all_sends(monkeypatch, tmp_path):
    """If ledger shows all recipients done, send loop is skipped entirely."""
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)
    monkeypatch.setattr(se, "fetch_daily_recipients", _two_recipients)

    import services.send_ledger as _sl_mod
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    ledger = _sl_mod._empty_ledger(today)
    for email in [se.TO.lower(), "sub@example.com"]:
        ledger["recipients"][email] = {"ok": True, "provider": "resend", "error": None, "ts": "x"}
    _sl_mod._LEDGER_PATH.write_text(json.dumps(ledger), encoding="utf-8")

    send_called = {"n": 0}
    monkeypatch.setattr(se.email_service, "send_raw",
                        lambda *a, **k: send_called.__setitem__("n", send_called["n"] + 1))

    rc = se.main([])
    assert rc == 0
    assert send_called["n"] == 0


def test_retry_with_repeat_failure_exits_6_no_mark(monkeypatch, tmp_path):
    """Regression (PR E commit 7): a retry where the pending recipient fails AGAIN
    must stay exit 6. Prior-run successes in the ledger must not deflate the
    failure count and let mark_sent_today() declare the day fully sent."""
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)
    monkeypatch.setattr(se, "fetch_daily_recipients", _two_recipients)

    marked = {"v": False}
    monkeypatch.setattr(se, "mark_sent_today", lambda: marked.__setitem__("v", True))

    def _sub_always_fails(msg, addrs, **k):
        if addrs == ["sub@example.com"]:
            raise OSError("mailbox unavailable")
        return "resend"

    monkeypatch.setattr(se.email_service, "send_raw", _sub_always_fails)

    # First attempt: internal ok, subscriber fails
    assert se.main([]) == se.EXIT_PARTIAL_SEND
    assert marked["v"] is False

    # Retry (ledger persisted): only the subscriber is pending, fails again
    assert se.main([]) == se.EXIT_PARTIAL_SEND
    assert marked["v"] is False

    # Ledger + summary still record the failure (health stays degradable)
    import services.send_ledger as _sl_mod
    ledger = json.loads(_sl_mod._LEDGER_PATH.read_text(encoding="utf-8"))
    assert ledger["recipients"]["sub@example.com"]["ok"] is False
    summary = json.loads(_sl_mod._SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["failed"] >= 1
    assert summary["sent"] == 1
    assert summary["internal_ok"] is True
    assert "@" not in json.dumps(summary)


# ---------------------------------------------------------------------------
# PR E: internal recipient failure
# ---------------------------------------------------------------------------

def test_internal_fails_exits_6(monkeypatch):
    """Internal send fails, subscriber succeeds → exit 6 (not 1)."""
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)
    monkeypatch.setattr(se, "fetch_daily_recipients", _two_recipients)

    def _internal_fails(msg, addrs, **k):
        if addrs == [se.TO]:
            raise OSError("internal smtp error")
        return "resend"

    monkeypatch.setattr(se.email_service, "send_raw", _internal_fails)

    marked = {"v": False}
    monkeypatch.setattr(se, "mark_sent_today", lambda: marked.__setitem__("v", True))

    rc = se.main([])
    assert rc == se.EXIT_PARTIAL_SEND
    assert marked["v"] is False


# ---------------------------------------------------------------------------
# PR E: subscriber fetch failure → exit 6, no mark_sent_today
# ---------------------------------------------------------------------------

def test_fetch_failure_exits_6_no_mark(monkeypatch):
    """fetch_ok=False → internal-only send, exit 6, no mark_sent_today."""
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)
    # fetch fails — only internal recipient, fetch_ok=False
    monkeypatch.setattr(se, "fetch_daily_recipients", lambda: _make_recipients(False))
    monkeypatch.setattr(se.email_service, "send_raw", lambda *a, **k: "resend")

    marked = {"v": False}
    monkeypatch.setattr(se, "mark_sent_today", lambda: marked.__setitem__("v", True))

    rc = se.main([])
    assert rc == se.EXIT_PARTIAL_SEND
    assert marked["v"] is False


def test_fetch_recovery_retry_exits_0(monkeypatch, tmp_path):
    """Retry after fetch recovers: internal already in ledger → sends only subscribers."""
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)
    # Fetch recovered — now returns all recipients
    monkeypatch.setattr(se, "fetch_daily_recipients", _two_recipients)

    import services.send_ledger as _sl_mod
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    # Pre-seed ledger: internal was sent ok in the prior failed run
    ledger = _sl_mod._empty_ledger(today)
    ledger["fetch_ok"] = False
    ledger["recipients"][se.TO.lower()] = {"ok": True, "provider": "resend", "error": None, "ts": "x"}
    _sl_mod._LEDGER_PATH.write_text(json.dumps(ledger), encoding="utf-8")

    sent_to = []
    monkeypatch.setattr(se.email_service, "send_raw",
                        lambda msg, addrs, **k: sent_to.extend(addrs) or "resend")

    marked = {"v": False}
    monkeypatch.setattr(se, "mark_sent_today", lambda: marked.__setitem__("v", True))

    rc = se.main([])
    assert rc == 0
    assert marked["v"] is True
    assert sent_to == ["sub@example.com"]  # only the subscriber, not the internal


# ---------------------------------------------------------------------------
# PR E: PDF gate
# ---------------------------------------------------------------------------

def test_pdf_missing_with_require_blocks_before_send(monkeypatch):
    """SEND_REQUIRE_PDF=1 + missing PDF → exit 1 before any send."""
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)
    monkeypatch.setattr(se, "_check_pdf", lambda today: (False, "[BLOCK] PDF not found — SEND_REQUIRE_PDF=1"))

    send_called = {"n": 0}
    monkeypatch.setattr(se.email_service, "send_raw",
                        lambda *a, **k: send_called.__setitem__("n", send_called["n"] + 1))

    rc = se.main([])
    assert rc == 1
    assert send_called["n"] == 0


def test_pdf_missing_default_warn_sends_anyway(monkeypatch):
    """SEND_REQUIRE_PDF=0 (default): missing PDF logs a warning but send proceeds."""
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)
    monkeypatch.setattr(se, "_check_pdf", lambda today: (False, "[WARN] PDF not found"))

    send_called = {"n": 0}
    monkeypatch.setattr(se.email_service, "send_raw",
                        lambda *a, **k: send_called.__setitem__("n", send_called["n"] + 1) or "resend")

    marked = {"v": False}
    monkeypatch.setattr(se, "mark_sent_today", lambda: marked.__setitem__("v", True))

    rc = se.main([])
    assert rc == 0
    assert send_called["n"] == 1
    assert marked["v"] is True


# ---------------------------------------------------------------------------
# 2026-06-22: internal recipient routes via Gmail (Resend silent-drop fix)
# ---------------------------------------------------------------------------

def test_all_recipients_route_via_default_provider(monkeypatch):
    # As of 2026-07-02 the internal ops copy is NO LONGER force-routed via Gmail. Every
    # recipient — internal and subscriber — goes through the default provider (Resend on
    # the branded epm-market-intelligence.com domain) with send_raw's automatic
    # Resend->Gmail fallback on SMTP failure. This restores the branded sender on the
    # internal copy (previously it showed the raw davidporter0731@gmail.com Gmail sender),
    # with delivery still covered by the ledger + the fallback. Supersedes the old
    # internal-forced-to-Gmail routing from the 6/22 anti-silent-drop fix.
    monkeypatch.setattr(se, "already_sent_today", lambda: False)
    monkeypatch.setattr(se, "is_market_open", lambda: True)
    monkeypatch.setattr(se.subprocess, "run", _ok_run)
    monkeypatch.setattr(se, "_check_commentary_fresh", lambda today: None)
    monkeypatch.setattr(se, "fetch_daily_recipients", lambda: _two_recipients())
    # Even with Gmail creds present, the internal recipient must NOT be forced to Gmail.
    monkeypatch.setattr(se.email_service, "gmail_configured", lambda: True)

    seen = {}

    def _capture(msg, to_addrs, *a, **k):
        seen[to_addrs[0].strip().lower()] = k.get("provider")
        return k.get("provider") or "resend"

    monkeypatch.setattr(se.email_service, "send_raw", _capture)
    assert se.main([]) == 0
    assert seen[se.TO.strip().lower()] is None           # internal → default (Resend), not Gmail
    assert seen["sub@example.com"] is None               # subscriber → default (Resend)
