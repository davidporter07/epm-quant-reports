"""
Transactional + outbound email service.

Single send path for ALL outbound mail (password reset, daily-recap subscriber
sends, and pipeline failure alerts). Provider config is env-driven:

  - If RESEND_API_KEY is set → send via Resend SMTP (smtp.resend.com:465, user
    "resend"), From = MAIL_FROM (a verified sender on epm-market-intelligence.com).
  - Otherwise → fall back to the legacy Gmail app-password path
    (GMAIL_APP_PASSWORD), preserving the original behaviour so nothing breaks
    before the domain sender is provisioned.

Routing policy (2026-06-10):
  - Resend (domain sender) is reserved for OUTWARD-FACING product mail: the
    daily report and subscriber transactional mail (password reset, opt-in
    confirmation).
  - INTERNAL ops alerts (run_daily failure alerts, server watchdog) must pass
    provider="gmail" so they never consume the Resend domain sender.
  - The daily report's default send path gains a Gmail fallback: if the Resend
    SMTP send fails, the message is re-sent via Gmail (From rewritten) so the
    report still goes out.

Env vars (see .env.example):
  RESEND_API_KEY      Resend API key (acts as the SMTP password when present)
  MAIL_FROM           e.g. "EPM Market Intelligence <reports@epm-market-intelligence.com>"
  MAIL_SMTP_HOST      override (default smtp.resend.com or smtp.gmail.com)
  MAIL_SMTP_PORT      override (default 465)
  MAIL_SMTP_USER      override (default "resend" or the gmail address)
  GMAIL_APP_PASSWORD  legacy fallback password

Import-safe. No subprocess calls, no pipeline imports.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
from pathlib import Path

# Legacy default sender, used only when no MAIL_FROM is configured and we are on
# the Gmail fallback path.
_LEGACY_GMAIL_FROM = "davidporter0731@gmail.com"
_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 465

_BASE_DIR = Path(__file__).resolve().parent.parent
_LOGO_PATH = _BASE_DIR / "epm_logo.png"

# Load .env so RESEND_API_KEY / MAIL_FROM / INTERNAL_API_KEY etc. are available on
# the laptop, where send_email.py and run_daily.py do NOT otherwise load it (only
# GMAIL_APP_PASSWORD happened to be a real OS env var). override=False so genuine
# OS environment variables still win. Wrapped so a missing python-dotenv never
# breaks the import. On the server, app.py already loads .env first; this is a
# harmless no-op there.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_BASE_DIR / ".env", override=False)
except Exception:
    pass


class EmailError(Exception):
    """Raised when an email cannot be sent."""


def _get_app_password() -> str:
    """Legacy accessor kept for backwards compatibility / explicit Gmail use."""
    pw = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if not pw:
        raise EmailError(
            "GMAIL_APP_PASSWORD environment variable is not set. "
            "Password reset emails cannot be sent."
        )
    return pw


def _mail_config() -> dict:
    """Resolve the active SMTP provider config from the environment.

    Prefers Resend (domain sender) when RESEND_API_KEY is present; otherwise
    falls back to the legacy Gmail app-password path so existing deployments
    keep working until the domain sender is provisioned.
    """
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if api_key:
        return {
            "host": os.getenv("MAIL_SMTP_HOST", "smtp.resend.com"),
            "port": int(os.getenv("MAIL_SMTP_PORT", "465")),
            "user": os.getenv("MAIL_SMTP_USER", "resend"),
            "password": api_key,
            "from": os.getenv("MAIL_FROM", "").strip()
            or "EPM Market Intelligence <onboarding@resend.dev>",
            "provider": "resend",
        }
    # Legacy Gmail fallback
    return {
        "host": os.getenv("MAIL_SMTP_HOST", _SMTP_HOST),
        "port": int(os.getenv("MAIL_SMTP_PORT", str(_SMTP_PORT))),
        "user": os.getenv("MAIL_SMTP_USER", _LEGACY_GMAIL_FROM),
        "password": os.getenv("GMAIL_APP_PASSWORD", "").strip(),
        "from": os.getenv("MAIL_FROM", "").strip() or _LEGACY_GMAIL_FROM,
        "provider": "gmail",
    }


def _gmail_config() -> dict:
    """Gmail config for INTERNAL mail (ops alerts) and as the Resend fallback.

    Deliberately ignores the MAIL_SMTP_* overrides — those are scoped to the
    active (Resend) provider and would break a Gmail login if applied here.
    """
    user = os.getenv("GMAIL_USER", "").strip() or _LEGACY_GMAIL_FROM
    return {
        "host": _SMTP_HOST,
        "port": _SMTP_PORT,
        "user": user,
        "password": os.getenv("GMAIL_APP_PASSWORD", "").strip(),
        "from": user,
        "provider": "gmail",
    }


def mail_configured() -> bool:
    """True when outbound mail has working credentials (Resend or Gmail).

    Callers that must never break the run (e.g. failure alerting) check this
    before attempting a send.
    """
    return bool(_mail_config()["password"])


def gmail_configured() -> bool:
    """True when the internal Gmail path (alerts / Resend fallback) can send."""
    return bool(_gmail_config()["password"])


def get_mail_from() -> str:
    """The configured From header value (display-name form)."""
    return _mail_config()["from"]


def _envelope_addr(addr: str) -> str:
    """Bare email for the SMTP envelope, stripping any display name."""
    return parseaddr(addr)[1] or addr


def _set_from(msg, sender: str) -> None:
    """Replace the From header on a prebuilt MIME message."""
    if "From" in msg:
        del msg["From"]
    msg["From"] = sender


def _smtp_send(cfg: dict, sender: str, to_addrs: list[str], msg) -> None:
    """One SMTP_SSL send attempt against the given provider config."""
    envelope_from = _envelope_addr(sender)
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context) as server:
            server.login(cfg["user"], cfg["password"])
            server.sendmail(envelope_from, to_addrs, msg.as_string())
    except Exception as exc:
        raise EmailError(
            f"Failed to send email via {cfg['provider']}: {exc}"
        ) from exc


def send_raw(
    msg,
    to_addrs: list[str] | str,
    from_addr: str | None = None,
    provider: str | None = None,
) -> None:
    """Send a pre-built MIME message via the configured SMTP provider.

    Used by send_email.py, which builds a rich multipart/related message
    (inline logo + PDF attachment) and just needs the shared credentials.

    provider:
      - None (default): env-driven (Resend when RESEND_API_KEY is set). If the
        Resend send FAILS and Gmail creds exist, the message is re-sent via
        Gmail with the From header rewritten — the daily report must go out.
      - "gmail": internal-only path (ops alerts). Never touches Resend.
    """
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]

    if provider == "gmail":
        gmail = _gmail_config()
        if not gmail["password"]:
            raise EmailError(
                "GMAIL_APP_PASSWORD is not set — internal (Gmail) mail cannot be sent."
            )
        sender = from_addr or gmail["from"]
        _set_from(msg, sender)
        _smtp_send(gmail, sender, to_addrs, msg)
        return

    cfg = _mail_config()
    if not cfg["password"]:
        raise EmailError(
            "No mail credentials configured (set RESEND_API_KEY or GMAIL_APP_PASSWORD)."
        )
    sender = from_addr or cfg["from"]
    try:
        _smtp_send(cfg, sender, to_addrs, msg)
        return
    except EmailError as exc:
        if cfg["provider"] != "resend":
            raise
        gmail = _gmail_config()
        if not gmail["password"]:
            raise
        print(f"[mail][WARN] Resend send failed: {exc}")
        print("[mail][WARN] Falling back to Gmail — investigate Resend before the next run.")
        _set_from(msg, gmail["from"])
        try:
            _smtp_send(gmail, gmail["from"], to_addrs, msg)
            print(f"[mail][WARN] Sent via Gmail fallback to {len(to_addrs)} recipient(s).")
        except EmailError as exc2:
            raise EmailError(
                f"Resend failed ({exc}); Gmail fallback also failed ({exc2})"
            ) from exc2


def send_message(
    to_email: str,
    subject: str,
    html: str,
    plain: str,
    headers: dict | None = None,
    from_addr: str | None = None,
    provider: str | None = None,
) -> None:
    """Send a simple multipart/alternative email via the configured provider.

    Used for password-reset and double-opt-in confirmation (default provider)
    and for internal ops alerts (provider="gmail" — never via Resend).
    """
    if provider == "gmail":
        default_from = _gmail_config()["from"]
    else:
        default_from = get_mail_from()
    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr or default_from
    msg["To"] = to_email
    msg["Subject"] = subject
    for key, value in (headers or {}).items():
        msg[key] = value
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    send_raw(msg, [to_email], from_addr=msg["From"], provider=provider)


def send_password_reset_email(to_email: str, username: str, reset_url: str) -> None:
    """
    Send a password reset link to the given email address.

    Args:
        to_email:  Recipient email address.
        username:  Their username, used in the greeting.
        reset_url: The full reset link, e.g. http://192.168.1.133:8000/reset-password?token=abc
    """
    subject = "EPM Market Intelligence — Password Reset Request"

    html = f"""
    <html>
    <body style="font-family:Inter,system-ui,sans-serif;background:#f5f8fd;margin:0;padding:0;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f8fd;padding:40px 20px;">
        <tr><td align="center">
          <table width="520" cellpadding="0" cellspacing="0"
                 style="background:#ffffff;border-radius:16px;border:1px solid #dfe6f0;
                        box-shadow:0 4px 24px rgba(0,0,0,0.07);overflow:hidden;">

            <!-- Header -->
            <tr>
              <td style="background:#061326;padding:28px 36px;text-align:left;">
                <span style="color:#c8a84b;font-size:13px;font-weight:700;
                             letter-spacing:0.08em;text-transform:uppercase;">
                  EPM Market Intelligence
                </span>
              </td>
            </tr>

            <!-- Body -->
            <tr>
              <td style="padding:36px 36px 28px;">
                <h2 style="margin:0 0 12px;font-size:22px;color:#0d1c2e;font-weight:700;">
                  Reset your password
                </h2>
                <p style="margin:0 0 10px;color:#3a5070;font-size:15px;line-height:1.6;">
                  Hi <strong>{username}</strong>,
                </p>
                <p style="margin:0 0 24px;color:#3a5070;font-size:15px;line-height:1.6;">
                  We received a request to reset your password. Click the button below to
                  choose a new one. This link expires in <strong>1 hour</strong>.
                </p>

                <!-- CTA Button -->
                <table cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
                  <tr>
                    <td style="border-radius:10px;background:linear-gradient(135deg,#1d4ed8,#3b82f6);">
                      <a href="{reset_url}"
                         style="display:inline-block;padding:14px 32px;color:#fff;
                                font-size:15px;font-weight:600;text-decoration:none;
                                border-radius:10px;letter-spacing:0.01em;">
                        Reset Password
                      </a>
                    </td>
                  </tr>
                </table>

                <p style="margin:0 0 6px;color:#7a94b4;font-size:13px;line-height:1.5;">
                  If the button doesn't work, copy and paste this link into your browser:
                </p>
                <p style="margin:0 0 24px;font-size:12px;color:#3b82f6;word-break:break-all;">
                  <a href="{reset_url}" style="color:#3b82f6;">{reset_url}</a>
                </p>

                <hr style="border:none;border-top:1px solid #e8eef6;margin:0 0 20px;" />

                <p style="margin:0;color:#b0bcd0;font-size:12px;line-height:1.5;">
                  If you didn't request a password reset, you can safely ignore this email.
                  Your password will not change. This link will expire automatically in 1 hour.
                </p>
              </td>
            </tr>

            <!-- Footer -->
            <tr>
              <td style="background:#f5f8fd;padding:16px 36px;
                         border-top:1px solid #e8eef6;text-align:left;">
                <span style="color:#b0bcd0;font-size:11px;">
                  EPM Financial &mdash; internal research platform
                </span>
              </td>
            </tr>

          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """

    plain = (
        f"Hi {username},\n\n"
        f"We received a request to reset your EPM Market Intelligence password.\n\n"
        f"Reset your password here (link expires in 1 hour):\n{reset_url}\n\n"
        f"If you didn't request this, you can safely ignore this email.\n\n"
        f"— EPM Financial"
    )

    send_message(to_email, subject, html, plain)


def send_subscription_confirmation_email(to_email: str, username: str, confirm_url: str) -> None:
    """Double-opt-in: confirm the user controls this address before any daily
    recap is sent to it."""
    subject = "Confirm your EPM Market Intelligence daily email"

    html = f"""
    <html>
    <body style="font-family:Inter,system-ui,sans-serif;background:#f5f8fd;margin:0;padding:0;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f8fd;padding:40px 20px;">
        <tr><td align="center">
          <table width="520" cellpadding="0" cellspacing="0"
                 style="background:#ffffff;border-radius:16px;border:1px solid #dfe6f0;
                        box-shadow:0 4px 24px rgba(0,0,0,0.07);overflow:hidden;">
            <tr>
              <td style="background:#061326;padding:28px 36px;text-align:left;">
                <span style="color:#c8a84b;font-size:13px;font-weight:700;
                             letter-spacing:0.08em;text-transform:uppercase;">
                  EPM Market Intelligence
                </span>
              </td>
            </tr>
            <tr>
              <td style="padding:36px 36px 28px;">
                <h2 style="margin:0 0 12px;font-size:22px;color:#0d1c2e;font-weight:700;">
                  Confirm your subscription
                </h2>
                <p style="margin:0 0 10px;color:#3a5070;font-size:15px;line-height:1.6;">
                  Hi <strong>{username}</strong>,
                </p>
                <p style="margin:0 0 24px;color:#3a5070;font-size:15px;line-height:1.6;">
                  Confirm this address to start receiving the EPM daily market recap.
                  You can unsubscribe at any time from the footer of any email or your profile.
                </p>
                <table cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
                  <tr>
                    <td style="border-radius:10px;background:linear-gradient(135deg,#1d4ed8,#3b82f6);">
                      <a href="{confirm_url}"
                         style="display:inline-block;padding:14px 32px;color:#fff;
                                font-size:15px;font-weight:600;text-decoration:none;
                                border-radius:10px;letter-spacing:0.01em;">
                        Confirm Subscription
                      </a>
                    </td>
                  </tr>
                </table>
                <p style="margin:0 0 6px;color:#7a94b4;font-size:13px;line-height:1.5;">
                  If the button doesn't work, paste this link into your browser:
                </p>
                <p style="margin:0 0 24px;font-size:12px;color:#3b82f6;word-break:break-all;">
                  <a href="{confirm_url}" style="color:#3b82f6;">{confirm_url}</a>
                </p>
                <hr style="border:none;border-top:1px solid #e8eef6;margin:0 0 20px;" />
                <p style="margin:0;color:#b0bcd0;font-size:12px;line-height:1.5;">
                  If you didn't request this, you can safely ignore this email — no emails
                  will be sent unless you confirm.
                </p>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """

    plain = (
        f"Hi {username},\n\n"
        f"Confirm your subscription to the EPM Market Intelligence daily recap:\n"
        f"{confirm_url}\n\n"
        f"If you didn't request this, you can safely ignore this email.\n\n"
        f"— EPM Financial"
    )

    send_message(to_email, subject, html, plain)
