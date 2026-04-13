"""features.py

Builds the daily `data/features.parquet` snapshot used by the report and models.

This version fixes:
- Join collisions when multiple model forecast files contain generic CI_Lower/CI_Upper.
- Ensures 'Momentum Z' exists for *all* tickers where enough history exists.
- Avoids dropping rows aggressively; models handle missing values.
"""

from __future__ import annotations

import os
import time
from datetime import timedelta
from io import StringIO

import numpy as np
import pandas as pd
try:
    import yfinance as yf
except Exception:
    yf = None
from sklearn.linear_model import LinearRegression

try:
    from universe_config import get_portfolio_tickers
except Exception:
    get_portfolio_tickers = None


def _extract_closes(prices: pd.DataFrame) -> pd.DataFrame:
    """Return a Date-indexed DataFrame of close prices with columns=tickers.

    Handles yfinance outputs with:
    - MultiIndex columns like (Ticker, Field) when group_by='ticker'
    - MultiIndex columns like (Field, Ticker) when group_by='column'
    - SingleIndex OHLC columns for single-ticker downloads
    """
    if prices is None or (hasattr(prices, "empty") and prices.empty):
        return pd.DataFrame()

    # SingleIndex columns: either OHLC (single ticker) or already close-only (columns=tickers)
    if isinstance(prices, pd.DataFrame) and not isinstance(prices.columns, pd.MultiIndex):
        cols_l = {str(c).lower(): c for c in prices.columns}
        if "close" in cols_l:
            # This is likely a single-ticker OHLC frame. We cannot infer the ticker reliably here;
            # return a 1-col DataFrame named 'SPY' if possible, else 'SINGLE'.
            col = cols_l["close"]
            name = "SPY" if "spy" in cols_l else "SINGLE"
            return prices[[col]].rename(columns={col: name})
        if "adj close" in cols_l:
            col = cols_l["adj close"]
            name = "SPY" if "spy" in cols_l else "SINGLE"
            return prices[[col]].rename(columns={col: name})
        return prices

    if not isinstance(prices.columns, pd.MultiIndex):
        return prices  # best effort

    lvl0 = prices.columns.get_level_values(0)
    lvl1 = prices.columns.get_level_values(1)
    lvl0_l = set(map(lambda x: str(x).lower(), lvl0))
    lvl1_l = set(map(lambda x: str(x).lower(), lvl1))

    # Case A: (Field, Ticker) => level0 has 'close'
    if "close" in lvl0_l:
        # preserve original label case
        close_label = next(x for x in set(lvl0) if str(x).lower() == "close")
        return prices[close_label]

    # Case B: (Ticker, Field) => level1 has 'close'
    if "close" in lvl1_l:
        close_label = next(x for x in set(lvl1) if str(x).lower() == "close")
        return prices.xs(close_label, level=1, axis=1, drop_level=True)

    # Fallback: Adj Close
    if "adj close" in lvl0_l:
        label = next(x for x in set(lvl0) if str(x).lower() == "adj close")
        return prices[label]
    if "adj close" in lvl1_l:
        label = next(x for x in set(lvl1) if str(x).lower() == "adj close")
        return prices.xs(label, level=1, axis=1, drop_level=True)

    return pd.DataFrame()

    # Single-ticker, OHLC columns
    if isinstance(prices, pd.DataFrame) and not isinstance(prices.columns, pd.MultiIndex):
        cols = {str(c).lower(): c for c in prices.columns}
        for key in ("close", "adj close", "adjclose"):
            if key in cols:
                return prices[[cols[key]]].rename(columns={cols[key]: "CLOSE"}).rename(columns={"CLOSE": cols[key]})
        # If it's already a close-only frame (columns=tickers), return as-is
        return prices

    if not isinstance(prices.columns, pd.MultiIndex):
        return prices

    lvl0 = set(map(str, prices.columns.get_level_values(0)))
    lvl1 = set(map(str, prices.columns.get_level_values(1)))

    # Case A: (Field, Ticker) => level0 has 'Close'
    if "Close" in lvl0:
        closes = prices["Close"]
        # closes columns are tickers
        return closes

    # Case B: (Ticker, Field) => level1 has 'Close'
    if "Close" in lvl1:
        closes = prices.xs("Close", level=1, axis=1, drop_level=True)
        return closes

    # Fallback: try Adj Close
    if "Adj Close" in lvl0:
        return prices["Adj Close"]
    if "Adj Close" in lvl1:
        return prices.xs("Adj Close", level=1, axis=1, drop_level=True)

    return pd.DataFrame()


