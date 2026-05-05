"""
Alpha Vantage Earnings Loader
Provides point-in-time quarterly EPS surprise data for PEAD backtesting.
Returns data in the same format as earnings_fmp.py so tournament.py can
use either source transparently.

Free tier: 25 calls/min, 500 calls/day → 844 tickers in ~2 days.
Cache is per-ticker JSON so downloads resume across sessions.

Setup: AV_API_KEY in .env
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

CACHE_DIR = Path(__file__).parent / "data" / "av_earnings"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

AV_BASE = "https://www.alphavantage.co/query"
# Free tier: 25/min. 2.5s delay keeps us safely under.
# Set AV_FAST=1 in env to remove delay (premium tier).
_DELAY = 0.0 if os.environ.get("AV_FAST") else 2.5


def _ticker_cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker}.json"


def _is_cached(ticker: str, max_age_days: int = 30) -> bool:
    p = _ticker_cache_path(ticker)
    if not p.exists():
        return False
    if (time.time() - p.stat().st_mtime) / 86400 >= max_age_days:
        return False
    # Empty [] means rate-limit response was cached — treat as not cached
    return p.stat().st_size > 4


class _DailyLimitExhausted(Exception):
    pass


def _sanitize_av_message(message: str, api_key: str) -> str:
    sanitized = message.replace(api_key, "[REDACTED]") if api_key else message
    return re.sub(r"API key as [A-Za-z0-9]+", "API key as [REDACTED]", sanitized)


def _fetch_ticker(ticker: str, api_key: str) -> list[dict]:
    params = {"function": "EARNINGS", "symbol": ticker, "apikey": api_key}
    resp = requests.get(AV_BASE, params=params, timeout=15)
    if resp.status_code != 200:
        log.warning(f"  AV {ticker}: HTTP {resp.status_code}")
        return []
    data = resp.json()
    if "Note" in data or "Information" in data:
        msg = _sanitize_av_message(data.get("Note") or data.get("Information", ""), api_key)
        log.warning(f"  AV rate limit: {msg[:80]}")
        # Daily limit exhausted — bail immediately rather than sleeping forever
        raise _DailyLimitExhausted(msg)
    return data.get("quarterlyEarnings", [])


def _normalize(records: list[dict], ticker: str) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    # Use reportedDate (announcement date) as index — critical for point-in-time
    df["date"] = pd.to_datetime(df.get("reportedDate", df.get("fiscalDateEnding")), errors="coerce")
    df = df.dropna(subset=["date"])
    df["epsActual"] = pd.to_numeric(df.get("reportedEPS", pd.NA), errors="coerce")
    df["epsEstimate"] = pd.to_numeric(df.get("estimatedEPS", pd.NA), errors="coerce")
    # AV surprisePercentage is in % form (e.g. 6.37), convert to decimal (0.0637)
    df["surprisePercent"] = pd.to_numeric(df.get("surprisePercentage", pd.NA), errors="coerce") / 100.0
    df["ticker"] = ticker
    df = df.set_index("date").sort_index()
    return df[["ticker", "epsActual", "epsEstimate", "surprisePercent"]]


def download_earnings(
    tickers: list[str],
    api_key: str,
    force_refresh: bool = False,
    max_age_days: int = 30,
) -> None:
    """Download and cache earnings for all tickers. Safe to interrupt and resume."""
    pending = [t for t in tickers if not _is_cached(t, max_age_days) or force_refresh]
    log.info(f"AV download: {len(pending)} to fetch, {len(tickers)-len(pending)} cached")
    if not pending:
        return
    for i, ticker in enumerate(pending, 1):
        if i % 50 == 1:
            log.info(f"  AV progress: {i}/{len(pending)}")
        try:
            records = _fetch_ticker(ticker, api_key)
            with open(_ticker_cache_path(ticker), "w") as f:
                json.dump(records, f)
        except _DailyLimitExhausted:
            log.warning(f"  AV daily limit exhausted at ticker {i}/{len(pending)} — stopping download. Re-run tomorrow.")
            break
        except Exception as exc:
            # requests exceptions include the full URL, which contains the API key.
            log.warning(f"  AV {ticker} failed: {type(exc).__name__}")
        if _DELAY:
            time.sleep(_DELAY)


def load_earnings_av(
    tickers: list[str] | None = None,
    api_key: str | None = None,
    start: str = "2006-01-01",
    end: str = "2025-12-31",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Load AV earnings from cache (downloading any missing tickers if api_key provided).
    Returns same format as load_earnings_fmp():
      index=DatetimeIndex, columns=[ticker, epsActual, epsEstimate, surprisePercent]
    """
    if api_key is None:
        api_key = os.environ.get("AV_API_KEY", "")
    if tickers is None:
        tickers = [p.stem for p in CACHE_DIR.glob("*.json")]

    if api_key:
        download_earnings(tickers, api_key, force_refresh=force_refresh)
    else:
        tickers = [t for t in tickers if _is_cached(t)]

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
            log.warning(f"  AV load failed {ticker}: {exc}")

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames).sort_index()
    combined = combined[
        (combined.index >= pd.Timestamp(start)) & (combined.index <= pd.Timestamp(end))
    ]
    log.info(
        f"AV earnings: {len(combined):,} records, "
        f"{combined['ticker'].nunique()} tickers, "
        f"{combined.index.min().date()} to {combined.index.max().date()}"
    )
    return combined


def cache_status(tickers: list[str] | None = None) -> dict:
    if tickers is None:
        tickers = [p.stem for p in CACHE_DIR.glob("*.json")]
    cached = [t for t in tickers if _is_cached(t)]
    missing = [t for t in tickers if not _is_cached(t, 9999)]
    return {
        "total": len(tickers),
        "cached": len(cached),
        "missing": len(missing),
        "est_days_remaining": -(-len(missing) // 500),
    }
