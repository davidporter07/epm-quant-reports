"""
PEAD — Seed #2 (Post-Earnings Announcement Drift)
Academic basis: Bernard & Thomas (1989, 1990). Stocks in top SUE decile drift +2-4%
over 60 days post-earnings. Decay documented in Chordia et al. (2014).

DATA LIMITATION: yfinance earnings_history covers ~8 quarters per stock (~2023-2025).
For a full 2006-2025 backtest, use Sharadar SFPO on Nasdaq Data Link (paid).
This implementation uses whatever history yfinance provides and notes the gap.
"""

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

HOLDING_DAYS = 20
SURPRISE_THRESHOLD = 0.03  # 3% EPS surprise threshold


def _build_signal_from_earnings(
    earnings_df: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    """
    Given a long-form earnings DataFrame (indexed by date, with 'ticker' and
    'surprisePercent' columns), build a daily signal matrix.

    A stock gets signal +1 for HOLDING_DAYS days after a positive surprise,
    -1 for HOLDING_DAYS days after a negative surprise.
    Later signals overwrite earlier ones for the same stock.
    """
    signal = pd.DataFrame(0, index=prices.index, columns=prices.columns)

    required_cols = {"ticker", "surprisePercent"}
    if earnings_df.empty or not required_cols.issubset(earnings_df.columns):
        log.warning("PEAD: earnings DataFrame missing required columns — returning zero signal")
        return signal

    price_dates = prices.index

    for date, row in earnings_df.iterrows():
        ticker = row["ticker"]
        surprise = row.get("surprisePercent", None)

        if ticker not in signal.columns or surprise is None or np.isnan(surprise):
            continue

        direction = 1 if surprise > SURPRISE_THRESHOLD else (-1 if surprise < -SURPRISE_THRESHOLD else 0)
        if direction == 0:
            continue

        # Apply signal for HOLDING_DAYS after the earnings date
        start_idx = price_dates.searchsorted(date)
        end_idx = min(start_idx + HOLDING_DAYS, len(price_dates))
        for i in range(start_idx, end_idx):
            signal.at[price_dates[i], ticker] = direction

    return signal


def pead_signal(
    prices: pd.DataFrame,
    prices_extra: dict | None = None,
    earnings_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Build PEAD signal from preloaded earnings data.

    earnings_df: output of data_loader.load_earnings() — long-form DataFrame indexed
                 by earnings date with columns [ticker, epsEstimate, epsActual, surprisePercent].

    If earnings_df is None, returns a zero signal with a warning.
    Tournament should pass earnings_df explicitly.
    """
    if earnings_df is None or earnings_df.empty:
        log.warning(
            "PEAD: No earnings data provided. "
            "Pass earnings_df from data_loader.load_earnings(). "
            "Note: yfinance only has ~8 quarters of history per stock."
        )
        return pd.DataFrame(0, index=prices.index, columns=prices.columns)

    return _build_signal_from_earnings(earnings_df, prices)


def pead_features(earnings_df: pd.DataFrame, prices: pd.DataFrame) -> dict:
    """
    Extract Tier-2 DL feature candidates.
    Returns per-ticker, per-date DataFrames for use with feature_tester.py.
    """
    if earnings_df.empty:
        return {}

    # earnings_surprise_last: most recent surprise %
    # earnings_beat_rate_4q: count of positive surprises in last 4 quarters
    surprise_last = pd.DataFrame(np.nan, index=prices.index, columns=prices.columns)
    beat_rate_4q = pd.DataFrame(np.nan, index=prices.index, columns=prices.columns)

    for ticker, grp in earnings_df.groupby("ticker"):
        if ticker not in prices.columns:
            continue
        grp = grp.sort_index()
        for date in prices.index:
            past = grp[grp.index <= date]
            if past.empty:
                continue
            last_surp = past["surprisePercent"].iloc[-1]
            surprise_last.at[date, ticker] = last_surp
            # Last 4 quarters
            last_4 = past.tail(4)
            beat_rate_4q.at[date, ticker] = int((last_4["surprisePercent"] > 0).sum())

    return {
        "earnings_surprise_last": surprise_last,
        "earnings_beat_rate_4q": beat_rate_4q,
    }
