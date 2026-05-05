"""Evaluate simple seed ensembles from an expanded-feature DL seed grid."""

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
DEFAULT_OUTPUT = Path("data/experiment/expanded_feature_ensemble_eval.json")


def _predict(model_path: Path, scaler_path: Path, panel: pd.DataFrame, test_days: int) -> tuple[np.ndarray, np.ndarray]:
    dates = pd.to_datetime(panel["Date"]).drop_duplicates().sort_values()
    if len(dates) < test_days + 10:
        test_days = max(5, int(len(dates) * 0.2))
    cutoff = dates.iloc[-test_days]
    test_panel = panel[panel["Date"] >= cutoff]

    model, scaler, feature_cols, seq_len = load_model_and_scaler(model_path, scaler_path, "cpu")
    ds = PanelSequenceDataset(test_panel, scaler, feature_cols, seq_len)
    loader = DataLoader(ds, batch_size=1024, shuffle=False)

    preds = []
    actuals = []
    with torch.no_grad():
        for xb, yb, _, _ in loader:
            mu, _ = model(xb)
            preds.append(mu.cpu().numpy().ravel())
            actuals.append(yb.cpu().numpy().ravel())
    return np.concatenate(preds), np.concatenate(actuals)


def _metrics(pred: np.ndarray, actual: np.ndarray) -> dict:
    return {
        "MAE": float(np.mean(np.abs(actual - pred))),
        "RMSE": float(np.sqrt(np.mean((actual - pred) ** 2))),
        "Directional_Accuracy": float(np.mean(np.sign(actual) == np.sign(pred))),
        "Correlation": (
            float(np.corrcoef(pred, actual)[0, 1])
            if len(pred) > 2 and np.std(pred) > 1e-12 and np.std(actual) > 1e-12
            else float("nan")
        ),
        "IC_Spearman": float(pd.Series(pred).rank().corr(pd.Series(actual).rank())) if len(pred) > 2 else float("nan"),
        "pct_bullish_pred": float(np.mean(pred > 0)),
        "pct_bullish_actual": float(np.mean(actual > 0)),
        "pred_mean": float(np.mean(pred)),
        "pred_std": float(np.std(pred)),
        "N": int(len(actual)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--sort-by", choices=["Directional_Accuracy", "MAE", "IC_Spearman"], default="Directional_Accuracy")
    ap.add_argument("--top-k", default="2,3,5")
    args = ap.parse_args()

    grid = json.loads(args.grid.read_text(encoding="utf-8"))
    rows = list(grid["rows"])
    raw_by_variant = {item["variant"]: item for item in grid["raw_results"]}
    panel_path = Path(grid["panel_path"])
    panel = _ensure_panel_schema(read_panel(panel_path))
    panel = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()

    reverse = args.sort_by != "MAE"
    rows = sorted(rows, key=lambda row: float(row[args.sort_by]), reverse=reverse)
    predictions = {}
    actual = None
    results = []

    for k in [int(part.strip()) for part in args.top_k.split(",") if part.strip()]:
        selected = rows[:k]
        pred_list = []
        for row in selected:
            variant = row["variant"]
            if variant not in predictions:
                raw = raw_by_variant[variant]
                pred, y = _predict(
                    Path(raw["model_path"]),
                    Path(raw["scaler_path"]),
                    panel,
                    int(grid["val_days"]),
                )
                predictions[variant] = pred
                actual = y
            pred_list.append(predictions[variant])

        ensemble_pred = np.mean(np.vstack(pred_list), axis=0)
        result = {
            "name": f"top_{k}_by_{args.sort_by}",
            "k": k,
            "sort_by": args.sort_by,
            "variants": [row["variant"] for row in selected],
            **_metrics(ensemble_pred, actual),
        }
        results.append(result)
        print(
            f"{result['name']}: MAE={result['MAE']:.6f} RMSE={result['RMSE']:.6f} "
            f"Dir={result['Directional_Accuracy']:.4f} IC={result['IC_Spearman']:.4f} "
            f"Bullish={result['pct_bullish_pred']:.4f}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "grid": str(args.grid),
                "panel_path": str(panel_path),
                "sort_by": args.sort_by,
                "results": results,
            },
            f,
            indent=2,
        )
    print(f"Saved ensemble eval -> {args.output}")


if __name__ == "__main__":
    main()
