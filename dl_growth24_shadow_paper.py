"""Train and run the growth24 rank-head shadow/paper candidate.

This is intentionally separate from the production forecasting page. It trains
the frozen growth24 DL candidate on matured labels, forecasts the latest panel
date, and appends a cap-aware paper selection plan for live shadow tracking.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from deep_learning_model import TARGET_COL, TrainConfig, _ensure_panel_schema, read_panel
from dl_cap_aware_replay_report import _load_validation_metrics
from dl_directional_loss_experiment import _parse_features
from dl_panel_diagnostics import assert_decision_date_panel
from dl_rank_head_experiment import _train_one
from dl_rank_head_historical_blind_loop import (
    _date_list,
    _matured_cutoff,
    _predict_decision_date,
    _write_panel,
)
from dl_rank_head_shadow_forecast import HORIZON
from dl_sign_regularized_experiment import _feature_cols, _parse_ints, _resolve_device


DEFAULT_PANEL = Path("data/experiment/dl_research_panels/research_growth_24_price_earnings_av_panel.parquet")
DEFAULT_OUT_DIR = Path("data/experiment/growth24_shadow_paper")
DEFAULT_MODEL_DIR = Path("models/experiment/growth24_shadow_paper")
DEFAULT_STEM = "growth24_current_8e_stress_drawdown20_w2_seedrobust_2seed"
MODEL_LABEL = "Growth24RankHeadShadowTop2StressW2"
VALIDATED_RESEARCH_ARTIFACT_STEM = "growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed"
GROWTH24_POLICY_BASIS = {
    "validated_research_artifact_stem": VALIDATED_RESEARCH_ARTIFACT_STEM,
    "diagnostic_top2_excess": 0.0614,
    "diagnostic_top2_hit_rate": 0.7500,
    "cap_aware_top2_cap50_excess": 0.0626,
    "cap_aware_top2_cap50_coverage": 0.8611,
    "cap_aware_top2_cap50_max_slot_share": 0.4194,
    "final4_top2_stress_spread": 0.0990,
    "final4_top2_worst_drawdown": -0.0454,
}
DEFAULT_GROWTH24_EXTRA_FEATURES = (
    "momentum_12_1,momentum_6_1,momentum_3_1,"
    "overnight_return_5d,intraday_return_5d,"
    "overnight_return_20d,intraday_return_20d,"
    "atr_percentile,hv_percentile,vol_regime,"
    "gap_magnitude_5d,gap_5d_count,"
    "Market_Ret_5D,Market_Ret_21D,Market_Ret_63D,"
    "Market_Vol_21D,Market_Vol_63D,"
    "Market_Drawdown_63D,Market_Drawdown_252D,Market_Stress_Regime,"
    "Rel_Ret_5D,Rel_Ret_21D,Rel_Ret_63D,"
    "RSI_14,MA_20,MA_50,MA_200,Volume,"
    "earnings_surprise_last,earnings_beat_rate_4q,days_since_earnings,"
    "post_earnings_window_active,earnings_surprise_direction,earnings_abs_surprise,"
    "post_earnings_positive_drift_window,post_earnings_negative_drift_window,"
    "earnings_surprise_x_atr_regime,earnings_surprise_x_gap_count"
)


def _latest_decision_date(panel: pd.DataFrame, raw: str | None) -> pd.Timestamp:
    dates = _date_list(panel)
    if raw:
        target = pd.Timestamp(raw)
        eligible = [d for d in dates if d <= target]
        if not eligible:
            raise RuntimeError(f"No panel date on or before {target.date()}")
        return eligible[-1]
    return dates[-1]


def _append_frame(path: Path, rows: pd.DataFrame, subset: list[str]) -> None:
    if rows.empty:
        return
    if path.exists():
        old = pd.read_parquet(path)
        combined = pd.concat([old, rows], ignore_index=True)
    else:
        combined = rows.copy()
    combined = combined.drop_duplicates(subset=subset, keep="last")
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)


def _history_counts(path: Path) -> tuple[Counter[str], int]:
    if not path.exists():
        return Counter(), 0
    rows = pd.read_csv(path)
    if "LongTickers" not in rows.columns:
        return Counter(), 0
    counts: Counter[str] = Counter()
    slots = 0
    for value in rows["LongTickers"].dropna().astype(str):
        tickers = [part.strip().upper() for part in value.split(",") if part.strip()]
        counts.update(tickers)
        slots += len(tickers)
    return counts, slots


def _ticker_allowed(counts: Counter[str], ticker: str, total_after: int, max_ticker_share: float) -> bool:
    if max_ticker_share >= 1.0:
        return True
    allowed_count = max(1, int(np.floor(float(max_ticker_share) * int(total_after))))
    return counts[str(ticker)] + 1 <= allowed_count


def _select_longs(
    forecasts: pd.DataFrame,
    top_n: int,
    max_ticker_share: float,
    prior_counts: Counter[str],
    prior_slots: int,
) -> pd.DataFrame:
    ordered = forecasts.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
    picked: list[int] = []
    scratch = Counter(prior_counts)
    total = int(prior_slots)
    for idx, row in ordered.iterrows():
        ticker = str(row["Ticker"]).upper().strip()
        if not _ticker_allowed(scratch, ticker, total + 1, max_ticker_share):
            continue
        picked.append(idx)
        scratch[ticker] += 1
        total += 1
        if len(picked) >= int(top_n):
            break
    if len(picked) < int(top_n):
        return ordered.iloc[0:0].copy()
    return ordered.loc[picked].copy()


def _signal_metrics(forecasts: pd.DataFrame, result_path: Path, top_n: int) -> dict[str, float]:
    ordered = forecasts.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
    top = ordered.head(int(top_n))
    metrics = _load_validation_metrics(str(result_path))
    rank_std = pd.to_numeric(top["RankScoreStd"], errors="coerce").mean() if "RankScoreStd" in top.columns else 0.0
    raw_std = pd.to_numeric(top["RawForecastStd"], errors="coerce").mean() if "RawForecastStd" in top.columns else 0.0
    metrics.update(
        {
            "ScoreGap": float(top["ShadowRankScore"].mean() - ordered["ShadowRankScore"].mean()),
            "ForecastGapPct": float(top["RawForecastPct"].mean() - ordered["RawForecastPct"].mean()),
            "RankScoreStdTop": float(rank_std),
            "RawForecastStdTop": float(raw_std),
        }
    )
    return metrics


def _gate_failures(metrics: dict[str, float], args: argparse.Namespace) -> list[str]:
    checks = [
        ("ScoreGap", float(args.min_score_gap), "score gap", "min"),
        ("ForecastGapPct", float(args.min_forecast_gap), "forecast gap", "min"),
        ("ValidationSelectionScore", float(args.min_validation_score), "validation score", "min"),
        ("ValidationDailyIC", float(args.min_validation_daily_ic), "validation daily IC", "min"),
        ("ValidationSpread", float(args.min_validation_spread), "validation spread", "min"),
        (
            "ValidationSpreadPositiveRate",
            float(args.min_validation_spread_positive_rate),
            "validation spread positive rate",
            "min",
        ),
        ("RankScoreStdTop", float(args.max_rank_score_std), "rank-score ensemble dispersion", "max"),
        ("RawForecastStdTop", float(args.max_raw_forecast_std), "raw-forecast ensemble dispersion", "max"),
    ]
    failures = []
    for key, threshold, label, mode in checks:
        value = float(metrics.get(key, float("nan")))
        if not np.isfinite(value):
            failures.append(f"{label} is not finite")
        elif mode == "min" and value < threshold:
            failures.append(f"{label} {value:.6f} < {threshold:.6f}")
        elif mode == "max" and value > threshold:
            failures.append(f"{label} {value:.6f} > {threshold:.6f}")
    return failures


def _build_plan_row(
    forecasts: pd.DataFrame,
    selected: pd.DataFrame,
    result_path: Path,
    metrics: dict[str, float],
    failures: list[str],
    args: argparse.Namespace,
    prior_slots: int,
    prior_counts: Counter[str],
) -> dict[str, Any]:
    counts = Counter(prior_counts)
    tickers = [str(t).upper().strip() for t in selected["Ticker"].tolist()]
    counts.update(tickers)
    total_slots = prior_slots + len(tickers)
    max_share = float(max(counts.values(), default=0) / max(1, total_slots))
    status = "selected" if not failures and len(tickers) == int(args.paper_top_n) else "blocked"
    if len(tickers) < int(args.paper_top_n):
        failures = [*failures, "cap-aware selection could not fill requested slots"]
    return {
        "RunDate": date.today().isoformat(),
        "AsOfDate": str(forecasts["AsOfDate"].iloc[0]),
        "Model": MODEL_LABEL,
        "Status": status,
        "LongTickers": ",".join(tickers) if status == "selected" else "",
        "CandidateTickers": ",".join(forecasts.sort_values("Rank").head(int(args.paper_top_n))["Ticker"].tolist()),
        "UniverseCount": int(len(forecasts)),
        "PaperTopN": int(args.paper_top_n),
        "MaxTickerShare": float(args.max_ticker_share),
        "PriorSlots": int(prior_slots),
        "PostSelectionSlots": int(total_slots if status == "selected" else prior_slots),
        "PostSelectionMaxTickerShare": max_share if status == "selected" else float(
            max(prior_counts.values(), default=0) / max(1, prior_slots)
        ),
        "SelectedAvgRank": float(selected["Rank"].mean()) if not selected.empty else float("nan"),
        "SelectedAvgRankScore": float(selected["ShadowRankScore"].mean()) if not selected.empty else float("nan"),
        "SelectedAvgForecastPct": float(selected["RawForecastPct"].mean()) if not selected.empty else float("nan"),
        "ScoreGap": float(metrics.get("ScoreGap", float("nan"))),
        "ForecastGapPct": float(metrics.get("ForecastGapPct", float("nan"))),
        "RankScoreStdTop": float(metrics.get("RankScoreStdTop", float("nan"))),
        "RawForecastStdTop": float(metrics.get("RawForecastStdTop", float("nan"))),
        "ValidationSelectionScore": float(metrics.get("ValidationSelectionScore", float("nan"))),
        "ValidationDailyIC": float(metrics.get("ValidationDailyIC", float("nan"))),
        "ValidationSpread": float(metrics.get("ValidationSpread", float("nan"))),
        "ValidationSpreadPositiveRate": float(metrics.get("ValidationSpreadPositiveRate", float("nan"))),
        "RiskGateMaxDrawdown": float(args.risk_gate_max_drawdown),
        "ValidatedResearchArtifactStem": VALIDATED_RESEARCH_ARTIFACT_STEM,
        "DiagnosticTop2Excess": float(GROWTH24_POLICY_BASIS["diagnostic_top2_excess"]),
        "DiagnosticTop2HitRate": float(GROWTH24_POLICY_BASIS["diagnostic_top2_hit_rate"]),
        "CapAwareTop2Cap50Excess": float(GROWTH24_POLICY_BASIS["cap_aware_top2_cap50_excess"]),
        "CapAwareTop2Cap50Coverage": float(GROWTH24_POLICY_BASIS["cap_aware_top2_cap50_coverage"]),
        "CapAwareTop2Cap50MaxSlotShare": float(GROWTH24_POLICY_BASIS["cap_aware_top2_cap50_max_slot_share"]),
        "Final4Top2StressSpread": float(GROWTH24_POLICY_BASIS["final4_top2_stress_spread"]),
        "Final4Top2WorstDrawdown": float(GROWTH24_POLICY_BASIS["final4_top2_worst_drawdown"]),
        "GateFailures": "; ".join(failures),
        "SourceResults": str(result_path),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def run_shadow_paper(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    device = _resolve_device(args.device)
    use_amp = bool(args.amp and device.startswith("cuda"))
    panel = _ensure_panel_schema(read_panel(args.panel))
    all_dates = _date_list(panel)
    decision_date = _latest_decision_date(panel, args.asof_date)
    matured = _matured_cutoff(all_dates, decision_date, HORIZON)
    extra_features = _parse_features(args.extra_features)
    feature_cols = _feature_cols(args.panel, extra_features)
    panel_gate = assert_decision_date_panel(
        panel=panel,
        decision_date=decision_date,
        feature_cols=feature_cols,
        seq_len=TrainConfig().seq_len,
        expected_universe_count=int(args.expected_universe_count),
        output_path=args.panel_diagnostic_output,
        allow_gaps=bool(args.allow_panel_gaps),
    )

    train_panel = panel[
        (panel["Date"] <= matured) & pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()
    ].copy()
    if train_panel.empty:
        raise RuntimeError("No matured training rows available.")

    run_name = f"{args.output_stem}_{decision_date.strftime('%Y%m%d')}"
    train_panel_path = _write_panel(train_panel, args.output_dir / "panels" / f"{run_name}_train.parquet")
    artifact_dir = args.model_dir / run_name
    result_dir = args.output_dir / "results"
    result_path = result_dir / f"{run_name}_results.json"

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
                ticker_concentration_weight=0.0,
                ticker_concentration_temperature=0.05,
                target_mode=args.target_mode,
                stress_loss_weight=float(args.stress_loss_weight),
                stress_feature_column=args.stress_feature_column,
                stress_feature_min=float(args.stress_feature_min),
                stress_drawdown_threshold=float(args.stress_drawdown_threshold),
                artifact_dir=artifact_dir,
            )
        )

    _write_json(
        result_path,
        {
            "run_name": run_name,
            "decision_date": decision_date.date().isoformat(),
            "train_label_through": matured.date().isoformat(),
            "panel_gate": panel_gate,
            "growth24_shadow_policy": {
                "paper_top_n": int(args.paper_top_n),
                "max_ticker_share": float(args.max_ticker_share),
                "risk_gate_max_drawdown": float(args.risk_gate_max_drawdown),
                "min_coverage_research_gate": float(args.research_min_coverage),
                "expected_universe_count": int(args.expected_universe_count),
                "stress_loss_weight": float(args.stress_loss_weight),
                "stress_feature_column": args.stress_feature_column,
                "stress_feature_min": float(args.stress_feature_min),
                "stress_drawdown_threshold": float(args.stress_drawdown_threshold),
                **GROWTH24_POLICY_BASIS,
            },
            "results": result_rows,
        },
    )

    forecasts = _predict_decision_date(result_rows, panel, decision_date, int(args.top_n), device, use_amp)
    forecasts["RunDate"] = date.today().isoformat()
    forecasts["TrainLabelThrough"] = matured.date().isoformat()
    forecasts["Model"] = MODEL_LABEL
    forecasts["Horizon"] = HORIZON
    forecasts["SourceResults"] = str(result_path)
    forecasts = forecasts[
        [
            "RunDate",
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
            "TrainLabelThrough",
            "SourceResults",
        ]
    ]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    forecasts.to_csv(args.forecast_output, index=False)
    _append_frame(args.forecast_log, forecasts, ["RunDate", "AsOfDate", "Ticker", "Model"])

    metrics = _signal_metrics(forecasts, result_path, int(args.paper_top_n))
    failures = _gate_failures(metrics, args)
    prior_counts, prior_slots = _history_counts(args.paper_plan_log)
    selected = _select_longs(forecasts, int(args.paper_top_n), float(args.max_ticker_share), prior_counts, prior_slots)
    plan_row = _build_plan_row(forecasts, selected, result_path, metrics, failures, args, prior_slots, prior_counts)
    plan = pd.DataFrame([plan_row])
    if args.paper_plan_log.exists():
        old_plan = pd.read_csv(args.paper_plan_log)
        plan_log = pd.concat([old_plan, plan], ignore_index=True)
        plan_log = plan_log.drop_duplicates(subset=["RunDate", "AsOfDate", "Model"], keep="last")
    else:
        plan_log = plan
    args.paper_plan_log.parent.mkdir(parents=True, exist_ok=True)
    plan_log.to_csv(args.paper_plan_log, index=False)
    plan.to_csv(args.paper_plan_output, index=False)

    summary = {
        "status": str(plan_row["Status"]),
        "run_name": run_name,
        "asof_date": decision_date.date().isoformat(),
        "train_label_through": matured.date().isoformat(),
        "forecast_output": str(args.forecast_output),
        "forecast_log": str(args.forecast_log),
        "paper_plan_output": str(args.paper_plan_output),
        "paper_plan_log": str(args.paper_plan_log),
        "result_path": str(result_path),
        "selected_tickers": plan_row["LongTickers"],
        "gate_failures": plan_row["GateFailures"],
        "panel_gate": panel_gate,
        "policy": {
            "paper_top_n": int(args.paper_top_n),
            "max_ticker_share": float(args.max_ticker_share),
            "risk_gate_max_drawdown": float(args.risk_gate_max_drawdown),
            "expected_universe_count": int(args.expected_universe_count),
            "stress_loss_weight": float(args.stress_loss_weight),
            "stress_feature_column": args.stress_feature_column,
            "stress_feature_min": float(args.stress_feature_min),
            "stress_drawdown_threshold": float(args.stress_drawdown_threshold),
            **GROWTH24_POLICY_BASIS,
        },
    }
    _write_json(args.summary_output, summary)
    return forecasts, plan, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the growth24 DL shadow/paper candidate.")
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--extra-features", default=DEFAULT_GROWTH24_EXTRA_FEATURES)
    ap.add_argument("--asof-date", default=None)
    ap.add_argument("--output-stem", default=DEFAULT_STEM)
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    ap.add_argument("--forecast-output", type=Path, default=DEFAULT_OUT_DIR / "growth24_current_shadow_forecast.csv")
    ap.add_argument("--forecast-log", type=Path, default=DEFAULT_OUT_DIR / "growth24_shadow_forecast_log.parquet")
    ap.add_argument("--paper-plan-output", type=Path, default=DEFAULT_OUT_DIR / "growth24_current_paper_plan.csv")
    ap.add_argument("--paper-plan-log", type=Path, default=DEFAULT_OUT_DIR / "growth24_paper_plan_log.csv")
    ap.add_argument("--summary-output", type=Path, default=DEFAULT_OUT_DIR / "growth24_current_shadow_summary.json")
    ap.add_argument("--top-n", type=int, default=1)
    ap.add_argument("--paper-top-n", type=int, default=2)
    ap.add_argument("--max-ticker-share", type=float, default=0.50)
    ap.add_argument("--risk-gate-max-drawdown", type=float, default=-0.35)
    ap.add_argument("--research-min-coverage", type=float, default=0.50)
    ap.add_argument("--min-score-gap", type=float, default=0.0)
    ap.add_argument("--min-forecast-gap", type=float, default=-10.0)
    ap.add_argument("--min-validation-score", type=float, default=0.25)
    ap.add_argument("--min-validation-daily-ic", type=float, default=-0.05)
    ap.add_argument("--min-validation-spread", type=float, default=0.02)
    ap.add_argument("--min-validation-spread-positive-rate", type=float, default=0.45)
    ap.add_argument("--max-rank-score-std", type=float, default=999.0)
    ap.add_argument("--max-raw-forecast-std", type=float, default=999.0)
    ap.add_argument("--expected-universe-count", type=int, default=24)
    ap.add_argument("--allow-panel-gaps", action="store_true")
    ap.add_argument(
        "--panel-diagnostic-output",
        type=Path,
        default=DEFAULT_OUT_DIR / "growth24_current_panel_diagnostics.json",
    )
    ap.add_argument("--seeds", default="20260506,20260507")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--val-days", type=int, default=126)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--scheduler", choices=["cosine", "onecycle", "none"], default="cosine")
    ap.add_argument("--max-lr", type=float, default=None)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--pin-memory", action="store_true")
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument("--date-grouped-batches", action="store_true", default=True)
    ap.add_argument("--min-date-batch-size", type=int, default=2)
    ap.add_argument("--dates-per-batch", type=int, default=64)
    ap.add_argument("--corr-weight", type=float, default=0.05)
    ap.add_argument("--rank-weight", type=float, default=0.005)
    ap.add_argument("--nll-weight", type=float, default=0.5)
    ap.add_argument("--aux-target-transform", choices=["raw", "demean", "zscore"], default="zscore")
    ap.add_argument("--rank-temperature", type=float, default=0.02)
    ap.add_argument("--top-excess-weight", type=float, default=0.5)
    ap.add_argument("--top-excess-temperature", type=float, default=0.05)
    ap.add_argument("--spread-loss-weight", type=float, default=0.0)
    ap.add_argument("--spread-loss-temperature", type=float, default=0.05)
    ap.add_argument("--monotonic-weight", type=float, default=0.05)
    ap.add_argument("--monotonic-quantiles", type=int, default=5)
    ap.add_argument("--target-mode", choices=["raw", "date_excess"], default="date_excess")
    ap.add_argument("--stress-loss-weight", type=float, default=2.0)
    ap.add_argument("--stress-feature-column", default="Market_Stress_Regime")
    ap.add_argument("--stress-feature-min", type=float, default=2.0)
    ap.add_argument("--stress-drawdown-threshold", type=float, default=-0.20)
    ap.add_argument("--daily-ic-min", type=float, default=-0.02)
    ap.add_argument("--spread-min", type=float, default=0.0)
    ap.add_argument("--spread-positive-rate-min", type=float, default=0.55)
    args = ap.parse_args()

    forecasts, plan, summary = run_shadow_paper(args)
    print(f"Status: {summary['status']}")
    print(f"AsOfDate: {summary['asof_date']}")
    print(f"Train labels through: {summary['train_label_through']}")
    print("Top forecast rows:")
    print(forecasts.sort_values("Rank").head(8)[["Ticker", "Rank", "ShadowRankScore", "RawForecastPct"]].to_string(index=False))
    if summary["status"] == "selected":
        print(f"Selected long tickers: {summary['selected_tickers']}")
    else:
        print(f"Gate failures: {summary['gate_failures']}")
    print(f"Saved forecast -> {args.forecast_output}")
    print(f"Updated forecast log -> {args.forecast_log}")
    print(f"Saved paper plan -> {args.paper_plan_output}")
    print(f"Updated paper plan log -> {args.paper_plan_log}")


if __name__ == "__main__":
    main()
