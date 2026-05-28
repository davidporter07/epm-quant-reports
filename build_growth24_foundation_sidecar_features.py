"""Build foundation-model sidecar features for the Growth24 DL panel.

The current implementation emits deterministic rolling time-series embedding
proxies and records whether TimesFM or Chronos packages are available. The
output can be merged into experiment panels while the external providers are
evaluated without blocking the existing shadow pipeline.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from deep_learning_model import _ensure_panel_schema, read_panel
from dl_growth24_shadow_paper import DEFAULT_PANEL

DEFAULT_OUTPUT = Path("data/experiment/growth24_foundation_sidecar_features.parquet")
DEFAULT_METADATA_OUTPUT = Path("data/experiment/growth24_foundation_sidecar_features_meta.json")


def _parse_windows(raw: str) -> list[int]:
    windows = [int(part.strip()) for part in str(raw).split(",") if part.strip()]
    if not windows:
        raise ValueError("At least one window is required.")
    return sorted(set(windows))


def _safe_skew(values: np.ndarray) -> float:
    clean = values[np.isfinite(values)]
    if clean.size < 3:
        return float("nan")
    centered = clean - clean.mean()
    std = clean.std()
    if std < 1e-12:
        return 0.0
    return float(np.mean((centered / std) ** 3))


def _safe_slope(values: np.ndarray) -> float:
    clean = values[np.isfinite(values)]
    if clean.size < 3:
        return float("nan")
    x = np.arange(clean.size, dtype=np.float64)
    y = np.log(np.maximum(clean.astype(np.float64), 1e-8))
    return float(np.polyfit(x, y, 1)[0])


def _safe_autocorr(values: np.ndarray) -> float:
    clean = values[np.isfinite(values)]
    if clean.size < 4:
        return float("nan")
    left = clean[:-1]
    right = clean[1:]
    if left.std() < 1e-12 or right.std() < 1e-12:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def _spectral_ratio(values: np.ndarray, low: int, high: int) -> float:
    clean = values[np.isfinite(values)]
    if clean.size < 8:
        return float("nan")
    centered = clean - clean.mean()
    spectrum = np.abs(np.fft.rfft(centered)) ** 2
    total = float(spectrum[1:].sum())
    if total <= 1e-12:
        return 0.0
    return float(spectrum[low:high].sum() / total)


def _rolling_apply(series: pd.Series, window: int, min_periods: int, func) -> pd.Series:
    return series.rolling(window, min_periods=min_periods).apply(lambda values: func(values), raw=True)


def _build_ticker_sidecar(g: pd.DataFrame, windows: list[int], min_periods: int) -> pd.DataFrame:
    out = g[["Date", "Ticker"]].copy()
    close = pd.to_numeric(g["Close"], errors="coerce")
    ret = close.pct_change()
    log_ret = np.log(close.clip(lower=1e-8)).diff()
    for window in windows:
        mp = min(int(window), max(2, int(min_periods)))
        prefix = f"foundation_proxy_w{window}"
        roll_ret = ret.rolling(window, min_periods=mp)
        roll_log = log_ret.rolling(window, min_periods=mp)
        out[f"{prefix}_ret_mean"] = roll_ret.mean()
        out[f"{prefix}_ret_std"] = roll_ret.std(ddof=0)
        out[f"{prefix}_ret_min"] = roll_ret.min()
        out[f"{prefix}_ret_max"] = roll_ret.max()
        out[f"{prefix}_ret_skew"] = _rolling_apply(ret, window, mp, _safe_skew)
        out[f"{prefix}_logret_sum"] = roll_log.sum()
        out[f"{prefix}_positive_rate"] = roll_ret.apply(lambda values: float(np.nanmean(values > 0.0)), raw=True)
        out[f"{prefix}_downside_std"] = roll_ret.apply(
            lambda values: float(np.nanstd(np.minimum(values, 0.0))),
            raw=True,
        )
        out[f"{prefix}_price_slope"] = _rolling_apply(close, window, mp, _safe_slope)
        out[f"{prefix}_ret_autocorr1"] = _rolling_apply(ret, window, mp, _safe_autocorr)
        out[f"{prefix}_spectral_low"] = _rolling_apply(ret, window, mp, lambda values: _spectral_ratio(values, 1, 3))
        out[f"{prefix}_spectral_mid"] = _rolling_apply(ret, window, mp, lambda values: _spectral_ratio(values, 3, 8))
        out[f"{prefix}_drawdown"] = close / close.rolling(window, min_periods=mp).max() - 1.0
        out[f"{prefix}_range_position"] = (
            close - close.rolling(window, min_periods=mp).min()
        ) / (close.rolling(window, min_periods=mp).max() - close.rolling(window, min_periods=mp).min())
    return out


def build_sidecar(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    panel = _ensure_panel_schema(read_panel(args.panel))
    if args.start_date:
        panel = panel[panel["Date"] >= pd.Timestamp(args.start_date)].copy()
    windows = _parse_windows(args.windows)

    pieces = []
    for _, g in panel.groupby("Ticker", sort=True):
        pieces.append(_build_ticker_sidecar(g.sort_values("Date"), windows, int(args.min_periods)))
    features = pd.concat(pieces, ignore_index=True)
    feature_cols = [col for col in features.columns if col not in {"Date", "Ticker"}]
    features[feature_cols] = features[feature_cols].replace([np.inf, -np.inf], np.nan).astype(np.float32)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(args.output, index=False)

    augmented_output = None
    if args.augmented_panel_output is not None:
        augmented = panel.merge(features, on=["Date", "Ticker"], how="left")
        args.augmented_panel_output.parent.mkdir(parents=True, exist_ok=True)
        augmented.to_parquet(args.augmented_panel_output, index=False)
        augmented_output = str(args.augmented_panel_output)

    metadata = {
        "status": "built",
        "mode": "deterministic_proxy_until_provider_installed",
        "panel": str(args.panel),
        "output": str(args.output),
        "augmented_panel_output": augmented_output,
        "rows": int(len(features)),
        "ticker_count": int(features["Ticker"].nunique()),
        "date_min": pd.Timestamp(features["Date"].min()).date().isoformat(),
        "date_max": pd.Timestamp(features["Date"].max()).date().isoformat(),
        "windows": windows,
        "feature_count": int(len(feature_cols)),
        "feature_columns": feature_cols,
        "provider_availability": {
            "timesfm": bool(importlib.util.find_spec("timesfm")),
            "chronos": bool(importlib.util.find_spec("chronos")),
            "chronos_forecasting": bool(importlib.util.find_spec("chronos_forecasting")),
        },
    }
    args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
    with args.metadata_output.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    return features, metadata


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Growth24 foundation sidecar features.")
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--windows", default="21,63,126")
    ap.add_argument("--min-periods", type=int, default=8)
    ap.add_argument("--start-date", default=None)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--metadata-output", type=Path, default=DEFAULT_METADATA_OUTPUT)
    ap.add_argument("--augmented-panel-output", type=Path, default=None)
    args = ap.parse_args()

    features, metadata = build_sidecar(args)
    print(f"Status: {metadata['status']}")
    print(f"Rows: {len(features)}")
    print(f"Feature count: {metadata['feature_count']}")
    print(f"Saved -> {args.output}")
    print(f"Saved metadata -> {args.metadata_output}")


if __name__ == "__main__":
    main()
