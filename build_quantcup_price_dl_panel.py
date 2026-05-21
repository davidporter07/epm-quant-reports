"""Build an older price-first DL panel from the local Quant Cup OHLCV cache."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_directional_feature_panel import (
    DEFAULT_TICKERS,
    build_directional_feature_panel,
)
from deep_learning_model import TARGET_COL
from quant_cup.data_loader import load_prices


DEFAULT_OUTPUT = Path("data/experiment/directional_feature_panel_quantcup_price.parquet")
PRICE_EXTRA_FEATURES = (
    "momentum_12_1,momentum_6_1,momentum_3_1,overnight_return_5d,"
    "intraday_return_5d,overnight_return_20d,intraday_return_20d,"
    "atr_percentile,hv_percentile,vol_regime,gap_magnitude_5d,gap_5d_count"
)
MARKET_EXTRA_FEATURES = (
    "Market_Ret_5D,Market_Ret_21D,Market_Ret_63D,Market_Vol_21D,"
    "Market_Vol_63D,Market_Drawdown_63D,Market_Drawdown_252D,"
    "Market_Stress_Regime,Rel_Ret_5D,Rel_Ret_21D,Rel_Ret_63D"
)


def _load_tickers_from_config(path: Path) -> list[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tickers = data.get("tickers")
    if not isinstance(tickers, list):
        raise ValueError(f"{path} must contain a top-level 'tickers' list.")
    seen = set()
    out: list[str] = []
    for value in tickers:
        ticker = str(value).upper().strip()
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    if not out:
        raise ValueError(f"{path} did not provide any usable tickers.")
    return out


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _market_feature_frame(close: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    usable = close[[ticker for ticker in tickers if ticker in close.columns]].apply(pd.to_numeric, errors="coerce")
    if "SPY" in close.columns and close["SPY"].last_valid_index() == close.index.max():
        market = pd.to_numeric(close["SPY"], errors="coerce")
    else:
        market = usable.median(axis=1)

    market_ret_1d = market.pct_change(1, fill_method=None)
    out = pd.DataFrame(index=close.index)
    out["Market_Ret_5D"] = market.pct_change(5, fill_method=None)
    out["Market_Ret_21D"] = market.pct_change(21, fill_method=None)
    out["Market_Ret_63D"] = market.pct_change(63, fill_method=None)
    out["Market_Vol_21D"] = market_ret_1d.rolling(21).std() * np.sqrt(252)
    out["Market_Vol_63D"] = market_ret_1d.rolling(63).std() * np.sqrt(252)
    out["Market_Drawdown_63D"] = (market / market.rolling(63).max()) - 1.0
    out["Market_Drawdown_252D"] = (market / market.rolling(252).max()) - 1.0
    out["Market_Stress_Regime"] = (
        (out["Market_Drawdown_63D"] <= -0.08)
        | (out["Market_Drawdown_252D"] <= -0.15)
        | (out["Market_Vol_21D"] >= out["Market_Vol_21D"].rolling(252, min_periods=63).quantile(0.80))
    ).astype(float)
    out["Market_Forward_21D"] = market.shift(-21) / market - 1.0
    return out


def _base_panel_from_prices(
    prices: dict[str, pd.DataFrame],
    tickers: list[str],
    start: str,
    end: str,
    target_mode: str,
) -> pd.DataFrame:
    close = prices["close"].copy()
    volume = prices.get("volume", pd.DataFrame(index=close.index, columns=close.columns)).copy()
    close.index = pd.to_datetime(close.index)
    volume.index = pd.to_datetime(volume.index)
    close = close[(close.index >= pd.Timestamp(start)) & (close.index <= pd.Timestamp(end))]
    volume = volume[(volume.index >= pd.Timestamp(start)) & (volume.index <= pd.Timestamp(end))]
    market_features = _market_feature_frame(close, tickers)
    close = close[[ticker for ticker in tickers if ticker in close.columns]]
    volume = volume.reindex(index=close.index, columns=close.columns)

    rows = []
    for ticker in close.columns:
        frame = pd.DataFrame(
            {
                "Date": close.index,
                "Close": pd.to_numeric(close[ticker], errors="coerce"),
                "Volume": pd.to_numeric(volume[ticker], errors="coerce"),
                "Ticker": ticker,
            }
        )
        frame["Ret_1D"] = frame["Close"].pct_change(1)
        frame["Ret_5D"] = frame["Close"].pct_change(5)
        frame["Ret_21D"] = frame["Close"].pct_change(21)
        frame["Ret_63D"] = frame["Close"].pct_change(63)
        frame["Ret_252D"] = frame["Close"].pct_change(252)
        frame["Vol_21D"] = frame["Ret_1D"].rolling(21).std() * np.sqrt(252)
        frame["Vol_63D"] = frame["Ret_1D"].rolling(63).std() * np.sqrt(252)
        frame["MA_20"] = frame["Close"].rolling(20).mean()
        frame["MA_50"] = frame["Close"].rolling(50).mean()
        frame["MA_200"] = frame["Close"].rolling(200).mean()
        frame["Gap_MA20"] = (frame["Close"] / frame["MA_20"]) - 1.0
        frame["Gap_MA50"] = (frame["Close"] / frame["MA_50"]) - 1.0
        frame["Gap_MA200"] = (frame["Close"] / frame["MA_200"]) - 1.0
        frame["RSI_14"] = _rsi(frame["Close"])
        frame["Raw_Target_Forward_21D"] = frame["Close"].shift(-21) / frame["Close"] - 1.0
        for col in market_features.columns:
            frame[col] = market_features[col].to_numpy()
        frame["Rel_Ret_5D"] = frame["Ret_5D"] - frame["Market_Ret_5D"]
        frame["Rel_Ret_21D"] = frame["Ret_21D"] - frame["Market_Ret_21D"]
        frame["Rel_Ret_63D"] = frame["Ret_63D"] - frame["Market_Ret_63D"]
        if target_mode == "excess":
            frame[TARGET_COL] = frame["Raw_Target_Forward_21D"] - frame["Market_Forward_21D"]
        else:
            frame[TARGET_COL] = frame["Raw_Target_Forward_21D"]
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def build_panel(
    tickers: list[str],
    start: str,
    end: str,
    include_earnings: bool,
    earnings_source: str,
    target_mode: str,
) -> pd.DataFrame:
    prices = load_prices(
        start=start,
        end=end,
        force_refresh=False,
        include_spy=False,
        tickers=tickers,
    )
    base = _base_panel_from_prices(prices, tickers, start, end, target_mode)
    feature_panel = build_directional_feature_panel(
        tickers=tickers,
        start=start,
        end=end,
        tier=2,
        include_earnings=include_earnings,
        download_earnings=False,
        earnings_source=earnings_source,
        force_refresh_prices=False,
        merge_base=False,
        base_panel_path=Path(""),
    )
    out = base.merge(feature_panel, on=["Date", "Ticker"], how="left")
    out = out.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    return out


def _print_summary(panel: pd.DataFrame, output: Path) -> None:
    labeled = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()]
    print(f"Saved {len(panel):,} rows -> {output}")
    print(f"Panel range: {panel['Date'].min().date()} -> {panel['Date'].max().date()}")
    print(f"Labeled range: {labeled['Date'].min().date()} -> {labeled['Date'].max().date()}")
    for ticker, group in panel.groupby("Ticker"):
        label_count = int(pd.to_numeric(group[TARGET_COL], errors="coerce").notna().sum())
        print(
            f"{ticker}: {group['Date'].min().date()} -> {group['Date'].max().date()} "
            f"rows={len(group)} labeled={label_count}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a Quant Cup price-first DL panel.")
    ap.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    ap.add_argument(
        "--ticker-config",
        type=Path,
        default=None,
        help="JSON config containing a top-level tickers list. Overrides --tickers.",
    )
    ap.add_argument("--start", default="2006-01-03")
    ap.add_argument("--end", default="2026-05-06")
    ap.add_argument("--include-earnings", action="store_true")
    ap.add_argument("--earnings-source", choices=["av", "fmp", "yahoo"], default="fmp")
    ap.add_argument(
        "--target-mode",
        choices=["raw", "excess"],
        default="raw",
        help="Use raw ticker 21D forward return or ticker return minus market 21D forward return.",
    )
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--csv-output", type=Path, default=None)
    args = ap.parse_args()

    if args.ticker_config:
        tickers = _load_tickers_from_config(args.ticker_config)
    else:
        tickers = [ticker.upper().strip() for ticker in args.tickers if ticker.strip()]
    panel = build_panel(
        tickers,
        args.start,
        args.end,
        bool(args.include_earnings),
        args.earnings_source,
        args.target_mode,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(args.output, index=False)
    if args.csv_output:
        args.csv_output.parent.mkdir(parents=True, exist_ok=True)
        panel.to_csv(args.csv_output, index=False)
    _print_summary(panel, args.output)


if __name__ == "__main__":
    main()
