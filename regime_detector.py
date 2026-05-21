"""regime_detector.py

HMM-based market regime detector.

Fits a 4-state Gaussian HMM on SPY OHLCV-derived features and exposes
get_current_regime() for use in abstention gate scripts.

State labels are assigned after fitting by sorting on realized volatility
and mean 5-day return:
  bull_quiet    — low vol, positive drift
  bear_quiet    — low vol, negative drift
  bull_volatile — high vol, positive drift
  bear_stress   — high vol, negative drift  (is_stress = True)

Usage (CLI):
  python regime_detector.py fit [--lookback-years 12] [--states 4]
  python regime_detector.py status

Usage (import):
  from regime_detector import get_current_regime
  r = get_current_regime()
  print(r['label'], r['is_stress'])
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from hmmlearn.hmm import GaussianHMM
except ImportError:
    GaussianHMM = None  # type: ignore[assignment]

MODEL_PATH = Path("models/hmm_regime.pkl")
META_PATH = Path("models/hmm_regime_meta.json")
TICKER = "SPY"
N_STATES = 4
LOOKBACK_YEARS = 12
CACHED_PRICE_DIR = Path("quant_cup/data")

# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _fetch_ohlcv(ticker: str, lookback_years: int) -> pd.DataFrame:
    end = date.today()
    start = end - timedelta(days=lookback_years * 365 + 30)
    if yf is None:
        return _fetch_cached_ohlcv(ticker, str(start), str(end))
    try:
        df = yf.download(ticker, start=str(start), end=str(end), auto_adjust=True, progress=False)
    except Exception:
        return _fetch_cached_ohlcv(ticker, str(start), str(end))
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Close"])
    if df.empty:
        return _fetch_cached_ohlcv(ticker, str(start), str(end))
    df.index = pd.to_datetime(df.index)
    return df


def _fetch_ohlcv_range(ticker: str, start: str, end: str) -> pd.DataFrame:
    if yf is None:
        return _fetch_cached_ohlcv(ticker, start, end)
    try:
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    except Exception:
        return _fetch_cached_ohlcv(ticker, start, end)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Close"])
    if df.empty:
        return _fetch_cached_ohlcv(ticker, start, end)
    df.index = pd.to_datetime(df.index)
    return df


def _fetch_cached_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    ticker = str(ticker).upper()
    frames: dict[str, pd.Series] = {}
    for field in ["open", "high", "low", "close", "volume"]:
        path = CACHED_PRICE_DIR / f"prices_{field}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Missing cached price file: {path}")
        table = pd.read_parquet(path)
        if ticker not in table.columns:
            raise KeyError(f"{ticker} not found in cached price file: {path}")
        frames[field.title() if field != "volume" else "Volume"] = table[ticker]
    out = pd.DataFrame(frames)
    out.index = pd.to_datetime(out.index)
    return out[(out.index >= pd.to_datetime(start)) & (out.index <= pd.to_datetime(end))].dropna(subset=["Close"])


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"].squeeze()
    high = df["High"].squeeze()
    low = df["Low"].squeeze()

    log_ret = np.log(close / close.shift(1))

    rv_20 = log_ret.rolling(20).std() * np.sqrt(252)
    long_rv = log_ret.rolling(252).std() * np.sqrt(252)
    vol_ratio = rv_20 / long_rv.replace(0, np.nan)
    ret_5d = log_ret.rolling(5).sum()
    range_ratio = (high - low) / close

    feat = pd.DataFrame(
        {
            "rv_20": rv_20,
            "vol_ratio": vol_ratio,
            "ret_5d": ret_5d,
            "range_ratio": range_ratio,
        },
        index=df.index,
    )
    feat = feat.dropna()
    return feat


# ---------------------------------------------------------------------------
# State labelling
# ---------------------------------------------------------------------------

def _label_states(
    hmm: GaussianHMM, n_states: int
) -> dict[int, str]:
    """Assign human-readable labels to HMM states.

    States are sorted by mean realized vol (feature index 0).
    The two lower-vol states are 'quiet' and the two higher-vol are 'volatile'.
    Within each vol group the state with higher mean 5d-return (feature index 2)
    is the bull variant.
    """
    means = hmm.means_  # (n_states, n_features)
    rv_col = 0
    ret_col = 2

    by_vol = sorted(range(n_states), key=lambda s: means[s, rv_col])
    low_vol_states = by_vol[: n_states // 2]
    high_vol_states = by_vol[n_states // 2 :]

    def _split_by_return(states: list[int]) -> tuple[int, int]:
        bull = max(states, key=lambda s: means[s, ret_col])
        bear = min(states, key=lambda s: means[s, ret_col])
        return bull, bear

    lv_bull, lv_bear = _split_by_return(low_vol_states)
    hv_bull, hv_bear = _split_by_return(high_vol_states)

    labels = {
        lv_bull: "bull_quiet",
        lv_bear: "bear_quiet",
        hv_bull: "bull_volatile",
        hv_bear: "bear_stress",
    }
    return labels


STRESS_LABELS = {"bull_volatile", "bear_stress"}


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------

def fit(
    ticker: str = TICKER,
    lookback_years: int = LOOKBACK_YEARS,
    n_states: int = N_STATES,
    n_iter: int = 200,
    random_state: int = 42,
) -> dict:
    if GaussianHMM is None:
        raise ImportError("hmmlearn required: pip install hmmlearn")
    print(f"Fetching {ticker} OHLCV ({lookback_years}y)...")
    df = _fetch_ohlcv(ticker, lookback_years)
    feat = _build_features(df)

    X = feat.values.astype(np.float64)
    lengths = [len(X)]

    print(f"Fitting GaussianHMM: {n_states} states, {len(X)} days...")
    hmm = GaussianHMM(
        n_components=n_states,
        covariance_type="full",
        n_iter=n_iter,
        random_state=random_state,
        verbose=False,
    )
    hmm.fit(X, lengths)
    print(f"HMM converged={hmm.monitor_.converged} log-likelihood={hmm.monitor_.history[-1]:.4f}")

    labels = _label_states(hmm, n_states)
    _log_prob, state_seq = hmm.decode(X)
    current_state = int(state_seq[-1])
    current_label = labels[current_state]

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"hmm": hmm, "labels": labels, "feature_names": list(feat.columns)}, MODEL_PATH)

    meta = {
        "ticker": ticker,
        "lookback_years": lookback_years,
        "n_states": n_states,
        "feature_names": list(feat.columns),
        "state_labels": {str(k): v for k, v in labels.items()},
        "means": {labels[s]: feat.columns.tolist() and dict(zip(feat.columns, hmm.means_[s].tolist())) for s in range(n_states)},
        "fit_date": str(date.today()),
        "fit_days": len(X),
        "converged": bool(hmm.monitor_.converged),
        "log_likelihood": float(hmm.monitor_.history[-1]),
        "as_of_date": str(feat.index[-1].date()),
        "current_state": current_state,
        "current_label": current_label,
        "is_stress": current_label in STRESS_LABELS,
    }
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved model -> {MODEL_PATH}")
    print(f"Saved meta  -> {META_PATH}")

    _print_state_summary(hmm, labels, feat.columns.tolist(), state_seq, current_state, current_label)
    return meta


def _print_state_summary(hmm, labels, feature_names, state_seq, current_state, current_label):
    print("\n--- State Summary ---")
    for s, label in sorted(labels.items()):
        pct = float(np.mean(state_seq == s)) * 100
        means_str = "  ".join(f"{feature_names[i]}={hmm.means_[s, i]:.4f}" for i in range(len(feature_names)))
        stress_tag = " [STRESS]" if label in STRESS_LABELS else ""
        print(f"  State {s} ({label}){stress_tag}: {pct:.1f}% of history  |  {means_str}")
    is_stress = current_label in STRESS_LABELS
    stress_str = " [STRESS]" if is_stress else ""
    print(f"\nCurrent regime: {current_label}{stress_str} (state {current_state})")


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def get_current_regime(
    ticker: str = TICKER,
    lookback_days: int = 504,
    model_path: Path = MODEL_PATH,
) -> dict:
    """Return current regime dict for use in abstention gate scripts.

    Returns:
        state       : int — HMM state index
        label       : str — 'bull_quiet' | 'bear_quiet' | 'bull_volatile' | 'bear_stress'
        is_stress   : bool — True for high-vol regimes
        as_of_date  : str — last OHLCV date used
        trans_probs : list[float] — transition probability row for current state
    """
    if not Path(model_path).exists():
        raise FileNotFoundError(
            f"No fitted HMM model at {model_path}. Run: python regime_detector.py fit"
        )
    payload = joblib.load(model_path)
    if GaussianHMM is None:
        raise ImportError("hmmlearn required: pip install hmmlearn")
    hmm: GaussianHMM = payload["hmm"]
    labels: dict[int, str] = payload["labels"]

    end = date.today()
    start = end - timedelta(days=lookback_days + 60)
    df = yf.download(ticker, start=str(start), end=str(end), auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Close"])
    feat = _build_features(df)
    if feat.empty:
        raise RuntimeError("Insufficient OHLCV data to compute regime features.")

    X = feat.values.astype(np.float64)
    _log_prob, state_seq = hmm.decode(X)
    current_state = int(state_seq[-1])
    current_label = labels[current_state]
    trans_probs = hmm.transmat_[current_state].tolist()

    return {
        "state": current_state,
        "label": current_label,
        "is_stress": current_label in STRESS_LABELS,
        "as_of_date": str(feat.index[-1].date()),
        "trans_probs": trans_probs,
        "next_state_labels": [labels[s] for s in range(hmm.n_components)],
    }


def get_regime_series(
    start: str,
    end: str,
    ticker: str = TICKER,
    model_path: Path = MODEL_PATH,
) -> pd.Series:
    """Return per-date HMM regime labels for a date range.

    The fetch begins before ``start`` so rolling features are available at the
    first requested output date. State assignment uses Viterbi decoding.
    """
    if not Path(model_path).exists():
        raise FileNotFoundError(
            f"No fitted HMM model at {model_path}. Run: python regime_detector.py fit"
        )
    payload = joblib.load(model_path)
    if GaussianHMM is None:
        raise ImportError("hmmlearn required: pip install hmmlearn")
    hmm: GaussianHMM = payload["hmm"]
    labels: dict[int, str] = payload["labels"]

    start_ts = pd.to_datetime(start)
    end_ts = pd.to_datetime(end)
    fetch_start = (start_ts - pd.Timedelta(days=420)).date().isoformat()
    fetch_end = (end_ts + pd.Timedelta(days=1)).date().isoformat()
    df = _fetch_ohlcv_range(ticker, fetch_start, fetch_end)
    feat = _build_features(df)
    feat = feat[(feat.index >= start_ts) & (feat.index <= end_ts)]
    if feat.empty:
        raise RuntimeError(f"Insufficient OHLCV data to compute regime series for {start} -> {end}.")

    X = feat.values.astype(np.float64)
    _log_prob, state_seq = hmm.decode(X)
    return pd.Series([labels[int(s)] for s in state_seq], index=feat.index, name="Regime")


def run_bic_sweep(n_range: tuple[int, int] = (2, 7), ticker: str = TICKER) -> pd.DataFrame:
    """Fit HMMs across state counts and report AIC/BIC."""
    if GaussianHMM is None:
        raise ImportError("hmmlearn required: pip install hmmlearn")
    df = _fetch_ohlcv(ticker, LOOKBACK_YEARS)
    feat = _build_features(df)
    X = feat.values.astype(np.float64)
    lengths = [len(X)]
    n_samples, n_features = X.shape

    rows: list[dict[str, float | int]] = []
    for n_states in range(*n_range):
        hmm = GaussianHMM(
            n_components=n_states,
            covariance_type="full",
            n_iter=200,
            random_state=42,
            verbose=False,
        )
        hmm.fit(X, lengths)
        log_likelihood = float(hmm.score(X, lengths))
        n_params = int(n_states**2 + 2 * n_states * n_features)
        bic = -2.0 * log_likelihood + n_params * np.log(n_samples)
        aic = -2.0 * log_likelihood + 2 * n_params
        rows.append(
            {
                "n_states": int(n_states),
                "log_likelihood": log_likelihood,
                "bic": float(bic),
                "aic": float(aic),
            }
        )

    out = pd.DataFrame(rows)
    best_n = int(out.loc[out["bic"].idxmin(), "n_states"])
    print(out.to_string(index=False))
    print(f"\nMinimum-BIC n_states: {best_n}")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_fit(args: argparse.Namespace) -> None:
    fit(
        ticker=args.ticker,
        lookback_years=args.lookback_years,
        n_states=args.states,
    )


def _cmd_status(args: argparse.Namespace) -> None:
    try:
        r = get_current_regime(ticker=args.ticker)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    stress_str = " [STRESS]" if r["is_stress"] else ""
    print(f"Regime as of {r['as_of_date']}: {r['label']}{stress_str} (state {r['state']})")
    print("Transition probabilities from current state:")
    for i, (prob, label) in enumerate(zip(r["trans_probs"], r["next_state_labels"])):
        print(f"  -> {label} (state {i}): {prob:.4f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="HMM market regime detector")
    ap.add_argument("--bic-sweep", action="store_true", help="Run n-state BIC sweep and exit")
    ap.add_argument("--bic-start", type=int, default=2)
    ap.add_argument("--bic-stop", type=int, default=7)
    sub = ap.add_subparsers(dest="cmd")

    fit_p = sub.add_parser("fit", help="Fit HMM on historical OHLCV data")
    fit_p.add_argument("--ticker", default=TICKER)
    fit_p.add_argument("--lookback-years", type=int, default=LOOKBACK_YEARS)
    fit_p.add_argument("--states", type=int, default=N_STATES)

    status_p = sub.add_parser("status", help="Report current regime from saved model")
    status_p.add_argument("--ticker", default=TICKER)

    args = ap.parse_args()
    if args.bic_sweep:
        run_bic_sweep((args.bic_start, args.bic_stop), ticker=TICKER)
    elif args.cmd == "fit":
        _cmd_fit(args)
    elif args.cmd == "status":
        _cmd_status(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
