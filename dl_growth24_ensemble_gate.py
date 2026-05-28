"""Growth24 ensemble and abstention gate for the DL shadow paper candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from dl_cap_aware_replay_report import _load_validation_metrics
from dl_growth24_shadow_paper import DEFAULT_OUT_DIR

DEFAULT_FORECAST = DEFAULT_OUT_DIR / "growth24_current_shadow_forecast.csv"
DEFAULT_SUMMARY = DEFAULT_OUT_DIR / "growth24_current_shadow_summary.json"
DEFAULT_OUTPUT = DEFAULT_OUT_DIR / "growth24_current_ensemble_gate.json"
DEFAULT_BASELINE_META = [Path("models/linear_panel_meta.json"), Path("models/ml_panel_meta.json")]


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not Path(path).exists():
        return {}
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def _safe_metric(metrics: dict[str, Any], key: str, default: float = float("nan")) -> float:
    try:
        value = float(metrics.get(key, default))
    except (TypeError, ValueError):
        return default
    return value


def _mean_column(rows: pd.DataFrame, column: str, default: float) -> float:
    if column not in rows.columns:
        return float(default)
    vals = pd.to_numeric(rows[column], errors="coerce").dropna()
    return float(vals.mean()) if not vals.empty else float(default)


def _min_column(rows: pd.DataFrame, column: str, default: float) -> float:
    if column not in rows.columns:
        return float(default)
    vals = pd.to_numeric(rows[column], errors="coerce").dropna()
    return float(vals.min()) if not vals.empty else float(default)


def _forecast_metrics(forecasts: pd.DataFrame, top_n: int) -> dict[str, Any]:
    ordered = forecasts.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
    top = ordered.head(int(top_n))
    return {
        "universe_count": int(len(ordered)),
        "top_n": int(top_n),
        "top_tickers": [str(ticker).upper().strip() for ticker in top["Ticker"].tolist()],
        "score_gap": float(top["ShadowRankScore"].mean() - ordered["ShadowRankScore"].mean()),
        "forecast_gap_pct": float(top["RawForecastPct"].mean() - ordered["RawForecastPct"].mean()),
        "rank_score_std_top": _mean_column(top, "RankScoreStd", 0.0),
        "raw_forecast_std_top": _mean_column(top, "RawForecastStd", 0.0),
        "min_member_count_top": int(_min_column(top, "MemberCount", 0.0)),
        "asof_date": str(ordered["AsOfDate"].iloc[0]),
        "model": str(ordered["Model"].iloc[0]) if "Model" in ordered.columns else "",
        "source_results": str(ordered["SourceResults"].iloc[0]) if "SourceResults" in ordered.columns else "",
    }


def _baseline_registry(paths: list[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        payload = _load_json(path)
        if not payload:
            rows.append({"path": str(path), "status": "missing"})
            continue
        rows.append(
            {
                "path": str(path),
                "status": "reference_only",
                "trained_through": payload.get("trained_through"),
                "trained_at": payload.get("trained_at"),
                "feature_count": len(payload.get("features", [])),
                "rmse": payload.get("rmse", payload.get("validation_rmse")),
                "rows": payload.get("observations", payload.get("rows")),
                "note": "Existing tabular baseline artifact; not yet a Growth24-specific ensemble member.",
            }
        )
    return rows


def _gate_failures(
    forecast_metrics: dict[str, Any],
    validation_metrics: dict[str, float],
    summary: dict[str, Any],
    args: argparse.Namespace,
) -> list[str]:
    failures = []
    panel_gate = summary.get("panel_gate")
    if isinstance(panel_gate, dict) and not bool(panel_gate.get("passed", False)):
        failures.append(
            "panel gate failed "
            f"{panel_gate.get('eligible_universe_count')}/{panel_gate.get('expected_universe_count')}"
        )

    min_checks = [
        ("universe_count", float(args.expected_universe_count), "universe count"),
        ("score_gap", float(args.min_score_gap), "score gap"),
        ("forecast_gap_pct", float(args.min_forecast_gap), "forecast gap"),
        ("min_member_count_top", float(args.min_member_count), "top member count"),
    ]
    for key, threshold, label in min_checks:
        value = float(forecast_metrics.get(key, float("nan")))
        if not np.isfinite(value) or value < threshold:
            failures.append(f"{label} {value:.6f} < {threshold:.6f}")

    max_checks = [
        ("rank_score_std_top", float(args.max_rank_score_std), "rank-score ensemble dispersion"),
        ("raw_forecast_std_top", float(args.max_raw_forecast_std), "raw-forecast ensemble dispersion"),
    ]
    for key, threshold, label in max_checks:
        value = float(forecast_metrics.get(key, float("nan")))
        if not np.isfinite(value) or value > threshold:
            failures.append(f"{label} {value:.6f} > {threshold:.6f}")

    validation_checks = [
        ("ValidationSelectionScore", float(args.min_validation_score), "validation score"),
        ("ValidationDailyIC", float(args.min_validation_daily_ic), "validation daily IC"),
        ("ValidationSpread", float(args.min_validation_spread), "validation spread"),
        (
            "ValidationSpreadPositiveRate",
            float(args.min_validation_spread_positive_rate),
            "validation spread positive rate",
        ),
    ]
    for key, threshold, label in validation_checks:
        value = _safe_metric(validation_metrics, key)
        if not np.isfinite(value) or value < threshold:
            failures.append(f"{label} {value:.6f} < {threshold:.6f}")
    return failures


def run_gate(args: argparse.Namespace) -> dict[str, Any]:
    forecasts = pd.read_csv(args.forecast)
    if forecasts.empty:
        raise RuntimeError(f"No forecast rows found in {args.forecast}")
    forecast_metrics = _forecast_metrics(forecasts, int(args.top_n))
    summary = _load_json(args.summary)

    results_path = Path(args.results) if args.results is not None else None
    if results_path is None and forecast_metrics.get("source_results"):
        results_path = Path(str(forecast_metrics["source_results"]))
    validation_metrics = _load_validation_metrics(str(results_path)) if results_path is not None else {}

    baseline_paths = [Path(part.strip()) for part in str(args.baseline_meta).split(",") if part.strip()]
    baselines = _baseline_registry(baseline_paths)
    failures = _gate_failures(forecast_metrics, validation_metrics, summary, args)
    output = {
        "status": "abstain" if failures else "trade_allowed",
        "forecast": str(args.forecast),
        "summary": str(args.summary) if args.summary is not None else None,
        "results_path": str(results_path) if results_path is not None else None,
        "forecast_metrics": forecast_metrics,
        "validation_metrics": validation_metrics,
        "baseline_registry": baselines,
        "thresholds": {
            "expected_universe_count": int(args.expected_universe_count),
            "top_n": int(args.top_n),
            "min_score_gap": float(args.min_score_gap),
            "min_forecast_gap": float(args.min_forecast_gap),
            "max_rank_score_std": float(args.max_rank_score_std),
            "max_raw_forecast_std": float(args.max_raw_forecast_std),
            "min_member_count": int(args.min_member_count),
            "min_validation_score": float(args.min_validation_score),
            "min_validation_daily_ic": float(args.min_validation_daily_ic),
            "min_validation_spread": float(args.min_validation_spread),
            "min_validation_spread_positive_rate": float(args.min_validation_spread_positive_rate),
        },
        "gate_failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    return output


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate the Growth24 DL ensemble before paper selection.")
    ap.add_argument("--forecast", type=Path, default=DEFAULT_FORECAST)
    ap.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    ap.add_argument("--results", type=Path, default=None)
    ap.add_argument(
        "--baseline-meta",
        default=",".join(str(path) for path in DEFAULT_BASELINE_META),
        help="Comma-separated tabular baseline metadata paths.",
    )
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--top-n", type=int, default=2)
    ap.add_argument("--expected-universe-count", type=int, default=24)
    ap.add_argument("--min-score-gap", type=float, default=0.0)
    ap.add_argument("--min-forecast-gap", type=float, default=-10.0)
    ap.add_argument("--max-rank-score-std", type=float, default=999.0)
    ap.add_argument("--max-raw-forecast-std", type=float, default=999.0)
    ap.add_argument("--min-member-count", type=int, default=1)
    ap.add_argument("--min-validation-score", type=float, default=0.25)
    ap.add_argument("--min-validation-daily-ic", type=float, default=-0.05)
    ap.add_argument("--min-validation-spread", type=float, default=0.02)
    ap.add_argument("--min-validation-spread-positive-rate", type=float, default=0.45)
    args = ap.parse_args()

    output = run_gate(args)
    print(f"Status: {output['status']}")
    print(f"AsOfDate: {output['forecast_metrics']['asof_date']}")
    print(f"Top tickers: {', '.join(output['forecast_metrics']['top_tickers'])}")
    if output["gate_failures"]:
        print("Gate failures:")
        for failure in output["gate_failures"]:
            print(f" - {failure}")
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
