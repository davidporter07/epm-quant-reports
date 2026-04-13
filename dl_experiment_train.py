"""dl_experiment_train.py
Bounded DL validation experiment: 11-feature baseline vs 10-feature (minus RSI_14).

Trains ONE variant, saves to models/experiment/. Never touches production files.

Usage:
    python dl_experiment_train.py --variant 11feat
    python dl_experiment_train.py --variant 10feat_no_rsi

Both variants use identical hyperparameters, identical data split, and train from
scratch (no warm-start from production checkpoint) for a clean comparison.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

import numpy as np
import torch

# Reproducible seed  same for both variants so only the feature set differs
SEED = 20260401


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


FEATURES_11 = [
    "Ret_1D", "Ret_5D", "Ret_21D", "Ret_63D", "Ret_252D",
    "Vol_21D", "Vol_63D", "Gap_MA20", "Gap_MA50", "Gap_MA200", "RSI_14",
]

FEATURES_10_NO_RSI    = [f for f in FEATURES_11 if f != "RSI_14"]
FEATURES_12_LOG_VOL   = FEATURES_11 + ["log_volume"]

VARIANTS = {
    "11feat":            {"features": FEATURES_11,          "label": "11-feature baseline (full)"},
    "10feat_no_rsi":     {"features": FEATURES_10_NO_RSI,   "label": "10-feature (RSI_14 removed)"},
    "12feat_log_volume": {"features": FEATURES_12_LOG_VOL,  "label": "12-feature (+ log_volume)"},
}

EXPERIMENT_DIR = Path("models/experiment")
PANEL_PATH     = Path("data/training_panel.parquet")
# log_volume must be pre-computed; use enriched panel for any variant that needs it
PANEL_PATH_LOG_VOL = Path("data/experiment/training_panel_with_log_volume.parquet")

VARIANTS_PANEL = {
    "12feat_log_volume": PANEL_PATH_LOG_VOL,
}

# Match production hyperparameters exactly
EPOCHS     = 10
SEQ_LEN    = 60
HIDDEN     = 64
DROPOUT    = 0.10
BATCH_SIZE = 512
VAL_DAYS   = 252
PATIENCE   = 3
LR         = 1e-3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=list(VARIANTS.keys()),
                    help="Which variant to train")
    args = ap.parse_args()

    variant   = args.variant
    cfg_info  = VARIANTS[variant]
    features  = cfg_info["features"]
    label     = cfg_info["label"]

    model_path  = EXPERIMENT_DIR / f"dl_{variant}.pt"
    scaler_path = EXPERIMENT_DIR / f"dl_{variant}_scaler.json"

    print(f"\n{'='*60}")
    print(f"DL Experiment  Training: {label}")
    print(f"  Features ({len(features)}): {features}")
    print(f"  Model path : {model_path}")
    print(f"  Scaler path: {scaler_path}")
    print(f"  Seed       : {SEED}")
    print(f"{'='*60}\n")

    _set_seed(SEED)

    # Import after seed is set
    sys.path.insert(0, str(Path(__file__).parent))
    from deep_learning_model import TrainConfig, train_model

    cfg = TrainConfig(
        seq_len=SEQ_LEN,
        batch_size=BATCH_SIZE,
        epochs=EPOCHS,
        lr=LR,
        hidden=HIDDEN,
        dropout=DROPOUT,
        val_days=VAL_DAYS,
        patience=PATIENCE,
    )

    panel_to_use = VARIANTS_PANEL.get(variant, PANEL_PATH)

    train_model(
        panel_path=panel_to_use,
        model_path=model_path,
        scaler_path=scaler_path,
        feature_cols=features,
        cfg=cfg,
        device="cpu",
        warm_start=False,  # MUST be False  no contamination from production weights
    )

    print(f"\nDone: {label}")
    print(f"  Saved: {model_path}")
    print(f"  Saved: {scaler_path}")


if __name__ == "__main__":
    main()
