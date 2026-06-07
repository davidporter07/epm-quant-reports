"""Audit Growth24 fixed-policy concentration and outlier dependence."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dl_growth24_post_prediction_gate_grid import _fmt_pct, _json_safe, _load_shadow_log
from dl_growth24_shadow_policy_replay import build_replay


def _split_tickers(value: object) -> list[str]:
    if pd.isna(value):
        return []
    return [part.strip().upper() for part in str(value).split(",") if part.strip()]


def _parse_policy(value: str) -> dict[str, Any]:
    parts = [part.strip() for part in str(value).split(":")]
    if len(parts) != 4:
        raise ValueError("Policy must use name:max_universe_score_std:max_forecast_gap:max_consecutive")
    return {
        "name": parts[0],
        "max_universe_score_std": float(parts[1]),
        "max_forecast_gap": float(parts[2]),
        "max_consecutive": int(parts[3]),
    }


def _replay_args(args: argparse.Namespace, policy: dict[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        shadow_log=args.shadow_log,
        long_n=args.long_n,
        short_n=args.short_n,
        expected_universe_count=args.expected_universe_count,
        max_universe_score_std=policy["max_universe_score_std"],
        max_forecast_gap=policy["max_forecast_gap"],
        max_consecutive=policy["max_consecutive"],
        start_date=args.start_date,
        end_date=args.end_date,
        score_start_date=args.score_start_date,
        score_end_date=args.score_end_date,
    )


def _slot_concentration(allowed: pd.DataFrame, long_n: int) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for _, row in allowed.iterrows():
        counts.update(_split_tickers(row["OverlayLongTickers"]))
    denominator = max(1, int(len(allowed)) * int(long_n))
    rows = [
        {"ticker": ticker, "slots": int(count), "slot_share": float(count / denominator)}
        for ticker, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "total_slots": int(denominator if len(allowed) else 0),
        "max_slot_share": float(rows[0]["slot_share"]) if rows else None,
        "max_slot_ticker": rows[0]["ticker"] if rows else None,
        "ticker_rows": rows,
    }


def _contribution_concentration(allowed: pd.DataFrame, shadow_log: Path) -> dict[str, Any]:
    shadow = _load_shadow_log(shadow_log)
    shadow["Ticker"] = shadow["Ticker"].astype(str).str.upper().str.strip()
    shadow["AsOfDate"] = pd.to_datetime(shadow["AsOfDate"])
    lookup = {
        (pd.Timestamp(row.AsOfDate).date().isoformat(), str(row.Ticker).upper().strip()): float(row.RealizedForwardReturn)
        for row in shadow.itertuples(index=False)
    }
    contribution_by_ticker: defaultdict[str, float] = defaultdict(float)
    missing: list[dict[str, str]] = []
    for _, row in allowed.iterrows():
        asof = pd.Timestamp(row["AsOfDate"]).date().isoformat()
        tickers = _split_tickers(row["OverlayLongTickers"])
        if not tickers:
            continue
        short_return = float(row["BaselineShortReturn"])
        for ticker in tickers:
            realized = lookup.get((asof, ticker))
            if realized is None:
                missing.append({"asof": asof, "ticker": ticker})
                continue
            contribution_by_ticker[ticker] += float(realized - short_return) / len(tickers)

    total_signed = float(sum(contribution_by_ticker.values()))
    total_abs = float(sum(abs(value) for value in contribution_by_ticker.values()))
    rows = []
    for ticker, contribution in sorted(contribution_by_ticker.items(), key=lambda item: (-abs(item[1]), item[0])):
        rows.append(
            {
                "ticker": ticker,
                "contribution": float(contribution),
                "signed_share": float(contribution / total_signed) if total_signed else None,
                "absolute_share": float(abs(contribution) / total_abs) if total_abs else None,
            }
        )
    return {
        "total_signed_contribution": total_signed,
        "total_absolute_contribution": total_abs,
        "max_absolute_share": rows[0]["absolute_share"] if rows else None,
        "max_absolute_ticker": rows[0]["ticker"] if rows else None,
        "missing": missing,
        "ticker_rows": rows,
    }


def _leave_one_cycle_out(ledger: pd.DataFrame) -> dict[str, Any]:
    rows = []
    for asof in sorted(ledger["AsOfDate"].astype(str).unique()):
        sub = ledger[ledger["AsOfDate"].astype(str).ne(asof)].copy()
        allowed = sub[sub["OverlayStatus"].eq("paper_overlay_allowed")].copy()
        allowed_returns = pd.to_numeric(allowed["OverlayLongShortReturn"], errors="coerce").dropna()
        baseline_returns = pd.to_numeric(sub["BaselineLongShortReturn"], errors="coerce").dropna()
        uplift = None
        if not allowed_returns.empty and not baseline_returns.empty:
            uplift = float(allowed_returns.mean() - baseline_returns.mean())
        rows.append(
            {
                "excluded_asof": asof,
                "allowed_cycles": int(len(allowed_returns)),
                "baseline_cycles": int(len(baseline_returns)),
                "filter_uplift_vs_baseline_all": uplift,
            }
        )
    scored = [row for row in rows if row["filter_uplift_vs_baseline_all"] is not None]
    min_row = min(scored, key=lambda row: row["filter_uplift_vs_baseline_all"]) if scored else None
    return {
        "rows": rows,
        "min_filter_uplift": min_row["filter_uplift_vs_baseline_all"] if min_row else None,
        "min_filter_uplift_excluded_asof": min_row["excluded_asof"] if min_row else None,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    policy = _parse_policy(args.policy)
    ledger, summary = build_replay(_replay_args(args, policy))
    ledger["AsOfDate"] = ledger["AsOfDate"].astype(str)
    allowed = ledger[ledger["OverlayStatus"].eq("paper_overlay_allowed")].copy()
    slot = _slot_concentration(allowed, args.long_n)
    contribution = _contribution_concentration(allowed, args.shadow_log)
    leave_one_out = _leave_one_cycle_out(ledger)

    failures: list[str] = []
    if slot["max_slot_share"] is None:
        failures.append("no allowed long slots to score")
    elif slot["max_slot_share"] > float(args.max_slot_share):
        failures.append(
            f"max slot share {slot['max_slot_share']:.2%} > {float(args.max_slot_share):.2%} "
            f"for {slot['max_slot_ticker']}"
        )
    if contribution["missing"]:
        failures.append(f"missing contribution rows: {len(contribution['missing'])}")
    if contribution["max_absolute_share"] is None:
        failures.append("no contribution share to score")
    elif contribution["max_absolute_share"] > float(args.max_contribution_share):
        failures.append(
            f"max contribution share {contribution['max_absolute_share']:.2%} > "
            f"{float(args.max_contribution_share):.2%} for {contribution['max_absolute_ticker']}"
        )
    if leave_one_out["min_filter_uplift"] is None:
        failures.append("leave-one-cycle-out uplift is missing")
    elif leave_one_out["min_filter_uplift"] < float(args.min_leave_one_out_uplift):
        failures.append(
            f"leave-one-cycle-out uplift {leave_one_out['min_filter_uplift']:.6f} < "
            f"{float(args.min_leave_one_out_uplift):.6f} when excluding "
            f"{leave_one_out['min_filter_uplift_excluded_asof']}"
        )

    return {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "paper_only": True,
        "live_policy_changed": False,
        "paper_plan_changed": False,
        "shadow_log": str(args.shadow_log),
        "policy": policy,
        "thresholds": {
            "max_slot_share": float(args.max_slot_share),
            "max_contribution_share": float(args.max_contribution_share),
            "min_leave_one_out_uplift": float(args.min_leave_one_out_uplift),
        },
        "summary": summary,
        "slot_concentration": slot,
        "contribution_concentration": contribution,
        "leave_one_cycle_out": leave_one_out,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Growth24 Policy Concentration Audit",
        "",
        f"- Status: `{report['status']}`",
        f"- Paper only: {report['paper_only']}",
        f"- Live policy changed: {report['live_policy_changed']}",
        f"- Paper plan changed: {report['paper_plan_changed']}",
        f"- Shadow log: `{report['shadow_log']}`",
        f"- Policy: `{report['policy']['name']}`",
        f"- Allowed cycles: {report['summary']['overlay_allowed_cycles']} / {report['summary']['cycles']}",
        f"- Overlay allowed mean LS: {_fmt_pct(report['summary']['overlay_allowed_mean_long_short'])}",
        f"- Baseline all-cycle mean LS: {_fmt_pct(report['summary']['baseline_all_mean_long_short'])}",
        f"- Max slot share: {_fmt_pct(report['slot_concentration']['max_slot_share'])} "
        f"({report['slot_concentration']['max_slot_ticker']})",
        f"- Max contribution share: {_fmt_pct(report['contribution_concentration']['max_absolute_share'])} "
        f"({report['contribution_concentration']['max_absolute_ticker']})",
        f"- Minimum leave-one-cycle-out uplift: {_fmt_pct(report['leave_one_cycle_out']['min_filter_uplift'])} "
        f"excluding {report['leave_one_cycle_out']['min_filter_uplift_excluded_asof']}",
        "",
    ]
    if report["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(f"- {failure}" for failure in report["failures"])
        lines.append("")

    lines.extend(
        [
            "## Slot Concentration",
            "",
            "| Ticker | Slots | Slot Share |",
            "|---|---:|---:|",
        ]
    )
    for row in report["slot_concentration"]["ticker_rows"]:
        lines.append(f"| {row['ticker']} | {row['slots']} | {_fmt_pct(row['slot_share'])} |")

    lines.extend(
        [
            "",
            "## Contribution Concentration",
            "",
            "| Ticker | Contribution | Absolute Share | Signed Share |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in report["contribution_concentration"]["ticker_rows"]:
        lines.append(
            f"| {row['ticker']} | {_fmt_pct(row['contribution'])} | "
            f"{_fmt_pct(row['absolute_share'])} | {_fmt_pct(row['signed_share'])} |"
        )

    lines.extend(
        [
            "",
            "## Leave-One-Cycle-Out Uplift",
            "",
            "| Excluded AsOfDate | Allowed Cycles | Filter Uplift vs Baseline All |",
            "|---|---:|---:|",
        ]
    )
    for row in report["leave_one_cycle_out"]["rows"]:
        lines.append(
            f"| {row['excluded_asof']} | {row['allowed_cycles']} | "
            f"{_fmt_pct(row['filter_uplift_vs_baseline_all'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Growth24 policy concentration and outlier dependence.")
    parser.add_argument("--shadow-log", type=Path, required=True)
    parser.add_argument("--long-n", type=int, default=2)
    parser.add_argument("--short-n", type=int, default=2)
    parser.add_argument("--expected-universe-count", type=int, default=24)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--score-start-date", default=None)
    parser.add_argument("--score-end-date", default=None)
    parser.add_argument("--max-slot-share", type=float, default=0.50)
    parser.add_argument("--max-contribution-share", type=float, default=0.50)
    parser.add_argument("--min-leave-one-out-uplift", type=float, default=0.0)
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
    print(f"Max slot share: {_fmt_pct(report['slot_concentration']['max_slot_share'])}")
    print(f"Max contribution share: {_fmt_pct(report['contribution_concentration']['max_absolute_share'])}")
    print(f"Min leave-one-cycle-out uplift: {_fmt_pct(report['leave_one_cycle_out']['min_filter_uplift'])}")
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
