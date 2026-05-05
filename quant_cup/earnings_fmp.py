"""
FMP (Financial Modeling Prep) Earnings Loader
Provides 20 years of point-in-time EPS surprise data for PEAD backtesting.
Caches per-ticker to allow incremental downloads across multiple days.

Free tier: 250 API calls/day → ~503 tickers takes 3 days.
Paid tier ($14/mo): unlimited calls → all tickers in ~10 minutes.

Setup:
    Add to .env:  FMP_API_KEY=your_key_here
    Get a free key at: https://financialmodelingprep.com/developer/docs/

Usage:
    from quant_cup.earnings_fmp import load_earnings_fmp
    df = load_earnings_fmp(tickers, api_key="your_key")
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "data" / "fmp_earnings"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FMP_BASE = "https://financialmodelingprep.com/stable"

# Free tier: 250 calls/day. Use 0.25s delay to stay within rate limits.
# Set FMP_FAST=1 in environment to disable delay (paid tier).
_DELAY = 0.0 if os.environ.get("FMP_FAST") else 0.3


def _ticker_cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker}.json"


def _sanitize_fmp_message(message: str, api_key: str) -> str:
    sanitized = message.replace(api_key, "[REDACTED]") if api_key else message
    return re.sub(r"apikey=[A-Za-z0-9]+", "apikey=[REDACTED]", sanitized)


def _is_cached(ticker: str, max_age_days: int = 30) -> bool:
    p = _ticker_cache_path(ticker)
    if not p.exists():
        return False
    if p.stat().st_size <= 2:
        return False
    age = (time.time() - p.stat().st_mtime) / 86400
    return age < max_age_days


def _fetch_ticker(ticker: str, api_key: str) -> list[dict]:
    """Fetch earnings surprises for one ticker from FMP. Returns raw JSON list."""
    url = f"{FMP_BASE}/earnings?symbol={ticker}&apikey={api_key}"
    resp = requests.get(url, timeout=15)
    if resp.status_code == 429:
        log.warning(f"  FMP rate limit hit on {ticker} — sleeping 60s")
        time.sleep(60)
        resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        log.warning(f"  FMP {ticker}: HTTP {resp.status_code}")
        return []
    data = resp.json()
    if isinstance(data, dict) and "Error Message" in data:
        msg = _sanitize_fmp_message(str(data["Error Message"]), api_key)
        log.warning(f"  FMP {ticker}: {msg}")
        return []
    return data if isinstance(data, list) else []


def _normalize(records: list[dict], ticker: str) -> pd.DataFrame:
    """
    Convert FMP response to standard format used by pead.py:
      index = earnings date (DatetimeIndex)
      columns: ticker, epsActual, epsEstimate, surprisePercent
    """
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    if "date" not in df.columns:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    # FMP column names vary by endpoint/version.
    rename = {
        "actualEarningResult": "epsActual",
        "estimatedEarning": "epsEstimate",
        "epsActual": "epsActual",
        "epsEstimated": "epsEstimate",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    if "epsActual" in df.columns and "epsEstimate" in df.columns:
        denom = df["epsEstimate"].abs().replace(0, float("nan"))
        df["surprisePercent"] = (df["epsActual"] - df["epsEstimate"]) / denom
    elif "surprisePercent" not in df.columns:
        return pd.DataFrame()

    df["ticker"] = ticker
    df = df.set_index("date").sort_index()
    return df[["ticker", "epsActual", "epsEstimate", "surprisePercent"]]


def download_earnings(
    tickers: list[str],
    api_key: str,
    force_refresh: bool = False,
    max_age_days: int = 30,
) -> None:
    """
    Download earnings for all tickers, caching each one individually.
    Safe to interrupt and resume — already-cached tickers are skipped.
    Prints progress so you can monitor across multi-day free-tier downloads.
    """
    pending = [t for t in tickers if not _is_cached(t, max_age_days) or force_refresh]
    already_done = len(tickers) - len(pending)

    log.info(f"FMP download: {len(pending)} tickers to fetch, {already_done} already cached")
    if not pending:
        return

    for i, ticker in enumerate(pending, 1):
        if i % 50 == 1:
            log.info(f"  Progress: {i}/{len(pending)} (of {len(tickers)} total)")
        try:
            records = _fetch_ticker(ticker, api_key)
            cache_path = _ticker_cache_path(ticker)
            with open(cache_path, "w") as f:
                json.dump(records, f)
        except Exception as exc:
            # requests exceptions can include the full URL, which contains the API key.
            log.warning(f"  {ticker} failed: {type(exc).__name__}")
        if _DELAY:
            time.sleep(_DELAY)


def load_earnings_fmp(
    tickers: list[str] | None = None,
    api_key: str | None = None,
    start: str = "2006-01-01",
    end: str = "2025-12-31",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Load earnings surprise data from FMP cache.
    Downloads any missing tickers if api_key is provided.

    Returns long-form DataFrame identical to data_loader.load_earnings() format:
      index = DatetimeIndex (earnings announcement date)
      columns: ticker, epsActual, epsEstimate, surprisePercent

    If api_key is None, loads only what's already in the cache.
    """
    if api_key is None:
        api_key = os.environ.get("FMP_API_KEY", "")

    if tickers is None:
        # Load everything in cache
        tickers = [p.stem for p in CACHE_DIR.glob("*.json")]

    if api_key:
        download_earnings(tickers, api_key, force_refresh=force_refresh)
    else:
        cached = [t for t in tickers if _is_cached(t)]
        missing = len(tickers) - len(cached)
        if missing:
            log.warning(
                f"FMP: {missing} tickers not cached and no api_key provided. "
                "Set FMP_API_KEY env var or pass api_key= to download them."
            )
        tickers = cached

    frames = []
    for ticker in tickers:
        p = _ticker_cache_path(ticker)
        if not p.exists():
            continue
        try:
            with open(p) as f:
                records = json.load(f)
            df = _normalize(records, ticker)
            if not df.empty:
                frames.append(df)
        except Exception as exc:
            log.warning(f"  Failed to load cache for {ticker}: {exc}")

    if not frames:
        log.warning("FMP: no earnings data loaded. Check API key and cache.")
        return pd.DataFrame()

    combined = pd.concat(frames).sort_index()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    combined = combined[(combined.index >= start_ts) & (combined.index <= end_ts)]

    log.info(
        f"FMP earnings loaded: {len(combined):,} records, "
        f"{combined['ticker'].nunique()} tickers, "
        f"{combined.index.min().date()} to {combined.index.max().date()}"
    )
    return combined


def cache_status(tickers: list[str] | None = None) -> dict:
    """Report how many tickers are cached and how fresh they are."""
    if tickers is None:
        tickers = [p.stem for p in CACHE_DIR.glob("*.json")]

    cached = [t for t in tickers if _is_cached(t, max_age_days=30)]
    stale = [t for t in tickers if _is_cached(t, max_age_days=9999) and not _is_cached(t, 30)]
    missing = [t for t in tickers if not _is_cached(t, max_age_days=9999)]

    return {
        "total": len(tickers),
        "cached_fresh": len(cached),
        "cached_stale": len(stale),
        "missing": len(missing),
        "missing_tickers": missing[:20],
        "days_remaining_free_tier": -(-len(missing) // 250) if missing else 0,
    }
