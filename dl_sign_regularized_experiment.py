"""Research-only DL training with anti-collapse directional objectives."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, WeightedRandomSampler

from deep_learning_model import (
    FEATURE_COLS_DEFAULT,
    TARGET_COL,
    PanelSequenceDataset,
    TCNForecaster,
    TrainConfig,
    _ensure_panel_schema,
    fit_scaler,
    gaussian_nll,
    read_panel,
    time_split,
)
from dl_directional_loss_experiment import _parse_features
from dl_expanded_feature_seed_grid import DEFAULT_EXTRA_FEATURES, DEFAULT_PANEL

EXPERIMENT_DIR = Path("models/experiment")
OUT_PATH = Path("data/experiment/sign_regularized_comparison.json")
CSV_PATH = Path("data/experiment/sign_regularized_comparison.csv")


def _parse_ints(raw: str) -> List[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _parse_floats(raw: str) -> List[float]:
    return [float(part.strip()) for part in raw.split(",") if part.strip()]


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _feature_cols(panel_path: Path, extra_features: List[str]) -> List[str]:
    cols = list(FEATURE_COLS_DEFAULT)
    panel_cols = set(read_panel(panel_path).columns)
    missing = [col for col in extra_features if col not in panel_cols]
    if missing:
        raise ValueError(f"Missing extra features in {panel_path}: {missing}")
    for col in extra_features:
        if col not in cols:
            cols.append(col)
    return cols


def _pearson_corr_loss(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    x = pred.view(-1)
    y = target.view(-1)
    x = x - x.mean()
    y = y - y.mean()
    denom = torch.sqrt(torch.sum(x * x) + 1e-8) * torch.sqrt(torch.sum(y * y) + 1e-8)
    corr = torch.sum(x * y) / denom
    return -corr


def _sign_balance_loss(pred: torch.Tensor, target: torch.Tensor, temperature: float) -> torch.Tensor:
    bullish_prob = torch.sigmoid(pred.view(-1) / float(temperature)).mean()
    bullish_target = (target.view(-1) > 0).to(dtype=pred.dtype).mean()
    return (bullish_prob - bullish_target).pow(2)


def _pairwise_rank_loss(pred: torch.Tensor, target: torch.Tensor, temperature: float) -> torch.Tensor:
    p = pred.view(-1)
    y = target.view(-1)
    if p.numel() < 2:
        return p.sum() * 0.0

    pred_diff = p[:, None] - p[None, :]
    target_diff = y[:, None] - y[None, :]
    direction = torch.sign(target_diff)
    mask = direction != 0
    if not torch.any(mask):
        return p.sum() * 0.0
    margin = direction[mask] * pred_diff[mask] / float(temperature)
    return torch.nn.functional.softplus(-margin).mean()


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


def _evaluate(model: nn.Module, loader: DataLoader) -> tuple[dict, np.ndarray, np.ndarray]:
    model.eval()
    preds = []
    actuals = []
    losses = []
    with torch.no_grad():
        for xb, yb, _, _ in loader:
            mu, log_sigma = model(xb)
            losses.append(float(gaussian_nll(mu, log_sigma, yb).item()))
            preds.append(mu.cpu().numpy().ravel())
            actuals.append(yb.cpu().numpy().ravel())
    pred = np.concatenate(preds)
    actual = np.concatenate(actuals)
    metrics = _metrics(pred, actual)
    metrics["NLL"] = float(np.mean(losses))
    return metrics, pred, actual


def _balanced_sampler(ds: PanelSequenceDataset) -> WeightedRandomSampler:
    labels = []
    for tkr_idx, end_i in ds._samples:
        labels.append(float(ds._y[int(tkr_idx)][int(end_i)]) > 0)
    arr = np.asarray(labels, dtype=bool)
    pos = max(1, int(arr.sum()))
    neg = max(1, int((~arr).sum()))
    weights = np.where(arr, 1.0 / pos, 1.0 / neg)
    return WeightedRandomSampler(
        weights=torch.as_tensor(weights, dtype=torch.double),
        num_samples=len(weights),
        replacement=True,
    )


def _selection_score(metrics: dict, bullish_min: float, bullish_max: float) -> float:
    bullish = float(metrics["pct_bullish_pred"])
    in_bounds = bullish_min <= bullish <= bullish_max
    balance_penalty = 0.0 if in_bounds else min(abs(bullish - bullish_min), abs(bullish - bullish_max))
    return (
        float(metrics["Directional_Accuracy"])
        + 0.50 * float(metrics["IC_Spearman"])
        - 0.50 * balance_penalty
        - 0.05 * float(metrics["MAE"])
    )


def _train_one(
    panel_path: Path,
    extra_features: List[str],
    seed: int,
    epochs: int,
    batch_size: int,
    val_days: int,
    lr: float,
    corr_weight: float,
    balance_weight: float,
    rank_weight: float,
    balance_temperature: float,
    rank_temperature: float,
    balanced_sampler: bool,
    bullish_min: float,
    bullish_max: float,
) -> dict:
    _set_seed(seed)
    panel = _ensure_panel_schema(read_panel(panel_path))
    panel = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    cutoff, _ = time_split(panel, val_days)
    train_panel = panel[panel["Date"] < cutoff]
    val_panel = panel[panel["Date"] >= cutoff]

    feature_cols = _feature_cols(panel_path, extra_features)
    cfg = TrainConfig(seq_len=60, batch_size=batch_size, epochs=epochs, lr=lr, val_days=val_days)
    scaler = fit_scaler(train_panel, feature_cols)
    train_ds = PanelSequenceDataset(train_panel, scaler, feature_cols, cfg.seq_len, seed=seed)
    val_ds = PanelSequenceDataset(val_panel, scaler, feature_cols, cfg.seq_len, seed=seed + 1)
    sampler = _balanced_sampler(train_ds) if balanced_sampler else None
    train_loader = DataLoader(
        train_ds,
        batch_size=batch_size,
        shuffle=sampler is None,
        sampler=sampler,
        drop_last=True,
    )
    val_loader = DataLoader(val_ds, batch_size=1024, shuffle=False)

    model = TCNForecaster(n_features=len(feature_cols), hidden=cfg.hidden, dropout=cfg.dropout).to("cpu")
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.05)

    variant = (
        f"signreg_seed{seed}_cw{str(corr_weight).replace('.', 'p')}"
        f"_bw{str(balance_weight).replace('.', 'p')}"
        f"_rw{str(rank_weight).replace('.', 'p')}"
    )
    if balanced_sampler:
        variant = f"{variant}_bs"
    model_path = EXPERIMENT_DIR / f"dl_{variant}.pt"
    scaler_path = EXPERIMENT_DIR / f"dl_{variant}_scaler.json"
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)

    best = {"score": -float("inf"), "state": None, "metrics": None}
    for epoch in range(1, epochs + 1):
        model.train()
        train_losses = []
        for xb, yb, _, _ in train_loader:
            opt.zero_grad(set_to_none=True)
            mu, log_sigma = model(xb)
            loss = gaussian_nll(mu, log_sigma, yb)
            if corr_weight > 0:
                loss = loss + float(corr_weight) * _pearson_corr_loss(mu, yb)
            if balance_weight > 0:
                loss = loss + float(balance_weight) * _sign_balance_loss(mu, yb, balance_temperature)
            if rank_weight > 0:
                loss = loss + float(rank_weight) * _pairwise_rank_loss(mu, yb, rank_temperature)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            train_losses.append(float(loss.item()))

        scheduler.step()
        metrics, _, _ = _evaluate(model, val_loader)
        score = _selection_score(metrics, bullish_min, bullish_max)
        print(
            f"seed={seed} cw={corr_weight} bw={balance_weight} epoch={epoch} "
            f"rw={rank_weight} "
            f"train={np.mean(train_losses):.6f} val_nll={metrics['NLL']:.6f} "
            f"dir={metrics['Directional_Accuracy']:.4f} ic={metrics['IC_Spearman']:.4f} "
            f"bull={metrics['pct_bullish_pred']:.4f} score={score:.4f}"
        )
        if score > best["score"]:
            best = {
                "score": score,
                "state": {k: v.detach().clone() for k, v in model.state_dict().items()},
                "metrics": metrics,
            }

    if best["state"] is not None:
        model.load_state_dict(best["state"])

    torch.save(
        {
            "state_dict": model.state_dict(),
            "feature_cols": feature_cols,
            "seq_len": cfg.seq_len,
            "hidden": cfg.hidden,
            "dropout": cfg.dropout,
            "seed": seed,
            "corr_weight": corr_weight,
            "balance_weight": balance_weight,
            "rank_weight": rank_weight,
            "balanced_sampler": balanced_sampler,
            "selection_score": best["score"],
        },
        model_path,
    )
    with scaler_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "feature_cols": feature_cols,
                "scaler": scaler,
                "seq_len": cfg.seq_len,
                "hidden": cfg.hidden,
                "dropout": cfg.dropout,
            },
            f,
            indent=2,
        )

    metrics, _, _ = _evaluate(model, val_loader)
    return {
        "variant": variant,
        "seed": seed,
        "corr_weight": corr_weight,
        "balance_weight": balance_weight,
        "rank_weight": rank_weight,
        "balanced_sampler": balanced_sampler,
        "balance_temperature": balance_temperature,
        "rank_temperature": rank_temperature,
        "selection_score": float(best["score"]),
        "panel_path": str(panel_path),
        "extra_features": extra_features,
        "feature_count": len(feature_cols),
        "model_path": str(model_path),
        "scaler_path": str(scaler_path),
        "metrics": metrics,
    }


def _aggregate(rows: list[dict]) -> dict:
    df = pd.DataFrame([{**row, **row["metrics"]} for row in rows])
    metrics = ["MAE", "RMSE", "Directional_Accuracy", "Correlation", "IC_Spearman", "pct_bullish_pred"]
    out = {}
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
    ap.add_argument("--seeds", default="20260505,20260506,20260507")
    ap.add_argument("--corr-weights", default="0,0.05,0.1")
    ap.add_argument("--balance-weights", default="0,0.1,0.5")
    ap.add_argument("--rank-weights", default="0")
    ap.add_argument("--balance-temperature", type=float, default=0.02)
    ap.add_argument("--rank-temperature", type=float, default=0.02)
    ap.add_argument("--balanced-sampler", action="store_true")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--val-days", type=int, default=252)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--bullish-min", type=float, default=0.35)
    ap.add_argument("--bullish-max", type=float, default=0.75)
    ap.add_argument("--output", type=Path, default=OUT_PATH)
    ap.add_argument("--csv-output", type=Path, default=CSV_PATH)
    args = ap.parse_args()

    extra_features = _parse_features(args.extra_features)
    results = []
    for seed in _parse_ints(args.seeds):
        for corr_weight in _parse_floats(args.corr_weights):
            for balance_weight in _parse_floats(args.balance_weights):
                for rank_weight in _parse_floats(args.rank_weights):
                    print(
                        f"\n=== sign regularized seed={seed} corr={corr_weight} "
                        f"balance={balance_weight} rank={rank_weight} ==="
                    )
                    results.append(
                        _train_one(
                            panel_path=args.panel,
                            extra_features=extra_features,
                            seed=seed,
                            epochs=int(args.epochs),
                            batch_size=int(args.batch_size),
                            val_days=int(args.val_days),
                            lr=float(args.lr),
                            corr_weight=float(corr_weight),
                            balance_weight=float(balance_weight),
                            rank_weight=float(rank_weight),
                            balance_temperature=float(args.balance_temperature),
                            rank_temperature=float(args.rank_temperature),
                            balanced_sampler=bool(args.balanced_sampler),
                            bullish_min=float(args.bullish_min),
                            bullish_max=float(args.bullish_max),
                        )
                    )

    flat_rows = [{**row, **row["metrics"]} for row in results]
    aggregate = _aggregate(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(flat_rows).to_csv(args.csv_output, index=False)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "panel_path": str(args.panel),
                "extra_features": extra_features,
                "epochs": int(args.epochs),
                "batch_size": int(args.batch_size),
                "val_days": int(args.val_days),
                "lr": float(args.lr),
                "results": results,
                "aggregate": aggregate,
            },
            f,
            indent=2,
        )

    print("\nTop results:")
    top = pd.DataFrame(flat_rows).sort_values(
        ["Directional_Accuracy", "IC_Spearman", "pct_bullish_pred"],
        ascending=[False, False, True],
    )
    print(top[["variant", "MAE", "RMSE", "Directional_Accuracy", "IC_Spearman", "pct_bullish_pred"]].head(15))
    print(f"\nSaved -> {args.output}")


if __name__ == "__main__":
    main()
