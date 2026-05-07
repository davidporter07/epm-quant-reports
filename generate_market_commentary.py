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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OLLAMA_HOST    = os.getenv("LOCAL_OLLAMA_URL",     "http://100.101.63.65:11434")
OLLAMA_MODEL   = os.getenv("LOCAL_OLLAMA_MODEL",   "qwen2.5:14b")
OLLAMA_TIMEOUT = int(os.getenv("LOCAL_OLLAMA_TIMEOUT", "900"))

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

# ---------------------------------------------------------------------------
# Market data helpers
# ---------------------------------------------------------------------------
def _fetch_quote(ticker: str, days_back: int = 7, prev_close: float | None = None) -> dict | None:
    """Return {level, change, pct_change} for a single ticker, or None.

    Tries fast_info first for a live intraday quote (avoids 0% pct_change when
    the daily bar is incomplete at market open). Falls back to historical daily bars.
    """
    if yf is None:
        return None
    # --- fast_info path: live intraday price vs previous session close ---
    try:
        fi = yf.Ticker(ticker).fast_info
        last = float(fi.last_price)
        prev_fi = float(fi.previous_close)
        if last > 0 and prev_fi > 0:
            # Honour stored prev_close for contract-roll tickers (futures) when provided.
            prev = prev_close if (prev_close and prev_close > 0) else prev_fi
            change = last - prev
            pct    = (change / prev) * 100
            return {
                "level":      round(last, 4),
                "change":     round(change, 4),
                "pct_change": round(pct, 2),
            }
    except Exception:
        pass
    # --- fallback: historical daily bars ---
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
        if len(closes) < 1:
            return None
        arr    = closes.to_numpy()
        latest = float(arr[-1])
        # Use the stored previous close when provided — avoids phantom swings caused
        # by futures contract rolls (BZ=F, CL=F, GC=F, etc.) where consecutive daily
        # closes in Yahoo Finance can be from different contract months.
        if prev_close is not None and prev_close > 0:
            prev = prev_close
        elif len(arr) >= 2:
            prev = float(arr[-2])
        else:
            return None
        change = latest - prev
        pct    = (change / prev) * 100
        return {
            "level":      round(latest, 4),
            "change":     round(change, 4),
            "pct_change": round(pct, 2),
        }
    except Exception:
        return None


def _prev_level(prev_data: dict | None, name: str) -> float | None:
    """Extract the stored previous level for a named instrument, or None."""
    if not prev_data:
        return None
    try:
        val = float(prev_data.get(name, {}).get("level") or 0)
        return val if val > 0 else None
    except Exception:
        return None


