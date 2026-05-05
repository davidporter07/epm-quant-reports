"""Evaluate validation-fitted sign thresholds for expanded-feature DL models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from deep_learning_model import (
    PanelSequenceDataset,
    TARGET_COL,
    _ensure_panel_schema,
    load_model_and_scaler,
    read_panel,
)

DEFAULT_GRID = Path("data/experiment/expanded_feature_seed_grid.json")
DEFAULT_OUTPUT = Path("data/experiment/sign_calibration_eval.json")
DEFAULT_CSV = Path("data/experiment/sign_calibration_eval.csv")


def _load_predictions(raw: dict, panel: pd.DataFrame, test_days: int) -> pd.DataFrame:
    dates = pd.to_datetime(panel["Date"]).drop_duplicates().sort_values()
    if len(dates) < test_days + 10:
        test_days = max(5, int(len(dates) * 0.2))
    cutoff = dates.iloc[-test_days]
    test_panel = panel[panel["Date"] >= cutoff]

    model, scaler, feature_cols, seq_len = load_model_and_scaler(
        Path(raw["model_path"]),
        Path(raw["scaler_path"]),
        "cpu",
    )
    ds = PanelSequenceDataset(test_panel, scaler, feature_cols, seq_len)
    loader = DataLoader(ds, batch_size=1024, shuffle=False)

    rows = []
    with torch.no_grad():
        for xb, yb, tickers, dates_ns in loader:
            mu, _ = model(xb)
            pred = mu.cpu().numpy().ravel()
            actual = yb.cpu().numpy().ravel()
            for ticker, date_ns, p, y in zip(tickers, dates_ns.numpy().ravel(), pred, actual):
                rows.append(
                    {
                        "Date": pd.Timestamp(int(date_ns)),
                        "Ticker": str(ticker),
                        "pred": float(p),
                        "actual": float(y),
                    }
                )
    return pd.DataFrame(rows).sort_values(["Date", "Ticker"]).reset_index(drop=True)


def _metrics(df: pd.DataFrame, threshold: float) -> dict:
    pred = df["pred"].to_numpy(dtype=float)
    actual = df["actual"].to_numpy(dtype=float)
    signal = np.where(pred > threshold, 1.0, -1.0)
    actual_sign = np.where(actual > 0, 1.0, -1.0)
    return {
        "threshold": float(threshold),
        "directional_accuracy": float(np.mean(signal == actual_sign)),
        "pct_bullish_signal": float(np.mean(signal > 0)),
        "mae": float(np.mean(np.abs(actual - pred))),
        "rmse": float(np.sqrt(np.mean((actual - pred) ** 2))),
        "correlation": (
            float(np.corrcoef(pred, actual)[0, 1])
            if len(pred) > 2 and np.std(pred) > 1e-12 and np.std(actual) > 1e-12
            else float("nan")
        ),
        "ic_spearman": float(pd.Series(pred).rank().corr(pd.Series(actual).rank())) if len(pred) > 2 else float("nan"),
        "n": int(len(df)),
    }


def _candidate_thresholds(pred: np.ndarray) -> np.ndarray:
    quantiles = np.linspace(0.05, 0.95, 181)
    vals = np.quantile(pred, quantiles)
    return np.unique(np.concatenate(([0.0], vals)))


def _fit_threshold(calib: pd.DataFrame, method: str, bullish_min: float, bullish_max: float) -> float:
    pred = calib["pred"].to_numpy(dtype=float)
    actual = calib["actual"].to_numpy(dtype=float)
    actual_bullish = float(np.mean(actual > 0))

    if method == "zero":
        return 0.0
    if method == "match_actual_bullish":
        return float(np.quantile(pred, max(0.0, min(1.0, 1.0 - actual_bullish))))
    if method == "median":
        return float(np.median(pred))

    best = None
    for threshold in _candidate_thresholds(pred):
        m = _metrics(calib, float(threshold))
        if method == "max_direction_bounded" and not (bullish_min <= m["pct_bullish_signal"] <= bullish_max):
            continue
        if method == "max_balanced_score":
            balance_penalty = abs(m["pct_bullish_signal"] - actual_bullish)
            score = m["directional_accuracy"] - 0.5 * balance_penalty
        else:
            score = m["directional_accuracy"]
        if best is None or score > best[0]:
            best = (score, float(threshold))

    return 0.0 if best is None else best[1]


def _split_calib_eval(preds: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.to_datetime(preds["Date"]).drop_duplicates().sort_values()
    split = dates.iloc[len(dates) // 2]
    calib = preds[preds["Date"] <= split].copy()
    eval_df = preds[preds["Date"] > split].copy()
    return calib, eval_df


def _ensemble_predictions(pred_frames: list[pd.DataFrame]) -> pd.DataFrame:
    base_cols = ["Date", "Ticker", "actual"]
    merged = pred_frames[0][base_cols + ["pred"]].rename(columns={"pred": "pred_0"})
    for idx, frame in enumerate(pred_frames[1:], start=1):
        merged = merged.merge(
            frame[base_cols + ["pred"]].rename(columns={"pred": f"pred_{idx}"}),
            on=base_cols,
            how="inner",
        )
    pred_cols = [col for col in merged.columns if col.startswith("pred_")]
    merged["pred"] = merged[pred_cols].mean(axis=1)
    return merged[base_cols + ["pred"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--csv-output", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--methods", default="zero,match_actual_bullish,median,max_direction_bounded,max_balanced_score")
    ap.add_argument("--bullish-min", type=float, default=0.35)
    ap.add_argument("--bullish-max", type=float, default=0.75)
    ap.add_argument("--ensemble-top-k", default="2,3,5")
    args = ap.parse_args()

    grid = json.loads(args.grid.read_text(encoding="utf-8"))
    panel = _ensure_panel_schema(read_panel(Path(grid["panel_path"])))
    panel = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    raw_by_variant = {item["variant"]: item for item in grid["raw_results"]}
    methods = [part.strip() for part in args.methods.split(",") if part.strip()]

    rows = []
    pred_frames: dict[str, pd.DataFrame] = {}
    sorted_seed_rows = sorted(grid["rows"], key=lambda row: float(row["Directional_Accuracy"]), reverse=True)

    for row in grid["rows"]:
        variant = row["variant"]
        preds = _load_predictions(raw_by_variant[variant], panel, int(grid["val_days"]))
        pred_frames[variant] = preds
        calib, eval_df = _split_calib_eval(preds)
        for method in methods:
            threshold = _fit_threshold(calib, method, args.bullish_min, args.bullish_max)
            train_m = _metrics(calib, threshold)
            eval_m = _metrics(eval_df, threshold)
            rows.append(
                {
                    "scope": "seed",
                    "name": variant,
                    "method": method,
                    "threshold": threshold,
                    "calib_directional_accuracy": train_m["directional_accuracy"],
                    "calib_pct_bullish_signal": train_m["pct_bullish_signal"],
                    "eval_directional_accuracy": eval_m["directional_accuracy"],
                    "eval_pct_bullish_signal": eval_m["pct_bullish_signal"],
                    "eval_mae": eval_m["mae"],
                    "eval_rmse": eval_m["rmse"],
                    "eval_correlation": eval_m["correlation"],
                    "eval_ic_spearman": eval_m["ic_spearman"],
                    "eval_n": eval_m["n"],
                }
            )

    for k in [int(part.strip()) for part in args.ensemble_top_k.split(",") if part.strip()]:
        selected = sorted_seed_rows[:k]
        name = f"top_{k}_by_direction"
        preds = _ensemble_predictions([pred_frames[row["variant"]] for row in selected])
        calib, eval_df = _split_calib_eval(preds)
        for method in methods:
            threshold = _fit_threshold(calib, method, args.bullish_min, args.bullish_max)
            train_m = _metrics(calib, threshold)
            eval_m = _metrics(eval_df, threshold)
            rows.append(
                {
                    "scope": "ensemble",
                    "name": name,
                    "method": method,
                    "threshold": threshold,
                    "calib_directional_accuracy": train_m["directional_accuracy"],
                    "calib_pct_bullish_signal": train_m["pct_bullish_signal"],
                    "eval_directional_accuracy": eval_m["directional_accuracy"],
                    "eval_pct_bullish_signal": eval_m["pct_bullish_signal"],
                    "eval_mae": eval_m["mae"],
                    "eval_rmse": eval_m["rmse"],
                    "eval_correlation": eval_m["correlation"],
                    "eval_ic_spearman": eval_m["ic_spearman"],
                    "eval_n": eval_m["n"],
                }
            )

    out_df = pd.DataFrame(rows).sort_values(
        ["eval_directional_accuracy", "eval_ic_spearman", "eval_mae"],
        ascending=[False, False, True],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.csv_output, index=False)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "grid": str(args.grid),
                "methods": methods,
                "bullish_bounds": [args.bullish_min, args.bullish_max],
                "rows": rows,
            },
            f,
            indent=2,
        )

    print(out_df.head(15).to_string(index=False))
    print(f"\nSaved calibration eval -> {args.output}")


if __name__ == "__main__":
    main()
