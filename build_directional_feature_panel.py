"""
Build a research panel of directional feature candidates for DL experiments.

This script intentionally does not change production DL inputs. It backfills
candidate features from OHLCV and optional Alpha Vantage earnings data so they
can be tested before being promoted into the daily training panel.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from quant_cup.data_loader import load_prices
from quant_cup.data_loader import load_earnings as load_earnings_yahoo
from quant_cup.earnings_av import cache_status, load_earnings_av
from quant_cup.earnings_fmp import cache_status as fmp_cache_status
from quant_cup.earnings_fmp import load_earnings_fmp
from quant_cup.models.gap_continuation import gap_features
from quant_cup.models.momentum import momentum_features
from quant_cup.models.overnight import overnight_features
from quant_cup.models.pead import pead_features
from quant_cup.models.vol_compression import vol_compression_features

log = logging.getLogger(__name__)

DEFAULT_TICKERS = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]
EARNINGS_TICKER_ALIASES = {"GOOG": "GOOGL"}
POST_EARNINGS_WINDOW_DAYS = 21


def _load_dotenv_key(key: str, env_path: Path = Path(".env")) -> str:
    if os.environ.get(key):
        return os.environ[key]
    if not env_path.exists():
        return ""
    for line in env_path.read_text(errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            return value.strip().strip("\"'")
    return ""


def _stack_features(feature_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    records = []
    for name, frame in feature_frames.items():
        if frame is None or frame.empty:
            continue
        stacked = frame.stack(future_stack=True).rename(name)
        records.append(stacked)
    if not records:
        return pd.DataFrame(columns=["Date", "Ticker"])
    panel = pd.concat(records, axis=1)
    panel.index.names = ["Date", "Ticker"]
    return panel.reset_index()


def _merge_base_panel(features: pd.DataFrame, base_panel_path: Path) -> pd.DataFrame:
    if not base_panel_path.exists():
        log.warning("Base panel not found: %s", base_panel_path)
        return features

    base = pd.read_parquet(base_panel_path)
    if "Date" not in base.columns or "Ticker" not in base.columns:
        log.warning("Base panel missing Date/Ticker columns: %s", base_panel_path)
        return features

    base = base.copy()
    base["Date"] = pd.to_datetime(base["Date"])
    features = features.copy()
    features["Date"] = pd.to_datetime(features["Date"])
    return base.merge(features, on=["Date", "Ticker"], how="left")


def _earnings_event_features(
    earnings_df: pd.DataFrame,
    prices: pd.DataFrame,
    feature_frames: dict[str, pd.DataFrame],
    window_days: int = POST_EARNINGS_WINDOW_DAYS,
) -> dict[str, pd.DataFrame]:
    """Build research-only event features from point-in-time earnings rows."""
    required_cols = {"ticker", "surprisePercent"}
    if earnings_df.empty or not required_cols.issubset(earnings_df.columns):
        return {}

    index = prices.index
    columns = prices.columns
    out = {
        "days_since_earnings": pd.DataFrame(np.nan, index=index, columns=columns),
        "post_earnings_window_active": pd.DataFrame(0.0, index=index, columns=columns),
        "earnings_surprise_direction": pd.DataFrame(np.nan, index=index, columns=columns),
        "earnings_abs_surprise": pd.DataFrame(np.nan, index=index, columns=columns),
        "post_earnings_positive_drift_window": pd.DataFrame(0.0, index=index, columns=columns),
        "post_earnings_negative_drift_window": pd.DataFrame(0.0, index=index, columns=columns),
    }

    for ticker, grp in earnings_df.groupby("ticker"):
        if ticker not in columns:
            continue
        grp = grp.sort_index()
        valid = pd.to_numeric(grp["surprisePercent"], errors="coerce").dropna()
        if valid.empty:
            continue

        for date in index:
            past = valid[valid.index <= date]
            if past.empty:
                continue
            event_date = past.index[-1]
            surprise = float(past.iloc[-1])
            days_since = int((pd.Timestamp(date) - pd.Timestamp(event_date)).days)
            active = 1.0 if 0 <= days_since <= int(window_days) else 0.0

            out["days_since_earnings"].at[date, ticker] = days_since
            out["post_earnings_window_active"].at[date, ticker] = active
            out["earnings_surprise_direction"].at[date, ticker] = float(np.sign(surprise))
            out["earnings_abs_surprise"].at[date, ticker] = abs(surprise)
            if active and surprise > 0:
                out["post_earnings_positive_drift_window"].at[date, ticker] = 1.0
            if active and surprise < 0:
                out["post_earnings_negative_drift_window"].at[date, ticker] = 1.0

    surprise_last = feature_frames.get("earnings_surprise_last")
    if surprise_last is None:
        surprise_last = out["earnings_surprise_direction"] * out["earnings_abs_surprise"]

    atr_regime = feature_frames.get("atr_percentile")
    if atr_regime is not None:
        out["earnings_surprise_x_atr_regime"] = surprise_last * atr_regime

    gap_count = feature_frames.get("gap_5d_count")
    if gap_count is not None:
        out["earnings_surprise_x_gap_count"] = surprise_last * gap_count

    return out


def build_directional_feature_panel(
    tickers: list[str],
    start: str,
    end: str,
    tier: int,
    include_earnings: bool,
    download_earnings: bool,
    earnings_source: str,
    force_refresh_prices: bool,
    merge_base: bool,
    base_panel_path: Path,
) -> pd.DataFrame:
    prices = load_prices(
        start=start,
        end=end,
        force_refresh=force_refresh_prices,
        include_spy=False,
        tickers=tickers,
    )
    close = prices["close"]
    available = [ticker for ticker in tickers if ticker in close.columns]
    if not available:
        raise RuntimeError("No requested tickers were available in downloaded price data.")

    close = close[available]
    extra = {
        name: frame[available]
        for name, frame in prices.items()
        if name != "close" and frame is not None and not frame.empty
    }

    feature_frames: dict[str, pd.DataFrame] = {}
    feature_frames.update(momentum_features(close))
    feature_frames.update(overnight_features(close, prices_extra=extra))

    if tier >= 2:
        feature_frames.update(vol_compression_features(close, prices_extra=extra))
        feature_frames.update(gap_features(close, prices_extra=extra))

    if include_earnings:
        earnings_tickers = [EARNINGS_TICKER_ALIASES.get(ticker, ticker) for ticker in available]
        alias_back = {source: target for target, source in EARNINGS_TICKER_ALIASES.items()}
        if earnings_source == "fmp":
            api_key = _load_dotenv_key("FMP_API_KEY") if download_earnings else ""
            earnings = load_earnings_fmp(
                tickers=earnings_tickers,
                api_key=api_key,
                start=start,
                end=end,
                force_refresh=False,
            )
        elif earnings_source == "yahoo":
            earnings = load_earnings_yahoo(tickers=earnings_tickers, force_refresh=download_earnings)
            if not earnings.empty:
                earnings = earnings[
                    (earnings.index >= pd.Timestamp(start)) & (earnings.index <= pd.Timestamp(end))
                ]
        else:
            api_key = _load_dotenv_key("AV_API_KEY") if download_earnings else ""
            earnings = load_earnings_av(
                tickers=earnings_tickers,
                api_key=api_key,
                start=start,
                end=end,
                force_refresh=False,
            )
        if not earnings.empty and "ticker" in earnings.columns:
            earnings = earnings.copy()
            earnings["ticker"] = earnings["ticker"].replace(alias_back)
        if not earnings.empty:
            feature_frames.update(pead_features(earnings, close))
            feature_frames.update(_earnings_event_features(earnings, close, feature_frames))
        else:
            status = fmp_cache_status(earnings_tickers) if earnings_source == "fmp" else cache_status(earnings_tickers)
            log.warning(
                "No %s earnings records loaded. Cache status: %s",
                earnings_source.upper(),
                status,
            )

    features = _stack_features(feature_frames)
    if merge_base:
        return _merge_base_panel(features, base_panel_path)
    return features


def _print_summary(panel: pd.DataFrame, output: Path) -> None:
    feature_cols = [
        col
        for col in panel.columns
        if col not in {"Date", "Ticker", "Target_Forward_21D"}
    ]
    directional_cols = [
        col
        for col in feature_cols
        if col.startswith(("momentum_", "overnight_", "intraday_", "atr_", "hv_", "vol_", "gap_", "earnings_"))
        or col.startswith(("days_since_earnings", "post_earnings_"))
    ]
    print(f"Saved {len(panel):,} rows to {output}")
    print(f"Directional candidate features: {len(directional_cols)}")
    for col in directional_cols:
        completeness = panel[col].notna().mean() * 100
        print(f"  {col:<28} {completeness:>5.1f}% non-null")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Backfill directional feature candidates for DL research.")
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2026-05-05")
    parser.add_argument("--tier", type=int, default=2, choices=[1, 2])
    parser.add_argument("--include-earnings", action="store_true")
    parser.add_argument("--download-earnings", action="store_true")
    parser.add_argument(
        "--earnings-source",
        choices=["av", "fmp", "yahoo"],
        default="av",
        help="Earnings surprise source for PEAD features. Yahoo is short-history only.",
    )
    parser.add_argument(
        "--force-refresh-prices",
        action="store_true",
        help=(
            "Refresh shared Quant Cup OHLCV cache. Do not use with a ticker subset "
            "unless --allow-shared-cache-overwrite is also supplied."
        ),
    )
    parser.add_argument(
        "--allow-shared-cache-overwrite",
        action="store_true",
        help="Explicitly allow overwriting shared quant_cup/data/prices_*.parquet caches.",
    )
    parser.add_argument("--merge-base", action="store_true")
    parser.add_argument("--base-panel", default="data/training_panel.parquet")
    parser.add_argument("--output", default="data/experiment/directional_feature_panel.parquet")
    parser.add_argument("--csv-output", default="")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    requested = [ticker.upper() for ticker in args.tickers]
    if args.force_refresh_prices and not args.allow_shared_cache_overwrite:
        raise SystemExit(
            "--force-refresh-prices writes to shared quant_cup/data/prices_*.parquet caches. "
            "Re-run without force refresh, or add --allow-shared-cache-overwrite only when "
            "refreshing the full intended cache universe."
        )

    panel = build_directional_feature_panel(
        tickers=requested,
        start=args.start,
        end=args.end,
        tier=args.tier,
        include_earnings=args.include_earnings or args.download_earnings,
        download_earnings=args.download_earnings,
        earnings_source=args.earnings_source,
        force_refresh_prices=args.force_refresh_prices,
        merge_base=args.merge_base,
        base_panel_path=Path(args.base_panel),
    )

    panel.to_parquet(output, index=False)
    if args.csv_output:
        csv_output = Path(args.csv_output)
        csv_output.parent.mkdir(parents=True, exist_ok=True)
        panel.to_csv(csv_output, index=False)
    _print_summary(panel, output)


if __name__ == "__main__":
    main()
