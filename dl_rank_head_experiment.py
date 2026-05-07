"""Research-only DL experiment with separate return and rank heads.

The production TCN emits one return estimate that must carry both magnitude and
cross-sectional ranking. This experiment keeps the return head for price-error
tracking and trains a second score head for date-relative ranking quality.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader

from deep_learning_model import (
    TARGET_COL,
    FeatureGate,
    PanelSequenceDataset,
    TCNBlock,
    TemporalAttentionPool,
    TrainConfig,
    _ensure_panel_schema,
    fit_scaler,
    gaussian_nll,
    read_panel,
    time_split,
)
from dl_directional_loss_experiment import _parse_features
from dl_expanded_feature_seed_grid import DEFAULT_EXTRA_FEATURES, DEFAULT_PANEL
from dl_sign_regularized_experiment import (
    DateGroupedBatchSampler,
    _feature_cols,
    _grouped_aux_loss,
    _metrics,
    _parse_floats,
    _parse_ints,
    _resolve_device,
    _selection_score,
    _transform_aux_target,
)

EXPERIMENT_DIR = Path("models/experiment")
OUT_PATH = Path("data/experiment/rank_head_comparison.json")
CSV_PATH = Path("data/experiment/rank_head_comparison.csv")


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class RankHeadTCN(nn.Module):
    """TCN backbone with independent raw-return and cross-sectional score heads."""

    def __init__(self, n_features: int, hidden: int = 64, dropout: float = 0.10):
        super().__init__()
        self.n_features = int(n_features)
        self.hidden = int(hidden)
        self.dropout = float(dropout)

        self.feature_gate = FeatureGate(self.n_features)
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
        self.rank_head = nn.Sequential(
            nn.Linear(self.hidden, self.hidden),
            nn.GELU(),
            nn.Dropout(self.dropout),
            nn.Linear(self.hidden, 1),
        )

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        x = x.transpose(1, 2)
        x = self.feature_gate(x)
        h = self.in_proj(x)
        h = self.blocks(h)
        h = self.temporal_pool(h)
        h = self.norm(h)
        raw = self.return_head(h)
        mu = raw[:, 0:1]
        log_sigma = raw[:, 1:2].clamp(-6.0, 3.0)
        rank_score = self.rank_head(h)
        return mu, log_sigma, rank_score


def _pearson_corr_loss(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    x = pred.view(-1)
    y = target.view(-1)
    x = x - x.mean()
    y = y - y.mean()
    denom = torch.sqrt(torch.sum(x * x) + 1e-8) * torch.sqrt(torch.sum(y * y) + 1e-8)
    return -(torch.sum(x * y) / denom)


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


def _ungrouped_aux_loss(
    pred: torch.Tensor,
    target: torch.Tensor,
    loss_name: str,
    temperature: float,
    target_transform: str,
) -> torch.Tensor:
    aux_target = _transform_aux_target(target, target_transform)
    if loss_name == "corr":
        return _pearson_corr_loss(pred, aux_target)
    if loss_name == "rank":
        return _pairwise_rank_loss(pred, aux_target, temperature)
    raise ValueError(f"Unknown auxiliary loss: {loss_name}")


def _center_by_date(pred: np.ndarray, dates_ns: np.ndarray) -> np.ndarray:
    rows = pd.DataFrame({"pred": pred, "date": dates_ns})
    centered = rows["pred"] - rows.groupby("date", sort=False)["pred"].transform("mean")
    return centered.to_numpy(dtype=np.float32)


def _selection_metrics(
    pred: np.ndarray,
    actual: np.ndarray,
    dates_ns: np.ndarray,
    top_frac: float = 0.20,
) -> dict:
    rows = pd.DataFrame({"pred": pred, "actual": actual, "date": dates_ns})
    top_returns = []
    bottom_returns = []
    spreads = []
    for _, g in rows.groupby("date", sort=False):
        if len(g) < 4:
            continue
        n_select = max(1, int(np.floor(len(g) * float(top_frac))))
        ordered = g.sort_values("pred", ascending=False)
        top_ret = float(ordered.head(n_select)["actual"].mean())
        bottom_ret = float(ordered.tail(n_select)["actual"].mean())
        top_returns.append(top_ret)
        bottom_returns.append(bottom_ret)
        spreads.append(top_ret - bottom_ret)

    if not spreads:
        return {
            "Selection_Top_Return_Mean": float("nan"),
            "Selection_Bottom_Return_Mean": float("nan"),
            "Selection_Long_Short_Spread_Mean": float("nan"),
            "Selection_Spread_Positive_Rate": float("nan"),
            "Selection_Long_Hit_Rate": float("nan"),
            "Selection_Short_Hit_Rate": float("nan"),
            "Selection_Count": 0,
        }

    top_arr = np.asarray(top_returns, dtype=np.float64)
    bottom_arr = np.asarray(bottom_returns, dtype=np.float64)
    spread_arr = np.asarray(spreads, dtype=np.float64)
    return {
        "Selection_Top_Return_Mean": float(np.mean(top_arr)),
        "Selection_Bottom_Return_Mean": float(np.mean(bottom_arr)),
        "Selection_Long_Short_Spread_Mean": float(np.mean(spread_arr)),
        "Selection_Spread_Positive_Rate": float(np.mean(spread_arr > 0.0)),
        "Selection_Long_Hit_Rate": float(np.mean(top_arr > 0.0)),
        "Selection_Short_Hit_Rate": float(np.mean(bottom_arr < 0.0)),
        "Selection_Count": int(len(spread_arr)),
    }


def _rank_selection_score(
    metrics: dict,
    bullish_min: float,
    bullish_max: float,
    ic_min: float,
    daily_ic_min: float,
    spread_min: float,
    spread_positive_rate_min: float,
    hard_gate: bool,
) -> float:
    ic = float(metrics.get("IC_Spearman", float("nan")))
    daily_ic = float(metrics.get("Daily_IC_Mean", float("nan")))
    spread = float(metrics.get("Selection_Long_Short_Spread_Mean", float("nan")))
    spread_pos = float(metrics.get("Selection_Spread_Positive_Rate", float("nan")))
    bullish = float(metrics.get("pct_bullish_pred", float("nan")))
    if not np.isfinite(ic):
        ic = -1.0
    if not np.isfinite(daily_ic):
        daily_ic = ic
    if not np.isfinite(spread):
        spread = -1.0
    if not np.isfinite(spread_pos):
        spread_pos = 0.0
    if not np.isfinite(bullish):
        bullish = 1.0

    balance_violation = 0.0
    if bullish < bullish_min:
        balance_violation = bullish_min - bullish
    elif bullish > bullish_max:
        balance_violation = bullish - bullish_max

    hard_penalty = 0.0
    if hard_gate:
        hard_penalty = (
            12.0 * max(0.0, float(spread_min) - spread)
            + 4.0 * max(0.0, float(spread_positive_rate_min) - spread_pos)
            + 4.0 * max(0.0, float(daily_ic_min) - daily_ic)
            + 2.0 * max(0.0, float(ic_min) - ic)
            + 4.0 * balance_violation
        )

    return (
        2.0 * spread
        + 0.75 * daily_ic
        + 0.35 * ic
        + 0.20 * spread_pos
        - 0.50 * balance_violation
        - hard_penalty
    )


def _evaluate_rank_model(
    model: nn.Module,
    loader: DataLoader,
    device: str,
    amp: bool,
    non_blocking: bool,
) -> tuple[dict, dict, dict]:
    model.eval()
    raw_preds = []
    rank_preds = []
    actuals = []
    dates = []
    losses = []
    with torch.no_grad():
        for xb, yb, _, date_ns in loader:
            xb = xb.to(device, non_blocking=non_blocking)
            yb = yb.to(device, non_blocking=non_blocking)
            with torch.amp.autocast("cuda", enabled=amp and device.startswith("cuda")):
                mu, log_sigma, rank_score = model(xb)
            losses.append(float(gaussian_nll(mu.float(), log_sigma.float(), yb.float()).item()))
            raw_preds.append(mu.detach().cpu().numpy().ravel())
            rank_preds.append(rank_score.detach().cpu().numpy().ravel())
            actuals.append(yb.detach().cpu().numpy().ravel())
            dates.append(np.asarray(date_ns).ravel())

    actual = np.concatenate(actuals)
    date_arr = np.concatenate(dates)
    raw_pred = np.concatenate(raw_preds)
    rank_pred = np.concatenate(rank_preds)
    rank_centered = _center_by_date(rank_pred, date_arr)
    raw_metrics = _metrics(raw_pred, actual, date_arr)
    rank_metrics = _metrics(rank_pred, actual, date_arr)
    rank_centered_metrics = _metrics(rank_centered, actual, date_arr)
    raw_metrics.update(_selection_metrics(raw_pred, actual, date_arr))
    rank_metrics.update(_selection_metrics(rank_pred, actual, date_arr))
    rank_centered_metrics.update(_selection_metrics(rank_centered, actual, date_arr))
    raw_metrics["NLL"] = float(np.mean(losses))
    return raw_metrics, rank_metrics, rank_centered_metrics


def _train_one(
    panel_path: Path,
    extra_features: List[str],
    seed: int,
    epochs: int,
    batch_size: int,
    val_days: int,
    lr: float,
    scheduler_name: str,
    max_lr: float | None,
    onecycle_pct_start: float,
    onecycle_div_factor: float,
    onecycle_final_div_factor: float,
    device: str,
    amp: bool,
    num_workers: int,
    pin_memory: bool,
    nll_weight: float,
    corr_weight: float,
    rank_weight: float,
    aux_target_transform: str,
    rank_temperature: float,
    date_grouped_batches: bool,
    min_date_batch_size: int,
    dates_per_batch: int,
    bullish_min: float,
    bullish_max: float,
    ic_min: float,
    daily_ic_min: float,
    spread_min: float,
    spread_positive_rate_min: float,
    selection_score_mode: str,
    direction_min: float,
    hard_gate: bool,
    daily_ic_weight: float,
    artifact_dir: Path | None = None,
) -> dict:
    _set_seed(seed)
    device = _resolve_device(device)
    use_amp = bool(amp and device.startswith("cuda"))
    pin = bool(pin_memory and device.startswith("cuda"))

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

    loader_kwargs = {"num_workers": int(num_workers), "pin_memory": pin}
    if int(num_workers) > 0:
        loader_kwargs["persistent_workers"] = True
    if date_grouped_batches:
        batch_sampler = DateGroupedBatchSampler(
            train_ds,
            seed=seed,
            min_batch_size=min_date_batch_size,
            dates_per_batch=dates_per_batch,
        )
        train_loader = DataLoader(train_ds, batch_sampler=batch_sampler, **loader_kwargs)
        print(
            f"date-grouped batches={len(batch_sampler)} "
            f"date_count={batch_sampler.date_count} "
            f"dates_per_batch={int(dates_per_batch)}"
        )
    else:
        train_loader = DataLoader(
            train_ds,
            batch_size=batch_size,
            shuffle=True,
            drop_last=True,
            **loader_kwargs,
        )
    val_loader = DataLoader(val_ds, batch_size=1024, shuffle=False, **loader_kwargs)

    model = RankHeadTCN(n_features=len(feature_cols), hidden=cfg.hidden, dropout=cfg.dropout).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    if scheduler_name == "onecycle":
        scheduler = torch.optim.lr_scheduler.OneCycleLR(
            opt,
            max_lr=float(max_lr if max_lr is not None else lr),
            epochs=int(epochs),
            steps_per_epoch=len(train_loader),
            pct_start=float(onecycle_pct_start),
            div_factor=float(onecycle_div_factor),
            final_div_factor=float(onecycle_final_div_factor),
        )
    elif scheduler_name == "cosine":
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.05)
    elif scheduler_name == "none":
        scheduler = None
    else:
        raise ValueError(f"Unknown scheduler: {scheduler_name}")
    amp_scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    variant = (
        f"rankhead_seed{seed}_cw{str(corr_weight).replace('.', 'p')}"
        f"_rw{str(rank_weight).replace('.', 'p')}"
        f"_nw{str(nll_weight).replace('.', 'p')}"
    )
    if date_grouped_batches:
        variant = f"{variant}_dgb"
    save_dir = Path(artifact_dir) if artifact_dir is not None else EXPERIMENT_DIR
    model_path = save_dir / f"dl_{variant}.pt"
    scaler_path = save_dir / f"dl_{variant}_scaler.json"
    save_dir.mkdir(parents=True, exist_ok=True)

    best = {
        "score": -float("inf"),
        "state": None,
        "raw_metrics": None,
        "rank_metrics": None,
        "rank_centered_metrics": None,
    }
    for epoch in range(1, epochs + 1):
        model.train()
        train_losses = []
        for xb, yb, _, date_ns in train_loader:
            xb = xb.to(device, non_blocking=pin)
            yb = yb.to(device, non_blocking=pin)
            date_ns = date_ns.to(device, non_blocking=pin)
            opt.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=use_amp):
                mu, log_sigma, rank_score = model(xb)

            mu_loss = mu.float()
            rank_loss_input = rank_score.float()
            yb_loss = yb.float()
            loss = float(nll_weight) * gaussian_nll(mu_loss, log_sigma.float(), yb_loss)
            if corr_weight > 0:
                corr_loss = (
                    _grouped_aux_loss(
                        rank_loss_input,
                        yb_loss,
                        date_ns,
                        "corr",
                        rank_temperature,
                        min_date_batch_size,
                        aux_target_transform,
                    )
                    if date_grouped_batches
                    else _ungrouped_aux_loss(
                        rank_loss_input,
                        yb_loss,
                        "corr",
                        rank_temperature,
                        aux_target_transform,
                    )
                )
                loss = loss + float(corr_weight) * corr_loss
            if rank_weight > 0:
                pair_loss = (
                    _grouped_aux_loss(
                        rank_loss_input,
                        yb_loss,
                        date_ns,
                        "rank",
                        rank_temperature,
                        min_date_batch_size,
                        aux_target_transform,
                    )
                    if date_grouped_batches
                    else _ungrouped_aux_loss(
                        rank_loss_input,
                        yb_loss,
                        "rank",
                        rank_temperature,
                        aux_target_transform,
                    )
                )
                loss = loss + float(rank_weight) * pair_loss

            amp_scaler.scale(loss).backward()
            amp_scaler.unscale_(opt)
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            amp_scaler.step(opt)
            amp_scaler.update()
            if scheduler_name == "onecycle" and scheduler is not None:
                scheduler.step()
            train_losses.append(float(loss.item()))

        if scheduler_name == "cosine" and scheduler is not None:
            scheduler.step()
        raw_metrics, rank_metrics, rank_centered_metrics = _evaluate_rank_model(model, val_loader, device, use_amp, pin)
        if selection_score_mode == "selection":
            score = _rank_selection_score(
                rank_centered_metrics,
                bullish_min,
                bullish_max,
                ic_min,
                daily_ic_min,
                spread_min,
                spread_positive_rate_min,
                hard_gate,
            )
        elif selection_score_mode == "legacy":
            score = _selection_score(
                rank_centered_metrics,
                bullish_min,
                bullish_max,
                ic_min,
                daily_ic_min,
                direction_min,
                hard_gate,
                daily_ic_weight,
            )
        else:
            raise ValueError(f"Unknown selection score mode: {selection_score_mode}")
        print(
            f"seed={seed} epoch={epoch}/{epochs} loss={np.mean(train_losses):.5f} "
            f"raw_dir={raw_metrics['Directional_Accuracy']:.4f} "
            f"rank_dir={rank_metrics['Directional_Accuracy']:.4f} "
            f"center_dir={rank_centered_metrics['Directional_Accuracy']:.4f} "
            f"rank_ic={rank_metrics['IC_Spearman']:.4f} "
            f"center_daily_ic={rank_centered_metrics['Daily_IC_Mean']:.4f} "
            f"center_spread={rank_centered_metrics['Selection_Long_Short_Spread_Mean']:.4f} "
            f"spread_pos={rank_centered_metrics['Selection_Spread_Positive_Rate']:.4f} "
            f"center_bull={rank_centered_metrics['pct_bullish_pred']:.4f}"
        )
        if score > float(best["score"]):
            best = {
                "score": float(score),
                "state": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
                "raw_metrics": raw_metrics,
                "rank_metrics": rank_metrics,
                "rank_centered_metrics": rank_centered_metrics,
            }

    if best["state"] is not None:
        model.load_state_dict(best["state"])
    raw_metrics, rank_metrics, rank_centered_metrics = _evaluate_rank_model(model, val_loader, device, use_amp, pin)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "model_type": "RankHeadTCN",
            "feature_cols": feature_cols,
            "seq_len": cfg.seq_len,
            "hidden": cfg.hidden,
            "dropout": cfg.dropout,
            "seed": seed,
            "device": device,
            "amp": use_amp,
            "scheduler": scheduler_name,
            "lr": lr,
            "max_lr": max_lr,
            "nll_weight": nll_weight,
            "corr_weight": corr_weight,
            "rank_weight": rank_weight,
            "aux_target_transform": aux_target_transform,
            "date_grouped_batches": date_grouped_batches,
            "min_date_batch_size": min_date_batch_size,
            "dates_per_batch": dates_per_batch,
            "selection_score_mode": selection_score_mode,
            "spread_min": spread_min,
            "spread_positive_rate_min": spread_positive_rate_min,
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
                "model_type": "RankHeadTCN",
            },
            f,
            indent=2,
        )
    return {
        "variant": variant,
        "seed": seed,
        "device": device,
        "amp": use_amp,
        "scheduler": scheduler_name,
        "lr": lr,
        "max_lr": max_lr,
        "num_workers": int(num_workers),
        "pin_memory": pin,
        "nll_weight": nll_weight,
        "corr_weight": corr_weight,
        "rank_weight": rank_weight,
        "aux_target_transform": aux_target_transform,
        "rank_temperature": rank_temperature,
        "date_grouped_batches": date_grouped_batches,
        "min_date_batch_size": min_date_batch_size,
        "dates_per_batch": dates_per_batch,
        "hard_gate": hard_gate,
        "ic_min": ic_min,
        "daily_ic_min": daily_ic_min,
        "spread_min": spread_min,
        "spread_positive_rate_min": spread_positive_rate_min,
        "selection_score_mode": selection_score_mode,
        "direction_min": direction_min,
        "daily_ic_weight": daily_ic_weight,
        "selection_score": float(best["score"]),
        "panel_path": str(panel_path),
        "extra_features": extra_features,
        "feature_count": len(feature_cols),
        "artifact_dir": str(save_dir),
        "model_path": str(model_path),
        "scaler_path": str(scaler_path),
        "raw_metrics": raw_metrics,
        "rank_metrics": rank_metrics,
        "rank_centered_metrics": rank_centered_metrics,
    }


def _aggregate(rows: list[dict], key: str) -> dict:
    df = pd.DataFrame([{**row, **row[key]} for row in rows])
    metrics = [
        "MAE",
        "RMSE",
        "Directional_Accuracy",
        "Correlation",
        "IC_Spearman",
        "Daily_IC_Mean",
        "Daily_IC_Positive_Rate",
        "Daily_Directional_Accuracy",
        "pct_bullish_pred",
        "Selection_Top_Return_Mean",
        "Selection_Bottom_Return_Mean",
        "Selection_Long_Short_Spread_Mean",
        "Selection_Spread_Positive_Rate",
        "Selection_Long_Hit_Rate",
        "Selection_Short_Hit_Rate",
    ]
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
    ap.add_argument("--corr-weights", default="0.05")
    ap.add_argument("--rank-weights", default="0.01")
    ap.add_argument("--nll-weights", default="0.5")
    ap.add_argument("--aux-target-transform", choices=["raw", "demean", "zscore"], default="zscore")
    ap.add_argument("--rank-temperature", type=float, default=0.02)
    ap.add_argument("--date-grouped-batches", action="store_true")
    ap.add_argument("--min-date-batch-size", type=int, default=2)
    ap.add_argument("--dates-per-batch", type=int, default=64)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--val-days", type=int, default=252)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--scheduler", choices=["cosine", "onecycle", "none"], default="cosine")
    ap.add_argument("--max-lr", type=float, default=None)
    ap.add_argument("--onecycle-pct-start", type=float, default=0.45)
    ap.add_argument("--onecycle-div-factor", type=float, default=10.0)
    ap.add_argument("--onecycle-final-div-factor", type=float, default=1000.0)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument("--pin-memory", action="store_true")
    ap.add_argument("--cudnn-benchmark", action="store_true")
    ap.add_argument("--bullish-min", type=float, default=0.35)
    ap.add_argument("--bullish-max", type=float, default=0.75)
    ap.add_argument("--ic-min", type=float, default=0.0)
    ap.add_argument("--daily-ic-min", type=float, default=-0.02)
    ap.add_argument("--spread-min", type=float, default=0.0)
    ap.add_argument("--spread-positive-rate-min", type=float, default=0.55)
    ap.add_argument("--selection-score-mode", choices=["selection", "legacy"], default="selection")
    ap.add_argument("--direction-min", type=float, default=0.5085)
    ap.add_argument("--daily-ic-weight", type=float, default=0.75)
    ap.add_argument("--hard-gate", action="store_true")
    ap.add_argument("--output", type=Path, default=OUT_PATH)
    ap.add_argument("--csv-output", type=Path, default=CSV_PATH)
    ap.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Optional immutable directory for saved rank-head checkpoints and scalers.",
    )
    args = ap.parse_args()

    if args.cudnn_benchmark and torch.cuda.is_available():
        torch.backends.cudnn.benchmark = True

    extra_features = _parse_features(args.extra_features)
    results = []
    for seed in _parse_ints(args.seeds):
        for corr_weight in _parse_floats(args.corr_weights):
            for rank_weight in _parse_floats(args.rank_weights):
                for nll_weight in _parse_floats(args.nll_weights):
                    print(
                        f"\n=== rank-head seed={seed} corr={corr_weight} "
                        f"rank={rank_weight} nll={nll_weight} ==="
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
                            scheduler_name=args.scheduler,
                            max_lr=args.max_lr,
                            onecycle_pct_start=float(args.onecycle_pct_start),
                            onecycle_div_factor=float(args.onecycle_div_factor),
                            onecycle_final_div_factor=float(args.onecycle_final_div_factor),
                            device=args.device,
                            amp=bool(args.amp),
                            num_workers=int(args.num_workers),
                            pin_memory=bool(args.pin_memory),
                            nll_weight=float(nll_weight),
                            corr_weight=float(corr_weight),
                            rank_weight=float(rank_weight),
                            aux_target_transform=args.aux_target_transform,
                            rank_temperature=float(args.rank_temperature),
                            date_grouped_batches=bool(args.date_grouped_batches),
                            min_date_batch_size=int(args.min_date_batch_size),
                            dates_per_batch=int(args.dates_per_batch),
                            bullish_min=float(args.bullish_min),
                            bullish_max=float(args.bullish_max),
                            ic_min=float(args.ic_min),
                            daily_ic_min=float(args.daily_ic_min),
                            spread_min=float(args.spread_min),
                            spread_positive_rate_min=float(args.spread_positive_rate_min),
                            selection_score_mode=args.selection_score_mode,
                            direction_min=float(args.direction_min),
                            daily_ic_weight=float(args.daily_ic_weight),
                            hard_gate=bool(args.hard_gate),
                            artifact_dir=args.artifact_dir,
                        )
                    )

    flat_rows = []
    for row in results:
        base = {k: v for k, v in row.items() if k not in {"raw_metrics", "rank_metrics", "rank_centered_metrics"}}
        raw = {f"raw_{k}": v for k, v in row["raw_metrics"].items()}
        rank = {f"rank_{k}": v for k, v in row["rank_metrics"].items()}
        rank_centered = {f"rank_centered_{k}": v for k, v in row["rank_centered_metrics"].items()}
        flat_rows.append({**base, **raw, **rank, **rank_centered})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(flat_rows).to_csv(args.csv_output, index=False)
    aggregate = {
        "raw": _aggregate(results, "raw_metrics"),
        "rank": _aggregate(results, "rank_metrics"),
        "rank_centered": _aggregate(results, "rank_centered_metrics"),
    }
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "panel_path": str(args.panel),
                "extra_features": extra_features,
                "epochs": int(args.epochs),
                "batch_size": int(args.batch_size),
                "date_grouped_batches": bool(args.date_grouped_batches),
                "min_date_batch_size": int(args.min_date_batch_size),
                "dates_per_batch": int(args.dates_per_batch),
                "val_days": int(args.val_days),
                "lr": float(args.lr),
                "scheduler": args.scheduler,
                "max_lr": args.max_lr,
                "device": args.device,
                "amp": bool(args.amp),
                "num_workers": int(args.num_workers),
                "pin_memory": bool(args.pin_memory),
                "cudnn_benchmark": bool(args.cudnn_benchmark),
                "nll_weights": _parse_floats(args.nll_weights),
                "corr_weights": _parse_floats(args.corr_weights),
                "rank_weights": _parse_floats(args.rank_weights),
                "aux_target_transform": args.aux_target_transform,
                "hard_gate": bool(args.hard_gate),
                "ic_min": float(args.ic_min),
                "daily_ic_min": float(args.daily_ic_min),
                "spread_min": float(args.spread_min),
                "spread_positive_rate_min": float(args.spread_positive_rate_min),
                "selection_score_mode": args.selection_score_mode,
                "direction_min": float(args.direction_min),
                "daily_ic_weight": float(args.daily_ic_weight),
                "bullish_min": float(args.bullish_min),
                "bullish_max": float(args.bullish_max),
                "artifact_dir": str(args.artifact_dir) if args.artifact_dir is not None else str(EXPERIMENT_DIR),
                "results": results,
                "aggregate": aggregate,
            },
            f,
            indent=2,
        )

    top = pd.DataFrame(flat_rows).sort_values(
        [
            "rank_centered_Selection_Long_Short_Spread_Mean",
            "rank_centered_Daily_IC_Mean",
            "rank_centered_IC_Spearman",
        ],
        ascending=[False, False, True],
    )
    print("\nTop rank-head results:")
    print(
        top[
            [
                "variant",
                "raw_MAE",
                "raw_RMSE",
                "raw_Directional_Accuracy",
                "rank_Directional_Accuracy",
                "rank_centered_Directional_Accuracy",
                "rank_centered_IC_Spearman",
                "rank_centered_Daily_IC_Mean",
                "rank_centered_Selection_Long_Short_Spread_Mean",
                "rank_centered_Selection_Spread_Positive_Rate",
                "rank_centered_pct_bullish_pred",
            ]
        ].head(15)
    )
    print(f"\nSaved -> {args.output}")


if __name__ == "__main__":
    main()
