"""Research-only DL training with anti-collapse directional objectives."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Iterator, List

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, Sampler, WeightedRandomSampler

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


def _resolve_device(raw: str) -> str:
    if raw == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if raw == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("--device cuda requested, but CUDA is not available.")
    return raw


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


def _grouped_aux_loss(
    pred: torch.Tensor,
    target: torch.Tensor,
    dates_ns: torch.Tensor,
    loss_name: str,
    temperature: float,
    min_group_size: int,
) -> torch.Tensor:
    pieces = []
    flat_dates = dates_ns.view(-1)
    for date_ns in torch.unique(flat_dates):
        mask = flat_dates == date_ns
        if int(mask.sum().item()) < int(min_group_size):
            continue
        if loss_name == "corr":
            pieces.append(_pearson_corr_loss(pred[mask], target[mask]))
        elif loss_name == "balance":
            pieces.append(_sign_balance_loss(pred[mask], target[mask], temperature))
        elif loss_name == "rank":
            pieces.append(_pairwise_rank_loss(pred[mask], target[mask], temperature))
        else:
            raise ValueError(f"Unknown grouped loss: {loss_name}")
    if not pieces:
        return pred.sum() * 0.0
    return torch.stack(pieces).mean()


def _daily_metrics(pred: np.ndarray, actual: np.ndarray, dates_ns: np.ndarray) -> dict:
    rows = pd.DataFrame({"pred": pred, "actual": actual, "date": dates_ns})
    ic_vals = []
    dir_vals = []
    for _, g in rows.groupby("date", sort=False):
        if len(g) < 2:
            continue
        dir_vals.append(float(np.mean(np.sign(g["actual"]) == np.sign(g["pred"]))))
        if g["pred"].std(ddof=0) > 1e-12 and g["actual"].std(ddof=0) > 1e-12:
            ic_vals.append(float(g["pred"].rank().corr(g["actual"].rank())))
    return {
        "Daily_IC_Mean": float(np.mean(ic_vals)) if ic_vals else float("nan"),
        "Daily_IC_Positive_Rate": float(np.mean(np.asarray(ic_vals) >= 0.0)) if ic_vals else float("nan"),
        "Daily_Directional_Accuracy": float(np.mean(dir_vals)) if dir_vals else float("nan"),
        "Daily_Count": int(len(dir_vals)),
    }


def _metrics(pred: np.ndarray, actual: np.ndarray, dates_ns: np.ndarray | None = None) -> dict:
    out = {
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
    if dates_ns is not None:
        out.update(_daily_metrics(pred, actual, dates_ns))
    return out


def _evaluate(
    model: nn.Module,
    loader: DataLoader,
    device: str,
    amp: bool,
    non_blocking: bool,
) -> tuple[dict, np.ndarray, np.ndarray]:
    model.eval()
    preds = []
    actuals = []
    dates = []
    losses = []
    with torch.no_grad():
        for xb, yb, _, date_ns in loader:
            xb = xb.to(device, non_blocking=non_blocking)
            yb = yb.to(device, non_blocking=non_blocking)
            with torch.amp.autocast("cuda", enabled=amp and device.startswith("cuda")):
                mu, log_sigma = model(xb)
            loss = gaussian_nll(mu.float(), log_sigma.float(), yb.float())
            losses.append(float(loss.item()))
            preds.append(mu.detach().cpu().numpy().ravel())
            actuals.append(yb.detach().cpu().numpy().ravel())
            dates.append(np.asarray(date_ns).ravel())
    pred = np.concatenate(preds)
    actual = np.concatenate(actuals)
    date_arr = np.concatenate(dates)
    metrics = _metrics(pred, actual, date_arr)
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


class DateGroupedBatchSampler(Sampler[List[int]]):
    """Yield batches containing samples from the same prediction date."""

    def __init__(
        self,
        ds: PanelSequenceDataset,
        seed: int,
        min_batch_size: int = 2,
        dates_per_batch: int = 1,
    ):
        groups: dict[int, list[int]] = {}
        for sample_idx, (tkr_idx, end_i) in enumerate(ds._samples):
            date_ns = int(ds._dates_ns[int(tkr_idx)][int(end_i)])
            groups.setdefault(date_ns, []).append(int(sample_idx))
        self._date_batches = [idxs for idxs in groups.values() if len(idxs) >= int(min_batch_size)]
        if not self._date_batches:
            raise RuntimeError("No date-grouped batches available. Lower --min-date-batch-size or check panel coverage.")
        self._seed = int(seed)
        self._dates_per_batch = max(1, int(dates_per_batch))
        self._epoch = 0

    def __iter__(self) -> Iterator[List[int]]:
        rng = np.random.default_rng(self._seed + self._epoch)
        self._epoch += 1
        order = rng.permutation(len(self._date_batches))
        for start in range(0, len(order), self._dates_per_batch):
            batch = []
            for batch_i in order[start : start + self._dates_per_batch]:
                batch.extend(self._date_batches[int(batch_i)])
            rng.shuffle(batch)
            yield batch

    def __len__(self) -> int:
        return int(np.ceil(len(self._date_batches) / self._dates_per_batch))

    @property
    def date_count(self) -> int:
        return len(self._date_batches)


def _selection_score(
    metrics: dict,
    bullish_min: float,
    bullish_max: float,
    ic_min: float,
    direction_min: float,
    hard_gate: bool,
) -> float:
    bullish = float(metrics["pct_bullish_pred"])
    ic = float(metrics["IC_Spearman"])
    if not np.isfinite(ic):
        ic = -1.0
    daily_ic = float(metrics.get("Daily_IC_Mean", float("nan")))
    if not np.isfinite(daily_ic):
        daily_ic = ic

    balance_violation = 0.0
    if bullish < bullish_min:
        balance_violation = bullish_min - bullish
    elif bullish > bullish_max:
        balance_violation = bullish - bullish_max
    ic_violation = max(0.0, float(ic_min) - ic)
    direction_violation = max(0.0, float(direction_min) - float(metrics["Directional_Accuracy"]))
    hard_penalty = 0.0
    if hard_gate:
        hard_penalty = 10.0 * balance_violation + 5.0 * ic_violation + 2.0 * direction_violation

    return (
        float(metrics["Directional_Accuracy"])
        + 0.50 * ic
        + 0.25 * daily_ic
        - 0.50 * balance_violation
        - hard_penalty
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
    balance_weight: float,
    rank_weight: float,
    balance_temperature: float,
    rank_temperature: float,
    balanced_sampler: bool,
    date_grouped_batches: bool,
    min_date_batch_size: int,
    dates_per_batch: int,
    bullish_min: float,
    bullish_max: float,
    ic_min: float,
    direction_min: float,
    hard_gate: bool,
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
    sampler = _balanced_sampler(train_ds) if balanced_sampler else None
    loader_kwargs = {
        "num_workers": int(num_workers),
        "pin_memory": pin,
    }
    if int(num_workers) > 0:
        loader_kwargs["persistent_workers"] = True
    if balanced_sampler and date_grouped_batches:
        raise ValueError("--balanced-sampler and --date-grouped-batches are mutually exclusive.")
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
            f"dates_per_batch={int(dates_per_batch)} "
            f"min_date_batch_size={int(min_date_batch_size)}"
        )
    else:
        train_loader = DataLoader(
            train_ds,
            batch_size=batch_size,
            shuffle=sampler is None,
            sampler=sampler,
            drop_last=True,
            **loader_kwargs,
        )
    val_loader = DataLoader(val_ds, batch_size=1024, shuffle=False, **loader_kwargs)

    model = TCNForecaster(n_features=len(feature_cols), hidden=cfg.hidden, dropout=cfg.dropout).to(device)
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
        f"signreg_seed{seed}_cw{str(corr_weight).replace('.', 'p')}"
        f"_bw{str(balance_weight).replace('.', 'p')}"
        f"_rw{str(rank_weight).replace('.', 'p')}"
        f"_nw{str(nll_weight).replace('.', 'p')}"
    )
    if balanced_sampler:
        variant = f"{variant}_bs"
    if date_grouped_batches:
        variant = f"{variant}_dgb"
    model_path = EXPERIMENT_DIR / f"dl_{variant}.pt"
    scaler_path = EXPERIMENT_DIR / f"dl_{variant}_scaler.json"
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)

    best = {"score": -float("inf"), "state": None, "metrics": None}
    for epoch in range(1, epochs + 1):
        model.train()
        train_losses = []
        for xb, yb, _, date_ns in train_loader:
            xb = xb.to(device, non_blocking=pin)
            yb = yb.to(device, non_blocking=pin)
            date_ns = date_ns.to(device, non_blocking=pin)
            opt.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=use_amp):
                mu, log_sigma = model(xb)
            mu_loss = mu.float()
            yb_loss = yb.float()
            loss = float(nll_weight) * gaussian_nll(mu_loss, log_sigma.float(), yb_loss)
            if corr_weight > 0:
                corr_loss = (
                    _grouped_aux_loss(mu_loss, yb_loss, date_ns, "corr", rank_temperature, min_date_batch_size)
                    if date_grouped_batches
                    else _pearson_corr_loss(mu_loss, yb_loss)
                )
                loss = loss + float(corr_weight) * corr_loss
            if balance_weight > 0:
                balance_loss = (
                    _grouped_aux_loss(mu_loss, yb_loss, date_ns, "balance", balance_temperature, min_date_batch_size)
                    if date_grouped_batches
                    else _sign_balance_loss(mu_loss, yb_loss, balance_temperature)
                )
                loss = loss + float(balance_weight) * balance_loss
            if rank_weight > 0:
                rank_loss = (
                    _grouped_aux_loss(mu_loss, yb_loss, date_ns, "rank", rank_temperature, min_date_batch_size)
                    if date_grouped_batches
                    else _pairwise_rank_loss(mu_loss, yb_loss, rank_temperature)
                )
                loss = loss + float(rank_weight) * rank_loss
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
        metrics, _, _ = _evaluate(model, val_loader, device, use_amp, pin)
        score = _selection_score(metrics, bullish_min, bullish_max, ic_min, direction_min, hard_gate)
        current_lr = float(opt.param_groups[0]["lr"])
        print(
            f"seed={seed} cw={corr_weight} bw={balance_weight} epoch={epoch} "
            f"rw={rank_weight} nw={nll_weight} "
            f"lr={current_lr:.6g} "
            f"train={np.mean(train_losses):.6f} val_nll={metrics['NLL']:.6f} "
            f"dir={metrics['Directional_Accuracy']:.4f} ic={metrics['IC_Spearman']:.4f} "
            f"daily_ic={metrics['Daily_IC_Mean']:.4f} bull={metrics['pct_bullish_pred']:.4f} "
            f"score={score:.4f}"
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
            "device": device,
            "amp": use_amp,
            "scheduler": scheduler_name,
            "lr": lr,
            "max_lr": max_lr,
            "corr_weight": corr_weight,
            "balance_weight": balance_weight,
            "rank_weight": rank_weight,
            "nll_weight": nll_weight,
            "balanced_sampler": balanced_sampler,
            "date_grouped_batches": date_grouped_batches,
            "min_date_batch_size": min_date_batch_size,
            "dates_per_batch": dates_per_batch,
            "hard_gate": hard_gate,
            "ic_min": ic_min,
            "direction_min": direction_min,
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

    metrics, _, _ = _evaluate(model, val_loader, device, use_amp, pin)
    return {
        "variant": variant,
        "seed": seed,
        "corr_weight": corr_weight,
        "balance_weight": balance_weight,
        "rank_weight": rank_weight,
        "nll_weight": nll_weight,
        "device": device,
        "amp": use_amp,
        "scheduler": scheduler_name,
        "lr": lr,
        "max_lr": max_lr,
        "num_workers": int(num_workers),
        "pin_memory": pin,
        "balanced_sampler": balanced_sampler,
        "date_grouped_batches": date_grouped_batches,
        "min_date_batch_size": min_date_batch_size,
        "dates_per_batch": dates_per_batch,
        "hard_gate": hard_gate,
        "ic_min": ic_min,
        "direction_min": direction_min,
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
    ap.add_argument("--corr-weights", default="0,0.05,0.1")
    ap.add_argument("--balance-weights", default="0,0.1,0.5")
    ap.add_argument("--rank-weights", default="0")
    ap.add_argument("--nll-weights", default="1.0")
    ap.add_argument("--balance-temperature", type=float, default=0.02)
    ap.add_argument("--rank-temperature", type=float, default=0.02)
    ap.add_argument("--balanced-sampler", action="store_true")
    ap.add_argument("--date-grouped-batches", action="store_true")
    ap.add_argument("--min-date-batch-size", type=int, default=2)
    ap.add_argument("--dates-per-batch", type=int, default=1)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--val-days", type=int, default=252)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--scheduler", choices=["cosine", "onecycle", "none"], default="cosine")
    ap.add_argument("--max-lr", type=float, default=None)
    ap.add_argument("--onecycle-pct-start", type=float, default=0.45)
    ap.add_argument("--onecycle-div-factor", type=float, default=10.0)
    ap.add_argument("--onecycle-final-div-factor", type=float, default=1000.0)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="cpu")
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument("--pin-memory", action="store_true")
    ap.add_argument("--cudnn-benchmark", action="store_true")
    ap.add_argument("--bullish-min", type=float, default=0.35)
    ap.add_argument("--bullish-max", type=float, default=0.75)
    ap.add_argument("--ic-min", type=float, default=0.0)
    ap.add_argument("--direction-min", type=float, default=0.5085)
    ap.add_argument("--hard-gate", action="store_true")
    ap.add_argument("--output", type=Path, default=OUT_PATH)
    ap.add_argument("--csv-output", type=Path, default=CSV_PATH)
    args = ap.parse_args()
    if args.cudnn_benchmark and torch.cuda.is_available():
        torch.backends.cudnn.benchmark = True

    extra_features = _parse_features(args.extra_features)
    results = []
    for seed in _parse_ints(args.seeds):
        for corr_weight in _parse_floats(args.corr_weights):
            for balance_weight in _parse_floats(args.balance_weights):
                for rank_weight in _parse_floats(args.rank_weights):
                    for nll_weight in _parse_floats(args.nll_weights):
                        print(
                            f"\n=== sign regularized seed={seed} corr={corr_weight} "
                            f"balance={balance_weight} rank={rank_weight} nll={nll_weight} ==="
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
                                balance_weight=float(balance_weight),
                                rank_weight=float(rank_weight),
                                balance_temperature=float(args.balance_temperature),
                                rank_temperature=float(args.rank_temperature),
                                balanced_sampler=bool(args.balanced_sampler),
                                date_grouped_batches=bool(args.date_grouped_batches),
                                min_date_batch_size=int(args.min_date_batch_size),
                                dates_per_batch=int(args.dates_per_batch),
                                bullish_min=float(args.bullish_min),
                                bullish_max=float(args.bullish_max),
                                ic_min=float(args.ic_min),
                                direction_min=float(args.direction_min),
                                hard_gate=bool(args.hard_gate),
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
                "hard_gate": bool(args.hard_gate),
                "ic_min": float(args.ic_min),
                "direction_min": float(args.direction_min),
                "bullish_min": float(args.bullish_min),
                "bullish_max": float(args.bullish_max),
                "results": results,
                "aggregate": aggregate,
            },
            f,
            indent=2,
        )

    print("\nTop results:")
    top = pd.DataFrame(flat_rows).sort_values(
        ["IC_Spearman", "Directional_Accuracy", "pct_bullish_pred"],
        ascending=[False, False, True],
    )
    print(
        top[
            [
                "variant",
                "MAE",
                "RMSE",
                "Directional_Accuracy",
                "IC_Spearman",
                "Daily_IC_Mean",
                "pct_bullish_pred",
            ]
        ].head(15)
    )
    print(f"\nSaved -> {args.output}")


if __name__ == "__main__":
    main()
