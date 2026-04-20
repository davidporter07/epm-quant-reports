"""
VOL_COMPRESSION — Seed #3
Academic basis: Mandelbrot (1963) volatility clustering, GARCH literature, Carr & Wu (2006).
When ATR falls below its 20th percentile (compression), the subsequent breakout tends to
be directional. Enter long/short on the day compression breaks with price confirmation.
"""

import numpy as np
import pandas as pd


def _true_range(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """Standard True Range = max(H-L, |H-Cprev|, |L-Cprev|)."""
    hl = high - low
    hc = (high - close.shift(1)).abs()
    lc = (low - close.shift(1)).abs()
    tr = np.maximum(hl.values, np.maximum(hc.values, lc.values))
    return pd.DataFrame(tr, index=high.index, columns=high.columns)


def _atr(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    tr = _true_range(high, low, close)
    return tr.rolling(period, min_periods=period).mean()


def vol_compression_signal(
    prices: pd.DataFrame,
    prices_extra: dict | None = None,
    atr_period: int = 14,
    lookback: int = 252,
    compression_pct: int = 20,
    breakout_multiplier: float = 1.5,
    holding_days: int = 20,
) -> pd.DataFrame:
    """
    1. Compute ATR(14) as % of close.
    2. Rolling 252-day percentile rank of ATR%.
    3. When percentile < 20 (compression zone), watch for breakout.
    4. Breakout: today's close > yesterday's high (or < yesterday's low) while ATR was compressed.
    5. Hold for holding_days.
    """
    close = prices

    if prices_extra and "high" in prices_extra and "low" in prices_extra:
        high = prices_extra["high"].reindex_like(close)
        low = prices_extra["low"].reindex_like(close)
        atr = _atr(high, low, close, atr_period)
    else:
        # Fallback: use rolling std as ATR proxy when only close available
        atr = close.rolling(atr_period, min_periods=atr_period).std()

    atr_pct = atr / close  # ATR as % of price

    # Rolling percentile rank (0-100) within 252-day window
    atr_percentile = (
        atr_pct.rolling(lookback, min_periods=lookback // 2)
        .rank(pct=True)
        .multiply(100)
    )

    compression = atr_percentile < compression_pct

    # Breakout: price breaks above prior high or below prior low
    # Using close-to-close breakout (simpler, avoids intraday data dependency)
    recent_high = close.rolling(5).max().shift(1)
    recent_low = close.rolling(5).min().shift(1)

    breakout_up = (close > recent_high) & compression.shift(1)
    breakout_down = (close < recent_low) & compression.shift(1)

    # Vectorized holding period: if any breakout in the last holding_days sessions, signal active.
    # rolling(holding_days).max() on the entry flags propagates the entry forward.
    long_active = breakout_up.astype(float).rolling(holding_days, min_periods=1).max().fillna(0) > 0
    short_active = breakout_down.astype(float).rolling(holding_days, min_periods=1).max().fillna(0) > 0

    signal = pd.DataFrame(0, index=close.index, columns=close.columns)
    signal[long_active] = 1
    # Short only where no concurrent long
    signal[(short_active) & (~long_active)] = -1

    return signal


def vol_compression_features(
    prices: pd.DataFrame,
    prices_extra: dict | None = None,
    atr_period: int = 14,
    lookback: int = 252,
) -> dict:
    """
    Extract Tier-2 DL feature candidates: hv_percentile, atr_percentile, vol_regime.
    """
    close = prices

    if prices_extra and "high" in prices_extra and "low" in prices_extra:
        high = prices_extra["high"].reindex_like(close)
        low = prices_extra["low"].reindex_like(close)
        atr = _atr(high, low, close, atr_period)
    else:
        atr = close.rolling(atr_period, min_periods=atr_period).std()

    atr_pct = atr / close
    atr_percentile = (
        atr_pct.rolling(lookback, min_periods=lookback // 2)
        .rank(pct=True)
        .multiply(100)
    )

    hv_20 = close.pct_change().rolling(20).std() * (252 ** 0.5)
    hv_percentile = (
        hv_20.rolling(lookback, min_periods=lookback // 2)
        .rank(pct=True)
        .multiply(100)
    )

    vol_regime = (atr_percentile < 20).astype(int)

    return {
        "atr_percentile": atr_percentile,
        "hv_percentile": hv_percentile,
        "vol_regime": vol_regime,
    }
