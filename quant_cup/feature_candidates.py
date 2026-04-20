"""
Quant Model Cup — Feature Candidate Extractor
Reads tournament results and computes winning-strategy features for a target ticker.
Output is a CSV ready for inspection before passing to feature_tester.py.

Usage:
    python quant_cup/feature_candidates.py --tickers AAPL MSFT NVDA
    python quant_cup/feature_candidates.py --tickers AAPL --tier 1
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from quant_cup.data_loader import load_earnings, load_prices
from quant_cup.models.gap_continuation import gap_features
from quant_cup.models.mean_revert import rsi_features
from quant_cup.models.momentum import momentum_features
from quant_cup.models.overnight import overnight_features
from quant_cup.models.vol_compression import vol_compression_features

log = logging.getLogger(__name__)

# Feature tiers from the handoff research:
# Tier 1 — unconditionally include (strong academic backing, clean single-stock computation)
# Tier 2 — include with clean data / point-in-time earnings
# rsi_14 alone was tested and removed 2026-04-02 — included here only as part of multi-lookback group

TIER1_FEATURES = [
    "momentum_12_1",
    "momentum_6_1",
    "momentum_3_1",
    "overnight_return_5d",
    "intraday_return_5d",
    "overnight_return_20d",
    "intraday_return_20d",
]

TIER2_FEATURES = [
    "hv_percentile",
    "atr_percentile",
    "vol_regime",
    "earnings_surprise_last",
    "earnings_beat_rate_4q",
    "gap_magnitude_5d",
    "gap_5d_count",
    "rsi_7",
    "rsi_14",
    "rsi_28",
]


def compute_features(
    tickers: list[str],
    start: str = "2006-01-01",
    end: str = "2025-12-31",
    tier: int = 1,
) -> pd.DataFrame:
    """
    Compute all candidate features for specified tickers.
    Returns a long-format DataFrame: date × (ticker, feature).
    """
    log.info(f"Loading prices for {len(tickers)} tickers...")
    all_prices = load_prices(start=start, end=end)
    close = all_prices["close"]
    extra = {k: v for k, v in all_prices.items() if k != "close"}

    # Filter to requested tickers (add any missing ones gracefully)
    available = [t for t in tickers if t in close.columns]
    if len(available) < len(tickers):
        missing = set(tickers) - set(available)
        log.warning(f"Tickers not in price data: {missing}")

    close_sub = close[available]
    extra_sub = {k: v[available] for k, v in extra.items() if not v.empty}

    all_features: dict[str, pd.DataFrame] = {}

    # Tier 1
    log.info("Computing Tier-1 features: momentum, overnight/intraday split...")
    all_features.update(momentum_features(close_sub))
    all_features.update(overnight_features(close_sub, prices_extra=extra_sub))

    if tier >= 2:
        log.info("Computing Tier-2 features: vol, gap, RSI, earnings...")
        all_features.update(
            vol_compression_features(close_sub, prices_extra=extra_sub)
        )
        all_features.update(gap_features(close_sub, prices_extra=extra_sub))
        all_features.update(rsi_features(close_sub))

        earnings_df = load_earnings(tickers=available)
        if not earnings_df.empty:
            from quant_cup.models.pead import pead_features

            all_features.update(pead_features(earnings_df, close_sub))
        else:
            log.warning(
                "No earnings data available for PEAD features. "
                "earnings_surprise_last and earnings_beat_rate_4q will be omitted."
            )

    # Melt into long format: index=(date, ticker), columns=features
    records = []
    for feat_name, df in all_features.items():
        if df is None or df.empty:
            continue
        melted = df.stack(future_stack=True).rename(feat_name)
        records.append(melted)

    if not records:
        return pd.DataFrame()

    result = pd.concat(records, axis=1)
    result.index.names = ["date", "ticker"]
    return result.reset_index()


def _print_summary(df: pd.DataFrame):
    print("\n=== Feature Candidate Summary ===")
    print(f"Rows: {len(df):,}  |  Features: {len(df.columns) - 2}")
    print("\nFeature completeness (non-null %):")
    feat_cols = [c for c in df.columns if c not in ("date", "ticker")]
    for col in feat_cols:
        pct = df[col].notna().mean() * 100
        tier = "T1" if col in TIER1_FEATURES else "T2"
        print(f"  [{tier}] {col:<30} {pct:>5.1f}%")

    print("\n=== NEXT STEPS ===")
    print("1. Inspect this CSV for look-ahead bias (especially earnings features).")
    print("2. For each feature, register with feature_registry.py:")
    print("   python feature_registry.py register --name momentum_12_1 --type float")
    print("3. Run A/B test via feature_tester.py:")
    print("   python feature_tester.py --feature momentum_12_1")
    print("4. If test passes threshold, promote:")
    print("   python feature_promoter.py --feature momentum_12_1")
    print("\nDo NOT add features to the DL model without passing the feature_tester.py gate.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Extract DL feature candidates from Quant Cup strategies")
    parser.add_argument("--tickers", nargs="+", default=["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"])
    parser.add_argument("--start", default="2006-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--tier", type=int, default=1, choices=[1, 2], help="Feature tier (1=Tier1 only, 2=both)")
    parser.add_argument("--output", default="quant_cup/results/feature_candidates.csv")
    args = parser.parse_args()

    df = compute_features(
        tickers=args.tickers,
        start=args.start,
        end=args.end,
        tier=args.tier,
    )

    if df.empty:
        print("No features computed. Check that prices downloaded successfully.")
        return

    df.to_csv(args.output, index=False)
    print(f"\nSaved {len(df):,} rows to {args.output}")
    _print_summary(df)


if __name__ == "__main__":
    main()
