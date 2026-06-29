"""QuantConnect-style cross-sectional factor model for MAG7 21-day forecasts.

History / fix (6/29): the original model collapsed five standardized factors into a
single fixed-weight "Quant Score" scalar and then regressed forward return on that
ONE feature. The fitted slope was near zero, so every ticker received essentially
the intercept (the mean forward return) — the forecasts were near-constant
(~1.9-2.9% for all seven names regardless of their factor exposures).

The fix keeps the model's identity (a cross-sectional institutional factor model on
the same five momentum/volatility factors) but regresses forward return on the five
standardized factors DIRECTLY (multivariate). Each factor now gets its own fitted
coefficient, so a ticker's forecast reflects its actual cross-sectional exposures and
the outputs disperse. Training and live prediction use the SAME per-date
cross-sectional standardization, removing the old train/predict inconsistency.

The module is import-safe (no work at import time) so the walk-forward backfill can
reuse fit_forecast_model / forecast_cross_section to reconstruct point-in-time
forecasts.
"""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.linear_model import LinearRegression

from data_utils import load_features, save_features, upsert_features

# --- Constants ---
MAG7 = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]
HORIZON = 21
FEATURES = ["1M Return", "3M Return", "12M Return", "Volatility", "MA200 Gap"]

# Legacy institutional weights — retained ONLY to report the descriptive "Quant
# Score" diagnostic. The forecast no longer collapses the factors through them.
QUANT_SCORE_WEIGHTS = {
    "1M Return": 0.10,
    "3M Return": 0.20,
    "12M Return": 0.30,
    "Volatility": 0.20,
    "MA200 Gap": 0.20,
}


# --- Download Price Data with Retry ---

def fetch_data(tickers: List[str], start, end, retries: int = 2, delay: int = 3) -> pd.DataFrame:
    data = pd.DataFrame()
    for attempt in range(retries):
        try:
            data = yf.download(tickers, start=start, end=end, auto_adjust=True)["Close"].ffill()
            if set(tickers).issubset(set(data.columns)):
                return data
            missing = set(tickers) - set(data.columns)
            print(f" Missing tickers on attempt {attempt + 1}: {missing}")
        except Exception as e:
            print(f" Attempt {attempt + 1} failed: {e}")
        time.sleep(delay)
    print(" Final attempt failed. Some tickers may be missing.")
    return data


# --- Factor construction ---

def compute_signals(prices: pd.DataFrame, tickers: List[str] = MAG7) -> pd.DataFrame:
    """Build the per-(ticker, date) factor panel plus the realized forward return."""
    signals = {}
    for ticker in tickers:
        try:
            if ticker not in prices.columns:
                continue
            p = prices[ticker].dropna()
            if len(p) < 260:
                continue

            r_1m = p.pct_change(21)
            r_3m = p.pct_change(63)
            r_12m = (p / p.shift(252)) - 1
            vol = p.pct_change().rolling(63).std() * np.sqrt(252)
            ma200 = p.rolling(200).mean()
            momentum_gap = (p - ma200) / ma200
            fwd_return = p.pct_change(periods=HORIZON).shift(-HORIZON)

            df = pd.DataFrame({
                "1M Return": r_1m,
                "3M Return": r_3m,
                "12M Return": r_12m,
                "Volatility": vol,
                "MA200 Gap": momentum_gap,
                "Forward Return": fwd_return,
            }).dropna(subset=FEATURES)

            df["Ticker"] = ticker
            df.index.name = "Date"
            signals[ticker] = df
        except Exception as e:
            print(f" Error with {ticker}: {e}")

    return pd.concat(signals.values()) if signals else pd.DataFrame()


def _zscore(x: pd.Series) -> pd.Series:
    """Cross-sectional z-score; degenerate (near-zero spread) -> zeros, not NaN/inf."""
    sd = float(x.std(ddof=0))
    if not np.isfinite(sd) or sd < 1e-9:
        return pd.Series(0.0, index=x.index)
    return (x - float(x.mean())) / sd


def zscore_within_date(df: pd.DataFrame, features: List[str] = FEATURES) -> pd.DataFrame:
    """Standardize each factor cross-sectionally within each date (across the universe)."""
    out = df.copy()
    out[features] = out.groupby(level=0)[features].transform(_zscore)
    return out


def fit_forecast_model(signal_df: pd.DataFrame, features: List[str] = FEATURES) -> Optional[LinearRegression]:
    """Multivariate OLS: standardized factors -> forward return (in %).

    Returns None if there is not enough labeled data to fit."""
    df = signal_df.dropna(subset=features + ["Forward Return"])
    if len(df) < (len(features) + 5):
        return None
    z = zscore_within_date(df, features)
    X = z[features].to_numpy(dtype=float)
    y = (df["Forward Return"].to_numpy(dtype=float)) * 100.0
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if ok.sum() < (len(features) + 5):
        return None
    return LinearRegression().fit(X[ok], y[ok])


