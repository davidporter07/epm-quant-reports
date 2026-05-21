"""Replay rank-head long selections with ticker cooldown constraints.

This tests whether the Growth24 champion can reduce over-persistence in a
single ticker without excluding that ticker entirely. It is offline-only and
reads saved shadow logs.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_SHADOW_LOG = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet"
)
DEFAULT_OUTPUT = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_ticker_cooldown.json"
)
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_36c_8e_feature_probe_ticker_cooldown.md")


def _parse_int_list(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def _parse_float_list(value: str) -> list[float]:
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def _max_drawdown(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return float("nan")
    equity = (1.0 + values).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


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
    rows["RealizedForwardReturn"] = pd.to_numeric(rows["RealizedForwardReturn"], errors="coerce")
    rows = rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"]).copy()
    return rows.sort_values(["AsOfDate", "Rank", "ShadowRankScore"], ascending=[True, True, False])


def _ticker_allowed_by_share(counts: Counter[str], ticker: str, total_after: int, max_ticker_share: float) -> bool:
    if float(max_ticker_share) >= 1.0:
        return True
    allowed = max(1, int(np.floor(float(max_ticker_share) * int(total_after))))
    return counts[str(ticker)] + 1 <= allowed


def _cooldown_blocked(last_selected: dict[str, int], ticker: str, idx: int, cooldown_cycles: int) -> bool:
    if int(cooldown_cycles) <= 0 or ticker not in last_selected:
        return False
    return idx - int(last_selected[ticker]) <= int(cooldown_cycles)


def _consecutive_blocked(consecutive_counts: dict[str, int], ticker: str, max_consecutive: int) -> bool:
    if int(max_consecutive) <= 0:
        return False
    return int(consecutive_counts.get(ticker, 0)) >= int(max_consecutive)


def _build_ledger(
    rows: pd.DataFrame,
    top_n: int,
    max_ticker_share: float,
    cooldown_cycles: int,
    max_consecutive: int,
) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    selected_slots = 0
    last_selected: dict[str, int] = {}
    consecutive_counts: dict[str, int] = defaultdict(int)
    recent_selected = deque(maxlen=1)

    for cycle_idx, (asof, group) in enumerate(rows.groupby("AsOfDate", sort=True)):
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False])
        picked = []
        for row_idx, row in ordered.iterrows():
            ticker = str(row["Ticker"]).upper().strip()
            if not _ticker_allowed_by_share(counts, ticker, selected_slots + 1, max_ticker_share):
                continue
            if _cooldown_blocked(last_selected, ticker, cycle_idx, cooldown_cycles):
                continue
            if _consecutive_blocked(consecutive_counts, ticker, max_consecutive):
                continue
            picked.append(row_idx)
            if len(picked) >= int(top_n):
                break
        if len(picked) < int(top_n):
            continue

        longs = ordered.loc[picked].copy()
        tickers = [str(t).upper().strip() for t in longs["Ticker"].tolist()]
        universe_return = float(ordered["RealizedForwardReturn"].mean())
        long_return = float(longs["RealizedForwardReturn"].mean())
        for ticker in tickers:
            counts[ticker] += 1
            last_selected[ticker] = cycle_idx
        prev = set(recent_selected[-1]) if recent_selected else set()
        selected_now = set(tickers)
        for ticker in list(consecutive_counts):
            if ticker not in selected_now:
                consecutive_counts[ticker] = 0
        for ticker in selected_now:
            consecutive_counts[ticker] = consecutive_counts[ticker] + 1 if ticker in prev else 1
        recent_selected.append(tickers)
        selected_slots += len(tickers)

        out.append(
            {
                "AsOfDate": asof.date().isoformat(),
                "LongTickers": ",".join(tickers),
                "LongReturn": long_return,
                "UniverseReturn": universe_return,
                "LongExcessReturn": long_return - universe_return,
                "SelectedAvgRank": float(pd.to_numeric(longs["Rank"], errors="coerce").mean()),
                "SelectedAvgRankScore": float(pd.to_numeric(longs["ShadowRankScore"], errors="coerce").mean()),
                "UniverseCount": int(len(ordered)),
            }
        )
    return pd.DataFrame(out)


def _summarize(ledger: pd.DataFrame, available_days: int, top_n: int) -> dict[str, Any]:
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
    slots = max(1, int(len(ledger) * int(top_n)))
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
        "avg_selected_rank": float(pd.to_numeric(ledger["SelectedAvgRank"], errors="coerce").mean()),
        "long_ticker_counts": ticker_counts,
        "max_ticker_slot_share": float(max(ticker_counts.values(), default=0) / slots),
    }


def build_report(
    shadow_log: Path,
    top_n_values: list[int],
    max_ticker_shares: list[float],
    cooldown_values: list[int],
    max_consecutive_values: list[int],
) -> dict[str, Any]:
    rows = _load_log(shadow_log)
    available_days = int(rows["AsOfDate"].nunique())
    configs = []
    for top_n in top_n_values:
        for max_ticker_share in max_ticker_shares:
            for cooldown_cycles in cooldown_values:
                for max_consecutive in max_consecutive_values:
                    ledger = _build_ledger(rows, top_n, max_ticker_share, cooldown_cycles, max_consecutive)
                    summary = _summarize(ledger, available_days, top_n)
                    configs.append(
                        {
                            "top_n": int(top_n),
                            "max_ticker_share": float(max_ticker_share),
                            "cooldown_cycles": int(cooldown_cycles),
                            "max_consecutive": int(max_consecutive),
                            "summary": summary,
                        }
                    )
    configs.sort(
        key=lambda item: (
            -float(item["summary"].get("mean_long_excess_return", -1.0e9) or -1.0e9),
            -float(item["summary"].get("excess_hit_rate", 0.0) or 0.0),
            float(item["summary"].get("long_max_drawdown", -1.0) or -1.0),
            -float(item["summary"].get("coverage", 0.0) or 0.0),
        )
    )
    return {
        "status": "scored",
        "shadow_log": str(shadow_log),
        "available_days": available_days,
        "configs": configs,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Growth24 Ticker Cooldown Replay",
        "",
        f"- Shadow log: `{report['shadow_log']}`",
        f"- Available days: {report['available_days']}",
        "",
        "| Top N | Max Share | Cooldown | Max Consecutive | Days | Coverage | Mean Excess | Excess Hit | Long DD | Max Slot Share | Avg Rank | Tickers |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in report["configs"][:30]:
        summary = item["summary"]
        lines.append(
            f"| {item['top_n']} | {item['max_ticker_share']:.2%} | {item['cooldown_cycles']} | "
            f"{item['max_consecutive']} | {summary.get('trade_days', 0)} | "
            f"{_fmt_pct(summary.get('coverage'))} | {_fmt_pct(summary.get('mean_long_excess_return'))} | "
            f"{_fmt_pct(summary.get('excess_hit_rate'))} | {_fmt_pct(summary.get('long_max_drawdown'))} | "
            f"{_fmt_pct(summary.get('max_ticker_slot_share'))} | "
            f"{float(summary.get('avg_selected_rank', float('nan'))):.2f} | "
            f"`{summary.get('long_ticker_counts', {})}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay rank-head selections with ticker cooldown rules.")
    parser.add_argument("--shadow-log", type=Path, default=DEFAULT_SHADOW_LOG)
    parser.add_argument("--top-n-values", default="1,2,3")
    parser.add_argument("--max-ticker-shares", default="0.5,0.67,1.0")
    parser.add_argument("--cooldown-cycles", default="0,1,2,3")
    parser.add_argument("--max-consecutive-values", default="0,2,3,4")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    report = build_report(
        shadow_log=args.shadow_log,
        top_n_values=_parse_int_list(args.top_n_values),
        max_ticker_shares=_parse_float_list(args.max_ticker_shares),
        cooldown_values=_parse_int_list(args.cooldown_cycles),
        max_consecutive_values=_parse_int_list(args.max_consecutive_values),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    print("Status: scored")
    if report["configs"]:
        best = report["configs"][0]
        summary = best["summary"]
        print(
            f"Best: top{best['top_n']} share={best['max_ticker_share']:.2%} "
            f"cooldown={best['cooldown_cycles']} max_consecutive={best['max_consecutive']} "
            f"mean_excess={_fmt_pct(summary.get('mean_long_excess_return'))} "
            f"hit={_fmt_pct(summary.get('excess_hit_rate'))} "
            f"coverage={_fmt_pct(summary.get('coverage'))}"
        )
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
