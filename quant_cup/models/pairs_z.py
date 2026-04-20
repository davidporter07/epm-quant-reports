"""
PAIRS_Z — Seed #5
Academic basis: Gatev, Goetzmann & Rouwenhorst (2006) RFS; Avellaneda & Lee (2010) QF.
Market-neutral: long A / short B when log-spread z-score < -2, reverse at +2.
Exit on z-score reversion to 0 (or holding period expiry).

Computationally expensive for 500 stocks (C(500,2) = 124,750 pairs).
Strategy: restrict to within-GICS-sector pairs to limit combinatorial explosion
and improve economic rationale (same-sector pairs have stronger mean-reversion basis).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ENTRY_Z = 2.0
EXIT_Z = 0.5
CORR_THRESHOLD = 0.80
FORMATION_DAYS = 252
MAX_PAIRS_PER_SECTOR = 10
HOLDING_LIMIT = 60  # days — exit if spread hasn't reverted


def _find_pairs(
    log_prices: pd.DataFrame,
    formation_end: pd.Timestamp,
    sector_map: dict[str, str] | None = None,
) -> list[tuple[str, str, float]]:
    """
    Find highly correlated pairs in the formation window.
    Returns list of (tickerA, tickerB, correlation).
    If sector_map provided, only consider same-sector pairs.
    """
    window = log_prices.loc[:formation_end].tail(FORMATION_DAYS)
    window = window.dropna(axis=1, thresh=FORMATION_DAYS // 2)

    if sector_map:
        # Group tickers by sector
        by_sector: dict[str, list[str]] = {}
        for t in window.columns:
            s = sector_map.get(t, "Unknown")
            by_sector.setdefault(s, []).append(t)
    else:
        by_sector = {"all": list(window.columns)}

    pairs = []
    for sector, tickers in by_sector.items():
        if len(tickers) < 2:
            continue
        sub = window[tickers]
        corr = sub.corr()
        # Upper triangle only
        sector_pairs = []
        for i, a in enumerate(tickers):
            for b in tickers[i + 1 :]:
                c = corr.at[a, b]
                if c >= CORR_THRESHOLD:
                    sector_pairs.append((a, b, c))
        # Top pairs by correlation
        sector_pairs.sort(key=lambda x: x[2], reverse=True)
        pairs.extend(sector_pairs[:MAX_PAIRS_PER_SECTOR])

    return pairs


def pairs_zscore_signal(
    prices: pd.DataFrame,
    prices_extra: dict | None = None,
    sector_map: dict[str, str] | None = None,
    composition=None,
    lookback: int = FORMATION_DAYS,
    entry_z: float = ENTRY_Z,
    exit_z: float = EXIT_Z,
) -> pd.DataFrame:
    """
    Rolling pairs trading signal.
    Re-forms pairs annually, applies z-score entry/exit rules daily.
    Returns signal matrix: +1 (long) / -1 (short) / 0 (flat) per ticker.

    sector_map: dict mapping ticker → GICS sector (reduces pair universe).
    composition: SP500Composition instance — if provided, only pairs both in
                 the index at formation time are eligible (eliminates survivorship bias).
    """
    log_prices = np.log(prices.replace(0, np.nan))
    signal = pd.DataFrame(0, index=prices.index, columns=prices.columns)

    dates = prices.index
    # First actual trading day of each calendar year (is_year_start matches Jan 1 only,
    # which is never a trading day — use groupby year instead)
    year_firsts = pd.DatetimeIndex(
        dates.to_series().groupby(dates.year).first().values
    )
    # Need at least `lookback` days of price history before a reform date can trade
    first_valid = dates[lookback] if len(dates) > lookback else dates[-1]
    reform_dates = year_firsts[year_firsts >= first_valid]

    for reform_date in reform_dates:
        end_idx = dates.searchsorted(reform_date) + lookback
        if end_idx > len(dates):
            end_idx = len(dates)
        period_dates = dates[dates.searchsorted(reform_date) : end_idx]

        # Filter log_prices to only tickers in the index at reform_date
        if composition is not None:
            valid = composition.members_on(reform_date)
            eligible_cols = [c for c in log_prices.columns if c in valid]
            lp_eligible = log_prices[eligible_cols]
        else:
            lp_eligible = log_prices

        pairs = _find_pairs(lp_eligible, reform_date, sector_map)
        if not pairs:
            continue

        log.debug(f"  {reform_date.date()}: {len(pairs)} pairs formed (universe={lp_eligible.shape[1]})")

        for ticker_a, ticker_b, _ in pairs:
            if ticker_a not in log_prices.columns or ticker_b not in log_prices.columns:
                continue

            # Compute z-score of log-spread over rolling lookback
            spread = log_prices[ticker_a] - log_prices[ticker_b]
            roll_mean = spread.rolling(lookback, min_periods=lookback // 2).mean()
            roll_std = spread.rolling(lookback, min_periods=lookback // 2).std()
            z = (spread - roll_mean) / roll_std.replace(0, np.nan)

            # Apply signals within this period
            in_trade = False
            trade_direction = 0
            entry_day = None

            for date in period_dates:
                if date not in z.index:
                    continue
                z_val = z.get(date, np.nan)
                if np.isnan(z_val):
                    continue

                if not in_trade:
                    if z_val < -entry_z:
                        # Spread too low: long A, short B
                        trade_direction = 1
                        in_trade = True
                        entry_day = date
                    elif z_val > entry_z:
                        # Spread too high: short A, long B
                        trade_direction = -1
                        in_trade = True
                        entry_day = date
                else:
                    days_in = (date - entry_day).days
                    # Exit on reversion or holding limit
                    if abs(z_val) < exit_z or days_in > HOLDING_LIMIT:
                        in_trade = False
                        trade_direction = 0
                        entry_day = None
                    else:
                        signal.at[date, ticker_a] = trade_direction
                        signal.at[date, ticker_b] = -trade_direction

    return signal
