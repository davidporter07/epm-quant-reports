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
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')


_MAG7_FALLBACK = "AAPL,MSFT,AMZN,NVDA,GOOG,META,TSLA"


def _default_infer_tickers() -> str:
    """Inference universe: MAG7 + any publicly-traded MANGOS members.

    Config-driven (config/portfolio_funds.json). MANGOS names self-gate in
    deep_learning_model.infer_live (skipped until they have enough panel history),
    so adding them here is safe before they accumulate data. Pending-IPO MANGOS
    members are excluded by get_mangos_active_tickers(). Falls back to a hardcoded
    MAG7 string if the config import fails, matching the defensive pattern used
    elsewhere in the pipeline.
    """
    try:
        from universe_config import get_mag7, get_mangos_active_tickers
        tickers = list(get_mag7()) + list(get_mangos_active_tickers())
        seen: set[str] = set()
        ordered = [t for t in tickers if not (t in seen or seen.add(t))]
        return ",".join(ordered) if ordered else _MAG7_FALLBACK
    except Exception as e:
        print(f" Could not load tickers from config ({e}). Using MAG7 fallback.")
        return _MAG7_FALLBACK


MAG7_DEFAULT = _default_infer_tickers()

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
    "market_movers.py",
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
    "council_roster.py",
    "pm_research.py",
    "research_service.py",
    "news_store.py",
    "snapshot_engine.py",
    "universe_config.py",
]

# Deployable CODE paths — dirty state here means the deploy would ship code
# that git doesn't know about. Pipeline-generated artifacts (models/, data/,
# charts/, epm-quant-reports/, docs/) are mutated daily and are excluded.
_DEPLOY_CODE_PATHS = SYNC_PY_FILES + [
    "services", "providers", "config", "static", "commentary",
]

# Tracked root .py files that are laptop-only BY DESIGN: research scripts,
# training pipelines, build tools, orchestrators, and one-off harnesses.
# Every tracked root .py must appear in SYNC_PY_FILES or here.
# tests/test_post_run_sync.py::test_root_py_inventory_classified enforces this.
_NOT_DEPLOYED_PY = frozenset({
    "_test_qwen_raw.py", "_test_recap_scenarios.py", "_test_repair.py",
    "arimax_model.py", "backfill_prediction_log.py",
    "build_directional_feature_panel.py",
    "build_growth24_foundation_sidecar_features.py",
    "build_growth24_pead_hmm_panel.py", "build_growth24_sector_relative_panel.py",
    "build_quantcup_price_dl_panel.py", "build_training_dataset.py",
    "check_site_freshness.py", "combine_growth24_stress_weight_36c.py",
    "compare_llm_models.py", "data_utils.py", "deep_learning_model.py",
    "dl_abstention_gate_eval.py", "dl_cap_aware_replay_report.py",
    "dl_champion_card_report.py", "dl_champion_failure_analysis.py",
    "dl_cleanbaseline_eval.py", "dl_directional_loss_experiment.py",
    "dl_dual_head_experiment.py", "dl_expanded_feature_ensemble_eval.py",
    "dl_expanded_feature_seed_grid.py", "dl_experiment_eval.py",
    "dl_experiment_train.py", "dl_growth24_current_control_gate.py",
    "dl_growth24_dispersion_gate_backtest.py", "dl_growth24_encoder_probe.py",
    "dl_growth24_ensemble_gate.py", "dl_growth24_paper_maturity_check.py",
    "dl_growth24_paper_outcome.py", "dl_growth24_shadow_paper.py",
    "dl_hmm_abstention_filter_report.py", "dl_long_only_gate_eval.py",
    "dl_panel_diagnostics.py", "dl_rank_head_distill_train.py",
    "dl_rank_head_ensemble_eval.py", "dl_rank_head_experiment.py",
    "dl_rank_head_historical_blind_loop.py", "dl_rank_head_paper_trade.py",
    "dl_rank_head_shadow_backtest.py", "dl_rank_head_shadow_forecast.py",
    "dl_rank_head_shadow_score.py", "dl_rank_head_walkforward.py",
    "dl_regime_gate_report.py", "dl_regime_test_commands.py",
    "dl_rolling_sign_calibration_eval.py", "dl_shadow_diagnostic_report.py",
    "dl_sign_calibration_eval.py", "dl_sign_regularized_experiment.py",
    "dl_ticker_cooldown_regime_replay.py", "dl_ticker_cooldown_replay.py",
    "dl_ticker_cooldown_stress_diff_report.py",
    "dl_ticker_cooldown_tolerance_regime_replay.py",
    "dl_ticker_holdout_report.py", "dl_warmstart_eval.py", "dl_warmstart_train.py",
    "exp5_log_volume_clean_baseline.py", "fama_french_model.py",
    "feature_dashboard_gen.py", "feature_drift_monitor.py",
    "feature_promoter.py", "feature_tester.py", "feature_validator.py",
    "forecast_common.py", "gather_qlora_data.py", "generate_charts.py",
    "generate_toggle_chart.py", "institutional_model.py", "linear_model.py",
    "ml_model.py", "model_leaderboard.py", "model_ranking.py",
    "post_run.py", "push_to_github.py", "quantconnect_model.py",
    "record_predictions.py", "refresh_fama_french_factors.py",
    "refresh_growth24_price_cache.py", "refresh_quant_cup_price_cache.py",
    "regime_detector.py", "run_daily.py", "scrape_ycharts.py", "ycharts_api.py",
    "summarize_distill_sweep.py",
    "sync_forecasts_to_features.py", "test_earnings_trigger.py",
    "update_sentiment.py",
})

