"""
fetch_enrichment.py

Pulls supplemental data that enriches LLM commentary and feeds candidate DL features.
Writes data/enrichment.json — consumed by generate_market_commentary.py.

Sources (all free, no scrapers):
  - CNN Fear & Greed Index      (public dataviz endpoint, no key)
  - Alternative.me crypto F&G  (api.alternative.me, no key)
  - ApeWisdom WSB sentiment     (api.apewisdom.io, no key)
  - FRED macro proxies          (api.stlouisfed.org, FRED_API_KEY)
  - Finnhub market news         (finnhub.io, FINNHUB_KEY — free tier)
  - Finnhub earnings calendar   (finnhub.io, FINNHUB_KEY — free tier)
  - OECD Composite Leading Indicators (sdmx.oecd.org, no key)
  - VADER headline scoring      (vaderSentiment, local)
  - EPM Composite Sentiment     (computed from above signals)

Run standalone:
    python fetch_enrichment.py

Or import:
    from fetch_enrichment import run_enrichment
    enrichment = run_enrichment()          # returns dict, also saves JSON
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

ROOT     = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT_PATH = DATA_DIR / "enrichment.json"

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------
try:
    from epm_secrets import FRED_API_KEY, FINNHUB_KEY, ALPHA_VANTAGE_KEY
except ImportError:
    FRED_API_KEY      = ""
    FINNHUB_KEY       = ""
    ALPHA_VANTAGE_KEY = ""

_TODAY     = datetime.today().strftime("%Y-%m-%d")
_YESTERDAY = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
_NEXT2W    = (datetime.today() + timedelta(days=14)).strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# VADER sentiment scorer
# ---------------------------------------------------------------------------
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer as _VADER
    _sia = _VADER()
    def score_headline(text: str) -> float:
        """Return VADER compound score: -1.0 (very negative) to +1.0 (very positive)."""
        return round(_sia.polarity_scores(str(text))["compound"], 3)
except ImportError:
    def score_headline(text: str) -> float:  # type: ignore[misc]
        """Fallback keyword scorer when vaderSentiment is unavailable."""
        pos = {"rally", "surge", "gain", "rise", "climb", "beat", "strong",
               "recover", "rebound", "record", "profit", "bullish", "growth"}
        neg = {"fall", "drop", "decline", "slump", "crash", "miss", "weak",
               "bearish", "recession", "loss", "fear", "selloff", "tariff",
               "plunge", "concern", "warning", "default", "crisis"}
        words = set(str(text).lower().split())
        p = len(words & pos)
        n = len(words & neg)
        total = max(p + n, 1)
        return round((p - n) / total, 3)


# ---------------------------------------------------------------------------
# 1. CNN Fear & Greed
# ---------------------------------------------------------------------------
def fetch_fear_greed() -> dict[str, Any]:
    """Return current Fear & Greed score + rating from CNN dataviz endpoint."""
    try:
        headers = {
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer":         "https://www.cnn.com/markets/fear-and-greed",
            "Origin":          "https://www.cnn.com",
        }
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers=headers, timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        fg   = data.get("fear_and_greed", {})
        hist = data.get("fear_and_greed_historical", {}).get("data", [])
        # Previous close (most recent historical point)
        prev = hist[-1] if hist else {}
        result = {
            "score":      round(float(fg.get("score", 0)), 1),
            "rating":     str(fg.get("rating", "")).replace("_", " "),
            "prev_score": round(float(prev.get("y", fg.get("score", 0))), 1) if prev else None,
            "timestamp":  fg.get("timestamp"),
            "source":     "cnn_fear_greed",
        }
        print(f"[ENRICH] Fear & Greed: {result['score']} ({result['rating']})")
        return result
    except Exception as exc:
        print(f"[WARN] Fear & Greed fetch failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# 2. WSB sentiment via ApeWisdom
# ---------------------------------------------------------------------------
def fetch_wsb_sentiment(top_n: int = 25) -> list[dict]:
    """Return top N tickers mentioned on r/wallstreetbets with mention + upvote counts."""
    try:
        r = requests.get(
            "https://apewisdom.io/api/v1.0/filter/wallstreetbets/page/1",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        out = []
        for i, item in enumerate(results[:top_n], 1):
            out.append({
                "rank":     i,
                "ticker":   str(item.get("ticker", "")).upper(),
                "name":     str(item.get("name", "")),
                "mentions": int(item.get("mentions") or 0),
                "upvotes":  int(item.get("upvotes") or 0),
                "mentions_24h_ago": int(item.get("mentions_24h_ago") or 0),
            })
        print(f"[ENRICH] WSB sentiment: {len(out)} tickers (top: {out[0]['ticker'] if out else 'none'})")
        return out
    except Exception as exc:
        print(f"[WARN] WSB sentiment fetch failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# 3. FRED macro proxies
# ---------------------------------------------------------------------------
_FRED_SERIES: dict[str, str] = {
    # US leading indicators
    "initial_claims":           "ICSA",          # weekly initial jobless claims
    "breakeven_inflation_10y":  "T10YIE",        # 10Y TIPS breakeven inflation
    "umich_consumer_sentiment": "UMCSENT",       # University of Michigan sentiment
    "fed_funds_target_upper":   "DFEDTARU",      # Fed funds rate upper bound
    # US macro KPIs
    "unemployment_rate":        "UNRATE",        # Unemployment rate (%)
    "cpi_yoy":                  "CPIAUCSL",      # CPI All Items — fetched with units=pc1 for YoY %
    "nonfarm_payrolls":         "PAYEMS",        # Total nonfarm payrolls (thousands, SA)
    # International / macro context
    "eu_cpi_hicp":              "CP0000EZ19M086NEST",  # Euro area HICP all-items index
    "jpy_per_usd":              "DEXJPUS",              # JPY per USD exchange rate
    "eur_per_usd":              "DEXUSEU",              # EUR per USD exchange rate
    "china_gdp_usd":            "MKTGDPCNA646NWDB",    # China nominal GDP (annual)
    "global_policy_uncertainty":"GEPUCURRENT",          # Global Economic Policy Uncertainty
}


# Extra per-series FRED API params (units transformations, etc.)
_FRED_EXTRA_PARAMS: dict[str, dict] = {
    "cpi_yoy": {"units": "pc1"},  # percent change from year ago
}


def fetch_fred_proxies() -> dict[str, dict]:
    """Pull latest observation for each FRED series. Returns {name: {value, date, series_id}}."""
    if not FRED_API_KEY:
        print("[WARN] FRED_API_KEY not set — skipping FRED proxies")
        return {}

    base = "https://api.stlouisfed.org/fred/series/observations"
    results: dict[str, dict] = {}

    for name, series_id in _FRED_SERIES.items():
        try:
            params = {
                "series_id":    series_id,
                "api_key":      FRED_API_KEY,
                "sort_order":   "desc",
                "limit":        2,
                "file_type":    "json",
                "observation_end": _TODAY,
            }
            params.update(_FRED_EXTRA_PARAMS.get(name, {}))
            r = requests.get(base, params=params, timeout=10)
            r.raise_for_status()
            obs = r.json().get("observations", [])
            # Find the most recent non-"." observation
            latest = next((o for o in obs if o.get("value") not in (".", None, "")), None)
            if latest:
                try:
                    val = float(latest["value"])
                except (ValueError, TypeError):
                    val = None
                results[name] = {
                    "value":     val,
                    "date":      latest.get("date"),
                    "series_id": series_id,
                }
        except Exception as exc:
            print(f"[WARN] FRED {series_id} ({name}) failed: {exc}")

    populated = sum(1 for v in results.values() if v.get("value") is not None)
    print(f"[ENRICH] FRED proxies: {populated}/{len(_FRED_SERIES)} series fetched")
    return results


# ---------------------------------------------------------------------------
# 4. Finnhub market news + sentiment scoring
# ---------------------------------------------------------------------------
_FINNHUB_CATEGORIES = ("general", "forex", "crypto", "merger")


def fetch_finnhub_news(max_per_category: int = 20) -> dict[str, list[dict]]:
    """Fetch and VADER-score market news from Finnhub by category."""
    if not FINNHUB_KEY:
        print("[WARN] FINNHUB_KEY not set — skipping Finnhub news")
        return {}

    result: dict[str, list[dict]] = {}
    for cat in _FINNHUB_CATEGORIES:
        try:
            r = requests.get(
                f"https://finnhub.io/api/v1/news",
                params={"category": cat, "token": FINNHUB_KEY},
                timeout=12,
            )
            r.raise_for_status()
            articles = r.json() or []
            scored = []
            for a in articles[:max_per_category]:
                headline = str(a.get("headline", "")).strip()
                summary  = str(a.get("summary", "")).strip()
                if not headline:
                    continue
                text_for_score = headline + " " + summary[:150]
                scored.append({
                    "headline":  headline,
                    "summary":   summary[:300],
                    "source":    str(a.get("source", "")),
                    "datetime":  a.get("datetime"),
                    "url":       str(a.get("url", "")),
                    "sentiment": score_headline(text_for_score),
                    "category":  cat,
                })
            result[cat] = scored
        except Exception as exc:
            print(f"[WARN] Finnhub news ({cat}) failed: {exc}")
            result[cat] = []

    total = sum(len(v) for v in result.values())
    print(f"[ENRICH] Finnhub news: {total} articles across {len(_FINNHUB_CATEGORIES)} categories")
    return result


def fetch_finnhub_company_news(symbols: list[str], days_back: int = 2) -> list[dict]:
    """Fetch and score company-specific news for a list of symbols."""
    if not FINNHUB_KEY:
        return []
    from_date = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    articles = []
    seen: set[str] = set()
    for sym in symbols:
        try:
            r = requests.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": sym, "from": from_date, "to": _TODAY, "token": FINNHUB_KEY},
                timeout=10,
            )
            r.raise_for_status()
            for a in (r.json() or [])[:8]:
                headline = str(a.get("headline", "")).strip()
                key = headline.lower()[:50]
                if not headline or key in seen:
                    continue
                seen.add(key)
                summary = str(a.get("summary", "")).strip()
                articles.append({
                    "ticker":    sym,
                    "headline":  headline,
                    "summary":   summary[:300],
                    "source":    str(a.get("source", "")),
                    "datetime":  a.get("datetime"),
                    "url":       str(a.get("url", "")),
                    "sentiment": score_headline(headline + " " + summary[:150]),
                })
        except Exception as exc:
            print(f"[WARN] Finnhub company news {sym}: {exc}")
    print(f"[ENRICH] Finnhub company news: {len(articles)} articles for {symbols}")
    return articles


# ---------------------------------------------------------------------------
# 5. Finnhub earnings calendar
# ---------------------------------------------------------------------------
def fetch_earnings_calendar() -> list[dict]:
    """Return upcoming earnings for the next 14 days from Finnhub (free tier)."""
    if not FINNHUB_KEY:
        return []
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"from": _TODAY, "to": _NEXT2W, "token": FINNHUB_KEY},
            timeout=12,
        )
        r.raise_for_status()
        raw = r.json().get("earningsCalendar", []) or []
        out = []
        for e in raw:
            out.append({
                "date":            str(e.get("date", "")),
                "symbol":          str(e.get("symbol", "")),
                "eps_estimate":    e.get("epsEstimate"),
                "eps_actual":      e.get("epsActual"),
                "revenue_estimate": e.get("revenueEstimate"),
                "hour":            str(e.get("hour", "")),  # "bmo" | "amc" | ""
            })
        out.sort(key=lambda x: x["date"])
        # Enrich with market cap so the downstream $2B gate can size names correctly.
        # Priority order: (1) analyst-COVERED names (non-null eps_estimate — Finnhub's
        # own signal that a name is real and report-worthy), near-dated first since `out`
        # is date-sorted; (2) the static large-cap set; (3) everything else. Covered names
        # go first so today's reporters (e.g. AZO, ZS) aren't crowded out of the lookup
        # budget by a 14-day backlog of microcaps and end up with market_cap=None.
        _LARGE_CAP_PRIORITY = {
            "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA",
            "AMD","INTC","QCOM","AVGO","TXN","MU","AMAT","ADI",
            "JPM","BAC","GS","MS","V","MA","WFC","C","BLK",
            "JNJ","UNH","XOM","CVX","WMT","HD","TGT","COST",
            "LOW","TJX","INTU","CRM","ORCL","IBM","ADBE",
            "DIS","NFLX","CMCSA","NKE","SBUX","MCD","PEP","KO","PG",
            "ELF","ULTA",
        }
        _covered  = [e["symbol"] for e in out if e.get("symbol") and e.get("eps_estimate") is not None]
        _priority = [e["symbol"] for e in out if e.get("symbol") in _LARGE_CAP_PRIORITY]
        _rest     = [e["symbol"] for e in out if e.get("symbol")]
        _seen: set[str] = set()
        _symbols: list[str] = []
        for s in _covered + _priority + _rest:
            if s not in _seen:
                _seen.add(s)
                _symbols.append(s)
        _symbols = _symbols[:60]
        if _symbols:
            try:
                import yfinance as yf
                batch = yf.Tickers(" ".join(_symbols))
                _lookup = set(_symbols)
                for e in out:
                    sym = e.get("symbol", "")
                    if sym not in _lookup:
                        continue
                    # Per-ticker guard: a single fast_info failure must NOT abort the
                    # whole loop and strand every later name with market_cap=None.
                    try:
                        t = batch.tickers.get(sym)
                        e["market_cap"] = (t.fast_info.get("marketCap") if t else None) or 0
                    except Exception:
                        e["market_cap"] = 0
            except Exception:
                pass  # batch construction failed; leave market_cap absent
        print(f"[ENRICH] Earnings calendar: {len(out)} events in next 14 days")
        return out
    except Exception as exc:
        print(f"[WARN] Finnhub earnings calendar failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# 6. OECD Composite Leading Indicators (CLI) — free, no auth required
# ---------------------------------------------------------------------------
_OECD_COUNTRY_LABELS: dict[str, str] = {
    "USA": "United States",
    "DEU": "Germany",
    "JPN": "Japan",
    "CHN": "China",
    "GBR": "United Kingdom",
    "FRA": "France",
    "ITA": "Italy",
    "CAN": "Canada",
    "BRA": "Brazil",
    "IND": "India",
}


def fetch_oecd_cli() -> dict[str, dict]:
    """
    Fetch OECD Composite Leading Indicators (amplitude-adjusted) for major economies.
    Uses the OECD SDMX-JSON 2.0 API (sdmx.oecd.org) — free, no API key required.
    Returns {country_name: {value, prev, mom, trend, posture, date}} or {} on failure.

    CLI interpretation:
      > 100: above long-run average (expansion)
      < 100: below long-run average (contraction)
      Rising MoM: momentum improving; Falling MoM: momentum deteriorating
    """
    # Dim key: REF_AREA.FREQ.MEASURE.UNIT_MEASURE.ACTIVITY.ADJUSTMENT.TRANSFORMATION.TIME_HORIZ.METHODOLOGY
    # AA = amplitude-adjusted, IX = index, _Z = not applicable
    countries = "+".join(_OECD_COUNTRY_LABELS.keys())
    url = (
        f"https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_CLI/"
        f"{countries}.M.LI.IX._Z.AA.IX._Z.H"
        f"/all?format=jsondata&lastNObservations=3"
    )
    try:
        r = requests.get(url, headers={"Accept": "application/json"}, timeout=25)
        r.raise_for_status()
        data = r.json()

        # SDMX-JSON 2.0: data.structures[0].dimensions + data.dataSets[0].series
        structs    = data.get("data", {}).get("structures", [{}])
        s0         = structs[0] if structs else {}
        series_dims = s0.get("dimensions", {}).get("series", [])
        time_dim   = (s0.get("dimensions", {}).get("observation") or [{}])[0]
        time_values = time_dim.get("values", [])

        area_dim = next((d for d in series_dims if d.get("id") == "REF_AREA"), {})
        area_values = area_dim.get("values", [])

        datasets = data.get("data", {}).get("dataSets", [{}])
        series_data = (datasets[0] if datasets else {}).get("series", {})

        result: dict[str, dict] = {}
        for series_key, series_val in series_data.items():
            parts = series_key.split(":")
            area_idx = int(parts[0]) if parts else -1
            if area_idx < 0 or area_idx >= len(area_values):
                continue
            country_code  = area_values[area_idx].get("id", "")
            country_label = _OECD_COUNTRY_LABELS.get(country_code, country_code)

            obs = series_val.get("observations", {})
            if not obs:
                continue
            # OECD SDMX-JSON 2.0: observation index 0 = most recent, 1 = one month prior
            sorted_obs = sorted(obs.items(), key=lambda x: int(x[0]))
            vals  = [o[1][0] for o in sorted_obs if o[1] and o[1][0] is not None]
            dates = [time_values[int(o[0])].get("id", "") for o in sorted_obs
                     if int(o[0]) < len(time_values)]

            if len(vals) < 2:
                continue

            latest  = round(float(vals[0]), 2)   # index 0 = most recent
            prev    = round(float(vals[1]), 2)
            mom     = round(latest - prev, 3)
            trend   = "improving" if mom > 0 else "deteriorating" if mom < 0 else "flat"
            posture = "above trend (expansionary)" if latest > 100 else "below trend (contractionary)"

            result[country_label] = {
                "value":   latest,
                "prev":    prev,
                "mom":     mom,
                "trend":   trend,
                "posture": posture,
                "date":    dates[0] if dates else "",
            }

        if result:
            top = list(result.items())[:3]
            print(f"[ENRICH] OECD CLI: {len(result)} economies — "
                  + ", ".join(f"{k}: {v['value']} ({v['trend']})" for k, v in top))
        else:
            print("[WARN] OECD CLI: parsed 0 economies from response")
        return result

    except Exception as exc:
        print(f"[WARN] OECD CLI fetch failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# 7. Alternative.me Crypto Fear & Greed (free, no key)
# ---------------------------------------------------------------------------
def fetch_alternative_me_fg() -> dict[str, Any]:
    """Fetch the Alternative.me Crypto Fear & Greed Index (0–100 scale)."""
    try:
        r = requests.get(
            "https://api.alternative.me/fng/?limit=2",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            return {}
        latest = data[0]
        prev   = data[1] if len(data) > 1 else {}
        score  = int(latest.get("value", 0))
        result = {
            "score":      score,
            "rating":     str(latest.get("value_classification", "")),
            "prev_score": int(prev.get("value", score)) if prev else score,
            "timestamp":  latest.get("timestamp"),
            "source":     "alternative_me",
        }
        print(f"[ENRICH] Alternative.me Crypto F&G: {result['score']} ({result['rating']})")
        return result
    except Exception as exc:
        print(f"[WARN] Alternative.me F&G fetch failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# 9. Reddit r/wallstreetbets sentiment (free public API, no key)
# ---------------------------------------------------------------------------
def fetch_reddit_wsb_sentiment(n_posts: int = 50, min_upvotes: int = 100) -> dict[str, Any]:
    """
    Fetch hot posts from r/wallstreetbets, VADER-score titles weighted by upvotes.
    Returns {score (0-100), label, raw_mean, posts_scored}.
    """
    try:
        r = requests.get(
            "https://www.reddit.com/r/wallstreetbets/hot.json",
            params={"limit": n_posts},
            headers={"User-Agent": "EPMBot/1.0 (market research, contact: research@epm.com)"},
            timeout=12,
        )
        r.raise_for_status()
        posts = r.json().get("data", {}).get("children", [])

        scores: list[float] = []
        weights: list[float] = []
        for p in posts:
            d = p.get("data", {})
            upvotes = int(d.get("score", 0))
            if upvotes < min_upvotes:
                continue
            title = str(d.get("title", ""))
            sent  = score_headline(title)
            w     = math.log(upvotes + 1)
            scores.append(sent * w)
            weights.append(w)

        if not weights:
            print("[WARN] Reddit WSB: no qualifying posts found")
            return {}

        weighted_avg = sum(scores) / sum(weights)
        normalized   = round((weighted_avg + 1) / 2 * 100, 1)
        label = (
            "extreme fear"  if normalized < 25 else
            "fear"          if normalized < 45 else
            "neutral"       if normalized < 55 else
            "greed"         if normalized < 75 else
            "extreme greed"
        )
        result = {
            "score":       normalized,
            "label":       label,
            "raw_mean":    round(weighted_avg, 3),
            "posts_scored": len(weights),
            "source":      "reddit_wsb",
        }
        print(f"[ENRICH] Reddit WSB: {normalized} ({label}) from {len(weights)} posts")
        return result
    except Exception as exc:
        print(f"[WARN] Reddit WSB sentiment failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# 10. Own news headlines sentiment (data/news_headlines.csv — GNews/NewsAPI)
# ---------------------------------------------------------------------------
def fetch_own_news_sentiment(days_back: int = 2) -> dict[str, Any]:
    """
    VADER-score the MARKET-tagged headlines from our own news pipeline
    (update_sentiment.py writes to data/news_headlines.csv via GNews/NewsAPI).
    Returns {score (0-100), label, mean_raw, n_articles}.
    """
    try:
        import pandas as pd
        csv_path = DATA_DIR / "news_headlines.csv"
        if not csv_path.exists():
            return {}

        df = pd.read_csv(csv_path)
        market_df = df[df["Ticker"] == "MARKET"].copy()

        if "PublishedAt" in market_df.columns:
            cutoff = datetime.now() - timedelta(days=days_back)
            try:
                market_df["PublishedAt"] = pd.to_datetime(
                    market_df["PublishedAt"], utc=True, errors="coerce"
                )
                import pandas as pd_ ; tz_cutoff = pd_.Timestamp(cutoff).tz_localize("UTC")
                market_df = market_df[market_df["PublishedAt"] >= tz_cutoff]
            except Exception:
                pass  # Use all rows if date parsing fails

        if market_df.empty:
            return {}

        raw_scores = []
        for _, row in market_df.iterrows():
            headline = str(row.get("Headline", ""))
            summary  = str(row.get("Summary", ""))[:150]
            raw_scores.append(score_headline(headline + " " + summary))

        if not raw_scores:
            return {}

        mean_raw   = sum(raw_scores) / len(raw_scores)
        normalized = round((mean_raw + 1) / 2 * 100, 1)
        label = (
            "bearish"       if mean_raw < -0.15 else
            "mildly bearish" if mean_raw < -0.05 else
            "neutral"       if mean_raw <  0.05 else
            "mildly bullish" if mean_raw <  0.15 else
            "bullish"
        )
        result = {
            "score":      normalized,
            "label":      label,
            "mean_raw":   round(mean_raw, 3),
            "n_articles": len(raw_scores),
            "source":     "own_news",
        }
        print(f"[ENRICH] Own news sentiment: {normalized} ({label}) from {len(raw_scores)} articles")
        return result
    except Exception as exc:
        print(f"[WARN] Own news sentiment failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# 11. CFTC E-mini S&P 500 speculator net positioning (via OpenBB, free)
# ---------------------------------------------------------------------------
_CFTC_SPX_ID    = "13874A"   # E-mini S&P 500 — Chicago Mercantile Exchange
_CFTC_HIST_HALF = 250_000    # rough historical half-range for normalization


def fetch_cftc_spx_positioning() -> dict[str, Any]:
    """
    Fetch the CFTC Commitment of Traders report for E-mini S&P 500 futures.
    Non-commercial (speculator) net position normalized to 0-100:
      0  = extreme net short (extreme fear)
      50 = neutral
      100 = extreme net long (extreme greed)
    """
    try:
        from openbb_cftc.models.cot import CftcCotFetcher

        async def _fetch() -> list:
            f    = CftcCotFetcher()
            data = await f.fetch_data({"id": _CFTC_SPX_ID}, credentials={})
            return list(data)

        items = asyncio.run(_fetch())
        if not items:
            print("[WARN] CFTC COT: no data returned")
            return {}

        d      = items[-1].model_dump()   # most recent report
        longs  = int(d.get("noncomm_positions_long_all",  0) or 0)
        shorts = int(d.get("noncomm_positions_short_all", 0) or 0)
        net    = longs - shorts
        score  = max(0.0, min(100.0, (net + _CFTC_HIST_HALF) / (_CFTC_HIST_HALF * 2) * 100))

        result = {
            "score":        round(score, 1),
            "net_position": net,
            "longs":        longs,
            "shorts":       shorts,
            "date":         str(d.get("date", "")),
            "trend":        "net long" if net > 0 else "net short",
            "source":       "cftc_cot",
        }
        print(f"[ENRICH] CFTC SPX positioning: {score:.1f} (net {net:+,} on {d.get('date','')})")
        return result
    except Exception as exc:
        print(f"[WARN] CFTC positioning failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# 12. Alpha Vantage RSI(14) for SPY  — free tier, 1 call/day
# ---------------------------------------------------------------------------
def fetch_alpha_vantage_rsi(symbol: str = "SPY") -> dict[str, Any]:
    """
    Fetch RSI(14) for SPY from Alpha Vantage (free endpoint).
    RSI is already 0-100 and maps directly to fear/greed:
      RSI < 30  → oversold / fear → low score
      RSI > 70  → overbought / greed → high score
    Score = RSI value directly (already 0-100 scale).
    """
    if not ALPHA_VANTAGE_KEY:
        print("[WARN] ALPHA_VANTAGE_KEY not set — skipping RSI fetch")
        return {}
    try:
        r = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function":    "RSI",
                "symbol":      symbol,
                "interval":    "daily",
                "time_period": 14,
                "series_type": "close",
                "apikey":      ALPHA_VANTAGE_KEY,
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if "Information" in data:
            print(f"[WARN] Alpha Vantage RSI: premium required — {data['Information'][:80]}")
            return {}
        rsi_series = data.get("Technical Analysis: RSI", {})
        if not rsi_series:
            print("[WARN] Alpha Vantage RSI: empty response")
            return {}
        latest_date = sorted(rsi_series.keys())[-1]
        rsi_val     = float(rsi_series[latest_date]["RSI"])
        label = (
            "Oversold (Fear)"    if rsi_val < 30 else
            "Overbought (Greed)" if rsi_val > 70 else
            "Neutral"
        )
        result = {
            "score":  round(rsi_val, 2),
            "label":  label,
            "symbol": symbol,
            "date":   latest_date,
            "source": "alpha_vantage_rsi",
        }
        print(f"[ENRICH] Alpha Vantage RSI({symbol}): {rsi_val:.1f} ({label}) on {latest_date}")
        return result
    except Exception as exc:
        print(f"[WARN] Alpha Vantage RSI failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# 13. SEC EDGAR insider activity  — display-only, no composite weight
# ---------------------------------------------------------------------------
# Top-50 S&P 500 by market cap — broad cross-sector insider coverage
_SEC_INSIDER_SYMBOLS: list[str] = [
    # Mega-cap tech / comm
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "ORCL", "AMD",
    "CRM", "ADBE", "QCOM", "NOW", "INTU", "INTC",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "AXP", "V", "MA", "SPGI",
    # Healthcare
    "JNJ", "UNH", "LLY", "ABBV", "MRK", "PFE", "TMO", "DHR", "AMGN",
    # Consumer / retail
    "PG", "KO", "PEP", "WMT", "COST", "HD", "MCD",
    # Energy
    "XOM", "CVX", "COP",
    # Industrials
    "GE", "CAT", "HON", "UPS",
]


def fetch_sec_insider_activity(
    symbols: list[str] | None = None,
    days_back: int = 30,
    limit_per_symbol: int = 15,
) -> dict[str, Any]:
    """
    Pull recent Form 4 insider transactions for a broad basket of S&P 500
    companies via OpenBB SEC. Filters to open-market purchases and sales only
    (excludes RSU vesting, option exercises, and gifts).

    Returns:
        {
          "transactions": [...],   # recent open-market Form 4s, sorted newest-first
          "summary": {
              "buy_count", "sell_count", "buy_ratio",
              "total_buy_value", "total_sell_value", "net_value",
              "companies_scanned", "days_back", "as_of"
          }
        }
    The summary fields are the DL feature candidates:
      - insider_buy_ratio_30d  = summary["buy_ratio"]
      - insider_net_value_30d  = summary["net_value"]  (millions USD)
    """
    symbols = symbols or _SEC_INSIDER_SYMBOLS
    cutoff  = (datetime.today() - timedelta(days=days_back)).date()
    transactions: list[dict] = []

    try:
        from openbb_sec.models.insider_trading import SecInsiderTradingFetcher
    except ImportError:
        print("[WARN] openbb-sec not installed — skipping insider activity")
        return {"transactions": [], "summary": {}}

    async def _fetch_one(sym: str) -> list:
        try:
            f    = SecInsiderTradingFetcher()
            data = await f.fetch_data({"symbol": sym, "limit": limit_per_symbol}, credentials={})
            return list(data)
        except Exception:
            return []

    async def _fetch_all() -> list:
        batches = await asyncio.gather(*[_fetch_one(s) for s in symbols], return_exceptions=True)
        out = []
        for batch in batches:
            if isinstance(batch, list):
                out.extend(batch)
        return out

    try:
        raw = asyncio.run(_fetch_all())
    except Exception as exc:
        print(f"[WARN] SEC insider fetch failed: {exc}")
        return {"transactions": [], "summary": {}}

    for item in raw:
        try:
            d        = item.model_dump()
            tx_date  = d.get("transaction_date") or d.get("filing_date")
            if tx_date and hasattr(tx_date, "date"):
                tx_date = tx_date.date()
            if tx_date and tx_date < cutoff:
                continue
            tx_type  = str(d.get("transaction_type") or "").lower()
            acq_disp = str(d.get("acquisition_or_disposition") or "")
            if "open market" not in tx_type and "private" not in tx_type:
                continue
            direction = "Buy" if acq_disp == "Acquisition" else "Sell"
            shares    = d.get("securities_transacted") or 0
            price     = d.get("transaction_price")
            value     = (float(shares) * float(price)) if price and shares else None
            transactions.append({
                "symbol":     d.get("symbol", ""),
                "owner":      d.get("owner_name", ""),
                "title":      d.get("owner_title", ""),
                "direction":  direction,
                "shares":     int(shares) if shares else 0,
                "price":      round(float(price), 2) if price else None,
                "value":      round(value) if value else None,
                "date":       str(tx_date or d.get("filing_date", "")),
                "filing_url": d.get("filing_url", ""),
            })
        except Exception:
            continue

    transactions.sort(key=lambda x: x.get("date", ""), reverse=True)

    # ── Summary stats (DL feature candidates) ──────────────────────────────
    buys  = [t for t in transactions if t["direction"] == "Buy"]
    sells = [t for t in transactions if t["direction"] == "Sell"]
    total = len(buys) + len(sells)
    buy_ratio       = round(len(buys) / total, 4) if total > 0 else None
    total_buy_val   = sum(t["value"] for t in buys  if t["value"]) / 1_000_000
    total_sell_val  = sum(t["value"] for t in sells if t["value"]) / 1_000_000
    net_value       = round(total_buy_val - total_sell_val, 2)

    summary = {
        "buy_count":        len(buys),
        "sell_count":       len(sells),
        "buy_ratio":        buy_ratio,
        "total_buy_value":  round(total_buy_val, 2),
        "total_sell_value": round(total_sell_val, 2),
        "net_value":        net_value,          # positive = net buying (bullish signal)
        "companies_scanned": len(symbols),
        "days_back":        days_back,
        "as_of":            _TODAY,
    }
    _ratio_str = f"{buy_ratio:.2f}" if buy_ratio is not None else "N/A"
    print(
        f"[ENRICH] SEC insider: {len(buys)} buys / {len(sells)} sells "
        f"(ratio {_ratio_str}) | net ${net_value:+.1f}M "
        f"across {len(symbols)} companies in last {days_back}d"
    )
    return {"transactions": transactions, "summary": summary}


# ---------------------------------------------------------------------------
# 14. EPM Composite Sentiment Index (computed from all available signals)
# ---------------------------------------------------------------------------
def compute_epm_sentiment_index(
    cnn_fg: dict,
    alt_fg: dict,
    news_sentiment: dict,
    reddit_wsb: dict | None = None,
    own_news: dict | None = None,
    cftc: dict | None = None,
    rsi_spy: dict | None = None,
) -> dict[str, Any]:
    """
    Weighted composite sentiment index (0–100 scale).

    Components and weights:
      CNN Fear & Greed (stock market)  35%  — already 0-100
      News VADER sentiment             25%  — normalized from [-1, +1] to [0, 100]
      Reddit WSB sentiment             20%  — 0-100 score
      Alternative.me Crypto F&G        15%  — already 0-100

    Score labels:
       0-24: Extreme Fear
      25-44: Fear
      45-54: Neutral
      55-74: Greed
      75-100: Extreme Greed
    """
    components: dict[str, dict] = {}

    if cnn_fg.get("score") is not None:
        components["cnn_fear_greed"] = {
            "label":  "CNN Fear & Greed",
            "score":  float(cnn_fg["score"]),
            "weight": 35,
            "detail": cnn_fg.get("rating", ""),
        }

    if news_sentiment.get("mean_score") is not None:
        raw        = float(news_sentiment["mean_score"])
        normalized = round((raw + 1) / 2 * 100, 1)   # -1→0, 0→50, +1→100
        components["news_sentiment"] = {
            "label":  "News Sentiment",
            "score":  normalized,
            "weight": 25,
            "detail": news_sentiment.get("label", ""),
        }

    if reddit_wsb and reddit_wsb.get("score") is not None:
        components["reddit_wsb"] = {
            "label":  "Reddit WSB",
            "score":  float(reddit_wsb["score"]),
            "weight": 20,
            "detail": f"{reddit_wsb.get('posts_scored', 0)} posts scored",
        }

    if own_news and own_news.get("score") is not None:
        components["own_news"] = {
            "label":  "EPM News Feed",
            "score":  float(own_news["score"]),
            "weight": 10,
            "detail": f"{own_news.get('n_articles', 0)} articles",
        }

    if cftc and cftc.get("score") is not None:
        components["cftc_positioning"] = {
            "label":  "CFTC Positioning",
            "score":  float(cftc["score"]),
            "weight": 15,
            "detail": f"Net {cftc.get('trend','')}, {cftc.get('net_position',0):+,}",
        }

    if rsi_spy and rsi_spy.get("score") is not None:
        components["rsi_spy"] = {
            "label":  "SPY RSI(14)",
            "score":  float(rsi_spy["score"]),
            "weight": 15,
            "detail": f"RSI {rsi_spy['score']:.1f} on {rsi_spy.get('date','')}",
        }

    if alt_fg.get("score") is not None:
        components["crypto_fear_greed"] = {
            "label":  "Crypto Fear & Greed",
            "score":  float(alt_fg["score"]),
            "weight": 15,
            "detail": alt_fg.get("rating", ""),
        }

    total_weight = sum(c["weight"] for c in components.values())
    if not components or total_weight == 0:
        return {}

    composite = sum(c["score"] * c["weight"] for c in components.values()) / total_weight
    composite  = round(composite, 1)

    label = (
        "Extreme Fear"  if composite < 25 else
        "Fear"          if composite < 45 else
        "Neutral"       if composite < 55 else
        "Greed"         if composite < 75 else
        "Extreme Greed"
    )

    result = {
        "score":      composite,
        "label":      label,
        "components": components,
        "as_of":      _TODAY,
    }
    print(f"[ENRICH] EPM Sentiment Index: {composite} ({label}) from {len(components)} signals")
    return result


# ---------------------------------------------------------------------------
# 10. Aggregate sentiment summary across all scored headlines
# ---------------------------------------------------------------------------
def aggregate_sentiment(news_by_cat: dict[str, list[dict]]) -> dict[str, Any]:
    """Compute mean/min/max/count sentiment across all categories."""
    all_scores = [
        a["sentiment"]
        for articles in news_by_cat.values()
        for a in articles
        if "sentiment" in a
    ]
    if not all_scores:
        return {}
    avg = round(sum(all_scores) / len(all_scores), 3)
    n_positive = sum(1 for s in all_scores if s > 0.05)
    n_negative = sum(1 for s in all_scores if s < -0.05)
    n_neutral  = len(all_scores) - n_positive - n_negative
    label = (
        "bullish"      if avg > 0.15 else
        "mildly bullish" if avg > 0.05 else
        "bearish"      if avg < -0.15 else
        "mildly bearish" if avg < -0.05 else
        "neutral"
    )
    return {
        "mean_score":  avg,
        "label":       label,
        "n_positive":  n_positive,
        "n_negative":  n_negative,
        "n_neutral":   n_neutral,
        "total":       len(all_scores),
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run_enrichment() -> dict[str, Any]:
    """
    Pull all enrichment sources, merge, save to data/enrichment.json, and return.
    Each source fails gracefully — a failed fetch produces an empty dict/list.
    """
    print("[ENRICH] Starting enrichment data fetch...")

    fear_greed     = fetch_fear_greed()
    alt_fg         = fetch_alternative_me_fg()
    wsb            = fetch_wsb_sentiment(top_n=25)
    reddit_wsb     = fetch_reddit_wsb_sentiment()
    own_news       = fetch_own_news_sentiment()
    cftc           = fetch_cftc_spx_positioning()
    rsi_spy        = fetch_alpha_vantage_rsi(symbol="SPY")
    sec_insider    = fetch_sec_insider_activity()
    fred           = fetch_fred_proxies()
    oecd_cli       = fetch_oecd_cli()
    market_news    = fetch_finnhub_news(max_per_category=20)
    company_news   = fetch_finnhub_company_news(
        symbols=["SPY", "QQQ", "TLT", "GLD", "XLE", "XLF", "XLK"],
        days_back=2,
    )
    earnings       = fetch_earnings_calendar()
    sentiment      = aggregate_sentiment(market_news)
    epm_index      = compute_epm_sentiment_index(
        fear_greed, alt_fg, sentiment,
        reddit_wsb=reddit_wsb, own_news=own_news, cftc=cftc, rsi_spy=rsi_spy,
    )

    payload: dict[str, Any] = {
        "updated":               _TODAY,
        "fear_greed":            fear_greed,
        "alternative_me_fg":     alt_fg,
        "wsb_sentiment":         wsb,
        "reddit_wsb_sentiment":  reddit_wsb,
        "own_news_sentiment":    own_news,
        "cftc_spx_positioning":  cftc,
        "rsi_spy":               rsi_spy,
        "sec_insider_activity":  sec_insider,
        "fred_proxies":          fred,
        "oecd_cli":              oecd_cli,
        "market_news":           market_news,
        "company_news":          company_news,
        "earnings_calendar":     earnings,
        "sentiment_summary":     sentiment,
        "epm_sentiment_index":   epm_index,
    }

    DATA_DIR.mkdir(exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)

    print(f"[ENRICH] Saved -> {OUT_PATH}")
    print(f"  CNN Fear & Greed:  {fear_greed.get('score', 'N/A')} ({fear_greed.get('rating', 'N/A')})")
    print(f"  Alt.me Crypto F&G: {alt_fg.get('score', 'N/A')} ({alt_fg.get('rating', 'N/A')})")
    print(f"  EPM Sentiment Idx: {epm_index.get('score', 'N/A')} ({epm_index.get('label', 'N/A')})")
    print(f"  WSB top ticker:    {wsb[0]['ticker'] if wsb else 'N/A'}")
    print(f"  FRED series:       {sum(1 for v in fred.values() if v.get('value') is not None)}/{len(_FRED_SERIES)}")
    print(f"  OECD CLI:          {len(oecd_cli)} economies")
    print(f"  Finnhub articles:  {sum(len(v) for v in market_news.values())}")
    print(f"  Earnings ahead:    {len(earnings)}")
    print(f"  News sentiment:    {sentiment.get('label', 'N/A')} (mean={sentiment.get('mean_score', 'N/A')})")

    return payload


if __name__ == "__main__":
    run_enrichment()
