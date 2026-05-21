"""Analyze worst decision cycles for the Growth24 DL research champion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import regime_detector


DEFAULT_SHADOW_LOG = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet"
)
DEFAULT_OUTPUT = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_failure_analysis.json"
)
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_36c_8e_feature_probe_failure_analysis.md")


def _fmt_pct(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not np.isfinite(number):
        return "n/a"
    return f"{number * 100:.{digits}f}%"


def _load_log(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Shadow log not found: {path}")
    rows = pd.read_parquet(path).copy()
    required = {"AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"}
    missing = required.difference(rows.columns)
    if missing:
        raise ValueError(f"{path} missing required columns: {sorted(missing)}")
    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce")
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    rows["Rank"] = pd.to_numeric(rows["Rank"], errors="coerce")
    rows["ShadowRankScore"] = pd.to_numeric(rows.get("ShadowRankScore"), errors="coerce")
    rows["RawForecastPct"] = pd.to_numeric(rows.get("RawForecastPct"), errors="coerce")
    rows["RealizedForwardReturn"] = pd.to_numeric(rows["RealizedForwardReturn"], errors="coerce")
    rows = rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"]).copy()
    return rows.sort_values(["AsOfDate", "Rank", "ShadowRankScore"], ascending=[True, True, False])


def _regime_lookup(start: str, end: str) -> dict[str, str]:
    try:
        series = regime_detector.get_regime_series(start, end)
    except Exception:
        return {}
    return {idx.date().isoformat(): str(label) for idx, label in series.items()}


def _cycle_rows(rows: pd.DataFrame, top_n: int, bottom_n: int) -> pd.DataFrame:
    start = rows["AsOfDate"].min().date().isoformat()
    end = rows["AsOfDate"].max().date().isoformat()
    regimes = _regime_lookup(start, end)

    out: list[dict[str, Any]] = []
    for asof, group in rows.groupby("AsOfDate", sort=True):
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False])
        longs = ordered.head(int(top_n))
        shorts = ordered.tail(int(bottom_n))
        long_return = float(longs["RealizedForwardReturn"].mean())
        short_return = float(shorts["RealizedForwardReturn"].mean())
        spread = long_return - short_return
        asof_key = asof.date().isoformat()
        out.append(
            {
                "AsOfDate": asof_key,
                "Cycle": str(ordered["Cycle"].dropna().iloc[0]) if "Cycle" in ordered.columns and ordered["Cycle"].notna().any() else "",
                "HMM_Regime": regimes.get(asof_key, ""),
                "HMM_Stress": regimes.get(asof_key, "") in regime_detector.STRESS_LABELS,
                "LongTickers": ",".join(longs["Ticker"].tolist()),
                "ShortTickers": ",".join(shorts["Ticker"].tolist()),
                "LongReturn": long_return,
                "ShortReturn": short_return,
                "LongShortReturn": spread,
                "LongAvgRankScore": float(longs["ShadowRankScore"].mean()),
                "ShortAvgRankScore": float(shorts["ShadowRankScore"].mean()),
                "ScoreGap": float(longs["ShadowRankScore"].mean() - shorts["ShadowRankScore"].mean()),
                "LongAvgForecastPct": float(longs["RawForecastPct"].mean()),
                "ShortAvgForecastPct": float(shorts["RawForecastPct"].mean()),
                "ForecastGapPct": float(longs["RawForecastPct"].mean() - shorts["RawForecastPct"].mean()),
                "BestActualTicker": str(ordered.sort_values("RealizedForwardReturn", ascending=False)["Ticker"].iloc[0]),
                "BestActualReturn": float(ordered["RealizedForwardReturn"].max()),
                "WorstActualTicker": str(ordered.sort_values("RealizedForwardReturn", ascending=True)["Ticker"].iloc[0]),
                "WorstActualReturn": float(ordered["RealizedForwardReturn"].min()),
            }
        )
    return pd.DataFrame(out)


def _ticker_loss_contribution(cycles: pd.DataFrame) -> list[dict[str, Any]]:
    loss_cycles = cycles[pd.to_numeric(cycles["LongShortReturn"], errors="coerce") < 0.0].copy()
    rows: list[dict[str, Any]] = []
    tickers = sorted(
        {
            ticker
            for value in loss_cycles.get("LongTickers", pd.Series(dtype=str)).astype(str)
            for ticker in value.split(",")
            if ticker.strip()
        }
    )
    for ticker in tickers:
        mask = loss_cycles["LongTickers"].astype(str).str.split(",").apply(
            lambda vals: ticker in [str(v).strip().upper() for v in vals]
        )
        subset = loss_cycles.loc[mask]
        if subset.empty:
            continue
        returns = pd.to_numeric(subset["LongShortReturn"], errors="coerce")
        rows.append(
            {
                "ticker": ticker,
                "loss_cycle_count": int(len(subset)),
                "mean_spread_when_selected_in_loss": float(returns.mean()),
                "total_spread_when_selected_in_loss": float(returns.sum()),
            }
        )
    return sorted(rows, key=lambda row: row["total_spread_when_selected_in_loss"])


def build_report(shadow_log: Path, top_n: int, bottom_n: int, worst_n: int) -> dict[str, Any]:
    rows = _load_log(shadow_log)
    cycles = _cycle_rows(rows, top_n, bottom_n)
    worst = cycles.sort_values("LongShortReturn", ascending=True).head(int(worst_n)).copy()
    best = cycles.sort_values("LongShortReturn", ascending=False).head(int(worst_n)).copy()
    loss_cycles = cycles[pd.to_numeric(cycles["LongShortReturn"], errors="coerce") < 0.0].copy()

    return {
        "status": "scored",
        "shadow_log": str(shadow_log),
        "top_n": int(top_n),
        "bottom_n": int(bottom_n),
        "cycle_count": int(len(cycles)),
        "loss_cycle_count": int(len(loss_cycles)),
        "loss_cycle_rate": float(len(loss_cycles) / max(1, len(cycles))),
        "mean_loss_spread": float(loss_cycles["LongShortReturn"].mean()) if not loss_cycles.empty else None,
        "worst_cycles": worst.to_dict(orient="records"),
        "best_cycles": best.to_dict(orient="records"),
        "loss_ticker_contribution": _ticker_loss_contribution(cycles),
        "hmm_regime_loss_counts": loss_cycles["HMM_Regime"].fillna("missing").value_counts().to_dict(),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Growth24 Champion Failure Analysis",
        "",
        f"- Shadow log: `{report['shadow_log']}`",
        f"- Cycles: {report['cycle_count']}",
        f"- Loss cycles: {report['loss_cycle_count']} ({_fmt_pct(report['loss_cycle_rate'])})",
        f"- Mean loss spread: {_fmt_pct(report['mean_loss_spread'])}",
        "",
        "## Worst Cycles",
        "",
        "| AsOf | Regime | Longs | Shorts | Spread | Long Ret | Short Ret | Best Actual | Worst Actual |",
        "|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in report["worst_cycles"]:
        lines.append(
            f"| {row['AsOfDate']} | {row.get('HMM_Regime', '')} | {row['LongTickers']} | {row['ShortTickers']} | "
            f"{_fmt_pct(row['LongShortReturn'])} | {_fmt_pct(row['LongReturn'])} | {_fmt_pct(row['ShortReturn'])} | "
            f"{row['BestActualTicker']} ({_fmt_pct(row['BestActualReturn'])}) | "
            f"{row['WorstActualTicker']} ({_fmt_pct(row['WorstActualReturn'])}) |"
        )
    lines.extend(["", "## Loss Ticker Contribution", ""])
    for row in report["loss_ticker_contribution"][:12]:
        lines.append(
            f"- {row['ticker']}: loss_cycles={row['loss_cycle_count']}, "
            f"mean_spread={_fmt_pct(row['mean_spread_when_selected_in_loss'])}, "
            f"total_spread={_fmt_pct(row['total_spread_when_selected_in_loss'])}"
        )
    lines.extend(["", "## HMM Regime Loss Counts", ""])
    for label, count in sorted(report["hmm_regime_loss_counts"].items()):
        lines.append(f"- {label}: {count}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze worst cycles for the Growth24 champion.")
    parser.add_argument("--shadow-log", type=Path, default=DEFAULT_SHADOW_LOG)
    parser.add_argument("--top-n", type=int, default=1)
    parser.add_argument("--bottom-n", type=int, default=1)
    parser.add_argument("--worst-n", type=int, default=8)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    report = build_report(args.shadow_log, int(args.top_n), int(args.bottom_n), int(args.worst_n))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    print("Status: scored")
    print(f"Cycles: {report['cycle_count']}")
    print(f"Loss cycles: {report['loss_cycle_count']} ({_fmt_pct(report['loss_cycle_rate'])})")
    if report["worst_cycles"]:
        worst = report["worst_cycles"][0]
        print(f"Worst cycle: {worst['AsOfDate']} spread={_fmt_pct(worst['LongShortReturn'])}")
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
