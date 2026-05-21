"""Patch the local Quant Cup OHLCV cache for the growth24 research universe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

from quant_cup import data_loader


FIELD_TO_CACHE = {
    "Close": data_loader.PRICES_CLOSE_FILE,
    "Open": data_loader.PRICES_OPEN_FILE,
    "High": data_loader.PRICES_HIGH_FILE,
    "Low": data_loader.PRICES_LOW_FILE,
    "Volume": data_loader.PRICES_VOLUME_FILE,
}


def _load_tickers(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("tickers")
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a top-level 'tickers' list.")
    seen = set()
    tickers: list[str] = []
    for value in raw:
        ticker = str(value).upper().strip()
        if ticker and ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    if not tickers:
        raise ValueError(f"{path} did not contain any usable tickers.")
    return tickers


def _download_ohlcv(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    raw = yf.download(
        tickers,
        start=start,
        end=(pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no price data.")

    out: dict[str, pd.DataFrame] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for field in FIELD_TO_CACHE:
            if field in raw.columns.get_level_values(0):
                frame = raw[field].copy()
                frame.columns = [str(col).upper() for col in frame.columns]
                out[field] = frame
    else:
        if len(tickers) != 1:
            raise RuntimeError("Expected MultiIndex columns for multi-ticker yfinance download.")
        ticker = tickers[0]
        for field in FIELD_TO_CACHE:
            if field in raw.columns:
                out[field] = raw[[field]].rename(columns={field: ticker})

    for field in FIELD_TO_CACHE:
        if field not in out:
            raise RuntimeError(f"Downloaded data did not include {field}.")
        out[field].index = pd.to_datetime(out[field].index)
    return out


def _merge_cache(cache_file: Path, downloaded: pd.DataFrame, tickers: list[str]) -> tuple[int, pd.Timestamp, pd.Timestamp]:
    if cache_file.exists():
        cached = pd.read_parquet(cache_file)
        cached.index = pd.to_datetime(cached.index)
    else:
        cached = pd.DataFrame()

    downloaded = downloaded.reindex(columns=tickers)
    merged = cached.reindex(index=cached.index.union(downloaded.index), columns=cached.columns.union(downloaded.columns))
    merged.update(downloaded)
    merged = merged.sort_index().loc[~merged.index.duplicated(keep="last")]
    merged.to_parquet(cache_file)

    valid = downloaded.notna().sum()
    missing = valid[valid == 0].index.tolist()
    if missing:
        print(f"Warning: no downloaded values for {cache_file.name}: {','.join(missing)}")
    return int(valid.sum()), merged.index.min(), merged.index.max()


def main() -> None:
    ap = argparse.ArgumentParser(description="Patch Quant Cup OHLCV caches for growth24 tickers.")
    ap.add_argument("--ticker-config", type=Path, default=Path("config/research_growth_universe.json"))
    ap.add_argument("--start", default="2025-12-01")
    ap.add_argument("--end", default="2026-05-12")
    args = ap.parse_args()

    tickers = _load_tickers(args.ticker_config)
    downloaded = _download_ohlcv(tickers, args.start, args.end)
    print(f"Downloaded {len(tickers)} tickers for {args.start} -> {args.end}")
    for field, cache_file in FIELD_TO_CACHE.items():
        values, min_date, max_date = _merge_cache(cache_file, downloaded[field], tickers)
        print(f"Patched {field:<6} values={values:,} cache_range={min_date.date()} -> {max_date.date()}")


if __name__ == "__main__":
    main()
