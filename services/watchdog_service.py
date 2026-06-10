"""watchdog_service.py — server-side staleness watchdog.

Runs as a daemon thread inside the web app. On each market day after the
configured cutoff (default 10:30 CST), checks whether data/latest_commentary.json
carries today's report_date. If not, sends ONE alert email to ALERT_EMAIL.

Controls:
  WATCHDOG_ENABLED=0       no-ops start_watchdog() (laptop dev runs)
  WATCHDOG_INTERVAL_SEC    poll interval in seconds (default 600)
  WATCHDOG_STALE_CUTOFF    HH:MM CST cutoff (default 10:30)
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, time as dtime, timezone
from pathlib import Path
from typing import Callable, Optional

try:
    from zoneinfo import ZoneInfo
    _CST = ZoneInfo("America/Chicago")
except Exception:
    _CST = None  # type: ignore[assignment]

_ROOT = Path(__file__).resolve().parent.parent
_COMMENTARY_PATH = _ROOT / "data" / "latest_commentary.json"

_DEFAULT_INTERVAL = 600
_DEFAULT_CUTOFF = dtime(10, 30)

_watchdog_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_last_alert_date: Optional[date] = None
_last_check_ts: Optional[str] = None


def _now_cst() -> datetime:
    if _CST is not None:
        return datetime.now(_CST)
    return datetime.utcnow().replace(tzinfo=timezone.utc)


def _is_market_open(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    try:
        import holidays as _hol
        return d not in _hol.US()
    except Exception:
        return True


def _load_report_date() -> Optional[str]:
    try:
        with _COMMENTARY_PATH.open(encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("report_date")
    except Exception:
        return None


def _parse_cutoff(s: str) -> dtime:
    try:
        h, m = s.split(":")
        return dtime(int(h), int(m))
    except Exception:
        return _DEFAULT_CUTOFF


def _should_alert(
    now: datetime,
    report_date: Optional[str],
    last_alert_date: Optional[date],
    *,
    cutoff: dtime = _DEFAULT_CUTOFF,
    is_market_open: Callable[[date], bool] = _is_market_open,
) -> bool:
    """Pure: True when a stale-report alert should fire."""
    today = now.date()
    if not is_market_open(today):
        return False
    if now.time().replace(tzinfo=None) < cutoff:
        return False
    if report_date == today.isoformat():
        return False
    if last_alert_date == today:
        return False
    return True


def _send_alert(report_date: Optional[str], alert_to: str) -> None:
    """Send the watchdog alert. Raises on failure (caller handles, no dedup)."""
    from services import email_service  # noqa: PLC0415
    date_str = _now_cst().strftime("%Y-%m-%d")
    subject = f"[EPM ALERT] daily report missing — {date_str}"
    body = (
        f"The EPM daily report has not been generated for {date_str}.\n\n"
        f"Last known report_date: {report_date or '(unknown)'}\n\n"
        f"Possible causes:\n"
        f"  • The laptop scheduler ('Send Quant Report') did not run\n"
        f"  • run_daily.py failed early (branch/dirty guard, email step)\n\n"
        f"Check: logs/run_daily.log and logs/run_daily_status.json"
    )
    html = f"<pre style='font-family:monospace;font-size:13px'>{body}</pre>"
    email_service.send_message(alert_to, subject, html, body)


def _run_tick(
    now: datetime,
    cutoff: dtime,
    *,
    load_fn: Callable[[], Optional[str]] = _load_report_date,
    send_fn: Callable[[Optional[str], str], None] = _send_alert,
) -> bool:
    """Execute one watchdog tick. Returns True if an alert was sent."""
    global _last_alert_date, _last_check_ts
    _last_check_ts = now.isoformat()
    report_date = load_fn()
    if not _should_alert(now, report_date, _last_alert_date, cutoff=cutoff):
        return False
    alert_to = os.getenv("ALERT_EMAIL", "").strip()
    if not alert_to:
        print("[watchdog] alert skipped: ALERT_EMAIL not set")
        return False
    from services import email_service  # noqa: PLC0415
    if not email_service.mail_configured():
        print("[watchdog] alert skipped: no mail creds configured")
        return False
    try:
        send_fn(report_date, alert_to)
        _last_alert_date = now.date()
        print(f"[watchdog] alert sent for {now.date()}")
        return True
    except Exception as exc:
        print(f"[watchdog] alert send failed: {exc}")
        return False  # no dedup — retry on next tick


def _watchdog_loop(
    *,
    interval: int,
    cutoff: dtime,
    now_fn: Callable[[], datetime] = _now_cst,
    load_fn: Callable[[], Optional[str]] = _load_report_date,
    send_fn: Callable[[Optional[str], str], None] = _send_alert,
) -> None:
    while not _stop_event.is_set():
        try:
            _run_tick(now_fn(), cutoff, load_fn=load_fn, send_fn=send_fn)
        except Exception as exc:
            print(f"[watchdog] loop error (continuing): {exc}")
        _stop_event.wait(timeout=interval)


def start_watchdog() -> None:
    global _watchdog_thread
    if os.getenv("WATCHDOG_ENABLED", "1") == "0":
        print("[watchdog] disabled by WATCHDOG_ENABLED=0")
        return
    interval = int(os.getenv("WATCHDOG_INTERVAL_SEC", str(_DEFAULT_INTERVAL)))
    cutoff = _parse_cutoff(os.getenv("WATCHDOG_STALE_CUTOFF", "10:30"))
    _stop_event.clear()
    _watchdog_thread = threading.Thread(
        target=_watchdog_loop,
        kwargs={"interval": interval, "cutoff": cutoff},
        name="watchdog",
        daemon=True,
    )
    _watchdog_thread.start()
    print(f"[watchdog] started (interval={interval}s, cutoff={cutoff})")


def stop_watchdog() -> None:
    _stop_event.set()


def watchdog_status() -> dict:
    return {
        "alive": bool(_watchdog_thread is not None and _watchdog_thread.is_alive()),
        "last_check_ts": _last_check_ts,
        "last_alert_date": _last_alert_date.isoformat() if _last_alert_date else None,
    }
