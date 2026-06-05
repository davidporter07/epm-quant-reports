"""Replay the Growth24 paper-control policy on historical shadow logs.

This is research-only. It produces a full cycle ledger from a saved shadow log:
raw top/bottom candidates, gate failures, replacement long candidates, and
realized outcomes. It does not change live policy, paper plans, scheduled
tasks, or email behavior.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from dl_growth24_current_control_gate import DEFAULT_FORECAST_GAP_MAX, DEFAULT_UNIVERSE_SCORE_STD_MAX
from dl_growth24_post_prediction_gate_grid import DEFAULT_SHADOW_LOG, _fmt_pct, _json_safe, _load_shadow_log, _max_drawdown


DEFAULT_OUTPUT = DEFAULT_SHADOW_LOG.with_name(f"{DEFAULT_SHADOW_LOG.stem}_paper_policy_replay.csv")
DEFAULT_SUMMARY_OUTPUT = DEFAULT_SHADOW_LOG.with_name(f"{DEFAULT_SHADOW_LOG.stem}_paper_policy_replay_summary.json")
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_36c_8e_paper_policy_replay.md")


def _safe_float(value: Any) -> float | None:
    out = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(out) if pd.notna(out) and np.isfinite(float(out)) else None


def _gate_failures(metrics: dict[str, Any], expected_universe_count: int, max_universe_score_std: float, max_forecast_gap: float) -> list[str]:
    failures: list[str] = []
    if int(metrics["universe_count"]) < int(expected_universe_count):
        failures.append(f"universe count {int(metrics['universe_count'])} < {int(expected_universe_count)}")
    universe_score_std = _safe_float(metrics.get("universe_score_std"))
    if universe_score_std is None or universe_score_std > float(max_universe_score_std):
        failures.append(
            f"universe score std {universe_score_std:.6f} > {float(max_universe_score_std):.6f}"
            if universe_score_std is not None
            else "universe score std missing"
        )
    forecast_gap = _safe_float(metrics.get("long_short_forecast_gap_pct"))
    if forecast_gap is None or forecast_gap > float(max_forecast_gap):
        failures.append(
            f"long-short forecast gap {forecast_gap:.6f} > {float(max_forecast_gap):.6f}"
            if forecast_gap is not None
            else "long-short forecast gap missing"
        )
    return failures


def _blocked(ticker: str, cycle_index: int, last_cycle: dict[str, int], streaks: dict[str, int], max_consecutive: int) -> bool:
    if int(max_consecutive) <= 0:
        return False
    ticker = str(ticker).upper().strip()
    return last_cycle.get(ticker) == cycle_index - 1 and int(streaks.get(ticker, 0)) >= int(max_consecutive)


def _select_longs(
    ordered: pd.DataFrame,
    long_n: int,
    cycle_index: int,
    last_cycle: dict[str, int],
    streaks: dict[str, int],
    max_consecutive: int,
) -> pd.DataFrame:
    picked: list[int] = []
    for idx, row in ordered.iterrows():
        ticker = str(row["Ticker"]).upper().strip()
        if _blocked(ticker, cycle_index, last_cycle, streaks, int(max_consecutive)):
            continue
        picked.append(idx)
        if len(picked) >= int(long_n):
            break
    if len(picked) < int(long_n):
        return ordered.iloc[0:0].copy()
    return ordered.loc[picked].copy()


def _update_streaks(tickers: list[str], cycle_index: int, last_cycle: dict[str, int], streaks: dict[str, int]) -> None:
    for ticker in {str(ticker).upper().strip() for ticker in tickers}:
        if last_cycle.get(ticker) == cycle_index - 1:
            streaks[ticker] = int(streaks.get(ticker, 0)) + 1
        else:
            streaks[ticker] = 1
        last_cycle[ticker] = cycle_index


def _cycle_metrics(ordered: pd.DataFrame, long_n: int, short_n: int) -> dict[str, Any]:
    longs = ordered.head(int(long_n))
    shorts = ordered.tail(int(short_n))
    long_forecast = _safe_float(longs["RawForecastPct"].mean())
    short_forecast = _safe_float(shorts["RawForecastPct"].mean())
    return {
        "universe_count": int(len(ordered)),
        "universe_score_std": float(ordered["ShadowRankScore"].std(ddof=0)),
        "long_short_score_gap": float(longs["ShadowRankScore"].mean() - shorts["ShadowRankScore"].mean()),
        "long_short_forecast_gap_pct": float(long_forecast - short_forecast)
        if long_forecast is not None and short_forecast is not None
        else None,
        "baseline_long_tickers": [str(ticker).upper().strip() for ticker in longs["Ticker"].tolist()],
        "baseline_short_tickers": [str(ticker).upper().strip() for ticker in shorts["Ticker"].tolist()],
        "baseline_long_return": float(longs["RealizedForwardReturn"].mean()),
        "baseline_short_return": float(shorts["RealizedForwardReturn"].mean()),
    }


def build_replay(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = _load_shadow_log(args.shadow_log)
    start_date = pd.Timestamp(args.start_date) if getattr(args, "start_date", None) else None
    end_date = pd.Timestamp(args.end_date) if getattr(args, "end_date", None) else None
    score_start_date = pd.Timestamp(args.score_start_date) if getattr(args, "score_start_date", None) else start_date
    score_end_date = pd.Timestamp(args.score_end_date) if getattr(args, "score_end_date", None) else end_date
    if start_date is not None:
        rows = rows[rows["AsOfDate"].ge(start_date)].copy()
    if end_date is not None:
        rows = rows[rows["AsOfDate"].le(end_date)].copy()
    out: list[dict[str, Any]] = []
    last_cycle: dict[str, int] = {}
    streaks: dict[str, int] = {}
    replacement_counts: Counter[str] = Counter()

    for cycle_index, (asof, group) in enumerate(rows.groupby("AsOfDate", sort=True)):
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
        if len(ordered) < max(int(args.long_n), int(args.short_n)):
            continue
        metrics = _cycle_metrics(ordered, int(args.long_n), int(args.short_n))
        failures = _gate_failures(
            metrics,
            int(args.expected_universe_count),
            float(args.max_universe_score_std),
            float(args.max_forecast_gap),
        )
        baseline_ls = float(metrics["baseline_long_return"] - metrics["baseline_short_return"])
        overlay_longs = ordered.iloc[0:0].copy()
        overlay_status = "paper_overlay_abstain"
        replacement_tickers: list[str] = []
        overlay_long_return = np.nan
        overlay_ls = np.nan
        if not failures:
            overlay_longs = _select_longs(
                ordered,
                int(args.long_n),
                cycle_index,
                last_cycle,
                streaks,
                int(args.max_consecutive),
            )
            if len(overlay_longs) < int(args.long_n):
                failures = [f"only {len(overlay_longs)} replacement longs available for top {int(args.long_n)}"]
            else:
                overlay_status = "paper_overlay_allowed"
                overlay_tickers = [str(ticker).upper().strip() for ticker in overlay_longs["Ticker"].tolist()]
                replacement_tickers = [ticker for ticker in overlay_tickers if ticker not in metrics["baseline_long_tickers"]]
                _update_streaks(overlay_tickers, cycle_index, last_cycle, streaks)
                overlay_long_return = float(overlay_longs["RealizedForwardReturn"].mean())
                overlay_ls = float(overlay_long_return - metrics["baseline_short_return"])

        score_row = True
        if score_start_date is not None and asof < score_start_date:
            score_row = False
        if score_end_date is not None and asof > score_end_date:
            score_row = False
        if score_row:
            replacement_counts.update(replacement_tickers)
            out.append(
                {
                    "AsOfDate": asof.date().isoformat(),
                    "OverlayStatus": overlay_status,
                    "BaselineLongTickers": ",".join(metrics["baseline_long_tickers"]),
                    "OverlayLongTickers": ",".join([str(t).upper().strip() for t in overlay_longs["Ticker"].tolist()]),
                    "ReplacementTickers": ",".join(replacement_tickers),
                    "BaselineShortTickers": ",".join(metrics["baseline_short_tickers"]),
                    "GateFailures": "; ".join(failures),
                    "UniverseCount": metrics["universe_count"],
                    "UniverseScoreStd": metrics["universe_score_std"],
                    "MaxUniverseScoreStd": float(args.max_universe_score_std),
                    "LongShortScoreGap": metrics["long_short_score_gap"],
                    "LongShortForecastGapPct": metrics["long_short_forecast_gap_pct"],
                    "MaxForecastGapPct": float(args.max_forecast_gap),
                    "MaxConsecutive": int(args.max_consecutive),
                    "BaselineLongReturn": metrics["baseline_long_return"],
                    "BaselineShortReturn": metrics["baseline_short_return"],
                    "BaselineLongShortReturn": baseline_ls,
                    "OverlayLongReturn": overlay_long_return,
                    "OverlayLongShortReturn": overlay_ls,
                    "OverlayVsBaselineLongShortDelta": float(overlay_ls - baseline_ls) if np.isfinite(overlay_ls) else np.nan,
                }
            )

    ledger = pd.DataFrame(out)
    allowed = ledger[ledger["OverlayStatus"].eq("paper_overlay_allowed")].copy() if not ledger.empty else ledger
    abstained = ledger[ledger["OverlayStatus"].eq("paper_overlay_abstain")].copy() if not ledger.empty else ledger
    replacements = allowed[allowed["ReplacementTickers"].astype(str).ne("")].copy() if not allowed.empty else allowed
    overlay_returns = pd.to_numeric(allowed["OverlayLongShortReturn"], errors="coerce") if not allowed.empty else pd.Series(dtype=float)
    baseline_allowed_returns = pd.to_numeric(allowed["BaselineLongShortReturn"], errors="coerce") if not allowed.empty else pd.Series(dtype=float)
    abstained_returns = pd.to_numeric(abstained["BaselineLongShortReturn"], errors="coerce") if not abstained.empty else pd.Series(dtype=float)
    summary = {
        "status": "scored",
        "paper_only": True,
        "live_policy_changed": False,
        "paper_plan_changed": False,
        "cycles": int(len(ledger)),
        "overlay_allowed_cycles": int(len(allowed)),
        "overlay_abstained_cycles": int(len(abstained)),
        "replacement_cycles": int(len(replacements)),
        "replacement_ticker_counts": dict(replacement_counts),
        "baseline_all_mean_long_short": float(pd.to_numeric(ledger["BaselineLongShortReturn"], errors="coerce").mean())
        if not ledger.empty
        else None,
        "overlay_allowed_mean_long_short": float(overlay_returns.mean()) if not overlay_returns.empty else None,
        "overlay_allowed_hit_rate": float((overlay_returns > 0.0).mean()) if not overlay_returns.empty else None,
        "overlay_allowed_max_drawdown": _max_drawdown(overlay_returns) if not overlay_returns.empty else None,
        "baseline_allowed_mean_long_short": float(baseline_allowed_returns.mean()) if not baseline_allowed_returns.empty else None,
        "abstained_baseline_mean_long_short": float(abstained_returns.mean()) if not abstained_returns.empty else None,
        "mean_replacement_delta": float(pd.to_numeric(replacements["OverlayVsBaselineLongShortDelta"], errors="coerce").mean())
        if not replacements.empty
        else None,
        "thresholds": {
            "expected_universe_count": int(args.expected_universe_count),
            "max_universe_score_std": float(args.max_universe_score_std),
            "max_forecast_gap": float(args.max_forecast_gap),
            "max_consecutive": int(args.max_consecutive),
            "long_n": int(args.long_n),
            "short_n": int(args.short_n),
        },
        "window": {
            "start_date": start_date.date().isoformat() if start_date is not None else None,
            "end_date": end_date.date().isoformat() if end_date is not None else None,
            "score_start_date": score_start_date.date().isoformat() if score_start_date is not None else None,
            "score_end_date": score_end_date.date().isoformat() if score_end_date is not None else None,
        },
    }
    return ledger, summary


def _markdown(ledger: pd.DataFrame, summary: dict[str, Any]) -> str:
    lines = [
        "# Growth24 Historical Paper-Policy Replay",
        "",
        f"- Paper only: {summary['paper_only']}",
        f"- Live policy changed: {summary['live_policy_changed']}",
        f"- Paper plan changed: {summary['paper_plan_changed']}",
        f"- Cycles: {summary['cycles']}",
        f"- Window start: {summary['window']['start_date']}",
        f"- Window end: {summary['window']['end_date']}",
        f"- Score window start: {summary['window']['score_start_date']}",
        f"- Score window end: {summary['window']['score_end_date']}",
        f"- Overlay allowed cycles: {summary['overlay_allowed_cycles']}",
        f"- Overlay abstained cycles: {summary['overlay_abstained_cycles']}",
        f"- Replacement cycles: {summary['replacement_cycles']}",
        f"- Baseline all-cycle mean LS: {_fmt_pct(summary['baseline_all_mean_long_short'])}",
        f"- Overlay allowed mean LS: {_fmt_pct(summary['overlay_allowed_mean_long_short'])}",
        f"- Baseline on allowed cycles mean LS: {_fmt_pct(summary['baseline_allowed_mean_long_short'])}",
        f"- Abstained baseline mean LS: {_fmt_pct(summary['abstained_baseline_mean_long_short'])}",
        f"- Mean replacement delta: {_fmt_pct(summary['mean_replacement_delta'])}",
        "",
        "## Thresholds",
        "",
        f"- Expected universe count: {summary['thresholds']['expected_universe_count']}",
        f"- Max universe score std: {summary['thresholds']['max_universe_score_std']}",
        f"- Max forecast gap: {summary['thresholds']['max_forecast_gap']}",
        f"- Max consecutive selections: {summary['thresholds']['max_consecutive']}",
        "",
        "## Replacement Cycles",
        "",
        "| AsOfDate | Baseline Longs | Overlay Longs | Replacements | Baseline LS | Overlay LS | Delta |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    replacements = ledger[ledger["ReplacementTickers"].astype(str).ne("")].copy() if not ledger.empty else ledger
    if replacements.empty:
        lines.append("| n/a |  |  |  |  |  |  |")
    else:
        for _, row in replacements.iterrows():
            lines.append(
                f"| {row['AsOfDate']} | {row['BaselineLongTickers']} | {row['OverlayLongTickers']} | "
                f"{row['ReplacementTickers']} | {_fmt_pct(row['BaselineLongShortReturn'])} | "
                f"{_fmt_pct(row['OverlayLongShortReturn'])} | {_fmt_pct(row['OverlayVsBaselineLongShortDelta'])} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Growth24 paper-control policy on a historical shadow log.")
    parser.add_argument("--shadow-log", type=Path, default=DEFAULT_SHADOW_LOG)
    parser.add_argument("--long-n", type=int, default=2)
    parser.add_argument("--short-n", type=int, default=2)
    parser.add_argument("--expected-universe-count", type=int, default=24)
    parser.add_argument("--max-universe-score-std", type=float, default=DEFAULT_UNIVERSE_SCORE_STD_MAX)
    parser.add_argument("--max-forecast-gap", type=float, default=DEFAULT_FORECAST_GAP_MAX)
    parser.add_argument("--max-consecutive", type=int, default=3)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--score-start-date", default=None)
    parser.add_argument("--score-end-date", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    ledger, summary = build_replay(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(args.output, index=False)
    args.summary_output.write_text(json.dumps(_json_safe(summary), indent=2), encoding="utf-8")
    args.markdown_output.write_text(_markdown(ledger, summary), encoding="utf-8")

    print("Status: scored")
    print(f"Cycles: {summary['cycles']}")
    print(f"Overlay allowed cycles: {summary['overlay_allowed_cycles']}")
    print(f"Overlay abstained cycles: {summary['overlay_abstained_cycles']}")
    print(f"Replacement cycles: {summary['replacement_cycles']}")
    print(f"Overlay allowed mean LS: {_fmt_pct(summary['overlay_allowed_mean_long_short'])}")
    print(f"Mean replacement delta: {_fmt_pct(summary['mean_replacement_delta'])}")
    print(f"Saved ledger -> {args.output}")
    print(f"Saved summary -> {args.summary_output}")
    print(f"Saved report -> {args.markdown_output}")


if __name__ == "__main__":
    main()
