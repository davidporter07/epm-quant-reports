# monitor.py

import os
import re
import html
import json
import time
import subprocess
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception:
    yf = None

try:
    import plotly.graph_objects as go
    from plotly.offline import plot as plotly_plot
    from plotly.subplots import make_subplots
except Exception:
    go = None
    plotly_plot = None
    make_subplots = None

from features import build_feature_table, load_ycharts_features
from news_store import (
    export_news_snapshot,
    load_news_selection_state,
    load_news_store,
    mark_selected_stories,
    save_news_selection_state,
    save_news_store,
)

try:
    import pillow_avif  # noqa: F401
except Exception:
    pillow_avif = None


start_time = time.time()

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
VENV_PYTHON = sys.executable
DEV_MODE = "--dev" in sys.argv
if DEV_MODE:
    print("  DEV MODE: skipping YCharts scrape, charts, PDF, and server sync.")

# ---------------------------------------------------------------------------
# Background service pause — freeze MiroFish + Kronos during the pipeline so
# they don't compete for GPU/VRAM with DL training and commentary generation.
# SIGSTOP freezes a process in-place (port stays bound, no restart needed).
# SIGCONT resumes it. atexit ensures thaw runs even if the pipeline crashes.
# ---------------------------------------------------------------------------
import signal as _signal
import atexit as _atexit

_FREEZE_PATTERNS = ["mirofish", "kronos"]

def _freeze_background_services() -> None:
    if DEV_MODE or sys.platform == "win32":
        return
    import subprocess as _sp
    for pattern in _FREEZE_PATTERNS:
        try:
            result = _sp.run(["pgrep", "-f", pattern], capture_output=True, text=True)
            pids = [p.strip() for p in result.stdout.strip().split() if p.strip()]
            for pid in pids:
                os.kill(int(pid), _signal.SIGSTOP)
                print(f"  [pipeline] Froze PID {pid} ({pattern})")
        except Exception as exc:
            print(f"  [pipeline] Could not freeze {pattern}: {exc}")

def _thaw_background_services() -> None:
    if sys.platform == "win32":
        return
    import subprocess as _sp
    for pattern in _FREEZE_PATTERNS:
        try:
            result = _sp.run(["pgrep", "-f", pattern], capture_output=True, text=True)
            pids = [p.strip() for p in result.stdout.strip().split() if p.strip()]
            for pid in pids:
                os.kill(int(pid), _signal.SIGCONT)
                print(f"  [pipeline] Resumed PID {pid} ({pattern})")
        except Exception as exc:
            print(f"  [pipeline] Could not resume {pattern}: {exc}")

_atexit.register(_thaw_background_services)
_freeze_background_services()

# --- Setup paths ---
os.makedirs("archive", exist_ok=True)
today_str = datetime.today().strftime("%Y-%m-%d")
site_dir = os.path.join(os.getcwd(), "epm-quant-reports")
os.makedirs(site_dir, exist_ok=True)
report_html_path = os.path.join(site_dir, "report.html")

# so the GitHub Pages root URL continues to work.
index_html_path = os.path.join(site_dir, "index.html")
report_pdf_path = os.path.join(site_dir, "report.pdf")
funds_html_path = os.path.join(site_dir, "funds.html")
markets_html_path = os.path.join(site_dir, "markets.html")
forecasting_html_path = os.path.join(site_dir, "forecasting.html")
home_html_path = os.path.join(site_dir, "index.html")
logo_path = os.path.join(site_dir, "epm_logo.png")
archive_html_path = f"archive/report_{today_str}.html"
archive_pdf_path = f"archive/report_{today_str}.pdf"

MAG7 = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]


def get_ytd_return_map(tickers):
    if yf is None:
        return {t: np.nan for t in tickers}
    start = f"{datetime.today().year}-01-01"
    try:
        px = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"]
    except Exception:
        return {t: np.nan for t in tickers}
    if isinstance(px, pd.Series):
        px = px.to_frame(name=tickers[0])
    px = px.ffill().dropna(how="all")
    out = {}
    for ticker in tickers:
        if ticker not in px.columns:
            out[ticker] = np.nan
            continue
        s = px[ticker].dropna()
        out[ticker] = ((s.iloc[-1] / s.iloc[0]) - 1.0) * 100.0 if not s.empty else np.nan
    return out

COMMENTARY_JSON_PATH = os.path.join("data", "latest_commentary.json")

# Scrape YCharts in background — no timeout, runs concurrently with training steps.
# We wait for it to finish before features.py needs the CSV.
# Skip if a pre-market scheduled scrape already ran today (within 4 hours).
_ycharts_proc = None
if not DEV_MODE:
    _ycharts_fresh = False
    try:
        import json as _json
        _yc_path = os.path.join("data", "ycharts_live.json")
        if os.path.exists(_yc_path):
            with open(_yc_path, encoding="utf-8") as _yf:
                _yc = _json.load(_yf)
            _ts = _yc.get("scrape_ts")
            if _ts:
                from datetime import timezone as _tz
                _age = (datetime.now() - datetime.fromisoformat(_ts)).total_seconds()
                _ycharts_fresh = _age < 4 * 3600  # fresh if scraped within 4 hours
    except Exception:
        pass

    if _ycharts_fresh:
        print("  YCharts data is fresh from pre-market scrape — skipping rescrape.")
    else:
        _ycharts_proc = subprocess.Popen([VENV_PYTHON, "scrape_ycharts.py"])
        print("  YCharts scrape launched in background.")

# Refresh MAG7 training panel — independent of YCharts, runs while scrape is in progress.
try:
    subprocess.run(
        [VENV_PYTHON, "build_training_dataset.py", "--universe", "mag7", "--years", "7"],
        check=True,
    )
except subprocess.CalledProcessError as e:
    print(f"Warning: Training panel refresh failed (models will use cached panel). Details: {e}")

# --- Deep Learning: daily warm-start fine-tune ---
# Back up the existing checkpoint before fine-tuning so it can be restored
# if a bad run degrades the model.
import shutil as _shutil
_dl_ckpt = os.path.join("models", "dl_tcn.pt")
_dl_backup = os.path.join("models", "dl_tcn_backup.pt")
_dl_scaler = os.path.join("models", "dl_scaler.json")
_dl_scaler_backup = os.path.join("models", "dl_scaler_backup.json")
_dl_fi = os.path.join("models", "dl_feature_importance.csv")
_dl_fi_backup = os.path.join("models", "dl_feature_importance_backup.csv")
_dl_guard_before = os.path.join("data", "dl_guard_before.csv")
_dl_guard_after = os.path.join("data", "dl_guard_after.csv")
_dl_guard_tolerance = 1.02
_dl_guard_dir_drop_limit = 0.03
_dl_guard_ic_drop_limit = 0.03


def _read_dl_guard_metrics(path):
    try:
        df = pd.read_csv(path)
        metrics = {}
        for _, row in df.iterrows():
            name = str(row.get("Metric") or "").strip()
            try:
                val = float(row.get("Value"))
            except Exception:
                continue
            if name and np.isfinite(val):
                metrics[name] = val
        return metrics or None
    except Exception:
        return None


def _run_dl_guard_eval(out_path):
    try:
        subprocess.run(
            [
                VENV_PYTHON,
                "deep_learning_model.py",
                "backtest",
                "--test-days",
                "252",
                "--out",
                out_path,
            ],
            check=True,
        )
        return _read_dl_guard_metrics(out_path)
    except subprocess.CalledProcessError as e:
        print(f" Warning: DL guard evaluation failed: {e}")
        return None


def _dl_guard_rejection_reason(before, after):
    before_mae = before.get("MAE")
    after_mae = after.get("MAE")
    if before_mae is None or after_mae is None:
        return "missing MAE metric"
    if after_mae > before_mae * _dl_guard_tolerance:
        return f"MAE worsened from {before_mae:.6f} to {after_mae:.6f}"

    before_dir = before.get("Directional_Accuracy")
    after_dir = after.get("Directional_Accuracy")
    if before_dir is not None and after_dir is not None:
        if after_dir < before_dir - _dl_guard_dir_drop_limit:
            return f"directional accuracy fell from {before_dir:.4f} to {after_dir:.4f}"

    before_ic = before.get("IC_Spearman")
    after_ic = after.get("IC_Spearman")
    if before_ic is not None and after_ic is not None:
        if after_ic < before_ic - _dl_guard_ic_drop_limit:
            return f"IC fell from {before_ic:.4f} to {after_ic:.4f}"

    return None


if os.path.exists(_dl_ckpt):
    _shutil.copy2(_dl_ckpt, _dl_backup)
    print(f" DL checkpoint backed up -> {_dl_backup}")
if os.path.exists(_dl_scaler):
    _shutil.copy2(_dl_scaler, _dl_scaler_backup)
if os.path.exists(_dl_fi):
    _shutil.copy2(_dl_fi, _dl_fi_backup)

_dl_mae_before = None
_dl_metrics_before = None
if os.path.exists(_dl_ckpt) and os.path.exists(_dl_scaler):
    _dl_metrics_before = _run_dl_guard_eval(_dl_guard_before)
    if _dl_metrics_before is not None:
        _dl_mae_before = _dl_metrics_before.get("MAE")
        print(
            " DL guard baseline "
            f"MAE={_dl_metrics_before.get('MAE', float('nan')):.6f} "
            f"Dir={_dl_metrics_before.get('Directional_Accuracy', float('nan')):.4f} "
            f"IC={_dl_metrics_before.get('IC_Spearman', float('nan')):.4f}"
        )

# Runs 2 epochs of fine-tuning on the refreshed panel. If no checkpoint exists
# yet, trains from scratch. This keeps the model learning from new market data
# every day without a full retrain.
try:
    subprocess.run(
        [
            VENV_PYTHON, "deep_learning_model.py", "train",
            "--epochs", "2",
            "--patience", "2",
            "--batch-size", "256",
        ],
        check=True,
    )
except subprocess.CalledProcessError as e:
    print(f" Warning: DL warm-start fine-tune failed (inference will use existing checkpoint). Details: {e}")

_dl_mae_after = None
_dl_metrics_after = None
if _dl_metrics_before is not None and os.path.exists(_dl_ckpt) and os.path.exists(_dl_scaler):
    _dl_metrics_after = _run_dl_guard_eval(_dl_guard_after)
    if _dl_metrics_after is not None:
        _dl_mae_after = _dl_metrics_after.get("MAE")
        print(
            " DL guard candidate "
            f"MAE={_dl_metrics_after.get('MAE', float('nan')):.6f} "
            f"Dir={_dl_metrics_after.get('Directional_Accuracy', float('nan')):.4f} "
            f"IC={_dl_metrics_after.get('IC_Spearman', float('nan')):.4f}"
        )
        _reject_reason = _dl_guard_rejection_reason(_dl_metrics_before, _dl_metrics_after)
        if _reject_reason:
            print(
                " DL guard rejected candidate checkpoint "
                f"({_reject_reason}). Restoring backup."
            )
            if os.path.exists(_dl_backup):
                _shutil.copy2(_dl_backup, _dl_ckpt)
            if os.path.exists(_dl_scaler_backup):
                _shutil.copy2(_dl_scaler_backup, _dl_scaler)
            if os.path.exists(_dl_fi_backup):
                _shutil.copy2(_dl_fi_backup, _dl_fi)
        else:
            print(" DL guard accepted candidate checkpoint.")

# Commit updated model checkpoint to git so there is a versioned record
# of how the model evolves over time.
_model_files = [
    "models/dl_tcn.pt",
    "models/dl_scaler.json",
    "models/dl_feature_importance.csv",
]
_here = os.path.dirname(os.path.abspath(__file__))
try:
    subprocess.run(["git", "add"] + _model_files, cwd=_here, check=True)
    _commit_msg = f"Update DL model checkpoint: {datetime.now().strftime('%Y-%m-%d')}"
    result = subprocess.run(
        ["git", "commit", "-m", _commit_msg],
        cwd=_here, capture_output=True, text=True
    )
    if result.returncode == 0:
        # Stash only tracked-file changes so pull --rebase can run cleanly.
        # Avoid --include-untracked: on Windows, Python's logging holds email_log.txt
        # open, and git's unlink attempt on untracked files triggers an interactive prompt.
        _stash_result = subprocess.run(
            ["git", "stash", "-m", "pipeline-auto-stash"],
            cwd=_here, capture_output=True, text=True
        )
        _stashed = (_stash_result.returncode == 0
                    and "No local changes to save" not in _stash_result.stdout)
        try:
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=_here, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=_here, check=True)
            print(" DL model checkpoint committed and pushed to git")
        finally:
            if _stashed:
                subprocess.run(["git", "stash", "pop"], cwd=_here)
    elif "nothing to commit" in result.stdout.lower() or "nothing to commit" in result.stderr.lower():
        print(" DL model checkpoint unchanged  no git commit needed")
    else:
        print(f" git commit failed: {result.stderr.strip()}")
except subprocess.CalledProcessError as e:
    print(f" Could not version DL model in git: {e}")

# Wait for background YCharts scrape to finish before features.py needs its CSV.
# By now build_training_dataset + DL training have been running concurrently,
# so the scrape has had several minutes to complete.
if _ycharts_proc is not None:
    print("  Waiting for YCharts scrape to finish...")
    _ycharts_proc.wait()
    if _ycharts_proc.returncode != 0:
        print(f"  YCharts scrape exited with code {_ycharts_proc.returncode} (non-fatal, cached data will be used).")
    else:
        print("  YCharts scrape complete.")

subprocess.run([VENV_PYTHON, "features.py"], check=True)

subprocess.run([VENV_PYTHON, "linear_model.py"], check=True)

try:
    subprocess.run([VENV_PYTHON, "refresh_fama_french_factors.py"], check=True)
except subprocess.CalledProcessError as e:
    print(f" Warning: Fama-French refresh failed but continuing. Details: {e}")

subprocess.run([VENV_PYTHON, "fama_french_model.py"], check=True)

subprocess.run([VENV_PYTHON, "institutional_model.py"], check=True)

