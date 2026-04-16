"""
scrape_ycharts.py

Playwright-based YCharts Professional scraper.
Collects the maximum available data set on every run:

  - Full US Treasury yield curve  (1M  30Y + real yields + Fed Funds + SOFR)
  - Economic indicators            (CPI, Core CPI, PCE, Core PCE, Unemployment,
                                    GDP, Initial Claims, ISM Mfg, ISM Services,
                                    Consumer Confidence, PPI, Retail Sales)
  - Portfolio fund risk metrics    (Sharpe, Sortino, Alpha, Beta, MaxDD, StdDev,
                                    VaR, Expense Ratio, AUM, Dividend Yield,
                                    1Y / 3Y / 5Y returns, Up/Down Capture)

Output  data/ycharts_live.json

Called from:
  monitor.py  (before generate_market_commentary.py)
  data_arbiter.py reads this file and merges with yfinance/OpenBB data.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
ROOT       = Path(__file__).resolve().parent
CREDS_FILE = ROOT / "config" / "ycharts_creds.json"  # legacy fallback only
OUT_FILE   = ROOT / "data" / "ycharts_live.json"
TODAY_STR  = datetime.today().strftime("%Y-%m-%d")

YCHARTS_BASE = "https://ycharts.com"
LOGIN_URL    = f"{YCHARTS_BASE}/login"

# ---------------------------------------------------------------------------
# Yield curve  YCharts indicator slugs
# ---------------------------------------------------------------------------
YIELD_CURVE_INDICATORS: dict[str, str] = {
    "1M":        "1_month_treasury_rate",
    "3M":        "3_month_treasury_rate",
    "6M":        "6_month_treasury_rate",
    "1Y":        "1_year_treasury_rate",
    "2Y":        "2_year_treasury_rate",
    "3Y":        "3_year_treasury_rate",
    "5Y":        "5_year_treasury_rate",
    "7Y":        "7_year_treasury_rate",
    "10Y":       "10_year_treasury_rate",
    "20Y":       "20_year_treasury_rate",
    "30Y":       "30_year_treasury_rate",
    "10s2s":     "10_2_year_treasury_yield_spread",
    "Breakeven_10Y": "10_year_breakeven_inflation_rate",
    "Fed_Funds": "effective_federal_funds_rate",
    "SOFR":      "sofr",
}

# ---------------------------------------------------------------------------
# Economic indicators
# ---------------------------------------------------------------------------
ECONOMIC_INDICATORS: dict[str, str] = {
    "CPI_YoY":           "us_inflation_rate",
    "Core_CPI_YoY":      "us_core_inflation_rate",
    "PCE_YoY":           "us_pce_price_index_yoy",
    "Core_PCE_YoY":      "us_core_pce_price_index_yoy",
    "Unemployment":      "us_unemployment_rate",
    "GDP_Growth":        "us_real_gdp_growth",
    "Initial_Claims":    "us_initial_claims_for_unemployment_insurance",
    "ISM_Manufacturing": "us_pmi",
    "Consumer_Sentiment":"us_consumer_sentiment_index",
    "PPI_YoY":           "us_producer_price_index_yoy",
    "Retail_Sales_MoM":  "us_retail_sales_mom",
    "Housing_Starts":    "housing_starts",
    "Nonfarm_Payrolls":  "us_change_in_nonfarm_payrolls",
    "Fed_Funds":         "effective_federal_funds_rate",
}

# ---------------------------------------------------------------------------
# Risk metric rows to extract from fund/ETF pages (row text  output key)
# ---------------------------------------------------------------------------
RISK_ROW_MAP: dict[str, str] = {
    "Alpha (3Y)":                                                  "alpha_3y",
    "Beta (3Y)":                                                   "beta_3y",
    "Annualized Standard Deviation of Monthly Returns (3Y Lookback)": "std_dev_3y",
    "Historical Sharpe Ratio (3Y)":                                "sharpe_3y",
    "Historical Sortino (3Y)":                                     "sortino_3y",
    "Max Drawdown (3Y)":                                           "max_drawdown_3y",
    "Monthly Value at Risk (VaR) 5% (3Y Lookback)":               "var_5pct_3y",
}

KEY_STAT_ROW_MAP: dict[str, str] = {
    "Net Expense Ratio":                          "expense_ratio",
    "Total Assets Under Management":              "aum",
    "Dividend Yield":                             "dividend_yield",
    "Turnover Ratio":                             "turnover_ratio",
    "1 Year Total Returns (Daily)":               "return_1y",
    "1 Month Total Returns (Daily)":              "return_1m",
    "Year to Date Total Returns (Daily)":         "return_ytd",
    "Max Drawdown (Since Inception)":             "max_drawdown_inception",
    "30-Day SEC Yield":                           "sec_yield_30d",
    # --- P/E: fund pages use "Weighted Average PE Ratio", company pages use "PE Ratio" ---
    "Weighted Average PE Ratio":                  "pe_ratio",
    "PE Ratio":                                   "pe_ratio",
    # --- ROE: fund pages use "Weighted Median ROE", company pages use "Return on Equity" ---
    "Weighted Median ROE":                        "roe",
    "Return on Equity":                           "roe",
}

PERFORMANCE_ROW_MAP: dict[str, str] = {
    "1 Month Total Return":    "return_1m",
    "3 Month Total Return":    "return_3m",
    "YTD Total Return":        "return_ytd",
    "1 Year Total Return":     "return_1y",
    "3 Year Annualized Total Return":  "return_3y_ann",
    "5 Year Annualized Total Return":  "return_5y_ann",
    "Since Inception Annualized Total Return": "return_inception_ann",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_creds() -> dict[str, str]:
    user = os.environ.get("YCHARTS_USER", "")
    pw   = os.environ.get("YCHARTS_PASS", "")
    if user and pw:
        return {"username": user, "password": pw}
    # Legacy fallback: read from config file (do not store plaintext creds there in production)
    with open(CREDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _clean_value(raw: str) -> Any:
    """Convert a YCharts display string to a Python float or keep as string."""
    if not raw or raw.strip() in ("", "--", "N/A", "n/a"):
        return None
    s = raw.strip()
    # Remove trailing %  store as decimal fraction for consistency
    is_pct = s.endswith("%")
    s = s.replace("%", "").replace(",", "").replace("$", "").replace("B", "e9").replace("M", "e6").replace("T", "e12").strip()
    try:
        v = float(s)
        return v / 100.0 if is_pct else v
    except ValueError:
        return raw.strip()


def _parse_indicator_page(html_text: str) -> dict[str, Any]:
    """
    Extract current value + previous value from an indicator page snapshot YAML.
    Returns {"value": float, "prev_value": float, "date": str, "prev_date": str}
    """
    result: dict[str, Any] = {}
    # The summary line: '- generic [ref=eXX]: 4.42% for Mar 26 2026'
    summary_match = re.search(
        r':\s*([\d.]+%?)\s+for\s+(\w+ \d+[, ]+\d+)', html_text
    )
    if summary_match:
        result["value"] = _clean_value(summary_match.group(1))
        result["date"]  = summary_match.group(2).strip()

    # Historical table: first two rows give current + previous
    rows = re.findall(
        r'row "(\w+ \d+, \d+) ([\d.]+%?)"', html_text
    )
    if rows:
        if len(rows) > 0:
            result["value"]      = _clean_value(rows[0][1])
            result["date"]       = rows[0][0]
        if len(rows) > 1:
            result["prev_value"] = _clean_value(rows[1][1])
            result["prev_date"]  = rows[1][0]
    return result


def _parse_risk_table(snapshot_yaml: str) -> dict[str, Any]:
    """Extract all risk metrics from a fund/ETF page snapshot."""
    metrics: dict[str, Any] = {}

    # Each risk row: 'row "LABEL VALUE"'
    risk_rows = re.findall(r'row "([^"]+)" \[ref=', snapshot_yaml)
    for row_text in risk_rows:
        for label, key in {**RISK_ROW_MAP, **KEY_STAT_ROW_MAP, **PERFORMANCE_ROW_MAP}.items():
            if row_text.startswith(label):
                value_str = row_text[len(label):].strip()
                metrics[key] = _clean_value(value_str)
                break
    return metrics


def _snapshot_text(page) -> str:
    """Read the most recent .playwright-cli snapshot YAML as text."""
    snap_dir = ROOT / ".playwright-cli"
    yamls = sorted(snap_dir.glob("page-*.yml"), key=lambda p: p.stat().st_mtime)
    if not yamls:
        return ""
    return yamls[-1].read_text(encoding="utf-8", errors="ignore")


# Column positions within chart-data-row value cells (index 0 = first value after label)
# Returns rows: [1M, 3M, YTD, 1Y, 3Y_ann, 5Y_ann, 10Y, SI]
_RETURN_ROW_COLS = [
    (0, "return_1m"),
    (1, "return_3m"),
    (2, "return_ytd"),
    (3, "return_1y"),
    (4, "return_3y_ann"),
    (5, "return_5y_ann"),
]
# Capture rows: [1Y, 3Y, 5Y, ...]
_CAPTURE_COL_3Y = 1


def _scrape_chart_data_rows(page) -> dict[str, Any]:
    """
    Parse div.chart-data-row elements on the YCharts performance sub-page.
    Returns fund returns (from 'Total Return (NAV)' or 'Total Return (Price)')
    and capture ratios (from 'Capture Ratio', 'Upside', 'Downside').
    """
    result: dict[str, Any] = {}
    rows: dict[str, list[str]] = {}

    for row_el in page.query_selector_all("div.chart-data-row"):
        try:
            children = row_el.evaluate(
                "el => [...el.children].map(c => c.innerText.trim())"
            )
            if not children:
                continue
            label = children[0]
            values = children[1:]
            rows[label] = values
        except Exception:
            continue

    # Returns  prefer NAV, fall back to Price
    for label in ("Total Return (NAV)", "Total Return (Price)"):
        if label in rows:
            vals = rows[label]
            for idx, key in _RETURN_ROW_COLS:
                if idx < len(vals):
                    v = _clean_value(vals[idx])
                    if v is not None:
                        result.setdefault(key, v)
            break

    # Capture ratios  3Y is at index _CAPTURE_COL_3Y
    if "Capture Ratio" in rows:
        vals = rows["Capture Ratio"]
        if len(vals) > _CAPTURE_COL_3Y:
            v = _clean_value(vals[_CAPTURE_COL_3Y])
            if v is not None:
                result["updown_ratio"] = v

    if "Upside" in rows:
        vals = rows["Upside"]
        if len(vals) > _CAPTURE_COL_3Y:
            v = _clean_value(vals[_CAPTURE_COL_3Y])
            if v is not None:
                result["up_capture_3y"] = v

    if "Downside" in rows:
        vals = rows["Downside"]
        if len(vals) > _CAPTURE_COL_3Y:
            v = _clean_value(vals[_CAPTURE_COL_3Y])
            if v is not None:
                result["down_capture_3y"] = v

    return result


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------
def _make_browser(pw, headless: bool = True):
    """Launch a fresh Chromium browser with standard settings."""
    browser = pw.chromium.launch(headless=headless)
    ctx = browser.new_context(
        viewport={"width": 1400, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    return browser, ctx


def _login(ctx, creds: dict) -> "Page":
    """Open a fresh page, log in to YCharts, return the authenticated page."""
    page = ctx.new_page()
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.fill('input[name="username"], input[type="email"], [placeholder*="mail"]',
              creds["username"])
    page.fill('input[name="password"], input[type="password"]',
              creds["password"])
    page.click('button[type="submit"], button:has-text("Sign In")')
    page.wait_for_url("**/dashboard/**", timeout=15000)
    return page


def _scrape_indicator_page(page, slug: str) -> dict[str, Any]:
    """Scrape a single YCharts indicator page and return {value, prev_value, date, prev_date}."""
    url = f"{YCHARTS_BASE}/indicators/{slug}"
    page.goto(url, wait_until="networkidle", timeout=30000)
    try:
        page.wait_for_selector("table tbody tr td", timeout=15000)
    except Exception:
        pass

    MONTHS = ["January","February","March","April","May","June",
              "July","August","September","October","November","December"]
    parsed: dict[str, Any] = {}
    for tbl in page.query_selector_all("table"):
        rows = tbl.query_selector_all("tbody tr")
        if not rows:
            continue
        cells0 = rows[0].query_selector_all("td")
        if len(cells0) < 2:
            continue
        date_text = cells0[0].inner_text().strip()
        if not any(m in date_text for m in MONTHS):
            continue
        parsed["date"]  = date_text
        parsed["value"] = _clean_value(cells0[1].inner_text())
        if len(rows) >= 2:
            cells1 = rows[1].query_selector_all("td")
            if len(cells1) >= 2:
                parsed["prev_date"]  = cells1[0].inner_text().strip()
                parsed["prev_value"] = _clean_value(cells1[1].inner_text())
        break
    return parsed


def _scrape_fund(ctx, raw_ticker: str) -> dict[str, Any]:
    """
    Open a fresh page, scrape one fund/ETF, close the page.
    Returns fund_data dict.
    """
    ticker = raw_ticker.upper().strip()
    if raw_ticker.upper().startswith("M:"):
        clean = ticker[2:]
        base_url = f"{YCHARTS_BASE}/mutual_funds/M:{clean}"
    else:
        clean = ticker
        base_url = f"{YCHARTS_BASE}/companies/{clean}"

    page = ctx.new_page()
    try:
        fund_data: dict[str, Any] = {"ticker": clean, "url": base_url}

        # Main page  key stats + risk table
        # Use "load" not "networkidle"  fund pages have persistent background XHR
        page.goto(base_url, wait_until="load", timeout=45000)
        page.wait_for_timeout(3000)  # let JS render tables after DOM load

        price_el = page.query_selector("span.index-rank-value")
        if price_el:
            fund_data["price"] = _clean_value(price_el.inner_text())

        all_maps = {**RISK_ROW_MAP, **KEY_STAT_ROW_MAP}
        for tbl in page.query_selector_all("table"):
            rows = tbl.query_selector_all("tr")
            pending_labels: list[str] = []  # for 4-cell multi-label rows
            for row in rows:
                cells = row.query_selector_all("td, th")
                if len(cells) < 2:
                    pending_labels = []
                    continue
                cell_texts = [c.inner_text().strip() for c in cells]

                # 4-cell rows on fund/ETF pages use a label-row / value-row pattern:
                #   Row N:   [label1, label2, label3, label4]  <- all non-numeric strings
                #   Row N+1: [value1, value2, value3, value4]  <- numeric / pct values
                # Detect label rows by: all 4 cells are non-numeric strings AND
                # at least one cell text is a known label key.
                if len(cells) == 4:
                    all_non_numeric = all(
                        not isinstance(_clean_value(t), (int, float))
                        for t in cell_texts
                    )
                    if all_non_numeric and any(t in all_maps for t in cell_texts):
                        # It's a header row  save and pair with next row
                        pending_labels = cell_texts
                        continue
                    if pending_labels:
                        # This row follows a label row  pair as values
                        for lbl, val in zip(pending_labels, cell_texts):
                            for ycharts_label, key in all_maps.items():
                                if lbl == ycharts_label:
                                    v = _clean_value(val)
                                    if v is not None:
                                        fund_data[key] = v
                        pending_labels = []
                        continue
                    pending_labels = []
                else:
                    pending_labels = []

                # Standard 2-cell pattern: [label, value]
                lbl = cell_texts[0]
                val = cell_texts[-1]
                for ycharts_label, key in RISK_ROW_MAP.items():
                    if lbl == ycharts_label:
                        fund_data[key] = _clean_value(val)
                for ycharts_label, key in KEY_STAT_ROW_MAP.items():
                    if lbl == ycharts_label:
                        # Only accept if value is numeric (not another label string)
                        v = _clean_value(val)
                        if isinstance(v, (int, float)):
                            fund_data[key] = v

        # Performance sub-page  returns and capture ratios live in
        # div.chart-data-row elements (not tables) on this page.
        perf_url = base_url + "/performance"
        page.goto(perf_url, wait_until="load", timeout=45000)
        try:
            page.wait_for_selector("div.chart-data-row", timeout=10000)
        except Exception:
            pass  # company pages (MAG7) don't have these; continue anyway

        chart_metrics = _scrape_chart_data_rows(page)
        fund_data.update(chart_metrics)

        # Also try table-based parsing for any performance rows that appear
        # in standard tables (e.g. on company overview pages).
        for tbl in page.query_selector_all("table"):
            for row in tbl.query_selector_all("tr"):
                cells = row.query_selector_all("td, th")
                if len(cells) < 2:
                    continue
                lbl = cells[0].inner_text().strip()
                val = cells[-1].inner_text().strip()
                for ycharts_label, key in PERFORMANCE_ROW_MAP.items():
                    if ycharts_label in lbl:
                        fund_data.setdefault(key, _clean_value(val))

        return fund_data

    except Exception as e:
        return {"ticker": clean, "url": base_url, "error": str(e)}
    finally:
        try:
            page.close()
        except Exception:
            pass


def run_scraper() -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[YCharts] playwright not installed  pip install playwright && playwright install chromium")
        return {}

    creds = _load_creds()
    results: dict[str, Any] = {
        "scrape_date":   TODAY_STR,
        "scrape_ts":     datetime.now().isoformat(),
        "yield_curve":   {},
        "economic":      {},
        "funds":         {},
    }

    import json as _json
    _cfg_path = ROOT / "config" / "portfolio_funds.json"
    with open(_cfg_path) as _f:
        portfolio_tickers = _json.load(_f).get("portfolio_ycharts_symbols", [])

    with sync_playwright() as pw:
        # ------------------------------------------------------------------ #
        # Session 1: yield curve + economic indicators
        # ------------------------------------------------------------------ #
        print("[YCharts] Session 1: indicators...")
        browser1, ctx1 = _make_browser(pw)
        try:
            print("[YCharts] Logging in (session 1)...")
            page = _login(ctx1, creds)
            print("[YCharts] Login successful.")

            print("[YCharts] Scraping yield curve...")
            for label, slug in YIELD_CURVE_INDICATORS.items():
                try:
                    parsed = _scrape_indicator_page(page, slug)
                    results["yield_curve"][label] = parsed
                    print(f"  {label:15s} {parsed.get('value','?')} ({parsed.get('date','?')})")
                except Exception as e:
                    print(f"  [WARN] {label}: {e}")
                    results["yield_curve"][label] = {}

            print("[YCharts] Scraping economic indicators...")
            for label, slug in ECONOMIC_INDICATORS.items():
                try:
                    parsed = _scrape_indicator_page(page, slug)
                    results["economic"][label] = parsed
                    print(f"  {label:25s} {parsed.get('value','?')} ({parsed.get('date','?')})")
                except Exception as e:
                    print(f"  [WARN] {label}: {e}")
                    results["economic"][label] = {}
        finally:
            try:
                browser1.close()
            except Exception:
                pass

        # Save partial results so we have yield/economic even if funds fail
        OUT_FILE.parent.mkdir(exist_ok=True)
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        print("[YCharts] Partial save after indicators.")

        # ------------------------------------------------------------------ #
        # Session 2: fund risk metrics (fresh browser to avoid OOM crashes)
        # ------------------------------------------------------------------ #
        print("[YCharts] Session 2: fund metrics...")
        browser2, ctx2 = _make_browser(pw)
        try:
            print("[YCharts] Logging in (session 2)...")
            _login(ctx2, creds)
            print("[YCharts] Login successful.")

            print("[YCharts] Scraping fund risk metrics...")
            for raw_ticker in portfolio_tickers:
                clean_key = raw_ticker.upper().replace("M:", "").strip()
                try:
                    fund_data = _scrape_fund(ctx2, raw_ticker)
                    results["funds"][clean_key] = fund_data
                    sharpe = fund_data.get("sharpe_3y", "?")
                    mdd    = fund_data.get("max_drawdown_3y", "?")
                    ret1m  = fund_data.get("return_1m", "?")
                    err    = fund_data.get("error", "")
                    if err:
                        print(f"  [WARN] {clean_key:8s}  {err[:80]}")
                    else:
                        print(f"  {clean_key:8s}  sharpe={sharpe}  mdd={mdd}  1m={ret1m}")
                except Exception as e:
                    print(f"  [WARN] {clean_key}: {e}")
                    results["funds"][clean_key] = {"ticker": clean_key, "error": str(e)}
        finally:
            try:
                browser2.close()
            except Exception:
                pass

    # ---------------------------------------------------------------------- #
    # 5. Write output
    # ---------------------------------------------------------------------- #
    OUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n[YCharts] Saved -> {OUT_FILE}")
    print(f"  Yield curve:  {len(results['yield_curve'])} indicators")
    print(f"  Economic:     {len(results['economic'])} indicators")
    print(f"  Funds:        {len(results['funds'])} tickers")
    return results


if __name__ == "__main__":
    run_scraper()