EXPECTED_COLUMNS = [
    "Ticker",
    "Price",
    "P/E Ratio",
    "ROE",
    "Max Drawdown 3Y",
    "200d MA",
    "Sharpe (3Y)",
    "Alpha (3Y)",
    "Beta (3Y)",
    "Standard Deviation 3Y",
    "Up/Down Ratio",
]

MAG7 = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]
INDEXES = ["^SPX", "^STOXX50E", "^N225", "^MSACAS", "^MSEUR"]


def clean_ticker(ticker: str) -> str:
    return str(ticker).replace("M:", "")


def _read_forecast_csv(path: str, *, prefix: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "Ticker" not in df.columns:
        raise ValueError(f"'Ticker' column not found in {path}")

    # Normalize generic CI columns to prefixed names
    if prefix:
        if "CI_Lower" in df.columns and f"{prefix}_CI_Lower" not in df.columns:
            df = df.rename(columns={"CI_Lower": f"{prefix}_CI_Lower"})
        if "CI_Upper" in df.columns and f"{prefix}_CI_Upper" not in df.columns:
            df = df.rename(columns={"CI_Upper": f"{prefix}_CI_Upper"})
        if "Date" in df.columns and f"{prefix}_Date" not in df.columns:
            df = df.rename(columns={"Date": f"{prefix}_Date"})

    return df


def load_ycharts_features() -> pd.DataFrame:
    """Load base YCharts snapshot and join model forecast outputs."""
    base_path = "data/features_from_ycharts.csv"
    if not os.path.exists(base_path):
        raise FileNotFoundError(f"Missing required file: {base_path}")

    base = pd.read_csv(base_path)
    if "Ticker" not in base.columns:
        raise ValueError("features_from_ycharts.csv must include a 'Ticker' column")

    print(" YCharts features loaded:")
    print(base.head())

    df = base.copy()
    df["Ticker"] = (
        df["Ticker"]
        .astype(str)
        .str.replace("M:", "", regex=False)
        .str.upper()
        .str.strip()
    )
    df = df[~df["Ticker"].isin(["^MSACAS", "^MSEUR"])].copy()
    df = df.set_index("Ticker")

    # Fama-French
    try:
        ff = pd.read_csv("data/fama_french_forecasts.csv").set_index("Ticker")
        df = df.join(ff, how="left")
        print(" Joined Fama-French forecasts.")
    except Exception as e:
        print(" Failed to join fama_french_forecasts.csv:", e)

    # Institutional
    try:
        if os.path.exists("data/institutional_forecasts.csv"):
            inst = pd.read_csv("data/institutional_forecasts.csv").set_index("Ticker")
            df = df.join(inst, how="left")
        elif os.path.exists("data/institutional_features.parquet"):
            inst = pd.read_parquet("data/institutional_features.parquet").set_index("Ticker")
            # Prefer forecast-only join if present
            cols = [c for c in ["Institutional Forecast (%)", "Institutional_Forecast_%", "Institutional_Score"] if c in inst.columns]
            df = df.join(inst[cols], how="left")
        # Normalize column name
        if "Institutional_Forecast_%" in df.columns and "Institutional Forecast (%)" not in df.columns:
            df = df.rename(columns={"Institutional_Forecast_%": "Institutional Forecast (%)"})
        print(" Joined institutional forecasts.")
    except Exception as e:
        print(" Failed to join institutional forecasts:", e)

    # QuantConnect
    try:
        qf = pd.read_csv("data/quantconnect_forecasts.csv").set_index("Ticker")
        # keep forecast + any prefixed CI
        keep = [c for c in qf.columns if c.startswith("QuantConnect")]
        df = df.join(qf[keep], how="left")
        print(" Joined QuantConnect forecasts.")
    except Exception as e:
        print(" Failed to join quantconnect_forecasts.csv:", e)

    # Linear
    try:
        lin = _read_forecast_csv("data/linear_forecasts.csv", prefix="Linear")
        lin = lin.set_index("Ticker")
        keep = [c for c in lin.columns if c in ("Linear Model Forecast (%)", "Linear_CI_Lower", "Linear_CI_Upper", "Linear_Date")]
        df = df.join(lin[keep], how="left")
        print(" Joined Linear Model forecasts.")
    except Exception as e:
        print(" Failed to join linear_forecasts.csv:", e)

    # ML
    try:
        ml = _read_forecast_csv("data/ml_forecasts.csv", prefix="ML")
        ml = ml.set_index("Ticker")
        keep = [c for c in ml.columns if c in ("ML Forecast (%)", "ML_CI_Lower", "ML_CI_Upper", "ML_Date")]
        df = df.join(ml[keep], how="left")
        print(" Joined ML forecasts.")
    except Exception as e:
        print(" Failed to join ml_forecasts.csv:", e)


    # ARIMAX
    try:
        arx = _read_forecast_csv("data/arimax_forecasts.csv", prefix="ARIMAX")
        arx = arx.set_index("Ticker")
        keep = [c for c in arx.columns if c in ("ARIMAX Forecast (%)", "ARIMAX_CI_Lower", "ARIMAX_CI_Upper", "ARIMAX_Date", "Forecast_Return", "Model")]
        df = df.join(arx[keep], how="left")
        print(" Joined ARIMAX forecasts.")
    except Exception as e:
        print(" Failed to join arimax_forecasts.csv:", e)

    # Ranking / consensus summary
    try:
        summary = pd.read_csv("data/report_forecast_summary.csv").set_index("Ticker")
        keep = [c for c in summary.columns if c in (
            "Winning_Model", "Winning_Forecast", "Consensus_Forecast", "Confidence_Label",
            "Agreement_Ratio", "Forecast_StdDev", "Best_Model_Rank_Score"
        )]
        df = df.join(summary[keep], how="left")
        print(" Joined report forecast summary.")
    except Exception as e:
        print(" Failed to join report_forecast_summary.csv:", e)

    # Deep Learning
    try:
        dl = _read_forecast_csv("data/dl_forecasts.csv", prefix="DL")
        dl = dl.set_index("Ticker")
        keep = [c for c in dl.columns if c in ("DL Forecast (%)", "DL_CI_Lower", "DL_CI_Upper", "DL_Date")]
        df = df.join(dl[keep], how="left")
        print(" Joined Deep Learning forecasts.")
    except Exception as e:
        # Not fatal; model may not be trained yet
        print(" Failed to join dl_forecasts.csv:", e)

    return df.reset_index()


def _zscore(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    mu = s.mean(skipna=True)
    sd = s.std(skipna=True)
    if pd.isna(sd) or sd == 0:
        return pd.Series(np.nan, index=s.index)
    return (s - mu) / sd


def enrich_features_with_missing_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute additional features from yfinance history (best-effort).

    Adds/updates:
    - 1M Return
    - Volatility
    - MA200 Gap
    - Forward Return (realized last 21 trading days)
    - Alpha (vs SPY) and Beta
    - Momentum Z (12M return z-score across tickers)
    - 3Y Sharpe normalization
    """
    if df.empty:
        return df

    df = df.copy()
    df["Ticker"] = df["Ticker"].astype(str)

    # Normalize Sharpe naming
    if "Sharpe (3Y)" in df.columns and "3Y Sharpe" not in df.columns:
        df["3Y Sharpe"] = pd.to_numeric(df["Sharpe (3Y)"], errors="coerce")

    tickers = [t for t in df["Ticker"].dropna().unique().tolist() if t not in INDEXES]
    tickers_cleaned = [clean_ticker(t) for t in tickers]

    # Download ~2y to compute 12M momentum and regression stats
    print(" Downloading price data for enrichment...")
    prices = yf.download(
        tickers_cleaned + ["SPY"],
        period="2y",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )

    closes = _extract_closes(prices)

    if closes.empty:
        print(" Price enrichment skipped (no close data returned).")
        return df

    spy_ret = pd.Series(dtype=float)
    if "SPY" in closes.columns:
        spy_close = closes["SPY"].dropna()
        spy_ret = spy_close.pct_change().dropna()
    else:
        print(" SPY close series missing from yfinance download; Alpha/Beta will be NaN.")

    records = []
    mom_12m = {}

    for orig, raw in zip(tickers, tickers_cleaned):
        try:
            s = closes[raw].dropna()
            r = s.pct_change().dropna()

            onemonth = (s.iloc[-1] / s.iloc[-21]) - 1 if len(s) >= 21 else np.nan
            vol = r[-60:].std() if len(r) >= 60 else np.nan
            ma200 = s.rolling(200).mean().iloc[-1] if len(s) >= 200 else np.nan
            ma_gap = (s.iloc[-1] / ma200) - 1 if pd.notna(ma200) else np.nan
            # realized forward return from 21 trading days ago to today (label proxy)
            fwd_ret = (s.iloc[-1] / s.iloc[-21]) - 1 if len(s) >= 21 else np.nan

            # 12M momentum (252 trading days)
            mom_12m[orig] = (s.iloc[-1] / s.iloc[-253]) - 1 if len(s) >= 260 else np.nan

            # alpha/beta vs SPY on last 1y of daily returns (252)
            beta = np.nan
            alpha = np.nan
            if len(r) >= 120 and len(spy_ret) >= 120:
                aligned = pd.concat([r, spy_ret.reindex(r.index)], axis=1).dropna()
                aligned.columns = ["ret", "spy"]
                if len(aligned) >= 120:
                    X = aligned["spy"].values.reshape(-1, 1)
                    y = aligned["ret"].values
                    reg = LinearRegression().fit(X, y)
                    beta = float(reg.coef_[0])
                    alpha = float(reg.intercept_)

        except Exception as e:
            print(f" Enrichment error for {orig}: {e}")
            onemonth = vol = ma_gap = fwd_ret = alpha = beta = np.nan
            mom_12m[orig] = np.nan

        records.append(
            {
                "Ticker": orig,
                "1M Return": onemonth,
                "Volatility": vol,
                "MA200 Gap": ma_gap,
                "Forward Return": fwd_ret,
                "Alpha (vs SPY)": alpha,
                "Beta": beta,
            }
        )

    enrich_df = pd.DataFrame(records)
    df = df.merge(enrich_df, on="Ticker", how="left", suffixes=("", "_enrich"))

    # Momentum Z across tickers
    mom_s = pd.Series(mom_12m)
    mom_z = _zscore(mom_s)
    df["Momentum Z"] = df["Ticker"].map(mom_z)

    return df


def build_feature_table(df: pd.DataFrame) -> str:
    df = df.copy()
    if "Ticker" in df.columns:
        df["Ticker"] = (
            df["Ticker"]
            .astype(str)
            .str.replace("M:", "", regex=False)
            .str.upper()
            .str.strip()
        )

    df = df[~df["Ticker"].isin(MAG7 + INDEXES)].copy()

    portfolio_tickers = []
    if get_portfolio_tickers is not None:
        try:
            portfolio_tickers = list(get_portfolio_tickers())
        except Exception:
            portfolio_tickers = []

    if portfolio_tickers:
        df = df[df["Ticker"].isin(portfolio_tickers)].copy()
        df["Ticker"] = pd.Categorical(df["Ticker"], categories=portfolio_tickers, ordered=True)
        df = df.sort_values("Ticker")
        df["Ticker"] = df["Ticker"].astype(str)

    desired_cols = [c for c in EXPECTED_COLUMNS if c in df.columns]
    df = df[desired_cols]
    return df.to_html(index=False, justify="center", border=0, classes="dataframe", escape=False)


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    df0 = load_ycharts_features()
    df = enrich_features_with_missing_metrics(df0)

    # De-duplicate
    if "Date" in df.columns:
        df = df.drop_duplicates(subset=["Ticker", "Date"], keep="last")
    else:
        df = df.drop_duplicates(subset=["Ticker"], keep="last")

    df.to_parquet("data/features.parquet", index=False)
    df.to_csv("data/features.csv", index=False)
    print(" features.parquet updated.")
    print(df.head())

    # sanity wait
    for i in range(5):
        if os.path.exists("data/features.parquet"):
            break
        print(f" Waiting for features.parquet... ({i+1}/5)")
        time.sleep(1)
    else:
        raise FileNotFoundError(" features.parquet was not detected after writing.")
