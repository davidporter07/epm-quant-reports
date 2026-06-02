"""Plan 1 — daily-email subscription, domain sender, and alerts.

Three independently-skippable groups so the suite runs in both the pipeline-only
venv and the full web-app venv:
  - email_service: stdlib-only, always runs.
  - auth_service: needs bcrypt + PyJWT (web venv).
  - send_email.get_daily_recipients: needs the pipeline import to succeed.
  - app endpoints: need fastapi + httpx.
"""
import sys
from email.mime.text import MIMEText
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# email_service — provider selection + send path (stdlib only)
# ---------------------------------------------------------------------------
import services.email_service as es


def test_mail_config_prefers_resend(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "rk_test")
    monkeypatch.setenv("MAIL_FROM", "EPM <reports@epm-market-intelligence.com>")
    cfg = es._mail_config()
    assert cfg["provider"] == "resend"
    assert cfg["host"] == "smtp.resend.com"
    assert cfg["user"] == "resend"
    assert cfg["password"] == "rk_test"
    assert es.mail_configured() is True
    assert es.get_mail_from() == "EPM <reports@epm-market-intelligence.com>"


def test_mail_config_gmail_fallback(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("MAIL_FROM", raising=False)
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "gmpw")
    cfg = es._mail_config()
    assert cfg["provider"] == "gmail"
    assert cfg["host"] == "smtp.gmail.com"
    assert cfg["password"] == "gmpw"


def test_mail_not_configured_without_creds(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert es.mail_configured() is False


def test_send_raw_raises_without_creds(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(es.EmailError):
        es.send_raw(MIMEText("x"), ["a@b.com"])


def test_send_message_uses_configured_smtp(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "rk")
    captured = {}

    class FakeServer:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, pw):
            captured["login"] = (user, pw)

        def sendmail(self, frm, to, msg):
            captured["mail"] = (frm, to)

    monkeypatch.setattr(es.smtplib, "SMTP_SSL", lambda *a, **k: FakeServer())
    es.send_message("to@x.com", "subj", "<b>h</b>", "h")
    assert captured["login"][0] == "resend"
    assert captured["login"][1] == "rk"
    assert captured["mail"][1] == ["to@x.com"]


# ---------------------------------------------------------------------------
# auth_service — tokens + subscription state (needs bcrypt + PyJWT)
# ---------------------------------------------------------------------------
try:
    import services.auth_service as auth
except Exception as exc:  # pragma: no cover - env dependent
    auth = None
    _auth_skip = str(exc)

_need_auth = pytest.mark.skipif(auth is None, reason="auth deps unavailable")


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    db = tmp_path / "users.db"
    monkeypatch.setattr(auth, "DB_PATH", db)
    auth.init_db()
    return db


@_need_auth
def test_email_token_roundtrip():
    tok = auth.make_email_token(7, auth.EMAIL_PURPOSE_UNSUB)
    assert auth.verify_email_token(tok, auth.EMAIL_PURPOSE_UNSUB) == 7


@_need_auth
def test_email_token_wrong_purpose_rejected():
    tok = auth.make_email_token(7, auth.EMAIL_PURPOSE_CONFIRM)
    with pytest.raises(auth.AuthError):
        auth.verify_email_token(tok, auth.EMAIL_PURPOSE_UNSUB)


@_need_auth
def test_email_token_tampered_rejected():
    with pytest.raises(auth.AuthError):
        auth.verify_email_token("not.a.valid.token", auth.EMAIL_PURPOSE_UNSUB)


@_need_auth
def test_subscription_full_flow(temp_db):
    user = auth.register_user("alice", "password12345", "alice@x.com", email_opt_in=True)
    uid = user["id"]

    # Opted in but unconfirmed → NOT yet a recipient.
    sub = auth.get_email_subscription(uid)
    assert sub["email_opt_in"] is True and sub["email_confirmed"] is False
    assert all(s["user_id"] != uid for s in auth.get_confirmed_subscribers())

    # Confirm → becomes a recipient.
    auth.set_email_confirmed(uid, True)
    subs = auth.get_confirmed_subscribers()
    assert any(s["user_id"] == uid and s["email"] == "alice@x.com" for s in subs)

    # Unsubscribe → removed, but the confirmed flag is preserved for easy re-sub.
    auth.set_email_opt_in(uid, False)
    assert all(s["user_id"] != uid for s in auth.get_confirmed_subscribers())
    assert auth.get_email_subscription(uid)["email_confirmed"] is True


@_need_auth
def test_register_defaults_to_no_optin(temp_db):
    user = auth.register_user("bob", "password12345", "bob@x.com")
    assert auth.get_email_subscription(user["id"])["email_opt_in"] is False


# ---------------------------------------------------------------------------
# send_email — recipient assembly + fallback
# ---------------------------------------------------------------------------
try:
    import send_email as se
except Exception as exc:  # pragma: no cover - env dependent
    se = None

_need_se = pytest.mark.skipif(
    se is None or getattr(se, "requests", None) is None,
    reason="send_email import or requests unavailable",
)


@_need_se
def test_recipients_internal_only_without_key(monkeypatch):
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    recips = se.get_daily_recipients()
    assert len(recips) == 1
    assert recips[0]["email"] == se.TO
    assert recips[0]["unsubscribe_url"] is None


@_need_se
def test_recipients_merge_and_dedup(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"recipients": [
                {"email": "sub@x.com", "unsubscribe_url": "https://site/unsubscribe?t=abc"},
                {"email": se.TO, "unsubscribe_url": "dup"},  # duplicate of internal — must dedup
            ]}

    monkeypatch.setattr(se.requests, "get", lambda *a, **k: FakeResp())
    recips = se.get_daily_recipients()
    emails = [r["email"] for r in recips]
    assert "sub@x.com" in emails
    assert emails.count(se.TO) == 1


@_need_se
def test_recipients_fallback_on_server_error(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")

    def boom(*a, **k):
        raise RuntimeError("server down")

    monkeypatch.setattr(se.requests, "get", boom)
    recips = se.get_daily_recipients()
    assert len(recips) == 1 and recips[0]["email"] == se.TO


# ---------------------------------------------------------------------------
# app endpoints — failure paths (no DB mutation), needs fastapi + httpx
# ---------------------------------------------------------------------------
try:
    from fastapi.testclient import TestClient
    from app import app as _app
    _client = TestClient(_app)
except Exception as exc:  # pragma: no cover - env dependent
    _client = None

_need_app = pytest.mark.skipif(_client is None, reason="web app deps unavailable")


@_need_app
def test_internal_recipients_forbidden_without_key():
    # No/!wrong X-Internal-Key → 403, regardless of whether a key is configured.
    resp = _client.get("/api/internal/daily-recipients")
    assert resp.status_code == 403


@_need_app
def test_confirm_invalid_token_returns_400():
    resp = _client.get("/email/confirm?t=bogus")
    assert resp.status_code == 400


@_need_app
def test_unsubscribe_invalid_token_returns_400():
    resp = _client.get("/unsubscribe?t=bogus")
    assert resp.status_code == 400