_ALLOW_DIRTY_ENV = "EPM_ALLOW_DIRTY_DEPLOY"
_HEALTH_URL = "https://epm-market-intelligence.com/api/health"


def _git_dirty_code_paths() -> list[str]:
    """Return deployable code paths with uncommitted changes. Never raises."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--"] + _DEPLOY_CODE_PATHS,
            capture_output=True, text=True, timeout=15,
            cwd=str(Path(__file__).resolve().parent),
        )
        if result.returncode != 0:
            print("[SYNC] WARNING: git status failed — skipping dirty check")
            return []
        dirty = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            dirty.append(parts[1] if len(parts) == 2 else parts[0])
        return dirty
    except Exception as e:
        print(f"[SYNC] WARNING: git check failed ({e}) — skipping dirty check")
        return []


def _unlisted_root_py() -> list[str]:
    """Return tracked root .py files not in SYNC_PY_FILES or _NOT_DEPLOYED_PY."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "*.py"],
            capture_output=True, text=True, timeout=15,
            cwd=str(Path(__file__).resolve().parent),
        )
        if result.returncode != 0:
            return []
        deployed = set(SYNC_PY_FILES)
        return [
            name for name in result.stdout.splitlines()
            if "/" not in name and name.endswith(".py")
            and name not in deployed
            and name not in _NOT_DEPLOYED_PY
        ]
    except Exception:
        return []


