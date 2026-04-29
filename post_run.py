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
SERVER_HOST = "192.168.1.145"
SERVER_PATH = "/opt/epm-market-intelligence"
SSH_KEY = str(Path.home() / ".ssh" / "epm_server")

SYNC_DIRS = ["charts", "commentary", "data", "epm-quant-reports", "static", "services", "feature_store", "config", "providers"]

# Individual Python files at root level that are part of the app
SYNC_PY_FILES = [
    "app.py",
    "fetch_enrichment.py",
    "generate_market_commentary.py",
    "monitor.py",
    "features.py",
    "fama_french.py",
    "data_arbiter.py",
    "feature_registry.py",
    "dl_feature_gate.py",
    "deep_analysis.py",
    "deep_analysis_worker.py",
    "local_council.py",
]


def run(cmd: list[str]) -> int:
    print("[>]", " ".join(cmd))
    try:
        return subprocess.call(cmd)
    except Exception as e:
        print(f"[WARN] Failed to run {cmd}: {e}")
        return 1


# Files that live on the server and must not be overwritten from local.
_SERVER_MANAGED = {"jwt_secret.key", "users.db"}


def _scp_dir(local: Path, remote: str, key_args: list[str]) -> int:
    """Copy contents of a local directory to a remote path via scp, skipping .git folders
    and any server-managed files that the server owns (e.g. jwt_secret.key, users.db)."""
    import tempfile, shutil
    dest_user_host, dest_path = remote.split(":", 1)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / local.name
        shutil.copytree(local, tmp_dir, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        # Drop server-managed files so scp never tries to overwrite them.
        for name in _SERVER_MANAGED:
            candidate = tmp_dir / name
            if candidate.exists():
                candidate.unlink()
        items = list(tmp_dir.iterdir())
        if not items:
            return 0
        cmd = ["scp", *key_args, "-r"] + [str(p) for p in items] + [f"{dest_user_host}:{dest_path}/"]
        return subprocess.call(cmd)


def sync_to_server():
    print("\n[SYNC] Pushing output to server...")
    dest = f"{SERVER_USER}@{SERVER_HOST}"
    key_args = ["-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", "-O"]
    errors = 0

    # Push directories
    for d in SYNC_DIRS:
        local = Path(d)
        if not local.exists():
            print(f"[SYNC] Skipping {d}/ (not found locally)")
            continue
        rc = _scp_dir(local, f"{dest}:{SERVER_PATH}/{d}", key_args)
        if rc == 0:
            print(f"[SYNC] {d}/ -> server [OK]")
        else:
            print(f"[SYNC] {d}/ -> server [FAILED]")
            errors += 1

    # Push individual Python files
    for fname in SYNC_PY_FILES:
        local = Path(fname)
        if not local.exists():
            continue
        rc = subprocess.call(["scp", *key_args, str(local), f"{dest}:{SERVER_PATH}/{fname}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if rc == 0:
            print(f"[SYNC] {fname} -> server [OK]")
        else:
            print(f"[SYNC] {fname} -> server [FAILED]")
            errors += 1

    if errors == 0:
        print("[SYNC] All directories synced successfully.")
    else:
        print(f"[SYNC] {errors} director(ies) failed to sync.")


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

    # Sync output to server
    sync_to_server()


if __name__ == "__main__":
    main()
