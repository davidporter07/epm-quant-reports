"""Replay regime shadow logs with ticker concentration/cooldown rules.

Outputs JSON files shaped like the existing topN/bottomN regime summaries so
``dl_regime_gate_report.py`` can score the challenger with the same gate.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_RESULTS_DIR = Path("data/experiment/final4_growth24_earnings_regime_probe")
DEFAULT_OUTPUT_DIR = Path("data/experiment/final4_growth24_earnings_ticker_cooldown_probe")


def _max_drawdown(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return float("nan")
    equity = (1.0 + values).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def _ticker_allowed(counts: Counter[str], ticker: str, total_after: int, max_ticker_share: float) -> bool:
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


def _load_log(path: Path) -> pd.DataFrame:
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


def _replay(
    rows: pd.DataFrame,
    long_n: int,
    short_n: int,
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
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
        picked = []
        for row_idx, row in ordered.iterrows():
            ticker = str(row["Ticker"]).upper().strip()
            if not _ticker_allowed(counts, ticker, selected_slots + 1, max_ticker_share):
                continue
            if _cooldown_blocked(last_selected, ticker, cycle_idx, cooldown_cycles):
                continue
            if _consecutive_blocked(consecutive_counts, ticker, max_consecutive):
                continue
            picked.append(row_idx)
            if len(picked) >= int(long_n):
                break
        if len(picked) < int(long_n):
            continue
        longs = ordered.loc[picked].copy()
        shorts = ordered.tail(int(short_n)).copy()
        if set(longs["Ticker"]).intersection(set(shorts["Ticker"])):
            continue

        tickers = [str(t).upper().strip() for t in longs["Ticker"].tolist()]
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

        long_ret = float(longs["RealizedForwardReturn"].mean())
        short_ret = float(shorts["RealizedForwardReturn"].mean())
        out.append(
            {
                "AsOfDate": asof.date().isoformat(),
                "LongTickers": ",".join(tickers),
                "ShortTickers": ",".join(shorts["Ticker"].tolist()),
                "LongReturn": long_ret,
                "ShortReturn": short_ret,
                "LongShortReturn": long_ret - short_ret,
                "SelectedAvgRank": float(pd.to_numeric(longs["Rank"], errors="coerce").mean()),
                "SelectedAvgRankScore": float(pd.to_numeric(longs["ShadowRankScore"], errors="coerce").mean()),
                "ShortAvgRankScore": float(pd.to_numeric(shorts["ShadowRankScore"], errors="coerce").mean()),
            }
        )
    return pd.DataFrame(out)


def _summary(
    ledger: pd.DataFrame,
    regime: str,
    long_n: int,
    short_n: int,
    max_ticker_share: float,
    cooldown_cycles: int,
    max_consecutive: int,
    source_log: Path,
) -> dict[str, Any]:
    if ledger.empty:
        return {
            "status": "no_trades",
            "regime": regime,
            "trade_days": 0,
            "long_n": int(long_n),
            "short_n": int(short_n),
            "max_ticker_share": float(max_ticker_share),
            "cooldown_cycles": int(cooldown_cycles),
            "max_consecutive": int(max_consecutive),
            "source_log": str(source_log),
        }
    returns = pd.to_numeric(ledger["LongShortReturn"], errors="coerce")
    long_returns = pd.to_numeric(ledger["LongReturn"], errors="coerce")
    short_returns = pd.to_numeric(ledger["ShortReturn"], errors="coerce")
    equity = (1.0 + returns).cumprod()
    counts = (
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
        "regime": regime,
        "trade_days": int(len(ledger)),
        "asof_start": str(ledger["AsOfDate"].iloc[0]),
        "asof_end": str(ledger["AsOfDate"].iloc[-1]),
        "mean_long_return": float(long_returns.mean()),
        "mean_short_return": float(short_returns.mean()),
        "mean_long_short_return": float(returns.mean()),
        "spread_hit_rate": float((returns > 0.0).mean()),
        "long_hit_rate": float((long_returns > 0.0).mean()),
        "short_hit_rate": float((short_returns > 0.0).mean()),
        "cumulative_long_short_equity": float(equity.iloc[-1]),
        "max_drawdown": _max_drawdown(returns),
        "long_ticker_counts": counts,
        "max_ticker_slot_share": float(max(counts.values(), default=0) / max(1, len(ledger) * int(long_n))),
        "long_n": int(long_n),
        "short_n": int(short_n),
        "max_ticker_share": float(max_ticker_share),
        "cooldown_cycles": int(cooldown_cycles),
        "max_consecutive": int(max_consecutive),
        "source_log": str(source_log),
    }


def replay_regimes(
    results_dir: Path,
    output_dir: Path,
    long_n: int,
    short_n: int,
    max_ticker_share: float,
    cooldown_cycles: int,
    max_consecutive: int,
) -> list[dict[str, Any]]:
    summaries = []
    logs = sorted(results_dir.rglob("*_shadow_log.parquet"))
    if not logs:
        raise FileNotFoundError(f"No shadow logs found under {results_dir}")
    for log in logs:
        regime = log.parent.name
        rows = _load_log(log)
        ledger = _replay(rows, long_n, short_n, max_ticker_share, cooldown_cycles, max_consecutive)
        summary = _summary(
            ledger,
            regime=regime,
            long_n=long_n,
            short_n=short_n,
            max_ticker_share=max_ticker_share,
            cooldown_cycles=cooldown_cycles,
            max_consecutive=max_consecutive,
            source_log=log,
        )
        target_dir = output_dir / regime
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{regime}_ticker_cooldown_top{long_n}_bottom{short_n}"
        ledger.to_csv(target_dir / f"{stem}.csv", index=False)
        (target_dir / f"{stem}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        summaries.append(summary)
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay regime logs with ticker cooldown rules.")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--long-n", type=int, default=1)
    parser.add_argument("--short-n", type=int, default=1)
    parser.add_argument("--max-ticker-share", type=float, default=0.50)
    parser.add_argument("--cooldown-cycles", type=int, default=0)
    parser.add_argument("--max-consecutive", type=int, default=3)
    args = parser.parse_args()

    summaries = replay_regimes(
        results_dir=args.results_dir,
        output_dir=args.output_dir,
        long_n=int(args.long_n),
        short_n=int(args.short_n),
        max_ticker_share=float(args.max_ticker_share),
        cooldown_cycles=int(args.cooldown_cycles),
        max_consecutive=int(args.max_consecutive),
    )
    print("Status: replayed")
    print(f"Regimes: {len(summaries)}")
    for row in summaries:
        print(
            f"{row['regime']}: days={row['trade_days']} "
            f"spread={row.get('mean_long_short_return', float('nan')):.6f} "
            f"hit={row.get('spread_hit_rate', float('nan')):.2%} "
            f"dd={row.get('max_drawdown', float('nan')):.2%}"
        )
    print(f"Saved -> {args.output_dir}")


if __name__ == "__main__":
    main()
