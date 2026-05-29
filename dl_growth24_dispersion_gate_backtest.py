"""Backtest the Growth24 dispersion gate on historical shadow logs.

This is a research-only comparison of the standing Growth24 paper selection
against a post-prediction abstention gate. It does not change live policy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_SHADOW_LOG = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet"
)
DEFAULT_OUTPUT = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_dispersion_gate_backtest.json"
)
DEFAULT_LEDGER_OUTPUT = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_dispersion_gate_backtest.csv"
)
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_36c_8e_stress_dispersion_gate_backtest.md")
DEFAULT_UNIVERSE_SCORE_STD_MAX = 0.085


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _fmt_pct(value: Any, digits: int = 2) -> str:
    number = _finite_float(value)
    if number is None:
        return "n/a"
    return f"{number * 100:.{digits}f}%"


def _fmt_num(value: Any, digits: int = 3) -> str:
    number = _finite_float(value)
    if number is None:
        return "n/a"
    return f"{number:.{digits}f}"


def _max_drawdown(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return float("nan")
    equity = (1.0 + values).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def _load_shadow_log(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Shadow log not found: {path}")
    rows = pd.read_parquet(path).copy()
    required = {"AsOfDate", "Ticker", "Rank", "ShadowRankScore", "RealizedForwardReturn"}
    missing = required.difference(rows.columns)
    if missing:
        raise ValueError(f"{path} missing required columns: {sorted(missing)}")
    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce")
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    rows["Rank"] = pd.to_numeric(rows["Rank"], errors="coerce")
    rows["ShadowRankScore"] = pd.to_numeric(rows["ShadowRankScore"], errors="coerce")
    rows["RawForecastPct"] = pd.to_numeric(rows.get("RawForecastPct"), errors="coerce")
    rows["RealizedForwardReturn"] = pd.to_numeric(rows["RealizedForwardReturn"], errors="coerce")
    rows = rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "ShadowRankScore", "RealizedForwardReturn"]).copy()
    return rows.sort_values(["AsOfDate", "Rank", "ShadowRankScore"], ascending=[True, True, False])


def _cycle_rows(rows: pd.DataFrame, long_n: int, short_n: int, max_universe_score_std: float) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    for asof, group in rows.groupby("AsOfDate", sort=True):
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
        longs = ordered.head(int(long_n))
        shorts = ordered.tail(int(short_n))
        if longs.empty or shorts.empty:
            continue
        long_return = float(longs["RealizedForwardReturn"].mean())
        short_return = float(shorts["RealizedForwardReturn"].mean())
        universe_score_std = float(ordered["ShadowRankScore"].std(ddof=0))
        out.append(
            {
                "AsOfDate": asof.date().isoformat(),
                "Cycle": str(ordered["Cycle"].dropna().iloc[0])
                if "Cycle" in ordered.columns and ordered["Cycle"].notna().any()
                else "",
                "LongTickers": ",".join(longs["Ticker"].tolist()),
                "ShortTickers": ",".join(shorts["Ticker"].tolist()),
                "LongReturn": long_return,
                "ShortReturn": short_return,
                "LongShortReturn": long_return - short_return,
                "SpreadHit": bool(long_return - short_return > 0.0),
                "UniverseScoreStd": universe_score_std,
                "GateAllowed": bool(universe_score_std <= float(max_universe_score_std)),
                "GateReason": ""
                if universe_score_std <= float(max_universe_score_std)
                else f"universe_score_std {universe_score_std:.6f} > {float(max_universe_score_std):.6f}",
                "LongAvgRankScore": float(longs["ShadowRankScore"].mean()),
                "ShortAvgRankScore": float(shorts["ShadowRankScore"].mean()),
                "LongShortScoreGap": float(longs["ShadowRankScore"].mean() - shorts["ShadowRankScore"].mean()),
                "LongAvgForecastPct": _finite_float(longs["RawForecastPct"].mean()),
                "ShortAvgForecastPct": _finite_float(shorts["RawForecastPct"].mean()),
            }
        )
    return pd.DataFrame(out)


def _summarize(ledger: pd.DataFrame, available_days: int) -> dict[str, Any]:
    if ledger.empty:
        return {
            "status": "no_trades",
            "trade_days": 0,
            "coverage": 0.0,
        }
    returns = pd.to_numeric(ledger["LongShortReturn"], errors="coerce")
    long_returns = pd.to_numeric(ledger["LongReturn"], errors="coerce")
    short_returns = pd.to_numeric(ledger["ShortReturn"], errors="coerce")
    std = float(returns.std(ddof=1)) if len(returns) > 1 else float("nan")
    mean = float(returns.mean())
    return {
        "status": "scored",
        "trade_days": int(len(ledger)),
        "coverage": float(len(ledger) / max(1, int(available_days))),
        "asof_start": str(ledger["AsOfDate"].iloc[0]),
        "asof_end": str(ledger["AsOfDate"].iloc[-1]),
        "mean_long_return": float(long_returns.mean()),
        "mean_short_return": float(short_returns.mean()),
        "mean_long_short_return": mean,
        "median_long_short_return": float(returns.median()),
        "std_long_short_return": std,
        "spread_hit_rate": float((returns > 0.0).mean()),
        "long_hit_rate": float((long_returns > 0.0).mean()),
        "short_hit_rate": float((short_returns < 0.0).mean()),
        "max_drawdown": _max_drawdown(returns),
        "naive_sharpe": float(mean / std * np.sqrt(252.0)) if std > 0 else float("nan"),
    }


def build_report(shadow_log: Path, long_n: int, short_n: int, max_universe_score_std: float) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = _load_shadow_log(shadow_log)
    cycles = _cycle_rows(rows, int(long_n), int(short_n), float(max_universe_score_std))
    baseline = cycles.copy()
    gated = cycles[cycles["GateAllowed"].eq(True)].copy()
    abstained = cycles[cycles["GateAllowed"].eq(False)].copy()
    available_days = int(len(cycles))

    baseline_summary = _summarize(baseline, available_days)
    gated_summary = _summarize(gated, available_days)
    abstained_summary = _summarize(abstained, available_days)
    avoided_negative = abstained[pd.to_numeric(abstained["LongShortReturn"], errors="coerce") < 0.0]

    report = {
        "status": "scored",
        "shadow_log": str(shadow_log),
        "long_n": int(long_n),
        "short_n": int(short_n),
        "max_universe_score_std": float(max_universe_score_std),
        "available_days": available_days,
        "baseline": baseline_summary,
        "dispersion_gated": gated_summary,
        "abstained": abstained_summary,
        "abstained_days": int(len(abstained)),
        "abstained_negative_days": int(len(avoided_negative)),
        "abstained_positive_days": int(len(abstained) - len(avoided_negative)),
        "abstained_cycles": abstained[
            ["AsOfDate", "LongTickers", "ShortTickers", "LongShortReturn", "UniverseScoreStd", "GateReason"]
        ].to_dict(orient="records"),
        "worst_baseline_cycles": baseline.sort_values("LongShortReturn", ascending=True)
        .head(10)[["AsOfDate", "LongTickers", "ShortTickers", "LongShortReturn", "UniverseScoreStd", "GateAllowed"]]
        .to_dict(orient="records"),
    }
    return cycles, report


def _markdown(report: dict[str, Any]) -> str:
    baseline = report["baseline"]
    gated = report["dispersion_gated"]
    abstained = report["abstained"]
    lines = [
        "# Growth24 Dispersion Gate Backtest",
        "",
        f"- Shadow log: `{report['shadow_log']}`",
        f"- Long/short book: top {report['long_n']} / bottom {report['short_n']}",
        f"- Gate: `UniverseScoreStd <= {report['max_universe_score_std']:.6f}`",
        f"- Available cycles: {report['available_days']}",
        "",
        "## Summary",
        "",
        "| Book | Days | Coverage | Mean LS | Median LS | Hit | Max DD | Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| Baseline | {baseline.get('trade_days', 0)} | {_fmt_pct(baseline.get('coverage'))} | "
            f"{_fmt_pct(baseline.get('mean_long_short_return'))} | "
            f"{_fmt_pct(baseline.get('median_long_short_return'))} | "
            f"{_fmt_pct(baseline.get('spread_hit_rate'))} | {_fmt_pct(baseline.get('max_drawdown'))} | "
            f"{_fmt_num(baseline.get('naive_sharpe'))} |"
        ),
        (
            f"| Dispersion-gated | {gated.get('trade_days', 0)} | {_fmt_pct(gated.get('coverage'))} | "
            f"{_fmt_pct(gated.get('mean_long_short_return'))} | "
            f"{_fmt_pct(gated.get('median_long_short_return'))} | "
            f"{_fmt_pct(gated.get('spread_hit_rate'))} | {_fmt_pct(gated.get('max_drawdown'))} | "
            f"{_fmt_num(gated.get('naive_sharpe'))} |"
        ),
        (
            f"| Abstained only | {abstained.get('trade_days', 0)} | {_fmt_pct(abstained.get('coverage'))} | "
            f"{_fmt_pct(abstained.get('mean_long_short_return'))} | "
            f"{_fmt_pct(abstained.get('median_long_short_return'))} | "
            f"{_fmt_pct(abstained.get('spread_hit_rate'))} | {_fmt_pct(abstained.get('max_drawdown'))} | "
            f"{_fmt_num(abstained.get('naive_sharpe'))} |"
        ),
        "",
        "## Abstention Quality",
        "",
        f"- Abstained cycles: {report['abstained_days']}",
        f"- Negative cycles avoided: {report['abstained_negative_days']}",
        f"- Positive cycles skipped: {report['abstained_positive_days']}",
        "",
        "## Worst Baseline Cycles",
        "",
        "| AsOf | Longs | Shorts | LS | Score Std | Gate Allowed |",
        "|---|---|---|---:|---:|---:|",
    ]
    for row in report["worst_baseline_cycles"]:
        lines.append(
            f"| {row['AsOfDate']} | {row['LongTickers']} | {row['ShortTickers']} | "
            f"{_fmt_pct(row['LongShortReturn'])} | {_fmt_num(row['UniverseScoreStd'], 6)} | {row['GateAllowed']} |"
        )
    lines.extend(["", "## Abstained Cycles", "", "| AsOf | Longs | Shorts | LS | Score Std | Reason |", "|---|---|---|---:|---:|---|"])
    for row in report["abstained_cycles"]:
        lines.append(
            f"| {row['AsOfDate']} | {row['LongTickers']} | {row['ShortTickers']} | "
            f"{_fmt_pct(row['LongShortReturn'])} | {_fmt_num(row['UniverseScoreStd'], 6)} | {row['GateReason']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the Growth24 dispersion gate on a saved shadow log.")
    parser.add_argument("--shadow-log", type=Path, default=DEFAULT_SHADOW_LOG)
    parser.add_argument("--long-n", type=int, default=2)
    parser.add_argument("--short-n", type=int, default=2)
    parser.add_argument("--max-universe-score-std", type=float, default=DEFAULT_UNIVERSE_SCORE_STD_MAX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ledger-output", type=Path, default=DEFAULT_LEDGER_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    ledger, report = build_report(
        shadow_log=args.shadow_log,
        long_n=int(args.long_n),
        short_n=int(args.short_n),
        max_universe_score_std=float(args.max_universe_score_std),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.ledger_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(report), indent=2), encoding="utf-8")
    ledger.to_csv(args.ledger_output, index=False)
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    baseline = report["baseline"]
    gated = report["dispersion_gated"]
    print("Status: scored")
    print(f"Available cycles: {report['available_days']}")
    print(
        "Baseline: "
        f"days={baseline.get('trade_days')} "
        f"mean_ls={_fmt_pct(baseline.get('mean_long_short_return'))} "
        f"hit={_fmt_pct(baseline.get('spread_hit_rate'))} "
        f"max_dd={_fmt_pct(baseline.get('max_drawdown'))}"
    )
    print(
        "Dispersion-gated: "
        f"days={gated.get('trade_days')} "
        f"mean_ls={_fmt_pct(gated.get('mean_long_short_return'))} "
        f"hit={_fmt_pct(gated.get('spread_hit_rate'))} "
        f"max_dd={_fmt_pct(gated.get('max_drawdown'))}"
    )
    print(f"Abstained cycles: {report['abstained_days']}")
    print(f"Saved -> {args.output}")
    print(f"Saved -> {args.ledger_output}")
    print(f"Saved -> {args.markdown_output}")


if __name__ == "__main__":
    main()
