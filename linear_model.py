from __future__ import annotations

import json
import os
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from forecast_common import MAG7, load_panel_with_features

OUT_CSV = os.path.join("data", "linear_forecasts.csv")
BACKTEST_CSV = os.path.join("data", "linear_backtest_results.csv")
MODEL_PATH = os.path.join("models", "linear_panel.pkl")
META_PATH = os.path.join("models", "linear_panel_meta.json")

TARGET = "forward_return_21d"
FEATURES = [
    "ret_5d", "ret_21d", "ret_63d", "ret_252d",
    "vol_21d", "vol_63d",
    "price_vs_ma20", "price_vs_ma50", "price_vs_ma200",
    "ma20_vs_ma50", "ma50_vs_ma200",
    "rsi_14", "log_volume",
    "lag1", "lag5", "lag21",
    "alpha_3y", "beta_3y", "sharpe_3y", "max_drawdown_3y", "up_down_ratio",
    "momentum_z", "composite_score", "quant_score",
]


def _valid_feature_list(df: pd.DataFrame) -> list[str]:
    feats = []
    for c in FEATURES:
        if c in df.columns and pd.to_numeric(df[c], errors="coerce").notna().sum() > 100:
            feats.append(c)
    return feats


def _fit_model(train_df: pd.DataFrame, features: list[str]):
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=1.0)),
    ])
    train_df = train_df.dropna(subset=features + [TARGET]).copy()
    X = train_df[features].astype(float)
    y = train_df[TARGET].astype(float)
    model.fit(X, y)
    return model


def run_backtest(df: pd.DataFrame, features: list[str], start_obs: int = 504, step: int = 21) -> pd.DataFrame:
    unique_dates = np.array(sorted(df["Date"].dropna().unique()))
    if len(unique_dates) <= start_obs + 1:
        start_obs = max(126, len(unique_dates) // 2)
    eval_dates = unique_dates[start_obs::step]

    rows = []
    for eval_date in eval_dates:
        train_df = df[df["Date"] < eval_date]
        test_df = df[(df["Date"] == eval_date) & (df["Ticker"].isin(MAG7))].copy()
        train_df = train_df.dropna(subset=features + [TARGET])
        test_df = test_df.dropna(subset=features + [TARGET])
        if train_df.empty or test_df.empty:
            continue
        model = _fit_model(train_df, features)
        preds = model.predict(test_df[features].astype(float))
        for row, pred in zip(test_df.itertuples(index=False), preds):
            actual = float(getattr(row, TARGET))
            error = float(pred - actual)
            rows.append({
                "Date": pd.to_datetime(row.Date).date().isoformat(),
                "Ticker": row.Ticker,
                "Model": "Linear",
                "Predicted_Return": float(pred),
                "Actual_Return": actual,
                "Error": error,
                "Absolute_Error": abs(error),
                "Squared_Error": error ** 2,
                "Direction_Correct": int(np.sign(pred) == np.sign(actual)),
            })
    return pd.DataFrame(rows)


def train_latest_and_forecast(df: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, dict]:
    train_df = df[df["Ticker"].notna()].copy()
    train_df = train_df.dropna(subset=features + [TARGET])
    model = _fit_model(train_df, features)

    os.makedirs("models", exist_ok=True)
    joblib.dump(model, MODEL_PATH)

    backtest = run_backtest(df, features)
    rmse = float(np.sqrt(np.nanmean(backtest["Squared_Error"]))) if not backtest.empty else float("nan")

    latest_rows = []
    for ticker in MAG7:
        sub = df[df["Ticker"] == ticker].sort_values("Date")
        sub = sub.dropna(subset=features)
        if sub.empty:
            continue
        latest_rows.append(sub.iloc[-1])
    latest = pd.DataFrame(latest_rows)
    preds = model.predict(latest[features].astype(float)) if not latest.empty else np.array([])

    z = 1.96
    ci = rmse if np.isfinite(rmse) and rmse > 0 else np.nanstd(preds) if len(preds) else 0.05
    lower = preds - z * ci
    upper = preds + z * ci

    out = pd.DataFrame({
        "Ticker": latest["Ticker"].values,
        "Date": pd.to_datetime(latest["Date"]).dt.date.astype(str).values,
        "Linear Model Forecast (%)": preds * 100.0,
        "Linear_CI_Lower": lower * 100.0,
        "Linear_CI_Upper": upper * 100.0,
        "Model": "Linear",
        "Forecast_Return": preds,
    })

    meta = {
        "trained_through": str(pd.to_datetime(df["Date"]).max().date()),
        "features": features,
        "rmse": rmse,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "observations": int(len(train_df)),
        "backtest_rows": int(len(backtest)),
    }
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return out, meta, backtest


def main() -> None:
    df = load_panel_with_features(MAG7)
    features = _valid_feature_list(df)
    out, meta, backtest = train_latest_and_forecast(df, features)

    os.makedirs("data", exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    backtest.to_csv(BACKTEST_CSV, index=False)

    print(f" Linear forecasts saved -> {OUT_CSV}")
    print(f" Linear backtest saved -> {BACKTEST_CSV} ({len(backtest)} rows)")
    print(f" Linear RMSE: {meta['rmse']:.4f}")
    print(out[["Ticker", "Linear Model Forecast (%)"]])


if __name__ == "__main__":
    main()
