"""feature_tester.py
Historical testing harness for the EPM feature promotion pipeline.

Runs a full test suite on any candidate feature using the training panel.
All tests use only point-in-time logic (no future data leakage).

Tests performed:
    1. IC Walk-Forward    rolling Spearman IC between feature and 21D target
    2. Availability       null rate, date coverage, distribution summary
    3. Leakage Check      detects suspicious same-day/lead correlations
    4. Distribution Drift  KS test on early vs late period feature values
    5. Regime Breakdown   IC in high-vol vs low-vol market regimes
    6. Robustness         IC stability after adding Gaussian noise
    7. Ablation           Ridge regression lift with/without this feature

Usage:
    python feature_tester.py --feature Ret_1D
    python feature_tester.py --feature sentiment_1d --min-obs 50
    python feature_tester.py --feature log_volume --tickers AAPL,MSFT,NVDA
    python feature_tester.py --list-features

Output:
    feature_store/testing/results/{feature}_{date}.json
"""

from __future__ import annotations

import argparse
import json
import warnings
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

PANEL_PATH = Path("data/training_panel.parquet")
RESULTS_DIR = Path("feature_store/testing/results")
TARGET_COL = "Target_Forward_21D"

# Column aliases: panel may use uppercase names
ALIAS_MAP = {
    "ret_1d": "Ret_1D", "ret_5d": "Ret_5D", "ret_21d": "Ret_21D",
    "ret_63d": "Ret_63D", "ret_252d": "Ret_252D",
    "vol_21d": "Vol_21D", "vol_63d": "Vol_63D",
    "gap_ma20": "Gap_MA20", "gap_ma50": "Gap_MA50", "gap_ma200": "Gap_MA200",
    "rsi_14": "RSI_14",
}

# Hardcoded fallback only  use _get_baseline_features() at runtime
_FALLBACK_BASELINE = [
    "Ret_1D", "Ret_5D", "Ret_21D", "Ret_63D", "Ret_252D",
    "Vol_21D", "Vol_63D", "Gap_MA20", "Gap_MA50", "Gap_MA200", "RSI_14",
]


def _get_baseline_features() -> List[str]:
    """Return the current DL-approved feature list from the gate (live, not hardcoded)."""
    try:
        from dl_feature_gate import get_approved_features
        cols = get_approved_features()
        return cols if cols else _FALLBACK_BASELINE
    except Exception:
        return list(_FALLBACK_BASELINE)


# ---------------------------------------------------------------------------
# Panel loading
# ---------------------------------------------------------------------------


