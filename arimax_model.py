from __future__ import annotations

import os
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

from forecast_common import MAG7, load_panel_with_features

OUT_CSV = os.path.join("data", "arimax_forecasts.csv")
BACKTEST_CSV = os.path.join("data", "arimax_backtest_results.csv")

TARGET = "forward_return_21d"
EXOG = ["ret_21d", "vol_21d", "price_vs_ma50", "lag1", "lag5", "lag21"]

warnings.filterwarnings("ignore")


def _fit(y: pd.Series, X: pd.DataFrame):
    model = SARIMAX(
        endog=y.reset_index(drop=True).astype(float),
        exog=X.reset_index(drop=True).astype(float),
        order=(1, 0, 0),
        trend="n",
        enforce_stationarity=False,
        enforce_invertibility=False,
    )
    return model.fit(disp=False, maxiter=12, method="lbfgs")


def _one_step_forecast(train: pd.DataFrame, test_row: pd.DataFrame, features: list[str]) -> tuple[float, float]:
    train = train.dropna(subset=features + [TARGET]).tail(120).copy()
    test_row = test_row.dropna(subset=features).copy()
    if train.empty or test_row.empty:
        return np.nan, np.nan
    try:
        res = _fit(train[TARGET], train[features])
        pred = float(res.forecast(steps=1, exog=test_row[features])[0])
        resid_std = float(np.nanstd(res.resid)) if len(res.resid) else 0.06
    except Exception:
        pred = float(train[TARGET].tail(21).mean())
        resid_std = float(train[TARGET].tail(63).std()) if len(train) else 0.06
    return pred, resid_std


def main() -> None:
    df = load_panel_with_features(MAG7)
    features = [c for c in EXOG if c in df.columns]
    current_rows = []
    backtest_rows = []

    for ticker in MAG7:
        sub_all = df[df["Ticker"] == ticker].sort_values("Date").copy()

        train_cur = sub_all.dropna(subset=features + [TARGET]).copy()
        live_cur = sub_all.dropna(subset=features).copy()

        if len(train_cur) < 100 or live_cur.empty:
            continue

        test_cur = live_cur.iloc[-1:][["Date", "Ticker"] + features].copy()
        pred, resid_std = _one_step_forecast(train_cur, test_cur, features)
        if pd.notna(pred):
            z = 1.96
            current_rows.append({
                "Ticker": ticker,
                "Date": pd.to_datetime(test_cur["Date"].iloc[0]).date().isoformat(),
                "ARIMAX Forecast (%)": pred * 100.0,
                "ARIMAX_CI_Lower": (pred - z * resid_std) * 100.0,
                "ARIMAX_CI_Upper": (pred + z * resid_std) * 100.0,
                "Model": "ARIMAX",
                "Forecast_Return": pred,
            })

        # Minimal walk-forward benchmark: evaluate one matured point ~21 trading days back
        sub_bt = sub_all.dropna(subset=features + [TARGET]).copy()
        if len(sub_bt) < 100:
            continue

        test_idx = max(80, len(sub_bt) - 22)
        train_bt = sub_bt.iloc[:test_idx].copy()
        test_bt = sub_bt.iloc[test_idx:test_idx + 1][["Date", "Ticker"] + features + [TARGET]].copy()

        bt_pred, _ = _one_step_forecast(train_bt, test_bt, features)
        if pd.notna(bt_pred) and not test_bt.empty:
            actual = float(test_bt[TARGET].iloc[0])
            err = float(bt_pred - actual)
            backtest_rows.append({
                "Date": pd.to_datetime(test_bt["Date"].iloc[0]).date().isoformat(),
                "Ticker": ticker,
                "Model": "ARIMAX",
                "Predicted_Return": bt_pred,
                "Actual_Return": actual,
                "Error": err,
                "Absolute_Error": abs(err),
                "Squared_Error": err ** 2,
                "Direction_Correct": int(np.sign(bt_pred) == np.sign(actual)),
            })

    current = pd.DataFrame(current_rows)
    backtest = pd.DataFrame(backtest_rows)
    os.makedirs("data", exist_ok=True)
    current.to_csv(OUT_CSV, index=False)
    backtest.to_csv(BACKTEST_CSV, index=False)
    print(f" ARIMAX forecasts saved -> {OUT_CSV}")
    print(f" ARIMAX backtest saved -> {BACKTEST_CSV} ({len(backtest)} rows)")
    if not current.empty:
        print(current[["Ticker", "ARIMAX Forecast (%)"]])


if __name__ == "__main__":
    main()
