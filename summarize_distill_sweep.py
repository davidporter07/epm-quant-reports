"""Summarize rank-head distillation sweep artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np


def _safe_float(value: Any) -> float:
    try:
        out = float(value)
    except Exception:
        return float("nan")
    return out if np.isfinite(out) else float("nan")


def _metric_from_results(data: dict[str, Any], key: str) -> float:
    values: list[float] = []
    for row in data.get("results", []):
        metrics = row.get("rank_centered_metrics") or {}
        values.append(_safe_float(metrics.get(key)))
    return float(np.nanmean(values)) if values else float("nan")


def _summarize(root: Path) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for metrics_path in sorted(root.glob("w*/metrics.json")):
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
        weight = _safe_float(data.get("distill_weight"))
        rows.append(
            {
                "weight": weight,
                "mean_selection_score": _safe_float(data.get("mean_selection_score")),
                "mean_ic_spearman": _safe_float(data.get("mean_IC_Spearman")),
                "mean_daily_ic": _metric_from_results(data, "Daily_IC_Mean"),
                "mean_spread": _metric_from_results(data, "Selection_Long_Short_Spread_Mean"),
                "path": str(metrics_path),
            }
        )
    return rows


def _markdown(rows: list[dict[str, float | str]]) -> str:
    lines = [
        "| Distill Weight | Selection Score | IC Spearman | Daily IC | Spread | Artifact |",
        "|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {float(row['weight']):.2f} | {float(row['mean_selection_score']):.4f} | "
            f"{float(row['mean_ic_spearman']):.4f} | {float(row['mean_daily_ic']):.4f} | "
            f"{float(row['mean_spread']):.5f} | `{row['path']}` |"
        )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize distillation weight sweep outputs.")
    ap.add_argument("--root", type=Path, default=Path("artifacts/distill_sweep"))
    ap.add_argument("--journal", type=Path, default=Path("notes/dl_testing_journal.md"))
    args = ap.parse_args()

    rows = _summarize(args.root)
    if not rows:
        raise SystemExit(f"No metrics found under {args.root}")

    table = _markdown(rows)
    print(table)

    args.journal.parent.mkdir(parents=True, exist_ok=True)
    with args.journal.open("a", encoding="utf-8") as f:
        f.write(f"\n## {date.today().isoformat()} - DL Distillation Weight Sweep\n\n")
        f.write(table)
        f.write("\n")


if __name__ == "__main__":
    main()
