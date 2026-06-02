"""run_daily.py — the single entry point the scheduler should call.

Chains the daily flow with proper success-gating so the live website can never
silently fall behind the email:

  1. send_email.py   — regenerates the report (runs monitor.py), applies the
                       existing freshness gate, and emails it. If this fails or
                       is blocked as stale, we STOP — we never deploy a bad report.
  2. post_run.py     — DL inference, prediction logging, and sync_to_server().
                       This is the step that was previously NOT scheduled, which
                       is why the public site went stale.
  3. freshness check — verify the LIVE site now serves today's analysis. If not,
                       exit non-zero so the scheduler/alerting surfaces it.

Observability: every terminal outcome is written to logs/run_daily_status.json
(structured) and appended to logs/run_daily.log (one line per run). /api/health and
an operator can read the status file to see the last run's result without scraping
stdout. On a hard failure (report/email step or post-sync site staleness) a short
alert email is also sent to ALERT_EMAIL via the shared mailer — guarded on creds
being present and wrapped so alerting can never break the run.

Designed for testability: the subprocess runner and the freshness checker are
injectable, so tests exercise the orchestration without sending email or deploying.

Exit codes:
  0  email sent (or already sent) AND site verified fresh
  1  report generation/email step failed — nothing deployed
  2  site is stale/unreachable after sync — investigate
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Tuple

ROOT = Path(__file__).resolve().parent
PY = sys.executable
LOGS_DIR = ROOT / "logs"
STATUS_FILE = LOGS_DIR / "run_daily_status.json"
MARKER_LOG = LOGS_DIR / "run_daily.log"


def _record_status(stage: str, ok: bool, detail: str, *, status_file: Path = STATUS_FILE) -> None:
    """Write a structured status file + append a marker line. Never raises — alerting
    must not break the run. `stage` is one of: send_email | post_run | freshness | ok.
    """
    try:
        status_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "ok": ok,
            "detail": detail,
        }
        tmp = status_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(status_file)
        with (status_file.parent / "run_daily.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{payload['ts']} [{'OK' if ok else 'FAIL'}] {stage}: {detail}\n")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[run_daily] (status write failed: {exc})")


def _send_alert(stage: str, detail: str) -> None:
    """Email a short failure alert to ALERT_EMAIL. Never raises — alerting must
    not break the run. No-ops silently if no mail creds are configured."""
    import os
    alert_to = os.getenv("ALERT_EMAIL", "").strip()
    if not alert_to:
        return
    try:
        from services import email_service
        if not email_service.mail_configured():
            print("[run_daily] (alert skipped: no mail creds configured)")
            return
        subject = f"[EPM ALERT] daily run failed at '{stage}'"
        body = (
            f"The EPM daily pipeline failed.\n\n"
            f"Stage: {stage}\n"
            f"Detail: {detail}\n"
            f"Time: {datetime.now(timezone.utc).isoformat()}\n\n"
            f"Check logs/run_daily.log and logs/run_daily_status.json."
        )
        html = f"<pre style='font-family:monospace;font-size:13px'>{body}</pre>"
        email_service.send_message(alert_to, subject, html, body)
        print(f"[run_daily] alert email sent to {alert_to}")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[run_daily] (alert email failed: {exc})")


def _default_runner(cmd: list[str]) -> int:
    print("[run_daily] >", " ".join(cmd))
    try:
        return subprocess.call(cmd, cwd=str(ROOT))
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[run_daily] command failed to launch: {exc}")
        return 1


def main(
    argv=None,
    *,
    runner: Optional[Callable[[list[str]], int]] = None,
    fresh_checker: Optional[Callable[[], Tuple[bool, str]]] = None,
) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-freshness", action="store_true",
                    help="Skip the post-deploy live-site freshness check.")
    args = ap.parse_args(argv)

    runner = runner or _default_runner

    # 1. Generate + email. send_email.py owns the freshness GATE that blocks stale
    #    or non-LLM reports, so a non-zero exit here means we must NOT deploy.
    rc = runner([PY, "send_email.py"])
    if rc != 0:
        msg = f"send_email.py exited {rc} — report not deployed. Aborting."
        print(f"[run_daily] {msg}")
        _record_status("send_email", False, msg)
        _send_alert("send_email", msg)
        return 1

    # 2. Post-run tasks + sync to server. A sync hiccup is non-fatal here because
    #    the freshness check below is the real gate on whether the site is current.
    rc = runner([PY, "post_run.py"])
    post_run_warn = ""
    if rc != 0:
        post_run_warn = f"post_run.py exited {rc} — sync may be incomplete; verifying site..."
        print(f"[run_daily] {post_run_warn}")

    # 3. Verify the public site actually reflects today's analysis.
    if args.skip_freshness:
        print("[run_daily] freshness check skipped by flag.")
        _record_status("ok", True, "freshness check skipped by flag" +
                       (f" ({post_run_warn})" if post_run_warn else ""))
        return 0

    if fresh_checker is None:
        from check_site_freshness import is_site_fresh
        fresh_checker = is_site_fresh

    fresh, detail = fresh_checker()
    if not fresh:
        msg = (f"LIVE SITE STALE: {detail}. The email may have gone out but the "
               f"website is behind. Re-run `python post_run.py` and check sync logs.")
        print(f"[run_daily] {msg}")
        _record_status("freshness", False, msg)
        _send_alert("freshness", msg)
        return 2

    ok_detail = detail + (f" (warning: {post_run_warn})" if post_run_warn else "")
    print(f"[run_daily] OK — {ok_detail}")
    _record_status("ok", True, ok_detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
