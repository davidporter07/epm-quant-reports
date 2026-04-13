"""build_training_dataset.py

Creates a historical *panel* dataset suitable for real ML / deep learning.

Output: data/training_panel.parquet
Schema (typical):
  Date, Ticker, Close, Volume, <feature columns...>, Target_Forward_21D

Notes
-----
- Uses yfinance for price history.
- Designed to be safe to run repeatedly: it rewrites the output file.
- Universe helper 'sp500' uses multiple sources + caching to avoid HTTP 403 issues.

Examples
--------
# MAG7 only (quick)
python build_training_dataset.py --universe mag7 --years 6

# S&P 500 (more data; slower)
python build_training_dataset.py --universe sp500 --years 8 --batch-size 40

# Custom tickers
python build_training_dataset.py --tickers AAPL,MSFT,AMZN --years 6
"""

from __future__ import annotations

import argparse
import io
import time
import urllib.request
from pathlib import Path
from typing import Iterable, List, Optional

import numpy as np
import pandas as pd


def _try_import_yf():
    try:
        import yfinance as yf  # type: ignore
        return yf
    except Exception as e:
        raise RuntimeError("yfinance is required. Install with: pip install yfinance") from e


MAG7_DEFAULT = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]


def _chunks(xs: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def _fetch_text(url: str, timeout: int = 20) -> str:
    """Fetch URL text with a browser-like User-Agent to reduce 403 blocks."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    # wikipedia pages sometimes include odd bytes; ignore decode errors
    return data.decode("utf-8", errors="ignore")


def _normalize_yf_ticker(t: str) -> str:
    """Convert common index ticker formats to yfinance-compatible tickers."""
    t = str(t).strip().upper()
    # Wikipedia uses dots for class shares, yfinance uses dashes
    t = t.replace(".", "-")
    return t


def get_sp500_tickers(
    cache_path: str | Path = Path("data") / "sp500_tickers_cache.csv",
    max_cache_age_days: int = 30,
) -> List[str]:
    """Best-effort S&P 500 list using multiple sources + a local cache.

    Tries (in order):
      1) Local cache (if fresh)
      2) Wikipedia HTML (with custom User-Agent)
      3) GitHub 'datasets/s-and-p-500-companies' CSV

    Returns
    -------
    List[str]
      yfinance-compatible tickers
    """
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # 1) Use fresh cache when available
    if cache_path.exists():
        age_days = (time.time() - cache_path.stat().st_mtime) / (60 * 60 * 24)
        if age_days <= max_cache_age_days:
            df = pd.read_csv(cache_path)
            if "Symbol" in df.columns:
                tickers = df["Symbol"].astype(str).tolist()
            else:
                tickers = df.iloc[:, 0].astype(str).tolist()
            tickers = [_normalize_yf_ticker(t) for t in tickers if str(t).strip()]
            tickers = sorted(set(tickers))
            if tickers:
                return tickers

    # Helper to save cache
    def _save_cache(tickers: List[str]) -> None:
        pd.DataFrame({"Symbol": tickers}).to_csv(cache_path, index=False)

    # 2) Wikipedia (common but sometimes blocks; UA helps)
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        html = _fetch_text(url)
        tables = pd.read_html(io.StringIO(html))
        df = tables[0]
        tickers = df["Symbol"].astype(str).tolist()
        tickers = [_normalize_yf_ticker(t) for t in tickers if str(t).strip()]
        tickers = sorted(set(tickers))
        if len(tickers) >= 400:
            _save_cache(tickers)
            print(f" Pulled {len(tickers)} S&P 500 tickers from Wikipedia (cached).")
            return tickers
        raise RuntimeError("Wikipedia parse returned too few tickers.")
    except Exception as e:
        print(f" Wikipedia S&P 500 fetch failed: {e}")

    # 3) GitHub dataset (often more reliable than Wikipedia)
    try:
        url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
        csv_text = _fetch_text(url)
        df = pd.read_csv(io.StringIO(csv_text))
        col = "Symbol" if "Symbol" in df.columns else ("symbol" if "symbol" in df.columns else None)
        if col is None:
            raise RuntimeError("Could not find Symbol column in GitHub CSV.")
        tickers = df[col].astype(str).tolist()
        tickers = [_normalize_yf_ticker(t) for t in tickers if str(t).strip()]
        tickers = sorted(set(tickers))
        if len(tickers) >= 400:
            _save_cache(tickers)
            print(f" Pulled {len(tickers)} S&P 500 tickers from GitHub (cached).")
            return tickers
        raise RuntimeError("GitHub parse returned too few tickers.")
    except Exception as e:
        print(f" GitHub S&P 500 fetch failed: {e}")

    # Final fallback: use stale cache if it exists
    if cache_path.exists():
        df = pd.read_csv(cache_path)
        tickers = df["Symbol"].astype(str).tolist() if "Symbol" in df.columns else df.iloc[:, 0].astype(str).tolist()
        tickers = [_normalize_yf_ticker(t) for t in tickers if str(t).strip()]
        tickers = sorted(set(tickers))
        if tickers:
            print(f" Using stale cached S&P 500 tickers ({len(tickers)}).")
            return tickers

    raise RuntimeError("Failed to fetch S&P 500 tickers and no cache was available.")


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / (avg_loss.replace(0, np.nan))
    return 100 - (100 / (1 + rs))


def compute_features(df: pd.DataFrame, horizon: int = 21) -> pd.DataFrame:
    """Compute a standard set of technical features for one ticker."""
    out = df.copy()
    close = out["Close"]

    # Returns
    out["Ret_1D"] = close.pct_change(1)
    out["Ret_5D"] = close.pct_change(5)
    out["Ret_21D"] = close.pct_change(21)
    out["Ret_63D"] = close.pct_change(63)
    out["Ret_252D"] = close.pct_change(252)

    # Volatility (annualized)
    out["Vol_21D"] = close.pct_change().rolling(21).std() * np.sqrt(252)
    out["Vol_63D"] = close.pct_change().rolling(63).std() * np.sqrt(252)

    # Moving averages + gaps
    out["MA_20"] = close.rolling(20).mean()
    out["MA_50"] = close.rolling(50).mean()
    out["MA_200"] = close.rolling(200).mean()
    out["Gap_MA20"] = (close - out["MA_20"]) / out["MA_20"]
    out["Gap_MA50"] = (close - out["MA_50"]) / out["MA_50"]
    out["Gap_MA200"] = (close - out["MA_200"]) / out["MA_200"]

    # RSI
    out["RSI_14"] = rsi(close, 14)

    # Target
    out["Target_Forward_21D"] = close.shift(-horizon) / close - 1.0

    return out


def _extract_ticker_frame(data: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """Extract Close/Volume series for one ticker from yfinance batch download output."""
    try:
        if isinstance(data.columns, pd.MultiIndex):
            # yfinance can return either (field, ticker) or (ticker, field)
            if ("Close", ticker) in data.columns:
                close = data[("Close", ticker)].rename("Close")
                vol = data[("Volume", ticker)].rename("Volume") if ("Volume", ticker) in data.columns else None
            elif (ticker, "Close") in data.columns:
                close = data[(ticker, "Close")].rename("Close")
                vol = data[(ticker, "Volume")].rename("Volume") if (ticker, "Volume") in data.columns else None
            else:
                # Older yfinance format: data["Close"][ticker]
                close = data["Close"][ticker].rename("Close")
                vol = data["Volume"][ticker].rename("Volume") if "Volume" in data.columns.levels[0] else None
        else:
            # Single ticker output (rare in our batched flow)
            close = data["Close"].rename("Close")
            vol = data["Volume"].rename("Volume") if "Volume" in data.columns else None

        df_t = pd.DataFrame({"Close": close})
        df_t["Volume"] = vol if vol is not None else np.nan
        df_t.index = pd.to_datetime(df_t.index)
        df_t = df_t.dropna(subset=["Close"]).copy()
        return df_t
    except Exception:
        return None


def download_prices_batched(
    tickers: List[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    batch_size: int = 50,
    sleep_s: float = 0.0,
) -> Iterable[tuple[List[str], pd.DataFrame]]:
    """Yield (batch_tickers, data) from yfinance download in manageable batches."""
    yf = _try_import_yf()
    for batch in _chunks(tickers, max(1, int(batch_size))):
        data = yf.download(
            batch,
            start=start,
            end=end,
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            progress=False,
        )
        if data is None or data.empty:
            print(f" No data returned for batch starting with {batch[0]}")
            continue
        yield batch, data
        if sleep_s and sleep_s > 0:
            time.sleep(sleep_s)


def build_panel(
    tickers: List[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    horizon: int = 21,
    batch_size: int = 50,
    sleep_s: float = 0.0,
) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []

    for batch, data in download_prices_batched(
        tickers=tickers,
        start=start,
        end=end,
        batch_size=batch_size,
        sleep_s=sleep_s,
    ):
        for t in batch:
            df_t = _extract_ticker_frame(data, t)
            if df_t is None or df_t.empty:
                continue
            try:
                df_t = compute_features(df_t, horizon=horizon)
                df_t["Ticker"] = t
                df_t = df_t.reset_index().rename(columns={"index": "Date"})
                rows.append(df_t)
            except Exception as e:
                print(f" Skipping {t} due to feature error: {e}")

    if not rows:
        raise RuntimeError("No rows built. Check tickers and data availability.")

    panel = pd.concat(rows, ignore_index=True)

    required = ["Close", "Ret_21D", "Vol_21D", "Gap_MA200", "RSI_14", "Target_Forward_21D"]
    panel = panel.dropna(subset=required)

    return panel


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", type=str, default=",".join(MAG7_DEFAULT))
    p.add_argument(
        "--universe",
        type=str,
        default="",
        choices=["", "mag7", "sp500"],
        help="Optional universe shortcut. Overrides --tickers when set.",
    )
    p.add_argument("--years", type=int, default=6, help="History length in years")
    p.add_argument("--horizon", type=int, default=21, help="Forward horizon in trading days")
    p.add_argument("--batch-size", type=int, default=50, help="yfinance download batch size (reduce if errors)")
    p.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between yfinance batches (rate-limit safety)")
    p.add_argument("--out", type=str, default=str(Path("data") / "training_panel.parquet"))
    args = p.parse_args()

    if args.universe == "mag7":
        tickers = MAG7_DEFAULT
    elif args.universe == "sp500":
        try:
            tickers = get_sp500_tickers()
        except Exception as e:
            print(f" Could not fetch S&P 500 tickers ({e}). Falling back to MAG7.")
            tickers = MAG7_DEFAULT
    else:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    # normalize all tickers for yfinance
    tickers = [_normalize_yf_ticker(t) for t in tickers]
    tickers = [t for t in tickers if t]

    end = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=int(args.years * 365.25))

    print(f" Building panel for {len(tickers)} tickers from {start.date()} to {end.date()}...")

    panel = build_panel(
        tickers,
        start=start,
        end=end,
        horizon=args.horizon,
        batch_size=args.batch_size,
        sleep_s=args.sleep,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        panel.to_parquet(out_path, index=False)
    except Exception:
        csv_out = out_path.with_suffix(".csv")
        panel.to_csv(csv_out, index=False)
        print(f" Parquet write failed; saved CSV instead -> {csv_out}")

    print(f" Saved training panel: {out_path} ({len(panel):,} rows)")
    print(panel.head())


if __name__ == "__main__":
    main()
