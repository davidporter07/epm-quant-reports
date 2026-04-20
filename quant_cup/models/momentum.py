"""
MOMENTUM — Seed #1
Academic basis: Jegadeesh & Titman (1993, 2001) "Returns to Buying Winners and Selling Losers"
12-1 month formation (skip last month to avoid short-term reversal contamination).
Long top decile, short bottom decile. Monthly rebalance.

Known risk: momentum crashes during sharp reversals (2009, 2020). See Daniel & Moskowitz (2016).
"""

import numpy as np
import pandas as pd


def momentum_signal(
    prices: pd.DataFrame,
    formation: int = 252,
    skip: int = 21,
    long_pct: float = 0.1,
    short_pct: float = 0.1,
) -> pd.DataFrame:
    """
    Ranks stocks by past (formation - skip) day return.
    Long top `long_pct` decile, short bottom `short_pct` decile.
    Returns DataFrame of signals: +1 long, -1 short, 0 flat.
    """
    # 12-1 month return: price 21 days ago / price 252 days ago
    past_return = prices.shift(skip) / prices.shift(formation) - 1

    # Percentile rank across tickers for each day
    pct_rank = past_return.rank(axis=1, pct=True)

    signal = pd.DataFrame(0, index=prices.index, columns=prices.columns)
    signal[pct_rank > (1 - long_pct)] = 1
    signal[pct_rank < short_pct] = -1

    # Require minimum number of stocks to form valid portfolio
    n_valid = past_return.notna().sum(axis=1)
    signal[n_valid < 20] = 0

    return signal


def momentum_features(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Extract Tier-1 DL feature candidates from the momentum signal.
    Returns DataFrame with momentum_12_1, momentum_6_1, momentum_3_1 per ticker.
    """
    feats = pd.DataFrame(index=prices.index, columns=prices.columns)

    momentum_12_1 = prices.shift(21) / prices.shift(252) - 1
    momentum_6_1 = prices.shift(21) / prices.shift(126) - 1
    momentum_3_1 = prices.shift(21) / prices.shift(63) - 1

    return {
        "momentum_12_1": momentum_12_1,
        "momentum_6_1": momentum_6_1,
        "momentum_3_1": momentum_3_1,
    }
