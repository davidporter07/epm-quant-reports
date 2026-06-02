"""
data_arbiter.py

Merges YCharts scraped data with yfinance/OpenBB data and selects
the best (most complete, most recent, most authoritative) value for
each metric used by generate_market_commentary.py and generate_pdf_report.py.

Priority rules (highest  lowest):
  1. YCharts   professional-grade, direct from source, refreshed daily
  2. Treasury.gov XML  official for yield levels only
  3. yfinance  broad coverage, free, occasionally stale for mutual funds

Output:  data/market_data_arbitrated.json
         data/features_from_ycharts.csv   (built from YCharts scraper data)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

ROOT     = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

YCHARTS_LIVE  = DATA_DIR / "ycharts_live.json"
ARBITRATED    = DATA_DIR / "market_data_arbitrated.json"
YCHARTS_CSV   = DATA_DIR / "features_from_ycharts.csv"
YCHARTS_BAK   = DATA_DIR / "features_from_ycharts.last_good.csv"

TODAY_STR = datetime.today().strftime("%Y-%m-%d")

# Acceptable staleness for YCharts data (if scrape ran today it's fresh)
MAX_STALE_DAYS = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _is_fresh(scrape_date: str) -> bool:
    try:
        d = datetime.strptime(scrape_date, "%Y-%m-%d")
        return (datetime.today() - d).days <= MAX_STALE_DAYS
    except Exception:
        return False


def _best(ycharts_val: Any, fallback_val: Any) -> Any:
    """Return YCharts value if it is non-None, else fallback."""
    if ycharts_val is not None and ycharts_val != "" and str(ycharts_val).strip() not in ("--", "N/A"):
        return ycharts_val
    return fallback_val


def _pct_to_float(v: Any) -> float | None:
    """Normalise a percentage value to a Python float (e.g. 4.42  4.42, 0.0442  4.42)."""
    try:
        f = float(v)
        # If stored as decimal fraction (< 0.5 for yield, < 1 for returns) scale up
        return f
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 1. Build arbitrated yield curve
# ---------------------------------------------------------------------------
def _arbitrate_yields(yc_live: dict, yf_bonds: dict) -> dict:
    """
    Merge YCharts full yield curve with yfinance bond data.
    Returns a dict keyed by human-readable label.
    """
    # YCharts label  report label
    label_map = {
        "1M":  "1-Month Yield",
        "3M":  "3-Month Yield",
        "6M":  "6-Month Yield",
        "1Y":  "1-Year Yield",
        "2Y":  "2-Year Yield",
        "3Y":  "3-Year Yield",
        "5Y":  "5-Year Yield",
        "7Y":  "7-Year Yield",
        "10Y": "10-Year Yield",
        "20Y": "20-Year Yield",
        "30Y": "30-Year Yield",
        "10s2s":         "10s-2s Spread",
        "Breakeven_10Y": "10Y Breakeven Inflation",
        "Fed_Funds":     "Fed Funds Rate",
        "SOFR":          "SOFR",
    }

    result = {}
    for yc_key, report_label in label_map.items():
        yc_entry  = yc_live.get(yc_key, {})
        yc_level  = yc_entry.get("value")
        yc_prev   = yc_entry.get("prev_value")

        # Fallback: matching entry from yfinance bonds dict
        yf_entry  = yf_bonds.get(report_label, {})
        yf_level  = yf_entry.get("level")
        yf_prev   = None  # yfinance doesn't usually give prev for yields

        level = _best(yc_level, yf_level)
        prev  = _best(yc_prev, yf_prev)

        if level is None:
            continue

        # Percentage values from YCharts come as decimal fraction (e.g. 0.0442 = 4.42%)
        # Normalise: if level < 0.5 assume it's already a decimal fraction, scale to pct
        try:
            lv = float(level)
            if lv < 0.5 and "Spread" not in report_label:
                lv = lv * 100
            level = round(lv, 4)
        except Exception:
            pass

        entry: dict[str, Any] = {"level": level, "source": "ycharts" if yc_level else "yfinance"}

        if prev is not None:
            try:
                pv = float(prev)
                if pv < 0.5 and "Spread" not in report_label:
                    pv = pv * 100
                change     = round(level - pv, 4)
                pct_change = round(change / pv * 100, 2) if pv else None
                entry["change"]     = change
                entry["pct_change"] = pct_change
                entry["prev_value"] = round(pv, 4)
            except Exception:
                pass

        result[report_label] = entry

    return result


# ---------------------------------------------------------------------------
# 2. Build arbitrated economic snapshot
# ---------------------------------------------------------------------------
def _arbitrate_economics(econ_live: dict) -> dict:
    result = {}
    label_map = {
        "CPI_YoY":           "CPI (YoY)",
        "Core_CPI_YoY":      "Core CPI (YoY)",
        "PCE_YoY":           "PCE (YoY)",
        "Core_PCE_YoY":      "Core PCE (YoY)",
        "Unemployment":      "Unemployment Rate",
        "GDP_Growth":        "GDP Growth (QoQ)",
        "Initial_Claims":    "Initial Jobless Claims",
        "ISM_Manufacturing":  "ISM Manufacturing PMI",
        "Consumer_Sentiment": "Consumer Sentiment",
        "PPI_YoY":           "PPI (YoY)",
        "Retail_Sales_MoM":  "Retail Sales (MoM)",
        "Housing_Starts":    "Housing Starts",
        "Nonfarm_Payrolls":  "Nonfarm Payrolls",
        "Fed_Funds":         "Fed Funds Rate",
    }
    for yc_key, report_label in label_map.items():
        entry = econ_live.get(yc_key, {})
        if not entry or entry.get("value") is None:
            continue
        result[report_label] = {
            "value":      entry.get("value"),
            "prev_value": entry.get("prev_value"),
            "date":       entry.get("date"),
            "source":     "ycharts",
        }
    return result


# ---------------------------------------------------------------------------
# 2b. FRED fallback — used when YCharts indicator scraping is empty/stale
# ---------------------------------------------------------------------------
_FRED_YIELD_SERIES: dict[str, str] = {
    "1M":            "DGS1MO",
    "3M":            "DGS3MO",
    "6M":            "DGS6MO",
    "1Y":            "DGS1",
    "2Y":            "DGS2",
    "3Y":            "DGS3",
    "5Y":            "DGS5",
    "7Y":            "DGS7",
    "10Y":           "DGS10",
    "20Y":           "DGS20",
    "30Y":           "DGS30",
    "10s2s":         "T10Y2Y",
    "Breakeven_10Y": "T10YIE",
    "Fed_Funds":     "DFF",
    "SOFR":          "SOFR",
}

_FRED_ECON_SERIES: dict[str, tuple[str, dict]] = {
    "CPI_YoY":           ("CPIAUCSL",         {"units": "pc1"}),
    "Core_CPI_YoY":      ("CPILFESL",         {"units": "pc1"}),
    "PCE_YoY":           ("PCEPI",            {"units": "pc1"}),
    "Core_PCE_YoY":      ("PCEPILFE",         {"units": "pc1"}),
    "Unemployment":      ("UNRATE",           {}),
    "GDP_Growth":        ("A191RL1Q225SBEA",  {}),
    "Initial_Claims":    ("ICSA",             {}),
    "Consumer_Sentiment":("UMCSENT",          {}),
    "PPI_YoY":           ("PPIACO",           {"units": "pc1"}),
    "Retail_Sales_MoM":  ("RSXFS",            {"units": "pch"}),
    "Nonfarm_Payrolls":  ("PAYEMS",           {"units": "chg"}),
    "Fed_Funds":         ("DFEDTARU",         {}),
}

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def _fred_api_key() -> str:
    try:
        from epm_secrets import FRED_API_KEY  # type: ignore[import]
        return FRED_API_KEY or ""
    except Exception:
        return ""


def _fred_fetch_series(series_id: str, extra: dict, api_key: str) -> dict:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "sort_order": "desc",
        "limit": 2,
        "file_type": "json",
        "observation_end": TODAY_STR,
        **extra,
    }
    r = requests.get(_FRED_BASE, params=params, timeout=10)
    r.raise_for_status()
    obs = [o for o in r.json().get("observations", [])
           if o.get("value") not in (".", None, "")]
    if not obs:
        return {}
    result: dict[str, Any] = {
        "value": float(obs[0]["value"]),
        "date":  obs[0]["date"],
    }
    if len(obs) > 1:
        result["prev_value"] = float(obs[1]["value"])
        result["prev_date"]  = obs[1]["date"]
    return result


def _fetch_fred_yield_curve() -> dict[str, Any]:
    api_key = _fred_api_key()
    if not api_key:
        return {}
    result: dict[str, Any] = {}
    for label, series_id in _FRED_YIELD_SERIES.items():
        try:
            entry = _fred_fetch_series(series_id, {}, api_key)
            if entry:
                result[label] = entry
        except Exception as exc:
            print(f"  [FRED yield] {series_id}: {exc}")
    print(f"[Arbiter/FRED] Yield curve: {len(result)}/{len(_FRED_YIELD_SERIES)} tenors")
    return result


def _fetch_fred_economics() -> dict[str, Any]:
    api_key = _fred_api_key()
    if not api_key:
        return {}
    result: dict[str, Any] = {}
    for label, (series_id, extra) in _FRED_ECON_SERIES.items():
        try:
            entry = _fred_fetch_series(series_id, extra, api_key)
            if entry:
                result[label] = entry
        except Exception as exc:
            print(f"  [FRED econ] {series_id}: {exc}")
    print(f"[Arbiter/FRED] Economics: {len(result)}/{len(_FRED_ECON_SERIES)} indicators")
    return result


# ---------------------------------------------------------------------------
# 3. Build features_from_ycharts.csv from YCharts scraper data
# ---------------------------------------------------------------------------

# Scraper JSON key  CSV column name (must match forecast_common.py / features.py)
SCRAPER_TO_CSV: dict[str, str] = {
    "price":           "Price",
    "pe_ratio":        "P/E Ratio",
    "roe":             "ROE",
    "max_drawdown_3y": "Max Drawdown 3Y",
    "sharpe_3y":       "Sharpe (3Y)",
    "alpha_3y":        "Alpha (3Y)",
    "beta_3y":         "Beta (3Y)",
    "std_dev_3y":      "Standard Deviation 3Y",
    "updown_ratio":    "Up/Down Ratio",
    "sortino_3y":      "Sortino (3Y)",
    "var_5pct_3y":     "VaR 5% (3Y)",
    "expense_ratio":   "Expense Ratio",
    "aum":             "AUM",
    "dividend_yield":  "Dividend Yield",
    "return_1m":       "1M Return",
    "return_3m":       "3M Return",
    "return_ytd":      "YTD Return",
    "return_1y":       "1Y Return",
    "return_3y_ann":   "3Y Ann Return",
    "return_5y_ann":   "5Y Ann Return",
}

_CSV_COL_ORDER = ["Ticker"] + list(SCRAPER_TO_CSV.values())


def _build_features_csv(funds_live: dict) -> None:
    """
    Build features_from_ycharts.csv entirely from ycharts_live.json funds data.
    Replaces the former Excel-based workflow.
    """
    import shutil

    rows = []
    for raw_ticker, fund_data in funds_live.items():
        if fund_data.get("error"):
            continue
        ticker = raw_ticker.upper().strip()
        row: dict[str, Any] = {"Ticker": ticker}
        for yc_key, csv_col in SCRAPER_TO_CSV.items():
            v = fund_data.get(yc_key)
            if v is not None:
                if yc_key == "max_drawdown_3y":
                    try:
                        v = abs(float(v))
                    except Exception:
                        pass
                row[csv_col] = v
        rows.append(row)

    if not rows:
        print("[Arbiter] No fund data  features_from_ycharts.csv not written")
        return

    df = pd.DataFrame(rows)
    for col in _CSV_COL_ORDER:
        if col not in df.columns:
            df[col] = float("nan")
    df = df[_CSV_COL_ORDER]

    if YCHARTS_CSV.exists():
        shutil.copy(YCHARTS_CSV, YCHARTS_BAK)

    df.to_csv(YCHARTS_CSV, index=False)
    print(f"[Arbiter] Built features_from_ycharts.csv  {len(df)} tickers")


# ---------------------------------------------------------------------------
# 4. Main arbitration entry point
# ---------------------------------------------------------------------------
def run_arbitration(yf_commentary: dict | None = None) -> dict:
    """
    Load YCharts live data, merge with yfinance commentary data,
    write arbitrated output, and update features CSV.

    yf_commentary: optional dict from generate_market_commentary.py
                   containing yfinance-sourced bonds_table, etc.
    """
    live = _load_json(YCHARTS_LIVE)
    yc_fresh = bool(live) and _is_fresh(live.get("scrape_date", ""))

    if not live:
        print("[Arbiter] YCharts data missing — yield/econ via FRED fallback")
        live = {}
    elif not yc_fresh:
        print(f"[Arbiter] YCharts stale ({live.get('scrape_date','?')}) — yield/econ via FRED fallback")

    yf_bonds = {}
    if yf_commentary and "bonds_table" in yf_commentary:
        yf_bonds = yf_commentary["bonds_table"]

    # Use YCharts yield/econ only when fresh; fall back to FRED otherwise.
    # Check for actual data content, not just key presence (empty {} = failed scrape).
    yc_yields = live.get("yield_curve", {}) if yc_fresh else {}
    yc_econ   = live.get("economic", {})    if yc_fresh else {}
    yc_yields_populated = any(v for v in yc_yields.values() if isinstance(v, dict) and v)
    yc_econ_populated   = any(v for v in yc_econ.values()   if isinstance(v, dict) and v)

    if not yc_yields_populated:
        fred_yields = _fetch_fred_yield_curve()
        merged_yields = {**fred_yields, **{k: v for k, v in yc_yields.items() if v}}
    else:
        merged_yields = yc_yields

    if not yc_econ_populated:
        fred_econ = _fetch_fred_economics()
        merged_econ = {**fred_econ, **{k: v for k, v in yc_econ.items() if v}}
    else:
        merged_econ = yc_econ

    arbitrated: dict[str, Any] = {
        "arbitrated_date":   TODAY_STR,
        "ycharts_scrape_ts": live.get("scrape_ts"),
        "yield_curve":       _arbitrate_yields(merged_yields, yf_bonds),
        "economics":         _arbitrate_economics(merged_econ),
    }

    # Build features CSV from scraper funds data. Fund risk metrics (Sharpe/alpha/beta/
    # MaxDD) come ONLY from YCharts, so there is no fallback — but if the scrape is stale
    # these freeze (the 2026-05-08 freeze sat undetected for weeks). Warn LOUDLY so the
    # staleness is visible; the 1M return is separately refreshed from yfinance in
    # features.enrich_features_with_missing_metrics and consumed via _fresh_1m_col().
    if live.get("funds"):
        if not yc_fresh:
            _scr = live.get("scrape_date", "?")
            try:
                _age_d = (datetime.now() - datetime.strptime(_scr, "%Y-%m-%d")).days
                _age_s = f"{_age_d} days"
            except Exception:
                _age_s = "unknown age"
            print("[Arbiter] " + "!" * 56)
            print(f"[Arbiter] STALE FUND METRICS: building features_from_ycharts.csv from a "
                  f"YCharts scrape dated {_scr} ({_age_s} old).")
            print("[Arbiter] Price / returns / Sharpe / alpha / beta / MaxDD are FROZEN. "
                  "Fix the scraper (playwright) to refresh.")
            print("[Arbiter] " + "!" * 56)
        _build_features_csv(live["funds"])

    with open(ARBITRATED, "w", encoding="utf-8") as f:
        json.dump(arbitrated, f, indent=2, default=str)

    print(f"[Arbiter] Saved -> {ARBITRATED}")
    print(f"  Yield curve entries:  {len(arbitrated['yield_curve'])}")
    print(f"  Economic entries:     {len(arbitrated['economics'])}")
    return arbitrated


if __name__ == "__main__":
    result = run_arbitration()
    print(json.dumps(result, indent=2))
