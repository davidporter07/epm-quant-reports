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
  3  wrong branch — refused to run (working tree not on the pipeline branch)
  4  dirty working tree — refused to run (uncommitted deployable code changes)
  5  deploy step failed (sync/restart/health) — email sent but server may run old code
"""
from __future__ import annotations

import argparse
import json
import os
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

# The scheduler ("Send Quant Report" task) runs this from D:\fund_monitor with
# whatever branch happens to be checked out. Research branches (e.g. growth24/*)
# carry stale pipeline code, so running from one silently ships a regressed report
# — this bit us on 2026-06-05 (the market-mover spotlight + gold/Fed fix were on
# main but the tree was left on growth24/research-salvage, 45 commits behind). The
# guard below turns that silent regression into a loud, logged refusal.
PIPELINE_BRANCH = "main"


def _current_branch() -> str:
    """Branch the working tree is on, or '' if it can't be determined (never raises)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # pragma: no cover - defensive
        return ""


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
    try:
        # Importing the mailer also loads .env, so ALERT_EMAIL/creds are populated
        # even though run_daily itself never calls load_dotenv.
        from services import email_service
        alert_to = os.getenv("ALERT_EMAIL", "").strip()
        if not alert_to:
            return
        # Internal alerts go via Gmail only — Resend is reserved for the
        # daily report / subscriber mail.
        if not email_service.gmail_configured():
            print("[run_daily] (alert skipped: GMAIL_APP_PASSWORD not configured)")
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
        email_service.send_message(alert_to, subject, html, body, provider="gmail")
        print(f"[run_daily] alert email sent to {alert_to}")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[run_daily] (alert email failed: {exc})")


