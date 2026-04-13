from __future__ import annotations

import json
import os
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_squared_error

from forecast_common import MAG7, load_panel_with_features, summarize_backtest

OUT_CSV = os.path.join("data", "ml_forecasts.csv")
BACKTEST_CSV = os.path.join("data", "ml_backtest_results.csv")
FEATURE_IMPORTANCE_CSV = os.path.join("data", "ml_feature_importance.csv")
PERF_SUMMARY_CSV = os.path.join("data", "ml_performance_summary.csv")
CONFIDENCE_CSV = os.path.join("data", "ml_confidence.csv")
MODEL_PATH = os.path.join("models", "ml_panel.pkl")
META_PATH = os.path.join("models", "ml_panel_meta.json")

TARGET = "forward_return_21d"
FEATURES = [
    "ret_5d", "ret_21d", "ret_63d", "ret_252d",
    "price_vs_ma20", "price_vs_ma50", "price_vs_ma200",
    "ma20_vs_ma50", "ma50_vs_ma200",
    "vol_21d", "vol_63d",
    "lag1", "lag5", "lag21",
    "alpha_3y", "beta_3y", "sharpe_3y", "max_drawdown_3y",
    "momentum_z", "value_z", "quality_z", "composite_score", "quant_score",
    "sentiment_3d",
]


def _valid_feature_list(df: pd.DataFrame) -> list[str]:
    feats = []
    for c in FEATURES:
        if c in df.columns and pd.to_numeric(df[c], errors="coerce").notna().sum() > 100:
            feats.append(c)
    return feats


def _candidates() -> dict[str, object]:
    return {
        "GradientBoosting": GradientBoostingRegressor(
            n_estimators=30,
            learning_rate=0.05,
            max_depth=3,
            random_state=42,
        )
    }


