from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from providers.openbb_provider import OpenBBProvider


TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_1M = 21
TRADING_DAYS_3M = 63

PERIOD_DAY_MAP = {
    "5d": 12,
    "1m": 45,
    "3m": 120,
    "6m": 220,
    "ytd": 400,
    "1y": 420,
    "3y": 1200,
    "5y": 2200,
    "10y": 4200,
    "all": None,
}


@dataclass
class SnapshotConfig:
    benchmark_symbol: str = "SPY"
    default_news_limit: int = 5
    history_lookback_days: int = 2200
    chart_lookback_days: int = 2200


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _pick_first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", "N/A", "None", "null"):
            return value
    return None


def _series_total_return(series: pd.Series) -> float | None:
    series = pd.to_numeric(series, errors='coerce').dropna()
    if len(series) < 2:
        return None
    start = _safe_float(series.iloc[0])
    end = _safe_float(series.iloc[-1])
    if start in (None, 0) or end is None:
        return None
    return (end / start) - 1.0


def _pct_return(series: pd.Series, periods: int) -> float | None:
    if len(series) <= periods:
        return None
    start = _safe_float(series.iloc[-periods - 1])
    end = _safe_float(series.iloc[-1])
    if start in (None, 0) or end is None:
        return None
    return (end / start) - 1.0


def _max_drawdown(close: pd.Series) -> float | None:
    if close.empty:
        return None
    running_max = close.cummax()
    drawdown = close / running_max - 1.0
    return _safe_float(drawdown.min())