def fetch_market_snapshot(prev_data: dict | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name, ticker in MARKET_TICKERS.items():
        q = _fetch_quote(ticker, prev_close=_prev_level(prev_data, name))
        if q:
            result[name] = q
    return result


def fetch_global_markets(prev_data: dict | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name, ticker in GLOBAL_TICKERS.items():
        q = _fetch_quote(ticker, prev_close=_prev_level(prev_data, name))
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
        # Also fetch prior month in case today is early in the month
        prev_month = (today.replace(day=1) - timedelta(days=1))
        ym_prev = prev_month.strftime("%Y%m")

        rows = _fetch_month(ym_cur)
        if len(rows) < 2:
            rows.update(_fetch_month(ym_prev))

        sorted_dates = sorted(rows.keys())
        if len(sorted_dates) < 2:
            return {}

        today_row = rows[sorted_dates[-1]]
        prev_row  = rows[sorted_dates[-2]]

        def _build(field: str) -> dict | None:
            try:
                cur  = float(today_row[field])
                prev = float(prev_row[field])
                chg  = round(cur - prev, 3)
                pct  = round(chg / prev * 100, 2) if prev else None
                return {"level": cur, "change": chg, "pct_change": pct}
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
            result["10s-2s Spread"] = {
                "level": round((y10 - y2) * 100, 1),
                "change": spread_chg,
                "pct_change": None,
            }
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
        "fomc press release":                          ("FOMC Meeting / Rate Decision",          "high"),
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
    out.sort(key=lambda r: r.get("earnings_date") or "", reverse=True)
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
ONE-SHOT CALIBRATION — geopolitical tone (follow this pattern exactly):
  Headline in payload: "U.S. and Israel expand strikes near Iranian facilities; diplomatic talks stall"
  BAD: "Mounting costs of the Iran war strain U.S. finances as the conflict widens."
  GOOD: "Markets are pricing a higher risk premium after reports of expanded strikes near Iranian facilities; diplomatic talks remain unresolved."
  Rule: mirror the payload's exact language — do not upgrade 'strikes' to 'war', do not assert fiscal or political consequences as fact, do not name a conflict as an ongoing war unless the payload explicitly uses that word.
Do NOT cite foreign central banks (BoE, ECB, BoJ, PBoC, RBA, BoC, SNB) or foreign sovereign yields (Gilts, Bunds, JGBs) as drivers of US asset moves unless a US-asset headline in the payload explicitly names that institution. Foreign monetary policy may move foreign assets in the international section; for US equities, US bonds, and US dollar commentary, drivers must come from the US payload.
Return ONLY valid JSON  no markdown fences, no explanation."""

# Call 1: Market narrative sections
SYSTEM_PROMPT_NARRATIVE = WRITING_RULES + """

Return JSON with EXACTLY these 6 keys:

NUMBER FIDELITY (non-negotiable):
- Every percent and price you cite MUST equal the value in the payload to within 0.01.
- S&P 500: use market_levels["S&P 500"]["pct_change"] for the percent; ["level"] for the price.
- Apply the same rule for Nasdaq 100, DXY, 10-Yr Yield, Gold, WTI Crude against market_levels / bonds / commodities_top6 / currencies_top5.
- Direction words (rose/fell/gained/slid) MUST agree with the SIGN of pct_change. A pct_change of -0.04% is "essentially flat" or "barely changed" — NOT "lower" or "fell".
- If a number is missing from the payload, OMIT it entirely. Do NOT estimate, round, or invent.
- Tickers in recent_earnings_actuals have ALREADY released earnings this week — never write "later this week" or "upcoming earnings" for them. If you mention one, cite the reported EPS and surprise % from the payload.

pre_market_bullets: Array of 5 strings:
  [0] "Markets closed [higher/lower]  S&P 500 [pct]%, Nasdaq 100 [pct]%; [specific catalyst from news]."
  [1] International/macro driver  cite a specific event from the payload.
  [2] Economic calendar: if there are events today in upcoming_economic_events, cite the most important one (name the event and its importance). If there are no events today, OMIT this bullet entirely and produce only 4 items total.
  [3] Fed/rates: cite 10-yr yield level and direction with a specific driver.
  [4] Top commodity or currency move with level and driver.

FLAT-DAY CALIBRATION: when |pct_change| < 0.10 for an index, write "essentially flat at [level]" instead of citing only a percent. Example:
  BAD: "S&P 500 unchanged% at 7,365.12"   (template substitution failure)
  BAD: "S&P 500 +0.04% — markets unchanged" (contradictory)
  GOOD: "S&P 500 closed essentially flat at 7,365.12 (+0.04%)"
  GOOD: "Markets closed mixed — S&P 500 essentially flat (+0.04%), Nasdaq 100 -0.12%; [catalyst]"

equities_commentary: 5-8 sentences. Lead with S&P 500 direction and level. Sector leadership. Connect to macro driver from news. Global market context. Risk ahead.

fixed_income_commentary: 5-6 sentences. Lead with 10-yr yield direction and exact level. Connect to inflation/growth data. For the 2s10s spread: read bonds["10s-2s Spread"]["change"] from the payload — if that value is negative the spread NARROWED (flattened), if positive it WIDENED (steepened); state the direction and magnitude in basis points. Implication for equity multiples.

commodities_commentary: 5-6 sentences. WTI direction and level first, then gold. Specific fundamental driver for each. Key price level nearby. Connect to macro thesis.

currencies_commentary: 4-5 sentences. DXY direction and level. Rate differential or trade-flow driver. EUR/USD and JPY if notable. EM implication.

economics_commentary: 4-5 sentences. Most important recent data release from payload (actual vs consensus). Macro cycle context (soft landing, slowdown, re-acceleration). Fed implications.

STRUCTURE EXAMPLE — shows format only; replace {placeholders} with EXACT values from the payload (do NOT reuse placeholder syntax in your output):
{"pre_market_bullets":["Markets closed {higher/lower} — S&P 500 {spx_pct}%, Nasdaq 100 {ndx_pct}%; [specific catalyst from recent_headlines].","[International index] {rose/fell} {pct}% as [specific macro driver from payload].","Key data today: [event from upcoming_economic_events] ({importance}) — consensus [value] vs prior [value]; [implication].","10-yr yield {rose/fell} {bps} bps to {ust10_level}%, [specific driver]; real yields [direction].","[Top commodity or currency] {rose/fell} {pct}% to {level} on [specific driver from payload]."],...}

Output schema (replace "..." with your generated content for all 6 keys):
{"pre_market_bullets":["...","...","...","...","..."],"equities_commentary":"...","fixed_income_commentary":"...","commodities_commentary":"...","currencies_commentary":"...","economics_commentary":"..."}"""

# Call 2: Outlook, allocation, portfolio spotlight
SYSTEM_PROMPT_OUTLOOK = WRITING_RULES + """

Return JSON with EXACTLY these 7 keys:

market_outlook_label: Exactly one of: "Bullish", "Cautious", "Neutral", "Bearish"  near-term 4-6 week equity view.

market_outlook_rationale: Exactly 2 sentences. Sentence 1: primary supporting factor. Sentence 2: key risk that could change the label.

tactical_outperforming: Short phrase (3-5 words)  sectors/themes outperforming. E.g., "Technology, energy, small caps".

tactical_underperforming: Short phrase (3-5 words)  sectors/themes lagging. E.g., "Regional banks, consumer discretionary".

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
  [0] Economic data: cite the most important event from upcoming_economic_events or "No major data today."
  [1] Earnings/corporate: cite from earnings_calendar (symbol + timing) or "No major earnings today."
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
- Name the single most important upcoming catalyst (from upcoming_economic_events or earnings_upcoming) and state exactly what outcome you are watching for (beat vs miss, hawkish vs dovish).
- The tone MUST be consistent with market_outlook_label: if Cautious, explain the specific mechanism of risk without adding false balance; if Bullish, name the specific driver without inventing caveats.
- 3-4 sentences total. No preamble. No conclusion phrase. Start directly with the cross-asset theme.

ONE-SHOT EXAMPLE:
  market_outlook_label: "Cautious"
  BAD: "Markets face multiple headwinds but show resilience; the outlook remains mixed as investors weigh risks against opportunities."
  GOOD: "WTI's 6% surge above $105 is feeding directly into 10-yr yield pressure at 4.36%, which in turn is compressing Nasdaq multiples — the oil-rates-tech linkage is the dominant driver today. The dollar's modest strengthening (+0.2%) confirms the market is pricing a sticky-inflation regime rather than a growth shock. Friday's Core PCE print is the key release: an above-consensus read would validate the hawkish rate path and add another leg down in tech; a miss would relieve duration pressure and let the MAG7 stabilize."

JSON template:
{"cross_asset_synthesis":"..."}"""

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


def scrub_banned_phrases(data: dict) -> dict:
    """Post-process commentary dict: replace banned phrases with accurate alternatives."""
    for key in NARRATIVE_KEYS:
        val = data.get(key)
        if isinstance(val, list):
            data[key] = [_scrub_text(item) if isinstance(item, str) else item for item in val]
        elif isinstance(val, str):
            data[key] = _scrub_text(val)
    return data

NARRATIVE_KEYS = [
    "pre_market_bullets", "equities_commentary", "fixed_income_commentary",
    "commodities_commentary", "currencies_commentary", "economics_commentary",
    "market_outlook_rationale",
    "session_recap", "watch_today", "international_section",
    "cross_asset_synthesis",
]


def _call_ollama_raw(system: str, user_payload: dict) -> dict:
    body = {
        "model":   OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": json.dumps(user_payload, default=str)},
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_predict": 2048,
            "num_ctx":     8192,
        },
    }
    resp = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json=body,
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    return json.loads(content)


def call_ollama(payload: dict) -> dict:
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

    # Flatten news to a plain headline list — avoids model templating output after section names
    # Articles in llm_buckets are pre-formatted strings (headline + summary snippet)
    flat_headlines = [
        a if isinstance(a, str) else (a.get("headline") or a.get("title") or "")
        for articles in news_trimmed.values()
        for a in articles
        if a
    ][:15]

    narrative_payload = {
        "date":                     payload.get("date"),
        "market_levels":            levels,
        "bonds":                    bonds,
        "global_markets_top5":      gm,
        "commodities_top6":         cmdty,
        "currencies_top5":          fx,
        "upcoming_economic_events": econ,
        "recent_headlines":         flat_headlines,
        "recent_earnings_actuals":  payload.get("recent_earnings_actuals") or [],
    }

    print("  [LLM Call 1/3] Generating market narrative sections...")
    part1 = {}
    for attempt in range(2):
        try:
            part1 = _call_ollama_raw(SYSTEM_PROMPT_NARRATIVE, narrative_payload)
            print(f"    Keys returned: {list(part1.keys())}")
            # Remap aliases to canonical keys BEFORE scrubbing so scrubber finds them
            for alias, canonical in LLM_KEY_ALIASES.items():
                if alias in part1 and canonical not in part1:
                    part1[canonical] = part1.pop(alias)
            part1 = scrub_banned_phrases(part1)
            banned = find_banned_phrases(part1)
            leaks = find_leaked_placeholders(part1)
            if not banned and not leaks:
                break
            if banned:
                print(f"  [RETRY] Attempt {attempt + 1} still contained banned phrases after scrub: {banned}. Retrying...")
            if leaks:
                print(f"  [RETRY] Attempt {attempt + 1} contained leaked placeholders: {leaks}. Retrying...")
        except Exception as exc:
            print(f"  [WARN] Narrative call failed (attempt {attempt + 1}): {exc}")
            part1 = {}

    # Compact payload for outlook call
    outlook_payload = {
        "date":                      payload.get("date"),
        "market_levels":             levels,
        "key_data_summary":          payload.get("key_data_summary"),
        "portfolio_top_performers":  payload.get("portfolio_top_performers"),
        "portfolio_names_to_watch":  payload.get("portfolio_names_to_watch"),
        "mag7_consensus_forecasts":  payload.get("mag7_consensus_forecasts"),
        "news_headlines":            {k: v[:2] for k, v in news_trimmed.items()},
    }

    print("  [LLM Call 2/3] Generating market outlook and portfolio intelligence...")
    part2 = {}
    for attempt in range(2):
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
        "upcoming_economic_events": econ,
        "earnings_calendar":        (payload.get("earnings_calendar") or [])[:5],
        "international_macro":      payload.get("international_macro") or {},
        "fear_greed":               payload.get("fear_greed") or {},
        "news_headlines":           {k: v[:2] for k, v in news_trimmed.items()},
        "recent_earnings_actuals":  payload.get("recent_earnings_actuals") or [],
    }

    print("  [LLM Call 3/3] Generating session recap and watch-today section...")
    part3 = {}
    for attempt in range(2):
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
        "market_outlook_label":     part2.get("market_outlook_label"),
        "equities_commentary":      part1.get("equities_commentary", ""),
        "fixed_income_commentary":  part1.get("fixed_income_commentary", ""),
        "commodities_commentary":   part1.get("commodities_commentary", ""),
        "currencies_commentary":    part1.get("currencies_commentary", ""),
        "economics_commentary":     part1.get("economics_commentary", ""),
        "upcoming_economic_events": econ,
        "earnings_upcoming":        (payload.get("earnings_calendar") or [])[:3],
    }

    print("  [LLM Call 4/4] Generating cross-asset synthesis...")
    part4 = {}
    for attempt in range(2):
        try:
            part4 = _call_ollama_raw(SYSTEM_PROMPT_SYNTHESIS, synthesis_payload)
            print(f"    Keys returned: {list(part4.keys())}")
            part4 = scrub_banned_phrases(part4)
            banned = find_banned_phrases(part4)
            leaks = find_leaked_placeholders(part4)
            if not banned and not leaks:
                break
            if banned:
                print(f"  [RETRY] Attempt {attempt + 1} synthesis still had banned phrases: {banned}. Retrying...")
            if leaks:
                print(f"  [RETRY] Attempt {attempt + 1} contained leaked placeholders: {leaks}. Retrying...")
        except Exception as exc:
            print(f"  [WARN] Synthesis call failed (attempt {attempt + 1}): {exc}")
            part4 = {}

    merged = {**part1, **part2, **part3, **part4}

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
    }
    unexpected = set(merged) - _ALLOWED_LLM_KEYS
    if unexpected:
        print(f"[VALIDATE] Stripping unexpected LLM keys: {sorted(unexpected)}")
    merged = {k: v for k, v in merged.items() if k in _ALLOWED_LLM_KEYS}

    return merged, known_tickers


def find_banned_phrases(data: dict) -> list[str]:
    found = []
    for key in NARRATIVE_KEYS:
        val = data.get(key, "")
        text = " ".join(val) if isinstance(val, list) else str(val)
        text = text.lower()
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

    # Magnitude + sign check for fields where the first % is the pct_change.
    # fixed_income excluded — yield level (e.g. "4.39%") ≠ yield pct_change.
    checks = [
        ("equities_commentary",    "S&P 500"),
        ("commodities_commentary", "WTI Crude"),
        ("currencies_commentary",  "U.S. Dollar (DXY)"),
    ]
    violations = []
    for narrative_key, snap_key in checks:
        snap = (snapshot or {}).get(snap_key) or {}
        truth_pct = snap.get("pct_change")
        if truth_pct is None:
            continue
        if abs(truth_pct) < 0.1:
            # Snapshot too close to zero to enforce sign — likely stale/pre-open data.
            continue
        prose = data.get(narrative_key, "")
        cited = _first_pct(prose if isinstance(prose, str) else " ".join(prose))
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
                    if truth_pct is not None and (truth_pct >= 0) != (cited >= 0):
                        violations.append(
                            f"pre_market_bullets: mentions {snap_key} {cited:+.2f}% but snapshot is {truth_pct:+.2f}% (sign mismatch)"
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
        violations = _check_numeric_consistency(data, snapshot)
        if violations:
            print(f"[VALIDATE] Numeric consistency violations vs market_snapshot: {violations}")
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
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    today = datetime.today().strftime("%Y-%m-%d")

    # Load yesterday's stored levels before fetching so each instrument's
    # prev_close reference is the value we actually reported last run.
    _prev: dict = {}
    if COMMENTARY_PATH.exists():
        try:
            with open(COMMENTARY_PATH, "r", encoding="utf-8") as _pf:
                _prev = json.load(_pf)
        except Exception:
            pass

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
        snapshot["10-Yr Yield"] = {
            "level":      _tsy_10y["level"],
            "change":     _tsy_10y.get("change"),
            "pct_change": _tsy_10y.get("pct_change"),
        }
        print(f"  [OK] Snapshot 10-Yr synced to Treasury.gov: {_tsy_10y['level']:.3f}%")

    tech_levels      = fetch_technical_levels()
    print(f"  [OK] Technical levels: {len(tech_levels)} assets")

    print("[DATA] Loading portfolio data...")
    df = load_portfolio_df()
    winners, watch     = build_portfolio_spotlight(df) if not df.empty else ([], [])
    mag7_consensus     = build_mag7_consensus(df)      if not df.empty else {}
    news_buckets       = load_news_headlines()

    print("[NET] Fetching world news...")
    world_news = fetch_world_news()

    print("[CAL] Fetching economic calendar...")
    econ_calendar = fetch_economic_calendar()

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
            entry = a.get("headline", "")
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

    # Top 10 earnings by proximity (already sorted by date)
    _top_earnings = [
        {"date": e["date"], "symbol": e["symbol"],
         "eps_estimate": e.get("eps_estimate"), "hour": e.get("hour")}
        for e in (earnings_cal if isinstance(earnings_cal, list) else [])[:10]
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
    existing["technical_levels"]   = tech_levels
    existing["report_date"]        = today
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
    ]:
        existing.pop(_k, None)

    DATA_DIR.mkdir(exist_ok=True)
    _atomic_write_json(COMMENTARY_PATH, existing)
    print(f"[OK] Market data saved -> {COMMENTARY_PATH}")

    print(f"[LLM] Requesting commentary from Ollama ({OLLAMA_HOST}, model={OLLAMA_MODEL})...")
    commentary = None
    known_tickers: set[str] = set()
    llm_ok = False
    try:
        commentary, known_tickers = call_ollama(payload)
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

    if llm_ok and commentary:
        existing.update(commentary)
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
