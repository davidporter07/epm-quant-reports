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

Previously the scheduler ran only step 1, so the site was never synced.

Designed for testability: the subprocess runner and the freshness checker are
injectable, so tests exercise the orchestration without sending email or deploying.

Exit codes:
  0  email sent (or already sent) AND site verified fresh
  1  report generation/email step failed — nothing deployed
  2  site is stale/unreachable after sync — investigate
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Tuple

ROOT = Path(__file__).resolve().parent
PY = sys.executable


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
        print(f"[run_daily] send_email.py exited {rc} — report not deployed. Aborting.")
        return 1

    # 2. Post-run tasks + sync to server. A sync hiccup is non-fatal here because
    #    the freshness check below is the real gate on whether the site is current.
    rc = runner([PY, "post_run.py"])
    if rc != 0:
        print(f"[run_daily] post_run.py exited {rc} — sync may be incomplete; verifying site...")

    # 3. Verify the public site actually reflects today's analysis.
    if args.skip_freshness:
        print("[run_daily] freshness check skipped by flag.")
        return 0

    if fresh_checker is None:
        from check_site_freshness import is_site_fresh
        fresh_checker = is_site_fresh

    fresh, detail = fresh_checker()
    if not fresh:
        print(f"[run_daily] LIVE SITE STALE: {detail}")
        print("[run_daily] The email may have gone out but the website is behind. "
              "Re-run `python post_run.py` and check the sync logs.")
        return 2

    print(f"[run_daily] OK — {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
