"""record_predictions.py

Append today's model predictions into data/prediction_log.parquet so we can
score them later in backtest_predictions.py.

Logs ONE row per (RunDate, Ticker, Model).

Key improvements vs prior versions:
- Robust parsing of forecast values stored as strings (e.g. "1.23%", "(0.45)", " 2,345.6 ")
- Parquet-safe schema coercion (prevents RunDate dtype mix errors)
- Optional --debug flag prints which model columns were found and how many rows logged per model
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
FEATURES_PATH = DATA_DIR / "features.parquet"
LOG_PATH = DATA_DIR / "prediction_log.parquet"

DEFAULT_TICKERS = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]
HORIZON = 21


def _safe_read_features() -> pd.DataFrame:
    """Load features.parquet (prefer data_utils.load_features if available)."""
    try:
        from data_utils import load_features  # type: ignore
        df = load_features()
        if isinstance(df, pd.DataFrame) and len(df):
            return df
    except Exception:
        pass

    if not FEATURES_PATH.exists():
        raise FileNotFoundError(f"features.parquet not found at {FEATURES_PATH}")
    return pd.read_parquet(FEATURES_PATH)


def _first_present(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _to_float(x) -> float:
    """Parse numeric values even if stored as strings like '1.23%' or '(0.45)'."""
    if x is None:
        return float("nan")
    try:
        if pd.isna(x):
            return float("nan")
    except Exception:
        pass

    # Fast path for numeric types
    if isinstance(x, (int, float, np.integer, np.floating)):
        try:
            return float(x)
        except Exception:
            return float("nan")

    # String parsing
    try:
        s = str(x).strip()
    except Exception:
        return float("nan")

    if not s or s.lower() in {"nan", "none", "nat"}:
        return float("nan")

    # Handle parentheses negative: (0.45) -> -0.45
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()

    # Remove percent sign and commas/spaces
    s = s.replace("%", "").replace(",", "").strip()

    # Some outputs could be like '+1.2' or '1.2' (unicode minus)
    s = s.replace("", "-").replace("+", "")

    try:
        val = float(s)
        return -val if neg else val
    except Exception:
        return float("nan")


def _normalize_one_date(v) -> Optional[str]:
    """Return YYYY-MM-DD string or None."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass

    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "nat"}:
        return None

    if s.isdigit() and len(s) == 8:
        dt = pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    else:
        dt = pd.to_datetime(s, errors="coerce")
    if pd.isna(dt):
        return None
    return dt.date().isoformat()


def _build_model_map(df: pd.DataFrame) -> Dict[str, Dict[str, Optional[str]]]:
    """Map each model to its forecast col + CI cols (if any)."""
    model_forecast_candidates: Dict[str, List[str]] = {
        "FamaFrench": ["FF Forecast (%)", "FF Forecast", "FF_Forecast (%)"],
        "Institutional": [
            "Institutional Forecast (%)",
            "Institutional Forecast",
            "Institutional_Forecast (%)",
            "Institutional Model Forecast (%)",
        ],
        "QuantConnect": [
            "QuantConnect Forecast (%)",
            "QuantConnect Forecast",
            "QuantConnect_Model_Forecast (%)",
        ],
        "Linear": ["Linear Model Forecast (%)", "Linear Forecast (%)", "Linear Forecast"],
        "ML": ["ML Forecast (%)", "ML Model Forecast (%)", "ML Forecast"],
        "DeepLearning": ["DL Forecast (%)", "Deep Learning Forecast (%)", "DL Forecast"],
    }

    model_ci_candidates: Dict[str, Tuple[List[str], List[str]]] = {
        "Linear": (["Linear_CI_Lower"], ["Linear_CI_Upper"]),
        "ML": (["ML_CI_Lower"], ["ML_CI_Upper"]),
        "DeepLearning": (["DL_CI_Lower", "DL_CI_Lower (%)"], ["DL_CI_Upper", "DL_CI_Upper (%)"]),
    }

    model_map: Dict[str, Dict[str, Optional[str]]] = {}
    for model, cands in model_forecast_candidates.items():
        fcol = _first_present(df, cands)
        if fcol is None:
            continue

        ci_lower = None
        ci_upper = None
        if model in model_ci_candidates:
            lcands, ucands = model_ci_candidates[model]
            ci_lower = _first_present(df, lcands)
            ci_upper = _first_present(df, ucands)

        model_map[model] = {"forecast": fcol, "ci_lower": ci_lower, "ci_upper": ci_upper}

    return model_map


