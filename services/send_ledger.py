"""Per-recipient send ledger and counts-only summary (PR E).

Tracks which recipients received the daily email so partial failures are
recoverable: a re-run only sends to recipients not yet marked ok.

Two artifacts:
  logs/email_send_ledger.json  — full per-recipient detail; LAPTOP-LOCAL ONLY
                                  (logs/ is never synced — subscriber addresses
                                  must never reach the server filesystem or
                                  the public health endpoint)
  data/email_send_summary.json — counts/booleans only; auto-syncs via data/
                                  SYNC_DIRS (PR D mechanism); NO email addresses

Design mirrors services/data_freshness.py:
  stdlib-only, injectable paths, never-raise writers, tmp→replace atomicity.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_BASE_DIR = Path(__file__).resolve().parent.parent
_LEDGER_PATH = _BASE_DIR / "logs" / "email_send_ledger.json"
_SUMMARY_PATH = _BASE_DIR / "data" / "email_send_summary.json"


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------

def _empty_ledger(today: str) -> dict:
    return {
        "date": today,
        "attempts": 0,
        "started_at": None,
        "finished_at": None,
        "fetch_ok": True,
        "pdf_ok": True,
        "recipients": {},
    }


def load_ledger(today: str, *, path: Optional[Path] = None) -> dict:
    """Load today's ledger from disk.

    Returns a fresh empty doc when the file is absent, belongs to a different
    day, or is malformed. Never raises.
    """
    p = Path(path) if path else _LEDGER_PATH
    try:
        raw = p.read_text(encoding="utf-8")
        doc = json.loads(raw)
        if not isinstance(doc, dict) or doc.get("date") != today:
            return _empty_ledger(today)
        # Ensure recipients key exists
        if "recipients" not in doc or not isinstance(doc["recipients"], dict):
            doc["recipients"] = {}
        return doc
    except Exception:
        return _empty_ledger(today)


def successful_recipients(ledger: dict) -> set:
    """Return the set of lowercased email addresses that were sent successfully."""
    return {
        email.lower()
        for email, rec in ledger.get("recipients", {}).items()
        if rec.get("ok") is True
    }


def record_attempt_start(ledger: dict, *, fetch_ok: bool, pdf_ok: bool) -> dict:
    """Increment attempt count and record fetch/pdf flags."""
    ledger = dict(ledger)
    ledger["attempts"] = ledger.get("attempts", 0) + 1
    ledger["started_at"] = datetime.now(timezone.utc).isoformat()
    ledger["fetch_ok"] = fetch_ok
    ledger["pdf_ok"] = pdf_ok
    return ledger


def record_result(
    ledger: dict,
    email: str,
    *,
    ok: bool,
    provider: Optional[str],
    error: Optional[str],
) -> dict:
    """Record one recipient's send result.

    A failure→success transition overwrites the previous entry so retries heal.
    Error strings are truncated to 200 chars to prevent unbounded growth.
    """
    ledger = dict(ledger)
    recipients = dict(ledger.get("recipients", {}))
    key = email.lower()
    existing = recipients.get(key, {})
    # Only overwrite a success with another success or a failure; never
    # overwrite a success with a failure (idempotent retry safety).
    if existing.get("ok") is True and not ok:
        ledger["recipients"] = recipients
        return ledger
    recipients[key] = {
        "ok": ok,
        "provider": provider,
        "error": (error or "")[:200] if not ok else None,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    ledger["recipients"] = recipients
    return ledger


def write_ledger(ledger: dict, *, path: Optional[Path] = None) -> None:
    """Persist the ledger atomically (tmp→replace). Never raises."""
    p = Path(path) if path else _LEDGER_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception as exc:
        print(f"[send_ledger][WARN] Could not write ledger: {exc}")


def write_summary(
    ledger: dict,
    *,
    internal_email: str,
    path: Optional[Path] = None,
) -> None:
    """Derive and persist the counts-only summary. Never raises.

    The summary MUST NOT contain any email addresses — it syncs to the server
    and is readable from the public /api/health endpoint.
    """
    p = Path(path) if path else _SUMMARY_PATH
    try:
        recipients = ledger.get("recipients", {})
        total = len(recipients)
        sent = sum(1 for r in recipients.values() if r.get("ok") is True)
        failed = total - sent
        internal_ok = recipients.get(
            internal_email.lower(), {}
        ).get("ok", False) if internal_email else False
        fallback_used = any(
            r.get("provider") == "gmail_fallback"
            for r in recipients.values()
        )
        summary = {
            "date": ledger.get("date"),
            "ts": datetime.now(timezone.utc).isoformat(),
            "attempts": ledger.get("attempts", 0),
            "total": total,
            "sent": sent,
            "failed": failed,
            "internal_ok": internal_ok,
            "fetch_ok": ledger.get("fetch_ok", True),
            "fallback_used": fallback_used,
            "pdf_ok": ledger.get("pdf_ok", True),
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception as exc:
        print(f"[send_ledger][WARN] Could not write summary: {exc}")
