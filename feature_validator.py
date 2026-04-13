"""feature_validator.py
Pre-test validation layer for the EPM feature promotion pipeline.

Run this BEFORE feature_tester.py to catch structural problems early.
A FAIL here means the feature is not ready for testing at all.

Checks:
    1. Column Presence      panel column exists in enriched panel
    2. Numeric Type         values are castable to float
    3. Coverage Gate        at least 200 valid observations
    4. Non-Constant         feature is not nearly constant (std > 0)
    5. Range Sanity         no extreme outliers suggesting data errors
    6. Lag Plausibility     lag_days consistent with update_frequency
    7. PIT Consistency      non-PIT features have lag_days >= 21
    8. Stationarity         ADF test (WARN if unit-root cannot be rejected)
    9. Registry Integrity   required fields present and non-empty

Usage:
    python feature_validator.py --feature sharpe_3y
    python feature_validator.py --feature log_volume --strict

Output:
    Prints validation report.
    Returns PASS / WARN / FAIL with blocking detail.
    Optionally saves to feature_store/testing/validation/{feature}_{date}.json
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

PANEL_PATH = Path("data/training_panel.parquet")
VALIDATION_DIR = Path("feature_store/testing/validation")
TARGET_COL = "Target_Forward_21D"

# Minimum observations before any test is meaningful
MIN_OBS_HARD = 200
MIN_OBS_WARN = 500

# Features expected to have high std (returns, gaps, etc.)
_HIGH_VARIANCE_TYPES = {"price_momentum", "technical_trend", "volatility", "technical_oscillator"}


# ---------------------------------------------------------------------------
# Panel loading (with enriched fallback via forecast_common)
# ---------------------------------------------------------------------------


def _load_enriched_panel(tickers: Optional[List[str]] = None) -> pd.DataFrame:
    """Load the enriched panel including static YCharts and institutional features."""
    try:
        from forecast_common import load_panel_with_features
        df = load_panel_with_features(tickers=tickers)
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
        return df.dropna(subset=["Date", "Ticker"]).sort_values(["Ticker", "Date"]).reset_index(drop=True)
    except Exception as e:
        if not PANEL_PATH.exists():
            raise FileNotFoundError(
                f"Neither forecast_common nor {PANEL_PATH} available: {e}"
            )
        df = pd.read_parquet(PANEL_PATH)
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
        return df.dropna(subset=["Date", "Ticker"]).sort_values(["Ticker", "Date"]).reset_index(drop=True)


def _get_registry_entry(feature_name: str) -> Optional[dict]:
    """Load registry entry for a feature (None if not registered)."""
    try:
        from feature_registry import FeatureRegistry
        return FeatureRegistry().get(feature_name)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_column_presence(df: pd.DataFrame, feature_name: str) -> Tuple[str, str, Optional[str]]:
    """Check 1: column exists in the enriched panel.
    Returns (flag, detail, resolved_column_name)."""
    # Direct match
    if feature_name in df.columns:
        return "PASS", f"Column '{feature_name}' found directly in panel.", feature_name

    # Try lower/upper variants
    col_lower = {c.lower(): c for c in df.columns}
    if feature_name.lower() in col_lower:
        resolved = col_lower[feature_name.lower()]
        return "PASS", f"Column resolved (case-insensitive): '{resolved}'.", resolved

    # Try canonical name map
    schema_path = Path("feature_store/schema/canonical_names.json")
    if schema_path.exists():
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            flat = schema.get("_flat_panel_to_registry", {})
            # Try registry  panel mapping
            for ftype in schema.values():
                if isinstance(ftype, dict) and feature_name in ftype:
                    panel_col = ftype[feature_name].get("panel_column") if isinstance(ftype[feature_name], dict) else None
                    if panel_col and panel_col in df.columns:
                        return "PASS", f"Column resolved via schema: '{panel_col}'.", panel_col
        except Exception:
            pass

    available = sorted(df.columns.tolist())
    return (
        "FAIL",
        f"Column '{feature_name}' not found in enriched panel.\n"
        f"Available columns include: {available[:20]}{'...' if len(available) > 20 else ''}",
        None,
    )


def _check_numeric_type(df: pd.DataFrame, col: str) -> Tuple[str, str]:
    """Check 2: values are castable to float."""
    series = pd.to_numeric(df[col], errors="coerce")
    n_coerced = int((series.isna() & df[col].notna()).sum())
    if n_coerced == 0:
        return "PASS", "All values are numeric or null."
    pct = n_coerced / len(df)
    if pct < 0.01:
        return "WARN", f"{n_coerced} values ({pct:.1%}) could not be cast to float. Check string formatting."
    return "FAIL", f"{n_coerced} values ({pct:.1%}) are non-numeric. Column may contain string labels or mixed types."


def _check_coverage(df: pd.DataFrame, col: str) -> Tuple[str, str]:
    """Check 3: sufficient non-null observations."""
    series = pd.to_numeric(df[col], errors="coerce")
    n_valid = int(series.notna().sum())
    null_rate = 1.0 - n_valid / len(series) if len(series) > 0 else 1.0

    if n_valid >= MIN_OBS_WARN:
        return "PASS", f"{n_valid:,} valid observations ({null_rate:.0%} null)."
    elif n_valid >= MIN_OBS_HARD:
        return "WARN", (
            f"Only {n_valid} valid observations ({null_rate:.0%} null). "
            f"Results may be unreliable. Recommend >= {MIN_OBS_WARN}."
        )
    else:
        return "FAIL", (
            f"Only {n_valid} valid observations. Minimum required: {MIN_OBS_HARD}. "
            f"Feature is too sparse for reliable testing."
        )


def _check_variance(df: pd.DataFrame, col: str) -> Tuple[str, str]:
    """Check 4: feature is not constant or near-constant."""
    series = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(series) == 0:
        return "FAIL", "No valid values to check variance."

    std = float(series.std())
    mean = float(series.mean())
    cv = abs(std / mean) if abs(mean) > 1e-10 else std  # coefficient of variation

    n_unique = series.nunique()
    if n_unique <= 1:
        return "FAIL", "Feature is constant (single unique value). Not predictive."
    if std < 1e-10:
        return "FAIL", f"Feature std  0. Near-constant. ({n_unique} unique values)"
    if n_unique <= 5:
        return "WARN", f"Only {n_unique} unique values  low resolution. May be categorical."

    return "PASS", f"std={std:.4f}, mean={mean:.4f}, {n_unique:,} unique values."


def _check_range_sanity(df: pd.DataFrame, col: str) -> Tuple[str, str]:
    """Check 5: no extreme outliers that suggest data errors."""
    series = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(series) < 10:
        return "WARN", "Too few values for range check."

    # Use IQR-based outlier detection
    q1, q3 = float(series.quantile(0.01)), float(series.quantile(0.99))
    iqr = q3 - q1
    if iqr < 1e-10:
        return "WARN", "IQR  0. Distribution is very concentrated  check for data quality issues."

    lower_bound = q1 - 10 * iqr
    upper_bound = q3 + 10 * iqr
    n_extreme = int(((series < lower_bound) | (series > upper_bound)).sum())
    pct = n_extreme / len(series)

    if n_extreme == 0:
        return "PASS", f"No extreme outliers. 1st-99th pctile range: [{q1:.4f}, {q3:.4f}]."
    elif pct < 0.005:
        return "WARN", (
            f"{n_extreme} extreme outliers ({pct:.2%}) beyond 10x IQR. "
            f"Range [{q1:.4f}, {q3:.4f}]. Consider winsorization."
        )
    else:
        return "FAIL", (
            f"{n_extreme} extreme outliers ({pct:.2%})  possible data errors. "
            f"Range [{q1:.4f}, {q3:.4f}]. Investigate before testing."
        )


def _check_lag_plausibility(entry: Optional[dict]) -> Tuple[str, str]:
    """Check 6: lag_days is consistent with update_frequency."""
    if not entry:
        return "WARN", "Feature not in registry  lag_days unknown. Register before testing."

    lag_days = entry.get("lag_days", 1)
    freq = entry.get("update_frequency", "daily")
    pit = entry.get("point_in_time", True)

    if lag_days < 1:
        return "FAIL", f"lag_days={lag_days} is invalid. Must be >= 1."

    if freq == "quarterly" and lag_days < 21:
        return "WARN", (
            f"Quarterly feature has lag_days={lag_days}. "
            f"Quarterly data typically has 45-90 day publication lag. "
            f"Increase lag_days to reduce forward-looking risk."
        )

    if not pit and lag_days < 21:
        return "WARN", (
            f"Non-PIT feature (point_in_time=False) has lag_days={lag_days}. "
            f"Non-PIT features should have lag_days >= 21 to be conservative."
        )

    return "PASS", f"lag_days={lag_days}, update_frequency={freq}, point_in_time={pit}."


def _check_pit_consistency(entry: Optional[dict]) -> Tuple[str, str]:
    """Check 7: point_in_time flag is consistent with feature construction."""
    if not entry:
        return "WARN", "Not in registry  cannot verify PIT consistency."

    pit = entry.get("point_in_time", True)
    freq = entry.get("update_frequency", "daily")
    lag = entry.get("lag_days", 1)
    source = entry.get("source", "")

    issues = []
    if not pit and lag < 21:
        issues.append(f"non-PIT with lag_days={lag} (too low)")
    if "ycharts" in source.lower() and pit and freq == "quarterly":
        issues.append("YCharts quarterly data marked as PIT  verify timing")
    if "derived_target" in source and lag < 22:
        issues.append("derived-target feature with lag_days < 22  potential forward look")

    if not issues:
        return "PASS", f"PIT flag consistent: point_in_time={pit}, source={source}."
    return "WARN", "PIT consistency issues: " + "; ".join(issues)


def _check_stationarity(df: pd.DataFrame, col: str) -> Tuple[str, str]:
    """Check 8: ADF unit-root test (WARN if non-stationary, never FAIL)."""
    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        return "WARN", "statsmodels not available. Stationarity check skipped."

    series = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(series) < 50:
        return "WARN", "Too few values for ADF test."

    # Use cross-section of all observations (not per-ticker time series)
    # This is a heuristic check, not a strict statistical test
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            adf_result = adfuller(series.values, autolag="AIC", maxlag=10)
            p_value = float(adf_result[1])
            adf_stat = float(adf_result[0])
        except Exception as e:
            return "WARN", f"ADF test failed: {e}"

    if p_value <= 0.05:
        return "PASS", f"Stationary (ADF p={p_value:.4f}, stat={adf_stat:.3f}). Unit root rejected."
    elif p_value <= 0.10:
        return "WARN", (
            f"Borderline stationary (ADF p={p_value:.4f}). "
            f"May have weak non-stationarity. Monitor over time."
        )
    else:
        return "WARN", (
            f"Possibly non-stationary (ADF p={p_value:.4f}). "
            f"Feature may have a unit root. Consider differencing or normalization."
        )


def _check_registry_integrity(feature_name: str, entry: Optional[dict]) -> Tuple[str, str]:
    """Check 9: registry entry has required fields populated."""
    if not entry:
        return "WARN", f"Feature '{feature_name}' not registered. Add via feature_registry.py before promoting."

    required_fields = [
        "description", "source", "feature_type", "panel_column",
        "first_available_date", "lag_days", "point_in_time",
    ]
    missing = [f for f in required_fields if entry.get(f) is None]
    if missing:
        return "WARN", f"Registry entry missing fields: {missing}. Complete before promotion."

    # Check panel_column matches what we found
    if entry.get("panel_column") and entry["panel_column"] != feature_name:
        return "PASS", (
            f"Registry points to panel_column='{entry['panel_column']}'. "
            f"Feature name '{feature_name}' is the registry key."
        )

    return "PASS", "Registry entry complete with all required fields."


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def validate_feature(
    feature_name: str,
    tickers: Optional[List[str]] = None,
    strict: bool = False,
    save: bool = True,
) -> dict:
    """Run all pre-test validation checks for a feature.

    Args:
        feature_name: Registry name or panel column name.
        tickers: Optional subset of tickers.
        strict: If True, treat WARN as FAIL for blocking decisions.
        save: Save validation report to feature_store/testing/validation/.

    Returns:
        Validation report dict. Check result["overall"] for PASS/WARN/FAIL.
    """
    print(f"\n[feature_validator] Validating: {feature_name}")
    print("=" * 55)

    entry = _get_registry_entry(feature_name)

    # Load panel (may use enriched version)
    try:
        df = _load_enriched_panel(tickers=tickers)
    except Exception as exc:
        return {
            "feature_name": feature_name,
            "validation_date": str(date.today()),
            "overall": "FAIL",
            "blocking_reason": f"Could not load training panel: {exc}",
            "checks": {},
        }

    # Resolve column
    col_flag, col_detail, resolved_col = _check_column_presence(df, feature_name)
    print(f"  column_presence     [{col_flag}]  {col_detail[:70]}")

    if col_flag == "FAIL":
        result = {
            "feature_name": feature_name,
            "validation_date": str(date.today()),
            "overall": "FAIL",
            "blocking_reason": col_detail,
            "checks": {"column_presence": {"flag": col_flag, "detail": col_detail}},
        }
        if save:
            _save_report(feature_name, result)
        return result

    col = resolved_col  # use the resolved column name for all subsequent checks

    checks = {
        "column_presence": {"flag": col_flag, "detail": col_detail, "resolved_column": col},
    }

    check_fns = [
        ("numeric_type",       lambda: _check_numeric_type(df, col)),
        ("coverage",           lambda: _check_coverage(df, col)),
        ("variance",           lambda: _check_variance(df, col)),
        ("range_sanity",       lambda: _check_range_sanity(df, col)),
        ("lag_plausibility",   lambda: _check_lag_plausibility(entry)),
        ("pit_consistency",    lambda: _check_pit_consistency(entry)),
        ("stationarity",       lambda: _check_stationarity(df, col)),
        ("registry_integrity", lambda: _check_registry_integrity(feature_name, entry)),
    ]

    flags = [col_flag]
    for check_name, fn in check_fns:
        try:
            flag, detail = fn()
        except Exception as exc:
            flag, detail = "WARN", f"Check failed with error: {exc}"
        checks[check_name] = {"flag": flag, "detail": detail}
        flags.append(flag)
        marker = "[FAIL]" if flag == "FAIL" else ("[WARN]" if flag == "WARN" else "[PASS]")
        print(f"  {check_name:<22s} {marker}  {detail[:65]}")

    # Overall verdict
    if "FAIL" in flags:
        overall = "FAIL"
        blocking = next(
            (checks[k]["detail"] for k in checks if checks[k]["flag"] == "FAIL"),
            "One or more checks failed."
        )
    elif "WARN" in flags and strict:
        overall = "FAIL"
        blocking = "Strict mode: WARN treated as FAIL."
    elif "WARN" in flags:
        overall = "WARN"
        blocking = None
    else:
        overall = "PASS"
        blocking = None

    print(f"\n  Overall: [{overall}]")
    if blocking:
        print(f"  Blocking: {blocking}")

    result = {
        "feature_name": feature_name,
        "resolved_column": col,
        "validation_date": str(date.today()),
        "overall": overall,
        "blocking_reason": blocking,
        "panel_rows": len(df),
        "tickers": df["Ticker"].nunique(),
        "checks": checks,
        "registry_stage": entry.get("stage") if entry else None,
    }

    if save:
        _save_report(feature_name, result)

    return result


def _save_report(feature_name: str, report: dict) -> None:
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{feature_name.lower()}_{date.today().strftime('%Y%m%d')}_validation.json"
    out_path = VALIDATION_DIR / fname
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"  Saved: {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Pre-test validation for a candidate feature.")
    ap.add_argument("--feature", type=str, required=True, help="Feature name to validate")
    ap.add_argument("--tickers", type=str, default=None, help="Comma-separated ticker subset")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Treat WARN as FAIL (stricter gate for DL promotion)",
    )
    ap.add_argument("--no-save", action="store_true", help="Do not write validation report to disk")
    return ap


def main() -> None:
    args = _build_parser().parse_args()
    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers
        else None
    )
    result = validate_feature(
        args.feature,
        tickers=tickers,
        strict=args.strict,
        save=not args.no_save,
    )
    if result["overall"] == "FAIL":
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()
