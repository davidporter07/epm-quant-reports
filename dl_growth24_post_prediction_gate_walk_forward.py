"""Walk-forward validation for Growth24 post-prediction gates.

This is research-only. It selects a gate configuration on earlier saved shadow
cycles, then evaluates that selected configuration on later cycles to reduce
the chance that a gate-grid win is just in-sample overfitting.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from dl_growth24_post_prediction_gate_grid import (
    DEFAULT_SHADOW_LOG,
    _build_config_ledger,
    _config_name,
    _config_rank_key,
    _cycle_frame,
    _fmt_num,
    _fmt_pct,
    _gate_status,
    _json_safe,
    _load_shadow_log,
    _parse_float_grid,
    _parse_int_grid,
    _safe_float,
    _summarize,
)


DEFAULT_OUTPUT = DEFAULT_SHADOW_LOG.with_name(f"{DEFAULT_SHADOW_LOG.stem}_post_prediction_gate_walk_forward.json")
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_36c_8e_post_prediction_gate_walk_forward.md")


def _parse_split_grid(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def _config_grid(args: argparse.Namespace) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    for max_score_gap in _parse_float_grid(args.max_score_gaps):
        for max_forecast_gap in _parse_float_grid(args.max_forecast_gaps):
            for max_universe_score_std in _parse_float_grid(args.max_universe_score_stds):
                for max_long_ticker_share in _parse_float_grid(args.max_long_ticker_shares, include_none=False):
                    for cooldown_cycles in _parse_int_grid(args.cooldown_cycles):
                        for max_consecutive in _parse_int_grid(args.max_consecutive):
                            configs.append(
                                {
                                    "max_score_gap": max_score_gap,
                                    "max_forecast_gap": max_forecast_gap,
                                    "max_universe_score_std": max_universe_score_std,
                                    "max_long_ticker_share": float(max_long_ticker_share),
                                    "cooldown_cycles": int(cooldown_cycles),
                                    "max_consecutive": int(max_consecutive),
                                }
                            )
    return configs


def _cycle_bounds(cycles: pd.DataFrame) -> dict[str, str]:
    if cycles.empty:
        return {"start": "", "end": ""}
    return {"start": str(cycles["AsOfDate"].iloc[0]), "end": str(cycles["AsOfDate"].iloc[-1])}


def _evaluate_configs(
    rows: pd.DataFrame,
    cycles: pd.DataFrame,
    configs: list[dict[str, Any]],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    available_days = int(len(cycles))
    for config in configs:
        ledger = _build_config_ledger(rows, cycles, config, int(args.long_n), int(args.short_n))
        summary = _summarize(ledger, available_days, int(args.long_n))
        out.append(
            {
                "name": _config_name(config),
                "config": config,
                "summary": summary,
                "gate": _gate_status(summary, args),
            }
        )
    out.sort(key=_config_rank_key)
    return out


def _split_report(
    rows: pd.DataFrame,
    cycles: pd.DataFrame,
    configs: list[dict[str, Any]],
    split_index: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    train_cycles = cycles.iloc[:split_index].copy()
    test_cycles = cycles.iloc[split_index:].copy()
    train_configs = _evaluate_configs(rows, train_cycles, configs, args)
    selected = train_configs[0] if train_configs else None
    baseline_test = _summarize(test_cycles, int(len(test_cycles)), int(args.long_n))

    selected_test: dict[str, Any]
    if selected:
        ledger = _build_config_ledger(rows, test_cycles, selected["config"], int(args.long_n), int(args.short_n))
        summary = _summarize(ledger, int(len(test_cycles)), int(args.long_n))
        baseline_delta = _safe_float(summary.get("mean_long_short_return")) - _safe_float(
            baseline_test.get("mean_long_short_return")
        )
        selected_test = {
            "summary": summary,
            "gate": _gate_status(summary, args),
            "ledger_trade_days": int(len(ledger)),
            "baseline_mean_delta": baseline_delta,
            "beats_baseline": bool(baseline_delta >= 0.0),
        }
    else:
        selected_test = {
            "summary": {"status": "no_configs", "trade_days": 0, "coverage": 0.0},
            "gate": {"status": "fail", "failures": ["no configs"]},
            "ledger_trade_days": 0,
            "baseline_mean_delta": float("nan"),
            "beats_baseline": False,
        }

    return {
        "split_index": int(split_index),
        "train_cycles": int(len(train_cycles)),
        "test_cycles": int(len(test_cycles)),
        "train_window": _cycle_bounds(train_cycles),
        "test_window": _cycle_bounds(test_cycles),
        "selected_train_config": selected,
        "selected_test": selected_test,
        "baseline_test": baseline_test,
    }


def build_walk_forward_report(args: argparse.Namespace) -> dict[str, Any]:
    rows = _load_shadow_log(args.shadow_log)
    cycles = _cycle_frame(rows, int(args.long_n), int(args.short_n))
    configs = _config_grid(args)
    all_sample_configs = _evaluate_configs(rows, cycles, configs, args)
    split_indices = [
        split
        for split in _parse_split_grid(args.splits)
        if split >= int(args.min_train_cycles) and int(len(cycles)) - split >= int(args.min_test_cycles)
    ]
    splits = [_split_report(rows, cycles, configs, split, args) for split in split_indices]
    passing_splits = [
        item
        for item in splits
        if item["selected_train_config"]["gate"]["status"] == "pass" and item["selected_test"]["gate"]["status"] == "pass"
        and item["selected_test"]["beats_baseline"]
    ]

    return {
        "status": "pass" if splits and len(passing_splits) == len(splits) else "fail",
        "shadow_log": str(args.shadow_log),
        "long_n": int(args.long_n),
        "short_n": int(args.short_n),
        "available_cycles": int(len(cycles)),
        "evaluated_config_count": int(len(configs)),
        "requested_splits": _parse_split_grid(args.splits),
        "valid_splits": split_indices,
        "gate_config": {
            "min_mean_ls": float(args.gate_min_mean_ls),
            "min_hit": float(args.gate_min_hit),
            "max_drawdown": float(args.gate_max_drawdown),
            "min_coverage": float(args.gate_min_coverage),
            "requires_holdout_baseline_uplift": True,
        },
        "all_sample_best": all_sample_configs[0] if all_sample_configs else None,
        "splits": splits,
        "passing_split_count": int(len(passing_splits)),
    }


def _markdown(report: dict[str, Any]) -> str:
    best = report.get("all_sample_best") or {}
    best_summary = best.get("summary") or {}
    lines = [
        "# Growth24 Post-Prediction Gate Walk-Forward",
        "",
        f"- Shadow log: `{report['shadow_log']}`",
        f"- Long/short book: top {report['long_n']} / bottom {report['short_n']}",
        f"- Available cycles: {report['available_cycles']}",
        f"- Evaluated configs: {report['evaluated_config_count']}",
        f"- Valid splits: {report['valid_splits']}",
        f"- Overall status: `{report['status']}`",
        f"- Passing splits: {report['passing_split_count']} / {len(report['splits'])}",
        "",
        "## All-Sample Reference",
        "",
        "| Config | Days | Coverage | Mean LS | Hit | Max DD | Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|",
        (
            f"| {best.get('name', 'n/a')} | {best_summary.get('trade_days', 0)} | "
            f"{_fmt_pct(best_summary.get('coverage'))} | "
            f"{_fmt_pct(best_summary.get('mean_long_short_return'))} | "
            f"{_fmt_pct(best_summary.get('spread_hit_rate'))} | "
            f"{_fmt_pct(best_summary.get('max_drawdown'))} | "
            f"{_fmt_num(best_summary.get('naive_sharpe'))} |"
        ),
        "",
        "## Walk-Forward Splits",
        "",
        (
            "| Split | Train Window | Test Window | Selected Config | "
            "Train Mean LS | Train Hit | Train DD | Test Mean LS | Test Hit | Test DD | "
            "Test Coverage | Test Status | Baseline Test Mean LS | Test Uplift | Accepted |"
        ),
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|",
    ]
    for item in report["splits"]:
        selected = item["selected_train_config"] or {}
        train_summary = selected.get("summary") or {}
        test = item["selected_test"]
        test_summary = test["summary"]
        baseline = item["baseline_test"]
        lines.append(
            f"| {item['split_index']} | "
            f"{item['train_window']['start']} -> {item['train_window']['end']} | "
            f"{item['test_window']['start']} -> {item['test_window']['end']} | "
            f"{selected.get('name', 'n/a')} | "
            f"{_fmt_pct(train_summary.get('mean_long_short_return'))} | "
            f"{_fmt_pct(train_summary.get('spread_hit_rate'))} | "
            f"{_fmt_pct(train_summary.get('max_drawdown'))} | "
            f"{_fmt_pct(test_summary.get('mean_long_short_return'))} | "
            f"{_fmt_pct(test_summary.get('spread_hit_rate'))} | "
            f"{_fmt_pct(test_summary.get('max_drawdown'))} | "
            f"{_fmt_pct(test_summary.get('coverage'))} | "
            f"{test['gate']['status']} | "
            f"{_fmt_pct(baseline.get('mean_long_short_return'))} | "
            f"{_fmt_pct(test.get('baseline_mean_delta'))} | "
            f"{'yes' if test.get('beats_baseline') else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward validate Growth24 post-prediction gates.")
    parser.add_argument("--shadow-log", type=Path, default=DEFAULT_SHADOW_LOG)
    parser.add_argument("--long-n", type=int, default=2)
    parser.add_argument("--short-n", type=int, default=2)
    parser.add_argument("--splits", default="18,24")
    parser.add_argument("--min-train-cycles", type=int, default=12)
    parser.add_argument("--min-test-cycles", type=int, default=8)
    parser.add_argument("--max-score-gaps", default="none,0.36,0.32")
    parser.add_argument("--max-forecast-gaps", default="none,4.0")
    parser.add_argument("--max-universe-score-stds", default="none,0.09,0.085")
    parser.add_argument("--max-long-ticker-shares", default="1.0,0.5")
    parser.add_argument("--cooldown-cycles", default="0,2")
    parser.add_argument("--max-consecutive", default="0,3")
    parser.add_argument("--gate-min-mean-ls", type=float, default=0.0)
    parser.add_argument("--gate-min-hit", type=float, default=0.50)
    parser.add_argument("--gate-max-drawdown", type=float, default=-0.25)
    parser.add_argument("--gate-min-coverage", type=float, default=0.25)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    report = build_walk_forward_report(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(report), indent=2), encoding="utf-8")
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    print(f"Status: {report['status']}")
    print(f"Splits: {report['passing_split_count']} / {len(report['splits'])} pass")
    best = report.get("all_sample_best") or {}
    best_summary = best.get("summary") or {}
    print(
        "All-sample best: "
        f"{best.get('name', 'n/a')} "
        f"mean_ls={_fmt_pct(best_summary.get('mean_long_short_return'))} "
        f"hit={_fmt_pct(best_summary.get('spread_hit_rate'))} "
        f"max_dd={_fmt_pct(best_summary.get('max_drawdown'))}"
    )
    for item in report["splits"]:
        selected = item["selected_train_config"] or {}
        test = item["selected_test"]
        test_summary = test["summary"]
        baseline = item["baseline_test"]
        print(
            f"Split {item['split_index']}: "
            f"{selected.get('name', 'n/a')} "
            f"test_mean_ls={_fmt_pct(test_summary.get('mean_long_short_return'))} "
            f"test_hit={_fmt_pct(test_summary.get('spread_hit_rate'))} "
            f"test_dd={_fmt_pct(test_summary.get('max_drawdown'))} "
            f"baseline_test_mean_ls={_fmt_pct(baseline.get('mean_long_short_return'))} "
            f"uplift={_fmt_pct(test.get('baseline_mean_delta'))} "
            f"accepted={'yes' if test.get('beats_baseline') else 'no'} "
            f"status={test['gate']['status']}"
        )
    print(f"Saved -> {args.output}")
    print(f"Saved -> {args.markdown_output}")


if __name__ == "__main__":
    main()
