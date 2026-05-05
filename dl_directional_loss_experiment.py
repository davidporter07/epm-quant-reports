"""Historical experiment for DL directional loss weights.

Runs isolated warm-start variants from the current production checkpoint.
Production model/scaler files are never modified.

Usage:
    python dl_directional_loss_experiment.py --weights 0,0.05,0.1,0.15,0.2
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import torch

SEED = 20260505

PANEL_PATH = Path("data/training_panel.parquet")
PROD_MODEL = Path("models/dl_tcn.pt")
PROD_SCALER = Path("models/dl_scaler.json")
EXPERIMENT_DIR = Path("models/experiment")
OUT_PATH = Path("data/experiment/directional_loss_comparison.json")


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _variant_name(weight: float) -> str:
    return f"direction_w{str(weight).replace('.', 'p')}"


def _parse_features(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _select_feature_cols(panel_path: Path, extra_features: List[str]) -> List[str]:
    from deep_learning_model import FEATURE_COLS_DEFAULT, read_panel

    feature_cols = list(FEATURE_COLS_DEFAULT)
    if not extra_features:
        return feature_cols

    panel_cols = set(read_panel(panel_path).columns)
    missing = [col for col in extra_features if col not in panel_cols]
    if missing:
        raise ValueError(f"Extra features missing from {panel_path}: {missing}")

    for col in extra_features:
        if col not in feature_cols:
            feature_cols.append(col)
    return feature_cols


def _load_metrics(csv_path: Path) -> Dict[str, float]:
    df = pd.read_csv(csv_path)
    out: Dict[str, float] = {}
    for _, row in df.iterrows():
        try:
            out[str(row["Metric"])] = float(row["Value"])
        except Exception:
            continue
    return out


def _train_variant(
    weight: float,
    temperature: float,
    neutral_threshold: float,
    epochs: int,
    batch_size: int,
    val_days: int,
    lr: float,
    warm_start: bool,
    seed: int,
    selection_metric: str,
    panel_path: Path,
    extra_features: List[str],
) -> dict:
    sys.path.insert(0, str(Path(__file__).parent))
    from deep_learning_model import TrainConfig, train_model, backtest

    name = _variant_name(weight)
    if weight > 0:
        name = (
            f"{name}_temp{str(temperature).replace('.', 'p')}"
            f"_thr{str(neutral_threshold).replace('.', 'p')}"
        )
    if extra_features:
        name = f"{name}_extra{len(extra_features)}"
    if not warm_start:
        name = f"{name}_scratch"
    if seed != SEED:
        name = f"{name}_seed{seed}"
    if selection_metric != "loss":
        name = f"{name}_select_{selection_metric}"
    model_path = EXPERIMENT_DIR / f"dl_{name}.pt"
    scaler_path = EXPERIMENT_DIR / f"dl_{name}_scaler.json"
    metrics_path = OUT_PATH.parent / f"{name}_backtest.csv"

    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if warm_start and (not PROD_MODEL.exists() or not PROD_SCALER.exists()):
        raise FileNotFoundError("Missing production DL model/scaler.")

    if warm_start:
        shutil.copy2(PROD_MODEL, model_path)

    cfg = TrainConfig(
        seq_len=60,
        batch_size=batch_size,
        epochs=epochs,
        lr=lr,
        hidden=64,
        dropout=0.10,
        val_days=val_days,
        patience=max(2, min(epochs, 3)),
    )

    feature_cols = _select_feature_cols(panel_path, extra_features)
    _set_seed(seed)
    train_model(
        panel_path=panel_path,
        model_path=model_path,
        scaler_path=scaler_path,
        feature_cols=feature_cols,
        cfg=cfg,
        device="cpu",
        warm_start=warm_start,
        direction_weight=weight,
        direction_temperature=temperature,
        direction_neutral_threshold=neutral_threshold,
        selection_metric=selection_metric,
    )
    backtest(
        panel_path=panel_path,
        model_path=model_path,
        scaler_path=scaler_path,
        test_days=val_days,
        device="cpu",
        out_csv=metrics_path,
    )

    metrics = _load_metrics(metrics_path)
    return {
        "variant": name,
        "direction_weight": weight,
        "direction_temperature": temperature,
        "direction_neutral_threshold": neutral_threshold,
        "lr": lr,
        "warm_start": warm_start,
        "seed": seed,
        "selection_metric": selection_metric,
        "panel_path": str(panel_path),
        "extra_features": extra_features,
        "feature_count": len(feature_cols),
        "model_path": str(model_path),
        "scaler_path": str(scaler_path),
        "metrics_path": str(metrics_path),
        "metrics": metrics,
    }


def _parse_weights(raw: str) -> List[float]:
    weights = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        weights.append(float(part))
    return weights


def _parse_thresholds(raw: str) -> List[float]:
    vals = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            vals.append(float(part))
    return vals


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=str, default="0,0.05,0.1,0.15,0.2")
    ap.add_argument("--temperature", type=float, default=0.02)
    ap.add_argument(
        "--thresholds",
        type=str,
        default="0",
        help="Comma-separated neutral thresholds, e.g. 0,0.005,0.01 for 0%%, 0.5%%, 1%%.",
    )
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--val-days", type=int, default=252)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--from-scratch", action="store_true")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--selection-metric", choices=["loss", "directional", "composite"], default="loss")
    ap.add_argument("--panel", type=Path, default=PANEL_PATH)
    ap.add_argument(
        "--extra-features",
        type=str,
        default="",
        help="Comma-separated research feature columns to append to the approved DL features.",
    )
    args = ap.parse_args()

    extra_features = _parse_features(args.extra_features)
    results = []
    for weight in _parse_weights(args.weights):
        thresholds = [0.0] if weight <= 0 else _parse_thresholds(args.thresholds)
        for threshold in thresholds:
            print(f"\n=== Directional loss experiment: weight={weight} threshold={threshold} ===")
            result = _train_variant(
                weight=weight,
                temperature=float(args.temperature),
                neutral_threshold=threshold,
                epochs=int(args.epochs),
                batch_size=int(args.batch_size),
                val_days=int(args.val_days),
                lr=float(args.lr),
                warm_start=not bool(args.from_scratch),
                seed=int(args.seed),
                selection_metric=args.selection_metric,
                panel_path=args.panel,
                extra_features=extra_features,
            )
            metrics = result["metrics"]
            print(
                f"weight={weight} threshold={threshold} "
                f"MAE={metrics.get('MAE', float('nan')):.6f} "
                f"RMSE={metrics.get('RMSE', float('nan')):.6f} "
                f"Dir={metrics.get('Directional_Accuracy', float('nan')):.4f} "
                f"IC={metrics.get('IC_Spearman', float('nan')):.4f}"
            )
            results.append(result)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "seed": int(args.seed),
                "epochs": int(args.epochs),
                "batch_size": int(args.batch_size),
                "val_days": int(args.val_days),
                "lr": float(args.lr),
                "warm_start": not bool(args.from_scratch),
                "selection_metric": args.selection_metric,
                "thresholds": _parse_thresholds(args.thresholds),
                "panel_path": str(args.panel),
                "extra_features": extra_features,
                "results": results,
            },
            f,
            indent=2,
        )
    print(f"\nSaved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
