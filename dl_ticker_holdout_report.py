"""Evaluate ticker dependence in rank-head shadow logs.

This report does not retrain. It replays saved per-date rankings after removing
one ticker at a time, then measures whether long-only performance survives.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _parse_int_list(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def _max_drawdown(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return float("nan")
    equity = (1.0 + values).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def _summarize(ledger: pd.DataFrame, available_days: int) -> dict[str, Any]:
    if ledger.empty:
        return {"status": "no_trades", "trade_days": 0, "coverage": 0.0}
    long_returns = pd.to_numeric(ledger["LongReturn"], errors="coerce")
    excess_returns = pd.to_numeric(ledger["LongExcessReturn"], errors="coerce")
    ticker_counts = (
        ledger["LongTickers"]
        .astype(str)
        .str.split(",")
        .explode()
        .str.strip()
        .str.upper()
        .value_counts()
        .to_dict()
    )
    return {
        "status": "scored",
        "trade_days": int(len(ledger)),
        "coverage": float(len(ledger) / max(1, int(available_days))),
        "mean_long_return": float(long_returns.mean()),
        "mean_long_excess_return": float(excess_returns.mean()),
        "long_hit_rate": float((long_returns > 0.0).mean()),
        "excess_hit_rate": float((excess_returns > 0.0).mean()),
        "long_max_drawdown": _max_drawdown(long_returns),
        "excess_max_drawdown": _max_drawdown(excess_returns),
        "cumulative_long_equity": float((1.0 + long_returns).cumprod().iloc[-1]),
        "cumulative_excess_equity": float((1.0 + excess_returns).cumprod().iloc[-1]),
        "long_ticker_counts": ticker_counts,
        "max_ticker_share": float(max(ticker_counts.values(), default=0) / max(1, int(len(ledger)))),
    }


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
    rows["RealizedForwardReturn"] = pd.to_numeric(rows["RealizedForwardReturn"], errors="coerce")
    rows = rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"]).copy()
    return rows.sort_values(["AsOfDate", "Rank", "ShadowRankScore"], ascending=[True, True, False])


def _build_long_ledger(rows: pd.DataFrame, top_n: int, exclude_ticker: str | None = None) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    exclude = str(exclude_ticker).upper().strip() if exclude_ticker else None
    for asof, group in rows.groupby("AsOfDate", sort=True):
        universe = group.copy()
        if exclude:
            universe = universe[universe["Ticker"] != exclude].copy()
        if len(universe) < int(top_n):
            continue
        ordered = universe.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False])
        longs = ordered.head(int(top_n)).copy()
        universe_return = float(ordered["RealizedForwardReturn"].mean())
        long_return = float(longs["RealizedForwardReturn"].mean())
        out.append(
            {
                "AsOfDate": asof.date().isoformat(),
                "LongTickers": ",".join(longs["Ticker"].tolist()),
                "LongReturn": long_return,
                "UniverseReturn": universe_return,
                "LongExcessReturn": long_return - universe_return,
                "UniverseCount": int(len(ordered)),
            }
        )
    return pd.DataFrame(out)


def _selected_ticker_contribution(ledger: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tickers = sorted(
        {
            ticker
            for value in ledger.get("LongTickers", pd.Series(dtype=str)).astype(str)
            for ticker in value.split(",")
            if ticker.strip()
        }
    )
    for ticker in tickers:
        mask = ledger["LongTickers"].astype(str).str.split(",").apply(lambda vals: ticker in [v.strip().upper() for v in vals])
        subset = ledger.loc[mask].copy()
        if subset.empty:
            continue
        excess = pd.to_numeric(subset["LongExcessReturn"], errors="coerce")
        rows.append(
            {
                "ticker": ticker,
                "selected_days": int(len(subset)),
                "selected_day_share": float(len(subset) / max(1, len(ledger))),
                "mean_excess_when_selected": float(excess.mean()),
                "total_excess_contribution": float(excess.sum()),
                "hit_rate_when_selected": float((excess > 0.0).mean()),
            }
        )
    return sorted(rows, key=lambda item: item["total_excess_contribution"], reverse=True)


def _holdout_rows(rows: pd.DataFrame, top_n: int, tickers: list[str]) -> list[dict[str, Any]]:
    out = []
    available_days = rows["AsOfDate"].nunique()
    for ticker in tickers:
        ledger = _build_long_ledger(rows, top_n=top_n, exclude_ticker=ticker)
        summary = _summarize(ledger, available_days)
        out.append({"excluded_ticker": ticker, "summary": summary})
    return sorted(out, key=lambda item: item["summary"].get("mean_long_excess_return", float("-inf")))


def _basket_report(rows: pd.DataFrame, top_n: int) -> dict[str, Any]:
    available_days = rows["AsOfDate"].nunique()
    base_ledger = _build_long_ledger(rows, top_n=top_n)
    selected_counts = Counter(
        ticker
        for value in base_ledger.get("LongTickers", pd.Series(dtype=str)).astype(str)
        for ticker in value.split(",")
        if ticker.strip()
    )
    selected_tickers = sorted(selected_counts)
    holdouts = _holdout_rows(rows, top_n=top_n, tickers=selected_tickers)
    holdout_excess = [
        item["summary"].get("mean_long_excess_return", float("nan"))
        for item in holdouts
        if item["summary"].get("status") == "scored"
    ]
    return {
        "top_n": int(top_n),
        "base": _summarize(base_ledger, available_days),
        "selected_ticker_contribution": _selected_ticker_contribution(base_ledger),
        "rerank_without_selected_ticker": holdouts,
        "worst_holdout_excess": float(np.nanmin(holdout_excess)) if holdout_excess else float("nan"),
        "median_holdout_excess": float(np.nanmedian(holdout_excess)) if holdout_excess else float("nan"),
        "positive_holdout_rate": float(np.mean(np.array(holdout_excess) > 0.0)) if holdout_excess else float("nan"),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DL Ticker Holdout Robustness Report",
        "",
        f"- Log path: `{report['log_path']}`",
        f"- Trade days: {report['trade_days']}",
        "",
        "## Summary",
        "",
        "| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for basket in report["baskets"]:
        base = basket["base"]
        lines.append(
            f"| {basket['top_n']} | {base.get('mean_long_excess_return', float('nan')):.6f} | "
            f"{base.get('excess_hit_rate', float('nan')):.2%} | "
            f"{base.get('max_ticker_share', float('nan')):.2%} | "
            f"{basket['worst_holdout_excess']:.6f} | {basket['median_holdout_excess']:.6f} | "
            f"{basket['positive_holdout_rate']:.2%} |"
        )
    for basket in report["baskets"]:
        lines.extend(["", f"## Top {basket['top_n']} Details", ""])
        lines.append(f"- Base ticker counts: `{basket['base'].get('long_ticker_counts', {})}`")
        lines.append("")
        lines.append("### Selected Ticker Contribution")
        lines.append("")
        lines.append("| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for item in basket["selected_ticker_contribution"]:
            lines.append(
                f"| {item['ticker']} | {item['selected_days']} | {item['selected_day_share']:.2%} | "
                f"{item['mean_excess_when_selected']:.6f} | {item['total_excess_contribution']:.6f} | "
                f"{item['hit_rate_when_selected']:.2%} |"
            )
        lines.append("")
        lines.append("### Rerank Without Ticker")
        lines.append("")
        lines.append("| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |")
        lines.append("|---|---:|---:|---:|---:|")
        for item in basket["rerank_without_selected_ticker"]:
            summary = item["summary"]
            lines.append(
                f"| {item['excluded_ticker']} | {summary.get('mean_long_excess_return', float('nan')):.6f} | "
                f"{summary.get('excess_hit_rate', float('nan')):.2%} | "
                f"{summary.get('max_ticker_share', float('nan')):.2%} | "
                f"{summary.get('coverage', 0.0):.2%} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate ticker-holdout robustness on a saved rank-head shadow log.")
    ap.add_argument("--log-path", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown-output", type=Path, default=None)
    ap.add_argument("--top-n-values", default="1,2,3")
    args = ap.parse_args()

    rows = _load_log(args.log_path)
    report = {
        "status": "scored",
        "log_path": str(args.log_path),
        "trade_days": int(rows["AsOfDate"].nunique()),
        "baskets": [_basket_report(rows, top_n) for top_n in _parse_int_list(args.top_n_values)],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    print(f"Status: {report['status']}")
    for basket in report["baskets"]:
        base = basket["base"]
        print(
            f"top{basket['top_n']}: base_excess={base.get('mean_long_excess_return', float('nan')):.6f} "
            f"worst_holdout={basket['worst_holdout_excess']:.6f} "
            f"positive_holdouts={basket['positive_holdout_rate']:.2%}"
        )
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
