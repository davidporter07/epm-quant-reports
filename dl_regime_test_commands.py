"""Generate local commands for historical rank-head regime tests.

The generated commands use the existing historical blind loop. They do not
rebuild features; they only inspect a DL-ready panel and create PowerShell
commands for the historical windows that overlap that panel.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from deep_learning_model import TARGET_COL
from dl_expanded_feature_seed_grid import DEFAULT_PANEL


DEFAULT_OUT_DIR = Path("data/experiment/historical_regime_tests")
DEFAULT_NOTES = Path("notes/dl_historical_regime_testing.md")

REGIMES = [
    ("gfc_2008", "2008-01-02", "2009-06-30", "Global financial crisis"),
    ("post_gfc_recovery", "2009-07-01", "2011-04-29", "Post-GFC recovery"),
    ("euro_debt_2011", "2011-05-02", "2012-06-29", "Eurozone/debt-ceiling stress"),
    ("china_oil_2015", "2015-06-01", "2016-03-31", "China/oil/rate cycle"),
    ("q4_2018_drawdown", "2018-09-04", "2018-12-31", "Q4 2018 drawdown"),
    ("covid_2020", "2020-02-21", "2020-12-31", "COVID shock/recovery"),
    ("rate_bear_2022", "2022-01-03", "2022-12-30", "Inflation/rate bear market"),
    ("ai_mega_cap_2023_2025", "2023-01-03", "2025-12-31", "AI/mega-cap regime"),
    ("current_2026", "2026-01-02", "2026-04-07", "Current matured-label window"),
]


def _load_panel(path: Path) -> pd.DataFrame:
    panel = pd.read_parquet(path)
    panel["Date"] = pd.to_datetime(panel["Date"], errors="coerce")
    panel["Ticker"] = panel["Ticker"].astype(str).str.upper().str.strip()
    panel[TARGET_COL] = pd.to_numeric(panel[TARGET_COL], errors="coerce")
    return panel


def _available_dates(panel: pd.DataFrame) -> pd.Series:
    labeled = panel[panel[TARGET_COL].notna()].copy()
    return pd.Series(sorted(labeled["Date"].dropna().drop_duplicates()))


def _select_dates(
    dates: pd.Series,
    start: str,
    end: str,
    step_days: int,
    max_cycles: int,
    horizon: int,
    min_train_dates: int,
) -> list[pd.Timestamp]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    feasible = []
    min_pos = int(horizon) + int(min_train_dates)
    for pos, date in enumerate(dates.tolist()):
        if pos >= min_pos:
            feasible.append(date)
    selected = [d for d in feasible if start_ts <= d <= end_ts]
    selected = selected[:: max(1, int(step_days))]
    if max_cycles > 0:
        selected = selected[-int(max_cycles) :]
    return [pd.Timestamp(d) for d in selected]


def _command(
    regime: str,
    start: str,
    end: str,
    panel: Path,
    out_dir: Path,
    epochs: int,
    seeds: str,
    extra_features: str,
    step_days: int,
    cycles: int,
    device: str,
) -> str:
    stem = f"{regime}_{cycles}c_{epochs}e"
    base = out_dir / regime / stem
    return (
        "python .\\dl_rank_head_historical_blind_loop.py "
        f"--panel {panel} "
        f"--extra-features {extra_features} "
        f"--start-date {start} --end-date {end} --cycles {cycles} --step-days {step_days} "
        f"--epochs {epochs} --seeds {seeds} --val-days 126 --top-n 1 "
        "--paper-long-n 2 --paper-short-n 2 "
        f"--device {device} --date-grouped-batches --dates-per-batch 64 "
        f"--output {base}_shadow_log.parquet "
        f"--csv-output {base}_shadow_log.csv "
        f"--summary-output {base}_summary.json "
        f"--output-stem {stem}"
    )


def _score_commands(regime: str, out_dir: Path, epochs: int, cycles: int) -> list[str]:
    stem = f"{regime}_{cycles}c_{epochs}e"
    base = out_dir / regime / stem
    log_path = f"{base}_shadow_log.parquet"
    commands = []
    for n in (1, 2, 3):
        commands.append(
            "python .\\dl_rank_head_paper_trade.py "
            f"--log-path {log_path} --long-n {n} --short-n {n} "
            f"--ledger-output {base}_top{n}_bottom{n}.csv "
            f"--summary-output {base}_top{n}_bottom{n}.json"
        )
    return commands


def _existing_results(out_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(out_dir.rglob("*top*_bottom*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(
            {
                "path": str(path),
                "trade_days": data.get("trade_days"),
                "asof_start": data.get("asof_start"),
                "asof_end": data.get("asof_end"),
                "mean_long_short_return": data.get("mean_long_short_return"),
                "spread_hit_rate": data.get("spread_hit_rate"),
                "max_drawdown": data.get("max_drawdown"),
                "cumulative_long_short_equity": data.get("cumulative_long_short_equity"),
            }
        )
    return rows


def _coverage_summary(panel: pd.DataFrame) -> dict:
    labeled = panel[panel[TARGET_COL].notna()].copy()
    by_ticker = {}
    for ticker, group in labeled.groupby("Ticker"):
        by_ticker[ticker] = {
            "start": group["Date"].min().date().isoformat(),
            "end": group["Date"].max().date().isoformat(),
            "rows": int(len(group)),
        }
    return {
        "panel_start": panel["Date"].min().date().isoformat(),
        "panel_end": panel["Date"].max().date().isoformat(),
        "labeled_start": labeled["Date"].min().date().isoformat(),
        "labeled_end": labeled["Date"].max().date().isoformat(),
        "tickers": by_ticker,
    }


def _notes_markdown(note: dict) -> str:
    lines = [
        "# DL Historical Regime Testing",
        "",
        "Generated by `dl_regime_test_commands.py`.",
        "",
        "## Priority Target",
        "",
        f"- Primary: {note['priority_target']['primary']}",
        "- Secondary:",
    ]
    lines.extend(f"  - {item}" for item in note["priority_target"]["secondary"])
    lines.append(f"- Avoid: {note['priority_target']['avoid']}")
    lines.extend(
        [
            "",
            "## Panel Coverage",
            "",
            f"- Panel: `{note['panel']}`",
            f"- Panel range: {note['coverage']['panel_start']} -> {note['coverage']['panel_end']}",
            f"- Mature labeled range: {note['coverage']['labeled_start']} -> {note['coverage']['labeled_end']}",
            "",
            "## Generated Regime Commands",
            "",
            f"PowerShell command file: `{note['commands_output']}`",
            "",
        ]
    )
    if note["generated"]:
        for item in note["generated"]:
            lines.extend(
                [
                    f"### {item['description']}",
                    "",
                    f"- Regime: `{item['regime']}`",
                    f"- Window: {item['start']} -> {item['end']}",
                    f"- Blind cycles: {item['cycles']}",
                    "",
                    "```powershell",
                    item["command"],
                    *item["score_commands"],
                    "```",
                    "",
                ]
            )
    if note["skipped"]:
        lines.extend(["## Skipped Regimes", ""])
        for item in note["skipped"]:
            lines.append(f"- `{item['regime']}`: {item['reason']}")
        lines.append("")
    if note["existing_results"]:
        lines.extend(["## Existing Result Summaries", ""])
        lines.append("| Result | Days | Window | Mean Spread | Hit Rate | Max Drawdown | Equity |")
        lines.append("|---|---:|---|---:|---:|---:|---:|")
        for item in note["existing_results"]:
            lines.append(
                "| "
                f"`{item['path']}` | "
                f"{item['trade_days']} | "
                f"{item['asof_start']} -> {item['asof_end']} | "
                f"{float(item['mean_long_short_return'] or 0.0):.6f} | "
                f"{float(item['spread_hit_rate'] or 0.0):.2%} | "
                f"{float(item['max_drawdown'] or 0.0):.2%} | "
                f"{float(item['cumulative_long_short_equity'] or 0.0):.6f} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Review Gate",
            "",
            "Treat a run as research-only unless it shows positive long-short spread, acceptable drawdown, and consistent top-1/top-2 behavior across more than one regime.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate historical regime blind-loop commands.")
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--notes-output", type=Path, default=DEFAULT_NOTES)
    ap.add_argument("--commands-output", type=Path, default=DEFAULT_OUT_DIR / "run_regime_tests.ps1")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--cycles", type=int, default=24)
    ap.add_argument("--step-days", type=int, default=21)
    ap.add_argument("--val-days", type=int, default=126)
    ap.add_argument("--horizon", type=int, default=21)
    ap.add_argument("--seq-len", type=int, default=60)
    ap.add_argument("--min-train-buffer-days", type=int, default=5)
    ap.add_argument("--seeds", default="20260505")
    ap.add_argument(
        "--extra-features",
        default="atr_percentile,gap_5d_count,earnings_surprise_last,days_since_earnings,earnings_surprise_x_gap_count,post_earnings_negative_drift_window",
    )
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="cpu")
    args = ap.parse_args()

    panel = _load_panel(args.panel)
    dates = _available_dates(panel)
    coverage = _coverage_summary(panel)
    generated = []
    skipped = []

    for regime, start, end, description in REGIMES:
        min_train_dates = int(args.val_days) + int(args.seq_len) + int(args.min_train_buffer_days)
        selected = _select_dates(
            dates,
            start,
            end,
            int(args.step_days),
            int(args.cycles),
            int(args.horizon),
            min_train_dates,
        )
        if len(selected) < 3:
            skipped.append(
                {
                    "regime": regime,
                    "description": description,
                    "reason": "fewer than 3 labeled decision dates overlap the current panel",
                }
            )
            continue
        cycles = len(selected)
        generated.append(
            {
                "regime": regime,
                "description": description,
                "start": selected[0].date().isoformat(),
                "end": selected[-1].date().isoformat(),
                "cycles": cycles,
                "command": _command(
                    regime,
                    selected[0].date().isoformat(),
                    selected[-1].date().isoformat(),
                    args.panel,
                    args.out_dir,
                    int(args.epochs),
                    args.seeds,
                    args.extra_features,
                    int(args.step_days),
                    cycles,
                    args.device,
                ),
                "score_commands": _score_commands(regime, args.out_dir, int(args.epochs), cycles),
            }
        )

    args.commands_output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Generated by dl_regime_test_commands.py",
        "$ErrorActionPreference = 'Stop'",
        "",
    ]
    for item in generated:
        lines.append(f"# {item['description']}: {item['start']} -> {item['end']}")
        for command in [item["command"], *item["score_commands"]]:
            lines.append(command)
            lines.append('if ($LASTEXITCODE -ne 0) { throw "Previous command failed." }')
        lines.append("")
    args.commands_output.write_text("\n".join(lines), encoding="utf-8")

    args.notes_output.parent.mkdir(parents=True, exist_ok=True)
    note = {
        "panel": str(args.panel),
        "coverage": coverage,
        "priority_target": {
            "primary": "walk-forward long-short spread with drawdown and regime consistency gates",
            "secondary": [
                "spread hit rate",
                "top-1 and top-2 basket agreement",
                "maximum drawdown",
                "single-ticker concentration",
            ],
            "avoid": "promoting on raw directional accuracy alone",
        },
        "generated": generated,
        "skipped": skipped,
        "existing_results": _existing_results(args.out_dir),
        "commands_output": str(args.commands_output),
    }
    args.notes_output.write_text(_notes_markdown(note), encoding="utf-8")

    print(f"Panel labeled range: {coverage['labeled_start']} -> {coverage['labeled_end']}")
    print(f"Generated regimes: {len(generated)}")
    for item in generated:
        print(f"- {item['regime']}: {item['start']} -> {item['end']} ({item['cycles']} cycles)")
    if skipped:
        print(f"Skipped regimes: {len(skipped)}")
        for item in skipped:
            print(f"- {item['regime']}: {item['reason']}")
    print(f"Saved commands -> {args.commands_output}")
    print(f"Saved notes -> {args.notes_output}")


if __name__ == "__main__":
    main()
