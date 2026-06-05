"""Evaluate a Growth24 shadow-log candidate against the fixed research contract.

This is research-only. It reads an existing historical-blind shadow log and
runs the current Growth24 evaluation gauntlet without changing live policy,
paper plans, scheduled tasks, or email behavior.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from dl_growth24_policy_threshold_sensitivity import build_report as build_threshold_sensitivity
from dl_growth24_post_prediction_gate_grid import DEFAULT_SHADOW_LOG, _fmt_pct, _json_safe, _load_shadow_log, build_report as build_gate_grid
from dl_growth24_post_prediction_gate_walk_forward import build_walk_forward_report
from dl_growth24_shadow_policy_replay import build_replay


DEFAULT_OUTPUT = DEFAULT_SHADOW_LOG.with_name(f"{DEFAULT_SHADOW_LOG.stem}_candidate_contract_eval.json")
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_36c_8e_candidate_contract_eval.md")


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if pd.notna(out) else None


def _available_cycles(shadow_log: Path) -> tuple[int, str | None, str | None]:
    rows = _load_shadow_log(shadow_log)
    dates = pd.to_datetime(rows["AsOfDate"], errors="coerce").dropna().drop_duplicates().sort_values()
    if dates.empty:
        return 0, None, None
    return int(len(dates)), dates.iloc[0].date().isoformat(), dates.iloc[-1].date().isoformat()


def _gate_grid_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        shadow_log=args.shadow_log,
        long_n=int(args.long_n),
        short_n=int(args.short_n),
        max_score_gaps=args.max_score_gaps,
        max_forecast_gaps=args.grid_max_forecast_gaps,
        max_universe_score_stds=args.grid_max_universe_score_stds,
        max_long_ticker_shares="1.0",
        cooldown_cycles="0",
        max_consecutive=args.grid_max_consecutive,
        gate_min_mean_ls=float(args.gate_min_mean_ls),
        gate_min_hit=float(args.gate_min_hit),
        gate_max_drawdown=float(args.gate_max_drawdown),
        gate_min_coverage=float(args.gate_min_coverage),
    )


def _walk_forward_args(args: argparse.Namespace) -> argparse.Namespace:
    gate_args = _gate_grid_args(args)
    gate_args.splits = args.splits
    gate_args.min_train_cycles = int(args.min_train_cycles)
    gate_args.min_test_cycles = int(args.min_test_cycles)
    return gate_args


def _replay_args(args: argparse.Namespace, *, max_consecutive: int = 0, score_start_date: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        shadow_log=args.shadow_log,
        long_n=int(args.long_n),
        short_n=int(args.short_n),
        expected_universe_count=int(args.expected_universe_count),
        max_universe_score_std=float(args.practical_max_universe_score_std),
        max_forecast_gap=float(args.practical_max_forecast_gap),
        max_consecutive=int(max_consecutive),
        start_date=None,
        end_date=None,
        score_start_date=score_start_date,
        score_end_date=None,
    )


def _threshold_sensitivity_args(
    args: argparse.Namespace,
    *,
    score_start_dates: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        shadow_log=args.shadow_log,
        long_n=int(args.long_n),
        short_n=int(args.short_n),
        expected_universe_count=int(args.expected_universe_count),
        max_universe_score_stds=args.sensitivity_max_universe_score_stds,
        max_forecast_gaps=args.sensitivity_max_forecast_gaps,
        max_consecutive=args.sensitivity_max_consecutive,
        score_start_dates=score_start_dates if score_start_dates is not None else args.score_start_dates,
        start_date=None,
        end_date=None,
        score_end_date=None,
        min_holdout_allowed_cycles=int(args.min_holdout_allowed_cycles),
        min_holdout_filter_uplift=float(args.min_holdout_filter_uplift),
        gate_min_hit=float(args.gate_min_hit),
        gate_max_drawdown=float(args.gate_max_drawdown),
    )


def _summary_subset(summary: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "cycles",
        "overlay_allowed_cycles",
        "overlay_abstained_cycles",
        "replacement_cycles",
        "baseline_all_mean_long_short",
        "overlay_allowed_mean_long_short",
        "overlay_allowed_hit_rate",
        "overlay_allowed_max_drawdown",
        "baseline_allowed_mean_long_short",
        "abstained_baseline_mean_long_short",
        "mean_replacement_delta",
        "thresholds",
        "window",
    ]
    return {key: summary.get(key) for key in keys}


def _skip(reason: str) -> dict[str, Any]:
    return {"status": "skipped", "reason": reason}


def _configured_score_start_dates(value: object) -> list[str]:
    return [
        token.strip()
        for token in str(value).split(",")
        if token.strip() and token.strip().lower() not in {"none", "null", "na", "n/a"}
    ]


def _valid_score_start_dates(value: object, start_date: str | None, end_date: str | None) -> list[str]:
    window_start = pd.to_datetime(start_date, errors="coerce")
    window_end = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(window_start) or pd.isna(window_end):
        return []

    valid: list[str] = []
    for token in _configured_score_start_dates(value):
        score_start = pd.to_datetime(token, errors="coerce")
        if pd.notna(score_start) and window_start < score_start <= window_end:
            valid.append(score_start.date().isoformat())
    return valid


def _candidate_status(
    gate_grid: dict[str, Any],
    walk_forward: dict[str, Any],
    sensitivity: dict[str, Any],
    practical: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[str, list[str], list[str]]:
    failures: list[str] = []
    skipped_checks: list[str] = []
    if gate_grid.get("status") != "pass":
        failures.append("gate_grid")
    if walk_forward.get("status") == "skipped":
        skipped_checks.append("walk_forward")
    elif walk_forward.get("status") != "pass":
        failures.append("walk_forward")
    if sensitivity.get("status") == "skipped":
        skipped_checks.append("threshold_sensitivity")
    elif sensitivity.get("status") != "pass":
        failures.append("threshold_sensitivity")

    practical_mean = _safe_float(practical.get("overlay_allowed_mean_long_short"))
    if practical_mean is None or practical_mean < float(args.gate_min_mean_ls):
        failures.append("practical_replay_mean")
    practical_hit = _safe_float(practical.get("overlay_allowed_hit_rate"))
    if practical_hit is None or practical_hit < float(args.gate_min_hit):
        failures.append("practical_replay_hit")
    practical_dd = _safe_float(practical.get("overlay_allowed_max_drawdown"))
    if practical_dd is None or practical_dd < float(args.gate_max_drawdown):
        failures.append("practical_replay_drawdown")

    status = "fail" if failures else "provisional" if skipped_checks else "pass"
    return status, failures, skipped_checks


def build_contract(args: argparse.Namespace) -> dict[str, Any]:
    cycles, start_date, end_date = _available_cycles(args.shadow_log)
    configured_score_starts = _configured_score_start_dates(args.score_start_dates)
    valid_score_starts = _valid_score_start_dates(args.score_start_dates, start_date, end_date)
    valid_score_start_set = set(valid_score_starts)
    gate_grid, _ = build_gate_grid(_gate_grid_args(args))

    if cycles >= int(args.min_train_cycles) + int(args.min_test_cycles):
        walk_forward = build_walk_forward_report(_walk_forward_args(args))
    else:
        walk_forward = _skip(
            f"{cycles} cycles < min train/test requirement "
            f"{int(args.min_train_cycles)}+{int(args.min_test_cycles)}"
        )

    _, practical_replay_summary = build_replay(_replay_args(args, max_consecutive=0))
    _, consecutive_replay_summary = build_replay(_replay_args(args, max_consecutive=int(args.research_max_consecutive)))

    holdouts: list[dict[str, Any]] = []
    for score_start in configured_score_starts:
        canonical_score_start = pd.to_datetime(score_start, errors="coerce")
        canonical_score_start = (
            canonical_score_start.date().isoformat()
            if pd.notna(canonical_score_start)
            else score_start
        )
        if canonical_score_start not in valid_score_start_set:
            holdouts.append(
                {
                    "score_start_date": score_start,
                    **_skip("score start is outside the candidate cycle window"),
                    "summary": _summary_subset({}),
                }
            )
            continue
        _, summary = build_replay(_replay_args(args, max_consecutive=0, score_start_date=canonical_score_start))
        if int(summary.get("cycles") or 0) < int(args.min_holdout_cycles_for_reporting):
            holdouts.append(
                {
                    "score_start_date": canonical_score_start,
                    **_skip("not enough scored holdout cycles"),
                    "summary": _summary_subset(summary),
                }
            )
        else:
            holdouts.append(
                {
                    "score_start_date": canonical_score_start,
                    "status": "scored",
                    "summary": _summary_subset(summary),
                }
            )

    if cycles < int(args.min_cycles_for_sensitivity):
        sensitivity_summary = _skip(f"{cycles} cycles < sensitivity minimum {int(args.min_cycles_for_sensitivity)}")
    elif not valid_score_starts:
        sensitivity_summary = _skip("no valid score-start dates within the candidate cycle window")
    else:
        sensitivity, sensitivity_rows = build_threshold_sensitivity(
            _threshold_sensitivity_args(args, score_start_dates=",".join(valid_score_starts))
        )
        sensitivity_summary = {
            "status": sensitivity.get("status"),
            "config_count": sensitivity.get("config_count"),
            "passing_config_count": sensitivity.get("passing_config_count"),
            "best_config": sensitivity.get("best_config"),
            "top_rows": sensitivity_rows.head(10).to_dict(orient="records"),
        }

    all_sample_best = gate_grid.get("best_config") or {}
    practical = _summary_subset(practical_replay_summary)
    candidate_status, failures, skipped_checks = _candidate_status(
        gate_grid,
        walk_forward,
        sensitivity_summary,
        practical,
        args,
    )

    return {
        "status": candidate_status,
        "failures": failures,
        "skipped_checks": skipped_checks,
        "paper_only": True,
        "live_policy_changed": False,
        "paper_plan_changed": False,
        "shadow_log": str(args.shadow_log),
        "cycles": cycles,
        "cycle_window": {"start": start_date, "end": end_date},
        "contract": {
            "long_n": int(args.long_n),
            "short_n": int(args.short_n),
            "expected_universe_count": int(args.expected_universe_count),
            "practical_max_universe_score_std": float(args.practical_max_universe_score_std),
            "practical_max_forecast_gap": float(args.practical_max_forecast_gap),
            "practical_max_consecutive": 0,
            "research_max_consecutive": int(args.research_max_consecutive),
        },
        "gate_grid": {
            "status": gate_grid.get("status"),
            "passing_config_count": gate_grid.get("passing_config_count"),
            "available_days": gate_grid.get("available_days"),
            "baseline": gate_grid.get("baseline"),
            "best_config": all_sample_best,
        },
        "walk_forward": walk_forward,
        "practical_replay": practical,
        "research_consecutive_replay": _summary_subset(consecutive_replay_summary),
        "holdouts": holdouts,
        "threshold_sensitivity": sensitivity_summary,
    }


def _markdown(report: dict[str, Any]) -> str:
    gate_best = report["gate_grid"].get("best_config") or {}
    gate_best_summary = gate_best.get("summary") or {}
    practical = report["practical_replay"]
    sensitivity = report["threshold_sensitivity"]
    sensitivity_best = (sensitivity.get("best_config") or {}) if sensitivity.get("status") != "skipped" else {}
    sensitivity_best_aggregate = sensitivity_best.get("aggregate") or {}
    lines = [
        "# Growth24 Candidate Contract Evaluation",
        "",
        f"- Shadow log: `{report['shadow_log']}`",
        f"- Status: `{report['status']}`",
        f"- Failures: {', '.join(report['failures']) if report['failures'] else 'none'}",
        f"- Skipped checks: {', '.join(report.get('skipped_checks', [])) if report.get('skipped_checks') else 'none'}",
        f"- Cycles: {report['cycles']}",
        f"- Window: {report['cycle_window']['start']} -> {report['cycle_window']['end']}",
        f"- Paper only: {report['paper_only']}",
        f"- Live policy changed: {report['live_policy_changed']}",
        f"- Paper plan changed: {report['paper_plan_changed']}",
        "",
        "## Practical Replay",
        "",
        f"- Allowed cycles: {practical.get('overlay_allowed_cycles')} / {practical.get('cycles')}",
        f"- Overlay mean LS: {_fmt_pct(practical.get('overlay_allowed_mean_long_short'))}",
        f"- Overlay hit rate: {_fmt_pct(practical.get('overlay_allowed_hit_rate'))}",
        f"- Overlay max drawdown: {_fmt_pct(practical.get('overlay_allowed_max_drawdown'))}",
        f"- Baseline all-cycle mean LS: {_fmt_pct(practical.get('baseline_all_mean_long_short'))}",
        f"- Abstained baseline mean LS: {_fmt_pct(practical.get('abstained_baseline_mean_long_short'))}",
        "",
        "## Gate Grid",
        "",
        f"- Status: `{report['gate_grid'].get('status')}`",
        f"- Passing configs: {report['gate_grid'].get('passing_config_count')}",
        f"- Best config: `{gate_best.get('name', 'n/a')}`",
        f"- Best mean LS: {_fmt_pct(gate_best_summary.get('mean_long_short_return'))}",
        f"- Best hit rate: {_fmt_pct(gate_best_summary.get('spread_hit_rate'))}",
        f"- Best max drawdown: {_fmt_pct(gate_best_summary.get('max_drawdown'))}",
        "",
        "## Walk Forward",
        "",
        f"- Status: `{report['walk_forward'].get('status')}`",
        f"- Passing splits: {report['walk_forward'].get('passing_split_count', 'n/a')} / {len(report['walk_forward'].get('splits', []))}",
        "",
        "## Threshold Sensitivity",
        "",
        f"- Status: `{sensitivity.get('status')}`",
        f"- Passing configs: {sensitivity.get('passing_config_count', 'n/a')}",
        f"- Best config: `{sensitivity_best.get('name', 'n/a')}`",
        f"- Minimum holdout uplift: {_fmt_pct(sensitivity_best_aggregate.get('min_holdout_filter_uplift'))}",
        f"- Minimum holdout LS: {_fmt_pct(sensitivity_best_aggregate.get('min_holdout_overlay_mean_long_short'))}",
        "",
        "## Holdouts",
        "",
        "| Score Start | Status | Allowed | Baseline Mean LS | Overlay Mean LS | Hit | Max DD |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for holdout in report["holdouts"]:
        summary = holdout["summary"]
        lines.append(
            f"| {holdout['score_start_date']} | {holdout['status']} | "
            f"{summary.get('overlay_allowed_cycles')} / {summary.get('cycles')} | "
            f"{_fmt_pct(summary.get('baseline_all_mean_long_short'))} | "
            f"{_fmt_pct(summary.get('overlay_allowed_mean_long_short'))} | "
            f"{_fmt_pct(summary.get('overlay_allowed_hit_rate'))} | "
            f"{_fmt_pct(summary.get('overlay_allowed_max_drawdown'))} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a Growth24 candidate shadow log against the fixed contract.")
    parser.add_argument("--shadow-log", type=Path, default=DEFAULT_SHADOW_LOG)
    parser.add_argument("--long-n", type=int, default=2)
    parser.add_argument("--short-n", type=int, default=2)
    parser.add_argument("--expected-universe-count", type=int, default=24)
    parser.add_argument("--practical-max-universe-score-std", type=float, default=0.085)
    parser.add_argument("--practical-max-forecast-gap", type=float, default=4.0)
    parser.add_argument("--research-max-consecutive", type=int, default=3)
    parser.add_argument("--max-score-gaps", default="none,0.36,0.32")
    parser.add_argument("--grid-max-forecast-gaps", default="none,3.0,4.0,5.0")
    parser.add_argument("--grid-max-universe-score-stds", default="none,0.08,0.085,0.09")
    parser.add_argument("--grid-max-consecutive", default="0,3")
    parser.add_argument("--splits", default="18,24")
    parser.add_argument("--min-train-cycles", type=int, default=12)
    parser.add_argument("--min-test-cycles", type=int, default=8)
    parser.add_argument("--score-start-dates", default="2024-10-11,2025-04-15")
    parser.add_argument("--min-holdout-cycles-for-reporting", type=int, default=4)
    parser.add_argument("--min-cycles-for-sensitivity", type=int, default=20)
    parser.add_argument("--sensitivity-max-universe-score-stds", default="0.08,0.085,0.09")
    parser.add_argument("--sensitivity-max-forecast-gaps", default="3.0,4.0,5.0")
    parser.add_argument("--sensitivity-max-consecutive", default="0,3")
    parser.add_argument("--min-holdout-allowed-cycles", type=int, default=4)
    parser.add_argument("--min-holdout-filter-uplift", type=float, default=0.0)
    parser.add_argument("--gate-min-mean-ls", type=float, default=0.0)
    parser.add_argument("--gate-min-hit", type=float, default=0.50)
    parser.add_argument("--gate-max-drawdown", type=float, default=-0.25)
    parser.add_argument("--gate-min-coverage", type=float, default=0.25)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    report = build_contract(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(report), indent=2), encoding="utf-8")
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    practical = report["practical_replay"]
    print(f"Status: {report['status']}")
    print(f"Cycles: {report['cycles']}")
    print(
        "Practical replay: "
        f"allowed={practical.get('overlay_allowed_cycles')}/{practical.get('cycles')} "
        f"mean_ls={_fmt_pct(practical.get('overlay_allowed_mean_long_short'))} "
        f"hit={_fmt_pct(practical.get('overlay_allowed_hit_rate'))} "
        f"max_dd={_fmt_pct(practical.get('overlay_allowed_max_drawdown'))}"
    )
    print(f"Gate grid: {report['gate_grid'].get('status')}")
    print(f"Walk-forward: {report['walk_forward'].get('status')}")
    print(f"Threshold sensitivity: {report['threshold_sensitivity'].get('status')}")
    print(f"Saved -> {args.output}")
    print(f"Saved -> {args.markdown_output}")


if __name__ == "__main__":
    main()