subprocess.run([VENV_PYTHON, "quantconnect_model.py"], check=True)

subprocess.run([VENV_PYTHON, "update_sentiment.py"], check=True)

# ML model may skip if not enough training data
try:
    subprocess.run([VENV_PYTHON, "ml_model.py"], check=True)
except subprocess.CalledProcessError as e:
    print(f" Warning: ML model failed or skipped. Details: {e}")


def remove_file_if_exists(path):
    try:
        if os.path.exists(path):
            os.remove(path)
            print(f" Removed stale file: {path}")
    except Exception as e:
        print(f" Could not remove stale file {path}: {e}")


def _safe_read_text(path, default=""):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f" Could not read {path}: {e}")
        return default

try:
    subprocess.run([VENV_PYTHON, "arimax_model.py"], check=True)
except subprocess.CalledProcessError as e:
    print(f" Warning: ARIMAX model failed or skipped. Details: {e}")
    remove_file_if_exists(os.path.join("data", "arimax_forecasts.csv"))
    remove_file_if_exists(os.path.join("data", "arimax_backtest_results.csv"))


try:
    subprocess.run([VENV_PYTHON, "model_ranking.py"], check=True)
except subprocess.CalledProcessError as e:
    print(f" Warning: Model ranking failed or skipped. Details: {e}")


# --- Deep Learning (PyTorch) inference + live prediction logging ---
try:
    subprocess.run([
        VENV_PYTHON,
        "deep_learning_model.py",
        "infer",
        "--tickers",
        "AAPL,MSFT,AMZN,NVDA,GOOG,META,TSLA",
    ], check=True)
except subprocess.CalledProcessError as e:
    print(f" Deep Learning inference skipped/failed: {e}")

# NEW: ensure features.parquet contains all model forecasts for MAG7 (not just DL)
try:
    subprocess.run([VENV_PYTHON, "sync_forecasts_to_features.py"], check=True)
except subprocess.CalledProcessError as e:
    print(f" Forecast sync failed but continuing. Details: {e}")

try:
    subprocess.run([VENV_PYTHON, "record_predictions.py"], check=True)
except subprocess.CalledProcessError as e:
    print(f" Prediction logging failed: {e}")

# Build/update model leaderboard (will show pending until predictions mature)
try:
    subprocess.run([VENV_PYTHON, "model_leaderboard.py", "--tickers", ",".join(MAG7)], check=True)
except subprocess.CalledProcessError as e:
    print(f" Leaderboard build failed but continuing. Details: {e}")

# --- Load features (with forecast CSV joins) ---
features_df = load_ycharts_features()

# --- Build sections ---
table_html = build_feature_table(features_df)

MARKET_SNAPSHOT_TICKERS = {
    "^GSPC": "S&P 500",
    "^STOXX50E": "Euro Stoxx 50",
    "^N225": "Nikkei 225",
    "^VIX": "VIX",
    "^TNX": "10Y Treasury",
    "DX-Y.NYB": "US Dollar",
    "GC=F": "Gold Futures",
    "CL=F": "WTI Crude",
}

CROSS_ASSET_TICKERS = {
    "^GSPC": "S&P 500",
    "^VIX": "VIX",
    "DX-Y.NYB": "US Dollar",
    "GC=F": "Gold Futures",
    "CL=F": "WTI Crude",
    "HYG": "High Yield",
    "IEF": "7-10Y Treasury",
}

SECTOR_TICKERS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLY": "Consumer Disc.",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication",
    "XLB": "Materials",
}

RISK_TICKERS = {
    "HYG": "High Yield",
    "LQD": "Inv. Grade",
    "IEF": "7-10Y Treasury",
    "TLT": "20Y+ Treasury",
}

MARKET_SYMBOL_PROXIES = {
    "^GSPC": ["^GSPC", "SPY"],
    "^STOXX50E": ["^STOXX50E", "FEZ"],
    "^N225": ["^N225", "EWJ"],
    "^VIX": ["^VIX"],
    "^TNX": ["^TNX"],
    "DX-Y.NYB": ["UUP", "DX-Y.NYB"],
    "GC=F": ["GC=F", "GLD", "XAUUSD=X"],
    "XAUUSD=X": ["GC=F", "GLD", "XAUUSD=X"],
    "CL=F": ["CL=F", "USO"],
    "GLD": ["GLD", "GC=F", "XAUUSD=X"],
    "USO": ["USO", "CL=F"],
    "HYG": ["HYG"],
    "IEF": ["IEF"],
    "LQD": ["LQD"],
    "TLT": ["TLT"],
    "XLK": ["XLK"],
    "XLF": ["XLF"],
    "XLV": ["XLV"],
    "XLI": ["XLI"],
    "XLY": ["XLY"],
    "XLP": ["XLP"],
    "XLE": ["XLE"],
    "XLU": ["XLU"],
    "XLRE": ["XLRE"],
    "XLC": ["XLC"],
    "XLB": ["XLB"],
}

MARKET_DASHBOARD_TICKERS = list(dict.fromkeys(
    list(MARKET_SNAPSHOT_TICKERS.keys())
    + list(CROSS_ASSET_TICKERS.keys())
    + list(SECTOR_TICKERS.keys())
    + list(RISK_TICKERS.keys())
))


def _extract_close_series(raw):
    if raw is None or raw.empty:
        return pd.Series(dtype=float)

    if isinstance(raw.columns, pd.MultiIndex):
        level0 = list(raw.columns.get_level_values(0))
        if "Close" in level0:
            close = raw["Close"]
        elif "Adj Close" in level0:
            close = raw["Adj Close"]
        else:
            close = raw.xs(raw.columns.get_level_values(0)[0], axis=1, level=0)
    else:
        if "Close" in raw.columns:
            close = raw["Close"]
        elif "Adj Close" in raw.columns:
            close = raw["Adj Close"]
        else:
            close = raw

    if isinstance(close, pd.DataFrame):
        if close.shape[1] == 1:
            close = close.iloc[:, 0]
        else:
            close = close.iloc[:, 0]

    return pd.to_numeric(close, errors="coerce").dropna()


def _download_symbol_history(symbol, period="2y"):
    options = MARKET_SYMBOL_PROXIES.get(symbol, [symbol])
    for proxy in options:
        try:
            raw = yf.download(
                proxy,
                period=period,
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            s = _extract_close_series(raw)
            if not s.empty:
                s.name = symbol
                return s
        except Exception:
            continue
    return pd.Series(dtype=float, name=symbol)


def _safe_close_download(tickers, period="2y"):
    if yf is None:
        return pd.DataFrame()

    frames = []
    for symbol in tickers:
        s = _download_symbol_history(symbol, period=period)
        if not s.empty:
            frames.append(s)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, axis=1).sort_index().ffill().dropna(how="all")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def _get_series(df, symbol):
    if df is None or df.empty or symbol not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[symbol], errors="coerce").dropna()


def _pct_change_n(series, n=1):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) <= n:
        return np.nan
    base = s.iloc[-(n + 1)]
    if pd.isna(base) or base == 0:
        return np.nan
    return (s.iloc[-1] / base - 1.0) * 100.0


def _pct_change_from_date(series, start_dt):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return np.nan
    s = s[s.index >= pd.Timestamp(start_dt)]
    if s.empty:
        return np.nan
    base = s.iloc[0]
    if pd.isna(base) or base == 0:
        return np.nan
    return (s.iloc[-1] / base - 1.0) * 100.0


def _bp_change_n(series, n=21):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) <= n:
        return np.nan
    return (s.iloc[-1] - s.iloc[-(n + 1)]) * 100.0


def _bp_change_from_date(series, start_dt):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return np.nan
    s = s[s.index >= pd.Timestamp(start_dt)]
    if len(s) < 2:
        return np.nan
    return (s.iloc[-1] - s.iloc[0]) * 100.0


def _fmt_pct(val, digits=2, signed=True):
    if pd.isna(val):
        return "N/A"
    return f"{val:+.{digits}f}%" if signed else f"{val:.{digits}f}%"


def _fmt_bps(val):
    if pd.isna(val):
        return "N/A"
    return f"{val:+.0f} bps"


def _fmt_level(symbol, val):
    if pd.isna(val):
        return "N/A"
    if symbol == "^TNX":
        return f"{val:.2f}%"
    if symbol in {"^VIX", "DX-Y.NYB", "GC=F", "XAUUSD=X", "CL=F", "GLD", "USO"}:
        return f"{val:.2f}"
    if abs(val) >= 1000:
        return f"{val:,.0f}"
    return f"{val:.2f}"


def _normalize_to_100(frame):
    out = frame.copy()
    for col in out.columns:
        s = pd.to_numeric(out[col], errors="coerce").dropna()
        if s.empty:
            out[col] = np.nan
            continue
        out[col] = out[col] / s.iloc[0] * 100.0
    return out



def _plotly_div(fig, height=360, margins=None):
    if plotly_plot is None:
        return "<p>Interactive chart unavailable (Plotly not installed).</p>"
    if margins is None:
        margins = dict(l=56, r=40, t=16, b=70)
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=margins,
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0, bgcolor="rgba(255,255,255,0.85)"),
        hovermode="x unified",
        height=height,
    )
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True, title_standoff=10)
    return plotly_plot(
        fig,
        output_type="div",
        include_plotlyjs=False,
        config={"displayModeBar": False, "responsive": True},
    )



def _build_market_snapshot_html(price_df):
    cards = []
    ytd_start = datetime(datetime.today().year, 1, 1)

    for symbol, label in MARKET_SNAPSHOT_TICKERS.items():
        s = _get_series(price_df, symbol)
        if s.empty:
            continue

        last = float(s.iloc[-1])
        if symbol == "^TNX":
            one_d = _bp_change_n(s, 1)
            one_m = _bp_change_n(s, 21)
            ytd = _bp_change_from_date(s, ytd_start)
            sub1 = f"1D: {_fmt_bps(one_d)}"
            sub2 = f"1M: {_fmt_bps(one_m)}"
            sub3 = f"YTD: {_fmt_bps(ytd)}"
        else:
            one_d = _pct_change_n(s, 1)
            one_m = _pct_change_n(s, 21)
            ytd = _pct_change_from_date(s, ytd_start)
            sub1 = f"1D: {_fmt_pct(one_d)}"
            sub2 = f"1M: {_fmt_pct(one_m)}"
            sub3 = f"YTD: {_fmt_pct(ytd)}"

        cards.append(
            f"""
            <div class='mini-card'>
              <h3>{html.escape(label)}</h3>
              <div style='font-size:26px;font-weight:700;color:#0f172a;margin-bottom:8px;'>{_fmt_level(symbol, last)}</div>
              <div style='font-size:13px;color:#475569;line-height:1.6;'>{sub1}<br>{sub2}<br>{sub3}</div>
            </div>
            """
        )

    if not cards:
        return "<p>Market snapshot unavailable.</p>"

    return "<div class='mini-grid'>" + "".join(cards) + "</div>"


def _build_equity_risk_chart_html(price_df):
    if go is None or price_df.empty:
        return "<p>Equity risk chart unavailable.</p>"

    spx = _get_series(price_df, "^GSPC")
    vix = _get_series(price_df, "^VIX")
    joined = pd.concat([spx, vix], axis=1).dropna()
    joined.columns = ["S&P 500", "VIX"]
    joined = joined[joined.index >= pd.Timestamp(datetime.today() - timedelta(days=365))]
    if joined.empty:
        return "<p>Equity risk chart unavailable.</p>"

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=joined.index, y=joined["S&P 500"], mode="lines", name="S&P 500", line=dict(color="#2563eb")))
    fig.add_trace(go.Scatter(x=joined.index, y=joined["VIX"], mode="lines", name="VIX", yaxis="y2", line=dict(color="#dc2626")))
    fig.update_layout(
        yaxis=dict(title="S&P 500"),
        yaxis2=dict(title="VIX", overlaying="y", side="right", showgrid=False),
    )
    return _plotly_div(fig, height=300)


def _build_rates_credit_chart_html(price_df):
    if go is None or price_df.empty:
        return "<p>Rates & credit chart unavailable.</p>"

    tnx = _get_series(price_df, "^TNX")
    hyg = _get_series(price_df, "HYG")
    ief = _get_series(price_df, "IEF")
    lqd = _get_series(price_df, "LQD")

    parts = []
    if not tnx.empty:
        parts.append(tnx.rename("10Y Treasury"))
    if not hyg.empty and not ief.empty:
        parts.append((hyg / ief).rename("HYG / IEF"))
    if not hyg.empty and not lqd.empty:
        parts.append((hyg / lqd).rename("HYG / LQD"))
    if not parts:
        return "<p>Rates & credit chart unavailable.</p>"

    joined = pd.concat(parts, axis=1).dropna(how="all")
    joined = joined[joined.index >= pd.Timestamp(datetime.today() - timedelta(days=365))].ffill().dropna(how="all")
    if joined.empty:
        return "<p>Rates & credit chart unavailable.</p>"

    fig = go.Figure()
    if "10Y Treasury" in joined.columns:
        fig.add_trace(go.Scatter(x=joined.index, y=joined["10Y Treasury"], mode="lines", name="10Y Treasury", yaxis="y1", line=dict(color="#7c3aed")))
    for col, color in [("HYG / IEF", "#059669"), ("HYG / LQD", "#f59e0b")]:
        if col in joined.columns:
            s = joined[col].dropna()
            if not s.empty:
                s = s / s.iloc[0] * 100.0
                fig.add_trace(go.Scatter(x=s.index, y=s, mode="lines", name=f"{col} (rebased)", yaxis="y2", line=dict(color=color)))
    fig.update_layout(
        yaxis=dict(title="10Y Yield (%)"),
        yaxis2=dict(title="Credit ratios (rebased=100)", overlaying="y", side="right", showgrid=False),
    )
    return _plotly_div(fig, height=300)



