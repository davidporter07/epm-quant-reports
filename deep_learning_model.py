"""deep_learning_model.py

A real PyTorch forecasting model for 21-trading-day forward returns.

This version is **memory-safe** for large universes (e.g., S&P 500).
It avoids prebuilding every sequence window in RAM.

Pipeline integration
--------------------
- Train on:  data/training_panel.parquet
- Infer to:  data/dl_forecasts.csv
- Upsert into data/features.parquet (DL Forecast (%) + CI bounds)

Modes
-----
train   : trains a TCN model (Temporal Convolution Network)
infer   : loads a trained model + scaler and produces live forecasts
backtest: evaluates on a held-out time window and writes metrics

Examples
--------
# 1) Build a panel
python build_training_dataset.py --universe sp500 --years 8

# 2) Train (CPU)
python deep_learning_model.py train --epochs 8 --seq-len 60 --batch-size 512

# 3) Train (GPU)
python deep_learning_model.py train --device cuda --epochs 12 --seq-len 60 --batch-size 1024

# 4) Infer (MAG7)
python deep_learning_model.py infer --tickers AAPL,MSFT,AMZN,NVDA,GOOG,META,TSLA

# 5) Backtest last 252 trading days (requires trained model)
python deep_learning_model.py backtest --test-days 252
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd

import torch
from torch import nn
from torch.utils.data import Dataset, DataLoader

from data_utils import load_features, save_features, upsert_features
from dl_feature_gate import get_approved_features, FALLBACK_FEATURES


MAG7_DEFAULT = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]

PANEL_PATH_DEFAULT = Path("data") / "training_panel.parquet"
MODEL_DIR = Path("models")
MODEL_PATH_DEFAULT = MODEL_DIR / "dl_tcn.pt"
SCALER_PATH_DEFAULT = MODEL_DIR / "dl_scaler.json"
FORECASTS_CSV_DEFAULT = Path("data") / "dl_forecasts.csv"

# --------------------------
# Dataset
# --------------------------

# IMPORTANT: Do not add features here directly.
# Features must pass the promotion pipeline (feature_tester.py + feature_promoter.py)
# before entering DL training. The approved list is managed by feature_registry.py
# and read at runtime by dl_feature_gate.get_approved_features().
#
# The fallback below is used only if feature_store/approved/dl_approved_features.json
# does not exist (e.g., first run before registry initialization).
FEATURE_COLS_DEFAULT = get_approved_features()

TARGET_COL = "Target_Forward_21D"


def read_panel(path: Path) -> pd.DataFrame:
    """Read a training panel from parquet when possible; otherwise fall back to CSV."""
    path = Path(path)
    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception:
            pass

    csv_path = path.with_suffix(".csv")
    if csv_path.exists():
        return pd.read_csv(csv_path)

    if path.suffix.lower() == ".csv" and path.exists():
        return pd.read_csv(path)

    raise FileNotFoundError(f"Panel file not found: {path} (or {csv_path})")


def _ensure_panel_schema(panel: pd.DataFrame) -> pd.DataFrame:
    required = {"Date", "Ticker", "Close", TARGET_COL}
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"Panel file missing required columns: {sorted(missing)}")

    panel = panel.copy()
    panel["Date"] = pd.to_datetime(panel["Date"], errors="coerce")
    panel = panel.dropna(subset=["Date"]).copy()
    panel["Ticker"] = panel["Ticker"].astype(str).str.upper()
    panel = panel.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    return panel


def fit_scaler(panel_train: pd.DataFrame, feature_cols: List[str]) -> Dict[str, Dict[str, float]]:
    stats: Dict[str, Dict[str, float]] = {}
    for c in feature_cols:
        x = pd.to_numeric(panel_train[c], errors="coerce")
        mu = float(np.nanmean(x))
        sd = float(np.nanstd(x))
        if not np.isfinite(sd) or sd < 1e-12:
            sd = 1.0
        stats[c] = {"mean": mu, "std": sd}
    return stats


def apply_scaler(panel: pd.DataFrame, scaler: Dict[str, Dict[str, float]], feature_cols: List[str]) -> np.ndarray:
    """Returns scaled float32 numpy array with shape (T, F)."""
    cols = []
    for c in feature_cols:
        mu = scaler[c]["mean"]
        sd = scaler[c]["std"]
        v = pd.to_numeric(panel[c], errors="coerce").to_numpy(dtype=np.float32)
        cols.append((v - mu) / sd)
    return np.stack(cols, axis=1)


def _rolling_all_true(mask: np.ndarray, window: int) -> np.ndarray:
    """Given a boolean mask of length T, returns boolean mask of length T
    where out[i] is True if mask[i-window+1:i+1].all() and i>=window-1.

    Implemented with convolution to avoid Python loops.
    """
    mask_i = mask.astype(np.int16)
    kernel = np.ones(window, dtype=np.int16)
    sums = np.convolve(mask_i, kernel, mode="valid")
    ok_end = sums == window
    # pad to length T
    out = np.zeros_like(mask, dtype=bool)
    out[window - 1 :] = ok_end
    return out


class PanelSequenceDataset(Dataset):
    """Memory-efficient sequence dataset.

    Stores per-ticker arrays once and keeps a list of sample pointers.
    Does NOT store every window in RAM.
    """

    def __init__(
        self,
        panel: pd.DataFrame,
        scaler: Dict[str, Dict[str, float]],
        feature_cols: List[str],
        seq_len: int,
        date_min: pd.Timestamp | None = None,
        date_max: pd.Timestamp | None = None,
        max_samples: int | None = None,
        seed: int = 42,
    ):
        self.feature_cols = feature_cols
        self.seq_len = int(seq_len)

        panel = _ensure_panel_schema(panel)
        if date_min is not None:
            panel = panel[panel["Date"] >= date_min]
        if date_max is not None:
            panel = panel[panel["Date"] <= date_max]

        self._tickers: List[str] = []
        self._X: List[np.ndarray] = []
        self._y: List[np.ndarray] = []
        self._dates_ns: List[np.ndarray] = []

        # (ticker_idx, end_index)
        self._samples: np.ndarray
        sample_pairs: List[Tuple[int, int]] = []

        for tkr_idx, (tkr, g) in enumerate(panel.groupby("Ticker", sort=False)):
            g = g.sort_values("Date")
            if len(g) < self.seq_len + 5:
                continue

            y = pd.to_numeric(g[TARGET_COL], errors="coerce").to_numpy(dtype=np.float32)
            X = apply_scaler(g, scaler, feature_cols)  # (T, F)
            dates_ns = g["Date"].astype("datetime64[ns]").to_numpy().astype(np.int64)

            # Row-level validity: all finite (no NaN/inf)
            row_ok = np.isfinite(X).all(axis=1)
            y_ok = np.isfinite(y)
            win_ok = _rolling_all_true(row_ok, self.seq_len)
            end_ok = win_ok & y_ok

            end_indices = np.where(end_ok)[0]
            if len(end_indices) == 0:
                continue

            self._tickers.append(tkr)
            self._X.append(X.astype(np.float32, copy=False))
            self._y.append(y.astype(np.float32, copy=False))
            self._dates_ns.append(dates_ns)

            # Map to local ticker index in the stored lists
            stored_idx = len(self._tickers) - 1
            sample_pairs.extend([(stored_idx, int(i)) for i in end_indices])

        if len(sample_pairs) == 0:
            raise RuntimeError(
                "No training samples available. Your panel likely needs more history or more tickers. "
                "Try rebuilding it with more years/universe."
            )

        samples = np.array(sample_pairs, dtype=np.int32)

        if max_samples is not None and max_samples > 0 and len(samples) > max_samples:
            rng = np.random.default_rng(seed)
            idx = rng.choice(len(samples), size=int(max_samples), replace=False)
            samples = samples[idx]

        self._samples = samples

    def __len__(self) -> int:
        return int(self._samples.shape[0])

    def __getitem__(self, idx: int):
        tkr_idx, end_i = self._samples[idx]
        X = self._X[tkr_idx]
        y = self._y[tkr_idx]
        dates_ns = self._dates_ns[tkr_idx]

        start_i = int(end_i) - self.seq_len + 1
        window = X[start_i : int(end_i) + 1]

        return (
            torch.from_numpy(window),
            torch.tensor([float(y[int(end_i)])], dtype=torch.float32),
            self._tickers[int(tkr_idx)],
            int(dates_ns[int(end_i)]),
        )


# --------------------------
# Model: TCN
# --------------------------


class FeatureGate(nn.Module):
    """Learnable per-feature importance gate applied before the TCN.

    Each feature gets an independent sigmoid-gated weight in [0, 1].
    Over many training runs with warm-start, these weights converge toward
    the features that are genuinely predictive, giving the model a built-in
    sense of 'which market signals matter most.'
    """

    def __init__(self, n_features: int):
        super().__init__()
        self.log_weights = nn.Parameter(torch.zeros(n_features))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, F, T)
        w = torch.sigmoid(self.log_weights)  # (F,) in [0, 1]
        return x * w.unsqueeze(0).unsqueeze(-1)

    def get_importances(self, feature_cols: List[str]) -> pd.DataFrame:
        w = torch.sigmoid(self.log_weights).detach().cpu().numpy()
        return (
            pd.DataFrame({"Feature": feature_cols, "Importance": w})
            .sort_values("Importance", ascending=False)
            .reset_index(drop=True)
        )


class TemporalAttentionPool(nn.Module):
    """Replaces naive global-average-pooling with a learned attention pool.

    A small query network scores each of the seq_len time steps, so the model
    learns which days in the look-back window are most predictive rather than
    treating every day equally.
    """

    def __init__(self, hidden: int):
        super().__init__()
        self.query = nn.Linear(hidden, 1, bias=False)

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        # h: (B, hidden, T)
        h_t = h.transpose(1, 2)          # (B, T, hidden)
        scores = self.query(h_t).squeeze(-1)  # (B, T)
        weights = torch.softmax(scores, dim=-1)  # (B, T)
        return (h_t * weights.unsqueeze(-1)).sum(dim=1)  # (B, hidden)


class TCNBlock(nn.Module):
    def __init__(self, in_ch: int, out_ch: int, kernel_size: int, dilation: int, dropout: float):
        super().__init__()
        padding = (kernel_size - 1) * dilation
        self.conv1 = nn.Conv1d(in_ch, out_ch, kernel_size, padding=padding, dilation=dilation)
        self.act1 = nn.GELU()
        self.drop1 = nn.Dropout(dropout)
        self.conv2 = nn.Conv1d(out_ch, out_ch, kernel_size, padding=padding, dilation=dilation)
        self.act2 = nn.GELU()
        self.drop2 = nn.Dropout(dropout)
        self.downsample = nn.Conv1d(in_ch, out_ch, 1) if in_ch != out_ch else None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.conv1(x)
        out = out[..., : x.shape[-1]]
        out = self.act1(out)
        out = self.drop1(out)

        out = self.conv2(out)
        out = out[..., : x.shape[-1]]
        out = self.act2(out)
        out = self.drop2(out)

        res = x if self.downsample is None else self.downsample(x)
        return out + res


class TCNForecaster(nn.Module):
    def __init__(self, n_features: int, hidden: int = 64, dropout: float = 0.10):
        super().__init__()
        self.n_features = int(n_features)
        self.hidden = int(hidden)
        self.dropout = float(dropout)

        # Learns which features matter most (persists across warm-start runs)
        self.feature_gate = FeatureGate(self.n_features)
        self.in_proj = nn.Conv1d(self.n_features, self.hidden, kernel_size=1)
        self.blocks = nn.Sequential(
            TCNBlock(self.hidden, self.hidden, kernel_size=3, dilation=1, dropout=self.dropout),
            TCNBlock(self.hidden, self.hidden, kernel_size=3, dilation=2, dropout=self.dropout),
            TCNBlock(self.hidden, self.hidden, kernel_size=3, dilation=4, dropout=self.dropout),
            TCNBlock(self.hidden, self.hidden, kernel_size=3, dilation=8, dropout=self.dropout),
        )
        # Learns which days in the look-back window are most predictive
        self.temporal_pool = TemporalAttentionPool(self.hidden)
        self.norm = nn.LayerNorm(self.hidden)
        self.head = nn.Sequential(
            nn.Linear(self.hidden, self.hidden),
            nn.GELU(),
            nn.Dropout(self.dropout),
            nn.Linear(self.hidden, 2),  # mu, log_sigma
        )

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        # x: (B, T, F)
        x = x.transpose(1, 2)        # (B, F, T)
        x = self.feature_gate(x)     # gate by learned feature importance
        h = self.in_proj(x)
        h = self.blocks(h)
        h = self.temporal_pool(h)    # attention-weighted pool over time steps
        h = self.norm(h)
        out = self.head(h)
        mu = out[:, 0:1]
        log_sigma = out[:, 1:2].clamp(-6.0, 3.0)
        return mu, log_sigma


def gaussian_nll(mu: torch.Tensor, log_sigma: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    inv_var = torch.exp(-2.0 * log_sigma)
    return torch.mean(log_sigma + 0.5 * (y - mu) ** 2 * inv_var)


def directional_bce(
    mu: torch.Tensor,
    y: torch.Tensor,
    temperature: float = 0.02,
    neutral_threshold: float = 0.0,
) -> torch.Tensor:
    """Binary direction loss, optionally ignoring small realized moves as noise."""
    if neutral_threshold > 0:
        mask = torch.abs(y) >= float(neutral_threshold)
        if not torch.any(mask):
            return mu.sum() * 0.0
        mu = mu[mask]
        y = y[mask]
    target = (y > 0).to(dtype=mu.dtype)
    temp = max(float(temperature), 1e-6)
    return nn.functional.binary_cross_entropy_with_logits(mu / temp, target)


# --------------------------
# Train / Backtest / Infer
# --------------------------


@dataclass
class TrainConfig:
    seq_len: int = 60
    batch_size: int = 512
    epochs: int = 10
    lr: float = 1e-3
    hidden: int = 64
    dropout: float = 0.10
    val_days: int = 252
    patience: int = 3
    max_train_samples: int | None = None
    max_val_samples: int | None = None
    num_workers: int = 0


def time_split(panel: pd.DataFrame, val_days: int) -> Tuple[pd.Timestamp, pd.Timestamp]:
    dates = pd.to_datetime(panel["Date"]).drop_duplicates().sort_values()
    if len(dates) < val_days + 5:
        split_idx = int(len(dates) * 0.8)
    else:
        split_idx = max(0, len(dates) - val_days)
    cutoff = dates.iloc[split_idx]
    return cutoff, dates.iloc[-1]


def _load_compatible_warm_start(model: nn.Module, state_dict: dict) -> tuple[list[str], list[str]]:
    target = model.state_dict()
    loaded: list[str] = []
    skipped: list[str] = []

    for key, val in state_dict.items():
        if key not in target:
            skipped.append(key)
            continue

        if target[key].shape == val.shape:
            target[key] = val.clone()
            loaded.append(key)
            continue

        if key == "feature_gate.log_weights" and target[key].ndim == 1 and val.ndim == 1:
            n = min(target[key].shape[0], val.shape[0])
            target[key][:n] = val[:n].clone()
            loaded.append(f"{key}[0:{n}]")
            continue

        if key == "in_proj.weight" and target[key].ndim == 3 and val.ndim == 3:
            if target[key].shape[0] == val.shape[0] and target[key].shape[2] == val.shape[2]:
                n = min(target[key].shape[1], val.shape[1])
                target[key][:, :n, :] = val[:, :n, :].clone()
                loaded.append(f"{key}[:,0:{n},:]")
                continue

        skipped.append(key)

    model.load_state_dict(target)
    return loaded, skipped


def train_model(
    panel_path: Path,
    model_path: Path,
    scaler_path: Path,
    feature_cols: List[str],
    cfg: TrainConfig,
    device: str,
    warm_start: bool = True,
    direction_weight: float = 0.0,
    direction_temperature: float = 0.02,
    direction_neutral_threshold: float = 0.0,
    selection_metric: str = "loss",
) -> None:
    panel = _ensure_panel_schema(read_panel(panel_path))
    labeled = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    if labeled.empty:
        raise RuntimeError(f"No labeled training rows found in {panel_path}")
    panel = labeled

    cutoff, _ = time_split(panel, cfg.val_days)
    train_panel = panel[panel["Date"] < cutoff]
    val_panel = panel[panel["Date"] >= cutoff]

    scaler = fit_scaler(train_panel, feature_cols)
    model_path.parent.mkdir(parents=True, exist_ok=True)

    # Save scaler + config used
    with open(scaler_path, "w", encoding="utf-8") as f:
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

    train_ds = PanelSequenceDataset(
        train_panel,
        scaler,
        feature_cols,
        cfg.seq_len,
        max_samples=cfg.max_train_samples,
        seed=42,
    )
    val_ds = PanelSequenceDataset(
        val_panel,
        scaler,
        feature_cols,
        cfg.seq_len,
        max_samples=cfg.max_val_samples,
        seed=123,
    )

    pin = True if device == "cuda" else False
    train_loader = DataLoader(
        train_ds,
        batch_size=cfg.batch_size,
        shuffle=True,
        drop_last=True,
        num_workers=cfg.num_workers,
        pin_memory=pin,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=cfg.batch_size,
        shuffle=False,
        num_workers=cfg.num_workers,
        pin_memory=pin,
    )

    model = TCNForecaster(n_features=len(feature_cols), hidden=cfg.hidden, dropout=cfg.dropout).to(device)

    # Warm-start: if a checkpoint exists, always load it so each run builds on
    # prior knowledge rather than starting over.  Pass warm_start=False (via
    # --from-scratch on the CLI) only when you intentionally want a full reset.
    _base_lr = cfg.lr
    if warm_start and model_path.exists():
        try:
            ckpt = torch.load(model_path, map_location=device, weights_only=True)
            loaded, skipped = _load_compatible_warm_start(model, ckpt["state_dict"])
            print(f" Warm-start: loaded {len(loaded)} tensors from {model_path}")
            if skipped:
                print(f" Warm-start: skipped incompatible tensors: {skipped}")
            _base_lr = cfg.lr * 0.2  # fine-tune with a lower learning rate
        except Exception as e:
            print(f"  Warm-start failed ({e}). Training from scratch.")
    elif warm_start and not model_path.exists():
        print("  No existing checkpoint found  training from scratch.")

    opt = torch.optim.AdamW(model.parameters(), lr=_base_lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        opt, T_max=cfg.epochs, eta_min=_base_lr * 0.05
    )

    best_val = float("inf")
    best_score = -float("inf")
    bad_epochs = 0

    for epoch in range(1, cfg.epochs + 1):
        model.train()
        train_losses = []
        for xb, yb, _, _ in train_loader:
            xb = xb.to(device, non_blocking=pin)
            yb = yb.to(device, non_blocking=pin)
            opt.zero_grad(set_to_none=True)
            mu, log_sigma = model(xb)
            loss = gaussian_nll(mu, log_sigma, yb)
            if direction_weight > 0:
                loss = loss + float(direction_weight) * directional_bce(
                    mu, yb, direction_temperature, direction_neutral_threshold
                )
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            train_losses.append(loss.item())

        model.eval()
        val_losses = []
        val_preds = []
        val_actuals = []
        with torch.no_grad():
            for xb, yb, _, _ in val_loader:
                xb = xb.to(device, non_blocking=pin)
                yb = yb.to(device, non_blocking=pin)
                mu, log_sigma = model(xb)
                loss = gaussian_nll(mu, log_sigma, yb)
                if direction_weight > 0:
                    loss = loss + float(direction_weight) * directional_bce(
                        mu, yb, direction_temperature, direction_neutral_threshold
                    )
                val_losses.append(loss.item())
                val_preds.append(mu.detach().cpu().numpy().ravel())
                val_actuals.append(yb.detach().cpu().numpy().ravel())

        scheduler.step()

        tr = float(np.mean(train_losses)) if train_losses else float("nan")
        va = float(np.mean(val_losses)) if val_losses else float("nan")
        val_dir = float("nan")
        if val_preds and val_actuals:
            vp = np.concatenate(val_preds)
            vy = np.concatenate(val_actuals)
            val_dir = float(np.mean(np.sign(vp) == np.sign(vy)))

        print(
            f" Epoch {epoch:02d} | train nll={tr:.6f} | val nll={va:.6f} "
            f"| val dir={val_dir:.4f} | lr={scheduler.get_last_lr()[0]:.2e}"
        )

        if selection_metric == "directional":
            score = val_dir
            improved = score > best_score + 1e-5
        elif selection_metric == "composite":
            score = -va + val_dir
            improved = score > best_score + 1e-5
        else:
            score = -va
            improved = va < best_val - 1e-5

        if improved:
            best_val = va
            best_score = score
            bad_epochs = 0
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feature_cols": feature_cols,
                    "seq_len": cfg.seq_len,
                    "hidden": cfg.hidden,
                    "dropout": cfg.dropout,
                    "cutoff": str(cutoff.date()),
                    "best_val": best_val,
                    "selection_metric": selection_metric,
                    "best_score": best_score,
                    "best_val_directional_accuracy": val_dir,
                },
                model_path,
            )
            print(
                f" Saved best model -> {model_path} "
                f"(val nll={best_val:.6f}, score={best_score:.6f})"
            )
        else:
            bad_epochs += 1
            if bad_epochs >= cfg.patience:
                print(" Early stopping")
                break

    # After training, reload the best checkpoint and export learned feature importances.
    # These importances reflect what the model has cumulatively learned across all runs.
    if model_path.exists():
        try:
            best_ckpt = torch.load(model_path, map_location=device, weights_only=True)
            model.load_state_dict(best_ckpt["state_dict"])
            fi_df = model.feature_gate.get_importances(feature_cols)
            fi_path = model_path.parent / "dl_feature_importance.csv"
            fi_df.to_csv(fi_path, index=False)
            print(f" Feature importances saved -> {fi_path}")
            top = fi_df.head(5)["Feature"].tolist()
            print(f"   Top features: {', '.join(top)}")
        except Exception as e:
            print(f"  Could not export feature importances: {e}")


def load_model_and_scaler(model_path: Path, scaler_path: Path, device: str):
    ckpt = torch.load(model_path, map_location=device)
    with open(scaler_path, "r", encoding="utf-8") as f:
        scaler_blob = json.load(f)

    feature_cols = scaler_blob["feature_cols"]
    scaler = scaler_blob["scaler"]
    seq_len = int(scaler_blob.get("seq_len", ckpt.get("seq_len", 60)))
    hidden = int(scaler_blob.get("hidden", ckpt.get("hidden", 64)))
    dropout = float(scaler_blob.get("dropout", ckpt.get("dropout", 0.10)))

    model = TCNForecaster(n_features=len(feature_cols), hidden=hidden, dropout=dropout).to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model, scaler, feature_cols, seq_len


@torch.no_grad()
def infer_live(
    panel_path: Path,
    model_path: Path,
    scaler_path: Path,
    tickers: List[str],
    out_csv: Path,
    device: str,
) -> pd.DataFrame:
    if (not panel_path.exists()) and (not panel_path.with_suffix(".csv").exists()):
        raise FileNotFoundError(f"{panel_path} not found. First run: python build_training_dataset.py ...")

    panel = _ensure_panel_schema(read_panel(panel_path))
    model, scaler, feature_cols, seq_len = load_model_and_scaler(model_path, scaler_path, device)

    tickers = [str(t).strip().upper().replace(".", "-") for t in tickers if str(t).strip()]

    rows = []
    for t in tickers:
        g = panel[panel["Ticker"] == t].sort_values("Date")
        if len(g) < seq_len:
            print(f" {t}: not enough history in panel ({len(g)}/{seq_len}). Skipping.")
            continue

        tail = g.iloc[-seq_len:].copy()
        X = apply_scaler(tail, scaler, feature_cols)
        if not np.isfinite(X).all():
            print(f" {t}: NaNs/infs in features window. Skipping.")
            continue

        xb = torch.from_numpy(X).unsqueeze(0).to(device)
        mu, log_sigma = model(xb)
        mu = float(mu.cpu().numpy().ravel()[0])
        sigma = float(np.exp(log_sigma.cpu().numpy().ravel()[0]))

        z = 1.96
        lo = mu - z * sigma
        hi = mu + z * sigma

        asof = pd.Timestamp(tail["Date"].iloc[-1]).normalize()
        rows.append(
            {
                "Ticker": t,
                "DL Forecast (%)": round(mu * 100, 4),
                "DL_CI_Lower": round(lo * 100, 4),
                "DL_CI_Upper": round(hi * 100, 4),
                "Date": asof,
            }
        )

    out = pd.DataFrame(rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)
    print(f" DL forecasts saved -> {out_csv}")

    # Upsert into features.parquet
    if not out.empty:
        base = load_features()
        upd = out[["Ticker", "DL Forecast (%)", "DL_CI_Lower", "DL_CI_Upper"]].copy()
        base = upsert_features(base, upd, date_value=pd.Timestamp.today())
        save_features(base)
        print(" Updated features.parquet with DL outputs (upsert).")

    return out


def backtest(
    panel_path: Path,
    model_path: Path,
    scaler_path: Path,
    test_days: int,
    device: str,
    out_csv: Path,
) -> None:
    panel = _ensure_panel_schema(read_panel(panel_path))
    panel = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    if panel.empty:
        raise RuntimeError(f"No labeled backtest rows found in {panel_path}")
    model, scaler, feature_cols, seq_len = load_model_and_scaler(model_path, scaler_path, device)

    dates = pd.to_datetime(panel["Date"]).drop_duplicates().sort_values()
    if len(dates) < test_days + 10:
        test_days = max(5, int(len(dates) * 0.2))

    cutoff = dates.iloc[-test_days]
    test_panel = panel[panel["Date"] >= cutoff]

    ds = PanelSequenceDataset(test_panel, scaler, feature_cols, seq_len)
    loader = DataLoader(ds, batch_size=1024, shuffle=False)

    preds = []
    ys = []

    with torch.no_grad():
        for xb, yb, _, _ in loader:
            xb = xb.to(device)
            mu, _ = model(xb)
            preds.append(mu.cpu().numpy().ravel())
            ys.append(yb.cpu().numpy().ravel())

    p = np.concatenate(preds)
    y = np.concatenate(ys)

    mae = float(np.mean(np.abs(y - p)))
    rmse = float(np.sqrt(np.mean((y - p) ** 2)))
    dir_acc = float(np.mean((np.sign(y) == np.sign(p)).astype(float)))
    corr = float(np.corrcoef(p, y)[0, 1]) if len(p) > 2 and np.std(p) > 1e-12 and np.std(y) > 1e-12 else float("nan")
    ic = float(pd.Series(p).rank().corr(pd.Series(y).rank())) if len(p) > 2 else float("nan")

    summary = pd.DataFrame(
        {
            "Metric": ["MAE", "RMSE", "Directional_Accuracy", "Correlation", "IC_Spearman", "N"],
            "Value": [mae, rmse, dir_acc, corr, ic, len(y)],
            "Test_Start": [str(cutoff.date())] * 6,
        }
    )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out_csv, index=False)
    print(f" DL backtest summary saved -> {out_csv}")
    print(summary)


def parse_args():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    tr = sub.add_parser("train")
    tr.add_argument("--panel", type=str, default=str(PANEL_PATH_DEFAULT))
    tr.add_argument("--model", type=str, default=str(MODEL_PATH_DEFAULT))
    tr.add_argument("--scaler", type=str, default=str(SCALER_PATH_DEFAULT))
    tr.add_argument("--seq-len", type=int, default=60)
    tr.add_argument("--epochs", type=int, default=10)
    tr.add_argument("--batch-size", type=int, default=512)
    tr.add_argument("--lr", type=float, default=1e-3)
    tr.add_argument("--hidden", type=int, default=64)
    tr.add_argument("--dropout", type=float, default=0.10)
    tr.add_argument("--val-days", type=int, default=252)
    tr.add_argument("--patience", type=int, default=3)
    tr.add_argument("--max-train-samples", type=int, default=0, help="Optional subsample for quick tests")
    tr.add_argument("--max-val-samples", type=int, default=0, help="Optional subsample for quick tests")
    tr.add_argument("--num-workers", type=int, default=0)
    tr.add_argument(
        "--direction-weight",
        type=float,
        default=0.0,
        help="Optional BCE direction-loss weight. 0.0 preserves the original Gaussian NLL objective.",
    )
    tr.add_argument(
        "--direction-temperature",
        type=float,
        default=0.02,
        help="Return scale used to convert predicted return into a direction logit.",
    )
    tr.add_argument(
        "--direction-neutral-threshold",
        type=float,
        default=0.0,
        help="Ignore examples with abs(realized 21D return) below this threshold for direction loss.",
    )
    tr.add_argument(
        "--from-scratch",
        action="store_true",
        default=False,
        help=(
            "Ignore any existing checkpoint and train from random initialization. "
            "Use this only when intentionally resetting the model (e.g. after a major "
            "architecture change or to establish a clean baseline). "
            "By default, training always warm-starts from the existing checkpoint."
        ),
    )

    inf = sub.add_parser("infer")
    inf.add_argument("--panel", type=str, default=str(PANEL_PATH_DEFAULT))
    inf.add_argument("--model", type=str, default=str(MODEL_PATH_DEFAULT))
    inf.add_argument("--scaler", type=str, default=str(SCALER_PATH_DEFAULT))
    inf.add_argument("--out", type=str, default=str(FORECASTS_CSV_DEFAULT))
    inf.add_argument("--tickers", type=str, default=",".join(MAG7_DEFAULT))

    bt = sub.add_parser("backtest")
    bt.add_argument("--panel", type=str, default=str(PANEL_PATH_DEFAULT))
    bt.add_argument("--model", type=str, default=str(MODEL_PATH_DEFAULT))
    bt.add_argument("--scaler", type=str, default=str(SCALER_PATH_DEFAULT))
    bt.add_argument("--test-days", type=int, default=252)
    bt.add_argument("--out", type=str, default=str(Path("data") / "dl_backtest_summary.csv"))

    ap.add_argument("--device", type=str, default="cpu", choices=["cpu", "cuda"], help="cuda requires a GPU")
    return ap.parse_args()


def main():
    args = parse_args()

    device = args.device
    if device == "cuda" and not torch.cuda.is_available():
        print(" CUDA requested but not available. Falling back to CPU.")
        device = "cpu"

    if device == "cuda":
        torch.backends.cudnn.benchmark = True

    if args.cmd == "train":
        cfg = TrainConfig(
            seq_len=args.seq_len,
            batch_size=args.batch_size,
            epochs=args.epochs,
            lr=args.lr,
            hidden=args.hidden,
            dropout=args.dropout,
            val_days=args.val_days,
            patience=args.patience,
            max_train_samples=(None if args.max_train_samples <= 0 else int(args.max_train_samples)),
            max_val_samples=(None if args.max_val_samples <= 0 else int(args.max_val_samples)),
            num_workers=int(args.num_workers),
        )
        train_model(
            panel_path=Path(args.panel),
            model_path=Path(args.model),
            scaler_path=Path(args.scaler),
            feature_cols=FEATURE_COLS_DEFAULT,
            cfg=cfg,
            device=device,
            warm_start=not args.from_scratch,
            direction_weight=float(args.direction_weight),
            direction_temperature=float(args.direction_temperature),
            direction_neutral_threshold=float(args.direction_neutral_threshold),
        )

    elif args.cmd == "infer":
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        infer_live(
            panel_path=Path(args.panel),
            model_path=Path(args.model),
            scaler_path=Path(args.scaler),
            tickers=tickers,
            out_csv=Path(args.out),
            device=device,
        )

    elif args.cmd == "backtest":
        backtest(
            panel_path=Path(args.panel),
            model_path=Path(args.model),
            scaler_path=Path(args.scaler),
            test_days=int(args.test_days),
            device=device,
            out_csv=Path(args.out),
        )


if __name__ == "__main__":
    main()
