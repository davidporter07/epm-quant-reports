"""Dual-head DL experiment.

This script tests whether a separate direction classifier head improves
historical directional accuracy while leaving production DL files untouched.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent))

from deep_learning_model import (  # noqa: E402
    FEATURE_COLS_DEFAULT,
    MODEL_PATH_DEFAULT,
    PANEL_PATH_DEFAULT,
    SCALER_PATH_DEFAULT,
    PanelSequenceDataset,
    TCNForecaster,
    TCNBlock,
    TemporalAttentionPool,
    apply_scaler,
    fit_scaler,
    gaussian_nll,
    read_panel,
    _ensure_panel_schema,
    TARGET_COL,
)

SEED = 20260505
EXPERIMENT_DIR = Path("models/experiment")
OUT_PATH = Path("data/experiment/dual_head_comparison.json")


class DualHeadTCN(nn.Module):
    def __init__(self, n_features: int, hidden: int = 64, dropout: float = 0.10):
        super().__init__()
        self.n_features = int(n_features)
        self.hidden = int(hidden)
        self.dropout = float(dropout)

        # Same backbone names as production TCN for partial checkpoint transfer.
        self.feature_gate = TCNForecaster(n_features, hidden, dropout).feature_gate
        self.in_proj = nn.Conv1d(self.n_features, self.hidden, kernel_size=1)
        self.blocks = nn.Sequential(
            TCNBlock(self.hidden, self.hidden, kernel_size=3, dilation=1, dropout=self.dropout),
            TCNBlock(self.hidden, self.hidden, kernel_size=3, dilation=2, dropout=self.dropout),
            TCNBlock(self.hidden, self.hidden, kernel_size=3, dilation=4, dropout=self.dropout),
            TCNBlock(self.hidden, self.hidden, kernel_size=3, dilation=8, dropout=self.dropout),
        )
        self.temporal_pool = TemporalAttentionPool(self.hidden)
        self.norm = nn.LayerNorm(self.hidden)
        self.return_head = nn.Sequential(
            nn.Linear(self.hidden, self.hidden),
            nn.GELU(),
            nn.Dropout(self.dropout),
            nn.Linear(self.hidden, 2),
        )
        self.direction_head = nn.Sequential(
            nn.Linear(self.hidden, self.hidden // 2),
            nn.GELU(),
            nn.Dropout(self.dropout),
            nn.Linear(self.hidden // 2, 1),
        )

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        x = x.transpose(1, 2)
        x = self.feature_gate(x)
        h = self.in_proj(x)
        h = self.blocks(h)
        h = self.temporal_pool(h)
        h = self.norm(h)
        out = self.return_head(h)
        mu = out[:, 0:1]
        log_sigma = out[:, 1:2].clamp(-6.0, 3.0)
        direction_logit = self.direction_head(h)
        return mu, log_sigma, direction_logit


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _time_split(panel: pd.DataFrame, val_days: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    dates = pd.to_datetime(panel["Date"]).drop_duplicates().sort_values()
    split_idx = max(0, len(dates) - int(val_days))
    return dates.iloc[split_idx], dates.iloc[-1]


def _parse_features(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _select_feature_cols(panel_path: Path, extra_features: List[str]) -> List[str]:
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


def _load_labeled_panel(panel_path: Path) -> pd.DataFrame:
    panel = _ensure_panel_schema(read_panel(panel_path))
    return panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()


def _transfer_checkpoint(model: DualHeadTCN) -> None:
    ckpt = torch.load(MODEL_PATH_DEFAULT, map_location="cpu", weights_only=True)
    prod = ckpt["state_dict"]
    target = model.state_dict()
    transferred = []
    for key, val in prod.items():
        target_key = key
        if key.startswith("head."):
            target_key = "return_head." + key[len("head.") :]
        if target_key in target and target[target_key].shape == val.shape:
            target[target_key] = val.clone()
            transferred.append(target_key)
    model.load_state_dict(target)
    print(f"Transferred {len(transferred)} tensors from production checkpoint.")


def _direction_loss(
    logit: torch.Tensor,
    y: torch.Tensor,
    threshold: float,
    pos_weight: torch.Tensor | None = None,
) -> torch.Tensor:
    mask = torch.abs(y) >= float(threshold)
    if not torch.any(mask):
        return logit.sum() * 0.0
    target = (y[mask] > 0).to(dtype=logit.dtype)
    return nn.functional.binary_cross_entropy_with_logits(logit[mask], target, pos_weight=pos_weight)


def _evaluate(model: DualHeadTCN, loader: DataLoader, device: str) -> Dict[str, float]:
    model.eval()
    preds, actuals, logits = [], [], []
    with torch.no_grad():
        for xb, yb, _, _ in loader:
            xb = xb.to(device)
            mu, _, direction_logit = model(xb)
            preds.append(mu.cpu().numpy().ravel())
            logits.append(direction_logit.cpu().numpy().ravel())
            actuals.append(yb.numpy().ravel())
    p = np.concatenate(preds)
    y = np.concatenate(actuals)
    l = np.concatenate(logits)
    dir_pred = np.where(l >= 0, 1.0, -1.0)
    return {
        "mae": float(np.mean(np.abs(y - p))),
        "rmse": float(np.sqrt(np.mean((y - p) ** 2))),
        "return_directional_accuracy": float(np.mean(np.sign(y) == np.sign(p))),
        "head_directional_accuracy": float(np.mean(np.sign(y) == dir_pred)),
        "correlation": float(np.corrcoef(p, y)[0, 1]) if len(p) > 2 else float("nan"),
        "ic_spearman": float(pd.Series(p).rank().corr(pd.Series(y).rank())) if len(p) > 2 else float("nan"),
        "direction_prob_mean": float(np.mean(1.0 / (1.0 + np.exp(-l)))),
        "pct_bullish_head": float(np.mean(l >= 0)),
        "n": int(len(y)),
    }


def _train_one(
    direction_weight: float,
    threshold: float,
    epochs: int,
    batch_size: int,
    val_days: int,
    balanced: bool,
    panel_path: Path,
    extra_features: List[str],
) -> dict:
    _set_seed(SEED)
    panel = _load_labeled_panel(panel_path)
    feature_cols = _select_feature_cols(panel_path, extra_features)
    cutoff, _ = _time_split(panel, val_days)
    train_panel = panel[panel["Date"] < cutoff]
    val_panel = panel[panel["Date"] >= cutoff]

    scaler = fit_scaler(train_panel, feature_cols)
    train_ds = PanelSequenceDataset(train_panel, scaler, feature_cols, 60)
    val_ds = PanelSequenceDataset(val_panel, scaler, feature_cols, 60)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=1024, shuffle=False)

    model = DualHeadTCN(len(feature_cols)).to("cpu")
    _transfer_checkpoint(model)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-4)

    pos_weight = None
    if balanced:
        y_train = pd.to_numeric(train_panel[TARGET_COL], errors="coerce").dropna()
        if threshold > 0:
            y_train = y_train[y_train.abs() >= threshold]
        pos = float((y_train > 0).sum())
        neg = float((y_train < 0).sum())
        if pos > 0 and neg > 0:
            pos_weight = torch.tensor([neg / pos], dtype=torch.float32)
            print(f"balanced BCE pos_weight={float(pos_weight.item()):.4f} (pos={pos:.0f}, neg={neg:.0f})")

    best = {"loss": float("inf"), "state": None}
    for epoch in range(1, epochs + 1):
        model.train()
        losses = []
        for xb, yb, _, _ in train_loader:
            opt.zero_grad(set_to_none=True)
            mu, log_sigma, direction_logit = model(xb)
            loss = gaussian_nll(mu, log_sigma, yb)
            loss = loss + float(direction_weight) * _direction_loss(direction_logit, yb, threshold, pos_weight)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            losses.append(float(loss.item()))

        model.eval()
        val_losses = []
        with torch.no_grad():
            for xb, yb, _, _ in val_loader:
                mu, log_sigma, direction_logit = model(xb)
                loss = gaussian_nll(mu, log_sigma, yb)
                loss = loss + float(direction_weight) * _direction_loss(direction_logit, yb, threshold, pos_weight)
                val_losses.append(float(loss.item()))
        val_loss = float(np.mean(val_losses))
        print(f"epoch={epoch} train={np.mean(losses):.6f} val={val_loss:.6f}")
        if val_loss < best["loss"]:
            best = {"loss": val_loss, "state": {k: v.detach().clone() for k, v in model.state_dict().items()}}

    if best["state"] is not None:
        model.load_state_dict(best["state"])

    metrics = _evaluate(model, val_loader, "cpu")
    suffix = "_balanced" if balanced else ""
    name = f"dual_head_w{str(direction_weight).replace('.', 'p')}_thr{str(threshold).replace('.', 'p')}{suffix}"
    if extra_features:
        name = f"{name}_extra{len(extra_features)}"
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = EXPERIMENT_DIR / f"dl_{name}.pt"
    scaler_path = EXPERIMENT_DIR / f"dl_{name}_scaler.json"
    torch.save(
        {
            "state_dict": model.state_dict(),
            "feature_cols": feature_cols,
            "seq_len": 60,
            "hidden": 64,
            "dropout": 0.10,
            "direction_weight": direction_weight,
            "direction_threshold": threshold,
            "balanced_direction_loss": balanced,
        },
        model_path,
    )
    with scaler_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "feature_cols": feature_cols,
                "scaler": scaler,
                "seq_len": 60,
                "hidden": 64,
                "dropout": 0.10,
            },
            f,
            indent=2,
        )
    return {
        "variant": name,
        "direction_weight": direction_weight,
        "direction_threshold": threshold,
        "balanced_direction_loss": balanced,
        "panel_path": str(panel_path),
        "extra_features": extra_features,
        "feature_count": len(feature_cols),
        "model_path": str(model_path),
        "metrics": metrics,
    }


def _parse_floats(raw: str) -> List[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="0.1,0.25,0.5")
    ap.add_argument("--thresholds", default="0.005,0.01,0.02")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--val-days", type=int, default=252)
    ap.add_argument("--balanced", action="store_true")
    ap.add_argument("--panel", type=Path, default=PANEL_PATH_DEFAULT)
    ap.add_argument(
        "--extra-features",
        type=str,
        default="",
        help="Comma-separated research feature columns to append to the approved DL features.",
    )
    args = ap.parse_args()

    extra_features = _parse_features(args.extra_features)
    results = []
    for weight in _parse_floats(args.weights):
        for threshold in _parse_floats(args.thresholds):
            print(f"\n=== dual-head weight={weight} threshold={threshold} ===")
            result = _train_one(
                weight,
                threshold,
                args.epochs,
                args.batch_size,
                args.val_days,
                bool(args.balanced),
                args.panel,
                extra_features,
            )
            print(result["metrics"])
            results.append(result)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "seed": SEED,
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "val_days": args.val_days,
                "balanced": bool(args.balanced),
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