def _build_dollar_commodities_chart_html(price_df):
    if go is None or price_df.empty:
        return "<p>Dollar & commodities chart unavailable.</p>"

    gold = _get_series(price_df, "GC=F")
    if gold.empty:
        gold = _get_series(price_df, "GLD")
    if gold.empty:
        gold = _get_series(price_df, "XAUUSD=X")

    wti = _get_series(price_df, "CL=F")

    joined = pd.concat([
        gold.rename("Gold $/oz") if not gold.empty else pd.Series(dtype=float),
        wti.rename("WTI $/bbl") if not wti.empty else pd.Series(dtype=float),
    ], axis=1).dropna(how="all")

    joined = joined[joined.index >= pd.Timestamp(datetime.today() - timedelta(days=183))].ffill().dropna(how="all")
    if joined.empty:
        return "<p>Dollar & commodities chart unavailable.</p>"

    fig = go.Figure()

    if "Gold $/oz" in joined.columns:
        gold_pp = (1.0 / pd.to_numeric(joined["Gold $/oz"], errors="coerce")) * 1000.0
        gold_pp = gold_pp.dropna()
        if not gold_pp.empty:
            fig.add_trace(go.Scatter(
                x=gold_pp.index,
                y=gold_pp,
                mode="lines",
                name="Gold purchasing power",
                yaxis="y1",
                line=dict(color="#7c3aed"),
                hovertemplate="Gold purchasing power: %{y:.4f} oz per $1,000<extra></extra>",
            ))

    if "WTI $/bbl" in joined.columns:
        oil_pp = (1.0 / pd.to_numeric(joined["WTI $/bbl"], errors="coerce")) * 100.0
        oil_pp = oil_pp.dropna()
        if not oil_pp.empty:
            fig.add_trace(go.Scatter(
                x=oil_pp.index,
                y=oil_pp,
                mode="lines",
                name="WTI purchasing power",
                yaxis="y2",
                line=dict(color="#059669"),
                hovertemplate="WTI purchasing power: %{y:.4f} bbl per $100<extra></extra>",
            ))

    fig.update_layout(
        yaxis=dict(title="Gold PP (oz / $1k)"),
        yaxis2=dict(title="WTI PP (bbl / $100)", overlaying="y", side="right", showgrid=False),
        hovermode="x unified",
    )
    return _plotly_div(fig, height=300, margins=dict(l=82, r=82, t=12, b=70))



def _build_sector_rotation_chart_html(price_df):
    if go is None or price_df.empty:
        return "<p>Sector rotation chart unavailable.</p>"

    ytd_start = datetime(datetime.today().year, 1, 1)
    rows = []
    for symbol, label in SECTOR_TICKERS.items():
        s = _get_series(price_df, symbol)
        if s.empty:
            continue
        rows.append({"Sector": label, "YTD": _pct_change_from_date(s, ytd_start)})

    sector_df = pd.DataFrame(rows).dropna()
    if sector_df.empty:
        return "<p>Sector rotation chart unavailable.</p>"

    sector_df = sector_df.sort_values("YTD", ascending=False)
    colors = ["#16a34a" if x >= 0 else "#dc2626" for x in sector_df["YTD"]]

    fig = go.Figure(go.Bar(
        x=sector_df["YTD"],
        y=sector_df["Sector"],
        orientation="h",
        marker_color=colors,
        text=[f"{x:+.1f}%" for x in sector_df["YTD"]],
        textposition="outside",
        textfont=dict(size=13),
        hovertemplate="%{y}: %{x:+.2f}%<extra></extra>",
    ))
    max_abs = max(abs(float(sector_df["YTD"].min())), abs(float(sector_df["YTD"].max())))
    pad = max(4.0, max_abs * 0.22)
    fig.update_layout(
        xaxis_title="YTD return",
        yaxis_title="",
        margin=dict(l=150, r=130, t=20, b=56),
        height=360,
    )
    fig.update_traces(cliponaxis=False)
    fig.update_xaxes(range=[float(sector_df["YTD"].min()) - pad, float(sector_df["YTD"].max()) + pad], automargin=True)
    fig.update_yaxes(categoryorder="array", categoryarray=list(sector_df["Sector"])[::-1], automargin=True)
    return _plotly_div(fig, height=300)


def _build_risk_dashboard_html(price_df):
    ytd_start = datetime(datetime.today().year, 1, 1)

    def last(symbol):
        s = _get_series(price_df, symbol)
        return float(s.iloc[-1]) if not s.empty else np.nan

    def ratio_change(sym_a, sym_b, days=21):
        a = _get_series(price_df, sym_a)
        b = _get_series(price_df, sym_b)
        if a.empty or b.empty:
            return np.nan
        joined = pd.concat([a, b], axis=1).dropna()
        if len(joined) <= days:
            return np.nan
        ratio = joined.iloc[:, 0] / joined.iloc[:, 1]
        return (ratio.iloc[-1] / ratio.iloc[-(days + 1)] - 1.0) * 100.0

    vix = last("^VIX")
    vix_label = "Contained" if pd.notna(vix) and vix < 18 else "Watchful" if pd.notna(vix) and vix < 22 else "Elevated"

    tnx = _get_series(price_df, "^TNX")
    tnx_1m = _bp_change_n(tnx, 21) if not tnx.empty else np.nan

    hyg_ief = ratio_change("HYG", "IEF", 21)
    hyg_lqd = ratio_change("HYG", "LQD", 21)

    sector_rows = []
    for symbol in SECTOR_TICKERS:
        s = _get_series(price_df, symbol)
        if s.empty:
            continue
        sector_rows.append(_pct_change_from_date(s, ytd_start))
    positive_sectors = int(sum(1 for x in sector_rows if pd.notna(x) and x > 0))
    total_sectors = len(sector_rows)

    dxy = _get_series(price_df, "DX-Y.NYB")
    dxy_ytd = _pct_change_from_date(dxy, ytd_start) if not dxy.empty else np.nan

    cards = [
        ("VIX Regime", vix_label, f"Level: {_fmt_level('^VIX', vix)}"),
        ("10Y Yield Trend", _fmt_bps(tnx_1m), "1-month change"),
        ("Credit vs Treasuries", _fmt_pct(hyg_ief), "HYG / IEF (1M)"),
        ("High Yield vs IG", _fmt_pct(hyg_lqd), "HYG / LQD (1M)"),
        ("Dollar Trend", _fmt_pct(dxy_ytd), "DXY YTD"),
        ("Sector Breadth", f"{positive_sectors}/{total_sectors}", "Positive sectors YTD"),
    ]

    out = ["<div class='mini-grid'>"]
    for title, value, desc in cards:
        out.append(
            f"""
            <div class='mini-card'>
              <h3>{html.escape(title)}</h3>
              <div style='font-size:24px;font-weight:700;color:#0f172a;margin-bottom:8px;'>{html.escape(str(value))}</div>
              <p>{html.escape(desc)}</p>
            </div>
            """
        )
    out.append("</div>")
    return "".join(out)


def _build_market_read_html(price_df):
    ytd_start = datetime(datetime.today().year, 1, 1)

    spx = _get_series(price_df, "^GSPC")
    vix = _get_series(price_df, "^VIX")
    tnx = _get_series(price_df, "^TNX")
    dxy = _get_series(price_df, "DX-Y.NYB")
    hyg = _get_series(price_df, "HYG")
    ief = _get_series(price_df, "IEF")

    spx_ytd = _pct_change_from_date(spx, ytd_start) if not spx.empty else np.nan
    vix_last = float(vix.iloc[-1]) if not vix.empty else np.nan
    tnx_1m = _bp_change_n(tnx, 21) if not tnx.empty else np.nan
    dxy_ytd = _pct_change_from_date(dxy, ytd_start) if not dxy.empty else np.nan

    if not hyg.empty and not ief.empty:
        joined = pd.concat([hyg, ief], axis=1).dropna()
        if len(joined) > 21:
            ratio = joined.iloc[:, 0] / joined.iloc[:, 1]
            hyg_ief_1m = (ratio.iloc[-1] / ratio.iloc[-22] - 1.0) * 100.0
        else:
            hyg_ief_1m = np.nan
    else:
        hyg_ief_1m = np.nan

    sector_perf = []
    for symbol, label in SECTOR_TICKERS.items():
        s = _get_series(price_df, symbol)
        if s.empty:
            continue
        sector_perf.append((label, _pct_change_from_date(s, ytd_start)))
    sector_perf = [(lab, val) for lab, val in sector_perf if pd.notna(val)]
    sector_perf.sort(key=lambda x: x[1], reverse=True)

    positive_sector_count = sum(1 for _, v in sector_perf if v > 0)

    if pd.notna(spx_ytd) and spx_ytd > 5 and pd.notna(vix_last) and vix_last < 20 and pd.notna(hyg_ief_1m) and hyg_ief_1m > 0:
        regime = "Risk-on"
    elif (pd.notna(vix_last) and vix_last > 22) or (pd.notna(spx_ytd) and spx_ytd < -3):
        regime = "Defensive"
    else:
        regime = "Mixed"

    leaders = ", ".join([f"{lab} ({val:+.1f}%)" for lab, val in sector_perf[:3]]) if sector_perf else "No clear leaders yet"
    laggards = ", ".join([f"{lab} ({val:+.1f}%)" for lab, val in sector_perf[-2:]]) if len(sector_perf) >= 2 else "No laggards yet"

    if pd.isna(tnx_1m):
        rates_text = "Rates pressure is unavailable."
    elif tnx_1m > 15:
        rates_text = f"The 10Y yield is up {_fmt_bps(tnx_1m)} over the last month, which can pressure long-duration equity valuations."
    elif tnx_1m < -15:
        rates_text = f"The 10Y yield is down {_fmt_bps(tnx_1m)} over the last month, which is a friendlier backdrop for growth multiples."
    else:
        rates_text = f"The 10Y yield has moved {_fmt_bps(tnx_1m)} over the last month, suggesting rates are not the dominant driver right now."

    if pd.isna(vix_last):
        vol_text = "Volatility data is unavailable."
    elif vix_last < 18:
        vol_text = f"VIX at {vix_last:.1f} points to a relatively contained volatility backdrop."
    elif vix_last < 22:
        vol_text = f"VIX at {vix_last:.1f} suggests a watchful, but not fully stressed, risk environment."
    else:
        vol_text = f"VIX at {vix_last:.1f} signals a more defensive tone and a higher premium on risk control."

    dollar_text = f"DXY is {_fmt_pct(dxy_ytd)} YTD." if pd.notna(dxy_ytd) else "Dollar trend is unavailable."

    return f"""
    <div style='line-height:1.7;color:#334155;'>
      <p><strong>Current regime:</strong> {regime}. The S&amp;P 500 is {_fmt_pct(spx_ytd)} YTD, positive sectors account for {positive_sector_count} of {len(sector_perf)} tracked groups, and credit-vs-Treasury performance is {_fmt_pct(hyg_ief_1m)} over the last month.</p>
      <p><strong>Leadership:</strong> {html.escape(leaders)}. <strong>Laggards:</strong> {html.escape(laggards)}.</p>
      <p><strong>Rates &amp; volatility:</strong> {html.escape(rates_text)} {html.escape(vol_text)} {html.escape(dollar_text)}</p>
      <p><strong>Read-through:</strong> This section is designed to show whether the market backdrop is broadening, narrowing, or becoming more defensive so the Forecasting page is viewed in the right macro context.</p>
    </div>
    """


def build_markets_dashboard_html(existing_index_chart_html):
    price_df = _safe_close_download(MARKET_DASHBOARD_TICKERS, period="2y")
    if price_df.empty:
        return f"""
        <div class='section-card'>
          <div class='section-title'><h2>Markets &amp; Indexes</h2></div>
          <p>Interactive comparison across the tracked market/index benchmarks.</p>
          {existing_index_chart_html}
        </div>
        """

    print(" Market dashboard columns:", list(price_df.columns))
    print(" Market dashboard rows:", len(price_df))

    snapshot_html = _build_market_snapshot_html(price_df)
    equity_risk_html = _build_equity_risk_chart_html(price_df)
    rates_credit_html = _build_rates_credit_chart_html(price_df)
    dollar_commodities_html = _build_dollar_commodities_chart_html(price_df)
    sector_rotation_html = _build_sector_rotation_chart_html(price_df)
    risk_html = _build_risk_dashboard_html(price_df)
    market_read_html = _build_market_read_html(price_df)

    quadrant_block = f"""
    <div class='quadrant-grid'>
      <div class='quadrant-card'>
        <h4 style='margin:0 0 8px 0;color:#0f172a;'>Equity Risk</h4>
        <p style='margin:0 0 10px 0;color:#475569;font-size:14px;'>How equity direction is behaving relative to implied volatility.</p>
        <div class='quadrant-chart'>{equity_risk_html}</div>
      </div>
      <div class='quadrant-card'>
        <h4 style='margin:0 0 8px 0;color:#0f172a;'>Rates &amp; Credit</h4>
        <p style='margin:0 0 10px 0;color:#475569;font-size:14px;'>10Y Treasury yields versus credit-sensitive relative strength.</p>
        <div class='quadrant-chart'>{rates_credit_html}</div>
      </div>
      <div class='quadrant-card'>
        <h4 style='margin:0 0 8px 0;color:#0f172a;'>Dollar vs Commodities</h4>
        <div class='quadrant-chart'>{dollar_commodities_html}</div>
      </div>
      <div class='quadrant-card'>
        <h4 style='margin:0 0 8px 0;color:#0f172a;'>Sector Rotation</h4>
        <p style='margin:0 0 10px 0;color:#475569;font-size:14px;'>YTD leadership and breadth across the major U.S. sector ETFs.</p>
        <div class='quadrant-chart'>{sector_rotation_html}</div>
      </div>
    </div>
    """

    return f"""
    <div class='section-card'>
      <div class='section-title'><h2>Markets &amp; Indexes</h2></div>
      <p>Cross-asset market dashboard with global indexes, risk signals, sector leadership, and a laptop-driven market read.</p>
      {snapshot_html}
    </div>

    <div class='section-card'>
      <h3>Global Index Comparison</h3>
      <p>Core comparison across the tracked benchmark indexes.</p>
      {existing_index_chart_html}
    </div>

    <div class='section-card'>
      <h3>Cross-Asset Risk &amp; Rotation</h3>
      <p>Four market lenses covering equity risk, rates/credit, dollar-versus-commodity relationships, and sector leadership.</p>
      {quadrant_block}
    </div>

    <div class='section-card'>
      <h3>Risk Dashboard</h3>
      {risk_html}
    </div>

    <div class='section-card'>
      <h3>Market Read</h3>
      {market_read_html}
    </div>
    """


