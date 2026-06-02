"""
Quant Model Cup — Tournament Runner
Runs the active single-factor models against S&P 500, 2006-2025.
Ranks by CAGR vs SPY buy-and-hold baseline.
Outputs results/round1.json.

Retired 2026-06-02 (Quant Cup Round 1, bottom 3 of 8 — only negative-return
strategies): MOMENTUM, VOL_COMPRESSION, GAP_CONTINUATION. Their `_signal`
functions are dropped from the roster below; the model files stay in place
because their `_features` extractors still feed the DL feature panel.

Usage:
    python quant_cup/tournament.py
    python quant_cup/tournament.py --start 2006-01-01 --end 2025-12-31 --models pead,overnight,pairs_z
    python quant_cup/tournament.py --dev  # 2020-2025 only, faster for iteration
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd

# Allow running as script from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

import os

from dotenv import load_dotenv

load_dotenv()

from quant_cup.backtest_engine import run_backtest
from quant_cup.data_loader import (
    get_sp500_with_sectors,
    load_earnings,
    load_prices,
)
from quant_cup.earnings_av import cache_status as av_cache_status
from quant_cup.earnings_av import load_earnings_av
from quant_cup.earnings_fmp import cache_status, load_earnings_fmp
# Retired 2026-06-02 (negative-return, bottom 3 of Quant Cup Round 1):
#   momentum_signal, vol_compression_signal, gap_continuation_signal.
# The modules remain importable for their `_features` extractors (DL panel).
from quant_cup.models.mean_revert import mean_reversion_signal
from quant_cup.models.overnight import overnight_signal
from quant_cup.models.pairs_diverge import pairs_diverge_signal
from quant_cup.models.pairs_z import pairs_zscore_signal
from quant_cup.models.pead import pead_signal
from quant_cup.sp500_composition import SP500Composition

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def _build_sector_map(sp500_df: pd.DataFrame) -> dict[str, str]:
    return dict(zip(sp500_df["Symbol"], sp500_df["GICS Sector"]))


def _run_all(
    prices: dict[str, pd.DataFrame],
    sp500_df: pd.DataFrame,
    earnings_df: pd.DataFrame,
    start: str,
    end: str,
    models_filter: list[str] | None = None,
    composition: "SP500Composition | None" = None,
) -> list[dict]:
    close = prices["close"]
    extra = {k: v for k, v in prices.items() if k != "close"}
    sector_map = _build_sector_map(sp500_df)

    # PEAD needs earnings injected at call time
    def _pead(p, prices_extra=None):
        return pead_signal(p, prices_extra=prices_extra, earnings_df=earnings_df)

    # Pairs models get sector_map + point-in-time composition (eliminates survivorship bias)
    def _pairs_z(p, prices_extra=None):
        return pairs_zscore_signal(
            p, prices_extra=prices_extra, sector_map=sector_map, composition=composition
        )

    def _pairs_diverge(p, prices_extra=None):
        return pairs_diverge_signal(
            p, prices_extra=prices_extra, sector_map=sector_map, composition=composition
        )

    # (fn, rebalance, extra_kwargs)
    # MOMENTUM, VOL_COMPRESSION, GAP_CONTINUATION retired 2026-06-02 (bottom 3
    # of Round 1, only negative-CAGR strategies). See module docstring.
    all_models = {
        "PEAD":            (_pead,                  "daily",   {}),
        "OVERNIGHT":       (overnight_signal,        "monthly", {"use_overnight_returns": True}),
        "PAIRS_Z":         (_pairs_z,                "daily",   {}),
        "MEAN_REVERT":     (mean_reversion_signal,   "monthly", {}),
        "PAIRS_DIVERGE":   (_pairs_diverge,          "daily",   {}),
    }

    if models_filter:
        all_models = {k: v for k, v in all_models.items() if k in models_filter}

    results = []
    for name, (fn, rebalance, extra_kwargs) in all_models.items():
        log.info(f"Running {name}...")
        t0 = time.time()
        try:
            result = run_backtest(
                model_fn=fn,
                prices=close,
                model_name=name,
                start=start,
                end=end,
                rebalance=rebalance,
                prices_extra=extra if extra else None,
                **extra_kwargs,
            )
            elapsed = time.time() - t0
            log.info(
                f"  {name}: CAGR={result.cagr:.2%}  Sharpe={result.sharpe:.2f}"
                f"  MaxDD={result.max_drawdown:.2%}  SPY={result.spy_cagr:.2%}"
                f"  Beats={'YES' if result.beats_buyhold else 'NO'}"
                f"  ({elapsed:.1f}s)"
            )
            d = result.to_dict()
            d["elapsed_s"] = round(elapsed, 1)
            results.append(d)
        except Exception as exc:
            log.error(f"  {name} FAILED: {exc}", exc_info=True)
            results.append({"model_name": name, "error": str(exc)})

    return results


def _rank_and_report(results: list[dict]) -> list[dict]:
    valid = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]

    # Rank by CAGR (primary), Sharpe (secondary)
    valid.sort(key=lambda r: (r.get("cagr", -999), r.get("sharpe", -999)), reverse=True)

    for rank, r in enumerate(valid, 1):
        r["rank"] = rank
        beats = r.get("beats_buyhold", False)
        r["advances"] = beats and rank == 1

    for r in failed:
        r["rank"] = None
        r["advances"] = False

    return valid + failed


def run_tournament(
    start: str = "2006-01-01",
    end: str = "2025-12-31",
    models_filter: list[str] | None = None,
    force_refresh: bool = False,
    output_file: str = "round1.json",
    fmp_api_key: str | None = None,
) -> Path:
    log.info(f"=== Quant Model Cup  {start} → {end} ===")

    # --- Point-in-time S&P 500 composition (eliminates survivorship bias) ---
    log.info("Loading S&P 500 historical composition...")
    composition = SP500Composition(force_refresh=force_refresh)
    coverage = composition.coverage_report(start, end)
    log.info(
        f"  Composition: {coverage['total_changes']} changes tracked, "
        f"{coverage['unique_tickers_ever']} unique tickers in universe"
    )

    # --- Price data: use full historical universe, not just current S&P 500 ---
    log.info("Loading price data...")
    universe = sorted(composition.universe_for_period(start, end) | {"SPY"})
    log.info(f"  Downloading {len(universe)} tickers (historical universe, survivorship-bias-free)")
    prices = load_prices(start=start, end=end, force_refresh=force_refresh, tickers=list(universe))

    log.info("Loading S&P 500 sector data...")
    sp500_df = get_sp500_with_sectors()

    # --- Earnings: AV (20yr, 120 qtrs/ticker) > FMP (legacy blocked) > yfinance (3 qtrs) ---
    av_key = os.environ.get("AV_API_KEY", "")
    fmp_key = fmp_api_key or os.environ.get("FMP_API_KEY", "")
    if av_key:
        log.info("AV key found — loading earnings from Alpha Vantage cache...")
        earnings_df = load_earnings_av(api_key=None, start=start, end=end)
        status = av_cache_status()
        log.info(f"  AV cache: {status['cached']} cached, {status['missing']} missing "
                 f"(~{status['est_days_remaining']} day(s) remaining at 500/day free tier)")
        earnings_source = "AlphaVantage"
    elif fmp_key:
        log.info("FMP key found — loading earnings from FMP...")
        earnings_df = load_earnings_fmp(api_key=fmp_key, start=start, end=end)
        earnings_source = "FMP"
    else:
        log.info("No earnings API key — falling back to yfinance (~3 quarters only).")
        earnings_df = load_earnings()
        earnings_source = "yfinance (limited)"

    results = _run_all(
        prices, sp500_df, earnings_df, start, end, models_filter, composition=composition
    )
    ranked = _rank_and_report(results)

    output_path = RESULTS_DIR / output_file
    payload = {
        "tournament": "Quant Model Cup",
        "start": start,
        "end": end,
        "data_quality": {
            "survivorship_bias": "eliminated via point-in-time S&P 500 composition",
            "composition_changes_tracked": coverage["total_changes"],
            "historical_universe_size": coverage["unique_tickers_ever"],
            "earnings_source": earnings_source,
            "pairs_universe": "point-in-time (no look-ahead)",
        },
        "spy_baseline": ranked[0]["spy_cagr"] if ranked else None,
        "models": ranked,
    }

    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)

    log.info(f"\n=== RESULTS ===")
    log.info(f"{'Rank':<6} {'Model':<20} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} {'Beats SPY'}")
    log.info("-" * 60)
    for r in ranked:
        if "error" in r:
            log.info(f"{'ERR':<6} {r['model_name']:<20}  FAILED: {r['error']}")
        else:
            log.info(
                f"{r['rank']:<6} {r['model_name']:<20}"
                f"  {r['cagr']:>7.2%}  {r['sharpe']:>7.2f}"
                f"  {r['max_drawdown']:>7.2%}  {'YES' if r['beats_buyhold'] else 'no'}"
            )

    log.info(f"\nSaved to {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Quant Model Cup Tournament")
    parser.add_argument("--start", default="2006-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--dev", action="store_true", help="Fast mode: 2020-2025, top 50 tickers")
    parser.add_argument(
        "--models",
        default=None,
        help="Comma-separated model names to run (default: all 8)",
    )
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--output", default="round1.json")
    parser.add_argument(
        "--fmp-key",
        default=None,
        help="Financial Modeling Prep API key (overrides FMP_API_KEY env var)",
    )
    args = parser.parse_args()

    start = "2020-01-01" if args.dev else args.start
    end = args.end
    models_filter = [m.strip().upper() for m in args.models.split(",")] if args.models else None

    run_tournament(
        start=start,
        end=end,
        models_filter=models_filter,
        force_refresh=args.force_refresh,
        output_file=args.output,
        fmp_api_key=args.fmp_key,
    )


if __name__ == "__main__":
    main()
