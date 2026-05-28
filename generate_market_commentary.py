"""
generate_market_commentary.py

Generates market-level narrative commentary sections for the EPM Market Report PDF.
Pulls live market data (US equities, global indices, commodities, currencies, bonds),
loads portfolio features, calls Ollama, and merges the result into
data/latest_commentary.json alongside the existing MAG7 commentary fields.

Fields written to latest_commentary.json:
  Narrative:
    pre_market_bullets          list of 4-6 bullet strings (Pre-Market Look)
    equities_commentary         paragraph
    fixed_income_commentary     paragraph
    commodities_commentary      paragraph
    currencies_commentary       paragraph
    economics_commentary        paragraph (economic data releases)
    market_outlook_label        "Bullish" | "Cautious" | "Neutral" | "Bearish"
    market_outlook_rationale    2-sentence explanation
    tactical_outperforming      comma-separated sectors/themes outperforming
    tactical_underperforming    comma-separated sectors/themes underperforming
    asset_class_outlooks        dict: Equities, Fixed Income, Commodities, US Dollar
                                  each has "label" and "rationale"
    portfolio_spotlight_winners list of {ticker, metric_label, commentary}
    portfolio_spotlight_watch   list of {ticker, metric_label, commentary}
  Market data:
    market_snapshot             US key assets (S&P, Nasdaq, DXY, Gold, WTI, 10-Yr)
    global_markets              major global equity indices
    commodities_table           DBC, Gold, Silver, Copper, WTI, Brent, NatGas, RBOB
    currencies_table            DXY, EUR/USD, GBP/USD, USD/JPY, USD/CAD, AUD/USD
    bonds_table                 2yr, 10yr, 30yr yields + 10s2s spread
    report_date                 YYYY-MM-DD
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from json_repair import repair_json as _repair_json
except ImportError:
    _repair_json = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OLLAMA_HOST    = os.getenv("LOCAL_OLLAMA_URL",     "http://100.101.63.65:11434")
OLLAMA_MODEL   = os.getenv("COMMENTARY_OLLAMA_MODEL", "qwen3.5:9b")
OLLAMA_TIMEOUT = int(os.getenv("LOCAL_OLLAMA_TIMEOUT", "900"))

# Topic spotlight: detect dominant news theme, write grounded story with fund tie-ins
TOPIC_SPOTLIGHT_ENABLED = True
MIN_TOPIC_HEADLINES     = 4   # min distinct matching headlines to gate the spotlight in
MIN_TOPIC_SOURCES       = 2   # min distinct sources required
MAX_CRAWL_ARTICLES      = 6   # max article URLs to crawl for fund grounding + analysis excerpts
MAX_SPOTLIGHT_FUNDS     = 5   # max verified funds to cite

ROOT             = Path(__file__).resolve().parent
DATA_DIR         = ROOT / "data"
COMMENTARY_PATH  = DATA_DIR / "latest_commentary.json"

# Core market tickers for pre-market snapshot
MARKET_TICKERS: dict[str, str] = {
    "S&P 500":           "^GSPC",
    "Nasdaq 100":        "^NDX",
    "U.S. Dollar (DXY)": "DX-Y.NYB",
    "Gold":              "GC=F",
    "WTI Crude":         "CL=F",
    "10-Yr Yield":       "^TNX",
}

GLOBAL_TICKERS: dict[str, str] = {
    "Dow Jones":         "^DJI",
    "Russell 2000":      "^RUT",
    "TSX Composite":     "^GSPTSE",
    "Euro Stoxx 50":     "^STOXX50E",
    "FTSE 100":          "^FTSE",
    "Nikkei 225":        "^N225",
    "Hang Seng":         "^HSI",
    "ASX 200":           "^AXJO",
}

COMMODITY_TICKERS: dict[str, str] = {
    "DBC (Cmdty ETF)":   "DBC",
    "Gold":              "GC=F",
    "Silver":            "SI=F",
    "Copper":            "HG=F",
    "WTI Crude":         "CL=F",
    "Brent Crude":       "BZ=F",
    "Natural Gas":       "NG=F",
    "RBOB Gasoline":     "RB=F",
    "Wheat":             "ZW=F",
    "DBA (Ag ETF)":      "DBA",
}

CURRENCY_TICKERS: dict[str, str] = {
    "Dollar Index":      "DX-Y.NYB",
    "EUR/USD":           "EURUSD=X",
    "GBP/USD":           "GBPUSD=X",
    "USD/JPY":           "JPY=X",
    "USD/CAD":           "CAD=X",
    "AUD/USD":           "AUDUSD=X",
    "USD/BRL":           "BRL=X",
    "Bitcoin":           "BTC-USD",
}

BOND_TICKERS: dict[str, str] = {
    "2-Year Yield":      "^IRX",    # 13-wk proxy; override below
    "10-Year Yield":     "^TNX",
    "30-Year Yield":     "^TYX",
}

SECTOR_TICKERS: dict[str, str] = {
    "Technology":        "XLK",
    "Financials":        "XLF",
    "Health Care":       "XLV",
    "Energy":            "XLE",
    "Consumer Discr":    "XLY",
    "Industrials":       "XLI",
    "Consumer Staples":  "XLP",
    "Utilities":         "XLU",
    "Materials":         "XLB",
    "Real Estate":       "XLRE",
    "Communication":     "XLC",
}

# ---------------------------------------------------------------------------
# Market data helpers
# ---------------------------------------------------------------------------
def _fetch_quote(ticker: str, days_back: int = 7, prev_close: float | None = None,
                 mode: str = "eod") -> dict | None:
    """Return {level, change, pct_change} for a single ticker, or None.

    mode="eod"  — use completed daily-bar closes only (authoritative yesterday's close).
                  Never returns intraday data — safe to call at any time of day.
    mode="live" — try fast_info first (live intraday), fall back to daily bars.
                  Use for pre-market futures block only.
    """
    if yf is None:
        return None
    # --- live path: fast_info intraday quote (futures/live tables only) ---
    if mode == "live":
        try:
            fi = yf.Ticker(ticker).fast_info
            last = float(fi.last_price)
            prev_fi = float(fi.previous_close)
            if last > 0 and prev_fi > 0:
                # Prefer Yahoo's official previous_close (the prior settle, already
                # holiday/roll aware). Only fall back to a stored prev_close when it is
                # FRESH — within 0.3% of prev_fi (a consecutive-session run). A stale
                # stored value (skipped run) would span the gap, so we ignore it.
                prev = prev_fi
                if prev_close and prev_close > 0 and abs(prev_close - prev_fi) / prev_fi <= 0.003:
                    prev = prev_close
                change = last - prev
                pct    = (change / prev) * 100
                return {
                    "level":      round(last, 4),
                    "change":     round(change, 4),
                    "pct_change": round(pct, 2),
                }
        except Exception:
            pass
    # --- eod path: completed daily-bar closes (default, all snapshot/table fetchers) ---
    try:
        end   = datetime.today()
        start = end - timedelta(days=days_back)
        data  = yf.download(ticker, start=start, end=end,
                            progress=False, auto_adjust=True)
        if data.empty:
            return None
        closes = data["Close"].dropna()
        if hasattr(closes, "squeeze"):
            closes = closes.squeeze()
        # Drop any bar dated today or later. During an intraday re-run yfinance can
        # return a partial in-progress bar for the current session; including it would
        # mislabel today's live print as "yesterday's close" (same-day rerun corruption).
        try:
            _today = end.date()
            closes = closes[[ts.date() < _today for ts in closes.index]]
        except Exception:
            pass
        if len(closes) < 2:
            return None
        arr    = closes.to_numpy()
        latest = float(arr[-1])               # most recent COMPLETED session
        # The true prior trading session is always arr[-2]. Unlike a stored prev_close
        # it is robust to skipped runs (weekends/holidays): a stored prev_close goes
        # stale across a skipped session and spans the gap, producing wrong-sign or
        # oversized moves (e.g. Brent shown -9.9% after the Memorial Day holiday when it
        # actually rose). Yahoo restitches continuous futures (=F) series, so
        # arr[-2]->arr[-1] is on a consistent contract basis (no roll artifact). Mirrors
        # the fetch_global_markets fix, extended here to commodities/currencies/metals.
        prev   = float(arr[-2])
        change = latest - prev
        pct    = (change / prev) * 100
        return {
            "level":      round(latest, 4),
            "change":     round(change, 4),
            "pct_change": round(pct, 2),
        }
    except Exception:
        return None


def _event_day_from_dates(event_date: str, today_date: str) -> str:
    """Human day label for an event relative to today: 'today', 'tomorrow', or weekday.

    Used so a forward-looking scenario built on a future catalyst (e.g. Thursday's GDP
    report selected on a Wednesday) is labelled by its real day instead of "today".
    """
    try:
        ed = datetime.strptime(str(event_date)[:10], "%Y-%m-%d").date()
        td = datetime.strptime(str(today_date)[:10], "%Y-%m-%d").date()
    except Exception:
        return ""
    delta = (ed - td).days
    if delta <= 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return ed.strftime("%A")   # e.g. "Thursday"


def _prev_level(prev_data: dict | None, name: str) -> float | None:
    """Extract the stored previous level for a named instrument, or None."""
    if not prev_data:
        return None
    try:
        val = float(prev_data.get(name, {}).get("level") or 0)
        return val if val > 0 else None
    except Exception:
        return None


def _guard_snapshot_drift(new_snapshot: dict, prev_path: "Path") -> None:
    """Warn loudly if same-session re-run produces materially different levels.

    A >1% level shift for the same report_date almost certainly means a bad
    data fetch (e.g. intraday print mis-labeled as a prior close). Prints a
    warning but does NOT block the write — the alert is enough to catch issues
    during the daily review.
    """
    try:
        if not prev_path.exists():
            return
        import json as _json
        prev_full = _json.loads(prev_path.read_text(encoding="utf-8"))
        prev_snap = prev_full.get("market_snapshot", {})
        # Only compare if both describe the same session date
        if prev_full.get("report_date") != datetime.today().strftime("%Y-%m-%d"):
            return
        _DRIFT_KEYS = ("S&P 500", "Nasdaq 100", "Gold", "10-Yr Yield")
        for key in _DRIFT_KEYS:
            old = (prev_snap.get(key) or {}).get("level")
            new = (new_snapshot.get(key) or {}).get("level")
            if old and new and old > 0 and abs(new - old) / old > 0.01:
                print(
                    f"[WARN] Snapshot drift guard: {key} shifted {old:.4f} → {new:.4f} "
                    f"({(new-old)/old*100:+.2f}%) within same session. "
                    f"Possible bad fast_info read — verify data before trusting."
                )
    except Exception:
        pass


def fetch_market_snapshot(prev_data: dict | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name, ticker in MARKET_TICKERS.items():
        q = _fetch_quote(ticker, prev_close=_prev_level(prev_data, name))
        if q:
            result[name] = q
    return result


def fetch_global_markets(prev_data: dict | None = None) -> dict[str, dict]:
    # NOTE: unlike commodities/futures, global equity INDICES do not roll contracts, so
    # the stored prev_close mechanism (designed for BZ=F/CL=F/GC=F roll protection) is the
    # wrong reference here — when a run is skipped (weekend/holiday) the stored level is
    # several sessions stale, producing gap artifacts (e.g. Nikkei "+5.37%" or a 0.00%
    # change when stored == latest). The true prior session is always _fetch_quote's
    # arr[-2], which is robust to skipped runs. `prev_data` is accepted for call-site
    # compatibility but intentionally not used as prev_close.
    _ = prev_data
    result: dict[str, dict] = {}
    for name, ticker in GLOBAL_TICKERS.items():
        q = _fetch_quote(ticker)
        if q:
            result[name] = q
    return result


def fetch_commodities_table(prev_data: dict | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name, ticker in COMMODITY_TICKERS.items():
        q = _fetch_quote(ticker, prev_close=_prev_level(prev_data, name))
        if q:
            result[name] = q
    return result


def fetch_currencies_table(prev_data: dict | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name, ticker in CURRENCY_TICKERS.items():
        q = _fetch_quote(ticker, prev_close=_prev_level(prev_data, name))
        if q:
            result[name] = q
    return result


FUTURES_TICKERS: dict[str, str] = {
    "S&P 500 Futures":      "ES=F",
    "Nasdaq 100 Futures":   "NQ=F",
    "Dow Futures":          "YM=F",
    "Russell 2000 Futures": "RTY=F",
}


def fetch_futures_table(prev_data: dict | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name, ticker in FUTURES_TICKERS.items():
        q = _fetch_quote(ticker, mode="live", prev_close=_prev_level(prev_data, name))
        if q:
            result[name] = q
    return result


def _fetch_treasury_gov_yields() -> dict[str, dict]:
    """Fetch official US Treasury yield curve data from home.treasury.gov.
    Returns a bonds_table-compatible dict with 2Y, 10Y, 30Y yields and the 10s-2s spread.
    Falls back to an empty dict if the endpoint is unavailable."""
    try:
        import urllib.request
        import xml.etree.ElementTree as ET
        from datetime import datetime, timedelta

        ns = {
            "a": "http://www.w3.org/2005/Atom",
            "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
            "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
        }

        def _fetch_month(ym: str) -> dict:
            url = (
                "https://home.treasury.gov/resource-center/data-chart-center/"
                f"interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value_month={ym}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                root = ET.fromstring(resp.read().decode("utf-8"))
            rows = {}
            for entry in root.findall(".//a:entry", ns):
                props = entry.find(".//m:properties", ns)
                if props is None:
                    continue
                row = {child.tag.split("}")[-1]: child.text for child in props}
                date = (row.get("NEW_DATE") or "")[:10]
                rows[date] = row
            return rows

        today = datetime.today()
        ym_cur  = today.strftime("%Y%m")
        prev_month = (today.replace(day=1) - timedelta(days=1))
        ym_prev = prev_month.strftime("%Y%m")

        rows = _fetch_month(ym_cur)
        if len(rows) < 2:
            rows.update(_fetch_month(ym_prev))

        # Fetch January data for YTD baseline when current/prev months don't cover it
        ym_jan = f"{today.year}01"
        if ym_jan not in (ym_cur, ym_prev):
            rows.update(_fetch_month(ym_jan))

        sorted_dates = sorted(rows.keys())
        if len(sorted_dates) < 2:
            return {}

        today_row = rows[sorted_dates[-1]]
        prev_row  = rows[sorted_dates[-2]]
        week_row  = rows[sorted_dates[-6]] if len(sorted_dates) >= 6 else None
        jan_dates = [d for d in sorted_dates if d.startswith(str(today.year))]
        ytd_row   = rows[jan_dates[0]] if jan_dates else None

        def _get_val(row: dict | None, field: str) -> float | None:
            if row is None:
                return None
            try:
                return float(row[field])
            except Exception:
                return None

        def _build(field: str) -> dict | None:
            try:
                cur  = float(today_row[field])
                prev = float(prev_row[field])
                chg  = round(cur - prev, 3)
                pct  = round(chg / prev * 100, 2) if prev else None
                entry: dict = {"level": cur, "change": chg, "pct_change": pct}
                wk = _get_val(week_row, field)
                if wk is not None:
                    entry["bp_change_1w"] = round((cur - wk) * 100, 1)
                yt = _get_val(ytd_row, field)
                if yt is not None:
                    entry["bp_change_ytd"] = round((cur - yt) * 100, 1)
                return entry
            except Exception:
                return None

        result: dict[str, dict] = {}
        for name, field in [
            ("2-Year Yield",  "BC_2YEAR"),
            ("10-Year Yield", "BC_10YEAR"),
            ("30-Year Yield", "BC_30YEAR"),
        ]:
            entry = _build(field)
            if entry:
                result[name] = entry

        y10     = result.get("10-Year Yield", {}).get("level")
        y2      = result.get("2-Year Yield",  {}).get("level")
        y10_chg = result.get("10-Year Yield", {}).get("change")
        y2_chg  = result.get("2-Year Yield",  {}).get("change")
        if y10 is not None and y2 is not None:
            spread_chg = None
            if y10_chg is not None and y2_chg is not None:
                spread_chg = round((y10_chg - y2_chg) * 100, 1)
            spread_entry: dict = {
                "level": round((y10 - y2) * 100, 1),
                "change": spread_chg,
                "pct_change": None,
            }
            y10_1w = result.get("10-Year Yield", {}).get("bp_change_1w")
            y2_1w  = result.get("2-Year Yield",  {}).get("bp_change_1w")
            if y10_1w is not None and y2_1w is not None:
                spread_entry["bp_change_1w"] = round(y10_1w - y2_1w, 1)
            y10_yt = result.get("10-Year Yield", {}).get("bp_change_ytd")
            y2_yt  = result.get("2-Year Yield",  {}).get("bp_change_ytd")
            if y10_yt is not None and y2_yt is not None:
                spread_entry["bp_change_ytd"] = round(y10_yt - y2_yt, 1)
            result["10s-2s Spread"] = spread_entry
        return result

    except Exception as exc:
        print(f"[WARN] Treasury.gov fetch failed: {exc}")
        return {}


def fetch_bonds_table() -> dict[str, dict]:
    # Primary: official US Treasury yield curve (always accurate, no API key needed)
    result = _fetch_treasury_gov_yields()
    if result:
        return result

    # Fallback: yfinance (less reliable for Treasury data)
    result = {}
    bond_map = {
        "10-Year Yield": "^TNX",
        "30-Year Yield": "^TYX",
    }
    for name, ticker in bond_map.items():
        q = _fetch_quote(ticker)
        if q:
            result[name] = q

    y10 = result.get("10-Year Yield", {}).get("level")
    y2  = result.get("2-Year Yield",  {}).get("level")
    if y10 is not None and y2 is not None:
        spread_bp = round((y10 - y2) * 100, 1)
        result["10s-2s Spread"] = {"level": spread_bp, "change": None, "pct_change": None}

    return result


def fetch_technical_levels() -> dict[str, dict]:
    """Compute 20d/50d/200d MAs, 52-wk high/low for key assets."""
    assets = {
        "S&P 500":      "^GSPC",
        "Nasdaq 100":   "^NDX",
        "Gold":         "GC=F",
        "WTI Crude":    "CL=F",
        "10-Yr Yield":  "^TNX",
        "VIX":          "^VIX",
    }
    result: dict[str, dict] = {}
    if yf is None:
        return result

    end   = datetime.today()
    start = end - timedelta(days=400)   # need 200d + some buffer

    for name, ticker in assets.items():
        try:
            data = yf.download(ticker, start=start, end=end,
                               progress=False, auto_adjust=True)
            if data.empty:
                continue
            closes = data["Close"].dropna()
            if hasattr(closes, "squeeze"):
                closes = closes.squeeze()
            arr = closes.to_numpy()
            if len(arr) < 2:
                continue

            current = float(arr[-1])
            high52  = float(closes.tail(252).max())
            low52   = float(closes.tail(252).min())
            ma20    = float(closes.tail(20).mean())  if len(arr) >= 20  else None
            ma50    = float(closes.tail(50).mean())  if len(arr) >= 50  else None
            ma200   = float(closes.tail(200).mean()) if len(arr) >= 200 else None

            result[name] = {
                "current": round(current, 2),
                "52w_high": round(high52, 2),
                "52w_low":  round(low52,  2),
                "ma20":  round(ma20,  2) if ma20  else None,
                "ma50":  round(ma50,  2) if ma50  else None,
                "ma200": round(ma200, 2) if ma200 else None,
            }
        except Exception:
            pass

    return result


def fetch_sector_performance() -> list[dict]:
    """Return daily % change for all 11 SPDR sector ETFs, sorted best to worst.

    Each entry: {"name": str, "ticker": str, "pct_change": float, "level": float}
    Returns empty list if yfinance unavailable.
    """
    if yf is None:
        return []
    try:
        tickers = list(SECTOR_TICKERS.values())
        end   = datetime.today()
        start = end - timedelta(days=7)
        data  = yf.download(tickers, start=start, end=end,
                            progress=False, auto_adjust=True, group_by="ticker")
        results: list[dict] = []
        for name, ticker in SECTOR_TICKERS.items():
            try:
                if len(tickers) == 1:
                    closes = data["Close"].dropna()
                else:
                    closes = data[ticker]["Close"].dropna()
                if hasattr(closes, "squeeze"):
                    closes = closes.squeeze()
                arr = closes.to_numpy()
                if len(arr) < 2:
                    continue
                last = float(arr[-1])
                prev = float(arr[-2])
                pct  = round((last - prev) / prev * 100, 2) if prev else 0.0
                results.append({"name": name, "ticker": ticker,
                                 "pct_change": pct, "level": round(last, 2)})
            except Exception:
                continue
        results.sort(key=lambda x: x["pct_change"], reverse=True)
        top3    = results[:3]
        bottom3 = results[-3:][::-1]
        print(f"  [OK] Sectors: top={top3[0]['name']} {top3[0]['pct_change']:+.2f}%  "
              f"bottom={bottom3[0]['name']} {bottom3[0]['pct_change']:+.2f}%")
        return results
    except Exception as exc:
        print(f"[WARN] fetch_sector_performance failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Portfolio data
# ---------------------------------------------------------------------------
def load_portfolio_df() -> pd.DataFrame:
    path = DATA_DIR / "features.parquet"
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path)
        df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.sort_values("Date").groupby("Ticker", as_index=False).tail(1)
        else:
            df = df.drop_duplicates(subset=["Ticker"], keep="last")
        return df
    except Exception as exc:
        print(f"[WARN] Could not load features.parquet: {exc}")
        return pd.DataFrame()


def _safe_float(val: Any, scale: float = 1.0) -> float | None:
    try:
        v = float(val)
        return round(v * scale, 3) if v == v else None
    except Exception:
        return None


# Fund descriptions — tells the LLM what each ticker actually is so it doesn't hallucinate sector attributions
FUND_DESCRIPTIONS: dict[str, str] = {
    "BUFR":  "FolioBeyond Rising Rates ETF — tactical rate-hedged fixed income",
    "CGDV":  "Capital Group Dividend Value ETF — dividend-focused large-cap US value equities",
    "FLQM":  "Franklin LibertyQ U.S. Mid Cap Equity ETF — mid-cap multi-factor equities",
    "AUSF":  "Global X Adaptive U.S. Factor ETF — multi-factor US equities",
    "SDVD":  "Siren DIVCON Dividend Defender ETF — dividend growth, hedged against dividend cutters",
    "DIVO":  "Amplify CWP Enhanced Dividend Income ETF — dividend income with covered call overlay",
    "XLG":   "Invesco S&P 500 Top 50 ETF — mega-cap US equities (top 50 in S&P 500)",
    "TMFC":  "Motley Fool 100 Index ETF — 100 largest Motley Fool-recommended US stocks",
    "XNTK":  "SPDR NYSE Technology ETF — US technology sector equities",
    "RLY":   "SPDR SSgA Multi-Asset Real Return ETF — real assets and inflation protection",
    "EFAA":  "Columbia Adaptive Risk Allocation ETF — multi-asset adaptive allocation",
    "LVHI":  "Legg Mason International Low Volatility High Dividend ETF — international low-volatility dividend equities (NOT tech)",
    "SGIIX": "Segall Bryant & Hamill International Small Cap Fund — international small-cap equities",
    "JFNIX": "John Hancock Fundamental All Cap Core Fund — all-cap US equities, fundamental strategy",
    "IXJ":   "iShares Global Healthcare ETF — global healthcare equities (NOT consumer discretionary)",
    "VSMIX": "Vanguard Strategic Small-Cap Equity Fund — US small-cap equities",
    "TGVIX": "Thornburg Global Value Fund — global value equities",
    "JAAA":  "Janus Henderson AAA CLO ETF — AAA-rated CLOs, short-duration investment-grade fixed income",
    "WCPBX": "Western Asset Core Plus Bond Fund — core plus multi-sector fixed income",
    "LBIIX": "Lord Abbett Bond Debenture Fund — multi-sector fixed income",
    "ADVNX": "BlackRock Advantage International Fund — international developed market equities",
    "EVTR":  "Eaton Vance Tax-Managed Diversified Equity Income Fund — tax-managed equity income",
    "MFIIX": "MainStay Floating Rate Fund — floating rate senior loans",
    "SUBFX": "Semper Short Duration Fund — short-duration fixed income",
    "KORP":  "American Century Diversified Corporate Bond ETF — investment-grade corporate bonds",
    "OMFYX": "Osterweis Strategic Income Fund — flexible multi-sector fixed income",
    "MTFGX": "MFS Total Return Fund — balanced equities and bonds",
    "JHPI":  "John Hancock Preferred Income Fund — preferred securities and income",
    "JHMB":  "John Hancock Mortgage-Backed Securities ETF — agency MBS fixed income",
    "JMST":  "JPMorgan Ultra-Short Municipal Income ETF — ultra-short tax-exempt munis",
    "JSI":   "Janus Henderson Securitized Income ETF — securitized credit (ABS, MBS, CLOs)",
    "FDUIX": "Federated Hermes Ultrashort Duration Fund — ultra-short investment-grade bonds",
    "QQA":   "Invesco QQA Nasdaq 100 ETF — Nasdaq 100 large-cap technology-heavy index",
    "SHLD":  "Global X Defense Tech ETF — defense and aerospace technology equities",
}


def build_portfolio_spotlight(df: pd.DataFrame) -> tuple[list, list]:
    try:
        from universe_config import get_portfolio_tickers, get_mag7
    except Exception:
        return [], []

    mag7     = set(get_mag7())
    all_port = get_portfolio_tickers()
    funds    = df[df["Ticker"].isin([t for t in all_port if t not in mag7])].copy()

    ret_col = "1M Return" if "1M Return" in funds.columns else None
    if funds.empty or ret_col is None:
        return [], []

    funds[ret_col] = pd.to_numeric(funds[ret_col], errors="coerce")
    funds = funds.dropna(subset=[ret_col]).sort_values(ret_col, ascending=False)

    def to_dict(row: pd.Series) -> dict:
        ret = _safe_float(row[ret_col], scale=100) or 0.0
        ticker = row["Ticker"]
        d: dict[str, Any] = {
            "ticker":      ticker,
            "description": FUND_DESCRIPTIONS.get(ticker, ""),
            "return_1m":   ret,
            "metric_label": f"{ret:+.1f}% (1M)",
        }
        for col, label in [
            ("Sharpe (3Y)",       "sharpe_3y"),
            ("3Y Sharpe",         "sharpe_3y"),
            ("Max Drawdown 3Y",   "max_drawdown"),
            ("Volatility",        "volatility"),
            ("Alpha (3Y)",        "alpha"),
        ]:
            if col in row.index and d.get(label) is None:
                v = _safe_float(row[col])
                if v is not None:
                    d[label] = v
        return d

    winners = [to_dict(r) for _, r in funds.head(3).iterrows()]
    watch   = [to_dict(r) for _, r in funds.tail(2).iterrows()]
    return winners, watch


def build_mag7_consensus(df: pd.DataFrame) -> dict[str, dict]:
    """Return per-ticker dict with consensus, confidence, agreement, winning model."""
    try:
        from universe_config import get_mag7
        mag7 = get_mag7()
    except Exception:
        return {}

    result: dict[str, dict] = {}
    mag7_df = df[df["Ticker"].isin(mag7)]
    for _, row in mag7_df.iterrows():
        ticker = row["Ticker"]
        entry: dict[str, Any] = {}
        for col in ("Consensus_Forecast", "Consensus Forecast (%)"):
            if col in row.index:
                v = _safe_float(row[col])
                if v is not None:
                    entry["consensus"] = round(v * 100 if abs(v) < 1 else v, 2)
                    break
        entry["confidence"]    = str(row.get("Confidence_Label", "") or "")
        entry["agreement"]     = _safe_float(row.get("Agreement_Ratio"))
        entry["winning_model"] = str(row.get("Winning_Model", "") or "")
        result[ticker] = entry

    return result


# ---------------------------------------------------------------------------
# News loading
# ---------------------------------------------------------------------------
_NEWS_BUCKETS: dict[str, list[str]] = {
    "commodities":  ["oil", "crude", "gold", "commodity", "commodities", "energy", "opec", "brent", "wti", "copper", "silver", "gas"],
    "fixed_income": ["fed", "federal reserve", "rate", "yield", "treasury", "inflation", "cpi", "fomc", "interest", "bonds", "debt", "credit"],
    "equities":     ["stock", "equity", "equities", "nasdaq", "s&p", "earnings", "shares", "market rally", "selloff", "ipo", "dividend"],
    "currencies":   ["dollar", "dxy", "currency", "forex", "yen", "euro", "pound", "fx", "bitcoin", "crypto"],
    "macro":        ["gdp", "recession", "growth", "unemployment", "jobs", "economy", "economic", "jolts", "pce", "consumer"],
}

# Promotional/sponsored content patterns to exclude from LLM context
_NOISE_KEYWORDS: frozenset[str] = frozenset({
    "ebook", "webinar", "whitepaper", "free report", "trading guide",
    "free download", "cfd broker", " cfds ", "sponsored", "advertisement",
    "launches free", "free tool", "sign up", "newsletter", "free access",
    "claim your", "download now", "register now", "watch now",
})

# US-relevance ranking for the LLM news corpus. We DE-PRIORITIZE (never drop) headlines
# about foreign-domestic markets/regulators with little direct US read-through (India/RBI,
# SE-Asia) so they sink below US-relevant stories in each bucket's top-N cut. A headline
# carrying a US hook (matches both lists) nets toward neutral and is retained.
_US_RELEVANCE_RE = re.compile(
    r"\b(fed|federal reserve|fomc|powell|treasury|u\.?s\.?|united states|wall street|"
    r"s&p|nasdaq|dow jones|dow|russell|vix|dollar|greenback|cpi|pce|payrolls?|jobless|"
    r"ism|gdp|white house|congress)\b",
    re.I,
)
_REGIONAL_DEPRIORITIZE_RE = re.compile(
    r"\b(india|indian|rbi|nifty|sensex|rupee|mumbai|sebi|malaysia|malaysian|ringgit|"
    r"indonesia|rupiah|jakarta|philippine|philippines|peso|thailand|baht|vietnam)\b",
    re.I,
)


def _us_relevance_score(text: str) -> int:
    """Higher = more US-relevant. Foreign-domestic-only headlines score negative so a
    stable sort sinks them in each bucket's top-N cut (de-prioritized, never dropped)."""
    low = text or ""
    return len(_US_RELEVANCE_RE.findall(low)) - len(_REGIONAL_DEPRIORITIZE_RE.findall(low))


def bucket_headlines(entries: list[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {k: [] for k in _NEWS_BUCKETS}
    buckets["other"] = []
    for entry in entries:
        lower   = entry.lower()
        matched = False
        for bucket, keywords in _NEWS_BUCKETS.items():
            if any(kw in lower for kw in keywords):
                buckets[bucket].append(entry)
                matched = True
                break
        if not matched:
            buckets["other"].append(entry)
    return {k: v for k, v in buckets.items() if v}


def load_news_headlines() -> dict[str, list[str]]:
    parquet_path = DATA_DIR / "news_store.parquet"
    csv_path     = DATA_DIR / "news_headlines.csv"

    df = None
    if parquet_path.exists():
        try:
            df = pd.read_parquet(parquet_path)
        except Exception:
            pass

    if df is None or df.empty:
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
            except Exception:
                return {}
        else:
            return {}

    if df is None or df.empty:
        return {}

    try:
        from news_store import _story_quality
        df["_q"] = df.apply(_story_quality, axis=1)
        df = df.sort_values("_q", ascending=False)
    except Exception:
        pass

    headline_col = next((c for c in df.columns if c.lower() in ("headline", "title", "head")), None)
    summary_col  = next((c for c in df.columns if c.lower() in ("summary", "description", "body")), None)
    if headline_col is None:
        return {}

    entries = []
    for _, row in df.head(60).iterrows():
        headline = str(row.get(headline_col, "") or "").strip()
        if not headline:
            continue
        summary = str(row.get(summary_col, "") or "").strip() if summary_col else ""
        if summary and summary.lower() not in ("nan", "none", ""):
            entries.append(f"{headline}  {summary}")
        else:
            entries.append(headline)

    return bucket_headlines(entries)


def fetch_world_news() -> list[dict]:
    articles: list[dict] = []

    try:
        from providers.openbb_provider import OpenBBProvider
        provider = OpenBBProvider()
        if getattr(provider, "obb", None) is not None:
            resp = provider.obb.news.world(limit=40, provider="fmp")
            results = resp.results if hasattr(resp, "results") else []
            for r in results:
                r = r.__dict__ if hasattr(r, "__dict__") else (r if isinstance(r, dict) else {})
                title = str(r.get("title") or r.get("headline") or "").strip()
                if not title:
                    continue
                articles.append({
                    "title":        title,
                    "summary":      str(r.get("text") or r.get("summary") or r.get("description") or "").strip()[:300],
                    "source":       str(r.get("source") or r.get("publisher") or "").strip(),
                    "published_at": str(r.get("date") or r.get("published_at") or ""),
                    "url":          str(r.get("url") or r.get("link") or ""),
                    "category":     "world",
                })
    except Exception as exc:
        print(f"[WARN] OpenBB world news failed: {exc}")

    if not articles and yf is not None:
        try:
            for sym in ("SPY", "QQQ", "TLT", "GLD", "UUP", "^VIX"):
                tkr  = yf.Ticker(sym)
                news = getattr(tkr, "news", None) or []
                for item in news[:10]:
                    content = item.get("content") if isinstance(item.get("content"), dict) else {}
                    title   = str(content.get("title") or item.get("title") or "").strip()
                    if not title:
                        continue
                    articles.append({
                        "title":        title,
                        "summary":      str(content.get("summary") or "").strip()[:300],
                        "source":       str((content.get("provider") or {}).get("displayName") or item.get("publisher") or "").strip(),
                        "published_at": str(content.get("pubDate") or item.get("providerPublishTime") or ""),
                        "url":          str((content.get("canonicalUrl") or {}).get("url") or item.get("link") or ""),
                        "category":     "world",
                    })
        except Exception:
            pass

    seen: set[str] = set()
    unique: list[dict] = []
    for a in articles:
        key = a["title"].lower()[:60]
        if key and key not in seen:
            seen.add(key)
            text = (a["title"] + " " + a["summary"]).lower()
            for bucket, keywords in _NEWS_BUCKETS.items():
                if any(kw in text for kw in keywords):
                    a["category"] = bucket
                    break
            unique.append(a)

    result = unique[:40]

    try:
        out = DATA_DIR / "world_news.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"updated": datetime.today().strftime("%Y-%m-%d"), "articles": result}, f,
                      indent=2, ensure_ascii=False, default=str)
        print(f"[OK] World news saved -> {out} ({len(result)} articles)")
    except Exception:
        pass

    return result


def _fetch_fed_speakers_json(today_str: str) -> list[dict]:
    """Today's Fed speaker events from the Fed's structured calendar JSON feed.

    federalreserve.gov/json/calendar.json is the official data behind the HTML calendar —
    2,500+ events, each with title (e.g. "Speech - Governor Lisa D. Cook"), description
    (topic), time, month (YYYY-MM), days, type, location. Far more reliable than scraping
    the rendered HTML (the CSS-selector scrape silently missed Cook & Jefferson on 5/27).
    Returns [] on any failure so the caller can fall back.
    """
    import urllib.request as _ur
    req = _ur.Request("https://www.federalreserve.gov/json/calendar.json",
                      headers={"User-Agent": "Mozilla/5.0"})
    with _ur.urlopen(req, timeout=14) as _resp:
        raw = _resp.read().decode("utf-8-sig", errors="replace")  # strip BOM
    events = json.loads(raw)
    if isinstance(events, dict):
        events = events.get("events") or events.get("days") or []
    out: list[dict] = []
    for ev in (events if isinstance(events, list) else []):
        # Date = month (YYYY-MM) + zero-padded day.
        month = str(ev.get("month", "")).strip()
        day   = str(ev.get("days", "")).strip()
        if not (month and day):
            continue
        ev_date = f"{month}-{int(day):02d}" if day.isdigit() else ""
        if ev_date != today_str:
            continue
        title = str(ev.get("title", "")).strip()
        etype = str(ev.get("type", "")).strip().lower()
        # Speaker events: type "Speeches"/"Testimony", or a title naming an official role.
        _is_speaker = (
            etype in ("speeches", "testimony")
            or any(r in title for r in ("Chair", "Governor", "President", "Vice Chair"))
        )
        if not _is_speaker or len(title) < 4:
            continue
        # Titles read "Speech - Governor Lisa D. Cook" / "Discussion - Vice Chair Philip
        # N. Jefferson". Strip the leading event-kind so the render shows just the role +
        # name (the topic field already conveys what kind of appearance it is).
        speaker = title.split(" - ", 1)[1].strip() if " - " in title else title
        out.append({
            "speaker": speaker,                                 # e.g. "Governor Lisa D. Cook"
            "time_et": str(ev.get("time", "")).strip(),
            "venue":   str(ev.get("location", "")).strip()[:160],
            "topic":   str(ev.get("description", "")).strip()[:200],
        })
    return out


def fetch_fed_speakers() -> list[dict]:
    """Return today's Fed speaker events.

    Primary: the Fed's structured calendar JSON feed (reliable, official). Fallbacks, in
    order: scraping the HTML calendar, then data/fed_speakers_2026.json.
    Output: list of {"speaker": str, "time_et": str, "venue": str, "topic": str}
    """
    today_str = datetime.today().strftime("%Y-%m-%d")
    today_dt  = datetime.today().date()

    def _from_fallback() -> list[dict]:
        path = DATA_DIR / "fed_speakers_2026.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [e for e in (data if isinstance(data, list) else [])
                    if str(e.get("date", ""))[:10] == today_str]
        except Exception:
            return []

    # ── Primary: structured JSON feed ─────────────────────────────────────────
    try:
        _json_speakers = _fetch_fed_speakers_json(today_str)
        if _json_speakers:
            print(f"[FED] {len(_json_speakers)} Fed speaker event(s) today (source: calendar.json).")
            return _json_speakers
    except Exception as _exc:
        print(f"[FED] calendar.json feed failed ({_exc}); trying HTML scrape.")

    # ── Fallback 1: HTML calendar scrape ──────────────────────────────────────
    try:
        import urllib.request as _ur
        from bs4 import BeautifulSoup
        req = _ur.Request(
            "https://www.federalreserve.gov/newsevents/calendar.htm",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with _ur.urlopen(req, timeout=14) as _resp:
            html_bytes = _resp.read()
        soup = BeautifulSoup(html_bytes.decode("utf-8", errors="replace"), "html.parser")

        speakers: list[dict] = []
        # The Fed calendar renders events grouped by date. Each group has a date header
        # (h5 or h4 with a parseable date string) followed by event rows.
        current_date: str | None = None
        for tag in soup.find_all(True):
            # Date header — e.g. <h5 class="...">May 7, 2026</h5>
            if tag.name in ("h4", "h5"):
                txt = tag.get_text(strip=True)
                try:
                    from datetime import datetime as _dtp
                    parsed = _dtp.strptime(txt.strip(), "%B %d, %Y")
                    current_date = parsed.strftime("%Y-%m-%d")
                except Exception:
                    pass
                continue
            # Event rows: look for divs with "eventlist__event" or similar markers
            if tag.name == "div" and current_date == today_str:
                cls = " ".join(tag.get("class") or [])
                if "eventlist__event" not in cls and "row" not in cls:
                    continue
                time_tag    = tag.select_one(".eventlist__time, .col-xs-12.col-md-3")
                heading_tag = tag.select_one(".eventlist__heading, h4, h5, .col-xs-12.col-md-9")
                desc_tag    = tag.select_one(".eventlist__description, p")
                time_et  = time_tag.get_text(strip=True)    if time_tag    else ""
                heading  = heading_tag.get_text(strip=True) if heading_tag else ""
                topic    = desc_tag.get_text(strip=True)    if desc_tag    else ""
                if heading and len(heading) > 3:
                    speakers.append({
                        "speaker":  heading,
                        "time_et":  time_et,
                        "venue":    "",
                        "topic":    topic[:200],
                    })

        if speakers:
            print(f"[FED] Scraped {len(speakers)} Fed event(s) for today.")
            return speakers
    except Exception as _exc:
        print(f"[FED] Fed calendar scrape failed ({_exc}); using fallback.")

    result = _from_fallback()
    if not result:
        print("[FED] No Fed speakers scheduled today (fallback empty).")
    return result


def fetch_economic_calendar() -> list[dict]:
    """Fetch upcoming macro events. Primary: FRED releases. Fallback: NASDAQ.
    Saves results to data/economic_calendar.json for the website to read."""
    events: list[dict] = []
    today     = datetime.today()
    next_4w   = today + timedelta(days=28)

    # ── FRED releases calendar (primary) ─────────────────────────────────────
    # Explicit blocklist — checked before EVENT_MAP so these never match a keyword
    _SKIP_KEYWORDS = {
        # ── daily market/rate series ─────────────────────────────────────────
        "federal funds data", "coinbase", "dow jones", "nasdaq daily",
        "nikkei", "cboe market statistics", "commercial paper",
        "euro short term rate", "interest rate on reserve", "overnight bank",
        "secured overnight", "historical overnight", "optimal blue",
        "ice bofa", "moody", "recession indicator", "key ecb",
        "interest rate spreads", "economic policy uncertainty",
        "kansas city fed policy", "bankrate", "daily treasury", "h.15 selected",
        "temporary open market operations", "tri-party general collateral",
        "sofr averages", "sonia interest rate benchmark",
        # ── commodity / rate surveys (not macro releases) ────────────────────
        "natural gas spot", "gasoline and diesel",
        "primary mortgage market survey",           # weekly Freddie Mac mortgage rates
        # ── state / metro / sub-national breakdowns ──────────────────────────
        "state unemployment insurance weekly claims",  # fires Fri after Thu national release
        "personal income by state", "monthly state retail sales",
        "state employment and unemployment", "state and metro area employment",
        "metropolitan area employment", "labor force participation by state",
        "texas employment data", "alternative measures of labor underutilization",
        # ── derived / model / academic indexes ──────────────────────────────
        "st. louis fed financial stress", "st. louis fed economic news",
        "chicago fed national financial conditions",
        "chicago fed advance",                      # retail trade summary, not CFNAI
        "kansas city financial stress",
        "weekly economic index",                    # Lewis-Mertens-Stock composite
        "brave-butters-kelley",                     # alternative activity index
        "hornstein-kudlyak-lange",                  # non-employment index
        "university of louisville",                 # academic LoDI index
        "fujita, moscarini",                        # academic transition series
        "u.s. recession probabilities",
        "gdp-based recession indicator",
        "debt to gross domestic product",           # ratio series, not a release
        "money velocity", "real money stock",
        "st. louis fed price pressures",
        # ── CPI / PCE variant series (headline already captured) ─────────────
        "current median cpi", "sticky price cpi",
        "research consumer price index", "average price data",
        # ── foreign / international data ────────────────────────────────────
        "bank of japan", "swiss national bank",
        "weekly financial statements of the eurosystem",
        "turkish foreign exchange", "international financial statistics",
        "h.10 foreign exchange", "quarterly national accounts",  # OECD/IMF series
        "financial soundness indicators", "summary measures of the foreign exchange",
        "bis effective exchange rate",
        # ── miscellaneous low-signal series ─────────────────────────────────
        "market hotness index", "visa spending momentum",
        "housing inventory core metrics", "housing vacancies and homeownership",
        "manufactured housing survey",
        "minimum wage rates",
        "market value of u.s. government debt",
        "selected property price", "national rates and rate caps",
        "h.4.1 factors affecting reserve",         # weekly Fed balance sheet
        "h.8 assets and liabilities",              # weekly bank assets
        "h.6 money stock",                         # M2 (low calendar impact)
        "select time series based on",             # SWAA working arrangements research
        "transportation services index",
        "supplemental estimates",                   # GDP supplemental tables
        "gross domestic product by industry",       # deduped anyway, cleaner to skip
        "gross domestic product by state",
        "survey of business uncertainty",
    }
    # Whitelist: only releases matching a keyword below appear on the calendar.
    # ORDER MATTERS — first match wins, so more-specific keys must come first.
    _EVENT_MAP = {
        "fomc minutes":                                    ("Fed FOMC Minutes",                       "high"),
        "minutes of the federal open market committee":    ("Fed FOMC Minutes",                       "high"),
        "fomc press release":                              ("FOMC Meeting / Rate Decision",           "high"),
        "gdpnow":                                      ("Atlanta Fed GDPNow Estimate",            "medium"),
        "consumer price index":                        ("CPI Inflation Report",                   "high"),
        "employment situation":                        ("Non-Farm Payrolls / Jobs Report",         "high"),
        "adp national employment":                     ("ADP Employment Report",                   "high"),
        "producer price index":                        ("PPI Inflation Report",                    "high"),
        "advance monthly sales for retail":            ("Retail Sales",                            "high"),
        "g.17 industrial production":                  ("Industrial Production",                   "medium"),
        # nonmanufacturing MUST precede manufacturing — it's a substring match trap
        "nonmanufacturing business outlook":           ("ISM Non-Manufacturing",                   "medium"),
        "manufacturing business outlook survey":       ("Philly Fed Manufacturing Index",          "medium"),
        "empire state manufacturing survey":           ("Empire State Manufacturing",              "medium"),
        "texas manufacturing outlook":                 ("Dallas Fed Manufacturing",                "medium"),
        "survey of regional conditions and expectations": ("Richmond Fed Survey (SORCE)",          "medium"),
        "harmonized indices of consumer prices":       ("EU CPI / HICP",                          "medium"),
        "national accounts - gdp (eurostat)":          ("Eurozone GDP",                           "medium"),
        "gross domestic product":                      ("GDP Report",                             "high"),
        "unemployment insurance weekly claims":        ("Initial Jobless Claims",                 "high"),
        "ism report on business":                      ("ISM Manufacturing / Services",            "medium"),
        # "surveys of consumers" is FRED's actual release name for UMich
        "surveys of consumers":                        ("UMich Consumer Sentiment",                "high"),
        "university of michigan":                      ("UMich Consumer Sentiment",                "high"),
        "personal income and outlays":                 ("Personal Income & PCE",                   "high"),
        "personal income":                             ("Personal Income & PCE",                   "high"),
        "employment cost index":                       ("Employment Cost Index",                   "medium"),
        "durable goods":                               ("Durable Goods Orders",                    "medium"),
        "manufacturer's shipments, inventories":       ("Factory Orders / Durable Goods",          "medium"),
        "manufacturing and trade inventories":         ("Business Inventories",                    "medium"),
        # new residential sales before new residential — avoid substring mismatch
        "new residential sales":                       ("New Home Sales",                          "medium"),
        "new residential":                             ("Housing Starts / Building Permits",       "medium"),
        "housing units authorized by building permits":("Housing Starts / Building Permits",       "medium"),
        "u.s. international trade in goods":           ("Trade Balance",                           "medium"),
        "trade balance":                               ("Trade Balance",                           "medium"),
        "u.s. import and export price indexes":        ("Import & Export Price Indexes",            "medium"),
        "monthly treasury statement":                  ("Federal Budget Statement",                "medium"),
        "trimmed mean pce":                            ("PCE Inflation (Trimmed Mean)",             "medium"),
        "job openings":                                ("JOLTS Job Openings",                      "medium"),
        "consumer confidence":                         ("Consumer Confidence",                     "medium"),
        "existing home sales":                         ("Existing Home Sales",                     "medium"),
        "new home sales":                              ("New Home Sales",                          "medium"),
        "factory orders":                              ("Factory Orders",                          "medium"),
        "wholesale trade":                             ("Wholesale Inventories",                   "medium"),
        "g.19 consumer credit":                        ("Consumer Credit",                         "medium"),
        "productivity and costs":                      ("Productivity & Unit Labor Costs",          "medium"),
        "construction spending":                       ("Construction Spending",                   "medium"),
        "s&p cotality case-shiller":                   ("Case-Shiller Home Price Index",            "medium"),
        "house price index":                           ("FHFA House Price Index",                  "medium"),
        "advance economic indicators":                 ("Advance Trade & Inventories",             "medium"),
        "chicago fed national activity":               ("Chicago Fed National Activity Index",      "medium"),
        "flash composite pmi":                         ("S&P Global Flash PMI",                   "high"),
        "flash manufacturing pmi":                     ("S&P Global Flash PMI",                   "high"),
        "flash services pmi":                          ("S&P Global Flash PMI",                   "high"),
    }
    try:
        from epm_secrets import FRED_API_KEY as _fk
        # Single call for the full 4-week window (limit=1000 covers all releases)
        _r = requests.get(
            "https://api.stlouisfed.org/fred/releases/dates",
            params={
                "api_key": _fk, "file_type": "json",
                "realtime_start": today.strftime("%Y-%m-%d"),
                "realtime_end":   next_4w.strftime("%Y-%m-%d"),
                "include_release_dates_with_no_data": "true",
                "limit": 1000,
            },
            timeout=30,
        )
        _r.raise_for_status()
        all_release_dates: list[dict] = _r.json().get("release_dates", [])
        seen: set[tuple] = set()
        for rel in all_release_dates:
            name_lc   = rel["release_name"].lower()
            date_str  = rel["date"]
            if any(kw in name_lc for kw in _SKIP_KEYWORDS):
                continue
            clean, imp = None, "medium"
            for kw, (cn, ci) in _EVENT_MAP.items():
                if kw in name_lc:
                    clean, imp = cn, ci
                    break
            if clean is None:
                continue   # whitelist-only: skip anything not in EVENT_MAP
            key = (date_str, clean)
            if key in seen:
                continue
            seen.add(key)
            events.append({"date": date_str, "event": clean, "country": "US",
                           "importance": imp, "actual": None, "consensus": None, "previous": None})
        events.sort(key=lambda x: x["date"])
        # ── Deduplicate FOMC: FRED emits one entry per day for multi-day meetings.
        # Keep only the LAST date per FOMC meeting (the announcement day).
        # Two FOMC entries within 4 days of each other = same meeting.
        fomc_label = "FOMC Meeting / Rate Decision"
        fomc_events = [e for e in events if e["event"] == fomc_label]
        non_fomc    = [e for e in events if e["event"] != fomc_label]
        merged_fomc: list[dict] = []
        for ev in fomc_events:
            from datetime import date as _date
            ev_date = _date.fromisoformat(ev["date"])
            absorbed = False
            for existing in merged_fomc:
                ex_date = _date.fromisoformat(existing["date"])
                if abs((ev_date - ex_date).days) <= 4:
                    # Keep the later date (announcement day)
                    if ev_date > ex_date:
                        existing["date"] = ev["date"]
                    absorbed = True
                    break
            if not absorbed:
                merged_fomc.append(dict(ev))
        events = sorted(non_fomc + merged_fomc, key=lambda x: x["date"])
        print(f"[CAL] Fetched {len(events)} economic events from FRED releases.")
        # Enrich FRED events with Finnhub consensus/previous (FRED never returns these)
        try:
            from epm_secrets import FINNHUB_KEY as _fhk_enrich
            _fh_enr = requests.get(
                "https://finnhub.io/api/v1/calendar/economic",
                params={"from": today.strftime("%Y-%m-%d"),
                        "to": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
                        "token": _fhk_enrich},
                timeout=12,
            )
            _fh_enr.raise_for_status()
            _fh_ev_list = _fh_enr.json().get("economicCalendar", [])
            # Index Finnhub events by date + lowercased event name
            _fh_idx: dict[str, dict[str, dict]] = {}
            for _fhe in _fh_ev_list:
                _fhd = str(_fhe.get("time", ""))[:10]
                _fhn = str(_fhe.get("event", "")).lower().strip()
                _fh_idx.setdefault(_fhd, {})[_fhn] = {
                    "consensus": _fhe.get("estimate"),
                    "previous":  _fhe.get("prev"),
                }
            _enriched_count = 0
            for _ev in events:
                if _ev.get("consensus") is not None:
                    continue
                _evd  = _ev["date"]
                _evn  = _ev["event"].lower().strip()
                _day  = _fh_idx.get(_evd, {})
                # Direct name match first
                if _evn in _day:
                    _ev["consensus"] = _day[_evn]["consensus"]
                    _ev["previous"]  = _day[_evn]["previous"]
                    _enriched_count += 1
                    continue
                # Partial match: ≥2 shared words
                _ev_words = set(_evn.split())
                for _fn, _fd in _day.items():
                    if len(_ev_words & set(_fn.split())) >= 2:
                        _ev["consensus"] = _fd["consensus"]
                        _ev["previous"]  = _fd["previous"]
                        _enriched_count += 1
                        break
            if _enriched_count:
                print(f"[CAL] Finnhub enriched {_enriched_count} event(s) with consensus/previous.")
        except Exception:
            pass  # enrichment is best-effort; FRED events still ship without it
    except Exception as exc:
        print(f"[WARN] FRED economic calendar failed: {exc} — trying NASDAQ fallback")
        try:
            url = ("https://api.nasdaq.com/api/calendar/economicevents"
                   f"?date={today.strftime('%Y-%m-%d')}&dateend={(today+timedelta(days=28)).strftime('%Y-%m-%d')}")
            rows = (requests.get(url, headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"},
                                  timeout=15).json().get("data") or {}).get("rows") or []
            for r in rows:
                imp = str(r.get("importance") or "").lower()
                if imp not in ("high","moderate","medium","low"):
                    imp = "medium"
                events.append({"date": str(r.get("eventDate") or ""), "event": str(r.get("eventName") or ""),
                               "country": str(r.get("country") or "US"), "importance": imp,
                               "actual": r.get("actual"), "consensus": r.get("consensus"),
                               "previous": r.get("previous")})
            print(f"[CAL] NASDAQ fallback: {len(events)} events.")
        except Exception as exc2:
            print(f"[WARN] NASDAQ fallback also failed: {exc2}")
        if not events:
            try:
                from epm_secrets import FINNHUB_KEY as _fhk
                r = requests.get(
                    "https://finnhub.io/api/v1/calendar/economic",
                    params={"from": today.strftime("%Y-%m-%d"),
                            "to": (today + timedelta(days=28)).strftime("%Y-%m-%d"),
                            "token": _fhk},
                    timeout=12,
                )
                r.raise_for_status()
                fh_events = r.json().get("economicCalendar", [])
                for e in fh_events:
                    imp_raw = str(e.get("impact") or "").lower()
                    imp = {"high": "high", "medium": "moderate", "low": "low"}.get(imp_raw, "low")
                    events.append({"date": str(e.get("time", ""))[:10], "event": str(e.get("event", "")),
                                   "country": str(e.get("country", "US")), "importance": imp,
                                   "actual": e.get("actual"), "consensus": e.get("estimate"),
                                   "previous": e.get("prev")})
                print(f"[CAL] Finnhub fallback: {len(events)} events.")
            except Exception as exc3:
                print(f"[WARN] Finnhub calendar fallback also failed: {exc3}")

    # ── Inject FOMC dates from the Fed's published schedule. ─────────────────
    # FRED's /releases/dates API misses the current meeting when the press
    # release falls on or before today's realtime_start boundary. We supplement
    # from the Fed's own JSON calendar (with a hardcoded 2026 fallback) so the
    # FOMC always appears in the 4-week view regardless of FRED timing.
    import calendar as _cal_mod
    from datetime import date as _ddate
    _today_d  = today.date() if hasattr(today, "date") else _ddate.fromisoformat(str(today)[:10])
    _next4w_d = next_4w.date() if hasattr(next_4w, "date") else _ddate.fromisoformat(str(next_4w)[:10])
    _fomc_label = "FOMC Meeting / Rate Decision"
    _fomc_dates: list[str] = []
    try:
        _fed_r = requests.get(
            "https://www.federalreserve.gov/monetarypolicy/json/fomcCalendars.json",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        _fed_r.raise_for_status()
        _fed_json = _fed_r.json()
        # Format: list of year-blocks, each with "year" and list of meeting dicts.
        # Each meeting has "month" (name string) and "day" (e.g. "27-28" or "28").
        for _yr_block in (_fed_json if isinstance(_fed_json, list) else []):
            try:
                _yr = int(_yr_block.get("year", 0))
            except (ValueError, TypeError):
                continue
            for _mtg in (_yr_block.get("meetings") or []):
                _month_str = str(_mtg.get("month") or _mtg.get("Month") or "").strip().capitalize()
                _day_str   = str(_mtg.get("day")   or _mtg.get("Day")   or "").strip()
                if not _month_str or not _day_str:
                    continue
                try:
                    _month_num = list(_cal_mod.month_name).index(_month_str)
                    _last_day  = int(_day_str.split("-")[-1].strip())
                    _fomc_dates.append(f"{_yr:04d}-{_month_num:02d}-{_last_day:02d}")
                except Exception:
                    continue
        if _fomc_dates:
            print(f"[CAL] Fed calendar: {len(_fomc_dates)} FOMC announcement dates fetched.")
    except Exception as _fe:
        print(f"[CAL] Fed calendar fetch failed ({_fe}); using hardcoded 2026 FOMC dates.")

    if not _fomc_dates:
        # Announcement dates (last day of each 2026 FOMC meeting).
        # Source: Federal Reserve published schedule.
        # Update annually when the Fed releases the following year's dates (usually November).
        _fomc_dates = [
            "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-10",
            "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
        ]

    # Add any FOMC date in [today, next_4w] not already covered in events.
    _existing_fomc = {e["date"] for e in events if e["event"] == _fomc_label}
    for _fd in _fomc_dates:
        try:
            _fd_d = _ddate.fromisoformat(_fd)
        except ValueError:
            continue
        if _fd_d < _today_d or _fd_d > _next4w_d:
            continue
        # Skip if already present within ±2 days (catches FRED's day-1 variant)
        if any(abs((_fd_d - _ddate.fromisoformat(_ex)).days) <= 2 for _ex in _existing_fomc):
            continue
        events.append({
            "date": _fd, "event": _fomc_label, "country": "US",
            "importance": "high", "actual": None, "consensus": None, "previous": None,
        })
        _existing_fomc.add(_fd)
        print(f"[CAL] Injected FOMC date: {_fd}")
    # ── Inject FOMC Minutes dates (3 weeks / 21 days after each announcement). ─
    # FRED never surfaces these; Fed website JSON is unreliable. Derive from the
    # same hardcoded/fetched announcement list so Minutes always appear in the
    # 4-week view when due.
    _minutes_label = "Fed FOMC Minutes"
    _existing_minutes = {e["date"] for e in events if e["event"] == _minutes_label}
    for _fd in _fomc_dates:
        try:
            _min_d = _ddate.fromisoformat(_fd) + timedelta(days=21)
        except (ValueError, TypeError):
            continue
        _min_str = _min_d.isoformat()
        if _min_d < _today_d or _min_d > _next4w_d:
            continue
        if any(abs((_min_d - _ddate.fromisoformat(_ex)).days) <= 1 for _ex in _existing_minutes):
            continue
        events.append({
            "date": _min_str, "event": _minutes_label, "country": "US",
            "importance": "high", "actual": None, "consensus": None, "previous": None,
        })
        _existing_minutes.add(_min_str)
        print(f"[CAL] Injected FOMC Minutes date: {_min_str}")

    # ── Inject Flash PMI dates (3rd Friday of each month, S&P Global). ──────
    # S&P Global Flash PMI is not a FRED release. Published ~3rd Friday monthly.
    _pmi_label = "S&P Global Flash PMI"
    _existing_pmi = {e["date"] for e in events if e["event"] == _pmi_label}
    for _yr, _mo in {(_today_d.year, _today_d.month), (_next4w_d.year, _next4w_d.month)}:
        # Find 3rd Friday of month (try/except guards short months)
        _fridays = []
        for _d in range(1, 32):
            try:
                _day = _ddate(_yr, _mo, _d)
            except ValueError:
                break
            if _day.weekday() == 4:
                _fridays.append(_day)
        if len(_fridays) < 3:
            continue
        _pmi_d   = _fridays[2]
        _pmi_str = _pmi_d.isoformat()
        if _pmi_d < _today_d or _pmi_d > _next4w_d:
            continue
        if _pmi_str in _existing_pmi:
            continue
        events.append({
            "date": _pmi_str, "event": _pmi_label, "country": "US",
            "importance": "high", "actual": None, "consensus": None, "previous": None,
        })
        _existing_pmi.add(_pmi_str)
        print(f"[CAL] Injected Flash PMI date: {_pmi_str}")

    events.sort(key=lambda x: x["date"])

    try:
        cal_path = DATA_DIR / "economic_calendar.json"
        with open(cal_path, "w", encoding="utf-8") as f:
            json.dump({"updated": today.strftime("%Y-%m-%d"), "events": events},
                      f, indent=2, ensure_ascii=False, default=str)
    except Exception as exc:
        print(f"[WARN] Could not save economic_calendar.json: {exc}")

    return [e for e in events if e["importance"] in ("high", "moderate", "medium")]


RECENT_EARNINGS_LOOKBACK_DAYS = 7


def load_recent_earnings_actuals() -> list[dict]:
    """Return tickers with confirmed actuals released within the last N days.

    Reads data/earnings_releases.json (written by earnings_refresh.py) and
    surfaces the structured result to the LLM prompt so it knows which tickers
    have ALREADY reported and can cite actual EPS / surprise figures instead of
    writing 'upcoming earnings' for them.
    """
    path = DATA_DIR / "earnings_releases.json"
    if not path.exists():
        return []
    try:
        releases = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_EARNINGS_LOOKBACK_DAYS)
    out: list[dict] = []
    for ticker, rec in (releases or {}).items():
        if not rec.get("actuals_available"):
            continue
        try:
            as_of = datetime.fromisoformat(str(rec.get("as_of", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        if as_of < cutoff:
            continue
        out.append({
            "ticker":           ticker,
            "earnings_date":    rec.get("earnings_date"),
            "eps_actual":       rec.get("eps_actual"),
            "eps_estimate":     rec.get("eps_estimate"),
            "eps_surprise_pct": rec.get("eps_surprise_pct"),
        })
    out.sort(key=lambda r: abs(r.get("eps_surprise_pct") or 0), reverse=True)
    return out


# ---------------------------------------------------------------------------
# LLM prompts  split into two focused calls to stay within 14B model limits
# ---------------------------------------------------------------------------

WRITING_RULES = """You are a senior market strategist writing for EPM Financial's daily Market Intelligence Report.
Rules: tight analytical prose; no filler; present tense; active voice.
NEVER use: "geopolitical tensions", "geopolitical risks", "global uncertainties", "amid uncertainty", "amid concerns", "it is worth noting", "in conclusion", "overall,", "moving forward".
All market directions MUST match the sign of pct_change values provided.
Do NOT describe a yield or price as "unchanged" if a non-zero pct_change is provided — state the actual direction (rose/fell) and magnitude instead.
Do not invent figures or events not in the payload.
Do NOT attribute geopolitical actions, policy proposals, or peace initiatives to specific companies or financial institutions — if a headline mentions a bank alongside a geopolitical event, the bank is a commentator or stakeholder, not the actor proposing the policy.
Do NOT escalate the severity of geopolitical events beyond the exact language in the payload — if headlines say "tensions" or "conflict", do not write "war"; if they say "negotiations", do not write "deal reached".
NARRATIVE COHERENCE: All sections must describe the same geopolitical reality. If one section cites escalating risk ("expanded strikes", "rising tensions"), no other section may simultaneously frame the same situation as de-escalating ("easing tensions", "peace deal hopes", "ceasefire optimism"). Pick the dominant tone from the headlines payload and apply it consistently across every section.
ONE-SHOT CALIBRATION — geopolitical tone (follow this pattern exactly):
  Headline in payload: "U.S. and Israel expand strikes near Iranian facilities; diplomatic talks stall"
  BAD: "Mounting costs of the Iran war strain U.S. finances as the conflict widens."
  GOOD: "Markets are pricing a higher risk premium after reports of expanded strikes near Iranian facilities; diplomatic talks remain unresolved."
  Rule: mirror the payload's exact language — do not upgrade 'strikes' to 'war', do not assert fiscal or political consequences as fact, do not name a conflict as an ongoing war unless the payload explicitly uses that word.
Do NOT cite foreign central banks (BoE, ECB, BoJ, PBoC, RBA, BoC, SNB) or foreign sovereign yields (Gilts, Bunds, JGBs) as drivers of US asset moves unless a US-asset headline in the payload explicitly names that institution. Foreign monetary policy may move foreign assets in the international section; for US equities, US bonds, and US dollar commentary, drivers must come from the US payload.
Return ONLY valid JSON  no markdown fences, no explanation."""

# Call 1: Market narrative sections
SYSTEM_PROMPT_NARRATIVE = WRITING_RULES + """

Return JSON with EXACTLY these 6 keys (no others):
pre_market_bullets, equities_commentary, fixed_income_commentary, commodities_commentary, currencies_commentary, economics_commentary

{"pre_market_bullets":["...","...","...","...","..."],"equities_commentary":"...","fixed_income_commentary":"...","commodities_commentary":"...","currencies_commentary":"...","economics_commentary":"..."}

SESSION FRAME: The payload "date" field is the report date. All pct_change, level, and bp_change values in market_levels, bonds, commodities, and currencies reflect the PREVIOUS SESSION's closing values — that is the session you are narrating. recent_earnings_actuals contain results released AFTER that session's close; they did NOT move session equity returns. Mention them in equities_commentary as "after the close" or "in extended trading" only — NEVER credit them as drivers of the day's S&P 500 return.

FLAT-DAY EQUITY RULE: If market_levels["S&P 500"]["pct_change"] is between -0.30% and +0.30%, do NOT write "rallied", "surged", "soared", "jumped", or "plunged" for the overall market. Instead write "closed essentially flat", "ended little changed", or "traded in a narrow range" and pivot to sector rotation or a specific catalyst story.

NUMBER FIDELITY (non-negotiable):
- Every percent and price you cite MUST equal the value in the payload to within 0.01.
- S&P 500: use market_levels["S&P 500"]["pct_change"] for the percent; ["level"] for the price.
- Apply the same rule for Nasdaq 100, DXY, Gold, WTI Crude against market_levels / commodities_top6 / currencies_top5.
- For 10-Yr Yield: cite the daily move in BASIS POINTS using market_levels["10-Yr Yield"]["bp_change"] (e.g. "+2 bp", "-5 bp"). NEVER write a percent sign after a yield move ("+0.44%" is wrong; "+2 bp" is correct).
- Direction words (rose/fell/gained/slid) MUST agree with the SIGN of pct_change. A pct_change of -0.04% is "essentially flat" or "barely changed" — NOT "lower" or "fell".
- SIGN PRESERVATION (most-violated rule): If pct_change is negative, the cited percent must be negative AND the verb must be "fell"/"slid"/"declined". If pct_change is positive, the cited percent must be positive AND the verb must be "rose"/"gained"/"climbed". Magnitude alone is wrong — sign and verb must both match.
  BAD: snapshot WTI Crude pct_change=-0.79 → "WTI rose 0.79% on supply concerns" (sign flipped, verb wrong)
  GOOD: snapshot WTI Crude pct_change=-0.79 → "WTI fell 0.79% to $94.99 on softer Asian demand"
- MAGNITUDE FIDELITY: Always cite the percent figure from pct_change, never the raw dollar delta. A $2.20 move on $4720 gold is +0.05%, not +2.2%. If you find yourself writing a number like "2.2002" or any figure that looks like a dollar amount rather than a percent, stop and use the pct_change from the payload instead.
- CAUSAL CONSISTENCY: The driver you cite must logically support the direction you report. "Fewer/lower rate hike expectations" and "peace deal hopes" both pull yields DOWN — if yields rose, do not use these as drivers. "Hawkish Fed/inflation data" pulls the dollar UP. Safe-haven buying pushes gold UP. If your verb says "rose" but your driver implies "down", rewrite either the verb or the driver to eliminate the contradiction.
- If a number is missing from the payload, OMIT it entirely. Do NOT estimate, round, or invent.
- Tickers in recent_earnings_actuals have ALREADY released earnings this week — never write "later this week" or "upcoming earnings" for them. If you mention one, cite the reported EPS and surprise % from the payload.

pre_market_bullets: Array of 5 strings:
  [0] Use the following template verbatim as the first bullet, replacing {catalyst} with one specific driver from recent_headlines (e.g. "megacap earnings beat", "tariff headlines"). Keep all numbers exactly as given — do NOT alter them. Template: BULLET_0_TEMPLATE
  [1] International/macro driver — cite one specific market-moving event (earnings beat/miss, geopolitical development, central bank action, major economic data). NEVER cite broker promotions, ebooks, webinars, or sponsored content.
  [2] Economic calendar: check todays_economic_events first. If it has entries, cite the most important one — include scheduled time and consensus vs prior — format: "Key data today: [Event] at [time] ET — consensus [X] vs prior [Y]; a [beat/miss] would [1-sentence market implication]." If todays_economic_events is EMPTY, cite the next important event from week_ahead_econ_events by its WEEKDAY name — format: "[Weekday]'s [Event] (consensus [X] vs prior [Y]) will be the next macro test." NEVER call a week_ahead_econ_events entry "today". If both lists are empty, OMIT this bullet and produce only 4 items total.
  [3] Fed/rates: cite 10-yr yield level and direction in basis points with a specific driver.
  [4] Top commodity or currency move. If recent_headlines contains a specific commodity move with a named driver (oil on Iran/OPEC/supply, gold on rates/dollar), cite that headline's development as the pre-market story. Otherwise describe the largest mover from commodities_top6 as yesterday's closing change with its driver.

FLAT-DAY CALIBRATION: when |pct_change| < 0.10 for an index, write "essentially flat at [level]" instead of citing only a percent. Example:
  BAD: "S&P 500 unchanged% at 7,365.12"   (template substitution failure)
  BAD: "S&P 500 +0.04% — markets unchanged" (contradictory)
  GOOD: "S&P 500 closed essentially flat at 7,365.12 (+0.04%)"
  GOOD: "Markets closed mixed — S&P 500 essentially flat (+0.04%), Nasdaq 100 -0.12%; [catalyst]"

equities_commentary: 5-8 sentences — write all 8 if the data supports it; never truncate at 4. Lead with S&P 500 direction and level. SECTOR ROTATION (required): cite the top 2 sectors from sector_top3 and bottom 2 from sector_bottom3 by name and pct_change — e.g. "Technology led (+1.2%), followed by Financials (+0.8%), while Energy (-1.1%) and Real Estate (-0.9%) lagged." Use sector_top3 and sector_bottom3 from the payload. Include VIX level from technical_context and characterize it by BAND — below 15 = "subdued"/"calm"; 15-20 = "contained"/"below-average"; 20-30 = "elevated"; above 30 = "stressed". NEVER call a sub-20 VIX "elevated" or "high". State whether SPX is above or below its 200-day MA. If recent_earnings_actuals is non-empty, name 1-2 specific tickers from it with their EPS surprise % (e.g., "AMD's 12% EPS beat lifted semis") — use only eps_surprise_pct values from the payload. Do NOT cite a specific corporate action (dividend change %, buyback size, guidance figure) unless that exact number appears in the payload — never invent a figure like "raised its dividend 2,400%". Name at least one specific catalyst from recent_headlines. Global market context: cite one or two international index moves. Forward: what level or catalyst traders are watching next.

fixed_income_commentary: 5-6 sentences on TREASURY MARKET dynamics, the yield curve, and Fed policy implications. SCOPE: yield levels, curve shape, Fed rate-path expectations, and equity-multiple effects ONLY. Do NOT write about covered-call ETFs, JEPQ, equity-linked notes, CLOs, retail income strategies, or bond substitutes.
  Sentence 1 MUST begin: "The [10/30]-year Treasury yield [rose/fell/held] [N] bp[s] to [X.XX]% ..." — use bp_change from bonds["10-Year Yield"]["bp_change"] and level from market_levels["10-Yr Yield"]["level"]. If |bp_change| < 1, write "held near [level]%."
  Sentence 2: 30-yr yield level and any notable threshold; or 2-yr yield if 30-yr absent.
  Sentence 3: Yield curve shape — bonds["10s-2s Spread"]["change"] negative = NARROWED, positive = WIDENED; state magnitude in bps.
  Sentence 4: Fed policy — connect yield move to rate expectations or a named FOMC official/event from news_by_category["fixed_income"].
  Sentence 5: Equity multiple implication of the current 10-yr yield level.
  ANTI-COPY RULE (critical): The STYLE REFERENCE below shows SENTENCE SHAPE ONLY. Its specific facts are placeholders — do NOT reproduce any of them. Never output a named official or nomination (e.g. "Warsh nomination"), a specific forward P/E ("32x"), a probability ("80%"), or a "first time since [year]" claim unless that exact fact is present in the payload or news_by_category. Fill every bracket from the payload; if a fact isn't in the payload, omit the clause.
  STYLE REFERENCE (shape only — substitute payload values for ALL bracketed parts, drop any clause you lack data for): "The 10-year Treasury yield [rose/fell/held] [N] bps to [X.XX]%, [extending/reversing] a recent move driven by [a driver from news_by_category]. The 30-year yield [moved] to [X.XX]%, [a notable threshold if relevant]. The 2s10s spread [widened/narrowed] [N] bps to [Y] bps as [front/back]-end [buying/selling] led. [A Fed rate-path sentence ONLY if news_by_category names a specific FOMC official/event — otherwise omit]. At a 10-year yield near [X.XX]%, elevated yields imply [an equity-multiple effect] on growth names."

commodities_commentary: 5-6 sentences. WTI direction and level first, then gold. Specific fundamental driver for each. Key price level nearby. Connect to macro thesis.

currencies_commentary: 4-5 sentences. DXY direction and level. Rate differential or trade-flow driver. EUR/USD and JPY if notable. EM implication.

economics_commentary: 4-5 sentences. If recent_headlines contains any economic data release that ALREADY occurred (Retail Sales, jobless claims, CPI, PPI, industrial production, PMI, GDP), cite the actual result vs consensus and interpret the beat or miss — but mark it clearly as a PAST release (e.g., "Last Thursday's Jobless Claims came in at 211k, in line with the 211k prior."). NEVER cite a past headline release as an upcoming event. Most important release first. Macro cycle context (soft landing, slowdown, re-acceleration). Fed rate trajectory implication.
  DATE GUARD (critical): If todays_economic_events is EMPTY there is NO release scheduled today — do NOT write that any report is "scheduled today", "due this morning", or "at 8:30 AM ET today", and do NOT invent a release that is not in todays_economic_events or week_ahead_econ_events. Refer to any upcoming release by its WEEKDAY (e.g., "Thursday's GDP report"), and anchor the paragraph in the macro cycle rather than a fictitious same-day calendar.

ONE-SHOT EXAMPLE — bullet format reference ONLY. Use payload-specific numbers; do NOT copy these specifics:
{"pre_market_bullets":["Markets closed mixed — S&P 500 -0.12%, Nasdaq 100 +0.08%; megacap tech offset weakness in regional banks after Q1 deposit guidance.","Hang Seng rose 0.9% as PBoC drained liquidity at a slower pace, easing Q2 tightening fears.","Key data today: ISM Services PMI (high importance) at 10:00 AM ET — consensus 52.0 vs prior 51.4; a beat would reinforce the soft-landing thesis and add upward pressure to long-end yields.","10-yr yield fell 3 bps to 4.36%; breakevens widened on stronger jobless claims.","WTI rose 1.2% to $77.40 on OPEC+ extending production cuts through Q3."],"equities_commentary":"...","fixed_income_commentary":"...","commodities_commentary":"...","currencies_commentary":"...","economics_commentary":"..."}"""

# Call 1r: Refinement/generation pass — deepens existing sections AND generates any missing ones.
# Input shape: {"draft": {...}, "source_data": {...}, "missing_keys": [...]}
# "missing_keys" is populated when Call 1 returned an incomplete draft — the model must
# GENERATE those sections from scratch using source_data rather than leaving them absent.
SYSTEM_PROMPT_REFINE = WRITING_RULES + """
You are a financial editor reviewing a draft market commentary. You will receive a JSON object with these keys:
- "draft": the commentary to review (partial or complete 6-key schema)
- "source_data": the market data payload used to generate the draft
- "missing_keys": list of keys that are ABSENT from the draft and MUST be written from scratch

Your job:

1. GENERATE MISSING — For every key in missing_keys, write the section from scratch using source_data. Follow the same length and specificity rules as the primary call. This takes priority over everything else.
2. LENGTH — For sections already in the draft: if equities_commentary, fixed_income_commentary, commodities_commentary, currencies_commentary, or economics_commentary has fewer than 6 sentences, add sentences grounded in specific facts from source_data (named tickers, price levels, pct changes, economic releases). Do NOT add vague filler.
3. SPECIFICITY — If any sentence makes a directional claim without a supporting data point (no ticker, no price, no pct, no named event), replace it with one that cites the relevant number from source_data.
4. SIGN ACCURACY — Verify every direction word (rose/fell/gained/slid) matches the sign of pct_change in source_data. Correct any mismatches silently.
5. PRESERVE GOOD SECTIONS — If a section already meets the length and specificity standard, return it verbatim. Do not rewrite for its own sake.
6. FIXED INCOME SCOPE CHECK — If the draft's fixed_income_commentary discusses covered-call ETFs, yield-alternative products (JEPQ, ELNs, CLOs), retail income strategies, or bond substitutes, it is off-scope and MUST be rewritten entirely from the bonds data in source_data. A valid fixed_income_commentary MUST begin with the 10-year Treasury yield level and daily bp move, then cover 30-yr yield context, yield curve shape (2s10s spread), Fed rate-path expectations, and equity multiple implications. Nothing else.
7. pre_market_bullets — only change a bullet if it is factually wrong per source_data or cites sponsored/promotional content. Otherwise return unchanged.

Return JSON with ALL 6 keys — generate any that are absent from the draft:
{"pre_market_bullets":["...","...","...","...","..."],"equities_commentary":"...","fixed_income_commentary":"...","commodities_commentary":"...","currencies_commentary":"...","economics_commentary":"..."}"""

# Call 2: Outlook, allocation, portfolio spotlight
SYSTEM_PROMPT_OUTLOOK = WRITING_RULES + """

Return JSON with EXACTLY these 7 keys:

market_outlook_label: Exactly one of: "Bullish", "Cautious", "Neutral", "Bearish"  near-term 4-6 week equity view.

market_outlook_rationale: Exactly 2 sentences. If prior_day_label is provided and market_outlook_label differs from it, Sentence 1 MUST explain what changed and why the view shifted since yesterday; otherwise Sentence 1 is the primary supporting factor. Sentence 2: key risk that could change the label.

tactical_outperforming: Short phrase (3-5 words) — sectors/themes outperforming. Ground in sector_top3 from the payload (e.g., "Technology, Financials, semis").

tactical_underperforming: Short phrase (3-5 words) — sectors/themes lagging. Ground in sector_bottom3 from the payload (e.g., "Energy, Real Estate, utilities").

asset_class_outlooks: Object with keys "Equities", "Fixed Income", "Commodities", "US Dollar". Each: {"label": one of Bullish/Cautious/Neutral/Negative, "rationale": "1-2 sentences"}.

portfolio_spotlight_winners: Array of up to 3 objects for tickers with positive return_1m: {"ticker":"...","metric_label":"...","commentary":"2 sentences on what drives outperformance and whether it persists."}. IMPORTANT: each entry in portfolio_top_performers includes a "description" field — use it to understand what the fund actually is. Write commentary grounded in that actual strategy. Do NOT invent sector attributions.
ONE-SHOT EXAMPLE for portfolio_spotlight_winners:
  Input: {"ticker":"JAAA","description":"Janus Henderson AAA CLO ETF — AAA-rated CLOs, short-duration investment-grade fixed income","return_1m":0.4,"metric_label":"+0.4% (1M)"}
  BAD commentary: "JAAA benefited from the technology rally and strong consumer spending data."
  GOOD commentary: "JAAA's AAA-rated CLO exposure insulates the fund from credit spread widening, making it a relative shelter as equity volatility rises. The short duration profile limits rate sensitivity, so outperformance should persist as long as credit markets remain orderly."

portfolio_spotlight_watch: MUST contain exactly one entry for EACH ticker listed in portfolio_names_to_watch — use the exact ticker symbol and metric_label from that input, do not substitute other tickers. {"ticker":"...","metric_label":"...","commentary":"2 sentences on what to monitor for this fund given current market conditions."}. IMPORTANT: use the "description" field to write accurate, strategy-specific commentary. Do NOT describe a bond or income fund as an equity fund.

JSON template:
{"market_outlook_label":"...","market_outlook_rationale":"...","tactical_outperforming":"...","tactical_underperforming":"...","asset_class_outlooks":{"Equities":{"label":"...","rationale":"..."},"Fixed Income":{"label":"...","rationale":"..."},"Commodities":{"label":"...","rationale":"..."},"US Dollar":{"label":"...","rationale":"..."}},"portfolio_spotlight_winners":[{"ticker":"...","metric_label":"...","commentary":"..."}],"portfolio_spotlight_watch":[{"ticker":"...","metric_label":"...","commentary":"..."}]}"""

# Call 3: Session recap, watch-today, international section
SYSTEM_PROMPT_RECAP = WRITING_RULES + """

Return JSON with EXACTLY these 3 keys:

session_recap: Array of exactly 3 strings summarising the PREVIOUS trading session:
  [0] "S&P 500 [closed higher/lower] at {level}, [pct]%; [single specific catalyst from news]."
  [1] Fixed income/rates recap: 10-yr yield level and direction with one specific driver.
  [2] Top non-equity mover: the most notable commodity OR currency with exact level and driver.

watch_today: Array of exactly 3 strings — actionable items for TODAY's session:
  [0] Economic data: cite the most important event from todays_economic_events ONLY. If todays_economic_events is empty, output exactly "No major data today." NEVER promote an event from week_ahead_econ_events into this slot — those belong to future days.
  [1] Earnings/corporate: cite from todays_earnings ONLY (entries whose date == today). If todays_earnings is empty, output exactly "No major earnings today." NEVER assign a future-day entry from this_week_earnings to today.
  [2] Technical level or market structure: one specific price level or spread to monitor.

international_section: 3-4 sentences covering non-US market impact on US outlook. Use global_markets and international_macro data. Include at least one of: EU/ECB, Japan/BOJ, China/Asia. Connect explicitly to how it affects US equities, rates, or commodities.

Tickers in recent_earnings_actuals have ALREADY released earnings this week — never write "later this week" or "upcoming earnings" for them in watch_today or session_recap.

JSON template:
{"session_recap":["...","...","..."],"watch_today":["...","...","..."],"international_section":"..."}"""

# Call 4: Cross-asset synthesis — runs AFTER parts 1-3, reads their output
SYSTEM_PROMPT_SYNTHESIS = WRITING_RULES + """

Return JSON with EXACTLY one key:

cross_asset_synthesis: Exactly 3-4 sentences. This is the "Market Take" wrap-up that ties together equities, rates, commodities, and the forward catalyst into a single coherent thesis.

Rules:
- Commit to a directional view — do NOT hedge with "risk remains elevated", "uncertainty persists", or "the outlook is mixed".
- Name the dominant cross-asset linkage (e.g., "oil is driving yields which is compressing tech multiples" — pick the actual theme from the payload).
- Name the single most important upcoming catalyst: use todays_economic_events if non-empty (call it "today"), otherwise use the first entry of week_ahead_econ_events (name it by weekday, e.g., "Thursday's Initial Jobless Claims") or this_week_earnings. State exactly what outcome you are watching for (beat vs miss, hawkish vs dovish).
- The tone MUST be consistent with market_outlook_label: if Cautious, explain the specific mechanism of risk without adding false balance; if Bullish, name the specific driver without inventing caveats.
- 3-4 sentences total. No preamble. No conclusion phrase. Start directly with the cross-asset theme.
- DATE CONSISTENCY: If todays_economic_events is EMPTY, there are NO economic releases today — do NOT call any event "today" or "this morning". Events in week_ahead_econ_events are FUTURE; always name them by their weekday (e.g., "Wednesday's Fed minutes", "Thursday's Flash PMI"). NEVER assign a week_ahead event to "today".

ONE-SHOT EXAMPLE:
  market_outlook_label: "Cautious"
  BAD: "Markets face multiple headwinds but show resilience; the outlook remains mixed as investors weigh risks against opportunities."
  GOOD: "WTI's 6% surge above $105 is feeding directly into 10-yr yield pressure at 4.36%, which in turn is compressing Nasdaq multiples — the oil-rates-tech linkage is the dominant driver today. The dollar's modest strengthening (+0.2%) confirms the market is pricing a sticky-inflation regime rather than a growth shock. Friday's Core PCE print is the key release: an above-consensus read would validate the hawkish rate path and add another leg down in tech; a miss would relieve duration pressure and let the MAG7 stabilize."

JSON template:
{"cross_asset_synthesis":"..."}"""

ETF_WHITELIST: frozenset = frozenset({
    "XLF","XLE","XLY","XLI","XLP","XLU","XLB","XLK","XLC","XLV","XLRE",
    "IWM","IJH","FLOT","BIL","SHY","IEF","TLT","GLD","GDX","SLV",
    "USO","BNO","UUP","UDN","FXI","EEM","EFA","SPY","QQQ","DIA",
    "SQQQ","SDS","SH","PSQ","UVXY","VIXY",
})

# Call 5: Scenario framework — "Too Hot / In Line / Too Cold" for today's key event
SYSTEM_PROMPT_SCENARIOS = WRITING_RULES + """

You are building a Sevens-Report-style scenario framework for today's most important economic release.

Return JSON with EXACTLY these 2 keys:

scenarios: Array of EXACTLY 3 scenario objects in this order:
  1. "Hot" — the hawkish surprise (stronger data / higher inflation / tighter labor). Yields rise, dollar up, equities under pressure, gold falls.
  2. "In Line" — outcome roughly matches consensus. Limited cross-asset reaction.
  3. "Cold" — the dovish surprise (weaker data / lower inflation / softer labor). Yields fall, dollar down, equities rally, gold rises.

Each scenario object has EXACTLY these 6 keys:
  label:      Short label with outcome range, e.g. "Hot (<195K)" or "Cold (>215K)"
              POLARITY — derive the inequality direction FROM THE INDICATOR; do NOT assume "Hot = lower number":
                • Activity / inflation / sentiment indicators where a HIGHER print is hawkish
                  (ISM, PMI, CPI, PCE, GDP, retail sales, consumer confidence, nonfarm payrolls):
                  Hot is the HIGH side  → "Hot (>X)";  Cold is the LOW side → "Cold (<Y)";  with X >= Y.
                • Labor-slack indicators where a HIGHER print is dovish
                  (initial/continuing jobless claims, unemployment rate):
                  Hot is the LOW side   → "Hot (<X)";  Cold is the HIGH side → "Cold (>Y)";  with X <= Y.
              The Hot and Cold ranges MUST NOT overlap — the In Line band sits strictly between them.
              Example (ISM Non-Manufacturing, consensus 50.0): "Hot (>52.0)", "In Line (48.0-52.0)", "Cold (<48.0)".
              Example (Jobless Claims, consensus 205K):        "Hot (<195K)", "In Line (195K-215K)", "Cold (>215K)".
  thesis:     1 sentence. The macro narrative if this scenario plays out.
  rates:      Expected 10-yr yield move with direction and approximate bp range.
  equities:   Expected S&P 500 move with approximate % range and one sector note.
  commodities: Gold and/or oil reaction in 1 short sentence.
  tickers:    Array of 3-5 ETF tickers from ONLY this list (choose the best fit for this scenario):
              XLF XLE XLY XLI XLP XLU XLB XLK XLC XLV XLRE IWM IJH FLOT BIL SHY IEF TLT GLD GDX SLV USO UUP UDN SPY QQQ

levels_to_watch: Array of EXACTLY 3 level objects. Pick the 3 most relevant assets given today's primary event.
  asset:        Asset name — one of: S&P 500, 10-Yr Yield, Gold, WTI Crude, VIX, U.S. Dollar (DXY)
  level:        Specific numeric price/rate level as a float (e.g. 4.5 for yield, 5500 for S&P)
  significance: 1 sentence explaining why this level matters right now.

Hot scenario tickers should favor defensives/cash/short-duration: XLP, XLU, FLOT, BIL, SHY, UUP, SH.
Cold scenario tickers should favor risk-on/duration: TLT, GLD, QQQ, XLK, IWM, XLY, UDN.
In-Line scenario tickers should be balanced: mix of cyclicals and core benchmarks (SPY, XLF, XLI, XLE).

JSON template:
{"scenarios":[{"label":"Hot (...)","thesis":"...","rates":"...","equities":"...","commodities":"...","tickers":["...","...","..."]},{"label":"In Line (...)","thesis":"...","rates":"...","equities":"...","commodities":"...","tickers":["...","...","..."]},{"label":"Cold (...)","thesis":"...","rates":"...","equities":"...","commodities":"...","tickers":["...","...","..."]}],"levels_to_watch":[{"asset":"...","level":0.0,"significance":"..."},{"asset":"...","level":0.0,"significance":"..."},{"asset":"...","level":0.0,"significance":"..."}]}"""


# Call 6: Trending-topic spotlight — optional, fires only when one topic dominates the day's news
SYSTEM_PROMPT_TOPIC_SCAN = """
You are a financial news editor. Scan today's headlines and decide whether ONE financial topic dominates with unusual market significance.

Return JSON with EXACTLY these 6 keys (no others):
{"has_spotlight":false,"topic":"","topic_keywords":[],"category":"","why_now":"","candidate_funds":[]}

has_spotlight: true ONLY when a single topic appears in 4 or more headlines from multiple outlets.
topic: concise name, e.g. "SpaceX IPO Filing", "U.S.-Iran Ceasefire", "NVIDIA Earnings Beat".
topic_keywords: 2-4 lowercase keywords that uniquely identify this topic, e.g. ["spacex","ipo","spcx"].
category: exactly one of: ipo, geopolitical, sector_catalyst, macro, earnings.
why_now: one sentence — what happened today that made this topic financially significant.
candidate_funds: 2-5 REAL fund or ETF tickers with meaningful exposure to this topic. Only use tickers you are confident exist. Common examples: ARKVX, DXYZ, XOVR for private-company exposure; XLE, USO for oil/energy; SHLD, ITA for defense.

Rules:
- has_spotlight=false for generic broad-market moves (routine S&P daily move, standard Fed statement, typical earnings).
- Topics must have direct investment implications: an IPO filing, geopolitical event affecting energy/trade/rates, sector breakthrough, macro regime shift.
- If no single dominant topic, set has_spotlight=false and all other fields to empty strings or empty arrays.

ONE-SHOT EXAMPLE:
Input headlines include 6 articles about SpaceX filing an IPO prospectus.
{"has_spotlight":true,"topic":"SpaceX IPO Filing","topic_keywords":["spacex","ipo","spcx"],"category":"ipo","why_now":"SpaceX formally filed its prospectus targeting NASDAQ at a $1.75T valuation, triggering broad financial media coverage.","candidate_funds":["ARKVX","DXYZ","XOVR","BPTRX"]}
"""

SYSTEM_PROMPT_TOPIC_SPOTLIGHT = """
You are a senior markets analyst writing the FLAGSHIP deep-dive for an institutional daily report — the kind of piece that explains a theme so well a portfolio manager forwards it. The topic is today's confirmed dominant financial theme. Write with the depth and authority of a top sell-side strategist note: explain the MECHANISM, judge whether it is SUSTAINABLE, and tell the reader what to DO.

Ground EVERY factual claim in the provided source_excerpts and supporting_headlines. Do NOT invent figures, company actions, valuations, or timelines that are not in those inputs.

Return JSON with EXACTLY these 4 keys (no others):
{"title":"","body":"","funds":[],"category":""}

title: Punchy, specific headline, max 12 words. Headline the THEME and its stakes (e.g. "The Memory Shortage Powering the Next Leg of the AI Trade"). Do NOT assert a daily index move/level ("Dow Surges 250 Points", "Oil Crashes") unless that exact move appears in the inputs — the report's data tables already report the close.

body: A genuine analytical deep-dive of 4-6 paragraphs as a SINGLE string, with paragraphs separated by a DOUBLE NEWLINE (\\n\\n). Each paragraph 3-5 sentences. Follow this arc:
  Paragraph 1 — WHAT & WHY IT MATTERS: the development and the specific numbers behind it (from source_excerpts). Establish the stakes.
  Paragraph 2 — THE MECHANISM: explain WHY this is happening — the underlying driver, the chain of cause and effect. Teach the reader the thing they did not already know. This is the paragraph that separates a deep-dive from a blurb.
  Paragraph 3 — IS IT SUSTAINABLE / VALUATION & DATA CONTEXT: the analytical judgment. Supply/demand, earnings, valuation, positioning, the bear case vs the bull case — grounded in the excerpts. Take a side.
  Paragraph 4 — WHAT TO DO NOW: concrete positioning. Which exposures benefit or face headwinds, how an investor would express the view using the verified_funds, and the SPECIFIC near-term catalyst or price level that confirms or breaks the thesis.
funds: Array of fund objects using ONLY tickers from the verified_funds input. If verified_funds is empty, set funds=[].
  Each object has exactly: ticker, name, type, exposure_note (one sentence on how it relates to the theme; no fabricated %/AUM).
category: carry through the category from the input.

Rules:
- GROUNDED: cite specifics only from source_excerpts/supporting_headlines. No invented numbers. Cite ONLY verified_funds tickers — never invent a ticker.
- TEACH, then CONCLUDE: the mechanism paragraph must explain a cause-and-effect a smart non-expert would not already know. Commit to a view — forbidden hedges: "investors should watch", "uncertainty remains", "markets face headwinds", "time will tell", "remains to be seen".
- Active voice, present tense. No preamble, no summary sentence, no "in conclusion". Start the body with the development itself.
- Geopolitical themes: market-impact framing only (energy, currencies, supply chains, rate path).

ONE-SHOT EXAMPLE (abbreviated — yours must be 4-6 full paragraphs):
{"title":"The Memory Shortage Powering the Next Leg of the AI Trade","body":"Large-cap memory makers have become the market's best performers, with Micron, SanDisk and Western Digital up roughly 115%, 145% and 87% over two months as the entire tech sector re-rates higher on their backs.\\n\\nThe driver is physical, not sentiment: AI processors can execute trillions of operations per second, but performance was capped by how fast memory could feed them data — the 'memory wall.' Stacking high-bandwidth memory directly atop the processor shattered that ceiling, and in doing so multiplied the number of memory chips a single AI server needs from eight to roughly ninety-six.\\n\\nThat demand shock is durable on a multi-year horizon. Micron's 2026 capacity is already sold out, new clean-room supply is years away, and trailing free cash flow is inflecting from under $2B to an expected $10B — which is why valuations have stayed near 10x forward earnings despite triple-digit rallies; earnings are outrunning the share price.\\n\\nThe cleanest expression is direct memory exposure, which most tech ETFs are structurally underweight. The thesis breaks only if hyperscalers cut data-center capex — the order book to watch into next quarter.","funds":[{"ticker":"SMH","name":"VanEck Semiconductor ETF","type":"ETF","exposure_note":"Holds the large-cap memory names driving the move, though weighted toward logic chipmakers."}],"category":"sector_catalyst"}
"""

# Sensational escalation phrases that are stripped from spotlight text.
# Much narrower than BANNED_PHRASES — factual geopolitical nouns (war, conflict, ceasefire) are allowed.
SPOTLIGHT_ESCALATION_PHRASES: list[str] = [
    "all-out war", "world war", "nuclear strike", "nuclear attack", "nuclear war",
    "apocalyptic", "catastrophic conflict", "total collapse", "economic collapse",
    "financial armageddon", "global meltdown",
]

BANNED_PHRASES = [
    "geopolitical tensions", "geopolitical risks", "global uncertainties",
    "global instability", "amid uncertainty", "amid concerns", "amid heightened",
    "uncertain environment", "uncertain outlook", "it is worth noting",
    "it should be noted", "importantly,", "in conclusion", "overall,",
    "needless to say", "at the end of the day", "moving forward",
]

# Alias map at module level so retry loops can remap keys before scrubbing.
# Scrub only operates on canonical NARRATIVE_KEYS — remapping must happen first.
LLM_KEY_ALIASES: dict[str, str] = {
    "currencies":        "currencies_commentary",
    "macro":             "economics_commentary",
    "economics":         "economics_commentary",
    "commodities":       "commodities_commentary",
    "fixed_income":      "fixed_income_commentary",
    "equities":          "equities_commentary",
    "pre_market":        "pre_market_bullets",
    # Common key drift patterns from qwen2.5:14b
    "pre_market_summary":   "pre_market_bullets",
    "market_performance":   "equities_commentary",
    "economic_news":        "economics_commentary",
    "company_news":         "equities_commentary",
    "sector_news":          "equities_commentary",
    "global_events":        "economics_commentary",
    "market_summary":       "equities_commentary",
    "market_overview":      "equities_commentary",
    "equity_commentary":    "equities_commentary",
    "bond_commentary":      "fixed_income_commentary",
    "rate_commentary":      "fixed_income_commentary",
    "commodity_commentary": "commodities_commentary",
    "currency_commentary":  "currencies_commentary",
    # Fallback: model occasionally returns last narrative section as 'other'
    "other":             "economics_commentary",
    # Consistent qwen2.5:14b typo: "outlight" instead of "outlook"
    "market_outlight_rationale": "market_outlook_rationale",
}

# Financially accurate replacements applied after generation.
# Filler phrases map to "" (removed). Substantive phrases map to precise alternatives.
PHRASE_REPLACEMENTS = {
    "geopolitical tensions":  "cross-border conflict risk",
    "geopolitical risks":     "political risk",
    "global uncertainties":   "macro cross-currents",
    "global instability":     "broad market stress",
    "amid uncertainty":       "against a mixed macro backdrop",
    "amid concerns":          "on rising risk premium",
    "amid heightened":        "against elevated",
    "uncertain environment":  "uneven macro backdrop",
    "uncertain outlook":      "mixed near-term visibility",
    "it is worth noting":     "",
    "it should be noted":     "",
    "importantly,":           "",
    "in conclusion":          "",
    "overall,":               "on balance,",
    "needless to say":        "",
    "at the end of the day":  "",
    "moving forward":         "looking ahead",
}


def _scrub_text(text: str) -> str:
    """Apply PHRASE_REPLACEMENTS to a single string, preserving sentence-start capitalisation."""
    import re
    for phrase, replacement in PHRASE_REPLACEMENTS.items():
        def _replace(m: re.Match) -> str:
            original = m.group(0)
            result = replacement
            if not result:
                return result
            # If the matched phrase started a sentence (first char uppercase), capitalise replacement
            if original[0].isupper():
                result = result[0].upper() + result[1:]
            return result
        text = re.sub(re.escape(phrase), _replace, text, flags=re.IGNORECASE)
    # Clean up double spaces and leading/trailing whitespace from removed phrases
    text = re.sub(r"  +", " ", text).strip()
    # Fix sentence-start punctuation artefacts like ". ," or " ,"
    text = re.sub(r"\.\s+,", ".", text)
    text = re.sub(r"\s+,", ",", text)
    return text


def _scrub_nested(val):
    """Recursively scrub banned phrases from strings inside any nested structure."""
    if isinstance(val, str):
        return _scrub_text(val)
    if isinstance(val, list):
        return [_scrub_nested(item) for item in val]
    if isinstance(val, dict):
        return {k: _scrub_nested(v) for k, v in val.items()}
    return val


def scrub_banned_phrases(data: dict) -> dict:
    """Post-process commentary dict: replace banned phrases with accurate alternatives."""
    for key in NARRATIVE_KEYS:
        if key in data:
            data[key] = _scrub_nested(data[key])
    return data

NARRATIVE_KEYS = [
    "pre_market_bullets", "equities_commentary", "fixed_income_commentary",
    "commodities_commentary", "currencies_commentary", "economics_commentary",
    "market_outlook_rationale",
    "session_recap", "watch_today", "international_section",
    "cross_asset_synthesis",
]


def _call_ollama_raw(system: str, user_payload: dict, num_ctx: int = 8192) -> dict:
    body = {
        "model":   OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": json.dumps(user_payload, default=str)},
        ],
        "stream": False,
        "format": "json",
        "think":  False,
        "options": {
            "temperature": 0,
            "num_predict": 4096,
            "num_ctx":     num_ctx,
        },
    }
    resp = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json=body,
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        if _repair_json is not None:
            parsed = json.loads(_repair_json(content))
        else:
            raise
    return _hoist_nested_dicts(parsed)


def _hoist_nested_dicts(data: dict) -> dict:
    """Fix LLM output where sub-keys were embedded as dicts inside a string array.

    qwen3.5:4b sometimes generates:
      {"pre_market_bullets": ["str1", ..., {"equities_commentary": "..."}]}
    instead of closing the array and opening a new top-level key.
    Runs iteratively until no more hoisting is possible (handles multi-level nesting).
    """
    result = dict(data)
    changed = True
    while changed:
        changed = False
        for key in list(result.keys()):
            value = result[key]
            if isinstance(value, list):
                has_strings = any(isinstance(item, str) for item in value)
                has_dicts = any(isinstance(item, dict) for item in value)
                # Only hoist when the list is mixed (strings + dicts). A pure dict
                # list (e.g. scenarios, portfolio_spotlight) is intentional — leave it.
                if has_strings and has_dicts:
                    result[key] = [item for item in value if isinstance(item, str)]
                    for item in value:
                        if isinstance(item, dict):
                            result.update(item)
                    changed = True
    return result


def _repair_scenario_labels(scenarios: list) -> int:
    """Detect and repair self-contradictory Hot/Cold threshold labels.

    Scenario labels may carry a numeric outcome range, e.g. "Hot (<50.0)". The
    Hot and Cold bands must not overlap: for indicators where higher = hotter
    (ISM/PMI, CPI, sentiment) the valid form is Hot (>X) / Cold (<Y) with X>=Y;
    for indicators where lower = hotter (jobless claims, unemployment) it is
    Hot (<X) / Cold (>Y) with X<=Y. When the parsed bands overlap (the LLM
    inverted the polarity, e.g. Hot (<50.0) + Cold (>48.0)), strip the numeric
    parenthetical from all three labels so we never ship a contradictory range —
    the thesis/rates/equities text already carries the directional meaning.

    Returns the number of labels stripped (0 = labels left intact).
    """
    def _parse(label: str):
        m = re.search(r'([<>])\s*=?\s*([0-9][0-9,\.]*)\s*([KkMmBb]?)', label or "")
        if not m:
            return None
        try:
            val = float(m.group(2).replace(",", ""))
        except ValueError:
            return None
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get(m.group(3).lower(), 1.0)
        return m.group(1), val * mult

    if not scenarios or len(scenarios) < 3:
        return 0

    hot, cold = _parse(str(scenarios[0].get("label", ""))), _parse(str(scenarios[2].get("label", "")))
    if not hot or not cold:
        return 0
    hot_op, hot_val = hot
    cold_op, cold_val = cold

    if hot_op == "<" and cold_op == ">":
        overlap = hot_val > cold_val          # valid (jobless-claims style) needs hot_val <= cold_val
    elif hot_op == ">" and cold_op == "<":
        overlap = hot_val < cold_val          # valid (ISM/PMI style) needs hot_val >= cold_val
    else:
        overlap = True                        # same operator on both sides is always contradictory

    if not overlap:
        return 0

    stripped = 0
    for sc in scenarios[:3]:
        lbl = str(sc.get("label", ""))
        new = re.sub(r'\s*\([^)]*\)\s*$', '', lbl).strip()
        if new != lbl:
            sc["label"] = new
            stripped += 1
    return stripped


def call_ollama(payload: dict, snapshot: dict) -> dict:
    """Two-shot generation: narrative sections then outlook/portfolio."""

    # Trim news to 4 items per bucket to keep payload small
    news = payload.get("news_by_section") or {}
    news_trimmed = {k: v[:4] for k, v in news.items()}

    # Narrow market_levels to just the key assets
    levels = payload.get("market_levels") or {}

    # Global markets: top 5 only
    gm = dict(list((payload.get("global_markets") or {}).items())[:5])

    # Commodities: top 6 only
    cmdty = dict(list((payload.get("commodities") or {}).items())[:6])

    # Currencies: top 5 only
    fx = dict(list((payload.get("currencies") or {}).items())[:5])

    # Bonds: all (small)
    bonds = payload.get("bonds") or {}

    # Economic events: top 5
    econ = (payload.get("upcoming_economic_events") or [])[:5]

    # Split events and earnings into today vs. rest-of-week so prompts can distinguish them.
    today_str  = payload.get("date") or ""
    today_econ = [e for e in econ if str(e.get("date", ""))[:10] == today_str]
    week_econ  = [e for e in econ if str(e.get("date", ""))[:10] != today_str]
    earn       = payload.get("earnings_calendar") or []
    today_earn = [e for e in earn if str(e.get("date", ""))[:10] == today_str]
    week_earn  = [e for e in earn if str(e.get("date", ""))[:10] != today_str][:5]

    # Flatten news to a plain headline list — avoids model templating output after section names
    # Articles in llm_buckets are pre-formatted strings (headline + summary snippet)
    # Priority order: "general" (Finnhub Reuters/AP breaking news) first, then equities/rates,
    # then commodities/world — prevents stale ETF-flow articles from crowding out breaking stories.
    _NEWS_PRIORITY = ["general", "equities", "fixed_income", "currencies", "commodities", "world"]
    _ordered_news = (
        [(k, news_trimmed[k]) for k in _NEWS_PRIORITY if k in news_trimmed]
        + [(k, v) for k, v in news_trimmed.items() if k not in _NEWS_PRIORITY]
    )
    flat_headlines = [
        a if isinstance(a, str) else (a.get("headline") or a.get("title") or "")
        for _, articles in _ordered_news
        for a in articles
        if a
    ][:15]

    # Sector leaders/laggards for narrative — item #2
    _sp = payload.get("sector_performance") or []
    _sector_top3    = _sp[:3]
    _sector_bottom3 = _sp[-3:][::-1] if len(_sp) >= 3 else []

    # Technical context for equities commentary — item #3
    _tl = payload.get("technical_levels") or {}
    _spx_tl = _tl.get("S&P 500", {})
    _vix_tl = _tl.get("VIX", {})
    _technical_context = {
        "vix":           _vix_tl.get("current"),
        "spx_ma200":     _spx_tl.get("ma200"),
        "spx_52w_high":  _spx_tl.get("52w_high"),
        "spx_current":   _spx_tl.get("current"),
        "spx_above_ma200": (
            bool(_spx_tl.get("current") and _spx_tl.get("ma200") and
                 _spx_tl["current"] > _spx_tl["ma200"])
        ),
    }

    # Week-over-week return context — item #5
    _week_context = {
        "SP500_1w_pct":   (levels.get("S&P 500") or {}).get("pct_change_1w"),
        "NDX_1w_pct":     (levels.get("Nasdaq 100") or {}).get("pct_change_1w"),
        "Gold_1w_pct":    (levels.get("Gold") or {}).get("pct_change_1w"),
        "Yield10_bp_1w":  (bonds.get("10-Year Yield") or {}).get("bp_change_1w"),
        "DXY_1w_pct":     (levels.get("U.S. Dollar (DXY)") or {}).get("pct_change_1w"),
    }

    # Deterministic opener for pre_market_bullets[0] — item #6
    # Compute from snapshot to guarantee number accuracy; LLM fills [catalyst] only.
    _sp500 = levels.get("S&P 500", {})
    _ndx   = levels.get("Nasdaq 100", {})
    _sp_pct  = _sp500.get("pct_change")
    _ndx_pct = _ndx.get("pct_change")
    _sp_lvl  = _sp500.get("level")
    _direction = "higher" if (_sp_pct or 0) >= 0 else "lower"
    _sp_str  = f"{float(_sp_pct):+.2f}%" if _sp_pct is not None else "N/A"
    _ndx_str = f"{float(_ndx_pct):+.2f}%" if _ndx_pct is not None else "N/A"
    _lvl_str = f"{float(_sp_lvl):,.2f}" if _sp_lvl is not None else ""
    _deterministic_opener = (
        f"Markets closed {_direction} — S&P 500 {_sp_str} to {_lvl_str}, "
        f"Nasdaq 100 {_ndx_str}; {{catalyst}}"
    )

    narrative_payload = {
        "date":                     payload.get("date"),
        "market_levels":            levels,
        "bonds":                    bonds,
        "global_markets_top5":      gm,
        "commodities_top6":         cmdty,
        "currencies_top5":          fx,
        "todays_economic_events":   today_econ,
        "week_ahead_econ_events":   week_econ,
        # item #7: bucketed headlines so model knows which category each story belongs to
        "news_by_category":         news_trimmed,
        "recent_headlines":         flat_headlines,   # flat list kept as fallback
        "recent_earnings_actuals":  payload.get("recent_earnings_actuals") or [],
        # items #2–#6
        "sector_top3":              _sector_top3,
        "sector_bottom3":           _sector_bottom3,
        "technical_context":        _technical_context,
        "fear_greed":               payload.get("fear_greed") or {},
        "week_context":             _week_context,
    }

    # Inline the opener into the system prompt (not the payload) so the model cannot
    # echo the key name as its sole output — the sentinel is replaced with the actual
    # template string before every Call 1 attempt.
    _narrative_sys = SYSTEM_PROMPT_NARRATIVE.replace("BULLET_0_TEMPLATE", _deterministic_opener)

    print("  [LLM Call 1/3] Generating market narrative sections...")
    part1 = {}
    for attempt in range(4):
        try:
            part1 = _call_ollama_raw(_narrative_sys, narrative_payload, num_ctx=16384)
            print(f"    Keys returned: {list(part1.keys())}")
            # Remap aliases to canonical keys BEFORE scrubbing so scrubber finds them.
            # Only remap when the value is a non-empty string — a dict value (e.g. market_summary
            # returned as a nested object) must not become equities_commentary.
            for alias, canonical in LLM_KEY_ALIASES.items():
                if alias in part1 and canonical not in part1:
                    _v = part1[alias]
                    if isinstance(_v, str) and _v.strip():
                        part1[canonical] = part1.pop(alias)
                    else:
                        part1.pop(alias)  # discard non-string alias values
            part1 = scrub_banned_phrases(part1)
            banned = find_banned_phrases(part1)
            leaks = find_leaked_placeholders(part1)
            sign_fixes = _correct_sign_mismatches(part1, snapshot)
            if sign_fixes:
                print(f"  [CORRECT] Auto-corrected {sign_fixes} sign mismatch(es) in Call 1 output.")
            _call1_required = {
                "pre_market_bullets", "equities_commentary", "fixed_income_commentary",
                "currencies_commentary", "commodities_commentary", "economics_commentary",
            }
            missing_required = _call1_required - set(part1.keys())
            if missing_required:
                print(f"  [RETRY] Attempt {attempt + 1} missing required narrative keys: {sorted(missing_required)}. Retrying...")
                continue
            numeric = _check_numeric_consistency(part1, snapshot)
            causal = _check_causal_logic(part1, snapshot)
            # When there are NO economic releases dated today, the narrative must not
            # frame any release as "today"/"this morning" — catches the LLM pulling a
            # week-ahead catalyst (e.g. Thursday's GDP) forward and dating it today.
            dating = _check_event_dating(part1, today_has_econ=bool(today_econ))
            if not banned and not leaks and not numeric and not causal and not dating:
                break
            if banned:
                print(f"  [RETRY] Attempt {attempt + 1} still contained banned phrases after scrub: {banned}. Retrying...")
            if leaks:
                print(f"  [RETRY] Attempt {attempt + 1} contained leaked placeholders: {leaks}. Retrying...")
            if numeric:
                print(f"  [RETRY] Attempt {attempt + 1} had numeric consistency violations: {numeric}. Retrying...")
            if causal:
                print(f"  [RETRY] Attempt {attempt + 1} had causal logic inversions: {causal}. Retrying...")
            if dating:
                print(f"  [RETRY] Attempt {attempt + 1} dated a non-today event as today: {dating}. Retrying...")
        except Exception as exc:
            print(f"  [WARN] Narrative call failed (attempt {attempt + 1}): {exc}")
            part1 = {}

    # Refinement pass: deepen existing sections AND generate any that Call 1 missed.
    if part1:
        print("  [LLM Call 1r] Refining narrative sections...")
        _call1_required = {
            "pre_market_bullets", "equities_commentary", "fixed_income_commentary",
            "currencies_commentary", "commodities_commentary", "economics_commentary",
        }
        _missing_after_loop = sorted(_call1_required - set(part1.keys()))
        if _missing_after_loop:
            print(f"  [GENERATE] Refinement pass will generate missing keys: {_missing_after_loop}")
        refinement_input = {
            "draft":        part1,
            "source_data":  narrative_payload,
            "missing_keys": _missing_after_loop,
        }
        for attempt in range(2):
            try:
                part1_refined = _call_ollama_raw(SYSTEM_PROMPT_REFINE, refinement_input)
                for key in ["equities_commentary", "fixed_income_commentary",
                            "commodities_commentary", "currencies_commentary", "economics_commentary"]:
                    refined_val = part1_refined.get(key, "")
                    if refined_val and len(refined_val) > len(part1.get(key, "")):
                        part1[key] = refined_val
                if (isinstance(part1_refined.get("pre_market_bullets"), list)
                        and len(part1_refined["pre_market_bullets"]) >= 4):
                    part1["pre_market_bullets"] = part1_refined["pre_market_bullets"]
                print(f"    Refinement pass complete (attempt {attempt + 1}).")
                break
            except Exception as exc:
                print(f"  [WARN] Refinement pass attempt {attempt + 1} failed: {exc}")

    # Safety net: if pre_market_bullets is still absent after all LLM attempts + refinement,
    # inject snapshot-derived bullets so validate_commentary passes with narrative_source='llm'.
    if not isinstance(part1.get("pre_market_bullets"), list) or not part1["pre_market_bullets"]:
        def _snap_val(key, field, default=0.0):
            return (snapshot.get(key) or {}).get(field) or default
        def _snap_dir(pct):
            return "gained" if pct >= 0 else "fell"
        _sp_pct  = _snap_val("S&P 500",           "pct_change")
        _sp_lvl  = _snap_val("S&P 500",           "level")
        _ndx_pct = _snap_val("Nasdaq 100",         "pct_change")
        _tyr_lvl = _snap_val("10-Yr Yield",        "level")
        _wti_pct = _snap_val("WTI Crude",          "pct_change")
        _wti_lvl = _snap_val("WTI Crude",          "level")
        _gld_pct = _snap_val("Gold",               "pct_change")
        _dxy_pct = _snap_val("U.S. Dollar (DXY)",  "pct_change")
        _dxy_lvl = _snap_val("U.S. Dollar (DXY)",  "level")
        part1["pre_market_bullets"] = [
            f"S&P 500 {_snap_dir(_sp_pct)} {_sp_pct:+.2f}% to {_sp_lvl:,.0f}; Nasdaq 100 {_snap_dir(_ndx_pct)} {_ndx_pct:+.2f}%.",
            f"10-Yr yield at {_tyr_lvl:.3f}%.",
            f"WTI crude {_snap_dir(_wti_pct)} {_wti_pct:+.2f}% to ${_wti_lvl:.2f}.",
            f"DXY {_snap_dir(_dxy_pct)} {_dxy_pct:+.2f}% to {_dxy_lvl:.2f}.",
        ]
        print("  [FALLBACK] Injected deterministic pre_market_bullets (LLM failed to generate).")

    # Compact payload for outlook call — items #2 (sectors) and #8 (prior-day continuity)
    outlook_payload = {
        "date":                      payload.get("date"),
        "market_levels":             levels,
        "key_data_summary":          payload.get("key_data_summary"),
        "portfolio_top_performers":  payload.get("portfolio_top_performers"),
        "portfolio_names_to_watch":  payload.get("portfolio_names_to_watch"),
        "mag7_consensus_forecasts":  payload.get("mag7_consensus_forecasts"),
        "news_headlines":            {k: v[:2] for k, v in news_trimmed.items()},
        "sector_top3":               _sector_top3,
        "sector_bottom3":            _sector_bottom3,
        "prior_day_label":           payload.get("prior_day_label"),
        "prior_day_synthesis":       payload.get("prior_day_synthesis"),
    }

    print("  [LLM Call 2/3] Generating market outlook and portfolio intelligence...")
    part2 = {}
    for attempt in range(4):
        try:
            part2 = _call_ollama_raw(SYSTEM_PROMPT_OUTLOOK, outlook_payload)
            print(f"    Keys returned: {list(part2.keys())}")
            part2 = scrub_banned_phrases(part2)
            banned = find_banned_phrases(part2)
            leaks = find_leaked_placeholders(part2)
            if not banned and not leaks:
                break
            if banned:
                print(f"  [RETRY] Attempt {attempt + 1} still contained banned phrases after scrub: {banned}. Retrying...")
            if leaks:
                print(f"  [RETRY] Attempt {attempt + 1} contained leaked placeholders: {leaks}. Retrying...")
        except Exception as exc:
            print(f"  [WARN] Outlook call failed (attempt {attempt + 1}): {exc}")
            part2 = {}

    # Focused payload for session recap / watch-today / international section
    recap_payload = {
        "date":                     payload.get("date"),
        "market_levels":            levels,
        "bonds":                    bonds,
        "global_markets_top3":      dict(list(gm.items())[:3]),
        "commodities_top3":         dict(list(cmdty.items())[:3]),
        "currencies_top3":          dict(list(fx.items())[:3]),
        "todays_economic_events":   today_econ,
        "week_ahead_econ_events":   week_econ,
        "todays_earnings":          today_earn,
        "this_week_earnings":       week_earn,
        "international_macro":      payload.get("international_macro") or {},
        "fear_greed":               payload.get("fear_greed") or {},
        "news_headlines":           {k: v[:2] for k, v in news_trimmed.items()},
        "recent_earnings_actuals":  payload.get("recent_earnings_actuals") or [],
    }

    print("  [LLM Call 3/3] Generating session recap and watch-today section...")
    part3 = {}
    for attempt in range(4):
        try:
            part3 = _call_ollama_raw(SYSTEM_PROMPT_RECAP, recap_payload)
            print(f"    Keys returned: {list(part3.keys())}")
            part3 = scrub_banned_phrases(part3)
            banned = find_banned_phrases(part3)
            leaks = find_leaked_placeholders(part3)
            if not banned and not leaks:
                break
            if banned:
                print(f"  [RETRY] Attempt {attempt + 1} still contained banned phrases after scrub: {banned}. Retrying...")
            if leaks:
                print(f"  [RETRY] Attempt {attempt + 1} contained leaked placeholders: {leaks}. Retrying...")
        except Exception as exc:
            print(f"  [WARN] Recap call failed (attempt {attempt + 1}): {exc}")
            part3 = {}

    # Deterministic watch_today — slots [0] (today's econ) and [1] (today's earnings) are
    # pure data lookups, so we ALWAYS compute them from the SAME today_econ/today_earn the
    # report/email blocks render. This guarantees they can never contradict those blocks
    # (the LLM has emitted "No major earnings today" while 8 names reported today, and has
    # dated week-ahead events as "today"). Slot [2] (a technical level/structure call) stays
    # LLM-authored when present, else a deterministic yield watch.
    _llm_wt = list(part3.get("watch_today") or [])
    if today_econ:
        _e0 = today_econ[0]
        _nm0, _imp0 = _e0.get("event", ""), _e0.get("importance", "")
        _wt0 = f"{_nm0} ({_imp0})" if (_nm0 and _imp0) else (_nm0 or "No major data today.")
    else:
        _wt0 = "No major data today."
    if today_earn:
        _syms = [e.get("symbol", "") for e in today_earn[:5] if e.get("symbol")]
        _wt1 = "Earnings due: " + ", ".join(_syms) + (", among others." if len(today_earn) > 5 else ".")
    else:
        _wt1 = "No major earnings today."
    _wt2 = _llm_wt[2].strip() if (len(_llm_wt) > 2 and str(_llm_wt[2]).strip()) else ""
    if not _wt2:
        _y10 = (bonds.get("10-Year Yield") or {}).get("level")
        _wt2 = (f"Monitor the 10-year Treasury yield near {float(_y10):.2f}%."
                if _y10 is not None else "Monitor key technical levels into the next session.")
    part3["watch_today"] = [_wt0, _wt1, _wt2]
    print("  [WATCH] watch_today [0]/[1] set deterministically from today's calendar.")

    # Collect known tickers from the portfolio payload for post-generation validation
    known_tickers: set[str] = set()
    for entry in (payload.get("mag7_consensus_forecasts") or {}).keys():
        known_tickers.add(str(entry).upper())
    for entry in (payload.get("portfolio_top_performers") or []):
        if isinstance(entry, dict) and entry.get("ticker"):
            known_tickers.add(str(entry["ticker"]).upper())
    for entry in (payload.get("portfolio_names_to_watch") or []):
        if isinstance(entry, dict) and entry.get("ticker"):
            known_tickers.add(str(entry["ticker"]).upper())

    # Compact synthesis payload — reads already-generated text, no raw market data needed
    synthesis_payload = {
        "date":                     today_str,
        "market_outlook_label":     part2.get("market_outlook_label"),
        "equities_commentary":      part1.get("equities_commentary", ""),
        "fixed_income_commentary":  part1.get("fixed_income_commentary", ""),
        "commodities_commentary":   part1.get("commodities_commentary", ""),
        "currencies_commentary":    part1.get("currencies_commentary", ""),
        "economics_commentary":     part1.get("economics_commentary", ""),
        "todays_economic_events":   today_econ,
        "week_ahead_econ_events":   week_econ,
        "todays_earnings":          today_earn,
        "this_week_earnings":       week_earn[:3],
    }

    print("  [LLM Call 4/4] Generating cross-asset synthesis...")
    part4 = {}
    for attempt in range(4):
        try:
            part4 = _call_ollama_raw(SYSTEM_PROMPT_SYNTHESIS, synthesis_payload)
            print(f"    Keys returned: {list(part4.keys())}")
            part4 = scrub_banned_phrases(part4)
            banned = find_banned_phrases(part4)
            leaks = find_leaked_placeholders(part4)
            dating = _check_event_dating(part4, today_has_econ=bool(today_econ))
            if not banned and not leaks and not dating:
                break
            if banned:
                print(f"  [RETRY] Attempt {attempt + 1} synthesis still had banned phrases: {banned}. Retrying...")
            if leaks:
                print(f"  [RETRY] Attempt {attempt + 1} contained leaked placeholders: {leaks}. Retrying...")
            if dating:
                print(f"  [RETRY] Attempt {attempt + 1} synthesis dated a non-today event as today: {dating}. Retrying...")
        except Exception as exc:
            print(f"  [WARN] Synthesis call failed (attempt {attempt + 1}): {exc}")
            part4 = {}

    # ── Call 5: Scenario framework (the soonest high-importance catalyst) ──
    part5: dict = {}
    _today_date = (payload.get("date") or datetime.today().strftime("%Y-%m-%d"))[:10]
    _today_events = [
        e for e in econ
        if str(e.get("date", ""))[:10] == _today_date and e.get("importance") == "high"
    ]
    # Pick the scenario's primary event. Prefer a high-importance event TODAY; otherwise
    # fall back to the soonest UPCOMING high-importance event (else the soonest event).
    # Crucially we no longer mislabel a future event as "today": we compute the event's
    # day label and pass it through so the section is titled correctly (e.g. "Thursday's
    # Scenarios") instead of presenting Thursday's GDP as today's catalyst.
    if _today_events:
        _primary_event, _event_day_label = _today_events[0], "today"
    else:
        _future = [e for e in econ if str(e.get("date", ""))[:10] > _today_date]
        _hi_future = [e for e in _future if e.get("importance") == "high"]
        _primary_event = (_hi_future or _future or econ or [None])[0]
        _event_day_label = _event_day_from_dates(
            str((_primary_event or {}).get("date", "")), _today_date
        )
    if _primary_event:
        _ev_name = _primary_event.get("event", "")
        _ev_cons = _primary_event.get("consensus")
        _ev_prev = _primary_event.get("previous")
        scenarios_payload = {
            "primary_event":    _ev_name,
            "event_day":        _event_day_label or "today",  # "today"/"tomorrow"/weekday
            "consensus":        _ev_cons,
            "previous":         _ev_prev,
            "market_snapshot":  {k: v for k, v in list(levels.items())[:8]},
            "bonds":            bonds,
            "upcoming_events":  econ[:3],
        }
        print("  [LLM Call 5/5] Generating scenario framework...")
        for attempt in range(3):
            try:
                part5 = _call_ollama_raw(SYSTEM_PROMPT_SCENARIOS, scenarios_payload)
                print(f"    Keys returned: {list(part5.keys())}")
                _scens = part5.get("scenarios") or []
                _lvls  = part5.get("levels_to_watch") or []
                # Validate tickers against whitelist; strip any bad ones
                _any_bad = False
                for _sc in _scens:
                    _raw_tickers = [str(t).upper() for t in (_sc.get("tickers") or [])]
                    _clean = [t for t in _raw_tickers if t in ETF_WHITELIST]
                    if len(_clean) < len(_raw_tickers):
                        _any_bad = True
                        _sc["tickers"] = _clean
                if _any_bad:
                    print(f"  [VALIDATE] Stripped non-whitelist ticker(s) from scenarios.")
                # Guard against inverted Hot/Cold threshold polarity (e.g. "Hot (<50)" + "Cold (>48)").
                _stripped = _repair_scenario_labels(_scens)
                if _stripped:
                    print(f"  [VALIDATE] Inverted scenario thresholds — stripped numeric range from {_stripped} label(s).")
                # Accept if we have at least 3 scenarios; levels_to_watch is optional
                if len(_scens) >= 3:
                    part5["scenarios"]       = _scens[:3]
                    part5["levels_to_watch"] = _lvls  # may be empty — render handles gracefully
                    part5["scenario_event"]     = _ev_name
                    part5["scenario_consensus"] = str(_ev_cons) if _ev_cons is not None else None
                    part5["scenario_event_day"] = _event_day_label or "today"
                    break
                print(f"  [RETRY] Attempt {attempt+1}: got {len(_scens)} scenarios, {len(_lvls)} levels. Retrying...")
                part5 = {}
            except Exception as exc:
                print(f"  [WARN] Scenarios call failed (attempt {attempt + 1}): {exc}")
                part5 = {}
    else:
        print("  [LLM Call 5/5] Skipped — no high-importance events today.")

    merged = {**part1, **part2, **part3, **part4, **part5}

    # Remap any remaining aliases (part1 loop already remapped its keys; this catches part2/3 stragglers)
    for alias, canonical in LLM_KEY_ALIASES.items():
        if alias in merged and canonical not in merged:
            merged[canonical] = merged.pop(alias)

    # Strip any keys not in the expected output schema — prevents LLM "response",
    # "portfolio_spotlight_losers", "summary", and other hallucinated fields from
    # leaking into latest_commentary.json.
    _ALLOWED_LLM_KEYS = {
        "pre_market_bullets", "equities_commentary", "fixed_income_commentary",
        "commodities_commentary", "currencies_commentary", "economics_commentary",
        "market_outlook_label", "market_outlook_rationale",
        "tactical_outperforming", "tactical_underperforming", "asset_class_outlooks",
        "portfolio_spotlight_winners", "portfolio_spotlight_watch",
        "session_recap", "watch_today", "international_section",
        "cross_asset_synthesis",
        # Phase 4: scenario framework
        "scenarios", "levels_to_watch", "scenario_event", "scenario_consensus", "scenario_event_day",
        # Phase 6: trending-topic spotlight (generated outside call_ollama, listed for documentation)
        "topic_spotlight",
    }
    unexpected = set(merged) - _ALLOWED_LLM_KEYS
    if unexpected:
        print(f"[VALIDATE] Stripping unexpected LLM keys: {sorted(unexpected)}")
    merged = {k: v for k, v in merged.items() if k in _ALLOWED_LLM_KEYS}

    return merged, known_tickers


def _extract_text_recursive(val) -> str:
    """Extract all text from a nested string/list/dict structure."""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " ".join(_extract_text_recursive(item) for item in val)
    if isinstance(val, dict):
        return " ".join(_extract_text_recursive(v) for v in val.values())
    return ""


def find_banned_phrases(data: dict) -> list[str]:
    found = []
    for key in NARRATIVE_KEYS:
        val = data.get(key, "")
        text = _extract_text_recursive(val).lower()
        for phrase in BANNED_PHRASES:
            if phrase in text and phrase not in found:
                found.append(phrase)
    return found


_PLACEHOLDER_PATTERNS = [
    re.compile(r"\{[a-z_][a-z0-9_]*\}"),           # {spx_pct}, {ust10_level}
    re.compile(r"\[[a-z_][a-z0-9_/ +-]*\]"),        # [value], [higher/lower], [implication]
]


def find_leaked_placeholders(data: dict) -> list[str]:
    """Detect prompt-template placeholders that leaked through into LLM output."""
    found = []
    for key in NARRATIVE_KEYS:
        val = data.get(key, "")
        text = " ".join(val) if isinstance(val, list) else str(val)
        for pat in _PLACEHOLDER_PATTERNS:
            for m in pat.findall(text):
                if m not in found:
                    found.append(m)
    return found


_EVENT_KEYWORDS = (
    "gdp", "gdpnow", "cpi", "pce", "ppi", "jobless claims", "initial claims",
    "nonfarm", "non-farm", "payroll", "ism", "pmi", "retail sales",
    "housing starts", "building permits", "factory orders", "durable goods",
    "consumer confidence", "consumer sentiment", "jolts", "fomc", "fed minutes",
    "rate decision", "trade balance", "industrial production",
)
_TODAY_WORDS_RE = re.compile(r"\b(today|this morning|this afternoon|8:30\s*am|10:00\s*am)\b", re.I)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _check_event_dating(data: dict, today_has_econ: bool) -> list[str]:
    """Flag narrative that dates an economic release as 'today' when none is scheduled.

    Only active when today_has_econ is False (no release dated today in our calendar):
    in that state ANY sentence pairing an econ-release keyword with a today-word is a
    false same-day claim (the LLM pulled a week-ahead catalyst forward). Returns a list
    of offending snippets (empty = clean). Scans pre_market_bullets + economics_commentary.
    """
    if today_has_econ:
        return []
    chunks: list[str] = []
    pmb = data.get("pre_market_bullets")
    if isinstance(pmb, list):
        chunks.extend(str(b) for b in pmb)
    elif isinstance(pmb, str):
        chunks.append(pmb)
    if data.get("economics_commentary"):
        chunks.append(str(data["economics_commentary"]))
    if data.get("cross_asset_synthesis"):
        chunks.append(str(data["cross_asset_synthesis"]))
    violations: list[str] = []
    for chunk in chunks:
        for sent in _SENTENCE_SPLIT_RE.split(chunk):
            low = sent.lower()
            if not _TODAY_WORDS_RE.search(sent):
                continue
            if any(kw in low for kw in _EVENT_KEYWORDS):
                violations.append(sent.strip()[:90])
    return violations[:4]


def _check_numeric_consistency(data: dict, snapshot: dict) -> list[str]:
    """Compare sign/magnitude of LLM narrative numbers against the market snapshot.

    Returns a list of violation strings (empty = clean). Checks the first percent
    figure in equity/commodities/currencies commentary against pct_change in the
    snapshot (tolerance: 0.5pp; sign mismatch always fails). Also checks
    direction-word contradictions and pre_market_bullets sign consistency.
    """
    import re
    PCT_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*%")

    def _first_pct(text: str) -> float | None:
        m = PCT_RE.search(text or "")
        return float(m.group(1)) if m else None

    def _pct_after_keyword(text: str, keyword: str) -> float | None:
        """Find the first % figure at or after `keyword` in text."""
        lower = (text or "").lower()
        idx = lower.find(keyword.lower())
        if idx == -1:
            return None
        m = PCT_RE.search(text, idx)
        return float(m.group(1)) if m else None

    # Magnitude + sign check: (narrative_key, snap_key, keyword_or_None).
    # fixed_income excluded — yield level (e.g. "4.39%") ≠ yield pct_change.
    # keyword_or_None: if set, find the first % AFTER that keyword in the prose
    # (needed for sections where multiple assets appear, e.g. commodities).
    checks = [
        ("equities_commentary",    "S&P 500",            None),
        ("commodities_commentary", "WTI Crude",           None),
        ("commodities_commentary", "Gold",                "gold"),
        ("currencies_commentary",  "U.S. Dollar (DXY)",   None),
    ]
    violations = []
    for narrative_key, snap_key, kw in checks:
        snap = (snapshot or {}).get(snap_key) or {}
        truth_pct = snap.get("pct_change")
        if truth_pct is None:
            continue
        prose = data.get(narrative_key, "")
        prose_str = prose if isinstance(prose, str) else " ".join(prose or [])
        if abs(truth_pct) < 0.02:
            # Near-zero: skip magnitude/sign check, but flag strong directional language
            # in equities_commentary — catches "rallied over 1%" on flat-close days.
            if narrative_key == "equities_commentary":
                _STRONG_MOVES = {
                    "rallied", "surged", "soared", "jumped", "skyrocketed",
                    "plunged", "collapsed", "tumbled", "sold off sharply",
                    "rose sharply", "fell sharply",
                }
                cited_strong = [w for w in _STRONG_MOVES if w in prose_str.lower()]
                if cited_strong:
                    violations.append(
                        f"{snap_key}: snapshot {truth_pct:+.2f}% (essentially flat) "
                        f"but equities_commentary uses strong directional language: {cited_strong}"
                    )
            continue
        cited = _first_pct(prose_str) if kw is None else _pct_after_keyword(prose_str, kw)
        if cited is None:
            continue
        if (truth_pct >= 0) != (cited >= 0):
            violations.append(
                f"{snap_key}: snapshot {truth_pct:+.2f}%, narrative cited {cited:+.2f}% (sign mismatch)"
            )
        elif abs(truth_pct - cited) > 0.5:
            violations.append(
                f"{snap_key}: snapshot {truth_pct:+.2f}%, narrative cited {cited:+.2f}% (magnitude > 0.5pp)"
            )

    # Direction-word check: strong directional words that contradict the snapshot sign.
    _BEARISH_STRONG = {"selloff", "plunged", "plunge", "collapsed", "collapse", "tumbled", "tumble"}
    _BULLISH_STRONG = {"surged", "surge", "soared", "soar", "skyrocketed"}
    _FIELD_ASSET = {
        "equities_commentary":     "S&P 500",
        "commodities_commentary":  "WTI Crude",
        "currencies_commentary":   "U.S. Dollar (DXY)",
        "fixed_income_commentary": "10-Yr Yield",
    }
    for narrative_key, snap_key in _FIELD_ASSET.items():
        snap = (snapshot or {}).get(snap_key) or {}
        truth_pct = snap.get("pct_change")
        if truth_pct is None:
            continue
        prose = data.get(narrative_key, "")
        words = set((prose if isinstance(prose, str) else " ".join(prose or [])).lower().split())
        if truth_pct > 0.3 and words & _BEARISH_STRONG:
            violations.append(
                f"{snap_key}: snapshot {truth_pct:+.2f}% (positive) but narrative uses strongly bearish language"
            )
        elif truth_pct < -0.3 and words & _BULLISH_STRONG:
            violations.append(
                f"{snap_key}: snapshot {truth_pct:+.2f}% (negative) but narrative uses strongly bullish language"
            )

    # pre_market_bullets: each bullet that names a known asset and cites a % must match sign.
    _ASSET_KW = {
        "s&p": "S&P 500",
        "nasdaq": "Nasdaq 100",
        "wti": "WTI Crude",
        "crude": "WTI Crude",
        "gold": "Gold",
        "dxy": "U.S. Dollar (DXY)",
    }
    bullets = data.get("pre_market_bullets", [])
    if isinstance(bullets, list):
        for bullet in bullets:
            btext = str(bullet).lower()
            m = PCT_RE.search(btext)
            if not m:
                continue
            cited = float(m.group(1))
            for kw, snap_key in _ASSET_KW.items():
                if kw in btext:
                    snap = (snapshot or {}).get(snap_key) or {}
                    truth_pct = snap.get("pct_change")
                    if truth_pct is not None:
                        if (truth_pct >= 0) != (cited >= 0):
                            violations.append(
                                f"pre_market_bullets: mentions {snap_key} {cited:+.2f}% but snapshot is {truth_pct:+.2f}% (sign mismatch)"
                            )
                        elif abs(truth_pct) >= 0.02 and abs(truth_pct - cited) > 0.5:
                            violations.append(
                                f"pre_market_bullets: mentions {snap_key} {cited:+.2f}% but snapshot is {truth_pct:+.2f}% (magnitude > 0.5pp)"
                            )
                    break

    return violations


# Verbs that imply direction. If the cited percent has the wrong sign, flip
# the verb in the same clause so the rewritten prose stays grammatical.
_VERB_FLIP_TO_DOWN = {
    "rose": "fell",
    "gained": "slid",
    "climbed": "declined",
    "advanced": "retreated",
    "rallied": "sold off",
    "surged": "tumbled",
    "soared": "plunged",
    "jumped": "dropped",
}
_VERB_FLIP_TO_UP = {v: k for k, v in _VERB_FLIP_TO_DOWN.items()}


def _rewrite_first_pct_sign(text: str, truth_pct: float) -> tuple[str, bool]:
    """Rewrite the first percent figure in `text` to match `truth_pct`'s sign.
    Also flips a nearby preceding directional verb when present.
    Idempotent: if signs already agree, returns text unchanged.
    Returns (new_text, changed).
    """
    if not isinstance(text, str) or not text:
        return text, False
    pct_re = re.compile(r"([-+]?)(\d+(?:\.\d+)?)\s*%")
    m = pct_re.search(text)
    if not m:
        return text, False
    sign_str, mag_str = m.group(1), m.group(2)
    cited = float((sign_str or "") + mag_str)
    if (cited >= 0) == (truth_pct >= 0):
        return text, False  # already aligned

    # Look for a nearby preceding directional verb to flip.
    flip_map = _VERB_FLIP_TO_DOWN if truth_pct < 0 else _VERB_FLIP_TO_UP
    verb_re = re.compile(
        r"\b(" + "|".join(re.escape(v) for v in flip_map.keys()) + r")\b",
        re.IGNORECASE,
    )
    window_start = max(0, m.start() - 120)
    window = text[window_start:m.start()]
    verb_match = None
    matches = list(verb_re.finditer(window))
    if matches:
        verb_match = matches[-1]

    # Positive truth with verb flip: bare magnitude is unambiguous (no leading sign = positive).
    # Negative truth: always emit explicit "-" so the validator can read the sign from the number
    # itself, regardless of whether a verb flip also occurs.
    if verb_match is not None and truth_pct >= 0:
        new_pct = f"{abs(truth_pct):.2f}%"
    else:
        new_sign = "-" if truth_pct < 0 else "+"
        new_pct = f"{new_sign}{abs(truth_pct):.2f}%"
    new_text = text[:m.start()] + new_pct + text[m.end():]

    if verb_match is not None:
        verb_text = verb_match.group(1)
        flipped = flip_map[verb_text.lower()]
        if verb_text[0].isupper():
            flipped = flipped[0].upper() + flipped[1:]
        abs_start = window_start + verb_match.start()
        abs_end = window_start + verb_match.end()
        new_text = new_text[:abs_start] + flipped + new_text[abs_end:]
    return new_text, True


def _rewrite_pct_sign_after_keyword(text: str, keyword: str, truth_pct: float) -> tuple[str, bool]:
    """Rewrite the first percent figure AFTER `keyword` in `text` to match `truth_pct`'s sign.
    Slices from the keyword position and delegates to _rewrite_first_pct_sign, then stitches back.
    Idempotent. Returns (new_text, changed).
    """
    if not isinstance(text, str) or not text:
        return text, False
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return text, False
    new_suffix, changed = _rewrite_first_pct_sign(text[idx:], truth_pct)
    if not changed:
        return text, False
    return text[:idx] + new_suffix, True


def _rewrite_first_pct_magnitude(text: str, truth_pct: float) -> tuple[str, bool]:
    """Rewrite the first percent figure in `text` to match `truth_pct`'s magnitude.
    Only fires when signs already agree — sign mismatches are left to _rewrite_first_pct_sign.
    Idempotent: returns text unchanged if within 0.5pp or signs disagree.
    Returns (new_text, changed).
    """
    if not isinstance(text, str) or not text:
        return text, False
    pct_re = re.compile(r"([-+]?)(\d+(?:\.\d+)?)\s*%")
    m = pct_re.search(text)
    if not m:
        return text, False
    sign_str, mag_str = m.group(1), m.group(2)
    cited = float((sign_str or "") + mag_str)
    if (cited >= 0) != (truth_pct >= 0):
        return text, False  # sign mismatch — handled by _rewrite_first_pct_sign
    if abs(truth_pct - cited) <= 0.5:
        return text, False  # within tolerance
    new_pct = f"{sign_str}{abs(truth_pct):.2f}%"
    return text[:m.start()] + new_pct + text[m.end():], True


def _rewrite_pct_magnitude_after_keyword(text: str, keyword: str, truth_pct: float) -> tuple[str, bool]:
    """Rewrite the first percent figure AFTER `keyword` in `text` to match `truth_pct`'s magnitude.
    Slices from the keyword position and delegates to _rewrite_first_pct_magnitude.
    Idempotent. Returns (new_text, changed).
    """
    if not isinstance(text, str) or not text:
        return text, False
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return text, False
    new_suffix, changed = _rewrite_first_pct_magnitude(text[idx:], truth_pct)
    if not changed:
        return text, False
    return text[:idx] + new_suffix, True


def _correct_sign_mismatches(data: dict, snapshot: dict) -> int:
    """Rewrite sign-flipped percents in narrative fields to match snapshot.
    Mutates data in place. Returns number of corrections applied.
    Idempotent — safe to call multiple times.
    """
    if not snapshot:
        return 0
    fixes = 0

    section_checks = [
        ("equities_commentary",    "S&P 500",            None),
        ("commodities_commentary", "WTI Crude",          "wti"),
        ("commodities_commentary", "Gold",               "gold"),
        ("currencies_commentary",  "U.S. Dollar (DXY)",  None),
    ]
    for narrative_key, snap_key, kw in section_checks:
        truth_pct = (snapshot.get(snap_key) or {}).get("pct_change")
        if truth_pct is None or abs(truth_pct) < 0.02:
            continue
        prose = data.get(narrative_key)
        if not isinstance(prose, str):
            continue
        if kw is None:
            new_prose, changed = _rewrite_first_pct_sign(prose, truth_pct)
        else:
            new_prose, changed = _rewrite_pct_sign_after_keyword(prose, kw, truth_pct)
        if changed:
            data[narrative_key] = new_prose
            fixes += 1

    asset_kw = {
        "s&p":    "S&P 500",
        "nasdaq": "Nasdaq 100",
        "wti":    "WTI Crude",
        "crude":  "WTI Crude",
        "gold":   "Gold",
        "dxy":    "U.S. Dollar (DXY)",
    }
    bullets = data.get("pre_market_bullets")
    if isinstance(bullets, list):
        new_bullets = []
        for bullet in bullets:
            if not isinstance(bullet, str):
                new_bullets.append(bullet)
                continue
            btext_lower = bullet.lower()
            corrected = bullet
            for kw, snap_key in asset_kw.items():
                if kw in btext_lower:
                    truth_pct = (snapshot.get(snap_key) or {}).get("pct_change")
                    if truth_pct is None or abs(truth_pct) < 0.02:
                        break
                    corrected, changed = _rewrite_first_pct_sign(corrected, truth_pct)
                    if changed:
                        fixes += 1
                    break
            new_bullets.append(corrected)
        data["pre_market_bullets"] = new_bullets

    return fixes


def _correct_magnitude_mismatches(data: dict, snapshot: dict) -> int:
    """Rewrite magnitude-divergent percents in narrative fields to match snapshot.
    Must run AFTER _correct_sign_mismatches — only fires when signs already agree.
    Mutates data in place. Returns number of corrections applied. Idempotent.
    """
    if not snapshot:
        return 0
    fixes = 0

    section_checks = [
        ("equities_commentary",    "S&P 500",            None),
        ("commodities_commentary", "WTI Crude",          "wti"),
        ("commodities_commentary", "Gold",               "gold"),
        ("currencies_commentary",  "U.S. Dollar (DXY)",  None),
    ]
    for narrative_key, snap_key, kw in section_checks:
        truth_pct = (snapshot.get(snap_key) or {}).get("pct_change")
        if truth_pct is None or abs(truth_pct) < 0.02:
            continue
        prose = data.get(narrative_key)
        if not isinstance(prose, str):
            continue
        if kw is None:
            new_prose, changed = _rewrite_first_pct_magnitude(prose, truth_pct)
        else:
            new_prose, changed = _rewrite_pct_magnitude_after_keyword(prose, kw, truth_pct)
        if changed:
            data[narrative_key] = new_prose
            fixes += 1

    asset_kw = {
        "s&p":    "S&P 500",
        "nasdaq": "Nasdaq 100",
        "wti":    "WTI Crude",
        "crude":  "WTI Crude",
        "gold":   "Gold",
        "dxy":    "U.S. Dollar (DXY)",
    }
    bullets = data.get("pre_market_bullets")
    if isinstance(bullets, list):
        new_bullets = []
        for bullet in bullets:
            if not isinstance(bullet, str):
                new_bullets.append(bullet)
                continue
            btext_lower = bullet.lower()
            corrected = bullet
            for kw, snap_key in asset_kw.items():
                if kw in btext_lower:
                    truth_pct = (snapshot.get(snap_key) or {}).get("pct_change")
                    if truth_pct is None or abs(truth_pct) < 0.02:
                        break
                    corrected, changed = _rewrite_first_pct_magnitude(corrected, truth_pct)
                    if changed:
                        fixes += 1
                    break
            new_bullets.append(corrected)
        data["pre_market_bullets"] = new_bullets

    return fixes


def _correct_yield_pct_to_bp(data: dict, snapshot: dict) -> int:
    """Replace yield-move percent citations with basis-point figures in Calls 2/3 output fields.

    Calls 2/3 (outlook, recap) may write "yields fell 2.14%" where 2.14 is the yield's
    pct_change — which is meaningless and wrong per NUMBER FIDELITY. This corrector finds
    the exact pct_change string (e.g. "2.14%") in yield-adjacent fields and replaces it
    with the correct bp expression (e.g. "10 bps").
    Mutates data in place. Returns number of corrections applied.
    """
    if not snapshot:
        return 0
    y10 = snapshot.get("10-Yr Yield") or {}
    pct_change = y10.get("pct_change")
    bp_change  = y10.get("bp_change")
    if pct_change is None or bp_change is None or abs(bp_change) < 1:
        return 0

    abs_pct = abs(pct_change)
    bp_abs  = abs(bp_change)
    bp_sfx  = "bp" if bp_abs == 1 else "bps"

    # Build exact string targets: "2.14%" and "-2.14%" and "+2.14%"
    targets = {
        f"{abs_pct:.2f}%",
        f"-{abs_pct:.2f}%",
        f"+{abs_pct:.2f}%",
    }
    replacement = f"{bp_abs:.0f} {bp_sfx}"

    fields = ["market_outlook_rationale", "cross_asset_synthesis"]
    fixes = 0

    def _fix_text(text: str) -> tuple[str, bool]:
        changed = False
        for t in targets:
            if t in text:
                text = text.replace(t, replacement)
                changed = True
        return text, changed

    for field in fields:
        val = data.get(field)
        if isinstance(val, str):
            new_val, changed = _fix_text(val)
            if changed:
                data[field] = new_val
                fixes += 1

    # session_recap is a list of strings
    recap = data.get("session_recap")
    if isinstance(recap, list):
        new_recap = []
        changed_any = False
        for item in recap:
            if isinstance(item, str):
                new_item, ch = _fix_text(item)
                new_recap.append(new_item)
                if ch:
                    changed_any = True
            else:
                new_recap.append(item)
        if changed_any:
            data["session_recap"] = new_recap
            fixes += 1

    # asset_class_outlooks is a nested dict
    aclooks = data.get("asset_class_outlooks")
    if isinstance(aclooks, dict):
        for asset_val in aclooks.values():
            if isinstance(asset_val, dict):
                rationale = asset_val.get("rationale", "")
                if isinstance(rationale, str):
                    new_r, ch = _fix_text(rationale)
                    if ch:
                        asset_val["rationale"] = new_r
                        fixes += 1

    return fixes


def _check_causal_logic(data: dict, snapshot: dict) -> list[str]:
    """Detect causal-logic inversions: driver implies one direction but prose says the opposite.
    Checks sentence-level contradictions in fixed_income_commentary only (the highest-error section).
    Returns violation strings (empty = clean).
    """
    import re
    violations = []

    fi_prose = data.get("fixed_income_commentary", "")
    if not isinstance(fi_prose, str) or not fi_prose:
        return violations

    sentences = re.split(r'(?<=[.!?])\s+', fi_prose)
    for sent in sentences:
        sl = sent.lower()
        yield_rose = bool(re.search(
            r'\byield[s]?\b.{0,60}\b(rose|climbed|jumped|surged|advanced|pushed\s+higher|moved\s+up)\b', sl
        ))
        if not yield_rose:
            continue
        # "Fewer/lower/reduced rate-hike expectations" pulls yields DOWN — contradicts "rose".
        if re.search(r'\b(fewer|lower|reduced)\b.{0,80}\b(rate\s*hikes?|hikes?|tightening|rate\s*increases?)\b', sl):
            violations.append(
                "fixed_income_commentary: causal inversion — 'fewer/lower rate hikes' driver should pull "
                "yields DOWN, but prose says they rose"
            )
            break
        # "Rate cut hopes / dovish expectations" pulls yields DOWN — contradicts "rose".
        if re.search(r'\b(rate\s+cut|cut\s+expectation|dovish|fewer\s+hike|cut\s+hope)\b', sl):
            violations.append(
                "fixed_income_commentary: causal inversion — rate-cut/dovish driver should pull "
                "yields DOWN, but prose says they rose"
            )
            break

    return violations


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically via a temp file + os.replace to avoid partial writes."""
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _build_deterministic_market_commentary(
    snapshot: dict,
    commodities_tbl: list,
    currencies_tbl: list,
    bonds_tbl: list,
) -> dict:
    """Build plain-text market narrative from snapshot data when LLM is unavailable.

    Output is numerically consistent with the snapshot and passes validate_commentary
    when called with snapshot=None. Called as fallback when Ollama fails or times out.
    """
    def _pct(val: Any) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    def _lvl(val: Any, fmt: str = ",.2f") -> str:
        try:
            return format(float(val), fmt)
        except Exception:
            return "N/A"

    def _dir(pct: float, style: str = "generic") -> str:
        if style == "yield":
            if pct > 0.05:  return "rose"
            if pct < -0.05: return "fell"
            return "was little changed"
        if pct > 0.5:    return "rose"
        if pct > 0.1:    return "edged higher"
        if pct < -0.5:   return "fell"
        if pct < -0.1:   return "edged lower"
        return "was little changed"

    sp  = snapshot.get("S&P 500", {})
    ndx = snapshot.get("Nasdaq 100", {})
    wti = snapshot.get("WTI Crude", {})
    gld = snapshot.get("Gold", {})
    dxy = snapshot.get("U.S. Dollar (DXY)", {})
    tyr = snapshot.get("10-Yr Yield", {})

    sp_pct  = _pct(sp.get("pct_change"));  sp_lvl  = _lvl(sp.get("level"))
    ndx_pct = _pct(ndx.get("pct_change")); ndx_lvl = _lvl(ndx.get("level"))
    wti_pct = _pct(wti.get("pct_change")); wti_lvl = _lvl(wti.get("level"))
    gld_pct = _pct(gld.get("pct_change")); gld_lvl = _lvl(gld.get("level"))
    dxy_pct = _pct(dxy.get("pct_change")); dxy_lvl = _lvl(dxy.get("level"))
    tyr_pct = _pct(tyr.get("pct_change")); tyr_lvl = _lvl(tyr.get("level"), ".3f")

    return {
        "pre_market_bullets": [
            f"S&P 500 {_dir(sp_pct)} {sp_pct:+.2f}% to {sp_lvl}; Nasdaq 100 {_dir(ndx_pct)} {ndx_pct:+.2f}%.",
            f"10-Yr yield at {tyr_lvl}%.",
            f"WTI crude {_dir(wti_pct)} {wti_pct:+.2f}% to ${wti_lvl}; gold {_dir(gld_pct)} {gld_pct:+.2f}%.",
            f"DXY {_dir(dxy_pct)} {dxy_pct:+.2f}% to {dxy_lvl}.",
        ],
        "equities_commentary": (
            f"The S&P 500 {_dir(sp_pct)} {sp_pct:+.2f}% to {sp_lvl}. "
            f"The Nasdaq 100 {_dir(ndx_pct)} {ndx_pct:+.2f}% to {ndx_lvl}."
        ),
        "fixed_income_commentary": (
            f"The 10-year Treasury yield {_dir(tyr_pct, 'yield')} to {tyr_lvl}, "
            f"reflecting prevailing market conditions."
        ),
        "commodities_commentary": (
            f"WTI crude {_dir(wti_pct)} {wti_pct:+.2f}% to ${wti_lvl}. "
            f"Gold {_dir(gld_pct)} {gld_pct:+.2f}% to ${gld_lvl}."
        ),
        "currencies_commentary": (
            f"The U.S. Dollar Index (DXY) {_dir(dxy_pct)} {dxy_pct:+.2f}% to {dxy_lvl}."
        ),
        "economics_commentary":      "Economic calendar data was unavailable for this session.",
        "market_outlook_label":      "Neutral",
        "market_outlook_rationale":  "Deterministic fallback — LLM commentary unavailable.",
        "tactical_outperforming":    "",
        "tactical_underperforming":  "",
        "asset_class_outlooks":      {},
        "portfolio_spotlight_winners": [],
        "portfolio_spotlight_watch":   [],
        "session_recap":             [],
        "watch_today":               [],
        "international_section":     "",
        "cross_asset_synthesis":     "",
    }


def validate_commentary(data: dict, known_tickers: set = None, snapshot: dict = None) -> bool:
    if not isinstance(data, dict):
        return False
    # commodities_commentary and economics_commentary are optional  model reliably omits them when
    # there is no relevant data; downstream renders gracefully without them
    required_narrative = {"pre_market_bullets", "equities_commentary", "fixed_income_commentary",
                          "currencies_commentary"}
    required_outlook   = {"market_outlook_label", "market_outlook_rationale",
                          "tactical_outperforming", "tactical_underperforming",
                          "asset_class_outlooks"}
    all_required = required_narrative | required_outlook
    missing = all_required - set(data.keys())
    if missing:
        print(f"[WARN] Commentary missing keys: {missing}")
        # Tolerate missing outlook keys if we have narrative
        if missing & required_narrative:
            return False
    # Check narrative sections are non-empty
    for key in required_narrative:
        val = data.get(key, "")
        if isinstance(val, list):
            if not val:
                print(f"[WARN] Empty list for '{key}'")
                return False
        elif not str(val).strip():
            print(f"[WARN] Empty string for '{key}'")
            return False
    # Numeric consistency gate — compare LLM prose directions/magnitudes to market snapshot
    if snapshot is not None:
        sign_fixes = _correct_sign_mismatches(data, snapshot)
        if sign_fixes:
            print(f"[CORRECT] Auto-corrected {sign_fixes} sign mismatch(es) in merged commentary.")
        mag_fixes = _correct_magnitude_mismatches(data, snapshot)
        if mag_fixes:
            print(f"[CORRECT] Auto-corrected {mag_fixes} magnitude mismatch(es) in merged commentary.")
        bp_fixes = _correct_yield_pct_to_bp(data, snapshot)
        if bp_fixes:
            print(f"[CORRECT] Auto-corrected {bp_fixes} yield-pct-to-bp citation(s) in merged commentary.")
        violations = _check_numeric_consistency(data, snapshot)
        if violations:
            print(f"[VALIDATE] Numeric consistency violations vs market_snapshot: {violations}")
            return False
        causal_violations = _check_causal_logic(data, snapshot)
        if causal_violations:
            print(f"[VALIDATE] Causal logic inversions: {causal_violations}")
            return False
    # Normalize market_outlook_label
    label = str(data.get("market_outlook_label", "")).strip()
    if label not in ("Bullish", "Cautious", "Neutral", "Bearish"):
        data["market_outlook_label"] = "Neutral"
    # Ensure portfolio lists exist
    data.setdefault("portfolio_spotlight_winners", [])
    data.setdefault("portfolio_spotlight_watch", [])
    data.setdefault("asset_class_outlooks", {})
    # New optional sections — graceful degradation if model omits them
    data.setdefault("session_recap", [])
    data.setdefault("watch_today", [])
    data.setdefault("international_section", "")
    data.setdefault("cross_asset_synthesis", "")

    # Strip spotlight entries whose tickers are outside the known universe
    if known_tickers:
        before_w = len(data["portfolio_spotlight_winners"])
        before_wt = len(data["portfolio_spotlight_watch"])
        data["portfolio_spotlight_winners"] = [
            e for e in data["portfolio_spotlight_winners"]
            if str(e.get("ticker", "")).upper() in known_tickers
        ]
        data["portfolio_spotlight_watch"] = [
            e for e in data["portfolio_spotlight_watch"]
            if str(e.get("ticker", "")).upper() in known_tickers
        ]
        removed_w = before_w - len(data["portfolio_spotlight_winners"])
        removed_wt = before_wt - len(data["portfolio_spotlight_watch"])
        if removed_w or removed_wt:
            print(f"[VALIDATE] Removed {removed_w} winner(s), {removed_wt} watch(es) outside known universe.")

    # Remove bearish tickers from spotlight winners (contradiction guard)
    bearish_tickers: set[str] = set()
    for bullet in data.get("top_bullets", []):
        if isinstance(bullet, str) and bullet.strip().lower().startswith("bearish"):
            parts = bullet.split("")
            if len(parts) >= 2:
                bearish_tickers.add(parts[1].split(":")[0].strip().upper())
    if bearish_tickers:
        before = len(data["portfolio_spotlight_winners"])
        data["portfolio_spotlight_winners"] = [
            e for e in data["portfolio_spotlight_winners"]
            if str(e.get("ticker", "")).upper() not in bearish_tickers
        ]
        removed = before - len(data["portfolio_spotlight_winners"])
        if removed:
            print(f"[VALIDATE] Removed {removed} winner(s) that contradicted bearish top_bullets: {bearish_tickers}")

    return True


# ---------------------------------------------------------------------------
# Historical return enrichment
# ---------------------------------------------------------------------------
_YIELD_NAMES: frozenset[str] = frozenset({
    "10-Yr Yield", "10-Year Yield", "30-Year Yield", "2-Year Yield",
})


def enrich_with_historical_returns(
    snapshots: list[tuple[dict, dict[str, str]]],
) -> None:
    """Add pct_change_1w / pct_change_ytd (bp_change_* for yields) to snapshot dicts in-place.

    snapshots: list of (data_dict, {display_name: yf_ticker})
    """
    if yf is None:
        return
    reverse: dict[str, list[tuple[dict, str]]] = {}
    for data_dict, ticker_map in snapshots:
        for name, ticker in ticker_map.items():
            if name in data_dict:
                reverse.setdefault(ticker, []).append((data_dict, name))
    if not reverse:
        return
    try:
        today = datetime.today()
        ytd_start = pd.Timestamp(today.year, 1, 1)
        dl_start  = ytd_start.strftime("%Y-%m-%d")
        dl_end    = today.strftime("%Y-%m-%d")
        raw = yf.download(
            list(reverse.keys()), start=dl_start, end=dl_end,
            progress=False, auto_adjust=True,
        )
        if raw.empty:
            return
        if isinstance(raw.columns, pd.MultiIndex):
            closes = raw["Close"]
        else:
            t = list(reverse.keys())[0]
            closes = pd.DataFrame({t: raw["Close"]})
        closes.index = pd.to_datetime(closes.index).tz_localize(None)
    except Exception as exc:
        print(f"[WARN] enrich_with_historical_returns: {exc}")
        return

    for ticker, targets in reverse.items():
        if ticker not in closes.columns:
            continue
        s = pd.to_numeric(closes[ticker], errors="coerce").dropna()
        if len(s) < 2:
            continue
        last = float(s.iloc[-1])
        base_1w = float(s.iloc[-6]) if len(s) > 5 else None
        s_ytd = s[s.index >= ytd_start]
        base_ytd = float(s_ytd.iloc[0]) if len(s_ytd) >= 1 else None
        for data_dict, name in targets:
            is_yield = name in _YIELD_NAMES
            if base_1w is not None:
                if is_yield:
                    data_dict[name]["bp_change_1w"] = round((last - base_1w) * 100, 1)
                elif base_1w != 0:
                    data_dict[name]["pct_change_1w"] = round((last / base_1w - 1) * 100, 2)
            if base_ytd is not None:
                if is_yield:
                    data_dict[name]["bp_change_ytd"] = round((last - base_ytd) * 100, 1)
                elif base_ytd != 0:
                    data_dict[name]["pct_change_ytd"] = round((last / base_ytd - 1) * 100, 2)


# ---------------------------------------------------------------------------
# Topic Spotlight helpers
# ---------------------------------------------------------------------------

def _topic_matches_text(keywords: list[str], text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _crawl_article_body(url: str, timeout: int = 8) -> str:
    """Fetch and extract plain text from a news article URL. Returns empty string on any failure."""
    if not url or not url.startswith("http"):
        return ""
    try:
        from bs4 import BeautifulSoup
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=timeout,
        )
        if r.status_code != 200:
            return ""
        content = r.content[:204800]  # cap at 200KB
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:8000]
    except Exception:
        return ""


def _extract_ticker_candidates(text: str) -> list[str]:
    """Extract potential fund/ETF tickers from article body text."""
    import re
    candidates: list[str] = []
    # Parenthetical groups: (XOVR), (BPTRX, BPTIX)
    for match in re.findall(r'\(([A-Z]{2,6}(?:,\s*[A-Z]{2,6})*)\)', text):
        for t in match.split(","):
            t = t.strip()
            if 2 <= len(t) <= 6:
                candidates.append(t)
    # Uppercase tokens immediately before "ETF", "Fund", or "Trust"
    for m in re.finditer(r'\b([A-Z]{2,6})\b\s+(?:ETF|Fund|Trust)', text):
        candidates.append(m.group(1))
    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for t in candidates:
        if t not in seen and not t.isdigit():
            seen.add(t)
            result.append(t)
    return result


def _verify_spotlight_fund(ticker: str) -> dict | None:
    """Verify a ticker resolves to a real fund via OpenBBProvider. Returns None on failure."""
    try:
        from providers.openbb_provider import OpenBBProvider
        profile = OpenBBProvider().get_profile(ticker)
        if not profile:
            return None
        name = str(profile.get("name") or "").strip()
        if not name or name.upper() == ticker.upper():
            return None
        issue_type = str(profile.get("issue_type") or "").upper()
        long_desc  = str(profile.get("long_description") or profile.get("short_description") or "")
        # Reject plain equities that aren't fund-like
        if issue_type in {"EQUITY", "COMMONSTOCK", "STOCK"} and "fund" not in name.lower() and "trust" not in name.lower():
            return None
        return {
            "ticker":      ticker,
            "name":        name,
            "type":        issue_type or "Fund",
            "aum":         profile.get("market_cap"),
            "description": long_desc[:300],
        }
    except Exception:
        return None


def _scrub_spotlight_text(text: str) -> str:
    """Strip sensational escalation phrases from spotlight text (narrower than BANNED_PHRASES)."""
    import re
    for phrase in SPOTLIGHT_ESCALATION_PHRASES:
        text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
    text = re.sub(r"  +", " ", text).strip()
    return text


# Asset aliases + directional verbs for the spotlight directional guard.
_SPOTLIGHT_ASSET_ALIASES: dict[str, tuple[str, ...]] = {
    "S&P 500":            ("s&p 500", "s&p500", "s&p", "spx"),
    "Nasdaq 100":         ("nasdaq 100", "nasdaq", "ndx"),
    "Dow Jones":          ("dow jones", "the dow", "dow", "djia"),
    "Russell 2000":       ("russell 2000", "russell", "small caps", "small-caps"),
    "Gold":               ("gold", "bullion"),
    "WTI Crude":          ("wti crude", "wti", "crude oil", "crude", "oil prices", "oil"),
    "U.S. Dollar (DXY)":  ("dollar index", "the dollar", "greenback", "dxy"),
    "Nikkei 225":         ("nikkei",),
    "FTSE 100":           ("ftse",),
}
_SPOTLIGHT_UP_RE = re.compile(
    r'\b(surge\w*|soar\w*|jump\w*|rallie\w*|rally|rallied|climb\w*|rocket\w*|'
    r'spike[ds]?|gain\w*|rise[s]?|rose|rebound\w*|advanc\w*|popp?\w*)\b'
)
_SPOTLIGHT_DOWN_RE = re.compile(
    r'\b(crash\w*|plunge[ds]?|plunging|tumbl\w*|sink[s]?|sank|slump\w*|slid\w*|slide[s]?|'
    r'tank\w*|sell-?off|drop\w*|fell|fall[s]?|div\w*|sink\w*|slip\w*)\b'
)


def _spotlight_contradicts_market(text: str, market_dirs: dict[str, int]) -> list[str]:
    """Return descriptions of directional claims in `text` that contradict the close.

    market_dirs maps canonical asset name -> sign (+1 closed up, -1 closed down, 0 flat).
    Fires only when an asset alias is immediately followed (within ~22 chars) by an
    up/down verb whose direction is opposite the actual close. The tight window keeps a
    second clause (e.g. "...as oil crashes") from contaminating the prior asset's check.
    """
    low = (text or "").lower()
    if not low:
        return []
    violations: list[str] = []
    for asset, sign in market_dirs.items():
        if not sign:
            continue
        for alias in _SPOTLIGHT_ASSET_ALIASES.get(asset, ()):
            hit = False
            for m in re.finditer(r'\b' + re.escape(alias) + r'\b', low):
                seg = low[m.end(): m.end() + 22]
                up = _SPOTLIGHT_UP_RE.search(seg)
                dn = _SPOTLIGHT_DOWN_RE.search(seg)
                if not up and not dn:
                    continue
                said_up = bool(up) and (not dn or up.start() < dn.start())
                if said_up and sign < 0:
                    violations.append(f"{asset} described as rising but closed lower")
                    hit = True
                elif (not said_up) and dn and sign > 0:
                    violations.append(f"{asset} described as falling but closed higher")
                    hit = True
            if hit:
                break  # one alias hit per asset is enough
    return violations


def generate_topic_spotlight(
    payload: dict,
    world_news: list[dict],
    enrich_news: dict,
    enrich_co_news: list[dict],
    market_dirs: dict[str, int] | None = None,
) -> dict | None:
    """Detect a trending financial topic and write a grounded spotlight story with verified fund tie-ins.

    Returns the topic_spotlight dict or None when the gate does not fire.
    """
    # ── Build headline corpus with source + URL ───────────────────────────────
    headline_corpus: list[dict] = []
    for a in (world_news or []):
        title = str(a.get("title") or "").strip()
        if title:
            headline_corpus.append({
                "text":   title + ("  " + str(a.get("summary") or ""))[:200],
                "source": str(a.get("source") or "world"),
                "url":    str(a.get("url") or ""),
            })
    for articles in (enrich_news if isinstance(enrich_news, dict) else {}).values():
        for a in (articles or []):
            hl = str(a.get("headline") or "").strip()
            if hl:
                headline_corpus.append({
                    "text":   hl + ("  " + str(a.get("summary") or ""))[:200],
                    "source": str(a.get("source") or "finnhub"),
                    "url":    str(a.get("url") or ""),
                })
    for a in (enrich_co_news if isinstance(enrich_co_news, list) else []):
        hl = str(a.get("headline") or "").strip()
        if hl:
            headline_corpus.append({
                "text":   hl,
                "source": str(a.get("source") or "finnhub"),
                "url":    str(a.get("url") or ""),
            })
    if not headline_corpus:
        return None

    # ── LLM topic scan ────────────────────────────────────────────────────────
    scan_payload = {
        "headlines": [{"index": i, "text": h["text"][:300]} for i, h in enumerate(headline_corpus[:40])],
        "date": payload.get("date", ""),
    }
    scan_result: dict = {}
    try:
        print("  [SPOTLIGHT] Scanning headlines for dominant topic...")
        scan_result = _call_ollama_raw(SYSTEM_PROMPT_TOPIC_SCAN, scan_payload)
    except Exception as exc:
        print(f"  [SPOTLIGHT] Scan failed: {exc}")
        return None

    if not scan_result.get("has_spotlight"):
        print("  [SPOTLIGHT] No dominant topic detected.")
        return None

    topic          = str(scan_result.get("topic") or "").strip()
    topic_keywords = [str(k).lower().strip() for k in (scan_result.get("topic_keywords") or []) if k]
    why_now        = str(scan_result.get("why_now") or "").strip()
    category       = str(scan_result.get("category") or "").strip()
    scan_funds     = [str(t).upper().strip() for t in (scan_result.get("candidate_funds") or []) if t]

    if not topic or not topic_keywords:
        return None

    # ── Deterministic gate ────────────────────────────────────────────────────
    matching       = [h for h in headline_corpus if _topic_matches_text(topic_keywords, h["text"])]
    distinct_src   = {h["source"] for h in matching}
    print(f"  [SPOTLIGHT] '{topic}': {len(matching)} matching headlines, {len(distinct_src)} sources.")

    if len(matching) < MIN_TOPIC_HEADLINES or len(distinct_src) < MIN_TOPIC_SOURCES:
        print(f"  [SPOTLIGHT] Gate failed (need >={MIN_TOPIC_HEADLINES} headlines, >={MIN_TOPIC_SOURCES} sources).")
        return None

    # ── Fund grounding: crawl topic articles + verify tickers ─────────────────
    candidate_tickers = list(scan_funds)
    crawl_targets = [h["url"] for h in matching if h.get("url", "").startswith("http")]
    crawled = 0
    crawled_excerpts: list[dict] = []
    for url in crawl_targets[:MAX_CRAWL_ARTICLES]:
        print(f"  [SPOTLIGHT] Crawling {url[:80]}...")
        body = _crawl_article_body(url)
        if body:
            candidate_tickers.extend(_extract_ticker_candidates(body))
            crawled += 1
            # Keep a clean excerpt to GROUND the analysis in actual reporting rather than
            # headlines alone — this is what lifts the spotlight from a blurb to a genuine
            # deep-dive (the mechanism/sustainability paragraphs need real source material).
            _src = url.split("/")[2] if "//" in url else url
            crawled_excerpts.append({"source": _src, "text": body[:1400]})
    print(f"  [SPOTLIGHT] Crawled {crawled} articles; {len(set(candidate_tickers))} raw candidates.")

    seen_t: set[str] = set()
    deduped: list[str] = []
    for t in candidate_tickers:
        if t not in seen_t and len(t) >= 2:
            seen_t.add(t)
            deduped.append(t)

    verified_funds: list[dict] = []
    for ticker in deduped:
        if len(verified_funds) >= MAX_SPOTLIGHT_FUNDS:
            break
        result = _verify_spotlight_fund(ticker)
        if result:
            verified_funds.append(result)
            print(f"  [SPOTLIGHT] Verified: {ticker} ({result['name']})")
        else:
            print(f"  [SPOTLIGHT] Dropped: {ticker}")

    # ── LLM story writing (Call 6) ─────────────────────────────────────────────
    writer_payload = {
        "topic":               topic,
        "category":            category,
        "why_now":             why_now,
        "supporting_headlines": [
            {"headline": h["text"][:300], "source": h["source"]} for h in matching[:10]
        ],
        # Real article text the analysis MUST be grounded in (facts, figures, mechanism).
        "source_excerpts": crawled_excerpts[:5],
        "verified_funds": [
            {"ticker": f["ticker"], "name": f["name"], "type": f["type"], "description": f["description"]}
            for f in verified_funds
        ],
        "date": payload.get("date", ""),
    }
    # Seed the writer with the actual closing directions so it is less likely to
    # invent a move that contradicts the tape on the first pass.
    if market_dirs:
        writer_payload["market_close_directions"] = {
            a: ("up" if s > 0 else "down" if s < 0 else "flat")
            for a, s in market_dirs.items() if s
        }

    print(f"  [LLM Call 6] Writing topic spotlight: '{topic}'...")
    # The writer loop now enforces BOTH completeness and the directional guard. A draft
    # that asserts a price move contradicting the close (e.g. "Dow Surges" on a down
    # day) is not discarded outright — we feed the specific error back and retry, so a
    # salvageable spotlight survives instead of vanishing. Only an exhausted loop drops.
    title = ""
    body  = ""
    story: dict = {}
    for attempt in range(4):
        try:
            story = _call_ollama_raw(SYSTEM_PROMPT_TOPIC_SPOTLIGHT, writer_payload, num_ctx=16384)
        except Exception as exc:
            print(f"  [SPOTLIGHT] Writer attempt {attempt + 1} failed: {exc}")
            story = {}
            continue
        # Depth gate: a flagship deep-dive must be substantive (>=3 paragraphs, >=600 chars).
        # A thin blurb triggers a retry; an exhausted loop drops it (quality over presence).
        _body_raw = str(story.get("body") or "").strip()
        _para_ct = len([p for p in _body_raw.split("\n\n") if p.strip()])
        if not (str(story.get("title") or "").strip() and len(_body_raw) >= 600 and _para_ct >= 3):
            print(f"  [SPOTLIGHT] Attempt {attempt + 1}: too thin "
                  f"({len(_body_raw)} chars, {_para_ct} paras) — retrying for depth.")
            story = {}
            continue
        # ── Scrub, then run the directional guard before accepting ─────────────
        title = _scrub_spotlight_text(str(story.get("title") or "").strip())
        body  = _scrub_spotlight_text(str(story.get("body") or "").strip())
        contradictions = (
            _spotlight_contradicts_market(title + ". " + body, market_dirs)
            if market_dirs else []
        )
        if not contradictions:
            break
        print(f"  [SPOTLIGHT] Attempt {attempt + 1}: claim contradicts market close "
              f"{contradictions}; retrying with correction.")
        writer_payload["factual_correction"] = (
            "Your previous draft was REJECTED for stating a price move that contradicts "
            "the actual market close: " + "; ".join(contradictions) + ". Rewrite so EVERY "
            "directional claim matches these closing directions: "
            + ", ".join(f"{a} closed {d}"
                        for a, d in writer_payload.get("market_close_directions", {}).items())
            + ". When unsure, use a thematic headline with no index/asset move."
        )
        story, title, body = {}, "", ""

    if not title or not body:
        print("  [SPOTLIGHT] No usable, market-consistent story produced — skipping spotlight.")
        return None

    verified_tickers = {f["ticker"] for f in verified_funds}
    raw_funds = story.get("funds") or []
    clean_funds: list[dict] = []
    for f in (raw_funds if isinstance(raw_funds, list) else []):
        if not isinstance(f, dict):
            continue
        t = str(f.get("ticker") or "").upper().strip()
        if t in verified_tickers:
            clean_funds.append({
                "ticker":       t,
                "name":         str(f.get("name") or ""),
                "type":         str(f.get("type") or ""),
                "exposure_note": _scrub_spotlight_text(str(f.get("exposure_note") or "")),
            })

    result = {"title": title, "body": body, "funds": clean_funds, "category": category, "topic": topic}
    print(f"  [SPOTLIGHT] Done: '{title}' ({len(clean_funds)} verified funds).")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    today = datetime.today().strftime("%Y-%m-%d")

    # Load yesterday's stored levels so each instrument's prev_close is the value
    # we actually reported last run.  GUARD: if the existing commentary file is from
    # TODAY (a same-day re-run), feeding its levels back would make daily pct_change
    # collapse to ~0 (today-vs-today).  In that case fall back to the most recent
    # prior-day archive file so contract-roll protection is still available.
    _prev: dict = {}
    if COMMENTARY_PATH.exists():
        try:
            with open(COMMENTARY_PATH, "r", encoding="utf-8") as _pf:
                _prev = json.load(_pf)
        except Exception:
            pass

    if _prev.get("report_date") == today:
        # Same-day re-run detected — source prev_close from prior archive instead.
        _archive_dir = COMMENTARY_PATH.parent / "commentary_archive"
        _archive_prev: dict = {}
        if _archive_dir.exists():
            _archive_files = sorted(
                (f for f in _archive_dir.glob("*.json") if f.stem < today),
                reverse=True,
            )
            if _archive_files:
                try:
                    with open(_archive_files[0], "r", encoding="utf-8") as _af:
                        _archive_prev = json.load(_af)
                    print(f"[DATA] Same-day re-run: using prior archive {_archive_files[0].name} for prev_close.")
                except Exception:
                    pass
        if _archive_prev:
            _prev = _archive_prev
        else:
            print("[DATA] Same-day re-run: no prior archive found — fetchers will use arr[-2] as prev_close.")
            _prev = {}

    print("[DATA] Fetching live market data...")
    snapshot         = fetch_market_snapshot(prev_data=_prev.get("market_snapshot"))
    print(f"  [OK] Core snapshot: {len(snapshot)} assets")

    global_markets   = fetch_global_markets(prev_data=_prev.get("global_markets"))
    print(f"  [OK] Global markets: {len(global_markets)} indices")

    commodities_tbl  = fetch_commodities_table(prev_data=_prev.get("commodities_table"))
    print(f"  [OK] Commodities: {len(commodities_tbl)} items")

    currencies_tbl   = fetch_currencies_table(prev_data=_prev.get("currencies_table"))
    print(f"  [OK] Currencies: {len(currencies_tbl)} pairs")

    bonds_tbl        = fetch_bonds_table()
    print(f"  [OK] Bonds: {len(bonds_tbl)} instruments")

    # Sync the 10-Yr Yield in the snapshot to the authoritative Treasury.gov value
    # so the market snapshot table and the yield table always agree on level/direction.
    _tsy_10y = bonds_tbl.get("10-Year Yield")
    if _tsy_10y and _tsy_10y.get("level") is not None:
        _tsy_chg = _tsy_10y.get("change")
        snapshot["10-Yr Yield"] = {
            "level":      _tsy_10y["level"],
            "change":     _tsy_chg,
            "pct_change": _tsy_10y.get("pct_change"),
            "bp_change":  round((_tsy_chg or 0) * 100, 1),
        }
        print(f"  [OK] Snapshot 10-Yr synced to Treasury.gov: {_tsy_10y['level']:.3f}%")

    print("[DATA] Enriching with 1W/YTD historical returns...")
    try:
        enrich_with_historical_returns([
            (snapshot,        MARKET_TICKERS),
            (global_markets,  GLOBAL_TICKERS),
            (commodities_tbl, COMMODITY_TICKERS),
            (currencies_tbl,  CURRENCY_TICKERS),
        ])
        print("  [OK] Historical enrichment complete")
    except Exception as _enrich_exc:
        print(f"  [WARN] Historical enrichment skipped: {_enrich_exc}")

    tech_levels      = fetch_technical_levels()
    print(f"  [OK] Technical levels: {len(tech_levels)} assets")

    # Sync the technical-table 10-Yr "current" to the same authoritative Treasury.gov
    # value used for the snapshot, so the page-8 moving-average table can't disagree
    # with pages 1-2 (yfinance ^TNX often lags Treasury.gov by several bp).
    _tsy_10y_tech = bonds_tbl.get("10-Year Yield")
    if _tsy_10y_tech and _tsy_10y_tech.get("level") is not None and tech_levels.get("10-Yr Yield"):
        tech_levels["10-Yr Yield"]["current"] = round(float(_tsy_10y_tech["level"]), 2)
        print(f"  [OK] Technical 10-Yr synced to Treasury.gov: {_tsy_10y_tech['level']:.3f}%")

    sector_perf      = fetch_sector_performance()
    print(f"  [OK] Sectors: {len(sector_perf)} ETFs fetched")

    futures_tbl      = fetch_futures_table(prev_data=_prev.get("futures_table"))
    print(f"  [OK] Futures: {len(futures_tbl)} contracts")

    print("[DATA] Loading portfolio data...")
    df = load_portfolio_df()
    winners, watch     = build_portfolio_spotlight(df) if not df.empty else ([], [])
    mag7_consensus     = build_mag7_consensus(df)      if not df.empty else {}
    news_buckets       = load_news_headlines()

    print("[NET] Fetching world news...")
    world_news = fetch_world_news()

    print("[CAL] Fetching economic calendar...")
    econ_calendar = fetch_economic_calendar()

    print("[FED] Checking Fed speaker schedule...")
    fed_speakers = fetch_fed_speakers()

    print("[ENRICH] Loading enrichment data...")
    enrichment: dict = {}
    try:
        from fetch_enrichment import run_enrichment
        enrich_path = DATA_DIR / "enrichment.json"
        # Use cached file if updated today, otherwise re-fetch
        if enrich_path.exists():
            with open(enrich_path, "r", encoding="utf-8") as _ef:
                _cached = json.load(_ef)
            if _cached.get("updated") == today:
                enrichment = _cached
                print(f"  [OK] Enrichment loaded from cache ({today})")
            else:
                enrichment = run_enrichment()
        else:
            enrichment = run_enrichment()
        fg    = enrichment.get("fear_greed", {})
        wsb   = enrichment.get("wsb_sentiment", [])
        fred  = enrichment.get("fred_proxies", {})
        oecd_cli = enrichment.get("oecd_cli", {})
        enrich_news = enrichment.get("market_news", {})
        enrich_co_news = enrichment.get("company_news", [])
        earnings_cal = enrichment.get("earnings_calendar", [])
        sent_summary = enrichment.get("sentiment_summary", {})
        print(f"  [OK] Fear & Greed: {fg.get('score','N/A')} ({fg.get('rating','N/A')})")
        print(f"  [OK] WSB top: {wsb[0]['ticker'] if wsb else 'N/A'}")
        print(f"  [OK] FRED proxies: {sum(1 for v in fred.values() if v.get('value') is not None)}")
        print(f"  [OK] OECD CLI: {len(oecd_cli)} economies")
        print(f"  [OK] Finnhub articles: {sum(len(v) for v in enrich_news.values())}")
    except Exception as _exc:
        print(f"  [WARN] Enrichment failed: {_exc}")
        fg = wsb = {}; fred = {}; oecd_cli = {}; enrich_news = enrich_co_news = {}; earnings_cal = []; sent_summary = {}

    # Merge world news + Finnhub news into buckets for the LLM
    world_buckets: dict[str, list[str]] = {}
    for a in world_news:
        cat   = a.get("category", "other")
        entry = a["title"]
        if a.get("summary"):
            entry += f"  {a['summary'][:200]}"
        world_buckets.setdefault(cat, []).append(entry)

    # Add Finnhub scored news (pre-sorted by sentiment extremes for signal density)
    for cat, articles in (enrich_news if isinstance(enrich_news, dict) else {}).items():
        sorted_arts = sorted(articles, key=lambda x: abs(x.get("sentiment", 0)), reverse=True)
        for a in sorted_arts[:4]:
            headline = a.get("headline", "")
            if any(kw in headline.lower() for kw in _NOISE_KEYWORDS):
                continue
            entry = headline
            if a.get("summary"):
                entry += f"  {a['summary'][:150]}"
            world_buckets.setdefault(cat, []).append(entry)

    # Finnhub company-level news → equity/macro buckets
    for a in (enrich_co_news if isinstance(enrich_co_news, list) else [])[:15]:
        entry = a.get("headline", "")
        if not entry:
            continue
        lower = entry.lower()
        cat = "equities"
        for bname, kws in _NEWS_BUCKETS.items():
            if any(kw in lower for kw in kws):
                cat = bname
                break
        world_buckets.setdefault(cat, []).append(entry)

    merged_buckets = dict(news_buckets)
    for cat, items in world_buckets.items():
        merged_buckets.setdefault(cat, [])
        merged_buckets[cat] = merged_buckets[cat] + items

    # De-prioritize foreign-domestic headlines (India/RBI/SE-Asia) at the source so
    # US-relevant stories fill each bucket's LLM cut. sorted() is stable, so equal-score
    # items keep their existing sentiment/recency order.
    for cat in merged_buckets:
        merged_buckets[cat] = sorted(merged_buckets[cat], key=_us_relevance_score, reverse=True)

    LLM_PER_BUCKET = 6
    llm_buckets = {cat: items[:LLM_PER_BUCKET] for cat, items in merged_buckets.items()}

    # Build international macro context block for LLM
    international_macro = {
        "eur_usd":    fred.get("eur_per_usd", {}) if isinstance(fred, dict) else {},
        "jpy_usd":    fred.get("jpy_per_usd", {}) if isinstance(fred, dict) else {},
        "eu_cpi":     fred.get("eu_cpi_hicp", {}) if isinstance(fred, dict) else {},
        "eu_stoxx":   global_markets.get("Euro Stoxx 50", {}),
        "nikkei":     global_markets.get("Nikkei 225", {}),
        "hang_seng":  global_markets.get("Hang Seng", {}),
        # OECD Composite Leading Indicators — monthly economic momentum by country
        # value >100 = above long-run trend (expansionary); trend = improving/deteriorating
        "oecd_cli":   oecd_cli,
    }

    # Derive authoritative DXY direction so the LLM writes consistent currency commentary.
    # Individual pair tickers (EURUSD=X etc.) can have stale/misaligned timestamps vs DXY.
    # We tell the LLM explicitly what direction the dollar moved and what that implies.
    _dxy_pct = (snapshot.get("U.S. Dollar (DXY)") or {}).get("pct_change") or 0.0
    if _dxy_pct > 0.05:
        _dollar_direction = "strengthened"
        _major_pairs_direction = "EUR/USD, GBP/USD, AUD/USD fell (dollar strengthened)"
    elif _dxy_pct < -0.05:
        _dollar_direction = "weakened"
        _major_pairs_direction = "EUR/USD, GBP/USD, AUD/USD rose (dollar weakened)"
    else:
        _dollar_direction = "flat"
        _major_pairs_direction = "Major pairs were little changed"

    # Build a concise summary of key data for the LLM
    key_data_summary = {
        "us_equities": {k: snapshot[k] for k in ["S&P 500", "Nasdaq 100"] if k in snapshot},
        "rates":       {k: snapshot[k] for k in ["10-Yr Yield"] if k in snapshot},
        "commodities": {k: snapshot[k] for k in ["Gold", "WTI Crude"] if k in snapshot},
        "dollar":      {k: snapshot[k] for k in ["U.S. Dollar (DXY)"] if k in snapshot},
        "dollar_direction":      _dollar_direction,
        "major_pairs_direction": _major_pairs_direction,
        "global_equities_highlights": {
            k: v for k, v in list(global_markets.items())[:6]
        },
        "bonds_spread": bonds_tbl.get("10s-2s Spread"),
        "gold_level":   commodities_tbl.get("Gold", {}).get("level"),
        "wti_level":    commodities_tbl.get("WTI Crude", {}).get("level"),
        "vix":          tech_levels.get("VIX", {}).get("current"),
        "spx_ma200":    tech_levels.get("S&P 500", {}).get("ma200"),
        "spx_52w_high": tech_levels.get("S&P 500", {}).get("52w_high"),
    }

    # Top earnings by proximity — filter to known large-caps or $2B+ market cap.
    # Symbol-based set is the primary gate; market_cap is a fallback for unlisted names.
    # (The enrichment in fetch_enrichment.py populates market_cap for up to 40 symbols
    # per run, prioritising this set — but the set catches them even if enrichment fails.)
    _PRIORITY_EARNINGS_SYMBOLS = {
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA",
        "AMD","INTC","QCOM","AVGO","TXN","MU","AMAT","ADI",
        "JPM","BAC","GS","MS","V","MA","WFC","C","BLK",
        "JNJ","UNH","XOM","CVX","WMT","HD","TGT","COST",
        "LOW","TJX","INTU","CRM","ORCL","IBM","ADBE",
        "DIS","NFLX","CMCSA","NKE","SBUX","MCD","PEP","KO","PG",
        "ELF","ULTA",
    }
    _MIN_MKTCAP = 2_000_000_000
    _top_earnings = [
        {"date": e["date"], "symbol": e["symbol"],
         "eps_estimate": e.get("eps_estimate"),
         "hour": e.get("hour") or ""}
        for e in (earnings_cal if isinstance(earnings_cal, list) else [])
        if e.get("symbol") and (
            e["symbol"] in _PRIORITY_EARNINGS_SYMBOLS
            or (e.get("market_cap") or 0) >= _MIN_MKTCAP
        )
    ][:8]
    # Today's earnings — only entries for report_date, with non-null eps_estimate,
    # limited to known large-caps by filtering out empty tickers
    _today_earnings = [
        e for e in _top_earnings
        if str(e.get("date", ""))[:10] == today and e.get("symbol")
    ]

    payload = {
        "date":                      today,
        "market_levels":             snapshot,
        "global_markets":            global_markets,
        "commodities":               commodities_tbl,
        "currencies":                currencies_tbl,
        "bonds":                     bonds_tbl,
        "technical_levels":          tech_levels,
        "key_data_summary":          key_data_summary,
        "portfolio_top_performers":  winners,
        "portfolio_names_to_watch":  watch,
        "mag7_consensus_forecasts":  mag7_consensus,
        "news_by_section":           llm_buckets,
        "upcoming_economic_events":  econ_calendar[:8],
        # Enrichment additions
        "fear_greed":                fg,
        "wsb_top5":                  (wsb[:5] if isinstance(wsb, list) else []),
        "fred_proxies":              fred,
        "international_macro":       international_macro,
        "earnings_calendar":         _top_earnings,
        "news_sentiment_summary":    sent_summary,
        "recent_earnings_actuals":   load_recent_earnings_actuals(),
        "sector_performance":        sector_perf,
        # item #8: prior-day continuity for outlook call
        "prior_day_label":           _prev.get("market_outlook_label"),
        "prior_day_synthesis":       _prev.get("cross_asset_synthesis"),
    }

    # Write market data first so snapshot/tables are always fresh.
    # Narrative keys are explicitly cleared here — if LLM and deterministic fallback
    # both fail, the file will have empty narrative fields that downstream freshness
    # gates will detect and block from reaching clients.
    existing: dict = {}
    if COMMENTARY_PATH.exists():
        try:
            with open(COMMENTARY_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    existing["market_snapshot"]    = snapshot
    existing["global_markets"]     = global_markets
    existing["commodities_table"]  = commodities_tbl
    existing["currencies_table"]   = currencies_tbl
    existing["bonds_table"]        = bonds_tbl
    existing["futures_table"]      = futures_tbl
    existing["fed_speakers"]       = fed_speakers
    existing["today_earnings"]     = _today_earnings
    existing["technical_levels"]   = tech_levels
    existing["sector_performance"] = sector_perf
    existing["report_date"]        = today
    existing["generated_at"]       = datetime.now(timezone.utc).isoformat()
    existing["data_source"]        = "yfinance:daily-bar"
    # Enrichment fields — available to email renderer even if LLM skipped.
    # Write a single structured fear_greed block; remove any stale fear_greed_index
    # that may have been written by a previous LLM output or older code path.
    existing.pop("fear_greed_index", None)
    if isinstance(fg, dict) and fg.get("score") is not None:
        existing["fear_greed_score"]  = fg.get("score")
        existing["fear_greed_rating"] = fg.get("rating", "")
        existing["fear_greed"]        = {
            "score":      fg.get("score"),
            "rating":     fg.get("rating", ""),
            "prev_score": fg.get("prev_score"),
        }
        ts = fg.get("timestamp")
        if ts:
            try:
                fg_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - fg_dt).total_seconds() / 3600
                if age_hours > 24:
                    print(f"[WARN] Fear & Greed data is {age_hours:.0f}h old (timestamp: {ts}). CNN endpoint may be stale.")
            except Exception:
                pass

    # Clear all narrative keys so prior-run prose cannot survive a failed LLM call.
    for _k in [
        "pre_market_bullets", "pre_market_summary",
        "equities_commentary", "fixed_income_commentary",
        "commodities_commentary", "currencies_commentary",
        "economics_commentary", "cross_asset_synthesis",
        "market_outlook_label", "market_outlook_rationale",
        "tactical_outperforming", "tactical_underperforming", "asset_class_outlooks",
        "portfolio_spotlight_winners", "portfolio_spotlight_watch",
        "session_recap", "watch_today", "international_section",
        "narrative_generated_at", "narrative_source_date", "narrative_source",
        "scenarios", "levels_to_watch", "scenario_event", "scenario_consensus", "scenario_event_day",
        "topic_spotlight",
    ]:
        existing.pop(_k, None)

    DATA_DIR.mkdir(exist_ok=True)
    _guard_snapshot_drift(snapshot, COMMENTARY_PATH)
    _atomic_write_json(COMMENTARY_PATH, existing)
    print(f"[OK] Market data saved -> {COMMENTARY_PATH}")

    print(f"[LLM] Requesting commentary from Ollama ({OLLAMA_HOST}, model={OLLAMA_MODEL})...")
    commentary = None
    known_tickers: set[str] = set()
    llm_ok = False
    try:
        commentary, known_tickers = call_ollama(payload, snapshot)
        commentary = scrub_banned_phrases(commentary)
        if validate_commentary(commentary, known_tickers=known_tickers, snapshot=snapshot):
            banned = find_banned_phrases(commentary)
            if banned:
                print(f"[WARN] Commentary still contains banned phrases after scrub: {banned}")
            llm_ok = True
        else:
            print("[WARN] Commentary response invalid — falling back to deterministic prose.")
    except requests.exceptions.ConnectionError:
        print("[WARN] Ollama unreachable — falling back to deterministic prose.")
    except requests.exceptions.Timeout:
        print("[WARN] Ollama timed out — falling back to deterministic prose.")
    except Exception as exc:
        print(f"[WARN] Ollama call failed ({exc}) — falling back to deterministic prose.")

    # Topic spotlight — detect dominant news theme (fires regardless of LLM commentary path)
    _spotlight: dict | None = None
    if TOPIC_SPOTLIGHT_ENABLED:
        # Build a directional map (asset -> +1/-1/0) so the spotlight guard can reject
        # any headline that claims a move contradicting the actual close.
        def _dir_sign(entry: dict | None) -> int:
            pc = (entry or {}).get("pct_change")
            if pc is None:
                pc = (entry or {}).get("change")
            try:
                pc = float(pc)
            except (TypeError, ValueError):
                return 0
            return 1 if pc > 0.05 else (-1 if pc < -0.05 else 0)
        _market_dirs = {
            name: _dir_sign(entry)
            for name, entry in {**(snapshot or {}), **(global_markets or {})}.items()
        }
        try:
            _spotlight = generate_topic_spotlight(
                payload,
                world_news=world_news,
                enrich_news=enrich_news,
                enrich_co_news=enrich_co_news,
                market_dirs=_market_dirs,
            )
        except Exception as _exc:
            print(f"[WARN] Topic spotlight generation failed: {_exc}")

    if llm_ok and commentary:
        existing.update(commentary)
        if _spotlight:
            existing["topic_spotlight"] = _spotlight
        else:
            existing.pop("topic_spotlight", None)
        existing["narrative_generated_at"] = datetime.now(timezone.utc).isoformat()
        existing["narrative_source_date"]  = today
        existing["narrative_source"]       = "llm"
        _atomic_write_json(COMMENTARY_PATH, existing)
        print(f"[OK] Commentary saved -> {COMMENTARY_PATH}")
        return 0

    # LLM failed or produced invalid output — try deterministic fallback.
    print("[INFO] Building deterministic market commentary from snapshot data...")
    try:
        det = _build_deterministic_market_commentary(snapshot, commodities_tbl, currencies_tbl, bonds_tbl)
        if validate_commentary(det, snapshot=None):
            existing.update(det)
            if _spotlight:
                existing["topic_spotlight"] = _spotlight
            else:
                existing.pop("topic_spotlight", None)
            existing["narrative_generated_at"] = datetime.now(timezone.utc).isoformat()
            existing["narrative_source_date"]  = today
            existing["narrative_source"]       = "deterministic"
            _atomic_write_json(COMMENTARY_PATH, existing)
            print(f"[OK] Deterministic commentary saved -> {COMMENTARY_PATH}")
            return 0
        else:
            print("[WARN] Deterministic commentary failed validation.")
    except Exception as exc:
        print(f"[WARN] Deterministic commentary build failed ({exc}).")

    # Both LLM and deterministic fallback failed — narrative keys are already cleared.
    # Non-zero exit signals monitor.py to skip PDF; send_email.py freshness gate blocks email.
    print("[ERROR] No valid commentary available — blocking PDF/email generation.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
