"""Evaluate rolling, past-window sign calibration for expanded DL models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from deep_learning_model import TARGET_COL, _ensure_panel_schema, read_panel
from dl_sign_calibration_eval import (
    _ensemble_predictions,
    _fit_threshold,
    _load_predictions,
    _metrics,
)

DEFAULT_GRID = Path("data/experiment/expanded_feature_seed_grid.json")
DEFAULT_OUTPUT = Path("data/experiment/rolling_sign_calibration_eval.json")
DEFAULT_CSV = Path("data/experiment/rolling_sign_calibration_eval.csv")


def _rolling_eval(
    preds: pd.DataFrame,
    method: str,
    lookback_days: int,
    label_lag_days: int,
    bullish_min: float,
    bullish_max: float,
) -> dict:
    dates = pd.to_datetime(preds["Date"]).drop_duplicates().sort_values().to_list()
    rows = []
    thresholds = []

    for idx, date in enumerate(dates):
        cal_end_idx = idx - int(label_lag_days)
        cal_start_idx = cal_end_idx - int(lookback_days)
        if cal_start_idx < 0 or cal_end_idx <= cal_start_idx:
            continue

        cal_dates = dates[cal_start_idx:cal_end_idx]
        calib = preds[preds["Date"].isin(cal_dates)]
        today = preds[preds["Date"] == date]
        if calib.empty or today.empty:
            continue

        threshold = _fit_threshold(calib, method, bullish_min, bullish_max)
        thresholds.append(threshold)
        rows.append(today.assign(threshold=threshold))

    if not rows:
        return {
            "threshold_mean": float("nan"),
            "threshold_std": float("nan"),
            **_metrics(preds.iloc[0:0], 0.0),
        }

    eval_df = pd.concat(rows, ignore_index=True)
    pred = eval_df["pred"].to_numpy(dtype=float)
    actual = eval_df["actual"].to_numpy(dtype=float)
    threshold = eval_df["threshold"].to_numpy(dtype=float)
    signal = np.where(pred > threshold, 1.0, -1.0)
    actual_sign = np.where(actual > 0, 1.0, -1.0)

    return {
        "threshold_mean": float(np.mean(thresholds)),
        "threshold_std": float(np.std(thresholds)),
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
        "n": int(len(eval_df)),
        "dates_evaluated": int(eval_df["Date"].nunique()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--csv-output", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--methods", default="match_actual_bullish,median,max_direction_bounded,max_balanced_score")
    ap.add_argument("--lookbacks", default="42,63,84")
    ap.add_argument("--label-lag-days", type=int, default=21)
    ap.add_argument("--bullish-min", type=float, default=0.35)
    ap.add_argument("--bullish-max", type=float, default=0.75)
    ap.add_argument("--ensemble-top-k", default="2,3,5")
    args = ap.parse_args()

    grid = json.loads(args.grid.read_text(encoding="utf-8"))
    panel = _ensure_panel_schema(read_panel(Path(grid["panel_path"])))
    panel = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    raw_by_variant = {item["variant"]: item for item in grid["raw_results"]}
    methods = [part.strip() for part in args.methods.split(",") if part.strip()]
    lookbacks = [int(part.strip()) for part in args.lookbacks.split(",") if part.strip()]

    pred_frames = {}
    for row in grid["rows"]:
        variant = row["variant"]
        pred_frames[variant] = _load_predictions(raw_by_variant[variant], panel, int(grid["val_days"]))

    sorted_seed_rows = sorted(grid["rows"], key=lambda row: float(row["Directional_Accuracy"]), reverse=True)
    candidates = [("seed", row["variant"], pred_frames[row["variant"]]) for row in grid["rows"]]
    for k in [int(part.strip()) for part in args.ensemble_top_k.split(",") if part.strip()]:
        selected = sorted_seed_rows[:k]
        candidates.append(
            (
                "ensemble",
                f"top_{k}_by_direction",
                _ensemble_predictions([pred_frames[row["variant"]] for row in selected]),
            )
        )

    rows = []
    for scope, name, preds in candidates:
        for lookback in lookbacks:
            for method in methods:
                metrics = _rolling_eval(
                    preds,
                    method,
                    lookback,
                    int(args.label_lag_days),
                    float(args.bullish_min),
                    float(args.bullish_max),
                )
                rows.append(
                    {
                        "scope": scope,
                        "name": name,
                        "method": method,
                        "lookback_days": lookback,
                        "label_lag_days": int(args.label_lag_days),
                        **metrics,
                    }
                )

    out_df = pd.DataFrame(rows).sort_values(
        ["directional_accuracy", "ic_spearman", "pct_bullish_signal"],
        ascending=[False, False, True],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.csv_output, index=False)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump({"grid": str(args.grid), "rows": rows}, f, indent=2)

    print(out_df.head(20).to_string(index=False))
    print(f"\nSaved rolling calibration eval -> {args.output}")


if __name__ == "__main__":
    main()