def _push_status() -> None:
    """Push logs/run_daily_status.json to the server so /api/health can read it.
    Never raises — must not change exit codes."""
    try:
        from post_run import push_status_file
        push_status_file()
    except Exception as exc:
        print(f"[run_daily] (status push failed: {exc})")


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
    branch_checker: Optional[Callable[[], str]] = None,
    dirty_checker: Optional[Callable[[], list[str]]] = None,
) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-freshness", action="store_true",
                    help="Skip the post-deploy live-site freshness check.")
    ap.add_argument("--allow-branch", action="store_true",
                    help=f"Bypass the {PIPELINE_BRANCH!r}-branch guard (intentional "
                         f"manual run from a feature/research branch).")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="Bypass the dirty-code guard (run with uncommitted changes).")
    args = ap.parse_args(argv)

    runner = runner or _default_runner

    # 0. Branch guard — refuse to ship from a non-pipeline branch (see PIPELINE_BRANCH
    #    note above). Inert under pytest unless a branch_checker is injected, so the
    #    existing suite is unaffected while the behaviour stays unit-testable.
    if not args.allow_branch:
        checker = branch_checker or (
            None if "PYTEST_CURRENT_TEST" in os.environ else _current_branch
        )
        if checker is not None:
            branch = checker()
            if branch and branch != PIPELINE_BRANCH:
                msg = (f"REFUSING TO RUN: working tree is on branch '{branch}', not "
                       f"'{PIPELINE_BRANCH}'. The daily pipeline must run from "
                       f"'{PIPELINE_BRANCH}' so it ships current code, not stale code "
                       f"from a research branch. Switch back (git checkout "
                       f"{PIPELINE_BRANCH}) or run research in a separate git worktree. "
                       f"Nothing was generated or deployed. "
                       f"(Override: run_daily.py --allow-branch.)")
                print(f"[run_daily] {msg}")
                _record_status("branch_guard", False, msg)
                _push_status()
                _send_alert("branch_guard", msg)
                return 3

    # 0b. Dirty-code guard — refuse to ship uncommitted deployable code changes.
    #     Inert under pytest unless dirty_checker is injected (mirrors branch guard).
    from post_run import _ALLOW_DIRTY_ENV, _git_dirty_code_paths
    if args.allow_dirty:
        os.environ[_ALLOW_DIRTY_ENV] = "1"
    else:
        dirty_fn = dirty_checker or (
            None if "PYTEST_CURRENT_TEST" in os.environ else _git_dirty_code_paths
        )
        if dirty_fn is not None:
            dirty = dirty_fn()
            if dirty:
                msg = (
                    f"REFUSING TO RUN: {len(dirty)} deployable code file(s) have "
                    f"uncommitted changes: {', '.join(dirty[:5])}"
                    + ("..." if len(dirty) > 5 else "")
                    + ". Commit or stash, or override with --allow-dirty."
                )
                print(f"[run_daily] {msg}")
                _record_status("dirty_guard", False, msg)
                _push_status()
                _send_alert("dirty_guard", msg)
                return 4

    # Per-stage timing (informational; never affects the run). Defensive import so
    # a missing module degrades to no-ops rather than breaking the daily pipeline.
    try:
        from services.stage_timer import stage_mark, stage_reset
    except Exception:
        def stage_mark(_n): pass
        def stage_reset(_l=""): pass
    stage_reset("run_daily.py")

    # 1. Generate + email. send_email.py owns the freshness GATE that blocks stale
    #    or non-LLM reports, so a non-zero exit here means we must NOT deploy —
    #    except exit 6 (EXIT_PARTIAL_SEND): partial sends still deploy so the site
    #    is live for subscribers who DID receive the email.
    rc = runner([PY, "send_email.py"])
    if rc == 6:  # EXIT_PARTIAL_SEND — deploy proceeds, health check carries the degradation
        msg = (
            "send_email.py reported PARTIAL send (exit 6) — "
            "see logs/email_send_ledger.json for failed recipients; deploying anyway."
        )
        print(f"[run_daily] [WARN] {msg}")
        _record_status("send_email_partial", True, msg)
        _send_alert("send_email_partial", msg)
    elif rc != 0:
        msg = f"send_email.py exited {rc} — report not deployed. Aborting."
        print(f"[run_daily] {msg}")
        _record_status("send_email", False, msg)
        _push_status()
        _send_alert("send_email", msg)
        return 1

    stage_mark("send_email.py + monitor.py (gen + send)")
    # 2. Post-run tasks + sync to server. A non-zero exit means the deploy itself
    #    failed (dirty guard, transfer error, restart failure, or health probe). We
    #    still run the freshness check so the operator sees content state too, but
    #    exit 5 surfaces the deploy failure even when content happens to be fresh.
    rc = runner([PY, "post_run.py"])
    post_run_warn = ""
    if rc != 0:
        post_run_warn = f"post_run.py exited {rc} — deploy may be incomplete; verifying site..."
        print(f"[run_daily] {post_run_warn}")
        _record_status("post_run", False, post_run_warn)
        _send_alert("post_run", post_run_warn)

    stage_mark("post_run.py (DL inference + sync)")
    # 3. Verify the public site actually reflects today's analysis.
    if args.skip_freshness:
        print("[run_daily] freshness check skipped by flag.")
        _record_status("ok" if not post_run_warn else "post_run", not bool(post_run_warn),
                       "freshness check skipped by flag" +
                       (f" ({post_run_warn})" if post_run_warn else ""))
        _push_status()
        return 5 if post_run_warn else 0

    if fresh_checker is None:
        from check_site_freshness import is_site_fresh
        fresh_checker = is_site_fresh

    fresh, detail = fresh_checker()
    if not fresh:
        msg = (f"LIVE SITE STALE: {detail}. The email may have gone out but the "
               f"website is behind. Re-run `python post_run.py` and check sync logs.")
        print(f"[run_daily] {msg}")
        _record_status("freshness", False, msg)
        _push_status()
        _send_alert("freshness", msg)
        return 2

    ok_detail = detail + (f" (warning: {post_run_warn})" if post_run_warn else "")
    print(f"[run_daily] OK — {ok_detail}")
    if post_run_warn:
        _record_status("post_run", False, ok_detail)
        _push_status()
        return 5
    _record_status("ok", True, ok_detail)
    _push_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
