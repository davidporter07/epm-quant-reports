"""Test Growth24 paper-policy threshold robustness across holdout windows.

This is research-only. It reuses the historical paper-policy replay over nearby
dispersion and forecast-gap thresholds, then checks whether each threshold set
survives warmup-aware temporal holdouts. It does not change live policy, paper
plans, scheduled tasks, or email behavior.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from dl_growth24_current_control_gate import DEFAULT_FORECAST_GAP_MAX, DEFAULT_UNIVERSE_SCORE_STD_MAX
from dl_growth24_post_prediction_gate_grid import DEFAULT_SHADOW_LOG, _fmt_pct, _json_safe
import dl_growth24_shadow_policy_replay as shadow_policy_replay


DEFAULT_OUTPUT = DEFAULT_SHADOW_LOG.with_name(f"{DEFAULT_SHADOW_LOG.stem}_policy_threshold_sensitivity.json")
DEFAULT_CSV_OUTPUT = DEFAULT_SHADOW_LOG.with_name(f"{DEFAULT_SHADOW_LOG.stem}_policy_threshold_sensitivity.csv")
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_36c_8e_policy_threshold_sensitivity.md")
DEFAULT_SCORE_START_DATES = "2024-10-11,2025-04-15"


def _split_grid(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = str(value).split(",")
    return [str(part).strip() for part in parts if str(part).strip()]


def _parse_float_grid(value: Any) -> list[float]:
    return [float(part) for part in _split_grid(value)]


def _parse_int_grid(value: Any) -> list[int]:
    return [int(part) for part in _split_grid(value)]


def _parse_date_grid(value: Any) -> list[str]:
    out: list[str] = []
    for part in _split_grid(value):
        if part.lower() in {"none", "null", "na", "n/a"}:
            continue
        out.append(pd.Timestamp(part).date().isoformat())
    return out


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _diff(left: Any, right: Any) -> float | None:
    left_float = _finite_float(left)
    right_float = _finite_float(right)
    if left_float is None or right_float is None:
        return None
    return left_float - right_float


def _summary_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    overlay_mean = _finite_float(summary.get("overlay_allowed_mean_long_short"))
    baseline_all_mean = _finite_float(summary.get("baseline_all_mean_long_short"))
    baseline_allowed_mean = _finite_float(summary.get("baseline_allowed_mean_long_short"))
    return {
        "cycles": int(summary.get("cycles") or 0),
        "overlay_allowed_cycles": int(summary.get("overlay_allowed_cycles") or 0),
        "overlay_abstained_cycles": int(summary.get("overlay_abstained_cycles") or 0),
        "replacement_cycles": int(summary.get("replacement_cycles") or 0),
        "baseline_all_mean_long_short": baseline_all_mean,
        "baseline_allowed_mean_long_short": baseline_allowed_mean,
        "overlay_allowed_mean_long_short": overlay_mean,
        "overlay_allowed_hit_rate": _finite_float(summary.get("overlay_allowed_hit_rate")),
        "overlay_allowed_max_drawdown": _finite_float(summary.get("overlay_allowed_max_drawdown")),
        "abstained_baseline_mean_long_short": _finite_float(summary.get("abstained_baseline_mean_long_short")),
        "mean_replacement_delta": _finite_float(summary.get("mean_replacement_delta")),
        "filter_uplift_vs_baseline_all": _diff(overlay_mean, baseline_all_mean),
        "selection_uplift_vs_baseline_allowed": _diff(overlay_mean, baseline_allowed_mean),
        "replacement_ticker_counts": summary.get("replacement_ticker_counts", {}),
        "window": summary.get("window", {}),
    }


def _replay_args(
    args: argparse.Namespace,
    *,
    max_universe_score_std: float,
    max_forecast_gap: float,
    max_consecutive: int,
    score_start_date: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        shadow_log=args.shadow_log,
        long_n=int(args.long_n),
        short_n=int(args.short_n),
        expected_universe_count=int(args.expected_universe_count),
        max_universe_score_std=float(max_universe_score_std),
        max_forecast_gap=float(max_forecast_gap),
        max_consecutive=int(max_consecutive),
        start_date=args.start_date,
        end_date=args.end_date,
        score_start_date=score_start_date,
        score_end_date=args.score_end_date,
    )


def _run_replay(
    args: argparse.Namespace,
    *,
    max_universe_score_std: float,
    max_forecast_gap: float,
    max_consecutive: int,
    score_start_date: str | None = None,
) -> dict[str, Any]:
    _, summary = shadow_policy_replay.build_replay(
        _replay_args(
            args,
            max_universe_score_std=max_universe_score_std,
            max_forecast_gap=max_forecast_gap,
            max_consecutive=max_consecutive,
            score_start_date=score_start_date,
        )
    )
    return _summary_metrics(summary)


def _config_name(config: dict[str, Any]) -> str:
    return (
        f"universe_score_std_max={float(config['max_universe_score_std']):g}; "
        f"forecast_gap_max={float(config['max_forecast_gap']):g}; "
        f"max_consecutive={int(config['max_consecutive'])}"
    )


def _holdout_gate(metrics: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    failures: list[str] = []
    allowed = int(metrics.get("overlay_allowed_cycles") or 0)
    if allowed < int(args.min_holdout_allowed_cycles):
        failures.append(f"allowed cycles {allowed} < {int(args.min_holdout_allowed_cycles)}")
    uplift = _finite_float(metrics.get("filter_uplift_vs_baseline_all"))
    if uplift is None or uplift < float(args.min_holdout_filter_uplift):
        failures.append(
            f"filter uplift {uplift:.6f} < {float(args.min_holdout_filter_uplift):.6f}"
            if uplift is not None
            else "filter uplift missing"
        )
    hit_rate = _finite_float(metrics.get("overlay_allowed_hit_rate"))
    if hit_rate is None or hit_rate < float(args.gate_min_hit):
        failures.append(
            f"hit rate {hit_rate:.2%} < {float(args.gate_min_hit):.2%}"
            if hit_rate is not None
            else "hit rate missing"
        )
    max_drawdown = _finite_float(metrics.get("overlay_allowed_max_drawdown"))
    if max_drawdown is None or max_drawdown < float(args.gate_max_drawdown):
        failures.append(
            f"max drawdown {max_drawdown:.2%} < {float(args.gate_max_drawdown):.2%}"
            if max_drawdown is not None
            else "max drawdown missing"
        )
    return {"status": "pass" if not failures else "fail", "failures": failures}


def _aggregate_holdouts(holdouts: list[dict[str, Any]]) -> dict[str, Any]:
    def values(key: str) -> list[float]:
        return [float(value) for item in holdouts if (value := _finite_float(item["metrics"].get(key))) is not None]

    allowed_values = [int(item["metrics"].get("overlay_allowed_cycles") or 0) for item in holdouts]
    return {
        "holdout_count": int(len(holdouts)),
        "holdout_pass_count": int(sum(1 for item in holdouts if item["gate"]["status"] == "pass")),
        "min_holdout_allowed_cycles": int(min(allowed_values)) if allowed_values else 0,
        "min_holdout_filter_uplift": min(values("filter_uplift_vs_baseline_all"), default=None),
        "min_holdout_selection_uplift": min(values("selection_uplift_vs_baseline_allowed"), default=None),
        "min_holdout_overlay_mean_long_short": min(values("overlay_allowed_mean_long_short"), default=None),
        "min_holdout_hit_rate": min(values("overlay_allowed_hit_rate"), default=None),
        "worst_holdout_max_drawdown": min(values("overlay_allowed_max_drawdown"), default=None),
    }


def _robust_gate(holdouts: list[dict[str, Any]]) -> dict[str, Any]:
    if not holdouts:
        return {"status": "fail", "failures": ["no holdout score-start dates configured"]}
    failures: list[str] = []
    for item in holdouts:
        if item["gate"]["status"] != "pass":
            failures.append(f"{item['score_start_date']}: {'; '.join(item['gate']['failures'])}")
    return {"status": "pass" if not failures else "fail", "failures": failures}


def _rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
    aggregate = item["aggregate"]
    all_sample = item["all_sample"]
    return (
        item["robust_gate"]["status"] != "pass",
        -float(aggregate["min_holdout_filter_uplift"] if aggregate["min_holdout_filter_uplift"] is not None else -1.0e9),
        -float(
            aggregate["min_holdout_overlay_mean_long_short"]
            if aggregate["min_holdout_overlay_mean_long_short"] is not None
            else -1.0e9
        ),
        -float(aggregate["worst_holdout_max_drawdown"] if aggregate["worst_holdout_max_drawdown"] is not None else -1.0e9),
        int(item["config"]["max_consecutive"]) > 0,
        -float(all_sample["overlay_allowed_mean_long_short"] if all_sample["overlay_allowed_mean_long_short"] is not None else -1.0e9),
        -int(all_sample["overlay_allowed_cycles"]),
    )


def _flat_row(item: dict[str, Any]) -> dict[str, Any]:
    config = item["config"]
    all_sample = item["all_sample"]
    aggregate = item["aggregate"]
    return {
        "status": item["robust_gate"]["status"],
        "name": item["name"],
        "max_universe_score_std": float(config["max_universe_score_std"]),
        "max_forecast_gap": float(config["max_forecast_gap"]),
        "max_consecutive": int(config["max_consecutive"]),
        "holdout_pass_count": aggregate["holdout_pass_count"],
        "holdout_count": aggregate["holdout_count"],
        "min_holdout_allowed_cycles": aggregate["min_holdout_allowed_cycles"],
        "min_holdout_filter_uplift": aggregate["min_holdout_filter_uplift"],
        "min_holdout_selection_uplift": aggregate["min_holdout_selection_uplift"],
        "min_holdout_overlay_mean_long_short": aggregate["min_holdout_overlay_mean_long_short"],
        "min_holdout_hit_rate": aggregate["min_holdout_hit_rate"],
        "worst_holdout_max_drawdown": aggregate["worst_holdout_max_drawdown"],
        "all_cycles": all_sample["cycles"],
        "all_overlay_allowed_cycles": all_sample["overlay_allowed_cycles"],
        "all_replacement_cycles": all_sample["replacement_cycles"],
        "all_baseline_mean_long_short": all_sample["baseline_all_mean_long_short"],
        "all_overlay_mean_long_short": all_sample["overlay_allowed_mean_long_short"],
        "all_filter_uplift": all_sample["filter_uplift_vs_baseline_all"],
        "all_selection_uplift": all_sample["selection_uplift_vs_baseline_allowed"],
        "all_hit_rate": all_sample["overlay_allowed_hit_rate"],
        "all_max_drawdown": all_sample["overlay_allowed_max_drawdown"],
        "failures": " | ".join(item["robust_gate"]["failures"]),
    }


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame]:
    configs: list[dict[str, Any]] = []
    score_start_dates = _parse_date_grid(args.score_start_dates)
    original_loader = shadow_policy_replay._load_shadow_log
    cached_rows = original_loader(args.shadow_log)
    shadow_policy_replay._load_shadow_log = lambda _: cached_rows.copy()
    try:
        for max_universe_score_std in _parse_float_grid(args.max_universe_score_stds):
            for max_forecast_gap in _parse_float_grid(args.max_forecast_gaps):
                for max_consecutive in _parse_int_grid(args.max_consecutive):
                    config = {
                        "max_universe_score_std": float(max_universe_score_std),
                        "max_forecast_gap": float(max_forecast_gap),
                        "max_consecutive": int(max_consecutive),
                    }
                    all_sample = _run_replay(
                        args,
                        max_universe_score_std=float(max_universe_score_std),
                        max_forecast_gap=float(max_forecast_gap),
                        max_consecutive=int(max_consecutive),
                    )
                    holdouts: list[dict[str, Any]] = []
                    for score_start_date in score_start_dates:
                        metrics = _run_replay(
                            args,
                            max_universe_score_std=float(max_universe_score_std),
                            max_forecast_gap=float(max_forecast_gap),
                            max_consecutive=int(max_consecutive),
                            score_start_date=score_start_date,
                        )
                        holdouts.append(
                            {
                                "score_start_date": score_start_date,
                                "metrics": metrics,
                                "gate": _holdout_gate(metrics, args),
                            }
                        )
                    configs.append(
                        {
                            "name": _config_name(config),
                            "config": config,
                            "all_sample": all_sample,
                            "holdouts": holdouts,
                            "aggregate": _aggregate_holdouts(holdouts),
                            "robust_gate": _robust_gate(holdouts),
                        }
                    )
    finally:
        shadow_policy_replay._load_shadow_log = original_loader

    configs.sort(key=_rank_key)
    rows = pd.DataFrame([_flat_row(item) for item in configs])
    passing = [item for item in configs if item["robust_gate"]["status"] == "pass"]
    report = {
        "status": "pass" if passing else "fail",
        "paper_only": True,
        "live_policy_changed": False,
        "paper_plan_changed": False,
        "shadow_log": str(args.shadow_log),
        "long_n": int(args.long_n),
        "short_n": int(args.short_n),
        "expected_universe_count": int(args.expected_universe_count),
        "score_start_dates": score_start_dates,
        "gate_config": {
            "min_holdout_allowed_cycles": int(args.min_holdout_allowed_cycles),
            "min_holdout_filter_uplift": float(args.min_holdout_filter_uplift),
            "min_hit": float(args.gate_min_hit),
            "max_drawdown": float(args.gate_max_drawdown),
        },
        "config_count": int(len(configs)),
        "passing_config_count": int(len(passing)),
        "best_config": configs[0] if configs else None,
        "configs": configs,
    }
    return report, rows


def _markdown(report: dict[str, Any]) -> str:
    best = report.get("best_config") or {}
    best_aggregate = best.get("aggregate") or {}
    lines = [
        "# Growth24 Paper-Policy Threshold Sensitivity",
        "",
        f"- Paper only: {report['paper_only']}",
        f"- Live policy changed: {report['live_policy_changed']}",
        f"- Paper plan changed: {report['paper_plan_changed']}",
        f"- Shadow log: `{report['shadow_log']}`",
        f"- Score start dates: {', '.join(report['score_start_dates'])}",
        f"- Configs tested: {report['config_count']}",
        f"- Passing configs: {report['passing_config_count']}",
        f"- Overall status: `{report['status']}`",
        "",
        "## Best Robust Config",
        "",
    ]
    if best:
        all_sample = best["all_sample"]
        lines.extend(
            [
                f"- Config: `{best['name']}`",
                f"- Full-sample allowed cycles: {all_sample['overlay_allowed_cycles']} / {all_sample['cycles']}",
                f"- Full-sample overlay mean LS: {_fmt_pct(all_sample['overlay_allowed_mean_long_short'])}",
                f"- Full-sample filter uplift: {_fmt_pct(all_sample['filter_uplift_vs_baseline_all'])}",
                f"- Full-sample selection uplift: {_fmt_pct(all_sample['selection_uplift_vs_baseline_allowed'])}",
                f"- Full-sample replacement cycles: {all_sample['replacement_cycles']}",
                f"- Minimum holdout allowed cycles: {best_aggregate.get('min_holdout_allowed_cycles')}",
                f"- Minimum holdout filter uplift: {_fmt_pct(best_aggregate.get('min_holdout_filter_uplift'))}",
                f"- Minimum holdout overlay mean LS: {_fmt_pct(best_aggregate.get('min_holdout_overlay_mean_long_short'))}",
                f"- Worst holdout max drawdown: {_fmt_pct(best_aggregate.get('worst_holdout_max_drawdown'))}",
            ]
        )
    else:
        lines.append("- n/a")

    lines.extend(
        [
            "",
            "## Top Configs",
            "",
            "| Status | Config | Holdout Passes | Min Holdout Allowed | Min Holdout Uplift | Min Holdout LS | Worst Holdout DD | All Allowed | All Mean LS | All Replacements |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in report["configs"][:25]:
        aggregate = item["aggregate"]
        all_sample = item["all_sample"]
        lines.append(
            f"| {item['robust_gate']['status']} | {item['name']} | "
            f"{aggregate['holdout_pass_count']} / {aggregate['holdout_count']} | "
            f"{aggregate['min_holdout_allowed_cycles']} | "
            f"{_fmt_pct(aggregate['min_holdout_filter_uplift'])} | "
            f"{_fmt_pct(aggregate['min_holdout_overlay_mean_long_short'])} | "
            f"{_fmt_pct(aggregate['worst_holdout_max_drawdown'])} | "
            f"{all_sample['overlay_allowed_cycles']} / {all_sample['cycles']} | "
            f"{_fmt_pct(all_sample['overlay_allowed_mean_long_short'])} | "
            f"{all_sample['replacement_cycles']} |"
        )

    lines.extend(
        [
            "",
            "## Holdout Detail",
            "",
            "| Config | Score Start | Status | Allowed | Baseline Mean LS | Overlay Mean LS | Filter Uplift | Hit | Max DD | Failures |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for item in report["configs"][:10]:
        for holdout in item["holdouts"]:
            metrics = holdout["metrics"]
            lines.append(
                f"| {item['name']} | {holdout['score_start_date']} | {holdout['gate']['status']} | "
                f"{metrics['overlay_allowed_cycles']} / {metrics['cycles']} | "
                f"{_fmt_pct(metrics['baseline_all_mean_long_short'])} | "
                f"{_fmt_pct(metrics['overlay_allowed_mean_long_short'])} | "
                f"{_fmt_pct(metrics['filter_uplift_vs_baseline_all'])} | "
                f"{_fmt_pct(metrics['overlay_allowed_hit_rate'])} | "
                f"{_fmt_pct(metrics['overlay_allowed_max_drawdown'])} | "
                f"{'; '.join(holdout['gate']['failures'])} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Growth24 paper-policy threshold robustness.")
    parser.add_argument("--shadow-log", type=Path, default=DEFAULT_SHADOW_LOG)
    parser.add_argument("--long-n", type=int, default=2)
    parser.add_argument("--short-n", type=int, default=2)
    parser.add_argument("--expected-universe-count", type=int, default=24)
    parser.add_argument("--max-universe-score-stds", default="0.08,0.085,0.09")
    parser.add_argument("--max-forecast-gaps", default=f"3.0,{DEFAULT_FORECAST_GAP_MAX:g},5.0")
    parser.add_argument("--max-consecutive", default="0,3")
    parser.add_argument("--score-start-dates", default=DEFAULT_SCORE_START_DATES)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--score-end-date", default=None)
    parser.add_argument("--min-holdout-allowed-cycles", type=int, default=4)
    parser.add_argument("--min-holdout-filter-uplift", type=float, default=0.0)
    parser.add_argument("--gate-min-hit", type=float, default=0.50)
    parser.add_argument("--gate-max-drawdown", type=float, default=-0.25)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    report, rows = build_report(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(report), indent=2), encoding="utf-8")
    rows.to_csv(args.csv_output, index=False)
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    best = report.get("best_config") or {}
    best_aggregate = best.get("aggregate") or {}
    all_sample = best.get("all_sample") or {}
    print(f"Status: {report['status']}")
    print(f"Configs tested: {report['config_count']}")
    print(f"Passing configs: {report['passing_config_count']}")
    print(f"Best: {best.get('name', 'n/a')}")
    print(
        "Best holdout floor: "
        f"uplift={_fmt_pct(best_aggregate.get('min_holdout_filter_uplift'))} "
        f"mean_ls={_fmt_pct(best_aggregate.get('min_holdout_overlay_mean_long_short'))} "
        f"allowed={best_aggregate.get('min_holdout_allowed_cycles', 'n/a')}"
    )
    print(
        "Best all-sample: "
        f"allowed={all_sample.get('overlay_allowed_cycles', 'n/a')} "
        f"mean_ls={_fmt_pct(all_sample.get('overlay_allowed_mean_long_short'))} "
        f"replacement_cycles={all_sample.get('replacement_cycles', 'n/a')}"
    )
    print(f"Saved -> {args.output}")
    print(f"Saved -> {args.csv_output}")
    print(f"Saved -> {args.markdown_output}")


if __name__ == "__main__":
    main()
