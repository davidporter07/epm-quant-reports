"""Historical blind adaptive loop for rank-head DL testing.

For each historical decision date:

1. Train only on labels that would have been known by that date.
2. Predict the decision date from features available through that date.
3. Attach the already-known realized return only after prediction, for scoring.

This is intentionally slower than a static backtest because it retrains per
cycle. Keep cycle counts small for research runs, then expand once the gate is
useful.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from deep_learning_model import TARGET_COL, _ensure_panel_schema, read_panel
from dl_directional_loss_experiment import _parse_features
from dl_expanded_feature_seed_grid import DEFAULT_EXTRA_FEATURES, DEFAULT_PANEL
from dl_rank_head_shadow_backtest import _predict_checkpoint_frame
from dl_rank_head_shadow_forecast import HORIZON, _assign_candidate_bucket
from dl_rank_head_experiment import _train_one
from dl_rank_head_paper_trade import build_paper_ledger
from dl_sign_regularized_experiment import _parse_ints, _resolve_device


OUT_DIR = Path("data/experiment/historical_blind_rank_head")
PANEL_DIR = OUT_DIR / "panels"
RESULTS_DIR = OUT_DIR / "results"
ARTIFACT_DIR = Path("models/experiment/rank_head_historical_blind")
DEFAULT_LEDGER = OUT_DIR / "historical_blind_shadow_log.parquet"
DEFAULT_SUMMARY = OUT_DIR / "historical_blind_summary.json"


def _date_list(panel: pd.DataFrame) -> list[pd.Timestamp]:
    dates = pd.to_datetime(panel["Date"], errors="coerce").dropna().drop_duplicates().sort_values()
    return [pd.Timestamp(d) for d in dates.tolist()]


def _decision_dates(
    panel: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
    cycles: int,
    step_days: int,
) -> list[pd.Timestamp]:
    labeled = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    dates = _date_list(labeled)
    if start_date:
        dates = [d for d in dates if d >= pd.Timestamp(start_date)]
    if end_date:
        dates = [d for d in dates if d <= pd.Timestamp(end_date)]
    if not dates:
        raise RuntimeError("No labeled decision dates available after filters.")

    selected = dates[:: max(1, int(step_days))]
    if cycles > 0:
        selected = selected[-int(cycles) :]
    return selected


def _matured_cutoff(all_dates: list[pd.Timestamp], decision_date: pd.Timestamp, horizon: int) -> pd.Timestamp:
    pos = all_dates.index(pd.Timestamp(decision_date))
    cutoff_pos = pos - int(horizon)
    if cutoff_pos <= 0:
        raise RuntimeError(f"Decision date {decision_date.date()} has no matured training cutoff.")
    return all_dates[cutoff_pos]


def _write_panel(panel: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(path, index=False)
    return path


def _predict_decision_date(
    result_rows: list[dict],
    full_panel: pd.DataFrame,
    decision_date: pd.Timestamp,
    top_n: int,
    device: str,
    amp: bool,
) -> pd.DataFrame:
    rows = sorted(result_rows, key=lambda row: float(row.get("selection_score", 0.0)), reverse=True)
    if int(top_n) > 0:
        rows = rows[: int(top_n)]
    if not rows:
        raise RuntimeError("No trained result rows available for prediction.")

    pred_panel = full_panel[full_panel["Date"] <= decision_date].copy()
    # Avoid target leakage into sample construction. The model uses only X;
    # y is set to a dummy finite value so PanelSequenceDataset can emit the
    # decision-date sample without seeing the real future outcome.
    pred_panel[TARGET_COL] = 0.0

    frames = [_predict_checkpoint_frame(row, pred_panel, device, amp) for row in rows]
    member_preds = pd.concat(frames, ignore_index=True)
    decision_key = decision_date.date().isoformat()
    member_preds = member_preds[member_preds["AsOfDate"] == decision_key].copy()
    if member_preds.empty:
        raise RuntimeError(f"No prediction rows emitted for {decision_key}.")

    grouped = (
        member_preds.groupby(["AsOfDate", "Ticker"], as_index=False)
        .agg(
            ShadowRankScore=("CenteredRankScore", "mean"),
            RawForecastPct=("RawForecastPct", "mean"),
            RankScoreStd=("CenteredRankScore", "std"),
            RawForecastStd=("RawForecastPct", "std"),
            MemberCount=("Member", "nunique"),
            MeanMemberSelectionScore=("SelectionScore", "mean"),
        )
        .sort_values("ShadowRankScore", ascending=False)
        .reset_index(drop=True)
    )
    grouped["RankScoreStd"] = grouped["RankScoreStd"].fillna(0.0)
    grouped["RawForecastStd"] = grouped["RawForecastStd"].fillna(0.0)
    n = len(grouped)
    grouped["Rank"] = np.arange(1, n + 1, dtype=int)
    grouped["RankPercentile"] = 1.0 - ((grouped["Rank"] - 1) / max(1, n - 1))
    grouped["CandidateBucket"] = [_assign_candidate_bucket(int(rank), n) for rank in grouped["Rank"]]
    return grouped


def _attach_realized(predictions: pd.DataFrame, full_panel: pd.DataFrame) -> pd.DataFrame:
    targets = full_panel[["Date", "Ticker", TARGET_COL]].copy()
    targets["AsOfDate"] = pd.to_datetime(targets["Date"], errors="coerce").dt.date.astype("string")
    targets["Ticker"] = targets["Ticker"].astype(str).str.upper().str.strip()
    targets[TARGET_COL] = pd.to_numeric(targets[TARGET_COL], errors="coerce")
    out = predictions.merge(targets[["AsOfDate", "Ticker", TARGET_COL]], on=["AsOfDate", "Ticker"], how="left")
    out["RealizedForwardReturn"] = out[TARGET_COL]
    return out.drop(columns=[TARGET_COL])


def run_loop(args: argparse.Namespace) -> tuple[pd.DataFrame, dict]:
    device = _resolve_device(args.device)
    use_amp = bool(args.amp and device.startswith("cuda"))
    panel = _ensure_panel_schema(read_panel(args.panel))
    all_dates = _date_list(panel)
    decisions = _decision_dates(panel, args.start_date, args.end_date, args.cycles, args.step_days)
    extra_features = _parse_features(args.extra_features)

    shadow_rows = []
    cycle_summaries = []
    for cycle_idx, decision_date in enumerate(decisions, start=1):
        matured = _matured_cutoff(all_dates, decision_date, HORIZON)
        train_panel = panel[
            (panel["Date"] <= matured) & pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()
        ].copy()
        if train_panel.empty:
            continue

        cycle_name = f"c{cycle_idx:03d}_{decision_date.strftime('%Y%m%d')}"
        train_panel_path = _write_panel(train_panel, PANEL_DIR / f"{cycle_name}_train.parquet")
        artifact_dir = ARTIFACT_DIR / args.output_stem / cycle_name
        print(
            f"\n=== blind cycle {cycle_name}: "
            f"train labels <= {matured.date()} predict {decision_date.date()} ==="
        )

        result_rows = []
        for seed in _parse_ints(args.seeds):
            result_rows.append(
                _train_one(
                    panel_path=train_panel_path,
                    extra_features=extra_features,
                    seed=seed,
                    epochs=int(args.epochs),
                    batch_size=int(args.batch_size),
                    val_days=int(args.val_days),
                    lr=float(args.lr),
                    scheduler_name=args.scheduler,
                    max_lr=args.max_lr,
                    onecycle_pct_start=0.45,
                    onecycle_div_factor=10.0,
                    onecycle_final_div_factor=1000.0,
                    device=device,
                    amp=use_amp,
                    num_workers=int(args.num_workers),
                    pin_memory=bool(args.pin_memory),
                    nll_weight=float(args.nll_weight),
                    corr_weight=float(args.corr_weight),
                    rank_weight=float(args.rank_weight),
                    aux_target_transform=args.aux_target_transform,
                    rank_temperature=float(args.rank_temperature),
                    date_grouped_batches=bool(args.date_grouped_batches),
                    min_date_batch_size=int(args.min_date_batch_size),
                    dates_per_batch=int(args.dates_per_batch),
                    bullish_min=0.35,
                    bullish_max=0.75,
                    ic_min=0.0,
                    daily_ic_min=float(args.daily_ic_min),
                    spread_min=float(args.spread_min),
                    spread_positive_rate_min=float(args.spread_positive_rate_min),
                    selection_score_mode="selection",
                    direction_min=0.5085,
                    hard_gate=True,
                    daily_ic_weight=0.75,
                    top_excess_weight=float(args.top_excess_weight),
                    spread_loss_weight=float(args.spread_loss_weight),
                    monotonic_weight=float(args.monotonic_weight),
                    top_excess_temperature=float(args.top_excess_temperature),
                    spread_loss_temperature=float(args.spread_loss_temperature),
                    monotonic_quantiles=int(args.monotonic_quantiles),
                    ticker_concentration_weight=float(args.ticker_concentration_weight),
                    ticker_concentration_temperature=float(args.ticker_concentration_temperature),
                    stress_loss_weight=float(args.stress_loss_weight),
                    stress_feature_column=args.stress_feature_column,
                    stress_feature_min=float(args.stress_feature_min),
                    stress_drawdown_threshold=float(args.stress_drawdown_threshold),
                    target_mode=args.target_mode,
                    artifact_dir=artifact_dir,
                )
            )

        result_dir = RESULTS_DIR / args.output_stem
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"{cycle_name}_results.json"
        with result_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "cycle": cycle_name,
                    "decision_date": decision_date.date().isoformat(),
                    "train_label_through": matured.date().isoformat(),
                    "results": result_rows,
                },
                f,
                indent=2,
            )

        predictions = _predict_decision_date(result_rows, panel, decision_date, int(args.top_n), device, use_amp)
        predictions = _attach_realized(predictions, panel)
        predictions["RunDate"] = pd.Timestamp.today().date().isoformat()
        predictions["Cycle"] = cycle_name
        predictions["TrainLabelThrough"] = matured.date().isoformat()
        predictions["Model"] = f"HistoricalBlindRankHeadTop{int(args.top_n)}"
        predictions["Horizon"] = HORIZON
        predictions["SourceResults"] = str(result_path)
        shadow_rows.append(predictions)

        long_ret = predictions.loc[predictions["CandidateBucket"] == "long_candidate", "RealizedForwardReturn"].mean()
        short_ret = predictions.loc[predictions["CandidateBucket"] == "short_candidate", "RealizedForwardReturn"].mean()
        cycle_summaries.append(
            {
                "cycle": cycle_name,
                "decision_date": decision_date.date().isoformat(),
                "train_label_through": matured.date().isoformat(),
                "long_ticker": ",".join(predictions.loc[predictions["CandidateBucket"] == "long_candidate", "Ticker"]),
                "short_ticker": ",".join(predictions.loc[predictions["CandidateBucket"] == "short_candidate", "Ticker"]),
                "long_return": float(long_ret),
                "short_return": float(short_ret),
                "long_short_return": float(long_ret - short_ret),
            }
        )

    if not shadow_rows:
        raise RuntimeError("No blind-loop predictions were generated.")

    shadow_log = pd.concat(shadow_rows, ignore_index=True)
    ordered_cols = [
        "RunDate",
        "Cycle",
        "TrainLabelThrough",
        "AsOfDate",
        "Ticker",
        "Model",
        "Horizon",
        "Rank",
        "RankPercentile",
        "ShadowRankScore",
        "RawForecastPct",
        "RankScoreStd",
        "RawForecastStd",
        "CandidateBucket",
        "MemberCount",
        "MeanMemberSelectionScore",
        "SourceResults",
        "RealizedForwardReturn",
    ]
    shadow_log = shadow_log[ordered_cols]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    shadow_log.to_parquet(args.output, index=False)
    shadow_log.to_csv(args.csv_output, index=False)

    paper_ledger_path = args.output.with_name(args.output.stem + "_paper_ledger.csv")
    paper_summary_path = args.output.with_name(args.output.stem + "_paper_summary.json")
    paper_ledger, paper_summary = build_paper_ledger(args.output, int(args.paper_long_n), int(args.paper_short_n))
    paper_ledger.to_csv(paper_ledger_path, index=False)
    with paper_summary_path.open("w", encoding="utf-8") as f:
        json.dump(paper_summary, f, indent=2)

    summary = {
        "status": "scored",
        "panel": str(args.panel),
        "cycles": len(cycle_summaries),
        "top_n": int(args.top_n),
        "paper_long_n": int(args.paper_long_n),
        "paper_short_n": int(args.paper_short_n),
        "output": str(args.output),
        "csv_output": str(args.csv_output),
        "paper_ledger": str(paper_ledger_path),
        "paper_summary": str(paper_summary_path),
        "stress_loss_weight": float(args.stress_loss_weight),
        "spread_loss_weight": float(args.spread_loss_weight),
        "spread_loss_temperature": float(args.spread_loss_temperature),
        "stress_feature_column": args.stress_feature_column,
        "stress_feature_min": float(args.stress_feature_min),
        "stress_drawdown_threshold": float(args.stress_drawdown_threshold),
        "cycle_summaries": cycle_summaries,
        "paper_metrics": paper_summary,
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    with args.summary_output.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return shadow_log, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a historical blind adaptive rank-head loop.")
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--extra-features", default=DEFAULT_EXTRA_FEATURES)
    ap.add_argument("--start-date", default=None)
    ap.add_argument("--end-date", default=None)
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--step-days", type=int, default=21)
    ap.add_argument("--top-n", type=int, default=1)
    ap.add_argument("--paper-long-n", type=int, default=1)
    ap.add_argument("--paper-short-n", type=int, default=1)
    ap.add_argument("--seeds", default="20260505")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--val-days", type=int, default=126)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--scheduler", choices=["cosine", "onecycle", "none"], default="cosine")
    ap.add_argument("--max-lr", type=float, default=None)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--pin-memory", action="store_true")
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument("--date-grouped-batches", action="store_true")
    ap.add_argument("--min-date-batch-size", type=int, default=2)
    ap.add_argument("--dates-per-batch", type=int, default=64)
    ap.add_argument("--corr-weight", type=float, default=0.05)
    ap.add_argument("--rank-weight", type=float, default=0.005)
    ap.add_argument("--nll-weight", type=float, default=0.5)
    ap.add_argument("--aux-target-transform", choices=["raw", "demean", "zscore"], default="zscore")
    ap.add_argument("--rank-temperature", type=float, default=0.02)
    ap.add_argument("--top-excess-weight", type=float, default=0.0)
    ap.add_argument("--top-excess-temperature", type=float, default=0.05)
    ap.add_argument("--spread-loss-weight", type=float, default=0.0)
    ap.add_argument("--spread-loss-temperature", type=float, default=0.05)
    ap.add_argument("--monotonic-weight", type=float, default=0.0)
    ap.add_argument("--monotonic-quantiles", type=int, default=5)
    ap.add_argument("--ticker-concentration-weight", type=float, default=0.0)
    ap.add_argument("--ticker-concentration-temperature", type=float, default=0.05)
    ap.add_argument("--stress-loss-weight", type=float, default=1.0)
    ap.add_argument("--stress-feature-column", default="Market_Stress_Regime")
    ap.add_argument("--stress-feature-min", type=float, default=0.5)
    ap.add_argument("--stress-drawdown-threshold", type=float, default=-0.10)
    ap.add_argument("--target-mode", choices=["raw", "date_excess"], default="raw")
    ap.add_argument("--daily-ic-min", type=float, default=-0.02)
    ap.add_argument("--spread-min", type=float, default=0.0)
    ap.add_argument("--spread-positive-rate-min", type=float, default=0.55)
    ap.add_argument("--output-stem", default="historical_blind_rank_head")
    ap.add_argument("--output", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--csv-output", type=Path, default=DEFAULT_LEDGER.with_suffix(".csv"))
    ap.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    args = ap.parse_args()

    shadow_log, summary = run_loop(args)
    print(f"Status: {summary['status']}")
    print(f"Cycles: {summary['cycles']}")
    print(f"Rows: {len(shadow_log)}")
    print(f"Saved shadow log -> {args.output}")
    print(f"Saved summary -> {args.summary_output}")
    if summary.get("paper_metrics", {}).get("status") == "scored":
        metrics = summary["paper_metrics"]
        print(f"Mean long-short return: {metrics['mean_long_short_return']:.6f}")
        print(f"Spread hit rate: {metrics['spread_hit_rate']:.6f}")


if __name__ == "__main__":
    main()