def _normalize_news_df(df):
    cols = {c.lower(): c for c in df.columns}
    ticker_col = cols.get("ticker") or cols.get("symbol")
    title_col = cols.get("title") or cols.get("headline")
    url_col = cols.get("url") or cols.get("link")
    source_col = cols.get("source") or cols.get("publisher")
    published_col = cols.get("publishedat") or cols.get("published_at") or cols.get("published") or cols.get("date")
    summary_col = cols.get("summary") or cols.get("description") or cols.get("snippet") or cols.get("content")
    image_col = cols.get("imageurl") or cols.get("image_url") or cols.get("image") or cols.get("urltoimage")
    provider_col = cols.get("provider")
    story_id_col = cols.get("storyid")
    selection_count_col = cols.get("selectioncount")
    last_selected_at_col = cols.get("lastselectedat")
    last_selected_slot_col = cols.get("lastselectedslot")
    canonical_url_col = cols.get("canonicalurl")
    headline_key_col = cols.get("headlinekey")
    similarity_key_col = cols.get("similaritykey")

    out = pd.DataFrame({
        "Ticker": df[ticker_col] if ticker_col in df.columns else "",
        "Headline": df[title_col] if title_col in df.columns else "",
        "Summary": df[summary_col] if summary_col in df.columns else "",
        "Source": df[source_col] if source_col in df.columns else "",
        "PublishedAt": df[published_col] if published_col in df.columns else pd.NaT,
        "URL": df[url_col] if url_col in df.columns else "",
        "ImageURL": df[image_col] if image_col in df.columns else "",
        "Provider": df[provider_col] if provider_col in df.columns else "",
        "StoryID": df[story_id_col] if story_id_col in df.columns else "",
        "SelectionCount": df[selection_count_col] if selection_count_col in df.columns else 0,
        "LastSelectedAt": df[last_selected_at_col] if last_selected_at_col in df.columns else pd.NaT,
        "LastSelectedSlot": df[last_selected_slot_col] if last_selected_slot_col in df.columns else "",
        "CanonicalURL": df[canonical_url_col] if canonical_url_col in df.columns else "",
        "HeadlineKey": df[headline_key_col] if headline_key_col in df.columns else "",
        "SimilarityKey": df[similarity_key_col] if similarity_key_col in df.columns else "",
    }).copy()

    out["Ticker"] = out["Ticker"].fillna("").astype(str).str.strip().str.upper()
    out["Headline"] = out["Headline"].fillna("").astype(str).str.strip()
    out["Summary"] = out["Summary"].fillna("").astype(str).str.strip()
    out["Source"] = out["Source"].fillna("").astype(str).str.strip()
    out["URL"] = out["URL"].fillna("").astype(str).str.strip()
    out["ImageURL"] = out["ImageURL"].fillna("").astype(str).str.strip()
    out["Provider"] = out["Provider"].fillna("").astype(str).str.strip()
    out["StoryID"] = out["StoryID"].fillna("").astype(str).str.strip()
    out["SelectionCount"] = pd.to_numeric(out["SelectionCount"], errors="coerce").fillna(0).astype(int)
    out["LastSelectedAt"] = pd.to_datetime(out["LastSelectedAt"], errors="coerce", utc=True).dt.tz_convert(None)
    out["LastSelectedSlot"] = out["LastSelectedSlot"].fillna("").astype(str).str.strip()
    out["CanonicalURL"] = out["CanonicalURL"].fillna("").astype(str).str.strip()
    out["HeadlineKey"] = out["HeadlineKey"].fillna("").astype(str).str.strip()
    out["SimilarityKey"] = out["SimilarityKey"].fillna("").astype(str).str.strip()
    out["PublishedAt"] = pd.to_datetime(out["PublishedAt"], errors="coerce", utc=True).dt.tz_convert(None)

    out = out[out["Headline"] != ""].copy()

    def _title_key(x):
        return re.sub(r"[^a-z0-9]+", " ", str(x).lower()).strip()

    out["_title_key"] = out["Headline"].map(_title_key)
    missing_story = out["StoryID"] == ""
    if missing_story.any():
        fallback = (
            out.loc[missing_story, "Ticker"].astype(str)
            + "|" + out.loc[missing_story, "_title_key"].astype(str)
            + "|" + out.loc[missing_story, "URL"].astype(str)
        )
        out.loc[missing_story, "StoryID"] = fallback.map(lambda x: hashlib.sha1(x.encode("utf-8", errors="ignore")).hexdigest()[:16])
    if (out["URL"] != "").any():
        out = out.drop_duplicates(subset=["URL"], keep="first")
    out = out.drop_duplicates(subset=["Ticker", "_title_key"], keep="first")
    return out.drop(columns=["_title_key"])


def _story_source_score(source_name):
    src = str(source_name or "").strip().lower()
    scores = {
        "reuters": 8,
        "associated press": 7,
        "ap": 7,
        "ap news": 7,
        "bloomberg": 8,
        "financial times": 7,
        "the wall street journal": 7,
        "wall street journal": 7,
        "wsj": 7,
        "cnbc": 6,
        "barron's": 6,
        "marketwatch": 5,
        "the information": 5,
        "fortune": 4,
        "yahoo finance": 4,
        "seeking alpha": 4,
        "benzinga": 1,
        "marketscreener": 0,
        "economictimes": 0,
        "the times of india": 0,
        "yahoo entertainment": -2,
        "android authority": 0,
        "notebookcheck.net": 0,
        "free press journal": 0,
        "devdiscourse": -1,
        "macrumors": 0,
        "9to5mac": 0,
    }
    return scores.get(src, 2 if src else 0)


COMPANY_TOKENS = {
    "AAPL": ["apple", "iphone", "ios", "ipad", "mac", "tim cook"],
    "MSFT": ["microsoft", "azure", "windows", "xbox", "satya nadella"],
    "AMZN": ["amazon", "aws", "prime", "andy jassy"],
    "NVDA": ["nvidia", "gpu", "data center", "jensen huang", "chip"],
    "GOOG": ["google", "alphabet", "youtube", "waymo", "gemini"],
    "META": ["meta", "facebook", "instagram", "whatsapp", "threads", "zuckerberg"],
    "TSLA": ["tesla", "elon musk", "musk", "ev", "autopilot", "deliveries"],
    "MARKET": ["federal reserve", "fed", "inflation", "cpi", "ppi", "yield", "treasury", "payroll", "jobs", "tariff", "gdp", "oil", "recession"],
}

MARKET_KEYWORDS = {
    "federal reserve": 8,
    "fed": 8,
    "fomc": 8,
    "inflation": 7,
    "cpi": 7,
    "ppi": 6,
    "treasury": 6,
    "yield": 6,
    "rates": 5,
    "payroll": 6,
    "jobs": 5,
    "gdp": 5,
    "tariff": 6,
    "sanction": 5,
    "oil": 4,
    "recession": 6,
}

MATERIAL_KEYWORDS = {
    "earnings": 8,
    "guidance": 8,
    "outlook": 6,
    "revenue": 6,
    "profit": 6,
    "margin": 5,
    "demand": 5,
    "deliveries": 6,
    "forecast": 5,
    "capex": 5,
    "ai": 5,
    "chip": 5,
    "data center": 5,
    "cloud": 5,
    "antitrust": 7,
    "doj": 6,
    "ftc": 6,
    "lawsuit": 5,
    "regulation": 5,
    "recall": 6,
    "production": 5,
    "partnership": 4,
    "estimate": 4,
    "downgrade": 4,
    "upgrade": 3,
}

FLUFF_KEYWORDS = {
    "review": 8,
    "hands-on": 7,
    "arcade": 7,
    "games": 6,
    "widget": 6,
    "how to": 6,
    "guide": 6,
    "tips": 5,
    "best ": 4,
    "versus": 5,
    " vs ": 5,
    "app update": 5,
    "coupon": 8,
    "deal": 7,
    "deals": 7,
    "free shipping": 7,
    "subscribe & save": 7,
    "prime day": 6,
    "under $": 5,
}

LOW_SIGNAL_SOURCES = {
    "dealnews": 10,
    "dealnews.com": 10,
    "slickdeals": 10,
}

TICKER_FALSE_POSITIVE_PHRASES = {
    "AAPL": ["big apple", "new yorkers", "nyc"],
}

LOW_SIGNAL_PATTERNS = [
    r"\bpypi\.org\b",
    r"\bslashdot\b",
    r"\bslickdeals?\b",
    r"\bdealnews\b",
    r"\bforum\b",
    r"\bthread\b",
    r"^\(pr\)",
]


def _contains_term(text, term):
    txt = str(text or "").lower()
    token = str(term or "").lower().strip()
    if not token:
        return False
    if re.search(r"[a-z0-9]", token) is None:
        return token in txt
    if " " in token or any(ch in token for ch in "/&.-"):
        return token in txt
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", txt) is not None


def _contains_any_term(text, terms):
    return any(_contains_term(text, term) for term in terms)


def _keyword_score(text, weights):
    score = 0
    hits = []
    for key, wt in weights.items():
        if _contains_term(text, key):
            score += wt
            hits.append(key)
    return score, hits


def _ticker_noise_adjustment(ticker, text, source_name):
    ticker = str(ticker or "").upper()
    src = str(source_name or "").strip().lower()

    penalty = 0
    notes = []

    for phrase in TICKER_FALSE_POSITIVE_PHRASES.get(ticker, []):
        if _contains_term(text, phrase):
            penalty += 25
            notes.append(phrase)

    if ticker == "AMZN":
        deal_terms = [
            "coupon", "free shipping", "subscribe & save", "deal", "deals",
            "buy now", "under local prices", "prime day", "sale"
        ]
        if _contains_any_term(text, deal_terms):
            penalty += 18
            notes.append("consumer-deal")
        if src in LOW_SIGNAL_SOURCES:
            penalty += LOW_SIGNAL_SOURCES[src]
            notes.append(src)

    return penalty, notes


def _story_kind(text):
    if _contains_any_term(text, ["earnings", "guidance", "outlook", "revenue", "margin"]):
        return "earnings"
    if _contains_any_term(text, ["federal reserve", "fed", "inflation", "cpi", "yield", "rates", "payroll", "jobs", "gdp", "tariff"]):
        return "macro"
    if _contains_any_term(text, ["antitrust", "doj", "ftc", "lawsuit", "regulation", "sanction", "exploit", "patch", "breach", "security"]):
        return "regulation"
    if _contains_any_term(text, ["ai", "chip", "data center", "cloud", "product", "launch", "partnership"]):
        return "strategy"
    if _contains_any_term(text, ["deliveries", "production", "recall", "demand"]):
        return "operations"
    return "general"


def _story_reason(row):
    kind = row.get("StoryKind", "general")
    ticker = row.get("Ticker", "")
    if ticker == "MARKET" or kind == "macro":
        return "Why it matters: macro and rates-sensitive headlines can shift broad market risk appetite and index valuations."
    if kind == "earnings":
        return "Why it matters: earnings and guidance headlines can quickly reset expectations for both the stock and broader mega-cap sentiment."
    if kind == "regulation":
        return "Why it matters: legal and regulatory headlines can affect valuation, business flexibility, and near-term investor confidence."
    if kind == "operations":
        return "Why it matters: demand, production, or delivery headlines can change short-term revenue expectations and price momentum."
    if kind == "strategy":
        return "Why it matters: AI, cloud, product, or strategic headlines can influence growth expectations and future market leadership."
    return "Why it matters: this story appears more relevant than routine coverage and could influence near-term positioning."


