"""dl_warmstart_train.py
Bounded DL warm-start validation: production checkpoint -> fine-tune variants.

Protocol
--------
1. Copies production checkpoint (models/dl_tcn.pt) into models/experiment/
   as the starting point for each variant.
2. Calls train_model(warm_start=True) which:
   - Loads the copied checkpoint with strict=False.
   - For 11-feat control: all layers load perfectly (identical architecture).
   - For 12-feat variant: TCN backbone + head load; feature_gate + in_proj
     (the only n_features-dependent layers) train from scratch.
   - LR is automatically reduced to 20% of base (warm-start fine-tune).
3. Trains for WARMSTART_EPOCHS (5)  shorter than from-scratch (10) to
   stay close to the production checkpoint.
4. Saves to models/experiment/dl_{variant}.pt. Never touches production.

Usage:
    python dl_warmstart_train.py --variant 11feat_ws
    python dl_warmstart_train.py --variant 12feat_log_volume_ws
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

import numpy as np
import torch

SEED = 20260401

PRODUCTION_CHECKPOINT = Path("models/dl_tcn.pt")
PRODUCTION_SCALER     = Path("models/dl_scaler.json")

EXPERIMENT_DIR        = Path("models/experiment")
PANEL_PATH            = Path("data/training_panel.parquet")
PANEL_PATH_LOG_VOL    = Path("data/experiment/training_panel_with_log_volume.parquet")

FEATURES_11 = [
    "Ret_1D", "Ret_5D", "Ret_21D", "Ret_63D", "Ret_252D",
    "Vol_21D", "Vol_63D", "Gap_MA20", "Gap_MA50", "Gap_MA200", "RSI_14",
]
FEATURES_12_LOG_VOL    = FEATURES_11 + ["log_volume"]
FEATURES_10_NO_RSI     = [f for f in FEATURES_11 if f != "RSI_14"]
FEATURES_11_CLEAN_LOGVOL = FEATURES_10_NO_RSI + ["log_volume"]   # 10-feat + log_volume, no RSI_14

VARIANTS = {
    "11feat_ws": {
        "features": FEATURES_11,
        "label":    "11-feat warm-start (production baseline)",
        "panel":    PANEL_PATH,
    },
    "12feat_log_volume_ws": {
        "features": FEATURES_12_LOG_VOL,
        "label":    "12-feat warm-start (+log_volume)",
        "panel":    PANEL_PATH_LOG_VOL,
    },
    # Experiment 4  combined clean-baseline variants
    "10feat_no_rsi_ws": {
        "features": FEATURES_10_NO_RSI,
        "label":    "10-feat warm-start (no RSI_14  clean baseline)",
        "panel":    PANEL_PATH,
    },
    "11feat_clean_logvol_ws": {
        "features":          FEATURES_11_CLEAN_LOGVOL,
        "label":             "11-feat warm-start (no RSI_14 + log_volume)",
        "panel":             PANEL_PATH_LOG_VOL,
        # Force re-init of feature_gate and in_proj even though n_features==11.
        # This variant substitutes log_volume for RSI_14 at the same slot.
        # Transferring RSI_14's input weights into log_volume's position
        # creates a contaminated warm-start; only the invariant backbone should
        # be inherited.
        "force_reinit_keys": {"feature_gate.log_weights", "in_proj.weight", "in_proj.bias"},
    },
}

# Shorter than from-scratch (10)  we're fine-tuning, not re-learning
WARMSTART_EPOCHS = 5
SEQ_LEN          = 60
HIDDEN           = 64
DROPOUT          = 0.10
BATCH_SIZE       = 512
VAL_DAYS         = 252
PATIENCE         = 3
LR               = 1e-3   # actual LR used = LR * 0.2 by warm_start logic


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=list(VARIANTS.keys()))
    args = ap.parse_args()

    variant  = args.variant
    cfg_info = VARIANTS[variant]
    features = cfg_info["features"]
    label    = cfg_info["label"]
    panel    = cfg_info["panel"]

    dest_model_path  = EXPERIMENT_DIR / f"dl_{variant}.pt"
    dest_scaler_path = EXPERIMENT_DIR / f"dl_{variant}_scaler.json"

    print(f"\n{'='*64}")
    print(f"DL Warm-start Experiment: {label}")
    print(f"  Features ({len(features)}): {features}")
    print(f"  Panel           : {panel}")
    print(f"  Source ckpt     : {PRODUCTION_CHECKPOINT}")
    print(f"  Dest model      : {dest_model_path}")
    print(f"  Epochs          : {WARMSTART_EPOCHS} (LR ~{LR*0.2:.5f})")
    print(f"  Seed            : {SEED}")
    print(f"{'='*64}\n")

    if not PRODUCTION_CHECKPOINT.exists():
        print(f"ERROR: production checkpoint not found: {PRODUCTION_CHECKPOINT}")
        sys.exit(1)

    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)

    _set_seed(SEED)

    sys.path.insert(0, str(Path(__file__).parent))
    from deep_learning_model import TrainConfig, train_model, TCNForecaster

    # ------------------------------------------------------------------ #
    # Partial weight transfer for warm-start                               #
    # PyTorch strict=False handles MISSING keys but NOT shape mismatches.  #
    # For the 12-feat variant, feature_gate and in_proj have different     #
    # shapes  we manually copy only the layers that match, then save the  #
    # partially-initialized model as the starting checkpoint.              #
    # ------------------------------------------------------------------ #
    print(f"Building partial warm-start checkpoint from {PRODUCTION_CHECKPOINT} ...")
    prod_ckpt = torch.load(PRODUCTION_CHECKPOINT, map_location="cpu", weights_only=True)
    prod_state = prod_ckpt["state_dict"]

    # Build target model so we have the correct architecture
    target_model = TCNForecaster(n_features=len(features), hidden=HIDDEN, dropout=DROPOUT)
    target_state  = target_model.state_dict()

    force_reinit = cfg_info.get("force_reinit_keys", set())
    transferred, skipped = [], []
    for key, param in prod_state.items():
        if key in force_reinit:
            skipped.append(f"{key} (forced reinit  feature substitution)")
        elif key in target_state and target_state[key].shape == param.shape:
            target_state[key] = param.clone()
            transferred.append(key)
        else:
            skipped.append(key)

    target_model.load_state_dict(target_state)

    print(f"  Transferred {len(transferred)} layer(s): {transferred}")
    if skipped:
        print(f"  Skipped (shape mismatch, will train from scratch): {skipped}")

    # Save the partially-initialized model as the experiment starting point.
    # train_model(warm_start=True) will find this file and load it  since all
    # shapes now match (we pre-loaded what could match), it will load cleanly
    # and use LR*0.2 for fine-tuning.
    partial_ckpt = {k: v for k, v in prod_ckpt.items() if k != "state_dict"}
    partial_ckpt["state_dict"] = target_model.state_dict()
    torch.save(partial_ckpt, dest_model_path)
    print(f"  Saved partial warm-start checkpoint -> {dest_model_path}\n")

    cfg = TrainConfig(
        seq_len=SEQ_LEN,
        batch_size=BATCH_SIZE,
        epochs=WARMSTART_EPOCHS,
        lr=LR,
        hidden=HIDDEN,
        dropout=DROPOUT,
        val_days=VAL_DAYS,
        patience=PATIENCE,
    )

    train_model(
        panel_path=panel,
        model_path=dest_model_path,
        scaler_path=dest_scaler_path,
        feature_cols=features,
        cfg=cfg,
        device="cpu",
        warm_start=True,   # loads dest_model_path with strict=False, LR*0.2
    )

    print(f"\nDone: {label}")
    print(f"  Saved: {dest_model_path}")
    print(f"  Saved: {dest_scaler_path}")


if __name__ == "__main__":
    main()
