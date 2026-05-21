"""Replay regime logs with score-gap-limited ticker cooldown rules."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_RESULTS_DIR = Path("data/experiment/final4_growth24_earnings_regime_probe")
DEFAULT_OUTPUT_DIR = Path("data/experiment/final4_growth24_earnings_ticker_cooldown_tolerance_probe")


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
    rows["RealizedForwardReturn"] = pd.to_numeric(rows["RealizedForwardReturn"], errors="coerce")
    rows = rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"]).copy()
    return rows.sort_values(["AsOfDate", "Rank", "ShadowRankScore"], ascending=[True, True, False])


def _candidate_blocked(
    row: pd.Series,
    counts: Counter[str],
    selected_slots: int,
    last_selected: dict[str, int],
    consecutive_counts: dict[str, int],
    cycle_idx: int,
    max_ticker_share: float,
    cooldown_cycles: int,
    max_consecutive: int,
) -> bool:
    ticker = str(row["Ticker"]).upper().strip()
    return (
        not _ticker_allowed(counts, ticker, selected_slots + 1, max_ticker_share)
        or _cooldown_blocked(last_selected, ticker, cycle_idx, cooldown_cycles)
        or _consecutive_blocked(consecutive_counts, ticker, max_consecutive)
    )


def _pick_longs(
    ordered: pd.DataFrame,
    counts: Counter[str],
    selected_slots: int,
    last_selected: dict[str, int],
    consecutive_counts: dict[str, int],
    cycle_idx: int,
    long_n: int,
    max_ticker_share: float,
    cooldown_cycles: int,
    max_consecutive: int,
    max_rank_score_gap: float,
) -> pd.DataFrame:
    original = ordered.head(int(long_n)).copy()
    if int(long_n) != 1:
        return original
    original_row = original.iloc[0]
    if not _candidate_blocked(
        original_row,
        counts,
        selected_slots,
        last_selected,
        consecutive_counts,
        cycle_idx,
        max_ticker_share,
        cooldown_cycles,
        max_consecutive,
    ):
        return original

    original_score = float(original_row["ShadowRankScore"])
    for _, row in ordered.iloc[1:].iterrows():
        if _candidate_blocked(
            row,
            counts,
            selected_slots,
            last_selected,
            consecutive_counts,
            cycle_idx,
            max_ticker_share,
            cooldown_cycles,
            max_consecutive,
        ):
            continue
        candidate_score = float(row["ShadowRankScore"])
        if original_score - candidate_score <= float(max_rank_score_gap):
            return pd.DataFrame([row])
        return original
    return original


def _replay(
    rows: pd.DataFrame,
    long_n: int,
    short_n: int,
    max_ticker_share: float,
    cooldown_cycles: int,
    max_consecutive: int,
    max_rank_score_gap: float,
) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    selected_slots = 0
    last_selected: dict[str, int] = {}
    consecutive_counts: dict[str, int] = defaultdict(int)
    recent_selected = deque(maxlen=1)

    for cycle_idx, (asof, group) in enumerate(rows.groupby("AsOfDate", sort=True)):
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
        longs = _pick_longs(
            ordered,
            counts,
            selected_slots,
            last_selected,
            consecutive_counts,
            cycle_idx,
            long_n,
            max_ticker_share,
            cooldown_cycles,
            max_consecutive,
            max_rank_score_gap,
        )
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
        original = ordered.head(int(long_n))
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
                "OriginalTopTicker": ",".join(original["Ticker"].astype(str).tolist()),
                "OriginalTopRankScore": float(pd.to_numeric(original["ShadowRankScore"], errors="coerce").mean()),
                "ReplacedOriginalTop": ",".join(tickers) != ",".join(original["Ticker"].astype(str).tolist()),
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
    max_rank_score_gap: float,
    source_log: Path,
) -> dict[str, Any]:
    if ledger.empty:
        return {"status": "no_trades", "regime": regime, "trade_days": 0, "source_log": str(source_log)}
    returns = pd.to_numeric(ledger["LongShortReturn"], errors="coerce")
    long_returns = pd.to_numeric(ledger["LongReturn"], errors="coerce")
    short_returns = pd.to_numeric(ledger["ShortReturn"], errors="coerce")
    equity = (1.0 + returns).cumprod()
    counts = (
        ledger["LongTickers"].astype(str).str.split(",").explode().str.strip().str.upper().value_counts().to_dict()
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
        "replaced_original_top_days": int(pd.Series(ledger["ReplacedOriginalTop"]).fillna(False).sum()),
        "long_n": int(long_n),
        "short_n": int(short_n),
        "max_ticker_share": float(max_ticker_share),
        "cooldown_cycles": int(cooldown_cycles),
        "max_consecutive": int(max_consecutive),
        "max_rank_score_gap": float(max_rank_score_gap),
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
    max_rank_score_gap: float,
) -> list[dict[str, Any]]:
    summaries = []
    logs = sorted(results_dir.rglob("*_shadow_log.parquet"))
    if not logs:
        raise FileNotFoundError(f"No shadow logs found under {results_dir}")
    for log in logs:
        regime = log.parent.name
        rows = _load_log(log)
        ledger = _replay(
            rows,
            long_n,
            short_n,
            max_ticker_share,
            cooldown_cycles,
            max_consecutive,
            max_rank_score_gap,
        )
        summary = _summary(
            ledger,
            regime,
            long_n,
            short_n,
            max_ticker_share,
            cooldown_cycles,
            max_consecutive,
            max_rank_score_gap,
            log,
        )
        target_dir = output_dir / regime
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{regime}_ticker_cooldown_gap{max_rank_score_gap:g}_top{long_n}_bottom{short_n}"
        ledger.to_csv(target_dir / f"{stem}.csv", index=False)
        (target_dir / f"{stem}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        summaries.append(summary)
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay regime logs with score-gap-limited ticker cooldown.")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--long-n", type=int, default=1)
    parser.add_argument("--short-n", type=int, default=1)
    parser.add_argument("--max-ticker-share", type=float, default=0.50)
    parser.add_argument("--cooldown-cycles", type=int, default=0)
    parser.add_argument("--max-consecutive", type=int, default=3)
    parser.add_argument("--max-rank-score-gap", type=float, default=0.02)
    args = parser.parse_args()

    summaries = replay_regimes(
        args.results_dir,
        args.output_dir,
        int(args.long_n),
        int(args.short_n),
        float(args.max_ticker_share),
        int(args.cooldown_cycles),
        int(args.max_consecutive),
        float(args.max_rank_score_gap),
    )
    print("Status: replayed")
    print(f"Regimes: {len(summaries)}")
    for row in summaries:
        print(
            f"{row['regime']}: days={row['trade_days']} "
            f"spread={row.get('mean_long_short_return', float('nan')):.6f} "
            f"hit={row.get('spread_hit_rate', float('nan')):.2%} "
            f"dd={row.get('max_drawdown', float('nan')):.2%} "
            f"replaced={row.get('replaced_original_top_days', 0)}"
        )
    print(f"Saved -> {args.output_dir}")


if __name__ == "__main__":
    main()
