"""
Quant Model Cup — Data Loader
Downloads S&P 500 constituents and 20 years of OHLCV from Yahoo Finance.
All data is cached locally as parquet files to avoid re-downloading.
"""

from __future__ import annotations

import io
import logging
import time
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

_WIKI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "data"
CACHE_DIR.mkdir(exist_ok=True)

SP500_TICKERS_FILE = CACHE_DIR / "sp500_tickers.csv"
PRICES_CLOSE_FILE = CACHE_DIR / "prices_close.parquet"
PRICES_OPEN_FILE = CACHE_DIR / "prices_open.parquet"
PRICES_HIGH_FILE = CACHE_DIR / "prices_high.parquet"
PRICES_LOW_FILE = CACHE_DIR / "prices_low.parquet"
PRICES_VOLUME_FILE = CACHE_DIR / "prices_volume.parquet"
EARNINGS_FILE = CACHE_DIR / "earnings.parquet"

# yfinance batch size — too large causes silent failures
BATCH_SIZE = 50


def get_sp500_tickers(force_refresh: bool = False) -> list[str]:
    """Pull current S&P 500 tickers from Wikipedia. Cached locally."""
    if SP500_TICKERS_FILE.exists() and not force_refresh:
        return pd.read_csv(SP500_TICKERS_FILE)["Symbol"].tolist()

    log.info("Fetching S&P 500 ticker list from Wikipedia...")
    sp500 = _fetch_sp500_table()
    tickers = sp500["Symbol"].tolist()
    sp500.to_csv(SP500_TICKERS_FILE, index=False)
    log.info(f"Saved {len(tickers)} tickers to {SP500_TICKERS_FILE}")
    return tickers


def get_sp500_with_sectors(force_refresh: bool = False) -> pd.DataFrame:
    """Return DataFrame with Symbol, Security, GICS Sector columns."""
    if SP500_TICKERS_FILE.exists() and not force_refresh:
        df = pd.read_csv(SP500_TICKERS_FILE)
        if "GICS Sector" in df.columns:
            return df[["Symbol", "Security", "GICS Sector"]].copy()

    sp500 = _fetch_sp500_table()
    sp500.to_csv(SP500_TICKERS_FILE, index=False)
    return sp500[["Symbol", "Security", "GICS Sector"]].copy()


def _fetch_sp500_table() -> pd.DataFrame:
    """Fetch S&P 500 table from Wikipedia with a browser User-Agent to avoid 403."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    resp = requests.get(url, headers=_WIKI_HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    sp500 = tables[0]
    sp500["Symbol"] = sp500["Symbol"].str.replace(".", "-", regex=False)
    return sp500


def _download_batch(
    tickers: list[str],
    start: str,
    end: str,
    field: str,
) -> pd.DataFrame:
    """Download one OHLCV field for a batch of tickers."""
    data = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if isinstance(data.columns, pd.MultiIndex):
        if field in data.columns.get_level_values(0):
            return data[field]
        return pd.DataFrame()
    # Single ticker → flat columns
    if field in data.columns:
        return data[[field]].rename(columns={field: tickers[0]})
    return pd.DataFrame()


def _load_or_download(
    cache_file: Path,
    tickers: list[str],
    start: str,
    end: str,
    field: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    if cache_file.exists() and not force_refresh:
        log.info(f"Loading {field} from cache: {cache_file}")
        df = pd.read_parquet(cache_file)
        df.index = pd.to_datetime(df.index)
        return df

    log.info(f"Downloading {field} for {len(tickers)} tickers ({start} → {end})...")
    frames = []
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i : i + BATCH_SIZE]
        log.info(f"  Batch {i // BATCH_SIZE + 1}/{(len(tickers) - 1) // BATCH_SIZE + 1}")
        try:
            chunk = _download_batch(batch, start, end, field)
            if not chunk.empty:
                frames.append(chunk)
        except Exception as exc:
            log.warning(f"  Batch {batch[:3]}... failed: {exc}")
        time.sleep(0.5)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, axis=1)
    combined = combined.loc[~combined.index.duplicated(keep="first")]
    combined.index = pd.to_datetime(combined.index)
    combined.to_parquet(cache_file)
    log.info(f"Saved {field} data: {combined.shape} → {cache_file}")
    return combined


def load_prices(
    start: str = "2006-01-01",
    end: str = "2025-12-31",
    force_refresh: bool = False,
    include_spy: bool = True,
    tickers: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Returns dict with keys: 'close', 'open', 'high', 'low', 'volume'.
    All DataFrames share the same DatetimeIndex and ticker columns.
    SPY is always included as the benchmark.
    Pass tickers= to override the default current S&P 500 list.
    """
    if tickers is None:
        tickers = get_sp500_tickers(force_refresh=force_refresh)
    if include_spy and "SPY" not in tickers:
        tickers = ["SPY"] + tickers

    result = {}
    for field, cache_file in [
        ("Close", PRICES_CLOSE_FILE),
        ("Open", PRICES_OPEN_FILE),
        ("High", PRICES_HIGH_FILE),
        ("Low", PRICES_LOW_FILE),
        ("Volume", PRICES_VOLUME_FILE),
    ]:
        df = _load_or_download(cache_file, tickers, start, end, field, force_refresh)
        result[field.lower()] = df

    return result


def load_earnings(
    tickers: list[str] | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch earnings history (epsEstimate, epsActual, surprisePct) from yfinance.

    NOTE: yfinance earnings_history only covers ~8 quarters per stock.
    This limits PEAD backtesting to approximately the last 2 years.
    For a full 2006-2025 backtest, Sharadar SFPO (Nasdaq Data Link) provides
    complete point-in-time earnings history.
    """
    if EARNINGS_FILE.exists() and not force_refresh:
        df = pd.read_parquet(EARNINGS_FILE)
        df.index = pd.to_datetime(df.index)
        return df

    if tickers is None:
        tickers = get_sp500_tickers()

    log.info(f"Fetching earnings history for {len(tickers)} tickers...")
    records = []
    for i, t in enumerate(tickers):
        if i % 50 == 0:
            log.info(f"  {i}/{len(tickers)}")
        try:
            hist = yf.Ticker(t).earnings_history
            if hist is not None and not hist.empty:
                hist = hist.copy()
                hist["ticker"] = t
                records.append(hist)
        except Exception:
            pass
        time.sleep(0.05)

    if not records:
        return pd.DataFrame()

    combined = pd.concat(records)
    combined.index = pd.to_datetime(combined.index)
    combined = combined.sort_index()
    combined.to_parquet(EARNINGS_FILE)
    return combined
