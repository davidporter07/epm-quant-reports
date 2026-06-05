"""Simulate Growth24 paper-control replacement candidates.

This is research-only. It applies the validated paper-control filters to the
saved Growth24 paper forecasts, then simulates replacement long selection with
a max-consecutive ticker reuse rule. It does not modify the base paper plan,
scheduled task, live policy, or email behavior.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from deep_learning_model import _ensure_panel_schema, read_panel
from dl_growth24_current_control_gate import DEFAULT_FORECAST_GAP_MAX, DEFAULT_UNIVERSE_SCORE_STD_MAX
from dl_growth24_paper_outcome import DEFAULT_FORECAST_LOG, DEFAULT_PANEL, DEFAULT_PLAN_LOG


DEFAULT_OUTPUT = Path("data/experiment/growth24_shadow_paper/growth24_overlay_candidate_sim_ledger.csv")
DEFAULT_SUMMARY_OUTPUT = Path("data/experiment/growth24_shadow_paper/growth24_overlay_candidate_sim_summary.json")
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_overlay_candidate_sim.md")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _fmt_pct(value: Any, digits: int = 2) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return "n/a"
    return f"{float(number) * 100:.{digits}f}%"


def _split_tickers(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [part.strip().upper() for part in str(value).split(",") if part.strip()]


def _numeric(value: object) -> float | None:
    out = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(out) if pd.notna(out) else None


def _load_forecasts(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Forecast log not found: {path}")
    rows = pd.read_parquet(path).copy()
    for column in ["RunDate", "AsOfDate", "Model", "SourceResults", "Ticker", "Rank", "ShadowRankScore", "RawForecastPct"]:
        if column not in rows.columns:
            rows[column] = ""
    rows["RunDate"] = rows["RunDate"].astype(str)
    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce").dt.date.astype(str)
    rows["Model"] = rows["Model"].astype(str)
    rows["SourceResults"] = rows["SourceResults"].astype(str)
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    rows["Rank"] = pd.to_numeric(rows["Rank"], errors="coerce")
    rows["ShadowRankScore"] = pd.to_numeric(rows["ShadowRankScore"], errors="coerce")
    rows["RawForecastPct"] = pd.to_numeric(rows["RawForecastPct"], errors="coerce")
    return rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "ShadowRankScore"]).copy()


def _selected_plans(plan_log: pd.DataFrame) -> pd.DataFrame:
    if plan_log.empty or "Status" not in plan_log.columns:
        return plan_log.iloc[0:0].copy()
    rows = plan_log[plan_log["Status"].astype(str).str.lower().eq("selected")].copy()
    if rows.empty:
        return rows
    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce").dt.date.astype(str)
    rows["RunDate"] = rows["RunDate"].astype(str)
    rows["Model"] = rows["Model"].astype(str)
    rows["SourceResults"] = rows["SourceResults"].astype(str)
    return rows.sort_values(["AsOfDate", "RunDate", "Model"])


def _forecast_rows(forecasts: pd.DataFrame, plan: pd.Series) -> pd.DataFrame:
    asof = str(plan.get("AsOfDate", ""))
    model = str(plan.get("Model", ""))
    source = str(plan.get("SourceResults", ""))
    run_date = str(plan.get("RunDate", ""))
    rows = forecasts[
        forecasts["AsOfDate"].eq(asof)
        & forecasts["Model"].eq(model)
        & forecasts["SourceResults"].eq(source)
    ].copy()
    if rows.empty:
        rows = forecasts[forecasts["AsOfDate"].eq(asof) & forecasts["Model"].eq(model) & forecasts["RunDate"].eq(run_date)].copy()
    if rows.empty:
        rows = forecasts[forecasts["AsOfDate"].eq(asof) & forecasts["Model"].eq(model)].copy()
    return rows.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False])


def _gate_metrics(rows: pd.DataFrame, long_n: int, short_n: int) -> dict[str, Any]:
    if rows.empty:
        return {
            "universe_count": 0,
            "universe_score_std": None,
            "long_short_forecast_gap_pct": None,
            "candidate_longs": [],
        }
    longs = rows.head(int(long_n))
    shorts = rows.tail(int(short_n))
    forecast_gap = None
    if longs["RawForecastPct"].notna().any() and shorts["RawForecastPct"].notna().any():
        forecast_gap = float(longs["RawForecastPct"].mean() - shorts["RawForecastPct"].mean())
    return {
        "universe_count": int(len(rows)),
        "universe_score_std": float(rows["ShadowRankScore"].std(ddof=0)),
        "long_short_forecast_gap_pct": forecast_gap,
        "candidate_longs": [str(ticker).upper().strip() for ticker in longs["Ticker"].tolist()],
    }


def _gate_failures(metrics: dict[str, Any], expected_universe_count: int, max_universe_score_std: float, max_forecast_gap: float) -> list[str]:
    failures: list[str] = []
    if int(metrics["universe_count"]) < int(expected_universe_count):
        failures.append(f"universe count {int(metrics['universe_count'])} < {int(expected_universe_count)}")
    universe_score_std = _numeric(metrics.get("universe_score_std"))
    if universe_score_std is None or universe_score_std > float(max_universe_score_std):
        failures.append(
            f"universe score std {universe_score_std:.6f} > {float(max_universe_score_std):.6f}"
            if universe_score_std is not None
            else "universe score std missing"
        )
    forecast_gap = _numeric(metrics.get("long_short_forecast_gap_pct"))
    if forecast_gap is None or forecast_gap > float(max_forecast_gap):
        failures.append(
            f"long-short forecast gap {forecast_gap:.6f} > {float(max_forecast_gap):.6f}"
            if forecast_gap is not None
            else "long-short forecast gap missing"
        )
    return failures


def _blocked_by_max_consecutive(ticker: str, cycle_index: int, last_cycle: dict[str, int], streaks: dict[str, int], max_consecutive: int) -> bool:
    if int(max_consecutive) <= 0:
        return False
    ticker = str(ticker).upper().strip()
    if last_cycle.get(ticker) != cycle_index - 1:
        return False
    return int(streaks.get(ticker, 0)) >= int(max_consecutive)


def _select_replacements(
    rows: pd.DataFrame,
    long_n: int,
    cycle_index: int,
    last_cycle: dict[str, int],
    streaks: dict[str, int],
    max_consecutive: int,
) -> list[str]:
    selected: list[str] = []
    for _, row in rows.iterrows():
        ticker = str(row["Ticker"]).upper().strip()
        if _blocked_by_max_consecutive(ticker, cycle_index, last_cycle, streaks, int(max_consecutive)):
            continue
        selected.append(ticker)
        if len(selected) >= int(long_n):
            break
    return selected


def _update_streaks(tickers: list[str], cycle_index: int, last_cycle: dict[str, int], streaks: dict[str, int]) -> None:
    selected = {str(ticker).upper().strip() for ticker in tickers}
    for ticker in selected:
        if last_cycle.get(ticker) == cycle_index - 1:
            streaks[ticker] = int(streaks.get(ticker, 0)) + 1
        else:
            streaks[ticker] = 1
        last_cycle[ticker] = cycle_index


def _panel_lookup(panel: pd.DataFrame) -> dict[tuple[str, str], pd.Series]:
    if panel.empty:
        return {}
    rows = panel.copy()
    rows["Date"] = pd.to_datetime(rows["Date"], errors="coerce").dt.date.astype(str)
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    return {(str(row["Ticker"]), str(row["Date"])): row for _, row in rows.iterrows()}


def _score_tickers(panel_rows: dict[tuple[str, str], pd.Series], asof: str, tickers: list[str]) -> dict[str, Any]:
    realized: list[float] = []
    excess: list[float] = []
    pending: list[str] = []
    for ticker in tickers:
        row = panel_rows.get((str(ticker).upper().strip(), str(asof)))
        if row is None:
            pending.append(ticker)
            continue
        forward = _numeric(row.get("Raw_Target_Forward_21D"))
        market = _numeric(row.get("Market_Forward_21D"))
        if forward is None:
            pending.append(ticker)
            continue
        realized.append(float(forward))
        if market is not None:
            excess.append(float(forward) - float(market))
    matured = len(realized) == len(tickers) and bool(tickers)
    return {
        "status": "matured" if matured else "pending",
        "ticker_count": int(len(tickers)),
        "pending_tickers": ",".join(pending),
        "mean_forward_21d": float(np.mean(realized)) if matured else None,
        "mean_excess_21d": float(np.mean(excess)) if matured and excess else None,
        "hit_rate": float(np.mean([value > 0.0 for value in realized])) if matured else None,
        "excess_hit_rate": float(np.mean([value > 0.0 for value in excess])) if matured and excess else None,
    }


def build_simulation(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not args.paper_plan_log.exists():
        raise FileNotFoundError(f"Paper plan log not found: {args.paper_plan_log}")
    plan_log = pd.read_csv(args.paper_plan_log)
    plans = _selected_plans(plan_log)
    forecasts = _load_forecasts(args.forecast_log)
    panel_rows = _panel_lookup(_ensure_panel_schema(read_panel(args.panel))) if args.panel.exists() else {}

    rows: list[dict[str, Any]] = []
    last_cycle: dict[str, int] = {}
    streaks: dict[str, int] = {}
    replacement_counts: Counter[str] = Counter()

    for cycle_index, (_, plan) in enumerate(plans.iterrows()):
        asof = str(plan.get("AsOfDate", ""))
        base_longs = _split_tickers(plan.get("LongTickers"))
        long_n = int(_numeric(plan.get("PaperTopN")) or len(base_longs) or int(args.long_n))
        forecast_rows = _forecast_rows(forecasts, plan)
        metrics = _gate_metrics(forecast_rows, long_n, int(args.short_n))
        failures = _gate_failures(
            metrics,
            int(args.expected_universe_count),
            float(args.max_universe_score_std),
            float(args.max_forecast_gap),
        )
        if failures:
            overlay_status = "paper_overlay_abstain"
            overlay_longs: list[str] = []
        else:
            overlay_longs = _select_replacements(
                forecast_rows,
                long_n,
                cycle_index,
                last_cycle,
                streaks,
                int(args.max_consecutive),
            )
            if len(overlay_longs) < long_n:
                failures = [f"only {len(overlay_longs)} replacement longs available for top {long_n}"]
                overlay_status = "paper_overlay_abstain"
                overlay_longs = []
            else:
                overlay_status = "paper_overlay_allowed"
                _update_streaks(overlay_longs, cycle_index, last_cycle, streaks)
                replacement_counts.update(ticker for ticker in overlay_longs if ticker not in base_longs)

        base_score = _score_tickers(panel_rows, asof, base_longs)
        overlay_score = _score_tickers(panel_rows, asof, overlay_longs)
        rows.append(
            {
                "RunDate": str(plan.get("RunDate", "")),
                "AsOfDate": asof,
                "Model": str(plan.get("Model", "")),
                "BaseLongTickers": ",".join(base_longs),
                "CandidateLongTickers": ",".join(metrics["candidate_longs"]),
                "OverlayStatus": overlay_status,
                "OverlayLongTickers": ",".join(overlay_longs),
                "ReplacementTickers": ",".join(ticker for ticker in overlay_longs if ticker not in base_longs),
                "GateFailures": "; ".join(failures),
                "UniverseCount": metrics["universe_count"],
                "UniverseScoreStd": metrics["universe_score_std"],
                "MaxUniverseScoreStd": float(args.max_universe_score_std),
                "LongShortForecastGapPct": metrics["long_short_forecast_gap_pct"],
                "MaxForecastGapPct": float(args.max_forecast_gap),
                "MaxConsecutive": int(args.max_consecutive),
                "BaseOutcomeStatus": base_score["status"],
                "BaseMeanForward21D": base_score["mean_forward_21d"],
                "BaseMeanExcess21D": base_score["mean_excess_21d"],
                "OverlayOutcomeStatus": overlay_score["status"] if overlay_longs else "abstained",
                "OverlayMeanForward21D": overlay_score["mean_forward_21d"],
                "OverlayMeanExcess21D": overlay_score["mean_excess_21d"],
                "OverlayPendingTickers": overlay_score["pending_tickers"],
                "SourceResults": str(plan.get("SourceResults", "")),
            }
        )

    ledger = pd.DataFrame(rows)
    allowed = ledger[ledger["OverlayStatus"].eq("paper_overlay_allowed")] if not ledger.empty else ledger
    replacements = allowed[allowed["ReplacementTickers"].astype(str).ne("")] if not allowed.empty else allowed
    overlay_matured = allowed[allowed["OverlayOutcomeStatus"].eq("matured")] if not allowed.empty else allowed
    summary = {
        "status": "scored",
        "paper_only": True,
        "live_policy_changed": False,
        "paper_plan_changed": False,
        "plans": int(len(ledger)),
        "overlay_allowed_plans": int(len(allowed)),
        "overlay_abstained_plans": int(ledger["OverlayStatus"].eq("paper_overlay_abstain").sum()) if not ledger.empty else 0,
        "replacement_plan_count": int(len(replacements)),
        "replacement_ticker_counts": dict(replacement_counts),
        "overlay_matured_plans": int(len(overlay_matured)),
        "overlay_matured_mean_forward_21d": float(overlay_matured["OverlayMeanForward21D"].mean()) if not overlay_matured.empty else None,
        "overlay_matured_mean_excess_21d": float(overlay_matured["OverlayMeanExcess21D"].mean()) if not overlay_matured.empty else None,
        "thresholds": {
            "expected_universe_count": int(args.expected_universe_count),
            "max_universe_score_std": float(args.max_universe_score_std),
            "max_forecast_gap": float(args.max_forecast_gap),
            "max_consecutive": int(args.max_consecutive),
        },
    }
    return ledger, summary


def _markdown(ledger: pd.DataFrame, summary: dict[str, Any]) -> str:
    lines = [
        "# Growth24 Overlay Candidate Simulation",
        "",
        f"- Paper only: {summary['paper_only']}",
        f"- Live policy changed: {summary['live_policy_changed']}",
        f"- Paper plan changed: {summary['paper_plan_changed']}",
        f"- Plans: {summary['plans']}",
        f"- Overlay allowed plans: {summary['overlay_allowed_plans']}",
        f"- Overlay abstained plans: {summary['overlay_abstained_plans']}",
        f"- Replacement plans: {summary['replacement_plan_count']}",
        f"- Overlay matured plans: {summary['overlay_matured_plans']}",
        f"- Overlay matured mean forward 21D: {_fmt_pct(summary['overlay_matured_mean_forward_21d'])}",
        "",
        "## Thresholds",
        "",
        f"- Expected universe count: {summary['thresholds']['expected_universe_count']}",
        f"- Max universe score std: {summary['thresholds']['max_universe_score_std']}",
        f"- Max forecast gap: {summary['thresholds']['max_forecast_gap']}",
        f"- Max consecutive selections: {summary['thresholds']['max_consecutive']}",
        "",
        "## Ledger",
        "",
        "| AsOfDate | Base Longs | Candidate Longs | Overlay Status | Overlay Longs | Replacements | Failures | Overlay Outcome |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _, row in ledger.iterrows():
        lines.append(
            f"| {row['AsOfDate']} | {row['BaseLongTickers']} | {row['CandidateLongTickers']} | "
            f"{row['OverlayStatus']} | {row['OverlayLongTickers']} | {row['ReplacementTickers']} | "
            f"{row['GateFailures']} | {row['OverlayOutcomeStatus']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate Growth24 paper-control replacement candidates.")
    parser.add_argument("--paper-plan-log", type=Path, default=DEFAULT_PLAN_LOG)
    parser.add_argument("--forecast-log", type=Path, default=DEFAULT_FORECAST_LOG)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--long-n", type=int, default=2)
    parser.add_argument("--short-n", type=int, default=2)
    parser.add_argument("--expected-universe-count", type=int, default=24)
    parser.add_argument("--max-universe-score-std", type=float, default=DEFAULT_UNIVERSE_SCORE_STD_MAX)
    parser.add_argument("--max-forecast-gap", type=float, default=DEFAULT_FORECAST_GAP_MAX)
    parser.add_argument("--max-consecutive", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    ledger, summary = build_simulation(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(args.output, index=False)
    args.summary_output.write_text(json.dumps(_json_safe(summary), indent=2), encoding="utf-8")
    args.markdown_output.write_text(_markdown(ledger, summary), encoding="utf-8")

    print("Status: scored")
    print(f"Plans: {summary['plans']}")
    print(f"Overlay allowed plans: {summary['overlay_allowed_plans']}")
    print(f"Overlay abstained plans: {summary['overlay_abstained_plans']}")
    print(f"Replacement plans: {summary['replacement_plan_count']}")
    print(f"Overlay matured plans: {summary['overlay_matured_plans']}")
    print(f"Saved ledger -> {args.output}")
    print(f"Saved summary -> {args.summary_output}")
    print(f"Saved report -> {args.markdown_output}")


if __name__ == "__main__":
    main()
