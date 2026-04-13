# sync_forecasts_to_features.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
FEATURES_PATH = DATA_DIR / "features.parquet"


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    return None


def _load_csv(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f" Could not read {path}: {e}")
        return None


def _to_numeric_series(s: pd.Series) -> pd.Series:
    # Strip percent signs/commas if present
    if s.dtype == "object":
        s2 = (
            s.astype(str)
            .str.replace("%", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.strip()
        )
        s2 = s2.replace({"nan": np.nan, "None": np.nan, "NaT": np.nan, "": np.nan})
        return pd.to_numeric(s2, errors="coerce")
    return pd.to_numeric(s, errors="coerce")


def _apply_updates(base: pd.DataFrame, src: pd.DataFrame, ticker_col: str, mapping: Dict[str, str]) -> pd.DataFrame:
    """
    mapping: {source_col -> target_col}
    Updates base[target_col] for matching tickers where source is non-null.
    """
    src = src.copy()
    src[ticker_col] = src[ticker_col].astype(str).str.upper().str.strip()

    base = base.copy()
    base["Ticker"] = base["Ticker"].astype(str).str.upper().str.strip()

    base_idx = base.set_index("Ticker")
    src_idx = src.set_index(ticker_col)

    for src_col, tgt_col in mapping.items():
        if src_col not in src_idx.columns:
            continue

        if tgt_col not in base_idx.columns:
            base_idx[tgt_col] = np.nan

        u = src_idx[src_col].reindex(base_idx.index)

        if tgt_col.endswith("_Date"):
            u2 = pd.to_datetime(u, errors="coerce").dt.date.astype("string")
            base_idx[tgt_col] = base_idx[tgt_col].where(u2.isna(), u2)
        else:
            u2 = _to_numeric_series(u)
            base_idx[tgt_col] = base_idx[tgt_col].where(u2.isna(), u2)

    return base_idx.reset_index()


def main():
    if not FEATURES_PATH.exists():
        raise FileNotFoundError(f"Missing {FEATURES_PATH}. Run features.py first.")

    base = pd.read_parquet(FEATURES_PATH)
    if "Ticker" not in base.columns:
        raise ValueError("features.parquet missing 'Ticker' column")

    configs = [
        ("fama_french_forecasts.csv",
         ["Ticker", "ticker", "Symbol", "symbol"],
         {"FF Forecast (%)": "FF Forecast (%)", "FF Forecast": "FF Forecast (%)", "Date": "FF_Date"}),

        ("institutional_forecasts.csv",
         ["Ticker", "ticker", "Symbol", "symbol"],
         {"Institutional Forecast (%)": "Institutional Forecast (%)",
          "Institutional Forecast": "Institutional Forecast (%)",
          "Date": "Institutional_Date"}),

        ("quantconnect_forecasts.csv",
         ["Ticker", "ticker", "Symbol", "symbol"],
         {"QuantConnect Forecast (%)": "QuantConnect Forecast (%)",
          "QuantConnect Forecast": "QuantConnect Forecast (%)",
          "Date": "QuantConnect_Date"}),

        ("linear_forecasts.csv",
         ["Ticker", "ticker", "Symbol", "symbol"],
         {"Linear Model Forecast (%)": "Linear Model Forecast (%)",
          "Linear Forecast (%)": "Linear Model Forecast (%)",
          "Linear_CI_Lower": "Linear_CI_Lower",
          "Linear_CI_Upper": "Linear_CI_Upper",
          "Date": "Linear_Date"}),

        ("ml_forecasts.csv",
         ["Ticker", "ticker", "Symbol", "symbol"],
         {"ML Forecast (%)": "ML Forecast (%)",
          "ML Model Forecast (%)": "ML Forecast (%)",
          "ML_CI_Lower": "ML_CI_Lower",
          "ML_CI_Upper": "ML_CI_Upper",
          "Date": "ML_Date"}),

        ("dl_forecasts.csv",
         ["Ticker", "ticker", "Symbol", "symbol"],
         {"DL Forecast (%)": "DL Forecast (%)",
          "Deep Learning Forecast (%)": "DL Forecast (%)",
          "DL_CI_Lower": "DL_CI_Lower",
          "DL_CI_Upper": "DL_CI_Upper",
          "Date": "DL_Date",
          "DL_Date": "DL_Date"}),
    ]

    for fname, ticker_candidates, col_map in configs:
        path = DATA_DIR / fname
        df = _load_csv(path)
        if df is None or df.empty:
            continue

        tcol = _find_col(df, ticker_candidates)
        if not tcol:
            print(f" {fname}: could not find ticker column; skipping")
            continue

        mapping = {src: tgt for src, tgt in col_map.items() if src in df.columns}
        if not mapping:
            forecast_like = [c for c in df.columns if "forecast" in c.lower()]
            if forecast_like:
                mapping = {forecast_like[0]: forecast_like[0]}
            else:
                print(f" {fname}: no forecast columns found; skipping")
                continue

        before = base.copy()
        base = _apply_updates(base, df, tcol, mapping)

        filled = 0
        for tgt in set(mapping.values()):
            if tgt in before.columns and tgt in base.columns:
                filled += int((before[tgt].isna() & base[tgt].notna()).sum())
        if filled:
            print(f" {fname}: filled {filled} previously-missing values")

    base.to_parquet(FEATURES_PATH, index=False)

    mag7 = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]
    m = base[base["Ticker"].isin(mag7)].copy()
    summary_cols = [c for c in [
        "FF Forecast (%)",
        "Institutional Forecast (%)",
        "QuantConnect Forecast (%)",
        "Linear Model Forecast (%)",
        "ML Forecast (%)",
        "DL Forecast (%)",
    ] if c in m.columns]
    counts = {c: int(m[c].notna().sum()) for c in summary_cols}
    print(" MAG7 non-null forecast counts:", counts)
    print(f" Synced forecasts into {FEATURES_PATH}")


if __name__ == "__main__":
    main()