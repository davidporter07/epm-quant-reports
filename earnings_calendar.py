"""
earnings_calendar.py — Persistent store for next-earnings dates.

Tracks the upcoming earnings date for a watched list of large-cap tickers plus
any ticker that has been run through deep analysis. On each POST to /api/deep,
the app checks this store instead of relying on a prior cached job existing —
so earnings-triggered invalidation works even on the very first analysis of the day.

Lifecycle:
  1. get_next_earnings_date(ticker)  — returns cached date if still valid, else fetches
  2. update_from_key_facts(ticker, key_facts)  — called when deep analysis completes
  3. mark_earnings_passed(ticker)  — called after actuals confirmed; clears date so
                                     the next refresh picks up the following quarter
  4. refresh_expired()  — called by daily pipeline; re-fetches any expired dates
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")

CALENDAR_PATH = Path("data") / "earnings_calendar.json"

# Tickers to always keep fresh, regardless of deep analysis runs.
WATCHED_TICKERS = [
    # Magnificent 7
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    # Large-cap semiconductors
    "AMD", "INTC", "QCOM", "AVGO", "TXN", "MU", "AMAT",
    # Large-cap finance
    "JPM", "BAC", "GS", "MS", "V", "MA",
    # Large-cap other
    "JNJ", "UNH", "XOM", "CVX", "WMT", "HD", "DIS",
]

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal I/O
# ---------------------------------------------------------------------------

def _load() -> dict:
    try:
        if CALENDAR_PATH.exists():
            return json.loads(CALENDAR_PATH.read_text())
    except Exception:
        pass
    return {}


def _save(calendar: dict) -> None:
    CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CALENDAR_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(calendar, indent=2))
    tmp.replace(CALENDAR_PATH)


def _fetch_from_yfinance(ticker: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (date_str, release_time) from yfinance calendar, or (None, None)."""
    try:
        from deep_analysis import _get_earnings_info
        info = _get_earnings_info(ticker)
        if info:
            return info.get("date"), info.get("release_time")
    except Exception:
        pass
    return None, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_next_earnings_date(ticker: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (next_earnings_date_str, release_time) for ticker.

    Returns the cached value if the date is today or in the future.
    Re-fetches from yfinance if the stored date has passed or is absent.
    Returns (None, None) if unavailable.
    """
    ticker = ticker.upper()
    today = datetime.now(tz=NY_TZ).date()
    today_str = str(today)

    with _lock:
        calendar = _load()
        entry = calendar.get(ticker, {})
        stored_date = entry.get("next_earnings_date")

        if stored_date:
            try:
                if date.fromisoformat(stored_date) >= today:
                    return stored_date, entry.get("release_time")
            except (ValueError, TypeError):
                pass

    # Expired or missing — fetch outside the lock (slow network call)
    date_str, release_time = _fetch_from_yfinance(ticker)

    if date_str:
        with _lock:
            calendar = _load()
            calendar[ticker] = {
                "next_earnings_date": date_str,
                "release_time":       release_time,
                "last_fetched":       today_str,
                "source":             "yfinance",
            }
            _save(calendar)

    return date_str, release_time


def update_from_key_facts(ticker: str, key_facts: dict) -> None:
    """Store earnings date extracted during deep analysis. Called on job completion.

    Only updates if the incoming date is the same or later than what's stored,
    so a stale key_facts from a re-queued job doesn't overwrite a fresher entry.
    """
    ticker = ticker.upper()
    date_str = key_facts.get("next_earnings_date")
    release_time = key_facts.get("release_time")
    if not date_str:
        return
    today_str = datetime.now(tz=NY_TZ).strftime("%Y-%m-%d")
    with _lock:
        calendar = _load()
        existing_date = calendar.get(ticker, {}).get("next_earnings_date") or ""
        if date_str >= existing_date:
            calendar[ticker] = {
                "next_earnings_date": date_str,
                "release_time":       release_time,
                "last_fetched":       today_str,
                "source":             "deep_analysis",
            }
            _save(calendar)


def mark_earnings_passed(ticker: str) -> None:
    """Mark a ticker's earnings as released so the next calendar fetch picks up
    the following quarter's date rather than the now-stale one."""
    ticker = ticker.upper()
    today_str = datetime.now(tz=NY_TZ).strftime("%Y-%m-%d")
    with _lock:
        calendar = _load()
        if ticker in calendar:
            calendar[ticker]["next_earnings_date"] = None
            calendar[ticker]["last_fetched"] = today_str
            _save(calendar)


def refresh_expired(tickers: list = None) -> dict:
    """Refresh any tickers whose stored date has already passed.

    Called by the daily pipeline (post_run.py). Returns {ticker: new_date_str}
    for every ticker that was updated.
    """
    today = datetime.now(tz=NY_TZ).date()
    today_str = str(today)
    target = [t.upper() for t in (tickers or WATCHED_TICKERS)]

    # Phase 1: identify who needs a refresh (fast, under lock)
    with _lock:
        calendar = _load()

    needs_refresh = []
    for ticker in target:
        entry = calendar.get(ticker, {})
        stored = entry.get("next_earnings_date")
        if not stored:
            needs_refresh.append(ticker)
            continue
        try:
            if date.fromisoformat(stored) < today:
                needs_refresh.append(ticker)
        except (ValueError, TypeError):
            needs_refresh.append(ticker)

    # Phase 2: fetch (outside lock — yfinance calls are slow)
    fetched: dict[str, tuple] = {}
    for ticker in needs_refresh:
        date_str, release_time = _fetch_from_yfinance(ticker)
        if date_str:
            fetched[ticker] = (date_str, release_time)
            print(f"[earnings_calendar] {ticker}: {calendar.get(ticker, {}).get('next_earnings_date', 'none')} -> {date_str} ({release_time})")

    # Phase 3: persist (re-read under lock in case other threads wrote)
    if fetched:
        with _lock:
            calendar = _load()
            for ticker, (date_str, release_time) in fetched.items():
                calendar[ticker] = {
                    "next_earnings_date": date_str,
                    "release_time":       release_time,
                    "last_fetched":       today_str,
                    "source":             "yfinance_refresh",
                }
            _save(calendar)

    return {t: v[0] for t, v in fetched.items()}
