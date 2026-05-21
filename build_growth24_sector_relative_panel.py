"""Add simple sector-relative research features to a Growth24 panel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_cup.data_loader import get_sp500_with_sectors


DEFAULT_INPUT = Path("data/experiment/dl_research_panels/research_growth_24_price_earnings_av_panel.parquet")
DEFAULT_OUTPUT = Path("data/experiment/dl_research_panels/research_growth_24_price_earnings_av_sector_panel.parquet")
DEFAULT_TICKER_CONFIG = Path("config/research_growth_universe.json")


def _load_tickers(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [str(t).upper().strip() for t in data["tickers"] if str(t).strip()]


def _sector_map(tickers: list[str]) -> dict[str, str]:
    sectors = get_sp500_with_sectors()
    mapping = dict(zip(sectors["Symbol"].astype(str), sectors["GICS Sector"].astype(str)))
    missing = sorted(set(tickers) - set(mapping))
    if missing:
        raise RuntimeError(f"Missing sector labels for: {missing}")
    return {ticker: mapping[ticker] for ticker in tickers}


def add_sector_relative_features(panel: pd.DataFrame, sectors: dict[str, str]) -> pd.DataFrame:
    out = panel.copy()
    out["Ticker"] = out["Ticker"].astype(str).str.upper().str.strip()
    out["Sector"] = out["Ticker"].map(sectors)
    if out["Sector"].isna().any():
        missing = sorted(out.loc[out["Sector"].isna(), "Ticker"].dropna().unique())
        raise RuntimeError(f"Panel tickers missing sector labels: {missing}")

    source_cols = [
        "Ret_5D",
        "Ret_21D",
        "Ret_63D",
        "Vol_21D",
        "Vol_63D",
        "momentum_3_1",
        "momentum_6_1",
        "momentum_12_1",
        "atr_percentile",
        "hv_percentile",
    ]
    available = [col for col in source_cols if col in out.columns]
    grouped = out.groupby(["Date", "Sector"], sort=False)
    for col in available:
        sector_col = f"Sector_{col}"
        rel_col = f"SectorRel_{col}"
        out[sector_col] = grouped[col].transform("median")
        out[rel_col] = pd.to_numeric(out[col], errors="coerce") - pd.to_numeric(out[sector_col], errors="coerce")

    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Add sector-relative Growth24 research features.")
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--ticker-config", type=Path, default=DEFAULT_TICKER_CONFIG)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    tickers = _load_tickers(args.ticker_config)
    panel = pd.read_parquet(args.input)
    out = add_sector_relative_features(panel, _sector_map(tickers))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, index=False)

    added = [col for col in out.columns if col.startswith(("Sector_", "SectorRel_"))]
    print(f"Saved {len(out):,} rows -> {args.output}")
    print(f"Added sector labels and {len(added)} sector-relative columns.")
    print("Sectors:")
    for sector, count in out[["Ticker", "Sector"]].drop_duplicates()["Sector"].value_counts().sort_index().items():
        print(f"  {sector}: {count}")


if __name__ == "__main__":
    main()
