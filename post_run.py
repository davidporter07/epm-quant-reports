"""post_run.py

One command to run after your daily pipeline (or after monitor.py):
- If a PyTorch DL model exists, run DL inference (MAG7 by default).
- Append today's forecasts into data/prediction_log.parquet.

Usage
-----
python post_run.py

Optional
--------
python post_run.py --tickers AAPL,MSFT,...
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')


MAG7_DEFAULT = "AAPL,MSFT,AMZN,NVDA,GOOG,META,TSLA"

SERVER_USER = "dporter02"
SERVER_HOST = "100.101.63.65"
SERVER_PATH = "/opt/epm-market-intelligence"
SSH_KEY = str(Path.home() / ".ssh" / "epm_server")

SYNC_DIRS = ["charts", "commentary", "data", "epm-quant-reports", "static", "services", "feature_store", "config", "providers"]

# Individual Python files at root level that are part of the app
SYNC_PY_FILES = [
    "app.py",
    "fetch_enrichment.py",
    "generate_market_commentary.py",
    "generate_pdf_report.py",
    "send_email.py",
    "monitor.py",
    "features.py",
    "fama_french.py",
    "data_arbiter.py",
    "feature_registry.py",
    "dl_feature_gate.py",
    "deep_analysis.py",
    "deep_analysis_worker.py",
    "earnings_calendar.py",
    "earnings_refresh.py",
    "local_council.py",
    "pm_research.py",
]


def run(cmd: list[str]) -> int:
    print("[>]", " ".join(cmd))
    try:
        return subprocess.call(cmd)
    except Exception as e:
        print(f"[WARN] Failed to run {cmd}: {e}")
        return 1


# Files that live on the server and must not be overwritten from local.
_SERVER_MANAGED = {"jwt_secret.key", "users.db", "earnings_calendar.json", "research_cache.db"}

# Directories that the SERVER owns and the laptop must never push up. data/jobs/
# is the live deep-analysis queue written by the web worker; pushing stale local
# job files would resurrect old/cancelled jobs and corrupt queue state.
_SERVER_OWNED_DIRS = {"jobs"}

# Local-only research/cache directories the live web app never reads. Excluding
# them keeps the sync fast AND avoids Windows MAX_PATH (260-char) copytree errors
# on the deeply-nested DL experiment outputs (data/experiment/.../growth24_*/...).
_LOCAL_ONLY_DIRS = {"experiment", "qlora_training", ".yfinance_cache", "commentary_archive"}

_SYNC_EXCLUDE_DIRS = _SERVER_OWNED_DIRS | _LOCAL_ONLY_DIRS


def _scp_dir_names(local: Path) -> list[str]:
    """Top-level entries of `local` to sync, with server-owned/local-only dirs and
    server-managed files excluded by name. Pure + deterministic so it can be tested
    without touching the network or the filesystem layout of the remote."""
    return [
        p.name for p in sorted(local.iterdir())
        if p.name not in _SYNC_EXCLUDE_DIRS
        and p.name not in _SERVER_MANAGED
        and p.name not in (".git", "__pycache__")
    ]


def _scp_dir(local: Path, remote: str, key_args: list[str]) -> int:
    """Copy a local directory's top-level entries to a remote path via scp.

    Runs scp from cwd=local and passes RELATIVE names. This avoids two Windows
    failure modes the previous temp-copytree approach hit:
      - absolute paths like 'C:\\Users\\...\\file' were handed to scp, which parses
        the leading 'C:' as 'host:path' and silently failed to transfer the file
        (this is why operational data/ files stopped syncing);
      - shutil.copytree blew the 260-char MAX_PATH limit on deep experiment dirs
        (data/experiment/.../growth24_*), aborting the entire sync.
    Server-owned/local-only dirs and server-managed files are excluded by name.
    """
    names = _scp_dir_names(local)
    if not names:
        return 0
    dest = remote if remote.endswith("/") else remote + "/"
    cmd = ["scp", *key_args, "-r", *names, dest]
    try:
        # cwd=local => scp receives bare relative names (no drive-letter colon).
        return subprocess.run(cmd, cwd=str(local), timeout=300).returncode
    except subprocess.TimeoutExpired:
        print(f"[WARN] scp timed out after 300s for {local} — skipping")
        return 1


def sync_to_server() -> bool:
    """Push outputs + app files to the server. Returns True only if EVERY transfer
    succeeded. Previously this returned None unconditionally, so a total failure (e.g.
    the server offline — every scp times out) looked identical to success and the
    deploy silently no-op'd. Now it tallies successes and shouts on any failure."""
    print("\n[SYNC] Pushing output to server...")
    dest = f"{SERVER_USER}@{SERVER_HOST}"
    key_args = ["-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=20", "-O"]
    errors = 0
    ok = 0

    # Push directories
    for d in SYNC_DIRS:
        local = Path(d)
        if not local.exists():
            print(f"[SYNC] Skipping {d}/ (not found locally)")
            continue
        rc = _scp_dir(local, f"{dest}:{SERVER_PATH}/{d}", key_args)
        if rc == 0:
            print(f"[SYNC] {d}/ -> server [OK]")
            ok += 1
        else:
            print(f"[SYNC] {d}/ -> server [FAILED]")
            errors += 1

    # Push individual Python files
    for fname in SYNC_PY_FILES:
        local = Path(fname)
        if not local.exists():
            continue
        try:
            rc = subprocess.run(["scp", *key_args, str(local), f"{dest}:{SERVER_PATH}/{fname}"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60).returncode
        except subprocess.TimeoutExpired:
            rc = 1
        if rc == 0:
            print(f"[SYNC] {fname} -> server [OK]")
            ok += 1
        else:
            print(f"[SYNC] {fname} -> server [FAILED]")
            errors += 1

    if errors == 0:
        print(f"[SYNC] All {ok} target(s) synced successfully.")
        return True

    # Failure path — make it impossible to miss (this masked the 2026-06-02 offline deploy).
    print("  " + "!" * 64)
    if ok == 0:
        print(f"  [SYNC][FAILED] ALL {errors} transfer(s) failed — the server is UNREACHABLE.")
        print("  NOTHING was deployed. Check the network / Tailscale and that epm-server is online,")
        print("  then re-run the sync. Do NOT assume the deploy succeeded.")
    else:
        print(f"  [SYNC][PARTIAL] {errors} of {ok + errors} transfer(s) FAILED — deploy is INCOMPLETE.")
    print("  " + "!" * 64)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=str, default=MAG7_DEFAULT)
    ap.add_argument("--skip-dl", action="store_true", help="Skip deep learning inference")
    args = ap.parse_args()

    py = sys.executable

    # DL inference (only if trained model exists)
    model_path = Path("models") / "dl_tcn.pt"
    scaler_path = Path("models") / "dl_scaler.json"
    if not args.skip_dl:
        if model_path.exists() and scaler_path.exists():
            rc = run([py, "deep_learning_model.py", "infer", "--tickers", args.tickers])
            if rc != 0:
                print(" DL inference returned non-zero exit code. Continuing to logging.")
        else:
            print(" DL model not found (models/dl_tcn.pt + models/dl_scaler.json). Skipping DL inference.")

    # Log today's forecasts
    if Path("record_predictions.py").exists():
        rc = run([py, "record_predictions.py"])
        if rc != 0:
            print("[WARN] record_predictions.py failed. Fix this before relying on live backtests.")
    else:
        print("[WARN] record_predictions.py not found. Copy it into the project to enable live backtesting.")

    # Feature drift monitoring (daily check on approved feature distributions)
    if Path("feature_drift_monitor.py").exists():
        rc = run([py, "feature_drift_monitor.py"])
        if rc != 0:
            print("[WARN] feature_drift_monitor.py failed. Check feature_store/dashboard/ manually.")

    # Regenerate internal feature dashboard
    if Path("feature_dashboard_gen.py").exists():
        rc = run([py, "feature_dashboard_gen.py"])
        if rc != 0:
            print("[WARN] feature_dashboard_gen.py failed.")

    # Refresh earnings calendar for watched tickers
    try:
        from earnings_calendar import refresh_expired
        refreshed = refresh_expired()
        if refreshed:
            print(f"[earnings_calendar] Refreshed {len(refreshed)} ticker(s): {', '.join(refreshed)}")
        else:
            print("[earnings_calendar] All watched ticker dates are current.")
    except Exception as e:
        print(f"[WARN] earnings_calendar refresh failed: {e}")

    # Archive today's commentary for future QLoRA training data
    _src = Path("data") / "latest_commentary.json"
    if _src.exists():
        try:
            import json as _json
            _c = _json.loads(_src.read_text(encoding="utf-8"))
            _date_key = _c.get("report_date") or _c.get("narrative_source_date") or ""
            if not _date_key:
                from datetime import date as _dt
                _date_key = _dt.today().isoformat()
            _archive_dir = Path("data") / "commentary_archive"
            _archive_dir.mkdir(exist_ok=True)
            _dest = _archive_dir / f"{_date_key}.json"
            if not _dest.exists():
                _dest.write_text(_src.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"[commentary_archive] Archived {_date_key}.json")
            else:
                print(f"[commentary_archive] {_date_key}.json already exists, skipping.")
        except Exception as _e:
            print(f"[WARN] Commentary archive failed: {_e}")

    # Sync output to server — surface a failed deploy loudly (non-zero exit) instead of
    # silently "succeeding" while nothing transferred.
    if not sync_to_server():
        print("[post_run] Server sync FAILED — see banner above. Outputs are NOT deployed.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
