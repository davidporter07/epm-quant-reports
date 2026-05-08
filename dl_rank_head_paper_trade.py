"""Build a paper-trading ledger from rank-head shadow forecasts.

This treats each historical AsOfDate as a paper signal date. The default
strategy is long the top-ranked ticker and short the bottom-ranked ticker,
using the already-realized 21-trading-day forward returns in the shadow
backtest log.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_LOG = Path("data/experiment/rank_head_current_immutable_shadow_backtest_252d.parquet")
DEFAULT_LEDGER = Path("data/experiment/rank_head_current_immutable_paper_trades.csv")
DEFAULT_SUMMARY = Path("data/experiment/rank_head_current_immutable_paper_trades.json")


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return float("nan")
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    return float(drawdown.min())


def _finite_float(value: object) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if np.isfinite(out) else None


def build_paper_ledger(log_path: Path, long_n: int, short_n: int) -> tuple[pd.DataFrame, dict]:
    if not log_path.exists():
        raise FileNotFoundError(f"Shadow backtest log not found: {log_path}")

    rows = pd.read_parquet(log_path).copy()
    required = {"AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"}
    missing = required.difference(rows.columns)
    if missing:
        raise ValueError(f"Shadow backtest log missing required columns: {sorted(missing)}")

    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce")
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    rows["Rank"] = pd.to_numeric(rows["Rank"], errors="coerce")
    rows["RealizedForwardReturn"] = pd.to_numeric(rows["RealizedForwardReturn"], errors="coerce")
    rows["ShadowRankScore"] = pd.to_numeric(rows.get("ShadowRankScore"), errors="coerce")
    rows = rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"]).copy()

    ledger_rows: list[dict] = []
    for asof, group in rows.groupby("AsOfDate", sort=True):
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
        longs = ordered.head(int(long_n)).copy()
        shorts = ordered.tail(int(short_n)).copy()
        if longs.empty or shorts.empty:
            continue

        long_ret = float(longs["RealizedForwardReturn"].mean())
        short_ret = float(shorts["RealizedForwardReturn"].mean())
        spread_ret = long_ret - short_ret
        ledger_rows.append(
            {
                "AsOfDate": asof.date().isoformat(),
                "LongTickers": ",".join(longs["Ticker"].tolist()),
                "ShortTickers": ",".join(shorts["Ticker"].tolist()),
                "LongReturn": long_ret,
                "ShortReturn": short_ret,
                "LongShortReturn": spread_ret,
                "LongHit": bool(long_ret > 0.0),
                "ShortHit": bool(short_ret < 0.0),
                "SpreadHit": bool(spread_ret > 0.0),
                "LongAvgRankScore": _finite_float(longs["ShadowRankScore"].mean()),
                "ShortAvgRankScore": _finite_float(shorts["ShadowRankScore"].mean()),
                "UniverseCount": int(len(ordered)),
            }
        )

    ledger = pd.DataFrame(ledger_rows)
    if ledger.empty:
        summary = {
            "status": "no_trades",
            "log_path": str(log_path),
            "long_n": int(long_n),
            "short_n": int(short_n),
        }
        return ledger, summary

    returns = pd.to_numeric(ledger["LongShortReturn"], errors="coerce")
    long_returns = pd.to_numeric(ledger["LongReturn"], errors="coerce")
    short_returns = pd.to_numeric(ledger["ShortReturn"], errors="coerce")
    ledger["CumulativeLongShortSum"] = returns.cumsum()
    ledger["CumulativeLongShortEquity"] = (1.0 + returns).cumprod()
    ledger["LongShortDrawdown"] = ledger["CumulativeLongShortEquity"] / ledger["CumulativeLongShortEquity"].cummax() - 1.0

    std = float(returns.std(ddof=1)) if len(returns) > 1 else float("nan")
    mean = float(returns.mean())
    summary = {
        "status": "scored",
        "log_path": str(log_path),
        "long_n": int(long_n),
        "short_n": int(short_n),
        "return_horizon_trading_days": 21,
        "overlapping_daily_signals": True,
        "compounded_equity_note": (
            "Rows are daily 21-trading-day forward returns, so adjacent rows overlap. "
            "Use mean spread, hit rates, and drawdown as diagnostics; do not treat "
            "compounded equity as a non-overlapping live portfolio curve."
        ),
        "trade_days": int(len(ledger)),
        "asof_start": str(ledger["AsOfDate"].iloc[0]),
        "asof_end": str(ledger["AsOfDate"].iloc[-1]),
        "mean_long_return": float(long_returns.mean()),
        "mean_short_return": float(short_returns.mean()),
        "mean_long_short_return": mean,
        "median_long_short_return": float(returns.median()),
        "std_long_short_return": std,
        "spread_hit_rate": float(ledger["SpreadHit"].mean()),
        "long_hit_rate": float(ledger["LongHit"].mean()),
        "short_hit_rate": float(ledger["ShortHit"].mean()),
        "cumulative_long_short_sum": float(ledger["CumulativeLongShortSum"].iloc[-1]),
        "cumulative_long_short_equity": float(ledger["CumulativeLongShortEquity"].iloc[-1]),
        "max_drawdown": _max_drawdown(ledger["CumulativeLongShortEquity"]),
        "naive_sharpe": float(mean / std * np.sqrt(252.0)) if std > 0 else float("nan"),
    }
    return ledger, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Build rank-head DL paper-trading ledger.")
    ap.add_argument("--log-path", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--long-n", type=int, default=1)
    ap.add_argument("--short-n", type=int, default=1)
    ap.add_argument("--ledger-output", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    args = ap.parse_args()

    ledger, summary = build_paper_ledger(args.log_path, args.long_n, args.short_n)
    args.ledger_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(args.ledger_output, index=False)
    with args.summary_output.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Status: {summary['status']}")
    if summary["status"] == "scored":
        print(f"Trade days: {summary['trade_days']}")
        print(f"AsOfDate range: {summary['asof_start']} -> {summary['asof_end']}")
        print(f"Mean long return: {summary['mean_long_return']:.6f}")
        print(f"Mean short return: {summary['mean_short_return']:.6f}")
        print(f"Mean long-short return: {summary['mean_long_short_return']:.6f}")
        print(f"Spread hit rate: {summary['spread_hit_rate']:.6f}")
        print(f"Long hit rate: {summary['long_hit_rate']:.6f}")
        print(f"Short hit rate: {summary['short_hit_rate']:.6f}")
        print(f"Cumulative long-short equity: {summary['cumulative_long_short_equity']:.6f}")
        print(f"Max drawdown: {summary['max_drawdown']:.6f}")
    print(f"Saved ledger -> {args.ledger_output}")
    print(f"Saved summary -> {args.summary_output}")


if __name__ == "__main__":
    main()
