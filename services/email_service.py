"""
Transactional email service — password reset only.

Uses the same Gmail account and GMAIL_APP_PASSWORD env var as send_email.py,
but is completely isolated from it. No subprocess calls, no monitor.py,
no daily report pipeline. Import-safe.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

_FROM = "davidporter0731@gmail.com"
_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 465

_BASE_DIR = Path(__file__).resolve().parent.parent
_LOGO_PATH = _BASE_DIR / "epm_logo.png"


class EmailError(Exception):
    """Raised when an email cannot be sent."""


def _get_app_password() -> str:
    pw = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if not pw:
        raise EmailError(
            "GMAIL_APP_PASSWORD environment variable is not set. "
            "Password reset emails cannot be sent."
        )
    return pw


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

    msg = MIMEMultipart("alternative")
    msg["From"] = _FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, context=context) as server:
            server.login(_FROM, _get_app_password())
            server.sendmail(_FROM, to_email, msg.as_string())
    except EmailError:
        raise
    except Exception as exc:
        raise EmailError(f"Failed to send email: {exc}") from exc
