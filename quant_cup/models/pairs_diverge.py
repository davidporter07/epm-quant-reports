"""
PAIRS_DIVERGE — Seed #8
Same architecture as PAIRS_Z but uses price ratio (not log-spread) and requires
tighter correlation (90%+). Targets shorter-duration convergence trades (retail stat-arb).
Entry at 2σ divergence, exit on convergence. Max hold 30 days (vs 60 for PAIRS_Z).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

CORR_THRESHOLD = 0.90
ENTRY_Z = 2.0
EXIT_Z = 0.3
FORMATION_DAYS = 252
MAX_PAIRS_PER_SECTOR = 8
HOLDING_LIMIT = 30


def _find_tight_pairs(
    prices: pd.DataFrame,
    formation_end: pd.Timestamp,
    sector_map: dict[str, str] | None = None,
) -> list[tuple[str, str, float]]:
    window = prices.loc[:formation_end].tail(FORMATION_DAYS)
    window = window.dropna(axis=1, thresh=FORMATION_DAYS // 2)

    if sector_map:
        by_sector: dict[str, list[str]] = {}
        for t in window.columns:
            s = sector_map.get(t, "Unknown")
            by_sector.setdefault(s, []).append(t)
    else:
        by_sector = {"all": list(window.columns)}

    pairs = []
    for _, tickers in by_sector.items():
        if len(tickers) < 2:
            continue
        sub = window[tickers]
        corr = sub.corr()
        sector_pairs = []
        for i, a in enumerate(tickers):
            for b in tickers[i + 1 :]:
                c = corr.at[a, b]
                if c >= CORR_THRESHOLD:
                    sector_pairs.append((a, b, c))
        sector_pairs.sort(key=lambda x: x[2], reverse=True)
        pairs.extend(sector_pairs[:MAX_PAIRS_PER_SECTOR])

    return pairs


def pairs_diverge_signal(
    prices: pd.DataFrame,
    prices_extra: dict | None = None,
    sector_map: dict[str, str] | None = None,
    composition=None,
    lookback: int = FORMATION_DAYS,
    entry_z: float = ENTRY_Z,
    exit_z: float = EXIT_Z,
) -> pd.DataFrame:
    """
    Price-ratio based pairs trading (vs log-spread in PAIRS_Z).
    ratio = price_A / price_B; normalize to z-score over rolling lookback.
    Tighter correlation threshold (0.9) and shorter holding limit (30 days).

    composition: SP500Composition instance — if provided, restricts pair
                 candidates to tickers in the index at formation time.
    """
    signal = pd.DataFrame(0, index=prices.index, columns=prices.columns)
    dates = prices.index
    year_firsts = pd.DatetimeIndex(
        dates.to_series().groupby(dates.year).first().values
    )
    first_valid = dates[lookback] if len(dates) > lookback else dates[-1]
    reform_dates = year_firsts[year_firsts >= first_valid]

    for reform_date in reform_dates:
        end_idx = dates.searchsorted(reform_date) + lookback
        end_idx = min(end_idx, len(dates))
        period_dates = dates[dates.searchsorted(reform_date) : end_idx]

        if composition is not None:
            valid = composition.members_on(reform_date)
            eligible_cols = [c for c in prices.columns if c in valid]
            prices_eligible = prices[eligible_cols]
        else:
            prices_eligible = prices

        pairs = _find_tight_pairs(prices_eligible, reform_date, sector_map)
        if not pairs:
            continue

        for ticker_a, ticker_b, _ in pairs:
            if ticker_a not in prices.columns or ticker_b not in prices.columns:
                continue

            ratio = prices[ticker_a] / prices[ticker_b].replace(0, np.nan)
            roll_mean = ratio.rolling(lookback, min_periods=lookback // 2).mean()
            roll_std = ratio.rolling(lookback, min_periods=lookback // 2).std()
            z = (ratio - roll_mean) / roll_std.replace(0, np.nan)

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
                        trade_direction = 1
                        in_trade = True
                        entry_day = date
                    elif z_val > entry_z:
                        trade_direction = -1
                        in_trade = True
                        entry_day = date
                else:
                    days_in = (date - entry_day).days
                    if abs(z_val) < exit_z or days_in > HOLDING_LIMIT:
                        in_trade = False
                        trade_direction = 0
                        entry_day = None
                    else:
                        signal.at[date, ticker_a] = trade_direction
                        signal.at[date, ticker_b] = -trade_direction

    return signal
