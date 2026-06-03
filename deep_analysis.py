"""
deep_analysis.py — Seed document generator for the EPM Investment Intelligence Council.

Seed doc is structured as labeled analytical perspective sections so each council
analyst receives focused context (Technical Analysis, Federal Reserve, Supply Chain
Risk, etc.) rather than a generic data dump.

Each section header frames the analytical domain for the persona that reads it.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf

import research_service
from earnings_refresh import load_recent_earnings_release, ticker_variants
from news_store import load_news_store
from universe_config import get_portfolio_tickers

KRONOS_URL = "http://127.0.0.1:8100"
DATA_DIR = Path("data")

# Hard ceiling (seconds) on the background web-research enrichment per deep-analysis
# build. Topics run concurrently inside enrich(), so this is the outer join timeout.
RESEARCH_TIMEOUT = int(os.getenv("RESEARCH_TIMEOUT_SEC", os.getenv("PM_RESEARCH_TIMEOUT_SEC", "210")))

_EPM_MODEL_FILES: Dict[str, Tuple[str, str]] = {
    "Linear Regression":  ("linear_forecasts.csv",       "Linear Model Forecast (%)"),
    "Fama-French":        ("fama_french_forecasts.csv",  "FF Forecast (%)"),
    "Machine Learning":   ("ml_forecasts.csv",            "ML Forecast (%)"),
    "ARIMAX":             ("arimax_forecasts.csv",         "ARIMAX Forecast (%)"),
    "Deep Learning":      ("dl_forecasts.csv",            "DL Forecast (%)"),
    "Institutional Flow": ("institutional_forecasts.csv", "Institutional Forecast (%)"),
}


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _get_ohlcv(ticker: str, days: int = 252) -> List[dict]:
    import logging
    logger = logging.getLogger(__name__)

    def _df_to_candles(df) -> List[dict]:
        candles = []
        for date, row in df.iterrows():
            def _f(col: str) -> float:
                v = row[col]
                return float(v.iloc[0]) if hasattr(v, "iloc") else float(v)
            candles.append({
                "date":   date.strftime("%Y-%m-%d"),
                "open":   round(_f("Open"),   2),
                "high":   round(_f("High"),   2),
                "low":    round(_f("Low"),    2),
                "close":  round(_f("Close"),  2),
                "volume": _f("Volume"),
            })
        return candles

    df = yf.download(ticker, period=f"{days}d", interval="1d", progress=False, auto_adjust=True)
    if df.empty:
        return []
    candles = _df_to_candles(df)

    # Sanity-check: compare last close against fast_info spot price.
    # If they diverge by >15%, yf.download() returned stale/bad data
    # (common when Yahoo Finance auth cookies are stale). Re-fetch via
    # Ticker.history() which uses a separate code path.
    if candles:
        try:
            spot = yf.Ticker(ticker).fast_info.get("lastPrice") or yf.Ticker(ticker).fast_info.get("last_price")
            if spot and spot > 0:
                last_close = candles[-1]["close"]
                ratio = abs(last_close / spot - 1)
                if ratio > 0.15:
                    logger.warning(
                        "OHLCV price sanity check failed for %s: last_close=%.2f vs fast_info=%.2f (%.0f%% gap). "
                        "Falling back to Ticker.history()", ticker, last_close, spot, ratio * 100
                    )
                    hist = yf.Ticker(ticker).history(period=f"{days}d", interval="1d", auto_adjust=True)
                    if not hist.empty:
                        candles = _df_to_candles(hist)
        except Exception as exc:
            logger.debug("OHLCV sanity check skipped (%s)", exc)

    return candles


def _get_kronos_scenarios(ticker: str, ohlcv: List[dict], pred_len: int = 5) -> List[List[dict]]:
    """
    Fetch Kronos OHLCV scenarios. Returns a list of forecast scenarios (each is a list of daily dicts).
    Handles both single-forecast and multi-sample response formats.
    Returns [] gracefully if Kronos is unavailable so the pipeline can continue without it.
    """
    import logging
    try:
        r = requests.post(
            f"{KRONOS_URL}/forecast",
            json={"ticker": ticker, "ohlcv": ohlcv, "pred_len": pred_len, "sample_count": 3},
            timeout=30,
        )
        r.raise_for_status()
    except Exception as exc:
        logging.getLogger(__name__).warning("Kronos unavailable for %s: %s", ticker, exc)
        return []
    data = r.json()

    # Multi-sample: {"forecasts": [[{day}, ...], [{day}, ...], ...]}
    if "forecasts" in data and isinstance(data["forecasts"], list):
        scenarios = [s for s in data["forecasts"] if isinstance(s, list) and s]
        if scenarios:
            return scenarios

    # Nested single: {"forecast": [[{day}, ...], ...]}
    if "forecast" in data:
        fc = data["forecast"]
        if isinstance(fc, list) and fc:
            if isinstance(fc[0], list):
                return [s for s in fc if s]
            if isinstance(fc[0], dict):
                return [fc]  # single scenario

    return []


def _get_epm_forecasts(ticker: str) -> Optional[Dict[str, float]]:
    """Raw model percentage outputs — no directional labels."""
    universe = [t.upper() for t in get_portfolio_tickers()]
    if ticker.upper() not in universe:
        return None

    forecasts: Dict[str, float] = {}
    for model_name, (filename, col) in _EPM_MODEL_FILES.items():
        path = DATA_DIR / filename
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df["Ticker"] = df["Ticker"].astype(str).str.upper()
        row = df[df["Ticker"] == ticker.upper()]
        if row.empty or col not in row.columns:
            continue
        val = pd.to_numeric(row.iloc[-1][col], errors="coerce")
        if pd.notna(val):
            forecasts[model_name] = round(float(val), 2)

    return forecasts if forecasts else None


def _get_news_headlines(ticker: str, max_headlines: int = 10) -> List[str]:
    store = load_news_store()
    variants = set(ticker_variants(ticker))
    ticker_news = store[store["Ticker"].astype(str).str.upper().isin(variants)].copy()

    if not ticker_news.empty:
        ticker_news = ticker_news.sort_values("PublishedAt", ascending=False)
        return [h for h in ticker_news["Headline"].head(max_headlines).tolist() if h]

    try:
        raw = yf.Ticker(ticker).news or []
        return [n.get("content", {}).get("title", "") or n.get("title", "")
                for n in raw[:max_headlines]
                if (n.get("content", {}).get("title") or n.get("title"))]
    except Exception:
        return []


def _compute_technicals(ohlcv: List[dict]) -> Dict:
    """RSI(14), momentum, volume trend, 52-week range, MAs."""
    closes  = [c["close"]  for c in ohlcv]
    volumes = [c["volume"] for c in ohlcv]
    current = closes[-1]

    rsi = None
    if len(closes) >= 15:
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains  = [max(d, 0) for d in deltas]
        losses = [abs(min(d, 0)) for d in deltas]
        avg_gain = float(np.mean(gains[-14:]))
        avg_loss = float(np.mean(losses[-14:]))
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = round(100 - (100 / (1 + rs)), 1)
        else:
            rsi = 100.0

    mom5  = round((current / closes[-6]  - 1) * 100, 2) if len(closes) >= 6  else None
    mom20 = round((current / closes[-21] - 1) * 100, 2) if len(closes) >= 21 else None

    vol_ratio = None
    if len(volumes) >= 20:
        avg20 = float(np.mean(volumes[-20:]))
        avg5  = float(np.mean(volumes[-5:]))
        if avg20 > 0:
            vol_ratio = round(avg5 / avg20, 2)

    high52 = round(max(c["high"] for c in ohlcv), 2)
    low52  = round(min(c["low"]  for c in ohlcv), 2)
    pct_from_high = round((current / high52 - 1) * 100, 1) if high52 else None
    pct_from_low  = round((current / low52  - 1) * 100, 1) if low52  else None
    ma50  = round(float(np.mean(closes[-50:])),  2) if len(closes) >= 50  else None
    ma200 = round(float(np.mean(closes[-200:])), 2) if len(closes) >= 200 else None

    return {
        "current": round(current, 2),
        "rsi": rsi, "mom5": mom5, "mom20": mom20, "vol_ratio": vol_ratio,
        "high52": high52, "low52": low52,
        "pct_from_high": pct_from_high, "pct_from_low": pct_from_low,
        "ma50": ma50, "ma200": ma200,
    }


def _get_company_info(ticker: str) -> Dict:
    try:
        info = yf.Ticker(ticker).info
        return {
            "name":     info.get("longName") or info.get("shortName") or ticker,
            "sector":   info.get("sector"),
            "industry": info.get("industry"),
            "country":  info.get("country"),
        }
    except Exception:
        return {"name": ticker, "sector": None, "industry": None, "country": None}


def _get_fundamentals(ticker: str) -> Dict:
    """Pull key fundamental metrics from yf.Ticker().info.

    Retries once after a short pause — Yahoo Finance periodically returns
    401 Invalid Crumb on the first call when the session hasn't been warmed.
    """
    import time as _time

    def _pct(v):
        return round(float(v) * 100, 2) if v is not None else None

    def _f(v, dp=2):
        return round(float(v), dp) if v is not None else None

    for attempt in range(2):
        try:
            info = yf.Ticker(ticker).info
            return {
                "pe_ratio":        _f(info.get("trailingPE")),
                "forward_pe":      _f(info.get("forwardPE")),
                "peg_ratio":       _f(info.get("pegRatio")),
                "eps_ttm":         _f(info.get("trailingEps")),
                "revenue_growth":  _pct(info.get("revenueGrowth")),
                "earnings_growth": _pct(info.get("earningsGrowth")),
                "profit_margin":   _pct(info.get("profitMargins")),
                "operating_margin":_pct(info.get("operatingMargins")),
                "roe":             _pct(info.get("returnOnEquity")),
                "debt_to_equity":  _f(info.get("debtToEquity")),
                "market_cap":      info.get("marketCap"),
                "enterprise_value":info.get("enterpriseValue"),
                "ev_to_ebitda":    _f(info.get("enterpriseToEbitda")),
                "price_to_book":   _f(info.get("priceToBook")),
                "dividend_yield":  _pct(info.get("trailingAnnualDividendYield")),
                "analyst_target":  _f(info.get("targetMeanPrice")),
                "analyst_count":   info.get("numberOfAnalystOpinions"),
                "recommendation":  _f(info.get("recommendationMean")),
            }
        except Exception:
            if attempt == 0:
                _time.sleep(4)
    return {}


_FUND_ISSUE_TYPES = {"ETF", "MUTUALFUND", "FUND", "INDEX", "MONEYMARKET", "CLOSEDENDFUND", "CEF"}


def _get_fund_profile(ticker: str) -> Dict:
    """Fetch fund composition + mandate via OpenBBProvider.get_profile().

    Returns {} for ordinary equities. For funds/ETFs returns an is_fund flag,
    top holdings (name + weight), top-10 concentration, stated objective,
    category/family, expense ratio, and sector tilt — the ground truth the
    FUND STRUCTURE ANALYST persona reasons over.
    """
    try:
        from providers.openbb_provider import OpenBBProvider
        profile = OpenBBProvider().get_profile(ticker)
    except Exception:
        return {}
    if not isinstance(profile, dict):
        return {}

    holdings = profile.get("top_holdings") or []
    issue_type = str(profile.get("issue_type") or "").upper().replace(" ", "")
    name = str(profile.get("name") or "").lower()
    is_fund = (
        issue_type in _FUND_ISSUE_TYPES
        or bool(holdings)
        or "etf" in name or " fund" in name or "trust" in name
    )
    if not is_fund:
        return {}

    clean_holdings: List[dict] = []
    for h in holdings:
        if not isinstance(h, dict):
            continue
        w = h.get("weight")
        clean_holdings.append({
            "symbol":     h.get("symbol"),
            "name":       h.get("name"),
            "weight_pct": round(float(w) * 100, 2) if w is not None else None,
        })
    top10 = clean_holdings[:10]
    concentration = (
        round(sum(h["weight_pct"] for h in top10 if h["weight_pct"] is not None), 2)
        if top10 else None
    )

    expense = profile.get("expense_ratio")
    expense_pct = round(float(expense) * 100, 4) if expense is not None else None

    sector_w = profile.get("sector_weightings") or {}
    sector_tilt: List[tuple] = []
    if isinstance(sector_w, dict):
        sector_tilt = sorted(
            ((str(k).replace("_", " ").title(), round(float(v) * 100, 1))
             for k, v in sector_w.items() if v is not None),
            key=lambda kv: kv[1], reverse=True,
        )[:5]

    objective = (
        profile.get("fund_overview")
        or profile.get("long_description")
        or profile.get("short_description")
        or ""
    )
    objective = str(objective).strip()

    return {
        "is_fund":                 True,
        "name":                    profile.get("name") or ticker,
        "issue_type":              issue_type or "FUND",
        "category":                profile.get("category"),
        "fund_family":             profile.get("fund_family"),
        "expense_ratio_pct":       expense_pct,
        "top_holdings":            top10,
        "top10_concentration_pct": concentration,
        "sector_tilt":             sector_tilt,
        "objective":               objective[:600],
    }


SECTOR_ETFS = {
    "technology": "XLK", "financials": "XLF", "healthcare": "XLV",
    "consumer discretionary": "XLY", "consumer staples": "XLP",
    "energy": "XLE", "utilities": "XLU", "materials": "XLB",
    "industrials": "XLI", "real estate": "XLRE",
    "communication services": "XLC",
}


def _get_relative_performance(ticker: str, sector: str) -> Dict:
    """Stock return vs sector ETF over 1m / 3m / 6m (Jegadeesh & Titman momentum)."""
    try:
        etf = SECTOR_ETFS.get((sector or "").lower())
        tickers_to_fetch = [ticker] + ([etf] if etf else [])
        df = yf.download(tickers_to_fetch, period="180d", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return {}

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"]
        else:
            close = df[["Close"]]

        def _ret(col, days):
            s = close[col].dropna()
            if len(s) < days + 1:
                return None
            return round((float(s.iloc[-1]) / float(s.iloc[-days-1]) - 1) * 100, 2)

        result: Dict = {"etf": etf}
        for period_label, days in [("1m", 21), ("3m", 63), ("6m", 126)]:
            stock_ret = _ret(ticker, days)
            etf_ret   = _ret(etf, days) if etf and etf in close.columns else None
            result[period_label] = {
                "stock": stock_ret,
                "etf":   etf_ret,
                "rel":   round(stock_ret - etf_ret, 2) if stock_ret is not None and etf_ret is not None else None,
            }

        rel_6m = result.get("6m", {}).get("rel")
        if rel_6m is not None:
            if rel_6m > 5:
                result["label"] = "SECTOR LEADER"
            elif rel_6m < -5:
                result["label"] = "SECTOR LAGGARD"
            else:
                result["label"] = "INLINE WITH SECTOR"
        return result
    except Exception:
        return {}


def _get_volatility_regime(ohlcv: List[dict]) -> Dict:
    """ATR-based volatility regime: where is current vol vs trailing 252-day distribution?"""
    closes = [c["close"] for c in ohlcv]
    highs  = [c["high"]  for c in ohlcv]
    lows   = [c["low"]   for c in ohlcv]

    tr_series = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i]  - closes[i-1]))
        tr_series.append(tr)

    atr_14 = float(np.mean(tr_series[-14:])) if len(tr_series) >= 14 else None

    if len(tr_series) >= 28:
        window_atrs = [float(np.mean(tr_series[i:i+14])) for i in range(len(tr_series) - 13)]
        pct = round(sum(1 for x in window_atrs if x < atr_14) / len(window_atrs) * 100, 1)
    else:
        pct = None

    if len(closes) >= 21:
        daily_returns = [np.log(closes[i]/closes[i-1]) for i in range(1, len(closes))]
        hv_20 = round(float(np.std(daily_returns[-20:])) * np.sqrt(252) * 100, 1)
    else:
        hv_20 = None

    if pct is not None:
        if pct <= 20:
            regime = "COMPRESSION — vol in bottom 20th pct; breakout risk elevated"
        elif pct <= 35:
            regime = "LOW — below-average vol; watch for compression-to-expansion transition"
        elif pct <= 65:
            regime = "NORMAL — vol in typical historical range"
        elif pct <= 80:
            regime = "ELEVATED — vol in top third; trend follow-through less reliable"
        else:
            regime = "EXTREME — vol in top 20th pct; mean-reversion more likely than continuation"
    else:
        regime = "N/A"

    return {"atr_14": round(atr_14, 2) if atr_14 else None, "atr_pct": pct, "hv_20": hv_20, "regime": regime}


def _get_overnight_stats(ohlcv: List[dict], lookback: int = 20) -> Dict:
    """Splits recent returns into overnight (close→open) vs intraday (open→close) components."""
    if len(ohlcv) < lookback + 1:
        return {}
    recent = ohlcv[-(lookback + 1):]
    overnight, intraday = [], []
    for i in range(1, len(recent)):
        prev_close = recent[i-1]["close"]
        today_open = recent[i]["open"]
        today_close = recent[i]["close"]
        overnight.append((today_open / prev_close - 1) * 100)
        intraday.append((today_close / today_open - 1) * 100)
    return {
        "overnight_avg":      round(float(np.mean(overnight)), 3),
        "intraday_avg":       round(float(np.mean(intraday)), 3),
        "overnight_pos_pct":  round(sum(1 for x in overnight if x > 0) / len(overnight) * 100, 1),
        "intraday_pos_pct":   round(sum(1 for x in intraday  if x > 0) / len(intraday)  * 100, 1),
    }


def _get_earnings_surprise_history(ticker: str, quarters: int = 8) -> List[dict]:
    """Returns recent quarterly EPS surprise history for PEAD signal."""
    try:
        t = yf.Ticker(ticker)
        hist = t.earnings_history
        if hist is None or (hasattr(hist, "empty") and hist.empty):
            return []
        records = []
        for _, row in hist.tail(quarters).iterrows():
            est = row.get("epsEstimate")
            act = row.get("epsActual")
            surprise = row.get("surprisePct")
            if est is not None and act is not None:
                records.append({
                    "date": str(row.name.date()) if hasattr(row.name, "date") else str(row.name),
                    "estimated": round(float(est), 2),
                    "actual":    round(float(act), 2),
                    "surprise_pct": round(float(surprise) * 100, 1) if surprise is not None else None,
                    "beat": float(act) >= float(est),
                })
        return records
    except Exception:
        return []


def _get_vix() -> Optional[float]:
    """Fetch current VIX level."""
    try:
        # Use Ticker.history() — avoids the MultiIndex column issues that yf.download causes
        # for indices when auto_adjust=True, which produces inflated values.
        hist = yf.Ticker("^VIX").history(period="5d", interval="1d")
        if not hist.empty:
            v = hist["Close"].iloc[-1]
            val = float(v.iloc[0]) if hasattr(v, "iloc") else float(v)
            # Sanity-check: VIX is always between 5 and 150
            if 5 <= val <= 150:
                return round(val, 1)
    except Exception:
        pass
    return None


def _get_spy_trend() -> Dict:
    """Fetch SPY recent returns for macro context."""
    result: Dict = {}
    try:
        df = yf.download("SPY", period="30d", interval="1d", progress=False, auto_adjust=True)
        if not df.empty:
            closes = [float(v.iloc[0]) if hasattr(v, "iloc") else float(v) for v in df["Close"]]
            current = closes[-1]
            if len(closes) >= 6:
                result["spy_5d"] = round((current / closes[-6] - 1) * 100, 2)
            if len(closes) >= 21:
                result["spy_20d"] = round((current / closes[-21] - 1) * 100, 2)
    except Exception:
        pass
    return result


def _get_earnings_info(ticker: str) -> Optional[Dict]:
    """Next earnings date + release time (BMO/AMC/None) from yfinance calendar."""
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None:
            return None
        today = datetime.now().date()

        def _release_time_from_ts(raw) -> Optional[str]:
            try:
                ts = pd.to_datetime(raw)
                h = ts.hour
                if h == 0:
                    return None
                if h < 12:
                    return "BMO"
                if h >= 16:
                    return "AMC"
                return "intraday"
            except Exception:
                return None

        # calendar is a DataFrame (columns = dates, rows = metrics)
        if hasattr(cal, "columns"):
            for col in cal.columns:
                try:
                    d = pd.to_datetime(col).date()
                    if d >= today:
                        days_until = (d - today).days
                        return {"date": str(d), "days_until": days_until,
                                "release_time": _release_time_from_ts(col)}
                except Exception:
                    continue

        # calendar is a dict
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date", [])
            if not isinstance(dates, (list, tuple)):
                dates = [dates]
            for raw in dates:
                try:
                    d = pd.to_datetime(raw).date()
                    if d >= today:
                        days_until = (d - today).days
                        return {"date": str(d), "days_until": days_until,
                                "release_time": _release_time_from_ts(raw)}
                except Exception:
                    continue
    except Exception:
        pass
    return None


def check_earnings_released(ticker: str, earnings_date_str: str) -> bool:
    """Return True if actual EPS data is available for the given earnings date.

    Checks yfinance earnings_dates DataFrame — if Reported EPS is non-null for
    the expected date, the report has dropped. Called only on the earnings date
    itself after the announced release window, so network cost is rare.
    """
    try:
        t = yf.Ticker(ticker)
        df = t.earnings_dates
        if df is None or (hasattr(df, "empty") and df.empty):
            return False
        target = pd.to_datetime(earnings_date_str).date()
        for idx in df.index:
            try:
                d = pd.to_datetime(idx).date()
                if d == target:
                    reported = df.loc[idx, "Reported EPS"] if "Reported EPS" in df.columns else None
                    if reported is not None and not (isinstance(reported, float) and pd.isna(reported)):
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _vix_label(vix: float) -> str:
    if vix < 15:
        return "low — market complacent"
    if vix < 20:
        return "normal range"
    if vix < 25:
        return "elevated — market uncertainty"
    if vix < 30:
        return "high — significant fear"
    return "extreme — crisis-level fear"


def _scenario_label(implied_move: float, scenarios: List[List[dict]], idx: int) -> str:
    """Label a Kronos scenario based on its position among all scenarios."""
    if len(scenarios) == 1:
        return "Base Scenario"
    moves = sorted([(s[-1]["close"], i) for i, s in enumerate(scenarios)])
    rank = next(r for r, (_, i) in enumerate(moves) if i == idx)
    labels = {0: "Bearish Case", len(scenarios) - 1: "Bullish Case"}
    return labels.get(rank, "Base Case")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_seed_doc(ticker: str, pred_len: int = 5) -> Tuple[str, Dict[str, Any]]:
    """
    Build an EPM Investment Intelligence Council seed document structured as analytical perspective sections.

    Section headers frame the analytical domain for each council persona, ensuring
    each analyst reasons from targeted data relevant to their specialty.

    Returns (seed_text, key_facts). key_facts is a flat dict of authoritative
    numbers for the downstream LLM post-processor to use as ground truth, so it
    does not hallucinate P/E, ROE, dividend yield, or price targets.
    """
    ticker = ticker.upper()
    today  = datetime.now().strftime("%Y-%m-%d")

    # Profile + fund detection first, then kick off web research (funds AND
    # stocks) in a background thread so the slow search+LLM enrichment overlaps
    # the price/forecast data collection below. Falls back to {} when SearxNG
    # is down or the topics yield nothing.
    co_info      = _get_company_info(ticker)
    fund         = _get_fund_profile(ticker)
    is_fund      = bool(fund)
    research_future, research_executor = None, None
    try:
        from concurrent.futures import ThreadPoolExecutor
        research_executor = ThreadPoolExecutor(max_workers=1)
        research_future = research_executor.submit(
            research_service.enrich, ticker,
            name=(co_info.get("name") or ticker),
            asset_kind=("fund" if is_fund else "stock"),
            fund_profile=(fund or None),
        )
    except Exception:
        research_future = None

    ohlcv    = _get_ohlcv(ticker, days=252)
    if not ohlcv:
        raise ValueError(f"No OHLCV data available for {ticker}")

    kronos_input = ohlcv[-60:]
    scenarios    = _get_kronos_scenarios(ticker, kronos_input, pred_len=pred_len)
    tech         = _compute_technicals(ohlcv)
    epm          = _get_epm_forecasts(ticker)
    headlines    = _get_news_headlines(ticker)
    vix          = _get_vix()
    spy          = _get_spy_trend()
    earnings     = _get_earnings_info(ticker)
    fundamentals = _get_fundamentals(ticker)
    vol_regime   = _get_volatility_regime(ohlcv)
    rel_perf     = _get_relative_performance(ticker, co_info.get("sector") or "")
    overnight    = _get_overnight_stats(ohlcv)
    eps_history  = _get_earnings_surprise_history(ticker)
    earnings_release = load_recent_earnings_release(ticker)

    current = tech["current"]
    sector  = (co_info.get("sector") or "").lower()

    lines: List[str] = [
        f"{ticker} — {co_info['name']}",
        f"Sector: {co_info['sector'] or 'N/A'} | Industry: {co_info['industry'] or 'N/A'}",
        f"Market Intelligence Brief: {today}",
        "",
    ]

    # ── SIMULATION PARTICIPANTS ───────────────────────────────────────────────
    # Placed before content sections so council personas recognize these as the primary discussion subjects
    lines.append("── SIMULATION PARTICIPANTS ──────────────────────────────────────────────────")
    lines.append(f"Seven specialist analysts provide perspectives on this {'fund' if is_fund else 'stock'}:")
    lines.append(f"- TECHNICAL ANALYST: interprets price action, RSI, volatility regime, relative performance, and overnight flow data for {ticker}")
    lines.append(f"- GROWTH INVESTOR: evaluates revenue growth, earnings growth, margins, ROE, forward P/E, and PEG ratio for {ticker}")
    lines.append(f"- VALUE INVESTOR: assesses trailing P/E, EV/EBITDA, price-to-book, debt/equity, dividend yield, and market cap for {ticker}")
    lines.append(f"- MACRO STRATEGIST: frames {ticker} within the VIX regime, SPY trend, and Federal Reserve interest rate environment")
    lines.append(f"- SUPPLY CHAIN RISK ANALYST: identifies geopolitical exposure, manufacturing concentration, and tariff risk for {ticker}")
    lines.append(f"- BEARISH ANALYST: argues the downside case, challenges consensus, and identifies risks quantitative models miss for {ticker}")
    if is_fund:
        lines.append(f"- FUND STRUCTURE ANALYST: reasons over top-holding concentration, sector tilt, stated mandate/objective, and expense drag for {ticker}")
    else:
        lines.append(f"- EARNINGS CATALYST ANALYST: tracks the next earnings date, EPS surprise history, beat rate, and PEAD drift signal for {ticker}")
    lines.append("")

    # ── FUND COMPOSITION & MANDATE ──────────────────────────────────────────────
    # Rendered only for funds/ETFs; this is the FUND STRUCTURE ANALYST's primary data.
    if is_fund:
        lines.append("── FUND COMPOSITION & MANDATE ──────────────────────────────────────────────────")
        meta_parts = []
        if fund.get("issue_type"):
            meta_parts.append(f"Type: {fund['issue_type']}")
        if fund.get("category"):
            meta_parts.append(f"Category: {fund['category']}")
        if fund.get("fund_family"):
            meta_parts.append(f"Family: {fund['fund_family']}")
        if fund.get("expense_ratio_pct") is not None:
            meta_parts.append(f"Expense ratio: {fund['expense_ratio_pct']:.2f}%")
        if meta_parts:
            lines.append(" | ".join(meta_parts))
        if fund.get("objective"):
            lines.append(f"Stated mandate: {fund['objective']}")
        if fund.get("top_holdings"):
            conc = fund.get("top10_concentration_pct")
            conc_str = f" (top-10 concentration: {conc:.1f}% of assets)" if conc is not None else ""
            lines.append(f"Top Holdings{conc_str}:")
            lines.append("| # | Holding | Symbol | Weight |")
            lines.append("|---|---------|--------|--------|")
            for i, h in enumerate(fund["top_holdings"], 1):
                w = f"{h['weight_pct']:.2f}%" if h.get("weight_pct") is not None else "N/A"
                lines.append(f"| {i} | {h.get('name') or 'N/A'} | {h.get('symbol') or 'N/A'} | {w} |")
        if fund.get("sector_tilt"):
            tilt = " | ".join(f"{nm} {pct:.1f}%" for nm, pct in fund["sector_tilt"])
            lines.append(f"Sector Tilt (top): {tilt}")
        conc = fund.get("top10_concentration_pct")
        if conc is not None:
            if conc >= 50:
                lines.append("Note: High top-10 concentration — performance is driven by a small number of names; single-name/idiosyncratic risk is elevated relative to a broad index.")
            elif conc <= 25:
                lines.append("Note: Low top-10 concentration — broadly diversified; returns track the mandate/sector rather than single-name catalysts.")
        lines.append("")

    # ── TECHNICAL ANALYSIS PERSPECTIVE ───────────────────────────────────────
    lines.append("── TECHNICAL ANALYSIS PERSPECTIVE ──────────────────────────────────────────")
    price_line = f"Current Price: ${current:.2f}"
    if tech["ma50"]:
        gap = (current / tech["ma50"] - 1) * 100
        price_line += f" | MA50: ${tech['ma50']:.2f} ({gap:+.1f}%)"
    if tech["ma200"]:
        gap = (current / tech["ma200"] - 1) * 100
        price_line += f" | MA200: ${tech['ma200']:.2f} ({gap:+.1f}%)"
    lines.append(price_line)

    if tech["high52"] and tech["low52"]:
        lines.append(
            f"52-Week Range: ${tech['low52']} – ${tech['high52']} | "
            f"Currently {tech['pct_from_high']:+.1f}% from 52w high, "
            f"{tech['pct_from_low']:+.1f}% from 52w low"
        )

    sig_parts = []
    if tech["rsi"] is not None:
        zone = "overbought" if tech["rsi"] > 70 else ("oversold" if tech["rsi"] < 30 else "neutral zone")
        sig_parts.append(f"RSI(14): {tech['rsi']:.1f} ({zone})")
    if tech["mom5"] is not None:
        sig_parts.append(f"5-day momentum: {tech['mom5']:+.2f}%")
    if tech["mom20"] is not None:
        sig_parts.append(f"20-day momentum: {tech['mom20']:+.2f}%")
    if tech["vol_ratio"] is not None:
        direction = "above" if tech["vol_ratio"] > 1 else "below"
        sig_parts.append(f"Volume: {tech['vol_ratio']:.2f}x 20-day avg ({direction}-average)")
    if sig_parts:
        lines.append(" | ".join(sig_parts))

    lines.append("")
    lines.append("Recent 10-Session Price Action:")
    lines.append("| Date | Open | High | Low | Close | Daily Change |")
    lines.append("|------|------|------|-----|-------|-------------|")
    recent = ohlcv[-10:]
    for i, c in enumerate(recent):
        prev_close = recent[i - 1]["close"] if i > 0 else c["open"]
        chg = (c["close"] / prev_close - 1) * 100 if prev_close else 0
        lines.append(
            f"| {c['date']} | ${c['open']:.2f} | ${c['high']:.2f} | "
            f"${c['low']:.2f} | ${c['close']:.2f} | {chg:+.2f}% |"
        )
    # Volatility regime
    if vol_regime.get("regime") and vol_regime["regime"] != "N/A":
        lines.append(f"Volatility Regime: {vol_regime['regime']}")
        vr_parts = []
        if vol_regime.get("atr_14") is not None:
            pct_str = f" ({vol_regime['atr_pct']}th percentile of 252-day ATR distribution)" if vol_regime.get("atr_pct") is not None else ""
            vr_parts.append(f"ATR(14): ${vol_regime['atr_14']:.2f}{pct_str}")
        if vol_regime.get("hv_20") is not None:
            vr_parts.append(f"HV-20 (realized annualized): {vol_regime['hv_20']}%")
        if vr_parts:
            lines.append("  " + " | ".join(vr_parts))
        if vol_regime.get("atr_pct") is not None and vol_regime["atr_pct"] <= 20:
            lines.append("  Note: Volatility compression to bottom quintile historically precedes outsized directional moves.")

    # Relative performance vs sector ETF
    if rel_perf and rel_perf.get("etf"):
        etf = rel_perf["etf"]
        lines.append(f"Relative Performance vs {etf} ({co_info.get('sector', 'Sector')} ETF):")
        for period_label in ["1m", "3m", "6m"]:
            p = rel_perf.get(period_label, {})
            if p.get("stock") is not None and p.get("etf") is not None:
                rel = p["rel"]
                direction = "outperformance" if rel >= 0 else "underperformance"
                lines.append(
                    f"  {period_label}: {ticker} {p['stock']:+.1f}% vs {etf} {p['etf']:+.1f}% "
                    f"→ {rel:+.1f}% {direction}"
                )
        if rel_perf.get("label"):
            lines.append(f"  Momentum Label: {rel_perf['label']}")
            if "LAGGARD" in rel_perf["label"]:
                lines.append("  Note: Jegadeesh & Titman (1993) — 6-month relative laggards tend to underperform over next 3-12 months.")
            elif "LEADER" in rel_perf["label"]:
                lines.append("  Note: Jegadeesh & Titman (1993) — 6-month relative leaders tend to continue outperforming.")

    # Overnight vs intraday return attribution
    if overnight:
        on_signal = "institutional accumulation" if overnight["overnight_avg"] > 0 else "institutional distribution"
        id_signal = "retail buying pressure" if overnight["intraday_avg"] > 0 else "retail distribution pressure"
        lines.append("Return Attribution (20-day):")
        lines.append(
            f"  Overnight (close→open): avg {overnight['overnight_avg']:+.3f}% | "
            f"positive {overnight['overnight_pos_pct']}% of sessions → {on_signal}"
        )
        lines.append(
            f"  Intraday (open→close):  avg {overnight['intraday_avg']:+.3f}% | "
            f"positive {overnight['intraday_pos_pct']}% of sessions → {id_signal}"
        )

    lines.append("")

    # ── KRONOS OHLCV FOUNDATION MODEL ────────────────────────────────────────
    lines.append(f"── PRICE SCENARIO FORECASTS — Next {pred_len} Trading Days (Kronos Model) ─────────────")
    if scenarios:
        for idx, scenario in enumerate(scenarios):
            label = _scenario_label(
                (scenario[-1]["close"] / current - 1) * 100, scenarios, idx
            )
            implied = (scenario[-1]["close"] / current - 1) * 100
            lines.append(f"{label} (Kronos implied: {implied:+.1f}% to ${scenario[-1]['close']:.2f}):")
            lines.append("| Date | Open | High | Low | Close | Volume |")
            lines.append("|------|------|------|-----|-------|--------|")
            for c in scenario:
                lines.append(
                    f"| {c['date']} | ${c['open']:.2f} | ${c['high']:.2f} | "
                    f"${c['low']:.2f} | ${c['close']:.2f} | {c['volume']/1e6:.1f}M |"
                )
            ranges = [c["high"] - c["low"] for c in scenario]
            lines.append(f"Avg daily range: ${float(np.mean(ranges)):.2f} | Max daily range: ${max(ranges):.2f}")
            lines.append("")
    else:
        lines.append("Kronos forecast unavailable.")
        lines.append("")

    # ── EPM QUANTITATIVE ENSEMBLE ─────────────────────────────────────────────
    if epm:
        lines.append("── EPM QUANTITATIVE ENSEMBLE — 5-Day Return Forecasts ──────────────────────────")
        for model_name, val in epm.items():
            lines.append(f"- {model_name}: {val:+.2f}%")
        vals = list(epm.values())
        spread = round(max(vals) - min(vals), 2)
        max_model = max(epm, key=lambda k: epm[k])
        min_model = min(epm, key=lambda k: epm[k])
        lines.append(
            f"Model spread: {spread:.2f}% | Most optimistic: {max_model} ({epm[max_model]:+.2f}%) | "
            f"Most pessimistic: {min_model} ({epm[min_model]:+.2f}%)"
        )
        lines.append("")

    # ── GROWTH INVESTOR PERSPECTIVE ───────────────────────────────────────────
    lines.append("── GROWTH INVESTOR PERSPECTIVE ─────────────────────────────────────────────────")
    if fundamentals:
        g_parts = []
        if fundamentals.get("revenue_growth") is not None:
            g_parts.append(f"Revenue Growth (YoY): {fundamentals['revenue_growth']:+.1f}%")
        if fundamentals.get("earnings_growth") is not None:
            g_parts.append(f"Earnings Growth (YoY): {fundamentals['earnings_growth']:+.1f}%")
        if g_parts:
            lines.append(" | ".join(g_parts))

        g_parts2 = []
        if fundamentals.get("forward_pe") is not None:
            g_parts2.append(f"Forward P/E: {fundamentals['forward_pe']:.1f}x")
        if fundamentals.get("peg_ratio") is not None:
            g_parts2.append(f"PEG Ratio: {fundamentals['peg_ratio']:.2f}")
        if fundamentals.get("ev_to_ebitda") is not None:
            g_parts2.append(f"EV/EBITDA: {fundamentals['ev_to_ebitda']:.1f}x")
        if g_parts2:
            lines.append(" | ".join(g_parts2))

        g_parts3 = []
        if fundamentals.get("profit_margin") is not None:
            g_parts3.append(f"Profit Margin: {fundamentals['profit_margin']:.1f}%")
        if fundamentals.get("operating_margin") is not None:
            g_parts3.append(f"Operating Margin: {fundamentals['operating_margin']:.1f}%")
        if fundamentals.get("roe") is not None:
            g_parts3.append(f"ROE: {fundamentals['roe']:.1f}%")
        if g_parts3:
            lines.append(" | ".join(g_parts3))

        g_parts4 = []
        if fundamentals.get("recommendation") is not None and fundamentals.get("analyst_count") is not None:
            rec = fundamentals["recommendation"]
            rec_label = "Strong Buy" if rec <= 1.5 else ("Buy" if rec <= 2.5 else ("Hold" if rec <= 3.5 else ("Sell" if rec <= 4.5 else "Strong Sell")))
            g_parts4.append(f"Analyst Consensus: {rec:.1f}/5.0 ({rec_label})")
        if fundamentals.get("analyst_target") is not None:
            updown = ((fundamentals["analyst_target"] / current) - 1) * 100
            g_parts4.append(
                f"Price Target: ${fundamentals['analyst_target']:.2f} ({updown:+.1f}% from current)"
                + (f" (N={fundamentals['analyst_count']})" if fundamentals.get("analyst_count") else "")
            )
        if g_parts4:
            lines.append(" | ".join(g_parts4))
    lines.append(
        f"Growth perspective on {ticker}: Evaluate whether revenue trajectory, margin expansion, "
        f"and reinvestment rate justify the current growth premium. Does near-term volatility represent "
        f"an entry opportunity in a structural winner, or a breakdown in the growth thesis?"
    )
    if earnings_release and earnings_release.get("actuals_available"):
        eps_surprise = earnings_release.get("eps_surprise_pct")
        eps_actual   = earnings_release.get("eps_actual")
        eps_estimate = earnings_release.get("eps_estimate")
        if eps_surprise is not None:
            beat_label = (
                "EXTRAORDINARY BEAT" if abs(eps_surprise) > 50
                else "STRONG BEAT" if abs(eps_surprise) > 10
                else "BEAT"
            )
            est_str = f"Est ${eps_estimate:.2f} → " if eps_estimate is not None else ""
            act_str = f"Actual ${eps_actual:.2f}. " if eps_actual is not None else ". "
            lines.append(
                f"RECENT EARNINGS QUALITY ({beat_label}): Most recent quarter EPS surprised by "
                f"{eps_surprise:+.1f}% ({est_str}{act_str}"
                f"Analyst consensus price targets predate this release and may understate upside."
            )
    lines.append("")

    # ── VALUE INVESTOR PERSPECTIVE ────────────────────────────────────────────
    lines.append("── VALUE INVESTOR PERSPECTIVE ──────────────────────────────────────────────────")
    if fundamentals:
        v_parts = []
        if fundamentals.get("pe_ratio") is not None:
            v_parts.append(f"Trailing P/E: {fundamentals['pe_ratio']:.1f}x")
        if fundamentals.get("forward_pe") is not None:
            v_parts.append(f"Forward P/E: {fundamentals['forward_pe']:.1f}x")
        if fundamentals.get("price_to_book") is not None:
            v_parts.append(f"Price/Book: {fundamentals['price_to_book']:.1f}x")
        if fundamentals.get("ev_to_ebitda") is not None:
            v_parts.append(f"EV/EBITDA: {fundamentals['ev_to_ebitda']:.1f}x")
        if v_parts:
            lines.append(" | ".join(v_parts))

        v_parts2 = []
        if fundamentals.get("debt_to_equity") is not None:
            v_parts2.append(f"Debt/Equity: {fundamentals['debt_to_equity']:.1f}%")
        if fundamentals.get("dividend_yield") is not None:
            v_parts2.append(f"Dividend Yield: {fundamentals['dividend_yield']:.2f}%")
        if fundamentals.get("market_cap") is not None:
            mc = fundamentals["market_cap"]
            mc_str = f"${mc/1e12:.2f}T" if mc >= 1e12 else f"${mc/1e9:.1f}B"
            v_parts2.append(f"Market Cap: {mc_str}")
        if v_parts2:
            lines.append(" | ".join(v_parts2))

    lines.append(
        f"Value perspective on {ticker}: What does the current price imply about normalized "
        f"long-run earnings power and return on invested capital? Is the stock pricing a durable moat "
        f"or extrapolating unsustainable momentum? What is the margin of safety at current levels?"
    )
    lines.append("")

    # ── MARKET COMMENTATOR PERSPECTIVE ───────────────────────────────────────
    lines.append("── MARKET COMMENTATOR PERSPECTIVE ──────────────────────────────────────────────")
    lines.append(
        f"From a market commentary and sentiment perspective on {ticker}: How is the market "
        f"commentator and retail investor narrative currently framing this stock — momentum play, "
        f"turnaround story, or value trap? What headline catalyst would most rapidly shift "
        f"sentiment in either direction? Are options markets pricing complacency or genuine "
        f"tail-risk hedging relative to the technical picture and model forecasts?"
    )
    lines.append("")

    # ── BEARISH ANALYST PERSPECTIVE ───────────────────────────────────────────
    lines.append("── BEARISH ANALYST PERSPECTIVE ─────────────────────────────────────────────────")
    lines.append(
        f"The bear case for {ticker}: What risk factors are bulls systematically underweighting? "
        f"Where is market consensus most likely wrong? If the most pessimistic quantitative model "
        f"proves correct, identify the specific catalyst that triggers it and the transmission "
        f"mechanism to price. What asymmetric downside scenario are the models failing to price in, "
        f"and what hedging approach would a short-focused analyst recommend given current technicals?"
    )
    lines.append("")

    # ── MACRO / FEDERAL RESERVE PERSPECTIVE ──────────────────────────────────
    lines.append("── MACRO / FEDERAL RESERVE PERSPECTIVE ─────────────────────────────────────────")
    if vix is not None:
        lines.append(f"VIX (Fear Index): {vix} — {_vix_label(vix)}")
    if spy.get("spy_5d") is not None:
        lines.append(f"S&P 500 5-day return: {spy['spy_5d']:+.2f}% | 20-day return: {spy.get('spy_20d', 'N/A'):+.2f}%"
                     if spy.get("spy_20d") is not None else f"S&P 500 5-day return: {spy['spy_5d']:+.2f}%")
    lines.append(
        "Interest Rate Environment: Federal Reserve maintaining elevated rates (Fed Funds Rate above 4%). "
        "Higher-for-longer policy increases discount rates on future earnings, creating headwinds for "
        "growth-oriented equities and affecting capital allocation across sectors."
    )
    lines.append("")

    # ── SUPPLY CHAIN & GEOPOLITICAL RISK PERSPECTIVE ─────────────────────────
    lines.append("── SUPPLY CHAIN & GEOPOLITICAL RISK PERSPECTIVE ────────────────────────────────")
    if "technology" in sector or "consumer electronics" in sector.lower():
        lines.append(
            f"{ticker} operates with significant manufacturing concentration in China "
            f"(~85-90% of final assembly for key products). US-China trade policy, tariff regimes, "
            f"and export controls on semiconductors create structural cost and margin risk that "
            f"quantitative models do not capture. Potential retaliatory measures in the Chinese "
            f"market and ongoing supply chain diversification to India and Vietnam (multi-year in "
            f"scope) represent material non-quantifiable risks."
        )
    elif "financial" in sector:
        lines.append(
            "Financial sector exposed to credit cycle risk, regional banking stress, and "
            "regulatory capital requirement changes. Geopolitical tensions affect cross-border "
            "capital flows and correspondent banking relationships."
        )
    elif "energy" in sector:
        lines.append(
            "Energy sector subject to OPEC+ production decisions, geopolitical supply disruptions, "
            "and energy transition policy risk. Global demand growth tied to China economic activity."
        )
    elif "communication" in sector:
        lines.append(
            f"{ticker} as a communication services company faces infrastructure concentration risk: "
            f"AI and cloud infrastructure depends on custom silicon (e.g. TPUs) sourced from TSMC's "
            f"advanced nodes — subject to Taiwan geopolitical risk and semiconductor export controls. "
            f"Digital advertising revenue is exposed to EU/US antitrust actions that could force "
            f"structural remedies. Data center build-out requires rare-earth materials and power "
            f"infrastructure subject to permitting and grid constraints. These are structural risks "
            f"not captured by price-based models."
        )
    elif "consumer cyclical" in sector or "retail" in sector or "consumer discretionary" in sector:
        lines.append(
            f"{ticker} as a consumer-cyclical business carries structural risks not captured by "
            f"price-based momentum models: tariff exposure on imported goods (China remains the "
            f"dominant sourcing geography for many discretionary categories and third-party seller "
            f"inventory), consumer spending sensitivity to real wage growth, credit card "
            f"delinquencies, and interest rates, and category-specific regulatory pressure — "
            f"for platform retailers, FTC/DOJ/EU antitrust scrutiny of self-preferencing, bundling, "
            f"and seller fee structures; for auto and durable-goods makers, EV credit policy, "
            f"NHTSA recall regimes, and battery raw-material supply concentration. For diversified "
            f"businesses, cloud or ad segments may carry most of the profit while retail margins "
            f"stay structurally compressed."
        )
    else:
        lines.append(
            f"{ticker} faces sector-specific supply chain dependencies and geopolitical "
            f"exposure. Tariff regime changes, input cost volatility, and market access restrictions "
            f"in key geographies represent risks not captured by historical price-based models."
        )
    lines.append("")

    # ── EARNINGS CATALYST PERSPECTIVE ────────────────────────────────────────
    lines.append("── EARNINGS CATALYST PERSPECTIVE ────────────────────────────────────────────────")
    if earnings:
        days = earnings["days_until"]
        risk_level = "HIGH" if days <= 14 else ("MODERATE" if days <= 30 else "LOW")
        lines.append(
            f"Next earnings date: {earnings['date']} ({days} days away) — "
            f"Earnings catalyst risk: {risk_level}"
        )
        if days <= 14:
            lines.append(
                "Earnings are within the next 2 weeks. Options market implied volatility typically "
                "expands in the pre-earnings window. A surprise in either direction would significantly "
                "move the stock and likely invalidate 5-day return forecasts from trend-following models."
            )
        elif days <= 30:
            lines.append(
                "Earnings are within the next month. The 5-day forecast window sits within the "
                "pre-earnings drift period — historically, analysts revise estimates in the weeks "
                "before reporting, which can create directional drift not captured by technical models."
            )
        else:
            lines.append(
                "No near-term earnings catalyst within the 5-day forecast window. "
                "Price movement primarily driven by macro factors, technical levels, and sector rotation."
            )
    else:
        lines.append("Earnings date not available. Monitor for pre-earnings implied volatility expansion.")

    if earnings_release:
        src = earnings_release.get("source") or "unknown"
        as_of = earnings_release.get("as_of", "")
        lines.append(f"── POST-RELEASE EARNINGS ACTUALS (source: {src}, captured: {as_of}) ───────────")
        lines.append("NOTE: These are CONFIRMED POST-RELEASE figures and supersede any pre-release estimates elsewhere in this brief.")
        if earnings_release.get("actuals_available"):
            parts = []
            if earnings_release.get("eps_estimate") is not None:
                parts.append(f"Est EPS ${earnings_release['eps_estimate']:.2f}")
            if earnings_release.get("eps_actual") is not None:
                parts.append(f"Reported EPS ${earnings_release['eps_actual']:.2f}")
            if earnings_release.get("eps_surprise_pct") is not None:
                parts.append(f"EPS surprise {earnings_release['eps_surprise_pct']:+.1f}%")
            if earnings_release.get("revenue_estimate") is not None:
                parts.append(f"Rev Est ${earnings_release['revenue_estimate'] / 1e6:.0f}M")
            lines.append("  " + " | ".join(parts))
        else:
            lines.append("  Reported EPS not yet available — analysis uses pre-release estimates.")
        if earnings_release.get("headlines"):
            lines.append("  Same-day earnings headlines:")
            for h in earnings_release["headlines"][:5]:
                lines.append(f"    - {h}")
        lines.append("")

    if eps_history:
        lines.append(f"Recent EPS Surprise History (last {len(eps_history)} quarters):")
        for rec in eps_history:
            beat_str = f"+{rec['surprise_pct']:.1f}% beat" if rec["beat"] and rec.get("surprise_pct") is not None else (
                f"{rec['surprise_pct']:.1f}% miss" if rec.get("surprise_pct") is not None else ("beat" if rec["beat"] else "miss")
            )
            lines.append(f"  {rec['date']}: Est ${rec['estimated']:.2f} → Act ${rec['actual']:.2f} ({beat_str})")
        beats = sum(1 for r in eps_history if r["beat"])
        total = len(eps_history)
        beat_rate = beats / total * 100
        surprises = [r["surprise_pct"] for r in eps_history if r.get("surprise_pct") is not None]
        avg_surprise = round(float(np.mean(surprises)), 1) if surprises else None
        lines.append(
            f"Beat Rate: {beats}/{total} quarters ({beat_rate:.0f}%)"
            + (f" | Avg surprise: {avg_surprise:+.1f}%" if avg_surprise is not None else "")
        )
        if beat_rate >= 75 and avg_surprise is not None and avg_surprise > 3:
            lines.append(
                "PEAD Signal: Consistent EPS beater with large positive surprises. "
                "Bernard & Thomas (1989) — stocks with >3% positive surprises drift +2-4% "
                "in the following 20 trading days beyond what technical models predict."
            )
        elif beat_rate < 50:
            lines.append(
                "PEAD Signal: Below-50% beat rate increases downside risk around earnings. "
                "Negative surprises tend to generate sharper post-earnings selling pressure."
            )

    # Flag extraordinary recent beat — may not appear in historical avg if just released
    if earnings_release and earnings_release.get("eps_surprise_pct") is not None:
        recent_surprise = earnings_release["eps_surprise_pct"]
        if abs(recent_surprise) > 30:
            lines.append(
                f"EXTRAORDINARY EARNINGS BEAT: Most recent quarter EPS surprised by {recent_surprise:+.1f}%. "
                f"This exceeds the historical PEAD threshold by a wide margin. Historical research "
                f"shows mega-beats of this magnitude (>30%) generate sustained positive drift of "
                f"3-6%+ over 20-60 trading days — substantially stronger than the standard PEAD signal."
            )
    lines.append("")

    # ── WEB-RESEARCH ENRICHMENT ──────────────────────────────────────────────
    # Collect the concurrent research result (time-boxed). Empty when SearxNG is
    # down or nothing was found — then no sections render.
    research: Dict[str, Any] = {}
    if research_future is not None:
        try:
            research = research_future.result(timeout=RESEARCH_TIMEOUT) or {}
        except Exception:
            research = {}
        finally:
            if research_executor is not None:
                research_executor.shutdown(wait=False)

    def _prov_line(*entries) -> Optional[str]:
        """'(researched <date> · sources: …)' from one or more topic entries."""
        srcs: List[str] = []
        date = ""
        for e in entries:
            if not e:
                continue
            date = date or str(e.get("fetched_at") or "")[:10]
            srcs.extend(e.get("sources") or [])
        srcs = list(dict.fromkeys(s for s in srcs if s))[:3]
        if not date and not srcs:
            return None
        bits = []
        if date:
            bits.append(f"researched {date}")
        if srcs:
            bits.append("sources: " + " | ".join(srcs))
        return "(" + " · ".join(bits) + ")"

    if is_fund:
        mgr   = research.get("manager")
        strat = research.get("strategy")
        if (mgr and mgr.get("summary")) or (strat and strat.get("summary")):
            lines.append("── MANAGEMENT & MANDATE ────────────────────────────────────────────────────────")
            if mgr and mgr.get("summary"):
                if mgr.get("tenure_years") is not None:
                    lines.append(f"Lead manager tenure: ~{mgr['tenure_years']:.0f} years")
                lines.append(f"Management: {mgr['summary']}")
            if strat and strat.get("summary"):
                lines.append(f"Strategy: {strat['summary']}")
            prov = _prov_line(mgr, strat)
            if prov:
                lines.append(prov)
            lines.append("")

        dev   = research.get("developments")
        flows = research.get("flows")
        if (dev and dev.get("summary")) or (flows and flows.get("summary")):
            lines.append("── FUND DEVELOPMENTS & FLOWS ───────────────────────────────────────────────────")
            if dev and dev.get("summary"):
                lines.append(f"Recent developments: {dev['summary']}")
            if flows and flows.get("summary"):
                lines.append(f"Asset flows: {flows['summary']}")
            prov = _prov_line(dev, flows)
            if prov:
                lines.append(prov)
            lines.append("")
    else:
        _STOCK_INTEL = [
            ("management_changes", "Management changes"),
            ("legal_regulatory",   "Legal / regulatory"),
            ("analyst_actions",    "Analyst actions"),
            ("mna",                "M&A activity"),
        ]
        present = [(lbl, research[k]) for k, lbl in _STOCK_INTEL
                   if research.get(k) and research[k].get("summary")]
        if present:
            lines.append("── SITUATIONAL INTELLIGENCE ────────────────────────────────────────────────────")
            for lbl, entry in present:
                lines.append(f"{lbl}: {entry['summary']}")
            prov = _prov_line(*[e for _, e in present])
            if prov:
                lines.append(prov)
            lines.append("")

    # ── RECENT HEADLINES ─────────────────────────────────────────────────────
    if headlines:
        lines.append("── RECENT HEADLINES ─────────────────────────────────────────────────────────")
        for i, h in enumerate(headlines[:8], 1):
            lines.append(f"{i}. {h}")
        lines.append("")

    # ── ANALYSIS OBJECTIVE ───────────────────────────────────────────────────
    lines.append("── ANALYSIS OBJECTIVE ───────────────────────────────────────────────────────────")

    kronos_clause = ""
    if scenarios:
        all_implied = [(s[-1]["close"] / current - 1) * 100 for s in scenarios]
        if len(all_implied) > 1:
            kronos_clause = (
                f"Kronos projects a range from {min(all_implied):+.1f}% to {max(all_implied):+.1f}% "
                f"over {pred_len} days (${scenarios[0][-1]['close']:.2f} – ${scenarios[-1][-1]['close']:.2f})"
            )
        else:
            implied = all_implied[0]
            kronos_clause = (
                f"Kronos projects {implied:+.1f}% to ${scenarios[0][-1]['close']:.2f} "
                f"over {pred_len} days"
            )

    epm_clause = ""
    if epm:
        vals = list(epm.values())
        spread = round(max(vals) - min(vals), 2)
        max_model = max(epm, key=lambda k: epm[k])
        min_model = min(epm, key=lambda k: epm[k])
        epm_clause = (
            f", while EPM models range from {min_model} at {epm[min_model]:+.2f}% "
            f"to {max_model} at {epm[max_model]:+.2f}% ({spread:.2f}% spread)"
        )

    lines.append(
        f"For {ticker} over the next {pred_len} trading days: {kronos_clause}{epm_clause}. "
        f"Given this data, across all analytical perspectives above: "
        f"(1) Under what specific market conditions or catalysts would {min_model if epm else 'the most pessimistic'}s "
        f"forecast prove correct — be specific about the trigger and mechanism. "
        f"(2) Where is the asymmetric risk — is the potential downside or upside more likely being underestimated, and why? "
        f"(3) What are the 2-3 most critical non-obvious risks that quantitative models cannot capture "
        f"(regulatory, geopolitical, supply chain, behavioral)? "
        f"(4) Does the model spread signal genuine directional uncertainty or do models simply weight different risk factors differently? "
        f"(5) Given the volatility regime, relative sector performance, overnight/intraday return split, and EPS beat history shown above — "
        f"what specific near-term behavioral edge do these signals provide beyond what price momentum models capture, "
        f"and does the PEAD drift signal strengthen or conflict with the Kronos base case? "
        f"Prioritize specific insight and scenario analysis over directional summary."
    )

    # ── KEY FACTS — authoritative values for the LLM post-processor ─────────
    # Named explicitly so the LLM cannot mistake units. All *_pct fields are
    # already in percent form (e.g. 34.2 means 34.2%). Null/None values are
    # preserved so the consumer can decide whether to omit them.
    key_facts: Dict[str, Any] = {
        "ticker":              ticker,
        "company_name":        co_info.get("name"),
        "sector":              co_info.get("sector"),
        "industry":            co_info.get("industry"),
        "report_date":         today,
        "current_price":       tech.get("current"),
        "52w_high":            tech.get("high52"),
        "52w_low":             tech.get("low52"),
        "pct_from_52w_high":   tech.get("pct_from_high"),
        "pct_from_52w_low":    tech.get("pct_from_low"),
        "ma50":                tech.get("ma50"),
        "ma200":               tech.get("ma200"),
        "rsi_14":              tech.get("rsi"),
        "mom_5d_pct":          tech.get("mom5"),
        "mom_20d_pct":         tech.get("mom20"),
        "vol_ratio_vs_20d":    tech.get("vol_ratio"),
    }

    if fundamentals:
        key_facts.update({
            "trailing_pe":                  fundamentals.get("pe_ratio"),
            "forward_pe":                   fundamentals.get("forward_pe"),
            "peg_ratio":                    fundamentals.get("peg_ratio"),
            "ev_to_ebitda":                 fundamentals.get("ev_to_ebitda"),
            "price_to_book":                fundamentals.get("price_to_book"),
            "eps_ttm":                      fundamentals.get("eps_ttm"),
            "revenue_growth_pct":           fundamentals.get("revenue_growth"),
            "earnings_growth_pct":          fundamentals.get("earnings_growth"),
            "profit_margin_pct":            fundamentals.get("profit_margin"),
            "operating_margin_pct":         fundamentals.get("operating_margin"),
            "roe_pct":                      fundamentals.get("roe"),
            "debt_to_equity":               fundamentals.get("debt_to_equity"),
            "dividend_yield_pct":           fundamentals.get("dividend_yield"),
            "market_cap_usd":               fundamentals.get("market_cap"),
            "analyst_target_price":         fundamentals.get("analyst_target"),
            "analyst_count":                fundamentals.get("analyst_count"),
            "analyst_recommendation_score": fundamentals.get("recommendation"),
        })
        if fundamentals.get("analyst_target") is not None and current:
            key_facts["analyst_target_upside_pct"] = round(
                (fundamentals["analyst_target"] / current - 1) * 100, 2
            )

    key_facts.update({
        "atr_14":                    vol_regime.get("atr_14"),
        "atr_percentile":            vol_regime.get("atr_pct"),
        "hv_20_annualized_pct":      vol_regime.get("hv_20"),
        "volatility_regime":         vol_regime.get("regime"),
    })

    if is_fund and fund:
        key_facts.update({
            "is_fund":                  True,
            "fund_type":                fund.get("issue_type"),
            "fund_category":            fund.get("category"),
            "fund_family":              fund.get("fund_family"),
            "expense_ratio_pct":        fund.get("expense_ratio_pct"),
            "top10_concentration_pct":  fund.get("top10_concentration_pct"),
            "top_holdings":             fund.get("top_holdings"),
            "fund_objective":           fund.get("objective") or None,
        })
        _mgr = research.get("manager") or {}
        if _mgr.get("summary"):
            key_facts["fund_managers"] = _mgr.get("managers") or None
            key_facts["manager_summary"] = _mgr.get("summary")
            key_facts["manager_tenure_years"] = _mgr.get("tenure_years")
        if (research.get("strategy") or {}).get("summary"):
            key_facts["fund_strategy"] = research["strategy"]["summary"]
        if (research.get("developments") or {}).get("summary"):
            key_facts["fund_developments"] = research["developments"]["summary"]
        if (research.get("flows") or {}).get("summary"):
            key_facts["fund_flows"] = research["flows"]["summary"]
    elif research:
        # Stock situational intelligence into key_facts for the bearish / supply-chain personas.
        for _k, _kf in (("management_changes", "mgmt_change_note"),
                        ("legal_regulatory", "legal_regulatory_note"),
                        ("analyst_actions", "analyst_action_note"),
                        ("mna", "mna_note")):
            if (research.get(_k) or {}).get("summary"):
                key_facts[_kf] = research[_k]["summary"]

    if rel_perf:
        key_facts["sector_etf"] = rel_perf.get("etf")
        key_facts["sector_momentum_label"] = rel_perf.get("label")
        for lbl in ("1m", "3m", "6m"):
            p = rel_perf.get(lbl) or {}
            key_facts[f"rel_perf_{lbl}_stock_pct"] = p.get("stock")
            key_facts[f"rel_perf_{lbl}_etf_pct"]   = p.get("etf")
            key_facts[f"rel_perf_{lbl}_diff_pct"]  = p.get("rel")

    if overnight:
        key_facts.update({
            "overnight_avg_pct_20d":     overnight.get("overnight_avg"),
            "intraday_avg_pct_20d":      overnight.get("intraday_avg"),
            "overnight_positive_pct":    overnight.get("overnight_pos_pct"),
            "intraday_positive_pct":     overnight.get("intraday_pos_pct"),
        })

    if eps_history:
        beats = sum(1 for r in eps_history if r.get("beat"))
        total = len(eps_history)
        surprises = [r["surprise_pct"] for r in eps_history if r.get("surprise_pct") is not None]
        avg_surprise = round(float(np.mean(surprises)), 1) if surprises else None
        beat_rate_pct = round(beats / total * 100, 1) if total else None
        if beat_rate_pct is not None and beat_rate_pct >= 75 and avg_surprise is not None and avg_surprise > 3:
            pead = "active_positive_drift"
        elif beat_rate_pct is not None and beat_rate_pct < 50:
            pead = "negative_earnings_risk"
        else:
            pead = "neutral"
        key_facts.update({
            "eps_beat_rate_str":     f"{beats}/{total}",
            "eps_beat_rate_pct":     beat_rate_pct,
            "avg_eps_surprise_pct":  avg_surprise,
            "pead_signal":           pead,
        })

    key_facts.update({
        "vix":          vix,
        "vix_regime":   _vix_label(vix) if vix is not None else None,
        "spy_5d_pct":   spy.get("spy_5d"),
        "spy_20d_pct":  spy.get("spy_20d"),
    })

    if earnings:
        key_facts.update({
            "next_earnings_date":  earnings.get("date"),
            "days_to_earnings":    earnings.get("days_until"),
            "earnings_release_time": earnings.get("release_time"),
        })

    if earnings_release:
        key_facts.update({
            "earnings_release_detected": earnings_release.get("actuals_available") or earnings_release.get("news_available"),
            "earnings_release_date": earnings_release.get("earnings_date"),
            "earnings_refresh_complete": earnings_release.get("refresh_complete"),
            "reported_eps": earnings_release.get("eps_actual"),
            "estimated_eps": earnings_release.get("eps_estimate"),
            "eps_release_surprise_pct": earnings_release.get("eps_surprise_pct"),
            "earnings_release_source": earnings_release.get("source"),
            "earnings_release_as_of": earnings_release.get("as_of"),
        })
        if earnings_release.get("headlines"):
            key_facts["earnings_release_headlines"] = earnings_release["headlines"][:8]

        # Flag stale analyst targets — targets predate the release so upside calc is unreliable
        if earnings_release.get("actuals_available"):
            key_facts["analyst_targets_may_be_stale"] = True

        # Enhance PEAD signal when most recent beat is extraordinary
        _release_surprise = earnings_release.get("eps_surprise_pct")
        if _release_surprise is not None and abs(_release_surprise) > 30:
            key_facts["pead_signal"] = "extraordinary_beat_positive_drift"
            key_facts["pead_extraordinary_note"] = (
                f"Most recent EPS beat of {_release_surprise:+.1f}% is extraordinary — "
                f"far exceeds the historical PEAD threshold (>3%). Historical research indicates "
                f"beats of this magnitude generate positive drift of 3-6%+ over 20-60 trading days."
            )

    if scenarios:
        ranked = sorted(scenarios, key=lambda s: s[-1]["close"])
        targets = [s[-1]["close"] for s in ranked]
        labels = ["kronos_bearish", "kronos_base", "kronos_bullish"]
        # If fewer than 3 scenarios, collapse: 1 → base only, 2 → bearish+bullish
        if len(ranked) == 1:
            key_facts["kronos_base_target"] = round(targets[0], 2)
            key_facts["kronos_base_implied_pct"] = round((targets[0] / current - 1) * 100, 2)
        else:
            for i, tgt in enumerate(targets):
                if i == 0:
                    k = "kronos_bearish"
                elif i == len(targets) - 1:
                    k = "kronos_bullish"
                else:
                    k = "kronos_base"
                key_facts[f"{k}_target"] = round(tgt, 2)
                key_facts[f"{k}_implied_pct"] = round((tgt / current - 1) * 100, 2)
        key_facts["kronos_forecast_days"] = pred_len

    if epm:
        vals = list(epm.values())
        key_facts.update({
            "epm_spread_pct":            round(max(vals) - min(vals), 2),
            "epm_most_optimistic_model": max(epm, key=lambda k: epm[k]),
            "epm_most_optimistic_pct":   round(max(vals), 2),
            "epm_most_pessimistic_model": min(epm, key=lambda k: epm[k]),
            "epm_most_pessimistic_pct":  round(min(vals), 2),
            "epm_model_count":           len(epm),
        })

    if headlines:
        key_facts["recent_headlines"] = headlines[:8]

    return "\n".join(lines), key_facts


if __name__ == "__main__":
    import sys, json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"Building seed doc for {ticker}...")
    doc, key_facts = build_seed_doc(ticker)
    print(doc)
    print(f"\n--- {len(doc)} chars, ~{len(doc.split())} words ---")
    print("\n--- KEY FACTS ---")
    print(json.dumps(key_facts, indent=2, default=str))