def _annualized_volatility(daily_returns: pd.Series) -> float | None:
    daily_returns = daily_returns.dropna()
    if len(daily_returns) < 20:
        return None
    return _safe_float(daily_returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def _sharpe_ratio(daily_returns: pd.Series, rf_annual: float = 0.0) -> float | None:
    daily_returns = daily_returns.dropna()
    if len(daily_returns) < 20:
        return None

    rf_daily = rf_annual / TRADING_DAYS_PER_YEAR
    excess = daily_returns - rf_daily
    vol = excess.std(ddof=1)
    if vol in (None, 0) or pd.isna(vol):
        return None

    return _safe_float((excess.mean() / vol) * np.sqrt(TRADING_DAYS_PER_YEAR))


def _beta_to_benchmark(asset_close: pd.Series, benchmark_close: pd.Series) -> float | None:
    asset_ret = asset_close.pct_change().dropna()
    bench_ret = benchmark_close.pct_change().dropna()

    df = pd.concat(
        [asset_ret.rename("asset"), bench_ret.rename("bench")],
        axis=1,
        join="inner",
    ).dropna()

    if len(df) < 20:
        return None

    bench_var = df["bench"].var(ddof=1)
    if bench_var in (None, 0) or pd.isna(bench_var):
        return None

    cov = df["asset"].cov(df["bench"])
    return _safe_float(cov / bench_var)




def _windowed_risk_metrics(close: pd.Series, benchmark_close: pd.Series | None, years: int) -> dict[str, float | None]:
    if close is None or close.empty:
        return {"volatility": None, "max_drawdown": None, "sharpe": None, "beta": None}

    window_days = max(int(TRADING_DAYS_PER_YEAR * years), 63)
    window_close = close.dropna().tail(window_days + 1)
    if len(window_close) < 20:
        return {"volatility": None, "max_drawdown": None, "sharpe": None, "beta": None}

    daily_returns = window_close.pct_change().dropna()
    beta = None
    if benchmark_close is not None and not benchmark_close.empty:
        beta = _beta_to_benchmark(window_close, benchmark_close.dropna().tail(max(len(window_close) + 5, window_days + 5)))

    return {
        "volatility": _annualized_volatility(daily_returns),
        "max_drawdown": _max_drawdown(window_close),
        "sharpe": _sharpe_ratio(daily_returns),
        "beta": beta,
    }

def _normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce", utc=True).dt.tz_localize(None)
        out = out.sort_values("date").reset_index(drop=True)

    for col in ["open", "high", "low", "close", "volume"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    return out


def _normalize_news_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": str(item.get("date")) if item.get("date") is not None else None,
        "title": item.get("title"),
        "source": item.get("source"),
        "url": item.get("url"),
        "summary": item.get("summary") or item.get("text") or item.get("excerpt"),
    }


def _trend_state(last_price: float | None, ma50: float | None, ma200: float | None) -> str:
    if last_price is None or ma50 is None or ma200 is None:
        return "unknown"
    if last_price > ma50 > ma200:
        return "strong_uptrend"
    if last_price > ma200 and ma50 > ma200:
        return "uptrend"
    if last_price < ma50 < ma200:
        return "strong_downtrend"
    if last_price < ma200:
        return "downtrend"
    return "mixed"


def _build_summary(snapshot: dict[str, Any]) -> str:
    price = snapshot["price"]
    risk = snapshot["risk"]
    trend = snapshot["trend"]
    returns = snapshot["returns"]
    news = snapshot["news"]

    last_price = price.get("last_price")
    trend_state = trend.get("trend_state", "unknown")
    r1m = returns.get("return_1m")
    vol = risk.get("volatility_1y")
    beta = risk.get("beta_1y")

    parts = []

    if last_price is not None:
        parts.append(f"{snapshot['ticker']} is trading near ${last_price:,.2f}.")

    if trend_state != "unknown":
        parts.append(f"Trend currently reads as {trend_state.replace('_', ' ')}.")

    if r1m is not None:
        parts.append(f"Over the last month, the stock is {'up' if r1m >= 0 else 'down'} {abs(r1m):.1%}.")

    if vol is not None:
        parts.append(f"Annualized volatility is about {vol:.1%}.")

    if beta is not None:
        parts.append(f"Beta versus SPY is approximately {beta:.2f}.")

    if news:
        parts.append(f"There are {len(news)} recent company news items in the current snapshot.")

    return " ".join(parts)


def _to_serializable_float_list(series: pd.Series) -> list[float | None]:
    out: list[float | None] = []
    for v in series.tolist():
        if pd.isna(v):
            out.append(None)
        else:
            out.append(float(v))
    return out


class TickerSnapshotEngine:
    def __init__(
        self,
        provider: OpenBBProvider | None = None,
        config: SnapshotConfig | None = None,
    ) -> None:
        self.provider = provider or OpenBBProvider()
        self.config = config or SnapshotConfig()

    def build_snapshot(
        self,
        ticker: str,
        include_news: bool = True,
        news_limit: int | None = None,
    ) -> dict[str, Any]:
        ticker = str(ticker).upper().strip()
        news_limit = news_limit if include_news and news_limit is not None else self.config.default_news_limit if include_news else 0
        end_dt = date.today()
        lookback_days = max(int(self.config.history_lookback_days), 2200)
        start_dt = end_dt - timedelta(days=lookback_days)

        bundle = self.provider.get_basic_bundle(
            symbol=ticker,
            start_date=start_dt.isoformat(),
            end_date=end_dt.isoformat(),
            news_limit=news_limit,
        )

        hist = _normalize_history(bundle["history"])
        if hist.empty or "close" not in hist.columns:
            raise ValueError(f"No usable close history returned for ticker: {ticker}")

        if "date" in hist.columns:
            close_series = pd.to_numeric(hist.set_index("date")["close"], errors="coerce").dropna()
        else:
            close_series = pd.to_numeric(hist["close"], errors="coerce").dropna()
        close = close_series
        last_price = _safe_float(close.iloc[-1]) if not close.empty else None
        latest_row = hist.iloc[-1] if not hist.empty else None

        hist["ma_50"] = pd.to_numeric(hist["close"], errors="coerce").rolling(50).mean()
        hist["ma_200"] = pd.to_numeric(hist["close"], errors="coerce").rolling(200).mean()

        ma50 = _safe_float(hist["ma_50"].iloc[-1]) if not hist.empty else None
        ma200 = _safe_float(hist["ma_200"].iloc[-1]) if not hist.empty else None

        daily_returns = close_series.pct_change()

        benchmark_beta = None
        benchmark_close = None
        try:
            bench_hist = self.provider.get_history(
                symbol=self.config.benchmark_symbol,
                start_date=start_dt.isoformat(),
                end_date=end_dt.isoformat(),
            )
            bench_hist = _normalize_history(bench_hist)
            if "date" in bench_hist.columns and "close" in bench_hist.columns:
                benchmark_close = pd.to_numeric(bench_hist.set_index("date")["close"], errors="coerce").dropna()
                benchmark_beta = _beta_to_benchmark(close_series, benchmark_close)
        except Exception:
            benchmark_beta = None
            benchmark_close = None

        ytd_return = None
        if isinstance(close_series.index, pd.DatetimeIndex):
            current_year = pd.Timestamp(end_dt).year
            ytd_close = close_series[close_series.index.year == current_year]
            ytd_return = _series_total_return(ytd_close)

        news_items = bundle["news"] if include_news else []
        news_items = [_normalize_news_item(x) for x in news_items]

        quote = bundle["quote"]
        profile = bundle["profile"]

        latest_open = _safe_float(latest_row.get("open")) if latest_row is not None and "open" in hist.columns else None
        latest_high = _safe_float(latest_row.get("high")) if latest_row is not None and "high" in hist.columns else None
        latest_low = _safe_float(latest_row.get("low")) if latest_row is not None and "low" in hist.columns else None
        latest_volume = _safe_float(latest_row.get("volume")) if latest_row is not None and "volume" in hist.columns else None
        rolling_year = hist.tail(TRADING_DAYS_PER_YEAR) if len(hist) > TRADING_DAYS_PER_YEAR else hist
        year_high = _safe_float(rolling_year["close"].max()) if not close.empty else None
        year_low = _safe_float(rolling_year["close"].min()) if not close.empty else None

        risk_windows_raw = {
            "1y": _windowed_risk_metrics(close, benchmark_close, 1),
            "3y": _windowed_risk_metrics(close, benchmark_close, 3),
            "5y": _windowed_risk_metrics(close, benchmark_close, 5),
        }
        risk_windows = {
            key: {
                f"volatility_{key}": value.get("volatility"),
                f"max_drawdown_{key}": value.get("max_drawdown"),
                f"sharpe_{key}": value.get("sharpe"),
                f"beta_{key}": value.get("beta") if value.get("beta") is not None else (_safe_float(profile.get("beta")) if key == "1y" else None),
            }
            for key, value in risk_windows_raw.items()
        }

        snapshot = {
            "ticker": ticker,
            "name": profile.get("name") or quote.get("name"),
            "asset_type": quote.get("asset_type") or profile.get("issue_type"),
            "description": profile.get("long_description") or profile.get("short_description"),
            "short_description": profile.get("short_description"),
            "long_description": profile.get("long_description"),
            "as_of": str(end_dt),
            "price": {
                "last_price": last_price,
                "prev_close": _safe_float(quote.get("prev_close")) if _safe_float(quote.get("prev_close")) is not None else (_safe_float(close.iloc[-2]) if len(close) >= 2 else None),
                "open": _safe_float(quote.get("open")) if _safe_float(quote.get("open")) is not None else latest_open,
                "high": _safe_float(quote.get("high")) if _safe_float(quote.get("high")) is not None else latest_high,
                "low": _safe_float(quote.get("low")) if _safe_float(quote.get("low")) is not None else latest_low,
                "volume": _safe_float(quote.get("volume")) if _safe_float(quote.get("volume")) is not None else latest_volume,
                "currency": quote.get("currency") or profile.get("currency"),
                "year_high": _safe_float(quote.get("year_high")) if _safe_float(quote.get("year_high")) is not None else year_high,
                "year_low": _safe_float(quote.get("year_low")) if _safe_float(quote.get("year_low")) is not None else year_low,
            },
            "returns": {
                "return_1m": _pct_return(close_series, TRADING_DAYS_1M),
                "return_3m": _pct_return(close_series, TRADING_DAYS_3M),
                "return_1y": _pct_return(close_series, min(TRADING_DAYS_PER_YEAR, max(len(close_series) - 1, 0))),
                "return_3y": _pct_return(close_series, min(TRADING_DAYS_PER_YEAR * 3, max(len(close_series) - 1, 0))),
                "return_5y": _pct_return(close_series, min(TRADING_DAYS_PER_YEAR * 5, max(len(close_series) - 1, 0))),
                "return_all": _series_total_return(close_series),
                "return_ytd": ytd_return,
            },
            "risk": {
                "volatility_1y": risk_windows["1y"].get("volatility_1y"),
                "max_drawdown_1y": risk_windows["1y"].get("max_drawdown_1y"),
                "sharpe_1y": risk_windows["1y"].get("sharpe_1y"),
                "beta_1y": risk_windows["1y"].get("beta_1y") if risk_windows["1y"].get("beta_1y") is not None else (benchmark_beta if benchmark_beta is not None else _safe_float(profile.get("beta"))),
            },
            "risk_windows": risk_windows,
            "trend": {
                "ma_50": ma50,
                "ma_200": ma200,
                "price_vs_ma50_pct": ((last_price / ma50) - 1.0) if last_price and ma50 else None,
                "price_vs_ma200_pct": ((last_price / ma200) - 1.0) if last_price and ma200 else None,
                "trend_state": _trend_state(last_price, ma50, ma200),
            },
            "fundamentals": {
                "sector": _pick_first(profile, "sector", "category", "sector_name", "gics_sector"),
                "industry": _pick_first(profile, "industry_category", "industry", "industry_group", "gics_industry", "fund_family"),
                "market_cap": _safe_float(_pick_first(profile, "market_cap", "marketCap", "totalAssets")),
                "employees": _safe_float(_pick_first(profile, "employees", "fullTimeEmployees", "full_time_employees", "employee_count")),
                "dividend_yield": _safe_float(_pick_first(profile, "dividend_yield", "dividendYield", "yield")),
                "shares_outstanding": _safe_float(_pick_first(profile, "shares_outstanding", "sharesOutstanding", "share_class_shares_outstanding")),
            },
            "sentiment": {"status": "placeholder", "label": "not_integrated_yet", "score": None},
            "news": news_items,
            "forecast": {"supported": False, "models": {}, "commentary": None},
        }

        snapshot["summary"] = _build_summary(snapshot)
        return snapshot

    def build_chart_payload(
        self,
        ticker: str,
        period: str = "1y",
    ) -> dict[str, Any]:
        ticker = str(ticker).upper().strip()
        period = str(period).lower().strip()

        if period not in PERIOD_DAY_MAP:
            raise ValueError(f"Unsupported period: {period}")

        end_dt = date.today()
        lookback_days = PERIOD_DAY_MAP[period]

        warmup_days = 520
        if period == "ytd":
            start_dt = date(end_dt.year, 1, 1)
            history_start_dt = start_dt - timedelta(days=warmup_days)
        elif lookback_days is None:
            start_dt = None
            history_start_dt = None
        else:
            start_dt = end_dt - timedelta(days=lookback_days)
            history_start_dt = start_dt - timedelta(days=warmup_days)

        if period == "all":
            hist = self.provider.get_history(symbol=ticker, end_date=end_dt.isoformat(), period="max")
        else:
            hist = self.provider.get_history(
                symbol=ticker,
                start_date=history_start_dt.isoformat() if history_start_dt else None,
                end_date=end_dt.isoformat(),
            )

        hist = _normalize_history(hist)

        if hist.empty or "close" not in hist.columns or "date" not in hist.columns:
            raise ValueError(f"No usable chart history returned for ticker: {ticker}")

        hist["ma_20"] = hist["close"].rolling(20).mean()
        hist["ma_50"] = hist["close"].rolling(50).mean()
        hist["ma_200"] = hist["close"].rolling(200).mean()

        if start_dt is None:
            chart_df = hist.copy()
        else:
            chart_df = hist[hist["date"] >= pd.Timestamp(start_dt)].copy()

        if chart_df.empty:
            raise ValueError(f"No chart data available for ticker: {ticker}")

        resistance = _safe_float(chart_df["close"].max())
        support = _safe_float(chart_df["close"].min())

        volume = chart_df["volume"] if "volume" in chart_df.columns else pd.Series([None] * len(chart_df))

        return {
            "ticker": ticker,
            "period": period,
            "dates": chart_df["date"].dt.strftime("%Y-%m-%d").tolist(),
            "close": _to_serializable_float_list(chart_df["close"]),
            "ma20": _to_serializable_float_list(chart_df["ma_20"]),
            "ma50": _to_serializable_float_list(chart_df["ma_50"]),
            "ma200": _to_serializable_float_list(chart_df["ma_200"]),
            "volume": _to_serializable_float_list(volume),
            "resistance": resistance,
            "support": support,
            "last_price": _safe_float(chart_df["close"].iloc[-1]),
        }