def _restart_service(dest: str, key_args: list[str]) -> bool:
    """SSH restart of epm.service on the server. Returns True on success."""
    ssh_args = [a for a in key_args if a != "-O"]
    cmd = ["ssh", *ssh_args, dest, "sudo systemctl restart epm.service"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print("[SYNC] epm.service restarted.")
            return True
        print(f"[SYNC] Restart failed (exit {result.returncode}): {result.stderr.strip()}")
        return False
    except subprocess.TimeoutExpired:
        print("[SYNC] Restart timed out after 60s.")
        return False
    except Exception as e:
        print(f"[SYNC] Restart failed: {e}")
        return False


def push_status_file(
    local_status: str = "logs/run_daily_status.json",
    remote_dest: str = f"{SERVER_USER}@{SERVER_HOST}:{SERVER_PATH}/data/run_daily_status.json",
) -> bool:
    """scp the run_daily status file to data/ on the server so /api/health can read it.

    Mirrors the error posture of _restart_service: returns bool, never raises.
    The -O flag keeps legacy SFTP mode (same as sync_to_server key_args).
    """
    local = Path(local_status)
    if not local.exists():
        print(f"[push_status] {local_status} not found — skipping")
        return False
    key_args = ["-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=20", "-O"]
    cmd = ["scp", *key_args, str(local), remote_dest]
    try:
        rc = subprocess.run(cmd, capture_output=True, timeout=30).returncode
        if rc == 0:
            print(f"[push_status] {local_status} → server [OK]")
            return True
        print(f"[push_status] scp failed (exit {rc})")
        return False
    except subprocess.TimeoutExpired:
        print("[push_status] scp timed out after 30s")
        return False
    except Exception as exc:
        print(f"[push_status] failed: {exc}")
        return False


def _probe_health_origin(
    ssh_dest: str = f"{SERVER_USER}@{SERVER_HOST}",
    ssh_key: str = SSH_KEY,
    port: int = 8000,
    attempts: int = 12,
    delay: int = 5,
) -> tuple[bool, str]:
    """Probe /api/health on the server's loopback via SSH+curl.

    Deploy-critical: proves epm.service restarted and FastAPI is serving.
    Not subject to Cloudflare WAF or laptop-side connectivity/UA blocks."""
    import json as _json
    curl_cmd = f"curl -fsS --max-time 10 http://127.0.0.1:{port}/api/health"
    ssh_args = [
        "ssh", "-i", ssh_key,
        "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=20",
        ssh_dest, curl_cmd,
    ]
    for attempt in range(1, attempts + 1):
        try:
            r = subprocess.run(ssh_args, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                stderr_snip = r.stderr.strip()[:120] if r.stderr else ""
                if attempt < attempts:
                    print(f"[SYNC] origin health not yet ready "
                          f"(attempt {attempt}/{attempts}, exit {r.returncode}"
                          + (f": {stderr_snip}" if stderr_snip else "")
                          + f"), retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                return False, (f"origin curl exit {r.returncode}"
                               + (f": {stderr_snip}" if stderr_snip else ""))
            try:
                data = _json.loads(r.stdout)
            except Exception:
                return False, f"origin health non-JSON body: {r.stdout[:120]!r}"
            status = data.get("status", "unknown")
            if status != "ok":
                print("  " + "!" * 64)
                print(f"  [SYNC][WARN] origin /api/health returned status={status!r}.")
                print("  Deploy succeeded but the app reports degraded state.")
                print("  " + "!" * 64)
            return True, f"origin status={status}"
        except subprocess.TimeoutExpired:
            if attempt < attempts:
                print(f"[SYNC] origin health SSH timed out "
                      f"(attempt {attempt}/{attempts}), retrying in {delay}s...")
                time.sleep(delay)
            else:
                return False, "origin SSH timed out after all retries"
        except Exception as exc:
            return False, f"origin probe error: {type(exc).__name__}: {exc}"
    return False, "origin unreachable after all retries"


def _probe_health(
    url: str = _HEALTH_URL,
    attempts: int = 3,
    delay: int = 5,
) -> tuple[bool, str]:
    """Probe /api/health via the public HTTPS URL. Secondary/warn-only.

    HTTP 200 with any valid JSON counts as reachable; degraded passes with a warning.
    Cloudflare may block urllib's UA with 403 — callers must not fail a deploy solely
    on this probe's result; use _probe_health_origin for the deploy-critical check."""
    import json as _json
    import urllib.request as _req
    import urllib.error as _uerr
    for attempt in range(1, attempts + 1):
        try:
            with _req.urlopen(url, timeout=10) as resp:
                if resp.status != 200:
                    if attempt < attempts:
                        time.sleep(delay)
                        continue
                    return False, f"HTTP {resp.status}"
                data = _json.loads(resp.read().decode())
                status = data.get("status", "unknown")
                if status != "ok":
                    print("  " + "!" * 64)
                    print(f"  [SYNC][WARN] /api/health returned status={status!r}.")
                    print("  Deploy succeeded but the app reports degraded state.")
                    print("  " + "!" * 64)
                return True, f"status={status}"
        except _uerr.HTTPError as e:
            body_snip = ""
            try:
                body_snip = e.read(256).decode(errors="replace")
            except Exception:
                pass
            detail = f"HTTP {e.code}" + (f" — {body_snip[:80]}" if body_snip else "")
            if attempt < attempts:
                print(f"[SYNC] public health {detail} (attempt {attempt}/{attempts}), retrying in {delay}s...")
                time.sleep(delay)
            else:
                return False, detail
        except _uerr.URLError as e:
            if attempt < attempts:
                print(f"[SYNC] public health not reachable "
                      f"(attempt {attempt}/{attempts}): {e.reason}, retrying in {delay}s...")
                time.sleep(delay)
            else:
                return False, f"unreachable: {e.reason}"
        except Exception as exc:
            return False, f"probe error: {type(exc).__name__}: {exc}"
    return False, "unreachable after all retries"


def run(cmd: list[str]) -> int:
    print("[>]", " ".join(cmd))
    try:
        return subprocess.call(cmd)
    except Exception as e:
        print(f"[WARN] Failed to run {cmd}: {e}")
        return 1


# Files that live on the server and must not be overwritten from local.
# Includes WAL/SHM sidecars: once users.db runs in WAL mode, a laptop dev run
# creates users.db-wal/-shm in data/; without these entries the next scp would
# push foreign sidecars next to the server's live DB (corruption vector).
_SERVER_MANAGED = {
    "jwt_secret.key",
    "users.db", "users.db-wal", "users.db-shm",
    "earnings_calendar.json",
    "research_cache.db", "research_cache.db-wal", "research_cache.db-shm",
}

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


def _write_deploy_stamp() -> None:
    """Write data/deploy_stamp.json with the current commit SHA + UTC timestamp.

    The file rides the existing data/ scp in sync_to_server() and is read by
    /api/health check 10 to report which commit is live (6/05 wrong-branch class).
    Never raises — a stamp failure must not block a deploy.
    """
    import datetime as _dt
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).resolve().parent),
        )
        commit = result.stdout.strip() if result.returncode == 0 else "unknown"
        stamp = {
            "commit": commit,
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        }
        stamp_path = Path("data") / "deploy_stamp.json"
        stamp_path.parent.mkdir(parents=True, exist_ok=True)
        stamp_path.write_text(
            json.dumps(stamp, indent=2), encoding="utf-8"
        )
        print(f"[SYNC] deploy stamp: commit={commit}")
    except Exception as exc:
        print(f"[SYNC] WARNING: deploy stamp failed ({exc}) — continuing")


