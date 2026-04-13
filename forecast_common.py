from __future__ import annotations

import os
from typing import Iterable, List

import numpy as np
import pandas as pd

MAG7 = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]

PANEL_PATHS = [
    os.path.join("data", "training_panel.parquet"),
    os.path.join("data", "training_panel.csv"),
]


def _read_panel(panel_path: str | None = None) -> pd.DataFrame:
    """Load a training panel. If panel_path is given, use it directly; otherwise
    fall back to the default PANEL_PATHS search order."""
    if panel_path is not None:
        p = str(panel_path)
        if not os.path.exists(p):
            raise FileNotFoundError(f"Specified panel not found: {p}")
        df = pd.read_parquet(p) if p.endswith(".parquet") else pd.read_csv(p)
    else:
        for path in PANEL_PATHS:
            if os.path.exists(path):
                df = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)
                break
        else:
            raise FileNotFoundError("Missing training panel (expected data/training_panel.parquet or .csv)")

    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
    df = df.dropna(subset=["Date", "Ticker"]).sort_values(["Ticker", "Date"]).reset_index(drop=True)
    return df


def _add_target_and_lags(df: pd.DataFrame, horizon: int = 21) -> pd.DataFrame:
    df = df.copy()
    g = df.groupby("Ticker", group_keys=False)

    if "Target_Forward_21D" in df.columns:
        df["forward_return_21d"] = pd.to_numeric(df["Target_Forward_21D"], errors="coerce")
    else:
        close = pd.to_numeric(df["Close"], errors="coerce")
        df["forward_return_21d"] = g["Close"].shift(-horizon) / close - 1.0

    df["lag1"] = g["forward_return_21d"].shift(1)
    df["lag5"] = g["forward_return_21d"].shift(5)
    df["lag21"] = g["forward_return_21d"].shift(21)
    return df


def _add_alias_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    alias_map = {
        "Ret_1D": "ret_1d",
        "Ret_5D": "ret_5d",
        "Ret_21D": "ret_21d",
        "Ret_63D": "ret_63d",
        "Ret_252D": "ret_252d",
        "Vol_21D": "vol_21d",
        "Vol_63D": "vol_63d",
        "Gap_MA20": "price_vs_ma20",
        "Gap_MA50": "price_vs_ma50",
        "Gap_MA200": "price_vs_ma200",
        "RSI_14": "rsi_14",
    }
    for src, dst in alias_map.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = pd.to_numeric(df[src], errors="coerce")

    if "MA_20" in df.columns and "MA_50" in df.columns and "ma20_vs_ma50" not in df.columns:
        df["ma20_vs_ma50"] = pd.to_numeric(df["MA_20"], errors="coerce") / pd.to_numeric(df["MA_50"], errors="coerce") - 1.0
    if "MA_50" in df.columns and "MA_200" in df.columns and "ma50_vs_ma200" not in df.columns:
        df["ma50_vs_ma200"] = pd.to_numeric(df["MA_50"], errors="coerce") / pd.to_numeric(df["MA_200"], errors="coerce") - 1.0
    if "Volume" in df.columns and "log_volume" not in df.columns:
        df["log_volume"] = np.log1p(pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0))

    return df


def _join_static_ticker_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    y_path = os.path.join("data", "features_from_ycharts.csv")
    if os.path.exists(y_path):
        y = pd.read_csv(y_path)
        y["Ticker"] = y["Ticker"].astype(str).str.replace("M:", "", regex=False).str.upper().str.strip()
        cols = {
            "Alpha (3Y)": "alpha_3y",
            "Beta (3Y)": "beta_3y",
            "Sharpe (3Y)": "sharpe_3y",
            "Max Drawdown 3Y": "max_drawdown_3y",
            "Up/Down Ratio": "up_down_ratio",
            "ROE": "roe",
            "P/E Ratio": "pe_ratio",
            "Standard Deviation 3Y": "stddev_3y",
        }
        keep = ["Ticker"] + [c for c in cols if c in y.columns]
        y = y[keep].rename(columns=cols).drop_duplicates(subset=["Ticker"])
        df = df.merge(y, on="Ticker", how="left")

    inst_path = os.path.join("data", "institutional_features.parquet")
    if os.path.exists(inst_path):
        inst = pd.read_parquet(inst_path)
        inst["Ticker"] = inst["Ticker"].astype(str).str.upper().str.strip()
        inst_cols = [c for c in inst.columns if c.startswith("Z_") or c == "Institutional_Score"]
        inst_last = inst.groupby("Ticker", as_index=False)[inst_cols].last()
        inst_last = inst_last.rename(columns={
            "Institutional_Score": "composite_score",
            "Z_12M_Momentum": "momentum_z",
            "Z_ROE": "quality_z",
            "Z_EarningsPrice": "value_z",
        })
        df = df.merge(inst_last, on="Ticker", how="left")

    qc_path = os.path.join("data", "quantconnect_features.parquet")
    if os.path.exists(qc_path):
        qc = pd.read_parquet(qc_path)
        if "Ticker" not in qc.columns and qc.index.name == "Ticker":
            qc = qc.reset_index()
        qc["Ticker"] = qc["Ticker"].astype(str).str.upper().str.strip()
        rename_map = {
            "Quant Score": "quant_score",
            "1M Return": "qc_ret_1m",
            "3M Return": "qc_ret_3m",
            "12M Return": "qc_ret_12m",
            "Volatility": "qc_volatility",
            "MA200 Gap": "qc_ma200_gap",
        }
        keep = ["Ticker"] + [c for c in rename_map if c in qc.columns]
        qc = qc[keep].rename(columns=rename_map).drop_duplicates(subset=["Ticker"])
        df = df.merge(qc, on="Ticker", how="left")

    for col in [
        "sentiment_1d",
        "sentiment_3d",
        "headline_count",
        "sentiment_trend",
        "positive_headline_ratio",
        "negative_headline_ratio",
    ]:
        if col not in df.columns:
            df[col] = np.nan

    return df


def load_panel_with_features(
    tickers: Iterable[str] | None = None,
    panel_path: str | None = None,
) -> pd.DataFrame:
    df = _read_panel(panel_path=panel_path)
    if tickers is not None:
        tickers = [str(t).upper().strip() for t in tickers]
        df = df[df["Ticker"].isin(tickers)].copy()
    df = _add_target_and_lags(df)
    df = _add_alias_features(df)
    df = _join_static_ticker_features(df)
    return df.sort_values(["Ticker", "Date"]).reset_index(drop=True)


def summarize_backtest(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Ticker", "Model", "RMSE", "MAE", "Directional_Accuracy", "Correlation", "Observations"])

    rows = []
    for (ticker, model), g in df.groupby(["Ticker", "Model"], dropna=False):
        err = pd.to_numeric(g["Error"], errors="coerce")
        abs_err = pd.to_numeric(g["Absolute_Error"], errors="coerce")
        pred = pd.to_numeric(g["Predicted_Return"], errors="coerce")
        actual = pd.to_numeric(g["Actual_Return"], errors="coerce")
        corr = pred.corr(actual)
        rows.append({
            "Ticker": ticker,
            "Model": model,
            "RMSE": float(np.sqrt(np.nanmean(err ** 2))) if len(err) else np.nan,
            "MAE": float(np.nanmean(abs_err)) if len(abs_err) else np.nan,
            "Directional_Accuracy": float(np.nanmean(np.sign(pred) == np.sign(actual))) if len(pred) else np.nan,
            "Correlation": float(corr) if pd.notna(corr) else np.nan,
            "Observations": int(len(g)),
        })
    return pd.DataFrame(rows)