def quant_score(z_row: pd.Series, features: List[str] = FEATURES) -> float:
    """Legacy descriptive composite (kept for display only)."""
    avail = [f for f in features if f in z_row.index and pd.notna(z_row[f])]
    if not avail:
        return float("nan")
    total = sum(QUANT_SCORE_WEIGHTS[f] for f in avail)
    if total <= 0:
        return float("nan")
    return float(sum(z_row[f] * (QUANT_SCORE_WEIGHTS[f] / total) for f in avail))


def forecast_cross_section(
    model: LinearRegression,
    live_factors: pd.DataFrame,
    features: List[str] = FEATURES,
) -> pd.DataFrame:
    """Forecast a single cross-section (one row per ticker, raw factor values).

    Standardizes the factors cross-sectionally across the supplied tickers — the
    SAME transform training uses per date — then applies the multivariate model."""
    live = live_factors.dropna(subset=features).copy()
    if live.empty or model is None:
        return pd.DataFrame(columns=["Ticker", "Quant Score", "QuantConnect Forecast (%)"])

    z = live.copy()
    for f in features:
        z[f] = _zscore(live[f])

    X = z[features].to_numpy(dtype=float)
    preds = model.predict(X)

    rows = []
    for i, (_, row) in enumerate(live.iterrows()):
        zr = z.iloc[i][features]
        rows.append({
            "Ticker": row["Ticker"],
            "Quant Score": round(quant_score(zr), 3),
            "QuantConnect Forecast (%)": round(float(preds[i]), 2),
        })
    return pd.DataFrame(rows)


def _latest_factor_row(prices: pd.DataFrame, ticker: str) -> Optional[dict]:
    """Compute today's raw factor values for one ticker from its price history."""
    if ticker not in prices.columns:
        return None
    p = prices[ticker].dropna()
    if len(p) < 252:
        return None
    ma200 = p.iloc[-200:].mean()
    return {
        "Ticker": ticker,
        "1M Return": p.pct_change(21).iloc[-1],
        "3M Return": p.pct_change(63).iloc[-1],
        "12M Return": (p.iloc[-1] / p.iloc[-252]) - 1,
        "Volatility": p.pct_change().rolling(63).std().iloc[-1] * np.sqrt(252),
        "MA200 Gap": (p.iloc[-1] - ma200) / ma200,
    }


def main() -> None:
    today = pd.Timestamp.today().normalize()
    start = today - timedelta(days=365 * 2)

    print(" Downloading MAG7 price data...")
    data = fetch_data(MAG7, start=start, end=today)
    if data.empty:
        print(" No price data — exiting.")
        return

    print(" Computing signals...")
    signal_df = compute_signals(data)
    if signal_df.empty:
        print(" No valid signals — exiting.")
        return

    model = fit_forecast_model(signal_df)
    if model is None:
        print(" Not enough labeled data to fit the model — exiting.")
        return

    print(" Computing live forecasts...")
    latest = data.iloc[-252:].copy()
    live_rows = [r for t in MAG7 if (r := _latest_factor_row(latest, t)) is not None]
    if not live_rows:
        print(" No live factor rows — exiting.")
        return

    live_factors = pd.DataFrame(live_rows)
    df_out = forecast_cross_section(model, live_factors)
    if df_out.empty:
        print(" No forecasts generated — exiting.")
        return

    df_out["Date"] = today
    df_out.set_index("Ticker").to_csv("data/quantconnect_forecasts.csv")
    print(" QuantConnect-style forecasts saved to data/quantconnect_forecasts.csv")
    print(df_out.to_string(index=False))

    # Persist the latest per-ticker standardized factor row + Quant Score for
    # forecast_common.py (qc_ret_*, quant_score model inputs). Same semantics as
    # before the multivariate fix: per-date cross-sectional z-scores, last row.
    try:
        zsig = zscore_within_date(signal_df.dropna(subset=FEATURES))
        zsig["Quant Score"] = zsig[FEATURES].apply(quant_score, axis=1).round(3)
        latest_rows = zsig.reset_index().sort_values("Date").groupby("Ticker").last()
        latest_rows.to_parquet("data/quantconnect_features.parquet")
        print(" QuantConnect features saved to data/quantconnect_features.parquet")
    except Exception as e:
        print(f" Warning: could not write quantconnect_features.parquet: {e}")

    # Upsert into features.parquet
    base = load_features()
    base = upsert_features(
        base, df_out[["Ticker", "Quant Score", "QuantConnect Forecast (%)"]], date_value=today
    )
    save_features(base)
    print(" Updated features.parquet with QuantConnect model outputs (upsert).")


if __name__ == "__main__":
    main()
