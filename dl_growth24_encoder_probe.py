"""Probe PatchTST-style and TFT-style encoders on the Growth24 DL panel.

The probe validates tensor shapes, feature compatibility, and forward-pass
stability before these encoders are promoted into a full training loop.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader

from deep_learning_model import (
    TARGET_COL,
    FeatureGate,
    PanelSequenceDataset,
    TrainConfig,
    _ensure_panel_schema,
    fit_scaler,
    read_panel,
)
from dl_directional_loss_experiment import _parse_features
from dl_growth24_shadow_paper import DEFAULT_GROWTH24_EXTRA_FEATURES, DEFAULT_PANEL
from dl_sign_regularized_experiment import _feature_cols, _resolve_device

DEFAULT_OUTPUT = Path("data/experiment/growth24_encoder_probe_summary.json")


class _RankProbeHeads(nn.Module):
    def __init__(self, hidden: int, dropout: float):
        super().__init__()
        self.return_head = nn.Sequential(
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, 2),
        )
        self.rank_head = nn.Sequential(
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, 1),
        )

    def forward(self, h: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        raw = self.return_head(h)
        mu = raw[:, 0:1]
        log_sigma = raw[:, 1:2].clamp(-6.0, 3.0)
        rank_score = self.rank_head(h)
        return mu, log_sigma, rank_score


class PatchTSTRankHeadProbe(nn.Module):
    """PatchTST-style encoder with rank and return heads."""

    def __init__(
        self,
        n_features: int,
        seq_len: int,
        patch_len: int = 12,
        hidden: int = 64,
        layers: int = 2,
        heads: int = 4,
        dropout: float = 0.10,
    ):
        super().__init__()
        self.n_features = int(n_features)
        self.seq_len = int(seq_len)
        self.patch_len = int(patch_len)
        self.patch_count = max(1, int(seq_len) // int(patch_len))
        self.feature_gate = FeatureGate(self.n_features)
        self.patch_proj = nn.Linear(self.patch_len * self.n_features, hidden)
        self.pos_embedding = nn.Parameter(torch.zeros(1, self.patch_count, hidden))
        layer = nn.TransformerEncoderLayer(
            d_model=hidden,
            nhead=heads,
            dim_feedforward=hidden * 4,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=layers)
        self.norm = nn.LayerNorm(hidden)
        self.heads = _RankProbeHeads(hidden, dropout)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        b, t, f = x.shape
        usable = self.patch_count * self.patch_len
        if t < usable:
            raise ValueError(f"Expected at least {usable} steps, received {t}.")
        x = x[:, -usable:, :]
        x = self.feature_gate(x.transpose(1, 2)).transpose(1, 2)
        patches = x.reshape(b, self.patch_count, self.patch_len * f)
        h = self.patch_proj(patches) + self.pos_embedding
        h = self.encoder(h)
        h = self.norm(h.mean(dim=1))
        return self.heads(h)


class GatedTemporalFusionRankHeadProbe(nn.Module):
    """Compact TFT-style encoder with feature gates, GRU context, and attention."""

    def __init__(self, n_features: int, hidden: int = 64, dropout: float = 0.10):
        super().__init__()
        self.feature_gate = FeatureGate(n_features)
        self.value_proj = nn.Sequential(
            nn.Linear(n_features, hidden),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.gru = nn.GRU(hidden, hidden, batch_first=True)
        self.temporal_score = nn.Linear(hidden, 1)
        self.context_gate = nn.Linear(hidden * 2, hidden)
        self.norm = nn.LayerNorm(hidden)
        self.heads = _RankProbeHeads(hidden, dropout)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        x = self.feature_gate(x.transpose(1, 2)).transpose(1, 2)
        values = self.value_proj(x)
        h, _ = self.gru(values)
        weights = torch.softmax(self.temporal_score(h).squeeze(-1), dim=1)
        context = torch.sum(h * weights.unsqueeze(-1), dim=1)
        last = h[:, -1, :]
        gate = torch.sigmoid(self.context_gate(torch.cat([last, context], dim=1)))
        fused = self.norm(gate * context + (1.0 - gate) * last)
        return self.heads(fused)


def _parameter_count(model: nn.Module) -> int:
    return int(sum(p.numel() for p in model.parameters()))


def _tensor_summary(tensor: torch.Tensor) -> dict[str, Any]:
    arr = tensor.detach().cpu().float().numpy().ravel()
    return {
        "shape": list(tensor.shape),
        "finite": bool(np.isfinite(arr).all()),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    panel = _ensure_panel_schema(read_panel(args.panel))
    if args.asof_date:
        panel = panel[panel["Date"] <= pd.Timestamp(args.asof_date)].copy()
    labeled = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    if labeled.empty:
        raise RuntimeError("No labeled rows available for encoder probe.")

    extra_features = _parse_features(args.extra_features)
    feature_cols = _feature_cols(args.panel, extra_features)
    scaler = fit_scaler(labeled, feature_cols)
    ds = PanelSequenceDataset(
        labeled,
        scaler,
        feature_cols,
        int(args.seq_len),
        max_samples=int(args.max_samples) if int(args.max_samples) > 0 else None,
    )
    loader = DataLoader(ds, batch_size=int(args.batch_size), shuffle=False)
    xb, yb, tickers, date_ns = next(iter(loader))
    device = _resolve_device(args.device)
    xb = xb.to(device)

    models: dict[str, nn.Module] = {
        "patchtst_rank_head_probe": PatchTSTRankHeadProbe(
            n_features=len(feature_cols),
            seq_len=int(args.seq_len),
            patch_len=int(args.patch_len),
            hidden=int(args.hidden),
            layers=int(args.layers),
            heads=int(args.heads),
            dropout=float(args.dropout),
        ).to(device),
        "gated_tft_rank_head_probe": GatedTemporalFusionRankHeadProbe(
            n_features=len(feature_cols),
            hidden=int(args.hidden),
            dropout=float(args.dropout),
        ).to(device),
    }

    model_summaries: dict[str, Any] = {}
    with torch.no_grad():
        for name, model in models.items():
            model.eval()
            mu, log_sigma, rank_score = model(xb)
            model_summaries[name] = {
                "parameters": _parameter_count(model),
                "mu": _tensor_summary(mu),
                "log_sigma": _tensor_summary(log_sigma),
                "rank_score": _tensor_summary(rank_score),
            }

    date_values = pd.to_datetime(np.asarray(date_ns), errors="coerce")
    summary = {
        "status": "probed",
        "panel": str(args.panel),
        "asof_date": args.asof_date,
        "feature_count": int(len(feature_cols)),
        "dataset_samples": int(len(ds)),
        "batch_size": int(xb.shape[0]),
        "seq_len": int(args.seq_len),
        "target_mean": float(yb.float().mean().item()),
        "target_std": float(yb.float().std(unbiased=False).item()),
        "batch_ticker_count": int(len(set(str(t) for t in tickers))),
        "batch_date_min": pd.Series(date_values).min().date().isoformat(),
        "batch_date_max": pd.Series(date_values).max().date().isoformat(),
        "models": model_summaries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe Growth24 alternative DL sequence encoders.")
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--extra-features", default=DEFAULT_GROWTH24_EXTRA_FEATURES)
    ap.add_argument("--asof-date", default=None)
    ap.add_argument("--seq-len", type=int, default=TrainConfig().seq_len)
    ap.add_argument("--patch-len", type=int, default=12)
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--heads", type=int, default=4)
    ap.add_argument("--dropout", type=float, default=0.10)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--max-samples", type=int, default=2048)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    summary = run_probe(args)
    print(f"Status: {summary['status']}")
    print(f"Feature count: {summary['feature_count']}")
    for name, model_summary in summary["models"].items():
        print(f"{name}: parameters={model_summary['parameters']} rank_finite={model_summary['rank_score']['finite']}")
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
