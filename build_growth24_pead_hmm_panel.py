"""Build a Growth24 research panel with PEAD and HMM regime features.

This is an offline research helper. It reads an existing Growth24 panel and
adds causal feature columns that can be passed to the historical blind DL loop.
It does not train models or modify the live daily pipeline.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import regime_detector


DEFAULT_INPUT = Path(
    "data/experiment/dl_research_panels/research_growth_24_price_earnings_av_sector_panel.parquet"
)
DEFAULT_OUTPUT = Path(
    "data/experiment/dl_research_panels/research_growth_24_price_earnings_av_sector_pead_hmm_panel.parquet"
)
DEFAULT_FEATURE_LIST = Path(
    "data/experiment/dl_research_panels/research_growth_24_pead_hmm_features.txt"
)

EXPECTED_HMM_LABELS = ("bull_quiet", "bear_quiet", "bull_volatile", "bear_stress")
STRESS_LABELS = set(regime_detector.STRESS_LABELS)

BASE_FEATURES = [
    "RSI_14",
    "Gap_MA20",
    "Gap_MA50",
    "Gap_MA200",
    "Volume",
    "Vol_21D",
    "Vol_63D",
    "momentum_3_1",
    "momentum_6_1",
    "momentum_12_1",
    "overnight_return_20d",
    "intraday_return_20d",
    "atr_percentile",
    "hv_percentile",
    "gap_5d_count",
    "earnings_surprise_last",
    "earnings_beat_rate_4q",
    "days_since_earnings",
    "earnings_abs_surprise",
    "earnings_surprise_x_gap_count",
    "post_earnings_window_active",
    "post_earnings_positive_drift_window",
    "post_earnings_negative_drift_window",
    "SectorRel_Ret_21D",
    "SectorRel_Vol_21D",
    "SectorRel_momentum_3_1",
    "SectorRel_momentum_6_1",
    "SectorRel_momentum_12_1",
    "Market_Stress_Regime",
    "Market_Drawdown_63D",
    "Market_Drawdown_252D",
]

PEAD_HMM_FEATURES = [
    "PEAD_Signal",
    "PEAD_Long",
    "PEAD_Short",
    "PEAD_Active",
    "PEAD_Surprise_Active",
    "PEAD_Days_Decay",
    "PEAD_Signal_x_Rel_Ret_21D",
    "PEAD_Signal_x_SectorRel_Ret_21D",
    "PEAD_Signal_x_Market_Stress",
    "HMM_Stress",
    "HMM_bull_quiet",
    "HMM_bear_quiet",
    "HMM_bull_volatile",
    "HMM_bear_stress",
    "HMM_Stress_x_PEAD_Signal",
    "HMM_Stress_x_Ret_21D",
    "HMM_Stress_x_Vol_21D",
]


def _numeric(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def add_pead_research_features(
    panel: pd.DataFrame,
    surprise_threshold: float = 0.03,
    window_days: int = 21,
) -> pd.DataFrame:
    """Add PEAD-style state features from already-causal earnings columns."""
    out = panel.copy()
    surprise = _numeric(out, "earnings_surprise_last", np.nan)
    if surprise.isna().all() and {"earnings_surprise_direction", "earnings_abs_surprise"}.issubset(out.columns):
        surprise = _numeric(out, "earnings_surprise_direction") * _numeric(out, "earnings_abs_surprise")
    surprise = surprise.fillna(0.0)

    abs_surprise = _numeric(out, "earnings_abs_surprise", np.nan).fillna(surprise.abs())
    pos_window = _numeric(out, "post_earnings_positive_drift_window") > 0
    neg_window = _numeric(out, "post_earnings_negative_drift_window") > 0
    strong = abs_surprise >= float(surprise_threshold)

    signal = pd.Series(0.0, index=out.index)
    signal.loc[pos_window & strong] = 1.0
    signal.loc[neg_window & strong] = -1.0

    out["PEAD_Signal"] = signal
    out["PEAD_Long"] = (signal > 0).astype(float)
    out["PEAD_Short"] = (signal < 0).astype(float)
    out["PEAD_Active"] = (signal != 0).astype(float)
    out["PEAD_Surprise_Active"] = surprise.where(signal != 0, 0.0)

    days_since = _numeric(out, "days_since_earnings", np.nan)
    decay = 1.0 - (days_since.clip(lower=0, upper=window_days) / float(window_days))
    out["PEAD_Days_Decay"] = decay.where(signal != 0, 0.0).fillna(0.0)

    out["PEAD_Signal_x_Rel_Ret_21D"] = signal * _numeric(out, "Rel_Ret_21D")
    out["PEAD_Signal_x_SectorRel_Ret_21D"] = signal * _numeric(out, "SectorRel_Ret_21D")
    out["PEAD_Signal_x_Market_Stress"] = signal * _numeric(out, "Market_Stress_Regime")
    return out


def add_hmm_regime_features(
    panel: pd.DataFrame,
    require_hmm: bool = False,
) -> pd.DataFrame:
    """Join date-level HMM regime labels and numeric stress indicators."""
    out = panel.copy()
    dates = pd.to_datetime(out["Date"], errors="coerce")
    start = dates.min().date().isoformat()
    end = dates.max().date().isoformat()

    try:
        regimes = regime_detector.get_regime_series(start, end)
    except Exception:
        if require_hmm:
            raise
        regimes = pd.Series(dtype="object")

    regime_by_date = {
        pd.Timestamp(idx).normalize(): str(label)
        for idx, label in regimes.items()
    }
    labels = dates.dt.normalize().map(regime_by_date)
    out["HMM_Regime"] = labels
    out["HMM_Stress"] = labels.isin(STRESS_LABELS).astype(float)
    for label in EXPECTED_HMM_LABELS:
        out[f"HMM_{label}"] = (labels == label).astype(float)

    out["HMM_Stress_x_PEAD_Signal"] = out["HMM_Stress"] * _numeric(out, "PEAD_Signal")
    out["HMM_Stress_x_Ret_21D"] = out["HMM_Stress"] * _numeric(out, "Ret_21D")
    out["HMM_Stress_x_Vol_21D"] = out["HMM_Stress"] * _numeric(out, "Vol_21D")
    return out


def _available_feature_list(panel: pd.DataFrame) -> list[str]:
    desired = BASE_FEATURES + PEAD_HMM_FEATURES
    return [col for col in desired if col in panel.columns]


def build_panel(
    input_path: Path,
    surprise_threshold: float,
    post_earnings_window_days: int,
    require_hmm: bool,
) -> pd.DataFrame:
    panel = pd.read_parquet(input_path)
    if "Date" not in panel.columns or "Ticker" not in panel.columns:
        raise ValueError(f"{input_path} must contain Date and Ticker columns.")
    panel["Date"] = pd.to_datetime(panel["Date"], errors="coerce")
    panel["Ticker"] = panel["Ticker"].astype(str).str.upper().str.strip()

    out = add_pead_research_features(panel, surprise_threshold, post_earnings_window_days)
    out = add_hmm_regime_features(out, require_hmm=require_hmm)
    return out.sort_values(["Ticker", "Date"]).reset_index(drop=True)


def _print_summary(panel: pd.DataFrame, output: Path, features: list[str]) -> None:
    print(f"Saved {len(panel):,} rows -> {output}")
    print(f"Date range: {panel['Date'].min().date()} -> {panel['Date'].max().date()}")
    print(f"Tickers: {panel['Ticker'].nunique()}")
    print(f"Suggested extra features: {len(features)}")
    if "PEAD_Active" in panel.columns:
        print(f"PEAD active rows: {int(pd.to_numeric(panel['PEAD_Active'], errors='coerce').fillna(0).sum()):,}")
    if "HMM_Stress" in panel.columns:
        stress_days = panel.loc[pd.to_numeric(panel["HMM_Stress"], errors="coerce") > 0, "Date"].nunique()
        print(f"HMM stress dates: {stress_days}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a PEAD/HMM-enhanced Growth24 DL research panel.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--feature-list-output", type=Path, default=DEFAULT_FEATURE_LIST)
    parser.add_argument("--surprise-threshold", type=float, default=0.03)
    parser.add_argument("--post-earnings-window-days", type=int, default=21)
    parser.add_argument("--require-hmm", action="store_true")
    args = parser.parse_args()

    panel = build_panel(
        input_path=args.input,
        surprise_threshold=float(args.surprise_threshold),
        post_earnings_window_days=int(args.post_earnings_window_days),
        require_hmm=bool(args.require_hmm),
    )
    features = _available_feature_list(panel)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.feature_list_output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(args.output, index=False)
    args.feature_list_output.write_text(",".join(features) + "\n", encoding="utf-8")
    _print_summary(panel, args.output, features)
    print(f"Feature list -> {args.feature_list_output}")


if __name__ == "__main__":
    main()
