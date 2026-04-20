"""
MEAN_REVERT — Seed #7
Academic basis: De Bondt & Thaler (1985); Poterba & Summers (1988).
RSI < 30 → oversold → long; RSI > 70 → overbought → short.
Included as tournament contrast to momentum — expected to OPPOSE momentum returns.
Note: rsi_14 was tested alone in the EPM DL model (2026-04-02) and not promoted.
This implementation also tests multi-period RSI (7, 14, 28) as a group.
"""

import numpy as np
import pandas as pd


def _rsi(prices: pd.DataFrame, period: int) -> pd.DataFrame:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period, min_periods=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def mean_reversion_signal(
    prices: pd.DataFrame,
    prices_extra: dict | None = None,
    rsi_period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
) -> pd.DataFrame:
    """
    RSI < oversold → long; RSI > overbought → short.
    This OPPOSES momentum — expected to underperform in trending markets.
    """
    rsi = _rsi(prices, rsi_period)
    signal = pd.DataFrame(0, index=prices.index, columns=prices.columns)
    signal[rsi < oversold] = 1
    signal[rsi > overbought] = -1
    return signal


def rsi_features(prices: pd.DataFrame) -> dict:
    """
    Multi-period RSI features for DL model.
    rsi_14 was tested alone and removed (2026-04-02). Test as a group.
    """
    return {
        "rsi_7": _rsi(prices, 7),
        "rsi_14": _rsi(prices, 14),
        "rsi_28": _rsi(prices, 28),
    }
