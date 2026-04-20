"""
S&P 500 Historical Composition
Reconstructs point-in-time S&P 500 membership from Wikipedia's changes table.
Eliminates survivorship bias: on any date, only trade stocks that were actually
in the index at that time.

Usage:
    comp = SP500Composition()
    members_2010 = comp.members_on("2010-06-15")   # set of tickers
    universe = comp.universe_for_period("2006-01-01", "2025-12-31")  # all tickers ever in index
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "data"
CACHE_DIR.mkdir(exist_ok=True)
CHANGES_FILE = CACHE_DIR / "sp500_changes.csv"
CURRENT_FILE = CACHE_DIR / "sp500_tickers.csv"

_WIKI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


def _fetch_changes(force_refresh: bool = False) -> pd.DataFrame:
    """Download and cache the historical S&P 500 changes table from Wikipedia."""
    if CHANGES_FILE.exists() and not force_refresh:
        df = pd.read_csv(CHANGES_FILE, parse_dates=["date"])
        return df

    log.info("Fetching S&P 500 historical changes from Wikipedia...")
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    resp = requests.get(url, headers=_WIKI_HEADERS, timeout=30)
    resp.raise_for_status()

    tables = pd.read_html(io.StringIO(resp.text))
    raw = tables[1].copy()
    raw.columns = ["date", "added_ticker", "added_name", "removed_ticker", "removed_name", "reason"]
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw.dropna(subset=["date"]).sort_values("date")

    # Clean tickers: strip whitespace, normalise BRK.B → BRK-B
    for col in ("added_ticker", "removed_ticker"):
        raw[col] = raw[col].astype(str).str.strip().str.replace(".", "-", regex=False)
        raw[col] = raw[col].replace("nan", pd.NA)

    raw.to_csv(CHANGES_FILE, index=False)
    log.info(f"Saved {len(raw)} changes ({raw['date'].min().date()} → {raw['date'].max().date()})")
    return raw


def _fetch_current(force_refresh: bool = False) -> set[str]:
    """Return today's S&P 500 member set."""
    if CURRENT_FILE.exists() and not force_refresh:
        df = pd.read_csv(CURRENT_FILE)
        return set(df["Symbol"].dropna().tolist())

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    resp = requests.get(url, headers=_WIKI_HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    tickers = (
        tables[0]["Symbol"]
        .str.strip()
        .str.replace(".", "-", regex=False)
        .dropna()
        .tolist()
    )
    pd.DataFrame({"Symbol": tickers}).to_csv(CURRENT_FILE, index=False)
    return set(tickers)


class SP500Composition:
    """
    Point-in-time S&P 500 membership tracker.

    Algorithm: start from today's known list, then wind the changes
    table backwards — un-apply every change that happened after the
    target date.
    """

    def __init__(self, force_refresh: bool = False):
        self._changes = _fetch_changes(force_refresh)
        self._current = _fetch_current(force_refresh)
        self._cache: dict[str, set[str]] = {}

    def members_on(self, date: str | pd.Timestamp) -> set[str]:
        """Return the set of S&P 500 tickers that were members on `date`."""
        target = pd.Timestamp(date)
        key = str(target.date())
        if key in self._cache:
            return self._cache[key]

        members = set(self._current)
        # Walk backwards through changes that happened AFTER the target date
        future_changes = self._changes[self._changes["date"] > target].sort_values(
            "date", ascending=False
        )

        for _, row in future_changes.iterrows():
            added = row["added_ticker"]
            removed = row["removed_ticker"]
            # Undo addition: ticker was added after target → wasn't there yet
            if pd.notna(added) and added != "nan":
                members.discard(added)
            # Undo removal: ticker was removed after target → was still there
            if pd.notna(removed) and removed != "nan":
                members.add(removed)

        self._cache[key] = members
        return members

    def universe_for_period(self, start: str, end: str) -> set[str]:
        """
        Union of all tickers that were in the S&P 500 at any point during [start, end].
        Use this as the download universe to avoid missing delisted stocks.
        """
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)

        # All tickers visible at start + everything added between start and end
        universe = self.members_on(start_ts)

        additions_in_period = self._changes[
            (self._changes["date"] >= start_ts) & (self._changes["date"] <= end_ts)
        ]["added_ticker"].dropna()

        for ticker in additions_in_period:
            if ticker != "nan":
                universe.add(ticker)

        return universe

    def build_membership_matrix(
        self, start: str, end: str, freq: str = "ME"
    ) -> pd.DataFrame:
        """
        Build a boolean DataFrame: index=month-end dates, columns=tickers.
        True means the ticker was in the S&P 500 on that date.
        Useful for masking signals in the tournament.
        """
        dates = pd.date_range(start, end, freq=freq)
        universe = sorted(self.universe_for_period(start, end))
        rows = {}
        for dt in dates:
            members = self.members_on(dt)
            rows[dt] = {t: (t in members) for t in universe}

        df = pd.DataFrame(rows).T
        df.index.name = "date"
        return df

    def filter_signal(
        self, signal: pd.DataFrame, date: pd.Timestamp
    ) -> pd.DataFrame:
        """Zero out signal for tickers not in the S&P 500 on `date`."""
        members = self.members_on(date)
        invalid = [c for c in signal.columns if c not in members and c != "SPY"]
        if invalid:
            signal = signal.copy()
            signal[invalid] = 0
        return signal

    def coverage_report(self, start: str = "2006-01-01", end: str = "2025-12-31") -> dict:
        """Summary statistics about the composition data quality."""
        changes_in_period = self._changes[
            (self._changes["date"] >= pd.Timestamp(start))
            & (self._changes["date"] <= pd.Timestamp(end))
        ]
        return {
            "total_changes": len(changes_in_period),
            "earliest_change": str(self._changes["date"].min().date()),
            "latest_change": str(self._changes["date"].max().date()),
            "unique_tickers_ever": len(self.universe_for_period(start, end)),
            "current_members": len(self._current),
        }
