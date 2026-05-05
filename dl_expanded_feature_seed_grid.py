"""Run repeated-seed DL checks for the expanded directional feature panel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

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
from dl_directional_loss_experiment import _parse_features, _train_variant

DEFAULT_PANEL = Path("data/experiment/directional_feature_panel_fmp.parquet")
DEFAULT_OUTPUT = Path("data/experiment/expanded_feature_seed_grid.json")
DEFAULT_CSV = Path("data/experiment/expanded_feature_seed_grid.csv")
DEFAULT_EXTRA_FEATURES = (
    "atr_percentile,gap_5d_count,earnings_surprise_last,days_since_earnings,"
    "earnings_surprise_x_gap_count,post_earnings_negative_drift_window"
)


def _parse_seeds(raw: str) -> List[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _prediction_stats(result: dict, panel_path: Path, test_days: int) -> dict:
    panel = _ensure_panel_schema(read_panel(panel_path))
    panel = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    dates = pd.to_datetime(panel["Date"]).drop_duplicates().sort_values()
    if len(dates) < test_days + 10:
        test_days = max(5, int(len(dates) * 0.2))
    cutoff = dates.iloc[-test_days]
    test_panel = panel[panel["Date"] >= cutoff]

    model, scaler, feature_cols, seq_len = load_model_and_scaler(
        Path(result["model_path"]),
        Path(result["scaler_path"]),
        "cpu",
    )
    ds = PanelSequenceDataset(test_panel, scaler, feature_cols, seq_len)
    loader = DataLoader(ds, batch_size=1024, shuffle=False)

    preds = []
    actuals = []
    with torch.no_grad():
        for xb, yb, _, _ in loader:
            mu, _ = model(xb)
            preds.append(mu.cpu().numpy().ravel())
            actuals.append(yb.cpu().numpy().ravel())

    p = np.concatenate(preds)
    y = np.concatenate(actuals)
    return {
        "pct_bullish_pred": float(np.mean(p > 0)),
        "pct_bullish_actual": float(np.mean(y > 0)),
        "pred_mean": float(np.mean(p)),
        "pred_std": float(np.std(p)),
        "actual_mean": float(np.mean(y)),
        "actual_std": float(np.std(y)),
    }


def _aggregate(rows: list[dict]) -> dict:
    metrics = [
        "MAE",
        "RMSE",
        "Directional_Accuracy",
        "Correlation",
        "IC_Spearman",
        "pct_bullish_pred",
    ]
    out = {}
    df = pd.DataFrame(rows)
    for metric in metrics:
        vals = pd.to_numeric(df[metric], errors="coerce").dropna()
        out[metric] = {
            "mean": float(vals.mean()) if not vals.empty else float("nan"),
            "std": float(vals.std(ddof=0)) if len(vals) > 1 else 0.0,
            "min": float(vals.min()) if not vals.empty else float("nan"),
            "max": float(vals.max()) if not vals.empty else float("nan"),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--extra-features", default=DEFAULT_EXTRA_FEATURES)
    ap.add_argument("--seeds", default="20260505,20260506,20260507,20260508,20260509")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--val-days", type=int, default=252)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--selection-metric", choices=["loss", "directional", "composite"], default="loss")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--csv-output", type=Path, default=DEFAULT_CSV)
    args = ap.parse_args()

    extra_features = _parse_features(args.extra_features)
    rows = []
    raw_results = []

    for seed in _parse_seeds(args.seeds):
        print(f"\n=== expanded-feature seed={seed} ===")
        result = _train_variant(
            weight=0.0,
            temperature=0.02,
            neutral_threshold=0.0,
            epochs=int(args.epochs),
            batch_size=int(args.batch_size),
            val_days=int(args.val_days),
            lr=float(args.lr),
            warm_start=False,
            seed=seed,
            selection_metric=args.selection_metric,
            panel_path=args.panel,
            extra_features=extra_features,
        )
        pred_stats = _prediction_stats(result, args.panel, int(args.val_days))
        metrics = result["metrics"]
        row = {
            "seed": seed,
            "variant": result["variant"],
            "selection_metric": args.selection_metric,
            "MAE": metrics.get("MAE"),
            "RMSE": metrics.get("RMSE"),
            "Directional_Accuracy": metrics.get("Directional_Accuracy"),
            "Correlation": metrics.get("Correlation"),
            "IC_Spearman": metrics.get("IC_Spearman"),
            **pred_stats,
        }
        rows.append(row)
        raw_results.append(result)
        print(
            f"seed={seed} MAE={row['MAE']:.6f} RMSE={row['RMSE']:.6f} "
            f"Dir={row['Directional_Accuracy']:.4f} IC={row['IC_Spearman']:.4f} "
            f"Bullish={row['pct_bullish_pred']:.4f}"
        )

    aggregate = _aggregate(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.csv_output, index=False)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "panel_path": str(args.panel),
                "extra_features": extra_features,
                "epochs": int(args.epochs),
                "batch_size": int(args.batch_size),
                "val_days": int(args.val_days),
                "lr": float(args.lr),
                "selection_metric": args.selection_metric,
                "rows": rows,
                "aggregate": aggregate,
                "raw_results": raw_results,
            },
            f,
            indent=2,
        )

    print(f"\nSaved seed grid -> {args.output}")
    print(pd.DataFrame(aggregate).T)


if __name__ == "__main__":
    main()