def _pick_best_model(df: pd.DataFrame, features: list[str]):
    dates = np.array(sorted(df["Date"].dropna().unique()))
    cutoff = dates[-252] if len(dates) > 252 else dates[max(1, len(dates)//5)]
    train = df[df["Date"] < cutoff].dropna(subset=features + [TARGET]).copy()
    val = df[df["Date"] >= cutoff].dropna(subset=features + [TARGET]).copy()
    X_train = train[features].astype(float)
    y_train = train[TARGET].astype(float)
    X_val = val[features].astype(float)
    y_val = val[TARGET].astype(float)

    best_name, best_model, best_rmse = None, None, np.inf
    for name, model in _candidates().items():
        model.fit(X_train, y_train)
        pred = model.predict(X_val)
        rmse = float(np.sqrt(mean_squared_error(y_val, pred)))
        if rmse < best_rmse:
            best_name, best_model, best_rmse = name, model, rmse
    return best_name, best_model, best_rmse


def _build_backtest(df: pd.DataFrame, features: list[str], model_name: str) -> pd.DataFrame:
    dates = np.array(sorted(df["Date"].dropna().unique()))
    eval_dates = list(dates[882::252])[-3:]
    rows = []
    for eval_date in eval_dates:
        train = df[df["Date"] < eval_date].dropna(subset=features + [TARGET]).copy()
        test = df[(df["Date"] == eval_date) & (df["Ticker"].isin(MAG7))].dropna(subset=features + [TARGET]).copy()
        if train.empty or test.empty:
            continue
        model = _candidates()[model_name]
        model.fit(train[features].astype(float), train[TARGET].astype(float))
        preds = model.predict(test[features].astype(float))
        for row, pred in zip(test.itertuples(index=False), preds):
            actual = float(getattr(row, TARGET))
            error = float(pred - actual)
            rows.append({
                "Date": pd.to_datetime(row.Date).date().isoformat(),
                "Ticker": row.Ticker,
                "Model": "ML",
                "Predicted_Return": float(pred),
                "Actual_Return": actual,
                "Error": error,
                "Absolute_Error": abs(error),
                "Squared_Error": error ** 2,
                "Direction_Correct": int(np.sign(pred) == np.sign(actual)),
            })
    return pd.DataFrame(rows)


def _feature_importance_df(model, features: list[str]) -> pd.DataFrame:
    vals = model.feature_importances_ if hasattr(model, "feature_importances_") else np.full(len(features), np.nan)
    out = pd.DataFrame({"Feature": features, "Importance": vals})
    out = out.sort_values("Importance", ascending=False)
    out["Ticker"] = "ALL"
    out["Date"] = datetime.today().date().isoformat()
    return out[["Ticker", "Feature", "Importance", "Date"]]


def _confidence(backtest: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    recent_mae = backtest.groupby("Ticker")["Absolute_Error"].mean().to_dict() if not backtest.empty else {}
    rows = []
    for row in current.itertuples(index=False):
        mae = recent_mae.get(row.Ticker, np.nan)
        if pd.isna(mae):
            label = "Medium"
        elif mae < 0.05:
            label = "High"
        elif mae < 0.10:
            label = "Medium"
        else:
            label = "Low"
        rows.append({
            "Date": row.Date,
            "Ticker": row.Ticker,
            "Predicted_Return": row.Forecast_Return,
            "Recent_MAE": mae,
            "Confidence_Label": label,
            "Model": "ML",
        })
    return pd.DataFrame(rows)


def main() -> None:
    panel = load_panel_with_features(MAG7)
    features = _valid_feature_list(panel)

    train_df = panel.dropna(subset=features + [TARGET]).copy()

    model_name, model, val_rmse = _pick_best_model(train_df, features)
    model.fit(train_df[features].astype(float), train_df[TARGET].astype(float))

    latest_rows = []
    for ticker in MAG7:
        sub_live = panel[panel["Ticker"] == ticker].sort_values("Date").dropna(subset=features).copy()
        if not sub_live.empty:
            latest_rows.append(sub_live.iloc[-1])

    latest = pd.DataFrame(latest_rows)
    preds = model.predict(latest[features].astype(float)) if not latest.empty else np.array([])

    backtest = _build_backtest(train_df, features, model_name)

    z = 1.96
    current = pd.DataFrame({
        "Ticker": latest["Ticker"].values,
        "Date": pd.to_datetime(latest["Date"]).dt.date.astype(str).values,
        "ML Forecast (%)": preds * 100.0,
        "ML_CI_Lower": (preds - z * val_rmse) * 100.0,
        "ML_CI_Upper": (preds + z * val_rmse) * 100.0,
        "Forecast_Return": preds,
        "Model": "ML",
        "Selected_Algorithm": model_name,
    })

    perf = summarize_backtest(backtest)
    perf["Model"] = "ML"
    perf["Selected_Algorithm"] = model_name
    fi = _feature_importance_df(model, features)
    conf = _confidence(backtest, current)

    os.makedirs("models", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    current.to_csv(OUT_CSV, index=False)
    backtest.to_csv(BACKTEST_CSV, index=False)
    fi.to_csv(FEATURE_IMPORTANCE_CSV, index=False)
    perf.to_csv(PERF_SUMMARY_CSV, index=False)
    conf.to_csv(CONFIDENCE_CSV, index=False)

    meta = {
        "trained_through": str(pd.to_datetime(train_df["Date"]).max().date()),
        "features": features,
        "selected_algorithm": model_name,
        "validation_rmse": val_rmse,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "rows": int(len(train_df)),
        "backtest_rows": int(len(backtest)),
    }
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f" ML forecasts saved -> {OUT_CSV}")
    print(f" ML backtest saved -> {BACKTEST_CSV} ({len(backtest)} rows)")
    print(f" ML feature importance saved -> {FEATURE_IMPORTANCE_CSV}")
    print(f" Selected algorithm: {model_name} | validation RMSE={val_rmse:.4f}")
    print(current[["Ticker", "ML Forecast (%)", "Selected_Algorithm"]])

if __name__ == "__main__":
    main()
