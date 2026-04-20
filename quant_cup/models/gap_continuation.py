"""
GAP_CONTINUATION — Seed #6
Practitioner basis: Toby Crabel (1990); CMT curriculum.
Gap > 2% at open + volume in top 30% of 20-day average → enter in gap direction.
Intraday hold (close at end of same day). Requires Open + Volume.
"""

import numpy as np
import pandas as pd


def gap_continuation_signal(
    prices: pd.DataFrame,
    prices_extra: dict | None = None,
    gap_threshold: float = 0.02,
    vol_ratio_threshold: float = 1.3,
    vol_lookback: int = 20,
    holding_days: int = 1,
) -> pd.DataFrame:
    """
    Gap up + high volume → long (continuation).
    Gap down + high volume → short (continuation).
    Default hold: 1 day (intraday). Set holding_days > 1 for multi-day.

    Without open prices, computes gap as close-to-close return (proxy).
    Without volume, ignores volume filter.
    """
    close = prices

    if prices_extra and "open" in prices_extra:
        open_prices = prices_extra["open"].reindex_like(close)
        overnight_gap = open_prices / close.shift(1) - 1
    else:
        # Fallback: close-to-close return as gap proxy
        overnight_gap = close.pct_change()

    signal = pd.DataFrame(0, index=close.index, columns=close.columns)

    if prices_extra and "volume" in prices_extra:
        volume = prices_extra["volume"].reindex_like(close)
        avg_vol = volume.rolling(vol_lookback, min_periods=vol_lookback // 2).mean()
        vol_ratio = volume / avg_vol.replace(0, np.nan)
        high_vol = vol_ratio > vol_ratio_threshold
    else:
        high_vol = pd.DataFrame(True, index=close.index, columns=close.columns)

    # Gap up + high volume → long
    gap_up = (overnight_gap > gap_threshold) & high_vol
    # Gap down + high volume → short
    gap_down = (overnight_gap < -gap_threshold) & high_vol

    if holding_days == 1:
        signal[gap_up] = 1
        signal[gap_down] = -1
    else:
        long_active = gap_up.astype(float).rolling(holding_days, min_periods=1).max().fillna(0) > 0
        short_active = gap_down.astype(float).rolling(holding_days, min_periods=1).max().fillna(0) > 0
        signal[long_active] = 1
        signal[(short_active) & (~long_active)] = -1

    return signal


def gap_features(
    prices: pd.DataFrame,
    prices_extra: dict | None = None,
    lookback: int = 5,
    gap_threshold: float = 0.01,
) -> dict:
    """
    Extract Tier-2 DL feature: gap_magnitude_5d (avg close-to-open gap over last 5 sessions).
    """
    close = prices

    if prices_extra and "open" in prices_extra:
        open_prices = prices_extra["open"].reindex_like(close)
        gap = (open_prices / close.shift(1) - 1).abs()
    else:
        gap = close.pct_change().abs()

    gap_magnitude = gap.rolling(lookback, min_periods=lookback // 2).mean()
    gap_5d_count = (gap > gap_threshold).rolling(lookback, min_periods=lookback // 2).sum()

    return {
        "gap_magnitude_5d": gap_magnitude,
        "gap_5d_count": gap_5d_count,
    }
