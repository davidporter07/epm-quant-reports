"""Mail routing policy (2026-06-10):

  - INTERNAL ops alerts (run_daily failure alerts, server watchdog) go via
    Gmail ONLY (provider="gmail") — they must never consume the Resend
    domain sender.
  - Resend is reserved for outward-facing mail (daily report, subscriber
    transactional mail).
  - The daily report's default send path falls back to Gmail if the Resend
    SMTP send fails, with the From header rewritten to the Gmail sender.
"""
from email.mime.text import MIMEText

import pytest

import services.email_service as es


GMAIL_USER = "internal@example.com"


class _FakeServer:
    def __init__(self, host, store, fail=False):
        self.host = host
        self.store = store
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        self.store.setdefault("logins", []).append((self.host, user, pw))

    def sendmail(self, frm, to, msg):
        if self.fail:
            raise RuntimeError("resend SMTP down")
        self.store.setdefault("sent", []).append((self.host, frm, list(to), msg))


def _wire_smtp(monkeypatch, store, fail_hosts=()):
    """Route SMTP_SSL by host; hosts in fail_hosts raise on sendmail."""
    def _factory(host, port, context=None):
        return _FakeServer(host, store, fail=host in fail_hosts)

    monkeypatch.setattr(es.smtplib, "SMTP_SSL", _factory)


@pytest.fixture
def mail_env(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "rk_test")
    monkeypatch.setenv("MAIL_FROM", "EPM <reports@epm-market-intelligence.com>")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "gmpw")
    monkeypatch.setenv("GMAIL_USER", GMAIL_USER)


# ---------------------------------------------------------------------------
# provider="gmail" — internal path never touches Resend
# ---------------------------------------------------------------------------

def test_send_message_gmail_provider_uses_gmail_smtp(monkeypatch, mail_env):
    store = {}
    _wire_smtp(monkeypatch, store)
    es.send_message("ops@example.com", "subj", "<b>h</b>", "h", provider="gmail")
    assert store["logins"] == [("smtp.gmail.com", GMAIL_USER, "gmpw")]
    host, frm, to, raw = store["sent"][0]
    assert host == "smtp.gmail.com"
    assert frm == GMAIL_USER
    assert to == ["ops@example.com"]
    assert f"From: {GMAIL_USER}" in raw


def test_send_raw_gmail_provider_without_creds_raises(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "rk_test")  # Resend creds must NOT be used
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(es.EmailError, match="GMAIL_APP_PASSWORD"):
        es.send_raw(MIMEText("x"), ["a@b.com"], provider="gmail")


def test_gmail_configured(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "gmpw")
    assert es.gmail_configured() is True
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert es.gmail_configured() is False


# ---------------------------------------------------------------------------
# Default path — Resend primary, Gmail fallback on send failure
# ---------------------------------------------------------------------------

def test_send_raw_resend_failure_falls_back_to_gmail(monkeypatch, mail_env, capsys):
    store = {}
    _wire_smtp(monkeypatch, store, fail_hosts={"smtp.resend.com"})
    msg = MIMEText("daily report")
    msg["From"] = "EPM <reports@epm-market-intelligence.com>"
    es.send_raw(msg, ["sub@example.com"])
    host, frm, to, raw = store["sent"][0]
    assert host == "smtp.gmail.com"
    assert frm == GMAIL_USER
    assert to == ["sub@example.com"]
    # From header must be rewritten to the Gmail sender for deliverability.
    assert f"From: {GMAIL_USER}" in raw
    assert "reports@epm-market-intelligence.com" not in raw.split("daily report")[0]
    out = capsys.readouterr().out
    assert "WARN" in out and "Gmail fallback" in out


def test_send_raw_resend_failure_without_gmail_raises(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "rk_test")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    store = {}
    _wire_smtp(monkeypatch, store, fail_hosts={"smtp.resend.com"})
    with pytest.raises(es.EmailError, match="resend"):
        es.send_raw(MIMEText("x"), ["a@b.com"])
    assert "sent" not in store


def test_send_raw_both_providers_fail_raises_combined(monkeypatch, mail_env):
    store = {}
    _wire_smtp(monkeypatch, store, fail_hosts={"smtp.resend.com", "smtp.gmail.com"})
    with pytest.raises(es.EmailError, match="fallback also failed"):
        es.send_raw(MIMEText("x"), ["a@b.com"])


def test_send_raw_resend_success_never_touches_gmail(monkeypatch, mail_env):
    store = {}
    _wire_smtp(monkeypatch, store)
    es.send_raw(MIMEText("x"), ["a@b.com"])
    hosts = [h for h, *_ in store["sent"]]
    assert hosts == ["smtp.resend.com"]
    assert store["logins"] == [("smtp.resend.com", "resend", "rk_test")]


# ---------------------------------------------------------------------------
# Alert callers pass provider="gmail"
# ---------------------------------------------------------------------------

def test_run_daily_alert_uses_gmail_provider(monkeypatch):
    import run_daily

    import services.email_service as _es
    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    monkeypatch.setattr(_es, "gmail_configured", lambda: True)
    captured = {}

    def _capture(to, subject, html, plain, **kw):
        captured["to"] = to
        captured["provider"] = kw.get("provider")

    monkeypatch.setattr(_es, "send_message", _capture)
    run_daily._send_alert("send_email", "boom")
    assert captured["to"] == "ops@example.com"
    assert captured["provider"] == "gmail"


def test_run_daily_alert_skips_without_gmail_creds(monkeypatch, capsys):
    import run_daily

    import services.email_service as _es
    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    monkeypatch.setattr(_es, "gmail_configured", lambda: False)
    monkeypatch.setattr(
        _es, "send_message",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not send")),
    )
    run_daily._send_alert("send_email", "boom")
    assert "GMAIL_APP_PASSWORD" in capsys.readouterr().out


def test_watchdog_alert_uses_gmail_provider(monkeypatch):
    import services.watchdog_service as ws
    import services.email_service as _es

    captured = {}

    def _capture(to, subject, html, plain, **kw):
        captured["to"] = to
        captured["provider"] = kw.get("provider")

    monkeypatch.setattr(_es, "send_message", _capture)
    ws._send_alert("2026-06-09", "ops@example.com")
    assert captured["to"] == "ops@example.com"
    assert captured["provider"] == "gmail"


def test_watchdog_tick_skips_without_gmail_creds(monkeypatch, capsys):
    import services.watchdog_service as ws
    import services.email_service as _es
    from datetime import datetime, time as dtime

    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    monkeypatch.setattr(ws, "_last_alert_date", None)
    monkeypatch.setattr(_es, "gmail_configured", lambda: False)

    sent = []
    result = ws._run_tick(
        datetime(2026, 6, 8, 11, 0),
        dtime(10, 30),
        load_fn=lambda: "2026-06-07",
        send_fn=lambda rpt, to: sent.append(to),
    )
    assert result is False
    assert sent == []
    assert "GMAIL_APP_PASSWORD" in capsys.readouterr().out