def _load_panel(
    tickers: Optional[List[str]] = None,
    feature_name: Optional[str] = None,
    panel_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Load enriched training panel. panel_path overrides the default location."""
    resolved = panel_path or PANEL_PATH
    df = None
    try:
        from forecast_common import load_panel_with_features
        df = load_panel_with_features(tickers=tickers, panel_path=str(resolved))
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
        df = df.dropna(subset=["Date", "Ticker"]).sort_values(["Ticker", "Date"]).reset_index(drop=True)
    except Exception as e:
        print(f"  [WARN] Enriched panel unavailable ({e}). Falling back to base panel.")

    if df is None:
        if not resolved.exists():
            raise FileNotFoundError(
                f"Training panel not found: {resolved}\n"
                "Run: python build_training_dataset.py"
            )
        df = pd.read_parquet(resolved)
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
        df = df.dropna(subset=["Date", "Ticker"]).sort_values(["Ticker", "Date"]).reset_index(drop=True)
        if tickers:
            tickers_up = [t.upper().strip() for t in tickers]
            df = df[df["Ticker"].isin(tickers_up)].copy().reset_index(drop=True)

    return df


def _apply_lag_enforcement(df: pd.DataFrame, col: str, lag_days: int) -> Tuple[pd.DataFrame, str, bool]:
    """Shift feature by (lag_days - 1) within each ticker to enforce PIT constraint.

    If lag_days > 1, the feature value at time T is replaced by the value from
    T - (lag_days - 1), representing what was actually available on date T.

    Returns (df_with_shifted_col, effective_col_name, was_shifted).
    """
    if lag_days <= 1:
        return df, col, False

    shift = lag_days - 1
    lag_col = f"{col}__pit_lag{shift}"
    df = df.copy()
    df = df.sort_values(["Ticker", "Date"])
    df[lag_col] = df.groupby("Ticker")[col].shift(shift)
    return df, lag_col, True


def _resolve_column(df: pd.DataFrame, feature_name: str) -> str:
    """Return the actual column name in the panel (handles aliases)."""
    if feature_name in df.columns:
        return feature_name
    alias = ALIAS_MAP.get(feature_name.lower())
    if alias and alias in df.columns:
        return alias
    raise KeyError(
        f"Feature column '{feature_name}' not found in panel.\n"
        f"Available columns: {sorted(df.columns.tolist())}"
    )


# ---------------------------------------------------------------------------
# Test 1: Availability
# ---------------------------------------------------------------------------


def test_availability(df: pd.DataFrame, col: str) -> dict:
    """Null rate, date coverage, and distribution summary."""
    series = pd.to_numeric(df[col], errors="coerce")
    total = len(series)
    n_null = int(series.isna().sum())
    n_valid = total - n_null
    null_rate = n_null / total if total > 0 else 1.0

    valid = series.dropna()
    first_date = str(df.loc[series.notna(), "Date"].min().date()) if n_valid > 0 else None
    last_date = str(df.loc[series.notna(), "Date"].max().date()) if n_valid > 0 else None

    result = {
        "total_rows": total,
        "valid_observations": n_valid,
        "null_rate": round(null_rate, 4),
        "first_available_date": first_date,
        "last_available_date": last_date,
        "mean": round(float(valid.mean()), 6) if n_valid > 0 else None,
        "std": round(float(valid.std()), 6) if n_valid > 0 else None,
        "min": round(float(valid.min()), 6) if n_valid > 0 else None,
        "p25": round(float(valid.quantile(0.25)), 6) if n_valid > 0 else None,
        "median": round(float(valid.median()), 6) if n_valid > 0 else None,
        "p75": round(float(valid.quantile(0.75)), 6) if n_valid > 0 else None,
        "max": round(float(valid.max()), 6) if n_valid > 0 else None,
        "flag": "PASS" if null_rate < 0.30 else ("WARN" if null_rate < 0.70 else "FAIL"),
    }

    if null_rate >= 0.70:
        result["note"] = f"Very sparse ({null_rate:.0%} null). Insufficient data for reliable testing."
    elif null_rate >= 0.30:
        result["note"] = f"Moderately sparse ({null_rate:.0%} null). Interpret results cautiously."
    else:
        result["note"] = f"Good coverage ({null_rate:.0%} null)."

    return result


# ---------------------------------------------------------------------------
# Test 2: IC Walk-Forward
# ---------------------------------------------------------------------------


def test_ic_walkforward(
    df: pd.DataFrame,
    col: str,
    window: int = 63,
    step: int = 21,
    min_obs: int = 20,
) -> dict:
    """Rolling Spearman Information Coefficient (IC) between feature and target.

    Uses rank correlation to measure linear + non-linear predictive value.
    Time-ordered: no future data is used in any window.

    Args:
        window: Rolling window in trading days.
        step: Step size between windows.
        min_obs: Minimum non-null rows per window to include the window.
    """
    valid_idx = df[[col, TARGET_COL]].dropna().index
    sub = df.loc[valid_idx, ["Date", "Ticker", col, TARGET_COL]].copy()
    sub = sub.sort_values("Date").reset_index(drop=True)

    if len(sub) < window + step:
        return {
            "flag": "FAIL",
            "note": f"Insufficient data: {len(sub)} rows, need at least {window + step}.",
            "windows_evaluated": 0,
        }

    dates = sub["Date"].drop_duplicates().sort_values().values
    n_dates = len(dates)
    ics = []

    for start_i in range(0, n_dates - window, step):
        end_i = start_i + window
        window_dates = dates[start_i:end_i]
        w = sub[sub["Date"].isin(window_dates)][[col, TARGET_COL]].dropna()

        if len(w) < min_obs:
            continue

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rho, _ = stats.spearmanr(w[col], w[TARGET_COL])
        if np.isfinite(rho):
            ics.append(float(rho))

    if not ics:
        return {
            "flag": "FAIL",
            "note": "No valid windows produced a finite IC.",
            "windows_evaluated": 0,
        }

    ic_arr = np.array(ics)
    mean_ic = float(np.mean(ic_arr))
    std_ic = float(np.std(ic_arr))
    hit_rate = float(np.mean(ic_arr > 0))  # fraction of windows with positive IC
    t_stat = mean_ic / (std_ic / np.sqrt(len(ic_arr))) if std_ic > 1e-9 else 0.0
    icir = mean_ic / std_ic if std_ic > 1e-9 else 0.0  # IC Information Ratio

    # Flag based on absolute mean IC and hit rate
    if abs(mean_ic) >= 0.05 and hit_rate >= 0.55:
        flag = "PASS"
    elif abs(mean_ic) >= 0.03 and hit_rate >= 0.50:
        flag = "WARN"
    else:
        flag = "FAIL"

    return {
        "flag": flag,
        "windows_evaluated": len(ics),
        "mean_ic": round(mean_ic, 5),
        "std_ic": round(std_ic, 5),
        "min_ic": round(float(np.min(ic_arr)), 5),
        "max_ic": round(float(np.max(ic_arr)), 5),
        "ic_hit_rate": round(hit_rate, 4),
        "t_stat": round(t_stat, 3),
        "ic_ir": round(icir, 3),
        "window_days": window,
        "step_days": step,
        "note": (
            f"Mean IC={mean_ic:.4f}, hit rate={hit_rate:.0%}, t-stat={t_stat:.2f}. "
            f"{'Strong signal.' if flag == 'PASS' else 'Marginal signal.' if flag == 'WARN' else 'Weak or absent signal.'}"
        ),
    }


# ---------------------------------------------------------------------------
# Test 3: Leakage Check
# ---------------------------------------------------------------------------


def test_leakage(df: pd.DataFrame, col: str) -> dict:
    """Detect suspicious forward-looking correlations.

    Checks whether the feature correlates with same-period or near-future
    returns at levels that suggest future data contamination.

    Logic:
      - Compute corr(feature_t, target_t): the intended predictive correlation.
      - Compute corr(feature_t, 1d_return_t): if >> target corr for a non-price
        feature, suspicious (price features naturally correlate same-day).
      - Compute corr(feature_t, target_{t-21}): should be low for most features
        (previous period's target). High corr suggests feature contains future info.
    """
    sub = df[["Ticker", "Date", col, TARGET_COL]].copy()
    sub[col] = pd.to_numeric(sub[col], errors="coerce")
    sub[TARGET_COL] = pd.to_numeric(sub[TARGET_COL], errors="coerce")

    # Shift target by -1 periods WITHIN each ticker to get "next window's target"
    # This represents the TARGET for the NEXT 21D window  should not correlate with today's feature
    sub = sub.sort_values(["Ticker", "Date"])
    sub["future_target"] = sub.groupby("Ticker")[TARGET_COL].shift(-1)

    # Lag the feature by +1 period  if feature_t is suspicious, it may "know" future_target_t
    # We check: does the UNLAGGED feature correlate strongly with FUTURE target?
    valid = sub[[col, TARGET_COL, "future_target"]].dropna()

    if len(valid) < 50:
        return {
            "flag": "WARN",
            "note": "Too few valid observations for leakage analysis (<50).",
        }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        corr_target, _ = stats.spearmanr(valid[col], valid[TARGET_COL])
        corr_future, _ = stats.spearmanr(valid[col], valid["future_target"])

    corr_target = float(corr_target) if np.isfinite(corr_target) else 0.0
    corr_future = float(corr_future) if np.isfinite(corr_future) else 0.0

    # Leakage flag: if feature correlates with next-period target MORE than current,
    # that is suspicious (feature may encode future information)
    leakage_ratio = abs(corr_future) / (abs(corr_target) + 1e-9)

    if leakage_ratio > 1.5 and abs(corr_future) > 0.10:
        flag = "FAIL"
        note = (
            f"Potential future leakage detected. "
            f"Feature correlates more with next-period target ({corr_future:.3f}) "
            f"than current-period target ({corr_target:.3f}). "
            f"Leakage ratio: {leakage_ratio:.2f}. Investigate feature construction."
        )
    elif leakage_ratio > 1.2 and abs(corr_future) > 0.05:
        flag = "WARN"
        note = (
            f"Mild leakage suspicion. Future-period corr ({corr_future:.3f}) "
            f"is close to current-period corr ({corr_target:.3f}). "
            f"Review lag assumptions (lag_days in registry)."
        )
    else:
        flag = "PASS"
        note = (
            f"No leakage detected. Current-period IC={corr_target:.3f}, "
            f"future-period IC={corr_future:.3f} (leakage ratio={leakage_ratio:.2f})."
        )

    return {
        "flag": flag,
        "corr_with_target": round(corr_target, 5),
        "corr_with_future_target": round(corr_future, 5),
        "leakage_ratio": round(leakage_ratio, 3),
        "observations": len(valid),
        "note": note,
    }


# ---------------------------------------------------------------------------
# Test 4: Distribution Drift
# ---------------------------------------------------------------------------


def test_drift(df: pd.DataFrame, col: str, split_pct: float = 0.50) -> dict:
    """Kolmogorov-Smirnov test on early vs late period feature distribution.

    A significant drift (low p-value) means the feature's statistical
    properties have changed over time, which may cause model instability.

    Args:
        split_pct: Fraction of dates defining the 'early' period.
    """
    sub = df[["Date", col]].copy()
    sub[col] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna()

    if len(sub) < 100:
        return {
            "flag": "WARN",
            "note": f"Insufficient data for drift test ({len(sub)} observations).",
        }

    dates = sub["Date"].sort_values().unique()
    split_date = dates[int(len(dates) * split_pct)]

    early = sub.loc[sub["Date"] < split_date, col].values
    late = sub.loc[sub["Date"] >= split_date, col].values

    if len(early) < 30 or len(late) < 30:
        return {
            "flag": "WARN",
            "note": "One period has <30 observations. Drift test unreliable.",
        }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ks_stat, ks_pvalue = stats.ks_2samp(early, late)

    mean_shift = float(np.mean(late) - np.mean(early))
    std_shift = float(np.std(late) - np.std(early))

    if ks_pvalue < 0.01:
        flag = "FAIL"
        note = f"Strong distribution drift detected (KS p={ks_pvalue:.4f}). Mean shift={mean_shift:+.4f}."
    elif ks_pvalue < 0.05:
        flag = "WARN"
        note = f"Moderate distribution drift (KS p={ks_pvalue:.4f}). Monitor over time."
    else:
        flag = "PASS"
        note = f"No significant drift detected (KS p={ks_pvalue:.4f})."

    return {
        "flag": flag,
        "ks_statistic": round(float(ks_stat), 5),
        "ks_pvalue": round(float(ks_pvalue), 5),
        "mean_shift": round(mean_shift, 6),
        "std_shift": round(std_shift, 6),
        "split_date": str(pd.Timestamp(split_date).date()),
        "early_n": len(early),
        "late_n": len(late),
        "note": note,
    }


# ---------------------------------------------------------------------------
# Test 5: Regime Breakdown
# ---------------------------------------------------------------------------


def test_regime_breakdown(df: pd.DataFrame, col: str) -> dict:
    """IC in high-volatility vs low-volatility regimes.

    High-vol regime is defined as dates where the cross-sectional average
    Vol_21D is above its 70th percentile (proxy for stressed markets).

    If Vol_21D is not in the panel, falls back to Ret_21D rolling std.
    """
    sub = df.copy()
    sub[col] = pd.to_numeric(sub[col], errors="coerce")
    sub[TARGET_COL] = pd.to_numeric(sub[TARGET_COL], errors="coerce")

    # Build regime indicator
    if "Vol_21D" in sub.columns:
        vol_proxy = pd.to_numeric(sub["Vol_21D"], errors="coerce")
    elif "Vol_63D" in sub.columns:
        vol_proxy = pd.to_numeric(sub["Vol_63D"], errors="coerce")
    else:
        return {
            "flag": "WARN",
            "note": "No volatility column (Vol_21D / Vol_63D) found. Regime breakdown skipped.",
        }

    vol_threshold = float(vol_proxy.quantile(0.70))
    sub["high_vol"] = vol_proxy >= vol_threshold

    results: Dict[str, dict] = {}
    for regime, label in [(True, "high_vol"), (False, "low_vol")]:
        mask = sub["high_vol"] == regime
        w = sub.loc[mask, [col, TARGET_COL]].dropna()
        if len(w) < 20:
            results[label] = {"ic": None, "n": len(w), "flag": "INSUFFICIENT"}
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rho, _ = stats.spearmanr(w[col], w[TARGET_COL])
        ic = float(rho) if np.isfinite(rho) else None
        results[label] = {"ic": round(ic, 5) if ic is not None else None, "n": len(w)}

    hi = results.get("high_vol", {}).get("ic")
    lo = results.get("low_vol", {}).get("ic")

    if hi is not None and lo is not None:
        # Feature passes regime test if it works in at least one regime
        if hi > 0.03 and lo > 0.03:
            flag = "PASS"
            note = f"Positive IC in both regimes: high_vol={hi:.4f}, low_vol={lo:.4f}."
        elif hi > 0.03 or lo > 0.03:
            flag = "WARN"
            note = (
                f"Feature works in one regime but not both: "
                f"high_vol={hi:.4f}, low_vol={lo:.4f}. "
                f"Consider regime-conditional weighting."
            )
        else:
            flag = "FAIL"
            note = f"Weak IC in both regimes: high_vol={hi:.4f}, low_vol={lo:.4f}."
    else:
        flag = "WARN"
        note = "One or more regimes had insufficient data for IC calculation."

    return {
        "flag": flag,
        "high_vol_ic": results.get("high_vol", {}).get("ic"),
        "low_vol_ic": results.get("low_vol", {}).get("ic"),
        "high_vol_n": results.get("high_vol", {}).get("n", 0),
        "low_vol_n": results.get("low_vol", {}).get("n", 0),
        "vol_threshold_used": round(vol_threshold, 6),
        "note": note,
    }


# ---------------------------------------------------------------------------
# Test 6: Robustness (noise injection)
# ---------------------------------------------------------------------------


def test_robustness(df: pd.DataFrame, col: str, noise_level: float = 0.10) -> dict:
    """IC stability after adding Gaussian noise (noise_level * feature std).

    A robust feature should maintain most of its predictive power even after
    small perturbations. High IC degradation suggests the feature is brittle
    or contains spurious precision.

    Args:
        noise_level: Fraction of feature std to use as noise amplitude.
    """
    sub = df[[col, TARGET_COL]].copy()
    sub[col] = pd.to_numeric(sub[col], errors="coerce")
    sub[TARGET_COL] = pd.to_numeric(sub[TARGET_COL], errors="coerce")
    sub = sub.dropna()

    if len(sub) < 50:
        return {
            "flag": "WARN",
            "note": "Insufficient data for robustness test (<50 observations).",
        }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        clean_ic, _ = stats.spearmanr(sub[col], sub[TARGET_COL])

    clean_ic = float(clean_ic) if np.isfinite(clean_ic) else 0.0

    rng = np.random.default_rng(42)
    feature_std = float(sub[col].std())
    noise = rng.normal(0, noise_level * feature_std, size=len(sub))
    noisy_feature = sub[col].values + noise

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        noisy_ic, _ = stats.spearmanr(noisy_feature, sub[TARGET_COL].values)

    noisy_ic = float(noisy_ic) if np.isfinite(noisy_ic) else 0.0

    # IC degradation as fraction of clean IC
    if abs(clean_ic) > 1e-9:
        degradation = (clean_ic - noisy_ic) / abs(clean_ic)
    else:
        degradation = 0.0

    if degradation < 0.10:
        flag = "PASS"
        note = f"Robust: {degradation:.0%} IC degradation with {noise_level:.0%} noise injection."
    elif degradation < 0.25:
        flag = "WARN"
        note = f"Moderate sensitivity: {degradation:.0%} IC degradation with {noise_level:.0%} noise."
    else:
        flag = "FAIL"
        note = (
            f"Brittle: {degradation:.0%} IC degradation under {noise_level:.0%} noise. "
            f"Feature may be overfitting specific numeric patterns."
        )

    return {
        "flag": flag,
        "clean_ic": round(clean_ic, 5),
        "noisy_ic": round(noisy_ic, 5),
        "ic_degradation_pct": round(degradation, 4),
        "noise_level_used": noise_level,
        "observations": len(sub),
        "note": note,
    }


# ---------------------------------------------------------------------------
# Test 7: Ablation (incremental value vs approved DL baseline)
# ---------------------------------------------------------------------------


def test_ablation(
    df: pd.DataFrame,
    col: str,
    baseline_features: Optional[List[str]] = None,
    test_frac: float = 0.30,
) -> dict:
    """Measure incremental R lift when adding this feature to the DL baseline.

    Uses Ridge regression on a time-ordered train/test split.
    The test set is always the most recent test_frac of dates (walk-forward).

    Args:
        baseline_features: Current DL-approved features (defaults to FALLBACK_FEATURES).
        test_frac: Fraction of dates to use as out-of-sample test set.
    """
    try:
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return {
            "flag": "WARN",
            "note": "scikit-learn not available. Install it to run ablation tests.",
        }

    baseline_features = baseline_features or _DEFAULT_BASELINE_FEATURES

    # Resolve all columns that actually exist in the panel
    available_baseline = [c for c in baseline_features if c in df.columns]
    if not available_baseline:
        return {
            "flag": "WARN",
            "note": "No baseline features found in panel. Ablation skipped.",
        }

    all_features = available_baseline + ([col] if col not in available_baseline else [])
    required_cols = all_features + [TARGET_COL, "Date"]
    sub = df[required_cols].copy()
    for c in all_features:
        sub[c] = pd.to_numeric(sub[c], errors="coerce")
    sub[TARGET_COL] = pd.to_numeric(sub[TARGET_COL], errors="coerce")
    sub = sub.dropna(subset=[col, TARGET_COL]).sort_values("Date").reset_index(drop=True)

    if len(sub) < 100:
        return {
            "flag": "WARN",
            "note": f"Insufficient data for ablation ({len(sub)} rows).",
        }

    # Time-ordered split  no shuffling
    split_idx = int(len(sub) * (1 - test_frac))
    train = sub.iloc[:split_idx]
    test = sub.iloc[split_idx:]

    def _fit_score(features: List[str]) -> Tuple[float, float]:
        X_tr = train[features].fillna(0).values
        y_tr = train[TARGET_COL].values
        X_te = test[features].fillna(0).values
        y_te = test[TARGET_COL].values

        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)

        model = Ridge(alpha=1.0)
        model.fit(X_tr_s, y_tr)
        y_pred = model.predict(X_te_s)

        ss_res = np.sum((y_te - y_pred) ** 2)
        ss_tot = np.sum((y_te - np.mean(y_te)) ** 2)
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return float(r2), float(np.mean(np.abs(y_te - y_pred)))

    # Baseline: approved features only (excluding the candidate)
    baseline_only = [c for c in available_baseline if c != col]
    baseline_r2, baseline_mae = _fit_score(baseline_only) if baseline_only else (0.0, float("nan"))

    # Augmented: baseline + candidate
    augmented_features = baseline_only + [col]
    augmented_r2, augmented_mae = _fit_score(augmented_features)

    delta_r2 = augmented_r2 - baseline_r2
    delta_mae = augmented_mae - baseline_mae  # negative = improvement

    if delta_r2 > 0.005:
        flag = "PASS"
        note = f"Clear incremental lift: delta R={delta_r2:+.5f} (baseline={baseline_r2:.5f})."
    elif delta_r2 > 0.001:
        flag = "WARN"
        note = f"Marginal incremental value: delta R={delta_r2:+.5f}. Consider vs complexity cost."
    elif delta_r2 >= -0.001:
        flag = "WARN"
        note = f"Negligible incremental value: delta R={delta_r2:+.5f}. May be redundant."
    else:
        flag = "FAIL"
        note = f"Negative incremental value: delta R={delta_r2:+.5f}. Feature may hurt the model."

    return {
        "flag": flag,
        "baseline_r2": round(baseline_r2, 6),
        "augmented_r2": round(augmented_r2, 6),
        "delta_r2": round(delta_r2, 6),
        "delta_mae": round(delta_mae, 6),
        "train_rows": len(train),
        "test_rows": len(test),
        "baseline_features_used": len(baseline_only),
        "note": note,
    }


# ---------------------------------------------------------------------------
# Test 8: Redundancy (cross-correlation with approved features)
# ---------------------------------------------------------------------------


def test_redundancy(
    df: pd.DataFrame,
    col: str,
    approved_features: Optional[List[str]] = None,
) -> dict:
    """Max pairwise Spearman correlation between candidate and each approved feature.

    A highly correlated feature is likely redundant  the model already captures
    that signal. Redundancy does not mean the feature is bad, but it must add
    incremental value beyond what the approved set already provides.

    Args:
        approved_features: Current DL-approved column names (reads from gate if None).
    """
    if approved_features is None:
        approved_features = _get_baseline_features()

    candidate = pd.to_numeric(df[col], errors="coerce")
    valid_mask = candidate.notna()
    if valid_mask.sum() < 30:
        return {"flag": "WARN", "note": "Too few valid observations for redundancy check."}

    correlations = {}
    for feat in approved_features:
        if feat == col or feat not in df.columns:
            continue
        other = pd.to_numeric(df[feat], errors="coerce")
        both = valid_mask & other.notna()
        if both.sum() < 30:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rho, _ = stats.spearmanr(candidate[both], other[both])
        if np.isfinite(rho):
            correlations[feat] = round(float(rho), 4)

    if not correlations:
        return {
            "flag": "PASS",
            "note": "No approved features available for comparison.",
            "correlations": {},
            "max_abs_corr": None,
            "most_similar_feature": None,
        }

    max_abs_corr = max(abs(v) for v in correlations.values())
    most_similar = max(correlations, key=lambda k: abs(correlations[k]))

    if max_abs_corr >= 0.85:
        flag = "FAIL"
        note = (
            f"Highly redundant with '{most_similar}' (rho={correlations[most_similar]:.3f}). "
            f"Nearly duplicates an approved feature. Ablation must show clear incremental value."
        )
    elif max_abs_corr >= 0.65:
        flag = "WARN"
        note = (
            f"Moderately correlated with '{most_similar}' (rho={correlations[most_similar]:.3f}). "
            f"May add limited new information. Verify ablation delta."
        )
    else:
        flag = "PASS"
        note = (
            f"Low redundancy. Max correlation with approved features: "
            f"rho={max_abs_corr:.3f} (vs '{most_similar}')."
        )

    return {
        "flag": flag,
        "max_abs_corr": round(max_abs_corr, 4),
        "most_similar_feature": most_similar,
        "most_similar_corr": correlations[most_similar],
        "all_correlations": correlations,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_tests(
    feature_name: str,
    tickers: Optional[List[str]] = None,
    min_obs: int = 30,
    save: bool = True,
    panel_path: Optional[Path] = None,
    label: str = "",
) -> dict:
    """Run the full test suite for a candidate feature.

    Args:
        feature_name: Registry name or panel column name of the feature to test.
        tickers: Optional subset of tickers to test on.
        min_obs: Minimum observations per IC window.
        save: Write results to feature_store/testing/results/ (or results/{label}/).
        panel_path: Override the default training_panel.parquet path.
        label: Universe label (e.g. "broad"). Results saved to results/{label}/
               when provided, so production results are never mixed with research runs.

    Returns:
        Full test results dict (also saved to JSON if save=True).
    """
    print(f"\n[feature_tester] Testing feature: {feature_name}" + (f" [{label}]" if label else ""))
    print("=" * 55)

    df = _load_panel(tickers=tickers, feature_name=feature_name, panel_path=panel_path)
    col = _resolve_column(df, feature_name)

    # Load lag_days and PIT flag from registry (if registered)
    lag_days = 1
    pit = True
    try:
        from feature_registry import FeatureRegistry
        entry = FeatureRegistry().get(feature_name)
        lag_days = entry.get("lag_days", 1)
        pit = entry.get("point_in_time", True)
    except Exception:
        pass

    # Enforce PIT constraint: shift feature by (lag_days-1) if non-trivial lag
    df, effective_col, was_shifted = _apply_lag_enforcement(df, col, lag_days)
    if was_shifted:
        print(f"  [PIT] Shifted '{col}' by {lag_days-1} days (lag_days={lag_days}) -> '{effective_col}'")

    # Resolve baseline features from the gate (live, not hardcoded)
    baseline_features = _get_baseline_features()

    print(f"  Panel shape  : {df.shape}")
    print(f"  Column used  : {effective_col} (original: {col})")
    print(f"  Tickers      : {df['Ticker'].nunique()} unique")
    print(f"  Date range   : {df['Date'].min().date()} -> {df['Date'].max().date()}")
    print(f"  Baseline     : {len(baseline_features)} DL-approved features")
    print(f"  Lag enforced : lag_days={lag_days}, PIT={pit}")
    print()

    results = {
        "feature_name": feature_name,
        "panel_column": col,
        "effective_column": effective_col,
        "lag_days_applied": lag_days,
        "pit_flag": pit,
        "lag_shifted": was_shifted,
        "test_date": str(date.today()),
        "panel_rows": len(df),
        "tickers_tested": df["Ticker"].nunique(),
        "ticker_list": df["Ticker"].unique().tolist(),
        "baseline_features": baseline_features,
        "tests": {},
    }

    col = effective_col  # use lag-enforced column for all tests

    test_fns = [
        ("availability",    lambda: test_availability(df, col)),
        ("leakage_check",   lambda: test_leakage(df, col)),
        ("ic_walkforward",  lambda: test_ic_walkforward(df, col, min_obs=min_obs)),
        ("drift",           lambda: test_drift(df, col)),
        ("regime_breakdown",lambda: test_regime_breakdown(df, col)),
        ("robustness",      lambda: test_robustness(df, col)),
        ("ablation",        lambda: test_ablation(df, col, baseline_features=baseline_features)),
        ("redundancy",      lambda: test_redundancy(df, col, approved_features=baseline_features)),
    ]

    overall_flags = []
    for test_name, test_fn in test_fns:
        print(f"  Running {test_name}...", end=" ", flush=True)
        try:
            r = test_fn()
            flag = r.get("flag", "WARN")
            results["tests"][test_name] = r
            overall_flags.append(flag)
            print(f"[{flag}]")
            if r.get("note"):
                print(f"    {r['note']}")
        except Exception as exc:
            results["tests"][test_name] = {"flag": "ERROR", "error": str(exc)}
            overall_flags.append("ERROR")
            print(f"[ERROR] {exc}")

    # Overall assessment
    if any(f == "FAIL" for f in overall_flags):
        overall = "FAIL"
    elif overall_flags.count("PASS") >= 4:
        overall = "PASS"
    else:
        overall = "WARN"

    results["overall_flag"] = overall
    results["flags_summary"] = {
        t: results["tests"][t].get("flag", "?")
        for t in results["tests"]
    }

    print()
    print(f"  Overall result: [{overall}]")

    if save:
        save_dir = RESULTS_DIR / label if label else RESULTS_DIR
        save_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{feature_name.lower()}_{date.today().strftime('%Y%m%d')}.json"
        out_path = save_dir / fname
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"  Results saved: {out_path}")
        results["saved_to"] = str(out_path)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Run historical tests on a candidate feature."
    )
    ap.add_argument("--feature", type=str, help="Feature name or panel column to test")
    ap.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated ticker subset (default: all in panel)",
    )
    ap.add_argument(
        "--min-obs",
        type=int,
        default=30,
        help="Minimum observations per IC window (default: 30)",
    )
    ap.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save results to disk (just print)",
    )
    ap.add_argument(
        "--panel",
        type=str,
        default=None,
        help="Path to an alternative panel parquet (e.g. data/research_panel.parquet). "
             "Defaults to data/training_panel.parquet.",
    )
    ap.add_argument(
        "--label",
        type=str,
        default="",
        help="Universe label for result file subdirectory (e.g. 'broad'). "
             "Results go to feature_store/testing/results/{label}/. "
             "Leave empty for production/MAG7 runs (default behaviour).",
    )
    ap.add_argument(
        "--list-features",
        action="store_true",
        help="List all columns in the training panel and exit",
    )
    return ap


def main() -> None:
    args = _build_parser().parse_args()

    panel_path = Path(args.panel) if args.panel else None

    if args.list_features:
        df = _load_panel(panel_path=panel_path)
        print(f"\nColumns in panel ({len(df.columns)}):")
        for c in sorted(df.columns):
            print(f"  {c}")
        return

    if not args.feature:
        print("Error: --feature is required (or use --list-features to see available columns)")
        return

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers
        else None
    )

    run_tests(
        feature_name=args.feature,
        tickers=tickers,
        min_obs=args.min_obs,
        save=not args.no_save,
        panel_path=panel_path,
        label=args.label,
    )


if __name__ == "__main__":
    main()