def _find_asof_col(df: pd.DataFrame) -> Optional[str]:
    return _first_present(df, ["Date", "DL_Date", "Forecast_Date", "AsOfDate"])


def _ensure_log_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Force stable schema + parquet-safe dtypes."""
    cols = ["RunDate", "Ticker", "Model", "Horizon", "ForecastPct", "CI_Lower", "CI_Upper", "AsOfDate"]
    if df is None or len(df) == 0:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in cols})

    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA

    df["RunDate"] = df["RunDate"].apply(_normalize_one_date).astype("string")
    df["AsOfDate"] = df["AsOfDate"].apply(_normalize_one_date).astype("string")

    df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip().astype("string")
    df["Model"] = df["Model"].astype(str).str.strip().astype("string")

    df["Horizon"] = pd.to_numeric(df["Horizon"], errors="coerce").fillna(HORIZON).astype(int)

    for c in ["ForecastPct", "CI_Lower", "CI_Upper"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    return df[cols]


def record_predictions(tickers: List[str], log_path: Path = LOG_PATH, debug: bool = False) -> int:
    features = _safe_read_features().copy()

    if "Ticker" not in features.columns:
        raise ValueError("features.parquet is missing required column 'Ticker'")

    features["Ticker"] = features["Ticker"].astype(str).str.upper().str.strip()
    tickers = [t.strip().upper() for t in tickers if t.strip()]
    features = features[features["Ticker"].isin(tickers)].copy()

    if features.empty:
        print(" No matching tickers found in features.parquet. Nothing to log.")
        return 0

    model_map = _build_model_map(features)
    if not model_map:
        print(" No forecast columns found in features.parquet. Nothing to log.")
        return 0

    run_date = date.today().isoformat()
    asof_col = _find_asof_col(features)

    if debug:
        print(" Detected forecast columns:")
        for m, cols in model_map.items():
            print(f" - {m}: {cols['forecast']} (CI: {cols.get('ci_lower')}, {cols.get('ci_upper')})")
        if asof_col:
            print(f" AsOf/Date column detected: {asof_col}")

    records: List[dict] = []
    per_model = {m: 0 for m in model_map.keys()}

    for _, row in features.iterrows():
        t = str(row["Ticker"]).strip().upper()

        for model, cols in model_map.items():
            fcol = cols.get("forecast")
            if not fcol:
                continue

            forecast = _to_float(row.get(fcol, np.nan))
            if np.isnan(forecast):
                continue

            ci_l = _to_float(row.get(cols.get("ci_lower"), np.nan)) if cols.get("ci_lower") else float("nan")
            ci_u = _to_float(row.get(cols.get("ci_upper"), np.nan)) if cols.get("ci_upper") else float("nan")

            asof = _normalize_one_date(row.get(asof_col)) if asof_col else None

            records.append(
                {
                    "RunDate": run_date,
                    "Ticker": t,
                    "Model": model,
                    "Horizon": HORIZON,
                    "ForecastPct": float(forecast),
                    "CI_Lower": float(ci_l) if not np.isnan(ci_l) else np.nan,
                    "CI_Upper": float(ci_u) if not np.isnan(ci_u) else np.nan,
                    "AsOfDate": asof,
                }
            )
            per_model[model] += 1

    if not records:
        print(" No non-null model forecasts found to log.")
        if debug:
            print("Model map existed, but all values parsed as NaN.")
        return 0

    new_log = _ensure_log_schema(pd.DataFrame.from_records(records))

    if log_path.exists():
        old = _ensure_log_schema(pd.read_parquet(log_path))
        combined = pd.concat([old, new_log], ignore_index=True)
    else:
        combined = new_log

    combined = combined.drop_duplicates(subset=["RunDate", "Ticker", "Model"], keep="last")
    combined = _ensure_log_schema(combined)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(log_path, index=False)

    n_today = int((combined["RunDate"] == run_date).sum())
    print(f" Logged {n_today} predictions for {run_date} -> {log_path}")

    if debug:
        print(" Logged rows per model (this run):")
        for m, n in per_model.items():
            print(f" - {m}: {n}")
    return n_today


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=str, default=",".join(DEFAULT_TICKERS), help="Comma-separated tickers to log")
    ap.add_argument("--log-path", type=str, default=str(LOG_PATH))
    ap.add_argument("--debug", action="store_true", help="Print detected columns and per-model counts")
    args = ap.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    record_predictions(tickers=tickers, log_path=Path(args.log_path), debug=bool(args.debug))


if __name__ == "__main__":
    main()
