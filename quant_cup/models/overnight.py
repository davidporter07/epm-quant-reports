"""
OVERNIGHT — Seed #4
Academic basis: Lou, Polk & Skouras (2019) JFE; Branch & Ma (2012).
~60-80% of long-run S&P 500 returns come from overnight gaps, not intraday moves.
Strategy: buy at close, sell at next open — pure overnight return capture.

Requires Open prices. yfinance provides these via auto_adjust=True download.
"""

import numpy as np
import pandas as pd


def overnight_signal(
    prices: pd.DataFrame,
    prices_extra: dict | None = None,
    top_pct: float = 0.3,
    lookback: int = 20,
) -> pd.DataFrame:
    """
    Simple version: long all stocks always (overnight drift is positive on average).
    Enhanced version: rank stocks by their trailing overnight return consistency
    and long only the top 30% — stocks with persistent overnight premium.

    If open prices are unavailable, falls back to a simple all-long signal.
    """
    close = prices

    if prices_extra is None or "open" not in prices_extra:
        # Degenerate but valid: long everything, captures broad overnight premium
        return pd.DataFrame(1, index=close.index, columns=close.columns)

    open_prices = prices_extra["open"].reindex_like(close)

    # Overnight return: open[t] / close[t-1] - 1
    overnight_ret = open_prices / close.shift(1) - 1

    # Rolling mean overnight return over last `lookback` days
    rolling_overnight = overnight_ret.rolling(lookback, min_periods=lookback // 2).mean()

    # Long stocks in top `top_pct` of recent overnight return momentum
    rank = rolling_overnight.rank(axis=1, pct=True)
    signal = pd.DataFrame(0, index=close.index, columns=close.columns)
    signal[rank > (1 - top_pct)] = 1

    return signal


def overnight_features(
    prices: pd.DataFrame,
    prices_extra: dict | None = None,
    lookback: int = 20,
) -> dict:
    """
    Extract Tier-1 DL feature candidates: overnight_return_Nd, intraday_return_Nd.
    Lou et al. (2019) show these have opposite expected-return signs on many stocks.
    """
    close = prices

    if prices_extra is None or "open" not in prices_extra:
        return {}

    open_prices = prices_extra["open"].reindex_like(close)

    overnight_ret = open_prices / close.shift(1) - 1
    intraday_ret = close / open_prices - 1

    overnight_5d = overnight_ret.rolling(5, min_periods=3).mean()
    intraday_5d = intraday_ret.rolling(5, min_periods=3).mean()
    overnight_20d = overnight_ret.rolling(lookback, min_periods=lookback // 2).mean()
    intraday_20d = intraday_ret.rolling(lookback, min_periods=lookback // 2).mean()

    return {
        "overnight_return_5d": overnight_5d,
        "intraday_return_5d": intraday_5d,
        "overnight_return_20d": overnight_20d,
        "intraday_return_20d": intraday_20d,
    }