def sync_to_server(*, allow_dirty: bool = False) -> bool:
    """Push outputs + app files to the server, restart the service, and verify
    /api/health. Returns True only if all transfers, the restart, and the health
    probe succeed."""
    dest = f"{SERVER_USER}@{SERVER_HOST}"
    key_args = ["-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=20", "-O"]

    if not allow_dirty and os.getenv(_ALLOW_DIRTY_ENV, "") not in ("1", "true"):
        dirty = _git_dirty_code_paths()
        if dirty:
            print("  " + "!" * 64)
            print(f"  [SYNC] REFUSING TO DEPLOY: {len(dirty)} deployable code file(s)")
            print("  have uncommitted changes:")
            for f in dirty:
                print(f"    {f}")
            print("  Commit or stash before deploying. Override with:")
            print("    python post_run.py --allow-dirty")
            print(f"    {_ALLOW_DIRTY_ENV}=1 python post_run.py")
            print("  " + "!" * 64)
            return False

    unlisted = _unlisted_root_py()
    if unlisted:
        print("  " + "!" * 64)
        print(f"  [SYNC][WARN] {len(unlisted)} root .py file(s) are unclassified")
        print("  (not in SYNC_PY_FILES or _NOT_DEPLOYED_PY) and will NOT be deployed:")
        for f in unlisted:
            print(f"    {f}")
        print("  Add to SYNC_PY_FILES (server) or _NOT_DEPLOYED_PY (laptop-only).")
        print("  " + "!" * 64)

    # Data freshness — warn-only summary before sync (never blocks manual deploys).
    # The pipeline gate runs earlier in send_email.py; this surfaces the same
    # information in the deploy log for operator awareness.
    try:
        from services import data_freshness as _df_sync
        for _w in _df_sync.warn_lines(_df_sync.run_checks()):
            print(f"[SYNC] {_w}")
    except Exception as _df_sync_exc:
        print(f"[SYNC] (data freshness check failed: {_df_sync_exc})")

    # Write deploy stamp — rides the data/ scp below, never raises.
    _write_deploy_stamp()

    print("\n[SYNC] Pushing output to server...")
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
        if not _restart_service(dest, key_args):
            print("  " + "!" * 64)
            print("  [SYNC][FAILED] Code synced but epm.service RESTART FAILED.")
            print("  The server may still be running OLD code. Investigate with:")
            print(f"  ssh dporter02@{SERVER_HOST} sudo systemctl status epm.service")
            print("  " + "!" * 64)
            return False
        origin_ok, origin_detail = _probe_health_origin()
        if not origin_ok:
            print("  " + "!" * 64)
            print("  [SYNC][FAILED] Restart issued but origin /api/health is unreachable.")
            print(f"  Detail: {origin_detail}")
            print("  Check: journalctl -u epm.service -n 50")
            print("  " + "!" * 64)
            return False
        # Secondary: public URL — warn only (Cloudflare may block urllib UA with 403)
        pub_ok, pub_detail = _probe_health()
        if not pub_ok:
            print("  " + "!" * 64)
            print(f"  [SYNC][WARN] Public health probe failed: {pub_detail}")
            print("  Origin is healthy; this is likely a Cloudflare/WAF/UA issue.")
            print("  " + "!" * 64)
        print(f"[SYNC] All {ok} target(s) deployed + restarted + health: {origin_detail}")
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
    ap.add_argument("--allow-dirty", action="store_true",
                    help="Bypass the dirty-code guard (deploy with uncommitted changes).")
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
    if not sync_to_server(allow_dirty=args.allow_dirty):
        print("[post_run] Server sync FAILED — see banner above. Outputs are NOT deployed.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
