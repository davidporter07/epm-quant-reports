"""Audit stored Growth24 seed/member diagnostics from historical blind results."""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dl_growth24_post_prediction_gate_grid import _fmt_pct, _json_safe


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _weighted_mean(rows: list[dict[str, Any]], value_key: str, weight_key: str) -> float | None:
    total_weight = 0.0
    total_value = 0.0
    for row in rows:
        value = _safe_float(row.get(value_key))
        weight = _safe_float(row.get(weight_key)) or 1.0
        if value is None:
            continue
        total_value += value * weight
        total_weight += weight
    return float(total_value / total_weight) if total_weight else None


def _load_result_rows(results_glob: str) -> list[dict[str, Any]]:
    paths = [Path(path) for path in glob.glob(results_glob)]
    if not paths:
        raise FileNotFoundError(f"No result JSON files matched {results_glob!r}")
    rows: list[dict[str, Any]] = []
    for path in sorted(paths):
        data = json.loads(path.read_text(encoding="utf-8"))
        cycle_id = f"{path.parent.name}/{data.get('cycle') or path.stem}"
        decision_date = data.get("decision_date")
        for result in data.get("results") or []:
            rank_metrics = result.get("rank_centered_metrics") or result.get("rank_metrics") or {}
            raw_metrics = result.get("raw_metrics") or {}
            rows.append(
                {
                    "path": str(path),
                    "cycle_id": cycle_id,
                    "decision_date": decision_date,
                    "seed": str(result.get("seed")),
                    "variant": result.get("variant"),
                    "hard_gate": bool(result.get("hard_gate")),
                    "selection_score": _safe_float(result.get("selection_score")),
                    "model_path": result.get("model_path"),
                    "scaler_path": result.get("scaler_path"),
                    "selection_spread": _safe_float(rank_metrics.get("Selection_Long_Short_Spread_Mean")),
                    "selection_count": _safe_float(rank_metrics.get("Selection_Count")) or 1.0,
                    "selection_positive_rate": _safe_float(rank_metrics.get("Selection_Spread_Positive_Rate")),
                    "daily_ic_mean": _safe_float(rank_metrics.get("Daily_IC_Mean")),
                    "daily_ic_count": _safe_float(rank_metrics.get("Daily_Count")) or 1.0,
                    "raw_selection_spread": _safe_float(raw_metrics.get("Selection_Long_Short_Spread_Mean")),
                }
            )
    return rows


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    expected_seeds = [part.strip() for part in str(args.expected_seeds).split(",") if part.strip()]
    rows = _load_result_rows(args.results_glob)
    cycle_ids = sorted({row["cycle_id"] for row in rows})
    by_seed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_seed[row["seed"]].append(row)

    seed_reports = []
    failures: list[str] = []
    for seed in expected_seeds:
        seed_rows = by_seed.get(seed, [])
        seen_cycles = {row["cycle_id"] for row in seed_rows}
        missing_cycles = sorted(set(cycle_ids).difference(seen_cycles))
        spread_values = [row["selection_spread"] for row in seed_rows if row["selection_spread"] is not None]
        aggregate_spread = _weighted_mean(seed_rows, "selection_spread", "selection_count")
        aggregate_daily_ic = _weighted_mean(seed_rows, "daily_ic_mean", "daily_ic_count")
        hard_gate_false = [row["cycle_id"] for row in seed_rows if not row["hard_gate"]]
        missing_artifacts = [
            row["cycle_id"]
            for row in seed_rows
            if not row.get("model_path") or not row.get("scaler_path")
        ]
        seed_failures = []
        if missing_cycles:
            seed_failures.append(f"missing {len(missing_cycles)} cycle(s)")
        if aggregate_spread is None:
            seed_failures.append("aggregate selection spread missing")
        elif aggregate_spread <= float(args.min_selection_spread):
            seed_failures.append(
                f"aggregate selection spread {aggregate_spread:.6f} <= {float(args.min_selection_spread):.6f}"
            )
        if hard_gate_false:
            seed_failures.append(f"hard_gate false in {len(hard_gate_false)} cycle(s)")
        if missing_artifacts:
            seed_failures.append(f"missing artifact paths in {len(missing_artifacts)} cycle(s)")
        failures.extend(f"seed {seed}: {failure}" for failure in seed_failures)
        seed_reports.append(
            {
                "seed": seed,
                "status": "pass" if not seed_failures else "fail",
                "failures": seed_failures,
                "cycles_present": int(len(seen_cycles)),
                "expected_cycles": int(len(cycle_ids)),
                "missing_cycles": missing_cycles,
                "aggregate_selection_spread": aggregate_spread,
                "min_cycle_selection_spread": min(spread_values) if spread_values else None,
                "positive_cycle_selection_spread_rate": (
                    float(sum(1 for value in spread_values if value > 0.0) / len(spread_values))
                    if spread_values
                    else None
                ),
                "aggregate_daily_ic_mean": aggregate_daily_ic,
                "hard_gate_false_cycles": hard_gate_false,
                "missing_artifact_cycles": missing_artifacts,
            }
        )

    unexpected_seeds = sorted(seed for seed in by_seed if seed not in expected_seeds)
    return {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "paper_only": True,
        "live_policy_changed": False,
        "paper_plan_changed": False,
        "results_glob": args.results_glob,
        "expected_seeds": expected_seeds,
        "cycle_count": int(len(cycle_ids)),
        "result_row_count": int(len(rows)),
        "unexpected_seeds": unexpected_seeds,
        "thresholds": {
            "min_selection_spread": float(args.min_selection_spread),
        },
        "seeds": seed_reports,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Growth24 Seed Stability Audit",
        "",
        f"- Status: `{report['status']}`",
        f"- Paper only: {report['paper_only']}",
        f"- Live policy changed: {report['live_policy_changed']}",
        f"- Paper plan changed: {report['paper_plan_changed']}",
        f"- Results glob: `{report['results_glob']}`",
        f"- Expected seeds: {', '.join(report['expected_seeds'])}",
        f"- Cycles: {report['cycle_count']}",
        f"- Result rows: {report['result_row_count']}",
        "",
        "## Seed Summary",
        "",
        "| Seed | Status | Cycles | Aggregate Selection Spread | Min Cycle Spread | Positive Spread Rate | Aggregate Daily IC | Failures |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for seed in report["seeds"]:
        lines.append(
            f"| {seed['seed']} | {seed['status']} | {seed['cycles_present']} / {seed['expected_cycles']} | "
            f"{_fmt_pct(seed['aggregate_selection_spread'])} | {_fmt_pct(seed['min_cycle_selection_spread'])} | "
            f"{_fmt_pct(seed['positive_cycle_selection_spread_rate'])} | {_fmt_pct(seed['aggregate_daily_ic_mean'])} | "
            f"{'; '.join(seed['failures'])} |"
        )
    if report["unexpected_seeds"]:
        lines.extend(["", "## Unexpected Seeds", ""])
        lines.append(", ".join(report["unexpected_seeds"]))
    if report["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in report["failures"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit stored Growth24 seed/member diagnostics.")
    parser.add_argument("--results-glob", required=True)
    parser.add_argument("--expected-seeds", required=True)
    parser.add_argument("--min-selection-spread", type=float, default=0.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, default=None)
    args = parser.parse_args()

    report = build_report(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(report), indent=2), encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8")
    print(f"Status: {report['status']}")
    for seed in report["seeds"]:
        print(
            f"seed {seed['seed']}: {seed['status']} cycles={seed['cycles_present']}/{seed['expected_cycles']} "
            f"spread={_fmt_pct(seed['aggregate_selection_spread'])}"
        )
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
