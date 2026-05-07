"""Incrementally refresh Quant Cup OHLCV parquet caches.

The existing Quant Cup loader has a force-refresh mode that rewrites the whole
shared cache. This helper is narrower: download only requested tickers for the
missing date range and merge those columns into the existing cache files.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from quant_cup.data_loader import (
    PRICES_CLOSE_FILE,
    PRICES_HIGH_FILE,
    PRICES_LOW_FILE,
    PRICES_OPEN_FILE,
    PRICES_VOLUME_FILE,
)

FIELD_FILES = {
    "Close": PRICES_CLOSE_FILE,
    "Open": PRICES_OPEN_FILE,
    "High": PRICES_HIGH_FILE,
    "Low": PRICES_LOW_FILE,
    "Volume": PRICES_VOLUME_FILE,
}
YFINANCE_CACHE_DIR = Path("data") / ".yfinance_cache"


def _normalize_tickers(raw: str) -> list[str]:
    return [ticker.strip().upper().replace(".", "-") for ticker in raw.split(",") if ticker.strip()]


def _read_cache(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def _download_ohlcv(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))
    except Exception:
        pass
    data = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    out: dict[str, pd.DataFrame] = {}
    if data.empty:
        return out

    if isinstance(data.columns, pd.MultiIndex):
        for field in FIELD_FILES:
            if field in data.columns.get_level_values(0):
                frame = data[field].copy()
                frame.columns = [str(col).upper().replace(".", "-") for col in frame.columns]
                out[field] = frame
    else:
        ticker = tickers[0]
        for field in FIELD_FILES:
            if field in data.columns:
                out[field] = data[[field]].rename(columns={field: ticker})
    return out


def _merge_field(cache: pd.DataFrame, update: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    update = update.copy()
    update.index = pd.to_datetime(update.index)
    wanted = [ticker for ticker in tickers if ticker in update.columns]
    if not wanted:
        return cache

    if cache.empty:
        merged = update[wanted]
    else:
        merged = cache.copy()
        merged = merged.reindex(merged.index.union(update.index)).sort_index()
        for ticker in wanted:
            merged[ticker] = update[ticker].combine_first(merged[ticker] if ticker in merged.columns else pd.Series(index=merged.index, dtype=float))
    return merged.loc[~merged.index.duplicated(keep="last")].sort_index()


def refresh_price_cache(tickers: list[str], start: str | None, end: str) -> dict[str, dict[str, str | int]]:
    close_cache = _read_cache(PRICES_CLOSE_FILE)
    if start is None:
        if close_cache.empty:
            start = "2019-01-01"
        else:
            start = (pd.Timestamp(close_cache.index.max()).date() + timedelta(days=1)).isoformat()

    if pd.Timestamp(start) >= pd.Timestamp(end):
        return {
            field: {"path": str(path), "rows": int(len(_read_cache(path))), "status": "current"}
            for field, path in FIELD_FILES.items()
        }

    downloaded = _download_ohlcv(tickers, start, end)
    if not downloaded:
        raise RuntimeError(f"No yfinance OHLCV rows returned for {tickers} from {start} to {end}")

    summary: dict[str, dict[str, str | int]] = {}
    for field, path in FIELD_FILES.items():
        cache = _read_cache(path)
        if field not in downloaded:
            summary[field] = {"path": str(path), "rows": int(len(cache)), "status": "missing_download"}
            continue
        merged = _merge_field(cache, downloaded[field], tickers)
        path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(path)
        summary[field] = {
            "path": str(path),
            "rows": int(len(merged)),
            "status": "updated",
            "max_date": pd.Timestamp(merged.index.max()).date().isoformat(),
        }
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Incrementally refresh Quant Cup OHLCV caches.")
    ap.add_argument("--tickers", default="AAPL,MSFT,AMZN,NVDA,GOOG,META,TSLA")
    ap.add_argument("--start", default=None, help="Inclusive start date. Defaults to cache max date + 1.")
    ap.add_argument(
        "--end",
        default=(date.today() + timedelta(days=1)).isoformat(),
        help="Exclusive yfinance end date. Defaults to tomorrow.",
    )
    args = ap.parse_args()

    tickers = _normalize_tickers(args.tickers)
    summary = refresh_price_cache(tickers=tickers, start=args.start, end=args.end)
    for field, info in summary.items():
        max_date = info.get("max_date", "")
        print(f"{field:<6} {info['status']:<16} rows={info['rows']} {max_date} {info['path']}")


if __name__ == "__main__":
    main()
