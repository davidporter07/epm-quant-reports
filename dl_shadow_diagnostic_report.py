"""Diagnose rank-head shadow logs without retraining.

The report focuses on whether a saved DL rank-head shadow run has a usable
long-only edge, a usable short leg, or mostly ticker/regime concentration.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _safe_float(value: object, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if np.isfinite(out) else default


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return float("nan")
    equity = (1.0 + returns).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def _summarize_returns(returns: pd.Series) -> dict[str, float]:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return {
            "mean": float("nan"),
            "median": float("nan"),
            "hit_rate": float("nan"),
            "max_drawdown": float("nan"),
            "cumulative_equity": float("nan"),
        }
    return {
        "mean": float(values.mean()),
        "median": float(values.median()),
        "hit_rate": float((values > 0.0).mean()),
        "max_drawdown": _max_drawdown(values),
        "cumulative_equity": float((1.0 + values).cumprod().iloc[-1]),
    }


def _ticker_counts(series: pd.Series) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for value in series.dropna().astype(str):
        for ticker in value.split(","):
            ticker = ticker.strip().upper()
            if ticker:
                counts[ticker] += 1
    return dict(counts.most_common())


def _load_shadow_log(path: Path) -> pd.DataFrame:
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
    rows["RealizedForwardReturn"] = pd.to_numeric(rows["RealizedForwardReturn"], errors="coerce")
    rows["ShadowRankScore"] = pd.to_numeric(rows.get("ShadowRankScore"), errors="coerce")
    rows["RawForecastPct"] = pd.to_numeric(rows.get("RawForecastPct"), errors="coerce")
    return rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"]).copy()


def _build_decisions(rows: pd.DataFrame, max_n: int) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    for asof, group in rows.groupby("AsOfDate", sort=True):
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
        universe_return = float(ordered["RealizedForwardReturn"].mean())
        row: dict[str, Any] = {
            "AsOfDate": asof.date().isoformat(),
            "UniverseCount": int(len(ordered)),
            "UniverseReturn": universe_return,
        }
        for n in range(1, max_n + 1):
            longs = ordered.head(n).copy()
            shorts = ordered.tail(n).copy()
            if longs.empty or shorts.empty:
                continue
            overlap = sorted(set(longs["Ticker"]).intersection(set(shorts["Ticker"])))
            long_ret = float(longs["RealizedForwardReturn"].mean())
            short_ret = float(shorts["RealizedForwardReturn"].mean())
            row.update(
                {
                    f"Top{n}Tickers": ",".join(longs["Ticker"].tolist()),
                    f"Bottom{n}Tickers": ",".join(shorts["Ticker"].tolist()),
                    f"Top{n}Return": long_ret,
                    f"Bottom{n}Return": short_ret,
                    f"Top{n}ExcessReturn": long_ret - universe_return,
                    f"Bottom{n}ExcessReturn": short_ret - universe_return,
                    f"LongShort{n}Return": long_ret - short_ret,
                    f"ShortAlpha{n}Return": -short_ret,
                    f"Top{n}ScoreGap": _safe_float(longs["ShadowRankScore"].mean() - shorts["ShadowRankScore"].mean()),
                    f"Top{n}ForecastGapPct": _safe_float(longs["RawForecastPct"].mean() - shorts["RawForecastPct"].mean()),
                    f"Top{n}OverlapCount": len(overlap),
                    f"Top{n}OverlapTickers": ",".join(overlap),
                }
            )
        out.append(row)
    return pd.DataFrame(out)


def _summarize_decisions(decisions: pd.DataFrame, max_n: int) -> dict[str, Any]:
    report: dict[str, Any] = {
        "trade_days": int(len(decisions)),
        "asof_start": str(decisions["AsOfDate"].iloc[0]) if not decisions.empty else None,
        "asof_end": str(decisions["AsOfDate"].iloc[-1]) if not decisions.empty else None,
        "universe_return": _summarize_returns(decisions.get("UniverseReturn", pd.Series(dtype=float))),
        "baskets": {},
    }
    for n in range(1, max_n + 1):
        long_col = f"Top{n}Return"
        short_col = f"ShortAlpha{n}Return"
        spread_col = f"LongShort{n}Return"
        if long_col not in decisions.columns:
            continue
        long_returns = pd.to_numeric(decisions[long_col], errors="coerce")
        short_alpha = pd.to_numeric(decisions[short_col], errors="coerce")
        spreads = pd.to_numeric(decisions[spread_col], errors="coerce")
        overlap = pd.to_numeric(decisions[f"Top{n}OverlapCount"], errors="coerce").fillna(0)
        report["baskets"][f"top{n}_bottom{n}"] = {
            "long": _summarize_returns(long_returns),
            "long_excess": _summarize_returns(decisions[f"Top{n}ExcessReturn"]),
            "short_alpha": _summarize_returns(short_alpha),
            "spread": _summarize_returns(spreads),
            "short_leg_negative_rate": float((pd.to_numeric(decisions[f"Bottom{n}Return"], errors="coerce") < 0.0).mean()),
            "clean_book_days": int((overlap == 0).sum()),
            "overlap_days": int((overlap > 0).sum()),
            "avg_score_gap": float(pd.to_numeric(decisions[f"Top{n}ScoreGap"], errors="coerce").mean()),
            "avg_forecast_gap_pct": float(pd.to_numeric(decisions[f"Top{n}ForecastGapPct"], errors="coerce").mean()),
            "long_ticker_counts": _ticker_counts(decisions[f"Top{n}Tickers"]),
            "short_ticker_counts": _ticker_counts(decisions[f"Bottom{n}Tickers"]),
        }
    return report


def _rank_bucket_summary(rows: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    for rank, group in rows.groupby("Rank", sort=True):
        returns = pd.to_numeric(group["RealizedForwardReturn"], errors="coerce")
        out.append(
            {
                "rank": int(rank),
                "observations": int(len(group)),
                "mean_return": float(returns.mean()),
                "hit_rate": float((returns > 0.0).mean()),
                "ticker_counts": dict(Counter(group["Ticker"].astype(str)).most_common()),
            }
        )
    return out


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DL Shadow Diagnostic Report",
        "",
        f"- Log path: `{report['log_path']}`",
        f"- Trade days: {report['summary']['trade_days']}",
        f"- Window: {report['summary']['asof_start']} -> {report['summary']['asof_end']}",
        "",
        "## Basket Diagnostics",
        "",
        "| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for basket, data in report["summary"]["baskets"].items():
        lines.append(
            f"| {basket} | {data['long']['mean']:.6f} | {data['long_excess']['mean']:.6f} | "
            f"{data['short_alpha']['mean']:.6f} | {data['spread']['mean']:.6f} | "
            f"{data['spread']['hit_rate']:.2%} | {data['spread']['max_drawdown']:.2%} | "
            f"{data['clean_book_days']} | {data['overlap_days']} |"
        )

    lines.extend(["", "## Ticker Concentration", ""])
    for basket, data in report["summary"]["baskets"].items():
        lines.append(f"### {basket}")
        lines.append("")
        lines.append(f"- Long counts: `{data['long_ticker_counts']}`")
        lines.append(f"- Short counts: `{data['short_ticker_counts']}`")
        lines.append("")

    lines.extend(
        [
            "## Rank Buckets",
            "",
            "| Rank | Observations | Mean Return | Hit Rate | Top Tickers |",
            "|---:|---:|---:|---:|---|",
        ]
    )
    for item in report["rank_buckets"]:
        top_tickers = dict(list(item["ticker_counts"].items())[:5])
        lines.append(
            f"| {item['rank']} | {item['observations']} | {item['mean_return']:.6f} | "
            f"{item['hit_rate']:.2%} | `{top_tickers}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnose a saved DL rank-head shadow log.")
    ap.add_argument("--log-path", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown-output", type=Path, default=None)
    ap.add_argument("--max-n", type=int, default=3)
    args = ap.parse_args()

    rows = _load_shadow_log(args.log_path)
    decisions = _build_decisions(rows, args.max_n)
    report = {
        "status": "scored",
        "log_path": str(args.log_path),
        "max_n": int(args.max_n),
        "summary": _summarize_decisions(decisions, args.max_n),
        "rank_buckets": _rank_bucket_summary(rows),
        "decisions": decisions.to_dict(orient="records"),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    print(f"Status: {report['status']}")
    for basket, data in report["summary"]["baskets"].items():
        print(
            f"{basket}: long={data['long']['mean']:.6f} "
            f"long_excess={data['long_excess']['mean']:.6f} "
            f"short_alpha={data['short_alpha']['mean']:.6f} "
            f"spread={data['spread']['mean']:.6f} "
            f"hit={data['spread']['hit_rate']:.2%}"
        )
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