def _time_ago(ts):
    if pd.isna(ts):
        return ""
    delta = datetime.now() - ts
    hours = max(int(delta.total_seconds() // 3600), 0)
    if hours < 1:
        mins = max(int(delta.total_seconds() // 60), 1)
        return f"{mins}m ago"
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _looks_english(text):
    txt = str(text or "").strip()
    if not txt:
        return False
    letters = sum(ch.isalpha() for ch in txt)
    if letters == 0:
        return False
    ascii_letters = sum((('a' <= ch.lower() <= 'z')) for ch in txt if ch.isalpha())
    return (ascii_letters / letters) >= 0.85


NEWS_SELECTION_STATE_PATH = os.path.join("data", "news_selection_state.json")

MIN_WINNER_SCORE = {
    "MARKET": 12.0,
    "AAPL": 13.0,
    "MSFT": 12.0,
    "AMZN": 11.0,
    "NVDA": 11.0,
    "GOOG": 13.0,
    "META": 11.0,
    "TSLA": 13.5,
}



def _row_age_hours(row_or_ts):
    ts = row_or_ts
    if isinstance(row_or_ts, pd.Series):
        ts = row_or_ts.get("PublishedAt", pd.NaT)
    if pd.isna(ts):
        return float("inf")
    return max((datetime.now() - pd.Timestamp(ts)).total_seconds() / 3600.0, 0.0)


def _selection_penalty(row):
    selection_count = int(pd.to_numeric(row.get("SelectionCount", 0), errors="coerce") or 0)
    penalty = min(selection_count, 4) * 0.35

    last_selected_at = row.get("LastSelectedAt", pd.NaT)
    if pd.notna(last_selected_at):
        hours_since = _row_age_hours(last_selected_at)
        if hours_since < 24:
            penalty += max(0.0, 0.75 - (hours_since / 24.0) * 0.75)
    return penalty


def _state_story_payload(row, slot_name, replacement_reason):
    published_at = row.get("PublishedAt", pd.NaT)
    selected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "slot": slot_name,
        "story_id": str(row.get("StoryID", "")),
        "ticker": str(row.get("Ticker", "")),
        "headline": str(row.get("Headline", "")),
        "url": str(row.get("URL", "")),
        "score": float(row.get("StoryScore", np.nan)),
        "base_score": float(row.get("BaseStoryScore", np.nan)),
        "selection_penalty": float(row.get("SelectionPenalty", 0.0)),
        "published_at": pd.Timestamp(published_at).isoformat() if pd.notna(published_at) else "",
        "selected_at": selected_at,
        "selection_count": int(pd.to_numeric(row.get("SelectionCount", 0), errors="coerce") or 0),
        "replacement_reason": replacement_reason,
    }


def _resolve_selected_story(pool, slot_name, state_entry, max_age_hours=30.0, min_story_score=6.0):
    if pool is None or pool.empty:
        return None, None, "no_candidates"

    if "StoryID" not in pool.columns:
        pool = _normalize_news_df(pool)

    candidates = pool.sort_values(["StoryScore", "PublishedAt"], ascending=[False, False]).reset_index(drop=True)
    challenger = candidates.iloc[0]

    current = None
    current_story_id = str((state_entry or {}).get("story_id", "")).strip()
    if current_story_id:
        current_matches = candidates[candidates["StoryID"].astype(str) == current_story_id]
        if not current_matches.empty:
            current = current_matches.iloc[0]

    challenger_score = float(challenger.get("StoryScore", -999))
    if current is None:
        if challenger_score >= min_story_score:
            return challenger, challenger.get("StoryID", ""), "new_slot_or_missing_current"
        return None, None, "below_threshold"

    current_score = float(current.get("StoryScore", -999))
    current_age = _row_age_hours(current)
    challenger_age = _row_age_hours(challenger)
    score_gap = challenger_score - current_score
    freshness_gap = current_age - challenger_age
    current_selection_count = int(pd.to_numeric(current.get("SelectionCount", 0), errors="coerce") or 0)

    if current_score < min_story_score and challenger_score < min_story_score:
        return None, None, "no_high_confidence_story"
    if current_score < min_story_score and challenger_score >= min_story_score:
        return challenger, challenger.get("StoryID", ""), "replace_low_confidence_current"

    if str(challenger.get("StoryID", "")) == str(current.get("StoryID", "")):
        return current, current.get("StoryID", ""), "keep_current_best"

    if challenger_score < min_story_score:
        if current_age > max_age_hours:
            return None, None, "current_expired_no_challenger"
        return current, current.get("StoryID", ""), "keep_current_story"

    if current_age > max_age_hours and challenger_score >= (current_score - 1.0):
        return challenger, challenger.get("StoryID", ""), "replace_expired_story"
    if score_gap >= 2.75:
        return challenger, challenger.get("StoryID", ""), "replace_higher_score"
    if freshness_gap >= 8.0 and challenger_score >= (current_score + 0.25):
        return challenger, challenger.get("StoryID", ""), "replace_much_fresher_story"
    if current_selection_count >= 3 and freshness_gap >= 4.0 and challenger_score >= (current_score + 0.1):
        return challenger, challenger.get("StoryID", ""), "rotate_repeated_story"

    return current, current.get("StoryID", ""), "keep_current_story"


def _select_persistent_news(scored, max_per_ticker=3):
    state = load_news_selection_state(NEWS_SELECTION_STATE_PATH)
    selected_rows = {}
    related_rows = {}
    selections_for_store = {}
    next_state = {}

    market_pool = scored[scored["Ticker"] == "MARKET"].copy()
    if market_pool.empty:
        broad = scored[scored["MatchedTerms"].astype(str).str.len() > 0].copy()
        market_pool = broad if not broad.empty else scored.copy()
    if not market_pool.empty:
        strong_market_pool = market_pool[market_pool.apply(_is_high_signal_story, axis=1)].copy()
        if not strong_market_pool.empty:
            market_pool = strong_market_pool
    market_story, market_story_id, market_reason = _resolve_selected_story(
        market_pool,
        "market_top",
        state.get("market_top", {}),
        max_age_hours=24.0,
        min_story_score=MIN_WINNER_SCORE.get("MARKET", 12.0),
    )
    if market_story is not None:
        selected_rows["market_top"] = market_story
        selections_for_store["market_top"] = market_story_id
        next_state["market_top"] = _state_story_payload(market_story, "market_top", market_reason)
        related_rows["market_top"] = market_pool[market_pool["StoryID"].astype(str) != str(market_story_id)].head(3).copy()
    else:
        related_rows["market_top"] = pd.DataFrame(columns=scored.columns)

    for ticker in MAG7:
        slot_name = f"ticker_top::{ticker}"
        sub = scored[scored["Ticker"] == ticker].copy()
        if not sub.empty:
            sub = sub[sub.apply(_is_high_signal_story, axis=1)].copy()
            sub = sub.sort_values(["StoryScore", "PublishedAt"], ascending=[False, False])
        story, story_id, story_reason = _resolve_selected_story(
            sub,
            slot_name,
            state.get(slot_name, {}),
            max_age_hours=30.0,
            min_story_score=MIN_WINNER_SCORE.get(ticker, 11.0),
        )
        if story is not None:
            selected_rows[slot_name] = story
            selections_for_store[slot_name] = story_id
            next_state[slot_name] = _state_story_payload(story, slot_name, story_reason)
            related_rows[slot_name] = sub[sub["StoryID"].astype(str) != str(story_id)].head(max(max_per_ticker - 1, 0)).copy()
        else:
            related_rows[slot_name] = pd.DataFrame(columns=scored.columns)

    save_news_selection_state(next_state, NEWS_SELECTION_STATE_PATH)
    return selected_rows, related_rows, selections_for_store


def _score_news_row(row):
    headline = str(row.get("Headline", ""))
    summary = str(row.get("Summary", ""))
    text = f"{headline} {summary}".lower()
    ticker = str(row.get("Ticker", "")).upper()
    source_name = row.get("Source", "")

    score = 0
    score += _story_source_score(source_name)

    market_score, market_hits = _keyword_score(text, MARKET_KEYWORDS)
    material_score, material_hits = _keyword_score(text, MATERIAL_KEYWORDS)
    fluff_penalty, fluff_hits = _keyword_score(text, FLUFF_KEYWORDS)
    noise_penalty, noise_hits = _ticker_noise_adjustment(ticker, text, source_name)

    score += market_score + material_score
    score -= fluff_penalty
    score -= noise_penalty

    tokens = COMPANY_TOKENS.get(ticker, [])
    token_hits = [tok for tok in tokens if _contains_term(text, tok)]
    if ticker and ticker != "MARKET":
        if token_hits:
            score += 4
        else:
            score -= 10

    if ticker == "MARKET" and market_score == 0:
        score -= 6

    ts = row.get("PublishedAt", pd.NaT)
    if pd.notna(ts):
        age_hours = max((datetime.now() - ts).total_seconds() / 3600.0, 0.0)
        score += max(0.0, 6.0 - min(age_hours, 6.0))

    base_score = float(score)
    selection_penalty = _selection_penalty(row)
    score -= selection_penalty

    kind = _story_kind(text)
    return pd.Series({
        "StoryScore": float(score),
        "BaseStoryScore": base_score,
        "SelectionPenalty": float(selection_penalty),
        "StoryKind": kind,
        "StoryReason": _story_reason({"Ticker": ticker, "StoryKind": kind}),
        "MatchedTerms": ", ".join((market_hits + material_hits + token_hits)[:5]),
        "FluffHits": ", ".join((fluff_hits + noise_hits)[:4]),
    })


def _is_high_signal_story(row):
    ticker = str(row.get("Ticker", "")).upper()
    score = float(row.get("StoryScore", -999))
    kind = str(row.get("StoryKind", "general")).lower()
    headline = str(row.get("Headline", ""))
    summary = str(row.get("Summary", ""))
    source = str(row.get("Source", "")).strip().lower()
    text = f"{headline} {summary}".lower()

    if score < 6:
        return False
    if not _looks_english(headline):
        return False

    if any(re.search(pattern, text) for pattern in LOW_SIGNAL_PATTERNS):
        return False

    if ticker == "MARKET":
        if source in {"marketscreener", "yahoo entertainment", "economictimes", "the times of india"} and score < 15:
            return False
        macro_terms = ["federal reserve", "fed", "inflation", "cpi", "yield", "rates", "payroll", "jobs", "gdp", "treasury", "credit", "oil", "dollar", "tariff", "recession"]
        if not _contains_any_term(text, macro_terms):
            return False

    if ticker == "AAPL":
        if _contains_any_term(text, ["big apple", "new yorkers", "nyc"]):
            return False
        apple_terms = ["apple", "iphone", "ipad", "ios", "mac", "airpods", "watch", "tim cook"]
        if not _contains_any_term(text, apple_terms):
            return False
        if _contains_any_term(text, ["price", "priced", "specifications", "colours", "colors", "pre-order", "preorder", "launch date", "under ", "under rs", "under $", "feature roundup"]) and not _contains_any_term(text, ["revenue", "earnings", "guidance", "services", "china", "regulation", "tariff", "supply chain", "production"]):
            return False
        if _contains_any_term(text, ["amazon.com", "prime day", "free shipping", "deal", "deals", "coupon"]) and kind == "general":
            return False

    if ticker == "AMZN":
        deal_terms = [
            "coupon", "free shipping", "subscribe & save", "deal", "deals",
            "buy now", "under local prices", "prime day", "sale", "tool only",
            "portable air inflator", "prime visa", "1 replies", "count box",
            "save + free shipping", "cashback", "slickdeals", "dealnews", "price of $",
            "price $", "under $", "off at amazon", "for $", "shop now", "prime members"
        ]
        signal_terms = [
            "aws", "andy jassy", "earnings", "guidance", "revenue", "margin",
            "outlook", "capex", "ai", "cloud", "antitrust", "doj", "ftc",
            "regulation", "lawsuit", "partnership", "advertising", "ad business",
            "prime video", "buy with prime", "data center", "fulfillment", "logistics"
        ]
        if source in LOW_SIGNAL_SOURCES or source in {"amazon.com", "slickdeals.net", "dealnews.com"}:
            return False
        if _contains_any_term(text, deal_terms):
            return False
        if not _contains_any_term(text, signal_terms):
            return False

    if ticker not in ("", "MARKET"):
        if kind == "general" and score < 12:
            return False

    if ticker in {"GOOG", "META", "MSFT"}:
        if any(re.search(pattern, text) for pattern in [r"\bmeta-[a-z0-9_-]+\b", r"\bgoogle-[a-z0-9_-]+\b", r"\bmicrosoft-[a-z0-9_-]+\b"]):
            return False

    return True


def _render_story_image(image_url, label, href=""):
    image_url = str(image_url or "").strip()
    label = html.escape(str(label or "Story"))
    if image_url:
        img = (
            f"<img src='{html.escape(image_url)}' alt='{label}' "
            "style='width:100%;height:220px;object-fit:cover;border-radius:12px 12px 0 0;' "
            "onerror=\"this.style.display='none'; this.nextElementSibling.style.display='flex';\">"
            f"<div style='display:none;height:220px;align-items:center;justify-content:center;background:linear-gradient(135deg,#1e3a8a,#60a5fa);color:white;font-size:28px;font-weight:700;border-radius:12px 12px 0 0;'>{label}</div>"
        )
    else:
        img = f"<div style='display:flex;height:220px;align-items:center;justify-content:center;background:linear-gradient(135deg,#1e3a8a,#60a5fa);color:white;font-size:28px;font-weight:700;border-radius:12px 12px 0 0;'>{label}</div>"

    if href:
        return f"<a href='{html.escape(href)}' target='_blank' rel='noopener noreferrer' style='display:block;text-decoration:none;'>{img}</a>"
    return img


def _render_story_card(row, title_prefix=None, compact=False, related_rows=None):
    if row is None or len(row) == 0:
        return ""

    headline = html.escape(str(row.get("Headline", "Headline")))
    url = html.escape(str(row.get("URL", "")))
    source = html.escape(str(row.get("Source", "")))
    summary = str(row.get("Summary", "")).strip()
    if summary:
        summary = html.escape(summary[:220] + ("" if len(summary) > 220 else ""))
    else:
        summary = "No article summary available yet."
    meta = "  ".join([x for x in [source, _time_ago(row.get("PublishedAt", pd.NaT))] if x])
    why = html.escape(str(row.get("StoryReason", "")))
    label = title_prefix or str(row.get("Ticker", "Story"))

    if compact:
        image_html = _render_story_image(row.get("ImageURL", ""), label, row.get("URL", ""))
        parts = [
            "<div style='border:1px solid #d7dbe5;border-radius:14px;background:#fff;overflow:hidden;box-shadow:0 3px 12px rgba(15,23,42,0.05);'>",
            image_html,
            "<div style='padding:14px 16px 16px 16px;'>",
            f"<div style='font-size:12px;font-weight:700;color:#1d4ed8;text-transform:uppercase;letter-spacing:.03em;margin-bottom:6px;'>{html.escape(label)}</div>",
            f"<h3 style='margin:0 0 8px 0;font-size:20px;line-height:1.3;'><a href='{url}' target='_blank' rel='noopener noreferrer' style='color:#0f172a;text-decoration:none;'>{headline}</a></h3>",
            f"<div style='font-size:12px;color:#64748b;margin-bottom:10px;'>{meta}</div>",
            f"<p style='margin:0 0 10px 0;color:#334155;line-height:1.6;'>{summary}</p>",
            f"<p style='margin:0;color:#0f172a;line-height:1.6;'><strong>Why it matters:</strong> {why.replace('Why it matters: ', '')}</p>",
        ]
        if related_rows is not None and len(related_rows) > 0:
            parts.append("<div style='margin-top:14px;padding-top:12px;border-top:1px solid #e5e7eb;'>")
            parts.append("<div style='font-size:12px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:.03em;margin-bottom:8px;'>Other relevant coverage</div><ul style='margin:0;padding-left:18px;'>")
            for _, r in related_rows.iterrows():
                rh = html.escape(str(r.get("Headline", "Headline")))
                ru = html.escape(str(r.get("URL", "")))
                rs = html.escape(str(r.get("Source", "")))
                rt = _time_ago(r.get("PublishedAt", pd.NaT))
                rmeta = "  ".join([x for x in [rs, rt] if x])
                if ru:
                    parts.append(f"<li style='margin:0 0 6px 0;'><a href='{ru}' target='_blank' rel='noopener noreferrer'>{rh}</a><span style='color:#64748b;font-size:12px;'> ({rmeta})</span></li>")
                else:
                    parts.append(f"<li style='margin:0 0 6px 0;'>{rh}<span style='color:#64748b;font-size:12px;'> ({rmeta})</span></li>")
            parts.append("</ul></div>")
        parts.append("</div></div>")
        return "".join(parts)

    return ""


def _render_empty_story_card(ticker):
    return (
        "<div style='border:1px solid #d7dbe5;border-radius:14px;background:#fff;overflow:hidden;box-shadow:0 3px 12px rgba(15,23,42,0.05);'>"
        f"<div style='display:flex;height:220px;align-items:center;justify-content:center;background:linear-gradient(135deg,#cbd5e1,#94a3b8);color:#0f172a;font-size:28px;font-weight:700;border-radius:12px 12px 0 0;'>{html.escape(ticker)}</div>"
        "<div style='padding:14px 16px 16px 16px;'>"
        f"<div style='font-size:12px;font-weight:700;color:#1d4ed8;text-transform:uppercase;letter-spacing:.03em;margin-bottom:6px;'>{html.escape(ticker)} top story</div>"
        "<h3 style='margin:0 0 8px 0;font-size:20px;line-height:1.3;color:#0f172a;'>No high-signal story surfaced</h3>"
        "<div style='font-size:12px;color:#64748b;margin-bottom:10px;'>Coverage filtered for relevance and business signal</div>"
        "<p style='margin:0;color:#334155;line-height:1.6;'>This slot is intentionally left blank when available stories are irrelevant to market data and movement.</p>"
        "</div></div>"
    )


def build_news_html(csv_path="data/news_headlines.csv", lookback_hours=48, max_per_ticker=3):
    store_path = os.path.join("data", "news_store.parquet")
    store_df = load_news_store(store_path, retention_hours=lookback_hours)

    if not store_df.empty:
        raw_df = store_df.copy()
    else:
        if not os.path.exists(csv_path):
            return "<div class='section-title'><h2>Market News</h2></div><p>No news file found.</p>"
        try:
            raw_df = pd.read_csv(csv_path)
        except Exception as e:
            return f"<div class='section-title'><h2>Market News</h2></div><p>Could not read news file: {e}</p>"

    if raw_df.empty:
        return "<div class='section-title'><h2>Market News</h2></div><p>No headlines available.</p>"

    df = _normalize_news_df(raw_df)
    cutoff = datetime.now() - timedelta(hours=lookback_hours)
    df = df[df["PublishedAt"].isna() | (df["PublishedAt"] >= cutoff)].copy()

    if df.empty:
        return f"<div class='section-title'><h2>Market News</h2></div><p>No headlines in the last {lookback_hours} hours.</p>"

    scored = df.join(df.apply(_score_news_row, axis=1))
    if "StoryID" not in scored.columns or scored["StoryID"].astype(str).eq("").any():
        rescored_base = _normalize_news_df(scored)
        scored = rescored_base.join(rescored_base.apply(_score_news_row, axis=1))
    scored = scored.sort_values(["StoryScore", "PublishedAt"], ascending=[False, False]).copy()

    selected_rows, related_rows, selections_for_store = _select_persistent_news(scored, max_per_ticker=max_per_ticker)

    if not store_df.empty and selections_for_store:
        updated_store = mark_selected_stories(store_df, selections_for_store)
        save_news_store(updated_store, store_path)
        export_news_snapshot(updated_store, csv_path)

    market_story = selected_rows.get("market_top")

    parts = [
        "<div class='section-title'><h2>Market News Intelligence</h2></div>",
        f"<p style='color:#475569;margin-top:-6px;'>Curated from the last {lookback_hours} hours using source quality, market relevance, business-impact filters, and persistent keep-vs-replace rules so strong stories stay in view until a meaningfully better one appears.</p>",
    ]

    if market_story is not None:
        related_market = related_rows.get("market_top", pd.DataFrame(columns=scored.columns))
        parts.append("<div style='margin-top:14px;'>")
        parts.append(_render_story_card(market_story, title_prefix="Top Market Story of the Day", compact=True, related_rows=related_market))
        parts.append("</div>")

    parts.append("<div style='margin-top:26px;'><h2 style='margin:0 0 10px 0;color:#0f172a;'>MAG7 Watchlist</h2><p style='color:#475569;margin:0 0 14px 0;'>One top story per stock, with smaller related links underneath. New stories replace current winners only when they are materially stronger, much fresher, or the existing story has become stale.</p></div>")
    parts.append("<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px;'>")

    for ticker in MAG7:
        slot_name = f"ticker_top::{ticker}"
        top_row = selected_rows.get(slot_name)
        if top_row is None:
            parts.append(_render_empty_story_card(ticker))
            continue
        related = related_rows.get(slot_name, pd.DataFrame(columns=scored.columns))
        parts.append(_render_story_card(top_row, title_prefix=f"{ticker} top story", compact=True, related_rows=related))

    parts.append("</div>")
    parts.append("<p style='margin:16px 0 0 0;color:#64748b;font-size:12px;'><em>Story selection is rule-based on the laptop. The goal is to surface material market and business drivers, not every mention of a company name.</em></p>")
    return "".join(parts)


def safe_pct(x):
    try:
        if pd.isna(x):
            return "N/A"
        return f"{float(x):.2f}%"
    except Exception:
        return "N/A"


def _first_existing_value(row, candidates, default=None):
    for col in candidates:
        if col in row.index and pd.notna(row[col]):
            return row[col]
    return default


def _clean_text_list(values):
    cleaned = []
    for value in values:
        if value is None:
            continue
        txt = str(value).strip()
        if txt:
            cleaned.append(txt)
    return cleaned


def _confidence_rank(value):
    val = str(value).strip().lower()
    return {"high": 3, "moderate": 2, "medium": 2, "low": 1}.get(val, 0)


def _safe_float_value(value, default=np.nan):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _build_market_summary(mag7_frame):
    consensus_values = []
    if "Consensus_Forecast" in mag7_frame.columns:
        consensus_values = [float(x) for x in mag7_frame["Consensus_Forecast"].dropna().tolist()]
    avg_consensus = float(np.mean(consensus_values)) if consensus_values else 0.0
    if avg_consensus > 0.01:
        market_regime = "constructive"
    elif avg_consensus < -0.01:
        market_regime = "defensive"
    else:
        market_regime = "mixed"
    strengths, risks = [], []
    if "Confidence_Label" in mag7_frame.columns:
        conf_counts = mag7_frame["Confidence_Label"].astype(str).str.lower().value_counts()
        if conf_counts.get("high", 0) >= 2:
            strengths.append("several MAG7 names carry high model confidence")
        if conf_counts.get("low", 0) >= 2 or conf_counts.get("medium",0) >= 3:
            risks.append("some MAG7 forecasts still carry lower confidence")
    if consensus_values:
        pos = sum(1 for x in consensus_values if x > 0)
        neg = sum(1 for x in consensus_values if x < 0)
        if pos >= max(4, len(consensus_values) - 1):
            strengths.append("most consensus forecasts remain positive")
        if neg >= 3:
            risks.append("multiple consensus forecasts are negative")
    if not strengths: strengths.append("some forecasts remain constructive across the tracked MAG7 names")
    if not risks: risks.append("forecast dispersion remains a watch point across models")
    return {"report_title":"EPM Quant Report","market_regime":market_regime,"top_strengths":_clean_text_list(strengths[:3]),"top_risks":_clean_text_list(risks[:3]),"notes":"This commentary is an interpretation layer built from the report's structured outputs."}


def _compute_model_agreement_label(row):
    forecasts = [
        _safe_float_value(_first_existing_value(row,["Linear Model Forecast (%)"])),
        _safe_float_value(_first_existing_value(row,["FF Forecast (%)"])),
        _safe_float_value(_first_existing_value(row,["Institutional Forecast (%)"])),
        _safe_float_value(_first_existing_value(row,["QuantConnect Forecast (%)"])),
        _safe_float_value(_first_existing_value(row,["ML Forecast (%)"])),
    ]
    valid=[x for x in forecasts if pd.notna(x)]
    if len(valid)<2: return "insufficient"
    positives=sum(1 for x in valid if x>0)
    negatives=sum(1 for x in valid if x<0)
    zeros=sum(1 for x in valid if x==0)
    if positives==len(valid) or negatives==len(valid): return "high"
    if max(positives, negatives)>=len(valid)-1: return "moderate"
    if zeros==len(valid): return "flat"
    return "low"


def _build_commentary_rows(mag7_frame, ytd_return_map):
    rows=[]
    for ticker in MAG7:
        if ticker not in mag7_frame.index:
            continue
        row=mag7_frame.loc[ticker]
        cons = _safe_float_value(_first_existing_value(row,["Consensus_Forecast"]), default=np.nan)
        rows.append({
            "ticker":ticker,
            "name":_first_existing_value(row,["Name","Company Name","Company","Full Name"],ticker),
            "price":_first_existing_value(row,["Price","Close","Last Price","Price/NAV"]),
            "ytd_return_pct":ytd_return_map.get(ticker, np.nan),
            "beta_3y":_first_existing_value(row,["Beta (3Y)","Beta","Beta 3Y"]),
            "sharpe_3y":_first_existing_value(row,["Sharpe Ratio (3Y)","Sharpe (3Y)","Sharpe"]),
            "ma200_signal":_first_existing_value(row,["MA200 Trend","MA200 Signal","200DMA Signal","MA 200 Signal"],""),
            "linear_forecast_21d_pct":_first_existing_value(row,["Linear Model Forecast (%)"]),
            "ff3_forecast_21d_pct":_first_existing_value(row,["FF Forecast (%)"]),
            "institutional_forecast_21d_pct":_first_existing_value(row,["Institutional Forecast (%)"]),
            "quantconnect_forecast_21d_pct":_first_existing_value(row,["QuantConnect Forecast (%)"]),
            "ml_forecast_21d_pct":_first_existing_value(row,["ML Forecast (%)"]),
            "consensus_forecast_pct": cons*100.0 if pd.notna(cons) else np.nan,
            "confidence_label":_first_existing_value(row,["Confidence_Label"],"N/A"),
            "winning_model":_first_existing_value(row,["Winning_Model"],"N/A"),
            "agreement_ratio":_safe_float_value(_first_existing_value(row,["Agreement_Ratio"]),default=np.nan),
            "model_agreement":_compute_model_agreement_label(row),
        })
    return rows


def _build_balanced_highlights(ticker_rows):
    ranked=[]
    for row in ticker_rows:
        consensus=_safe_float_value(row.get("consensus_forecast_pct"), default=np.nan)
        ranked.append({**row,"consensus_forecast_pct":consensus,"confidence_rank":_confidence_rank(row.get("confidence_label","N/A")),"agreement_ratio":_safe_float_value(row.get("agreement_ratio"), default=0.0)})
    bullish=[r for r in ranked if pd.notna(r["consensus_forecast_pct"]) and r["consensus_forecast_pct"]>0]
    bearish=[r for r in ranked if pd.notna(r["consensus_forecast_pct"]) and r["consensus_forecast_pct"]<0]
    bullish.sort(key=lambda r:(r["confidence_rank"],r["agreement_ratio"],r["consensus_forecast_pct"]), reverse=True)
    bearish.sort(key=lambda r:(r["confidence_rank"],r["agreement_ratio"],abs(r["consensus_forecast_pct"])), reverse=True)
    selected=[]; used=set()
    for row in bullish[:2]:
        rr=dict(row); rr["highlight_bias"]="bullish"; selected.append(rr); used.add(rr["ticker"])
    for row in bearish:
        if row["ticker"] not in used:
            rr=dict(row); rr["highlight_bias"]="bearish"; selected.append(rr); used.add(rr["ticker"]); break
    if len(selected)<3:
        remainder=[r for r in ranked if r["ticker"] not in used]
        remainder.sort(key=lambda r:(r["confidence_rank"],abs(r["consensus_forecast_pct"]) if pd.notna(r["consensus_forecast_pct"]) else -999,r["agreement_ratio"]), reverse=True)
        for row in remainder:
            rr=dict(row); rr["highlight_bias"]="bullish" if pd.notna(rr["consensus_forecast_pct"]) and rr["consensus_forecast_pct"]>=0 else "bearish"; selected.append(rr); used.add(rr["ticker"]);
            if len(selected)==3: break
    for row in selected:
        reasons=[]
        if pd.notna(row.get("consensus_forecast_pct")):
            direction="positive" if row["consensus_forecast_pct"]>=0 else "negative"
            reasons.append(f"consensus is {direction} at {row['consensus_forecast_pct']:.2f}%")
        conf=str(row.get("confidence_label",""))
        if conf and conf.lower()!="n/a": reasons.append(f"confidence is {conf.lower()}")
        model_agreement=str(row.get("model_agreement",""))
        if model_agreement: reasons.append(f"model agreement is {model_agreement.lower()}")
        row["highlight_reason"]="; ".join(reasons[:3])
    return selected[:3]

def _format_expected_highlight_bullets(top_highlights):
    bullets = []
    for row in top_highlights[:3]:
        bias = "Bullish" if str(row.get("highlight_bias", "")).lower() == "bullish" else "Bearish"
        ticker = str(row.get("ticker", "")).strip()
        reason = str(row.get("highlight_reason", "")).strip()
        if reason and not reason.endswith("."):
            reason += "."
        bullets.append(f"{bias}  {ticker}: {reason}")
    return bullets


def _format_all_mag7_bullets(ticker_rows):
    """Generate one bullet per ticker — used for the MAG7 signal summary box."""
    bullets = []
    for row in ticker_rows:
        val = _safe_float_value(row.get("consensus_forecast_pct"), default=np.nan)
        bias = "Bullish" if pd.notna(val) and val >= 0 else "Bearish"
        ticker = str(row.get("ticker", "")).strip()
        reasons = []
        if pd.notna(val):
            direction = "positive" if val >= 0 else "negative"
            reasons.append(f"consensus is {direction} at {val:.2f}%")
        conf = str(row.get("confidence_label", ""))
        if conf and conf.lower() != "n/a":
            reasons.append(f"confidence is {conf.lower()}")
        model_agreement = str(row.get("model_agreement", ""))
        if model_agreement:
            reasons.append(f"model agreement is {model_agreement.lower()}")
        reason = "; ".join(reasons[:3])
        if reason and not reason.endswith("."):
            reason += "."
        bullets.append(f"{bias}  {ticker}: {reason}")
    return bullets

def _bullets_need_replacement(bullets, top_highlights):
    if not isinstance(bullets, list) or len(bullets) != 3:
        return True

    expected_tickers = [str(x.get("ticker", "")).strip().upper() for x in top_highlights[:3]]

    for i, bullet in enumerate(bullets):
        b = str(bullet).strip()
        if not b:
            return True
        if "bullish" not in b.lower() and "bearish" not in b.lower():
            return True
        if expected_tickers[i] and expected_tickers[i] not in b.upper():
            return True
        if ":" not in b and "because" not in b.lower():
            return True

    return False

def _load_cached_commentary(path=COMMENTARY_JSON_PATH):
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        print(f" Could not load cached commentary: {e}")
        return None

def _render_commentary_unavailable_html(reason="AI commentary unavailable for this run."):
    return (
        "<div style='margin:16px 0 24px 0;padding:18px;border:1px solid #d9e2f0;border-radius:12px;background:#f8fbff;'>"
        "<h3 style='margin-top:0;color:#1e2a44;'>AI Commentary</h3>"
        f"<p style='margin:0;color:#4b5563;line-height:1.6;'>{html.escape(str(reason))}</p>"
        "<p style='margin:14px 0 0 0;color:#667085;font-size:12px;'><em>Interpretation layer only. Forecast tables remain the source of truth.</em></p>"
        "</div>"
    )



def _clean_commentary_text(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("text", "summary", "overview", "reflection", "commentary"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return " ".join(candidate.strip().split())
        return ""
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            cleaned = _clean_commentary_text(item)
            if cleaned:
                parts.append(cleaned)
        return " ".join(parts).strip()
    return " ".join(str(value).strip().split())



def _normalize_commentary_data(commentary_data, top_highlights=None):
    if not isinstance(commentary_data, dict):
        return commentary_data

    data = dict(commentary_data)
    overview = _clean_commentary_text(data.get("portfolio_overview", ""))
    reflection = _clean_commentary_text(data.get("market_reflection") or data.get("what_this_suggests", ""))
    bullets = [_clean_commentary_text(x) for x in data.get("top_bullets", []) if _clean_commentary_text(x)]

    if top_highlights and _bullets_need_replacement(bullets, top_highlights):
        bullets = _format_expected_highlight_bullets(top_highlights)

    deduped_bullets = []
    seen_bullets = set()
    for bullet in bullets:
        key = bullet.lower()
        if key in seen_bullets:
            continue
        deduped_bullets.append(bullet)
        seen_bullets.add(key)

    if overview and reflection and overview.lower() == reflection.lower():
        reflection = ""

    data["portfolio_overview"] = overview
    data["top_bullets"] = deduped_bullets
    data["market_reflection"] = reflection
    if "what_this_suggests" in data and reflection:
        data["what_this_suggests"] = reflection
    elif "what_this_suggests" in data and not reflection:
        data["what_this_suggests"] = ""
    return data


def _commentary_is_valid(commentary_data):
    if not isinstance(commentary_data, dict):
        return False

    overview = _clean_commentary_text(commentary_data.get("portfolio_overview", ""))
    bullets = [_clean_commentary_text(x) for x in commentary_data.get("top_bullets", []) if _clean_commentary_text(x)]
    reflection = _clean_commentary_text(commentary_data.get("market_reflection") or commentary_data.get("what_this_suggests", ""))

    placeholder_texts = {
        "this is a sample portfolio overview.",
        "this is a market reflection.",
        "item 1",
        "item 2",
        "item 3",
    }

    combined = [overview.lower(), reflection.lower()] + [b.lower() for b in bullets]
    if any(x in placeholder_texts for x in combined):
        return False

    substantive_sections = sum(bool(x) for x in [overview, reflection]) + (1 if bullets else 0)
    return substantive_sections >= 2


def _build_deterministic_commentary_data(market_summary, top_highlights, ticker_rows):
    top_highlights = top_highlights or []
    ticker_rows = ticker_rows or []

    consensus_vals = []
    bullish = 0
    bearish = 0
    agreement_counts = {}
    for row in ticker_rows:
        val = _safe_float_value(row.get("consensus_forecast_pct"), default=np.nan)
        if pd.notna(val):
            consensus_vals.append(val)
            if val > 0:
                bullish += 1
            elif val < 0:
                bearish += 1
        label = str(row.get("model_agreement", "")).strip().lower()
        if label:
            agreement_counts[label] = agreement_counts.get(label, 0) + 1

    avg_consensus = np.nanmean(consensus_vals) if consensus_vals else np.nan
    dominant_agreement = max(agreement_counts, key=agreement_counts.get) if agreement_counts else "mixed"

    overview_parts = []
    if pd.notna(avg_consensus):
        if bullish > bearish:
            overview_parts.append(f"MAG7 signals lean constructive overall, but breadth is not uniform, with {bullish} bullish names versus {bearish} bearish.")
        elif bearish > bullish:
            overview_parts.append(f"MAG7 signals skew defensive overall, with {bearish} bearish names versus {bullish} bullish.")
        else:
            overview_parts.append(f"MAG7 signals are mixed overall, with breadth split at {bullish} bullish and {bearish} bearish names.")

        if avg_consensus >= 0:
            overview_parts.append(f"Consensus is still positive on balance at {avg_consensus:.2f}%, which suggests upside is concentrated rather than broad.")
        else:
            overview_parts.append(f"Consensus is negative on balance at {avg_consensus:.2f}%, which keeps the group on a cautious footing.")
    elif ticker_rows:
        overview_parts.append(f"MAG7 signals are mixed, with {dominant_agreement} model agreement the most common reading across the group.")
    overview = " ".join(overview_parts[:2]).strip()

    bullish_highlights = [row for row in top_highlights if str(row.get("highlight_bias", "")).strip().lower() == "bullish"]
    bearish_highlights = [row for row in top_highlights if str(row.get("highlight_bias", "")).strip().lower() == "bearish"]
    if bullish_highlights and bearish_highlights:
        leaders = ", ".join(str(r.get("ticker", "")).strip() for r in bullish_highlights if str(r.get("ticker", "")).strip())
        laggards = ", ".join(str(r.get("ticker", "")).strip() for r in bearish_highlights if str(r.get("ticker", "")).strip())
        reflection = f"Leadership is narrow, with strength concentrated in {leaders} while {laggards} still screen weaker. That points to selective opportunity rather than broad-based tech leadership."
    elif bullish_highlights:
        leaders = ", ".join(str(r.get("ticker", "")).strip() for r in bullish_highlights if str(r.get("ticker", "")).strip())
        reflection = f"Leadership is concentrated in {leaders}, which keeps the near-term tone constructive even if conviction is not yet broad across the whole group."
    elif bearish_highlights:
        laggards = ", ".join(str(r.get("ticker", "")).strip() for r in bearish_highlights if str(r.get("ticker", "")).strip())
        reflection = f"Weakness is concentrated in {laggards}, which keeps the broader MAG7 tone cautious until leadership broadens out again."
    else:
        reflection = "Leadership appears selective rather than broad, with conviction concentrated in a smaller set of names while the rest of the group remains less aligned."

    bullets = _format_all_mag7_bullets(ticker_rows) if ticker_rows else []

    return {
        "portfolio_overview": overview,
        "top_bullets": bullets,
        "market_reflection": reflection,
        "source": "deterministic_fallback",
    }


def _render_commentary_html(commentary_data):
    if not _commentary_is_valid(commentary_data):
        return _render_commentary_unavailable_html()

    commentary_data = _normalize_commentary_data(commentary_data)

    parts = [
        "<div style='margin:16px 0 24px 0;padding:18px;border:1px solid #d9e2f0;border-radius:12px;background:#f8fbff;'>",
        "<h3 style='margin-top:0;color:#1e2a44;'>AI Commentary</h3>"
    ]

    overview = _clean_commentary_text(commentary_data.get("portfolio_overview", ""))
    if overview:
        parts.append(
            f"<p style='margin:0 0 10px 0;color:#1f2937;line-height:1.6;'>{html.escape(overview)}</p>"
        )

    bullets = commentary_data.get("top_bullets", [])
    if bullets:
        parts.append("<p style='margin:0 0 10px 0;font-weight:600;color:#1e2a44;'>Top MAG7 Highlights</p>")
        parts.append("<ul>")
        for bullet in bullets:
            parts.append(f"<li>{html.escape(str(bullet))}</li>")
        parts.append("</ul>")

    reflection = _clean_commentary_text(
        commentary_data.get("market_reflection")
        or commentary_data.get("what_this_suggests", "")
    )
    if reflection:
        parts.append("<h4 style='margin:10px 0 6px 0;color:#1e2a44;'>What this suggests</h4>")
        parts.append(
            f"<p style='margin:0;color:#4b5563;line-height:1.6;'>{html.escape(reflection)}</p>"
        )

    parts.append(
        "<p style='margin:14px 0 0 0;color:#667085;font-size:12px;'><em>Interpretation layer only. Forecast tables remain the source of truth.</em></p>"
    )
    parts.append("</div>")
    return "".join(parts)

# Build MAG7 forecast model table
mag7_df = features_df[features_df["Ticker"].isin(MAG7)].copy()
mag7_df = mag7_df.drop_duplicates(subset=["Ticker"], keep="last")
mag7_df = mag7_df.set_index("Ticker")

# safer series fetches
ff_s = mag7_df["FF Forecast (%)"] if "FF Forecast (%)" in mag7_df.columns else pd.Series(index=MAG7, dtype=float)
qc_s = mag7_df["QuantConnect Forecast (%)"] if "QuantConnect Forecast (%)" in mag7_df.columns else pd.Series(index=MAG7, dtype=float)
inst_s = mag7_df["Institutional Forecast (%)"] if "Institutional Forecast (%)" in mag7_df.columns else pd.Series(index=MAG7, dtype=float)
lin_s = mag7_df["Linear Model Forecast (%)"] if "Linear Model Forecast (%)" in mag7_df.columns else pd.Series(index=MAG7, dtype=float)
ml_s = mag7_df["ML Forecast (%)"] if "ML Forecast (%)" in mag7_df.columns else pd.Series(index=MAG7, dtype=float)
arx_s = mag7_df["ARIMAX Forecast (%)"] if "ARIMAX Forecast (%)" in mag7_df.columns else pd.Series(index=MAG7, dtype=float)
dl_s = mag7_df["DL Forecast (%)"] if "DL Forecast (%)" in mag7_df.columns else pd.Series(index=MAG7, dtype=float)
win_model_s = mag7_df["Winning_Model"] if "Winning_Model" in mag7_df.columns else pd.Series(index=MAG7, dtype=object)
win_fc_s = mag7_df["Winning_Forecast"] if "Winning_Forecast" in mag7_df.columns else pd.Series(index=MAG7, dtype=float)
cons_s = mag7_df["Consensus_Forecast"] if "Consensus_Forecast" in mag7_df.columns else pd.Series(index=MAG7, dtype=float)
conf_s = mag7_df["Confidence_Label"] if "Confidence_Label" in mag7_df.columns else pd.Series(index=MAG7, dtype=object)

forecast_table = pd.DataFrame({
    "Ticker": MAG7,
    "Fama-French": [safe_pct(ff_s.get(t, np.nan)) for t in MAG7],
    "QuantConnect": [safe_pct(qc_s.get(t, np.nan)) for t in MAG7],
    "Institutional": [safe_pct(inst_s.get(t, np.nan)) for t in MAG7],
    "Linear": [safe_pct(lin_s.get(t, np.nan)) for t in MAG7],
    "ML Forecast": [safe_pct(ml_s.get(t, np.nan)) for t in MAG7],
    "ARIMAX": [safe_pct(arx_s.get(t, np.nan)) for t in MAG7],
    "Deep Learning": [safe_pct(dl_s.get(t, np.nan)) for t in MAG7],
    "Best Model": [str(win_model_s.get(t, "N/A")) if pd.notna(win_model_s.get(t, np.nan)) else "N/A" for t in MAG7],
    "Best Forecast": [safe_pct((win_fc_s.get(t, np.nan) * 100.0) if pd.notna(win_fc_s.get(t, np.nan)) else np.nan) for t in MAG7],
    "Consensus": [safe_pct((cons_s.get(t, np.nan) * 100.0) if pd.notna(cons_s.get(t, np.nan)) else np.nan) for t in MAG7],
    "Confidence": [str(conf_s.get(t, "N/A")) if pd.notna(conf_s.get(t, np.nan)) else "N/A" for t in MAG7],
})

mag7_model_html = "<h3 style='margin-top:40px;'>Forecast Model Outputs (Next 21 Days)</h3>"
mag7_model_html += forecast_table.to_html(index=False, escape=False)

ytd_return_map = get_ytd_return_map(MAG7)
commentary_html = ""
commentary_result = {"ok": False, "data": None, "error": None}
cached_commentary = _load_cached_commentary()

market_summary = _build_market_summary(mag7_df)
ticker_rows = _build_commentary_rows(mag7_df, ytd_return_map)
top_highlights = _build_balanced_highlights(ticker_rows)
deterministic_commentary = _normalize_commentary_data(
    _build_deterministic_commentary_data(market_summary, top_highlights, ticker_rows),
    top_highlights=top_highlights,
)

# Persist MAG7 signal summary fields so generate_pdf_report.py can render the
# Quantitative Signal Summary box on page 4.
try:
    _dc_existing: dict = {}
    if os.path.exists(COMMENTARY_JSON_PATH):
        with open(COMMENTARY_JSON_PATH, "r", encoding="utf-8") as _fh:
            _dc_existing = json.load(_fh)
    for _k in ("portfolio_overview", "top_bullets", "market_reflection"):
        if deterministic_commentary.get(_k):
            _dc_existing[_k] = deterministic_commentary[_k]
    with open(COMMENTARY_JSON_PATH, "w", encoding="utf-8") as _fh:
        json.dump(_dc_existing, _fh, indent=2, ensure_ascii=False)
except Exception as _e:
    print(f"[WARN] Could not persist deterministic commentary fields: {_e}")

# Commentary is generated by the generate_market_commentary.py subprocess below (14b model).
# The commentary_html variable is retained for legacy email template references but is unused.
commentary_html = ""

leaderboard_html = _safe_read_text("data/model_leaderboard.html", "")

models_overview_html = """
<div class='section-title'><h2>Forecasting Models Overview</h2></div>
<ul>
  <li><strong>Fama-French:</strong> A factor-based model that estimates expected return using market, size, and value exposures. It helps show how much of a stocks outlook may be explained by broad equity style factors rather than company-specific signals.</li>

  <li><strong>QuantConnect:</strong> A rules-based short-term model built from market signals such as momentum, moving-average gaps, and recent volatility. It is designed to be more responsive to recent price action while still using a broader lookback window to reduce overreaction.</li>

  <li><strong>Institutional:</strong> A multi-factor forecasting approach inspired by institutional managers such as AQR. It blends signals tied to valuation, quality, profitability, growth, and momentum to estimate a forward return in a more balanced, cross-signal framework.</li>

  <li><strong>Linear:</strong> A linear regression model that uses historical relationships between selected inputs and future 21-day returns. It is a transparent baseline model that helps show how forecasts behave when signal effects are assumed to be stable and additive.</li>

  <li><strong>ML Forecast:</strong> A machine-learning model trained on engineered features from price, risk, trend, lagged target behavior, and model inputs. It is intended to capture more complex nonlinear patterns than a standard linear model while still remaining grounded in structured market data.</li>

  <li><strong>ARIMAX:</strong> A time-series benchmark that models 21-day forward returns with autoregressive structure plus exogenous market features such as momentum, volatility, and lagged target signals. It helps test whether short-term serial behavior adds predictive value beyond cross-sectional factors alone.</li>

  <li><strong>Deep Learning (PyTorch TCN):</strong> A temporal convolutional network trained on panel market data to predict 21-day forward returns with confidence bounds. It is designed to recognize time-dependent patterns across sequences that simpler models may miss.</li>
</ul>
"""

# --- Build charts + PDF ---
if not DEV_MODE:
    subprocess.run([VENV_PYTHON, "generate_toggle_chart.py"], check=True)
    subprocess.run([VENV_PYTHON, "generate_charts.py"], check=True)
# Generate market-level LLM commentary; non-zero exit means narrative unavailable.
os.makedirs("logs", exist_ok=True)
_gmc_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "generate_market_commentary.log")
_gmc_result = subprocess.run(
    [VENV_PYTHON, "generate_market_commentary.py"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, encoding="utf-8", errors="replace",
)
sys.stdout.write(_gmc_result.stdout)
with open(_gmc_log_path, "a", encoding="utf-8") as _gmc_lf:
    _gmc_lf.write(f"\n--- {datetime.now().isoformat()} ---\n")
    _gmc_lf.write(_gmc_result.stdout)
_gmc_ok = (_gmc_result.returncode == 0)
if not _gmc_ok:
    print("[WARN] generate_market_commentary.py returned non-zero — narrative unavailable; PDF will be skipped.")
# Arbitrate YCharts vs yfinance data  enriches bonds_table and economic data
try:
    subprocess.run([VENV_PYTHON, "data_arbiter.py"], check=True, timeout=60)
except Exception as e:
    print(f"  Data arbitration failed (non-fatal): {e}")
if not DEV_MODE and _gmc_ok:
    subprocess.run([VENV_PYTHON, "generate_pdf_report.py"], check=True)
elif not DEV_MODE:
    print("[SKIP] PDF generation skipped — narrative unavailable.")

# --- Read charts ---
fund_chart_html = _safe_read_text(
    "charts/fund_chart.html",
    "<div class='section-card'><p>Fund chart HTML was not generated on this run.</p></div>",
)

mag7_chart_html = _safe_read_text(
    "charts/mag7_forecast_chart.html",
    "<div class='section-card'><p>MAG7 forecast chart HTML was not generated on this run.</p></div>",
)

news_html = build_news_html(csv_path="data/news_headlines.csv", lookback_hours=48, max_per_ticker=8)

index_chart_html = _safe_read_text(
    "charts/index_comparison_chart.html",
    "<div class='section-card'><p>Index comparison chart HTML was not generated on this run.</p></div>",
)

markets_dashboard_html = build_markets_dashboard_html(index_chart_html)

forecast_section_html = f"""
<div class='section-title'><h2>Forecasting</h2></div>
{commentary_html}
{models_overview_html}
{mag7_model_html}
{leaderboard_html}
"""

def nav_html(active: str) -> str:
    tabs = [
        ("Home", "index.html", "home"),
        ("Funds", "funds.html", "funds"),
        ("Markets", "markets.html", "markets"),
        ("Forecasting", "forecasting.html", "forecasting"),
        ("PDF Report", "report.pdf", "pdf"),
    ]

    links = []
    for label, href, key in tabs:
        cls = "nav-link active" if key == active else "nav-link"
        target = " target='_blank'" if href.endswith(".pdf") else ""
        links.append(f"<a class='{cls}' href='{href}'{target}>{label}</a>")
    return "<div class='top-nav'>" + "".join(links) + "</div>"


def page_shell(title: str, body_html: str, active: str) -> str:
    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}  {today_str}</title>
  <script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 0;
      background: #f7f8fb;
      color: #1f2937;
    }}
    .page-wrap {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 28px 30px 60px 30px;
    }}
    .site-header {{
      display: flex;
      align-items: center;
      gap: 18px;
      padding: 18px 0 8px 0;
      border-bottom: 2px solid #d7dbe5;
      margin-bottom: 18px;
    }}
    .site-logo {{
      height: 58px;
      width: auto;
      object-fit: contain;
      background: white;
      padding: 6px 10px;
      border-radius: 10px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    }}
    .site-title h1 {{
      margin: 0;
      font-size: 30px;
      color: #1e2a44;
    }}
    .site-title p {{
      margin: 4px 0 0 0;
      color: #667085;
      font-size: 14px;
    }}
    .top-nav {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 18px 0 28px 0;
    }}
    .nav-link {{
      text-decoration: none;
      color: #1e2a44;
      background: #e8edf6;
      padding: 10px 14px;
      border-radius: 8px;
      font-weight: 600;
      border: 1px solid #cfd7e6;
    }}
    .nav-link:hover {{
      background: #dbe5f4;
    }}
    .nav-link.active {{
      background: #1e2a44;
      color: white;
      border-color: #1e2a44;
    }}
    .section-card {{
      background: white;
      border: 1px solid #dfe3eb;
      border-radius: 14px;
      padding: 22px;
      margin-bottom: 24px;
      box-shadow: 0 3px 14px rgba(0,0,0,0.05);
    }}
    .section-title {{
      margin-top: 10px;
      margin-bottom: 16px;
    }}
    .section-title h2 {{
      margin: 0;
      color: #1e2a44;
    }}
    .mini-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-top: 10px;
    }}
    .mini-card {{
      background: #ffffff;
      border: 1px solid #dfe3eb;
      border-radius: 12px;
      padding: 16px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }}
    .mini-card h3 {{
      margin: 0 0 8px 0;
      font-size: 16px;
      color: #1e2a44;
    }}
    .mini-card p {{
      margin: 0;
      color: #4b5563;
      font-size: 14px;
      line-height: 1.45;
    }}
    .quadrant-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      align-items: stretch;
    }}
    .quadrant-card {{
      background: white;
      border: 1px solid #dfe3eb;
      border-radius: 12px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      min-height: 470px;
      overflow: hidden;
    }}
    .quadrant-chart {{
      flex: 1 1 auto;
      min-height: 0;
      overflow: hidden;
    }}
    @media (max-width: 980px) {{
      .quadrant-grid {{
        grid-template-columns: 1fr;
      }}
      .quadrant-card {{
        min-height: 420px;
      }}
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      table-layout: fixed;
      word-wrap: break-word;
      font-size: 10px;
      background: white;
    }}
    th, td {{
      border: 1px solid #cfd7e6;
      padding: 8px;
      text-align: right;
    }}
    th {{
      background-color: #eef2f8;
      text-align: center;
      color: #1e2a44;
    }}
    iframe {{
      width: 100%;
      height: 650px;
      border: none;
      margin-top: 6px;
      background: white;
      border-radius: 10px;
    }}
    ul {{
      line-height: 1.55;
    }}
    .footer-note {{
      margin-top: 32px;
      color: #667085;
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <div class="page-wrap">
    <div class="site-header">
      <img src="epm_logo.png" alt="EPM Logo" class="site-logo">
      <div class="site-title">
        <h1>EPM Quant Report</h1>
        <p>{today_str}</p>
      </div>
    </div>

    {nav_html(active)}

    {body_html}

    <div class="footer-note">
      Generated automatically by the EPM quantitative monitoring pipeline.
    </div>
  </div>
</body>
</html>
"""

# --- HTML Template ---
home_body = f"""
<div class='section-card'>
  <div class='section-title'><h2>Dashboard</h2></div>
  <p>
    Welcome to the EPM Quant dashboard. Use the navigation above to move between
    Funds, Markets, and Forecasting. The PDF report remains available for download.
  </p>
  <div class='mini-grid'>
    <div class='mini-card'>
      <h3>Funds</h3>
      <p>Portfolio metrics table and the interactive funds chart.</p>
    </div>
    <div class='mini-card'>
      <h3>Markets</h3>
      <p>Index comparison and market-level charting.</p>
    </div>
    <div class='mini-card'>
      <h3>Forecasting</h3>
      <p>MAG7 model outputs, forecasting overview, leaderboard, and chart projections.</p>
    </div>
    <div class='mini-card'>
      <h3>PDF Report</h3>
      <p>Download the printable PDF version from the navigation bar above.</p>
    </div>
  </div>
</div>

<div class='section-card'>
  {news_html}
</div>
"""

funds_body = f"""
<div class='section-card'>
  <div class='section-title'><h2>Funds</h2></div>
  {table_html}
</div>

<div class='section-card'>
  <h3>Portfolio View</h3>
  {fund_chart_html}
</div>
"""

markets_body = f"""
{markets_dashboard_html}
"""

forecasting_body = f"""
<div class='section-card'>
  {forecast_section_html}
</div>

<div class='section-card'>
  <h3>MAG7 Forecast View</h3>
  {mag7_chart_html}
</div>
"""

home_html = page_shell("Home", home_body, "home")
funds_html = page_shell("Funds", funds_body, "funds")
markets_html = page_shell("Markets", markets_body, "markets")
forecasting_html = page_shell("Forecasting", forecasting_body, "forecasting")

# Keep report.html as a full legacy page for compatibility / archive / PDF pairing
report_body = f"""
<div class='section-card'>
  <div class='section-title'><h2>Portfolio Metrics</h2></div>
  {table_html}
</div>

<div class='section-card'>
  <h3>Portfolio View</h3>
  {fund_chart_html}
</div>

{markets_dashboard_html}

<div class='section-card'>
  {forecast_section_html}
</div>

<div class='section-card'>
  <h3>MAG7 Forecast View</h3>
  {mag7_chart_html}
</div>

<div class='section-card'>
  {news_html}
</div>
"""
report_html = page_shell("Full Report", report_body, "")

# GitHub Pages HTML writes disabled  epm-market-intelligence.com is now the live site
# Uncomment to re-enable GitHub Pages output:
# try:
#     if os.path.exists("epm_logo.png"):
#         import shutil
#         shutil.copy("epm_logo.png", logo_path)
# except Exception as e:
#     print(f" Could not refresh site logo: {e}")
#
# with open(home_html_path, "w", encoding="utf-8") as f:
#     f.write(home_html)
# with open(funds_html_path, "w", encoding="utf-8") as f:
#     f.write(funds_html)
# with open(markets_html_path, "w", encoding="utf-8") as f:
#     f.write(markets_html)
# with open(forecasting_html_path, "w", encoding="utf-8") as f:
#     f.write(forecasting_html)
# with open(report_html_path, "w", encoding="utf-8") as f:
#     f.write(report_html)

# Archive PDF only (HTML archive disabled)
try:
    import shutil
    shutil.copy(report_pdf_path, archive_pdf_path)
except Exception as e:
    print(f" Could not archive PDF: {e}")

# GitHub Pages push disabled  epm-market-intelligence.com is now the live site
# try:
#     subprocess.run([VENV_PYTHON, "push_to_github.py"], check=True)
#     print(" Changes pushed to GitHub Pages repo.")
# except subprocess.CalledProcessError as e:
#     print(f" GitHub push failed: {e}")

print(f" Total runtime: {time.time() - start_time:.1f}s")

# Sync output to server and log predictions
if not DEV_MODE:
    try:
        subprocess.run([VENV_PYTHON, "post_run.py"], check=True, timeout=180)
    except subprocess.CalledProcessError as e:
        print(f"[WARN] post_run.py failed: {e}")
