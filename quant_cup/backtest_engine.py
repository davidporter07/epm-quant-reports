"""
Quant Model Cup — Backtesting Engine
Runs a single-factor strategy over a universe of stocks and returns performance metrics.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Callable, Literal

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass
class BacktestResult:
    model_name: str
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    trade_count: int
    avg_holding_days: float
    worst_year_return: float
    beats_buyhold: bool
    spy_cagr: float
    annual_returns: dict = field(default_factory=dict)
    equity_curve: pd.Series = field(default_factory=pd.Series)

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "total_return": round(self.total_return, 4),
            "cagr": round(self.cagr, 4),
            "sharpe": round(self.sharpe, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "win_rate": round(self.win_rate, 4),
            "trade_count": self.trade_count,
            "avg_holding_days": round(self.avg_holding_days, 1),
            "worst_year_return": round(self.worst_year_return, 4),
            "beats_buyhold": self.beats_buyhold,
            "spy_cagr": round(self.spy_cagr, 4),
            "annual_returns": {k: round(v, 4) for k, v in self.annual_returns.items()},
        }


def _compute_spy_cagr(prices: pd.DataFrame, start: str, end: str) -> float:
    if "SPY" not in prices.columns:
        return float("nan")
    spy = prices["SPY"].dropna()
    spy = spy.loc[start:end]
    if len(spy) < 2:
        return float("nan")
    n_years = (spy.index[-1] - spy.index[0]).days / 365.25
    return float((spy.iloc[-1] / spy.iloc[0]) ** (1 / n_years) - 1)


def _resample_signals(
    signals: pd.DataFrame,
    rebalance: Literal["daily", "weekly", "monthly"],
) -> pd.DataFrame:
    """Reduce signal updates to rebalance frequency, then forward-fill."""
    if rebalance == "daily":
        return signals
    freq = "W-FRI" if rebalance == "weekly" else "ME"
    rebalance_dates = signals.resample(freq).last()
    return rebalance_dates.reindex(signals.index, method="ffill")


def _portfolio_daily_returns(
    signals: pd.DataFrame,
    daily_returns: pd.DataFrame,
) -> pd.Series:
    """
    signals[t] → position held during day t+1 → return on t+1.
    Long side equally weighted to +1 gross exposure.
    Short side equally weighted to -1 gross exposure.
    Mixed long/short → market-neutral (net exposure ≈ 0).
    Long-only (no -1 signals) → long exposure.
    """
    # Positions effective on day t+1 — shift signals forward by 1
    pos = signals.shift(1)

    long_mask = pos == 1
    short_mask = pos == -1

    long_counts = long_mask.sum(axis=1).replace(0, np.nan)
    short_counts = short_mask.sum(axis=1).replace(0, np.nan)

    long_weights = long_mask.div(long_counts, axis=0).fillna(0)
    short_weights = short_mask.div(short_counts, axis=0).fillna(0)

    net_weights = long_weights - short_weights

    # NaN returns don't contribute (stock suspended / missing data)
    port_returns = (net_weights * daily_returns).sum(axis=1)
    return port_returns


def _cagr(equity_curve: pd.Series) -> float:
    if len(equity_curve) < 2:
        return 0.0
    n_years = (equity_curve.index[-1] - equity_curve.index[0]).days / 365.25
    if n_years <= 0:
        return 0.0
    return float((equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1 / n_years) - 1)


def _sharpe(daily_returns: pd.Series) -> float:
    clean = daily_returns.dropna()
    if len(clean) < 2 or clean.std() == 0:
        return 0.0
    return float(clean.mean() / clean.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def _max_drawdown(equity_curve: pd.Series) -> float:
    roll_max = equity_curve.cummax()
    drawdown = equity_curve / roll_max - 1
    return float(drawdown.min())


def _win_rate_and_trade_count(
    signals: pd.DataFrame, daily_returns: pd.DataFrame
) -> tuple[float, int, float]:
    """
    A 'trade' is a position held for a contiguous run of +1 or -1 for a single ticker.
    Win = trade's cumulative return > 0.
    """
    wins = 0
    total = 0
    holding_days: list[int] = []

    pos = signals.shift(1)

    for ticker in pos.columns:
        s = pos[ticker].fillna(0)
        r = daily_returns[ticker]

        # Find runs (entry/exit points)
        transitions = s.diff().fillna(s.iloc[0] if len(s) else 0)
        entries = s.index[(transitions != 0) & (s != 0)]
        exits = s.index[(transitions != 0) & (s == 0)]

        # Pair entries and exits
        for entry in entries:
            # Find next exit after this entry
            future_exits = exits[exits > entry]
            if len(future_exits) == 0:
                exit_date = s.index[-1]
            else:
                exit_date = future_exits[0]

            direction = s.loc[entry]
            trade_returns = r.loc[entry:exit_date].dropna()
            if len(trade_returns) == 0:
                continue

            cum_return = float(((1 + trade_returns).prod() - 1) * direction)
            holding_days.append(len(trade_returns))
            total += 1
            if cum_return > 0:
                wins += 1

    win_rate = wins / total if total > 0 else 0.0
    avg_hold = float(np.mean(holding_days)) if holding_days else 0.0
    return win_rate, total, avg_hold


def _annual_returns(daily_returns: pd.Series) -> dict:
    yearly = daily_returns.resample("YE").apply(lambda r: float((1 + r).prod() - 1))
    return {str(dt.year): v for dt, v in yearly.items()}


def run_backtest(
    model_fn: Callable[[pd.DataFrame], pd.DataFrame],
    prices: pd.DataFrame,
    model_name: str = "unnamed",
    start: str = "2006-01-01",
    end: str = "2025-12-31",
    rebalance: Literal["daily", "weekly", "monthly"] = "monthly",
    prices_extra: dict | None = None,
) -> BacktestResult:
    """
    model_fn: receives close prices (and optionally extra OHLCV via prices_extra keyword
              argument if the function signature accepts **kwargs).
    prices:   daily close prices, index=DatetimeIndex, columns=tickers (must include SPY).
    prices_extra: optional dict of {"open": df, "high": df, "low": df, "volume": df}.
    """
    prices = prices.loc[start:end]

    # Drop tickers with fewer than 1 year of valid data — prevents bad delisted-ticker data
    min_valid = 252
    valid_cols = prices.notna().sum() >= min_valid
    # Always keep SPY for benchmark
    if "SPY" in prices.columns:
        valid_cols["SPY"] = True
    prices = prices.loc[:, valid_cols]

    spy_cagr = _compute_spy_cagr(prices, start, end)

    daily_returns = prices.pct_change(fill_method=None)
    # Clip extreme single-day returns — prevents overflow and runaway short losses from bad delisted-ticker data
    daily_returns = daily_returns.clip(-0.5, 0.5)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import inspect

        sig = inspect.signature(model_fn)
        if "prices_extra" in sig.parameters and prices_extra:
            raw_signals = model_fn(prices, prices_extra=prices_extra)
        else:
            raw_signals = model_fn(prices)

    raw_signals = raw_signals.reindex_like(prices).fillna(0)
    signals = _resample_signals(raw_signals, rebalance)

    port_returns = _portfolio_daily_returns(signals, daily_returns)
    equity_curve = (1 + port_returns).cumprod()

    total_return = float(equity_curve.iloc[-1] - 1) if len(equity_curve) else 0.0
    cagr = _cagr(equity_curve)
    sharpe = _sharpe(port_returns)
    mdd = _max_drawdown(equity_curve)
    ann_rets = _annual_returns(port_returns)
    worst_year = min(ann_rets.values()) if ann_rets else 0.0

    win_rate, trade_count, avg_hold = _win_rate_and_trade_count(signals, daily_returns)

    return BacktestResult(
        model_name=model_name,
        total_return=total_return,
        cagr=cagr,
        sharpe=sharpe,
        max_drawdown=mdd,
        win_rate=win_rate,
        trade_count=trade_count,
        avg_holding_days=avg_hold,
        worst_year_return=worst_year,
        beats_buyhold=cagr > spy_cagr,
        spy_cagr=spy_cagr,
        annual_returns=ann_rets,
        equity_curve=equity_curve,
    )
