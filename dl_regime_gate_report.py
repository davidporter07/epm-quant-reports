"""Summarize historical regime test outputs and apply stress-aware gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


STRESS_REGIMES = {
    "gfc_2008",
    "q4_2018_drawdown",
    "rate_bear_2022",
    "current_2026",
}


def _load_rows(results_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(results_dir.rglob("*top*_bottom*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(
            {
                "regime": path.parent.name,
                "basket": "_".join(path.stem.split("_")[-2:]),
                "trade_days": int(data.get("trade_days") or 0),
                "asof_start": data.get("asof_start"),
                "asof_end": data.get("asof_end"),
                "mean_long_short_return": float(data.get("mean_long_short_return") or 0.0),
                "spread_hit_rate": float(data.get("spread_hit_rate") or 0.0),
                "max_drawdown": float(data.get("max_drawdown") or 0.0),
                "cumulative_long_short_equity": float(data.get("cumulative_long_short_equity") or 0.0),
                "long_hit_rate": float(data.get("long_hit_rate") or 0.0),
                "short_hit_rate": float(data.get("short_hit_rate") or 0.0),
                "path": str(path),
            }
        )
    return rows


def _evaluate_basket(rows: list[dict], basket: str, min_spread: float, min_hit: float, max_drawdown: float) -> dict:
    basket_rows = [row for row in rows if row["basket"] == basket]
    stress_rows = [row for row in basket_rows if row["regime"] in STRESS_REGIMES]
    failures = []
    for row in stress_rows:
        if row["mean_long_short_return"] < min_spread:
            failures.append(f"{row['regime']} spread {row['mean_long_short_return']:.6f} < {min_spread:.6f}")
        if row["spread_hit_rate"] < min_hit:
            failures.append(f"{row['regime']} hit {row['spread_hit_rate']:.2%} < {min_hit:.2%}")
        if row["max_drawdown"] < max_drawdown:
            failures.append(f"{row['regime']} drawdown {row['max_drawdown']:.2%} < {max_drawdown:.2%}")

    return {
        "basket": basket,
        "status": "pass" if not failures and stress_rows else "fail",
        "stress_regimes_checked": len(stress_rows),
        "failures": failures,
        "mean_spread_all": sum(row["mean_long_short_return"] for row in basket_rows) / max(1, len(basket_rows)),
        "mean_spread_stress": sum(row["mean_long_short_return"] for row in stress_rows) / max(1, len(stress_rows)),
        "min_stress_drawdown": min([row["max_drawdown"] for row in stress_rows], default=0.0),
        "rows": basket_rows,
    }


def _markdown(report: dict) -> str:
    lines = [
        "# DL Regime Gate Report",
        "",
        f"- Results dir: `{report['results_dir']}`",
        f"- Status: `{report['status']}`",
        f"- Stress regimes: {', '.join(sorted(STRESS_REGIMES))}",
        "",
        "## Basket Gates",
        "",
    ]
    for gate in report["gates"]:
        lines.extend(
            [
                f"### {gate['basket']}",
                "",
                f"- Status: `{gate['status']}`",
                f"- Mean spread all regimes: {gate['mean_spread_all']:.6f}",
                f"- Mean spread stress regimes: {gate['mean_spread_stress']:.6f}",
                f"- Worst stress drawdown: {gate['min_stress_drawdown']:.2%}",
                "",
            ]
        )
        if gate["failures"]:
            lines.append("Failures:")
            lines.extend(f"- {failure}" for failure in gate["failures"])
            lines.append("")

    lines.extend(
        [
            "## Results",
            "",
            "| Regime | Basket | Days | Window | Spread | Hit | Max DD | Equity |",
            "|---|---|---:|---|---:|---:|---:|---:|",
        ]
    )
    for row in report["rows"]:
        lines.append(
            f"| {row['regime']} | {row['basket']} | {row['trade_days']} | "
            f"{row['asof_start']} -> {row['asof_end']} | "
            f"{row['mean_long_short_return']:.6f} | {row['spread_hit_rate']:.2%} | "
            f"{row['max_drawdown']:.2%} | {row['cumulative_long_short_equity']:.6f} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply stress-aware gates to DL regime test summaries.")
    ap.add_argument("--results-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown-output", type=Path, default=None)
    ap.add_argument("--min-spread", type=float, default=0.0)
    ap.add_argument("--min-hit", type=float, default=0.50)
    ap.add_argument("--max-drawdown", type=float, default=-0.25)
    args = ap.parse_args()

    rows = _load_rows(args.results_dir)
    gates = [
        _evaluate_basket(rows, basket, args.min_spread, args.min_hit, args.max_drawdown)
        for basket in ("top1_bottom1", "top2_bottom2", "top3_bottom3")
    ]
    report = {
        "status": "pass" if any(gate["status"] == "pass" for gate in gates) else "fail",
        "results_dir": str(args.results_dir),
        "gate_config": {
            "min_spread": args.min_spread,
            "min_hit": args.min_hit,
            "max_drawdown": args.max_drawdown,
            "stress_regimes": sorted(STRESS_REGIMES),
        },
        "gates": gates,
        "rows": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8")
    print(f"Status: {report['status']}")
    for gate in gates:
        print(
            f"{gate['basket']}: {gate['status']} "
            f"stress_spread={gate['mean_spread_stress']:.6f} "
            f"worst_dd={gate['min_stress_drawdown']:.2%}"
        )
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
