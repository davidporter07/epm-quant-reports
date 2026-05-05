from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from news_store import export_news_snapshot, load_news_store, merge_news_store, save_news_store

try:
    from epm_secrets import FINNHUB_KEY, GNEWS_KEY, NEWSAPI_KEY
except Exception:
    FINNHUB_KEY = ""
    GNEWS_KEY = ""
    NEWSAPI_KEY = ""

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
EARNINGS_RELEASES_PATH = DATA_DIR / "earnings_releases.json"
NY_TZ = ZoneInfo("America/New_York")

NEWS_RETENTION_HOURS = int(os.getenv("EPM_EARNINGS_NEWS_RETENTION_HOURS", "168"))
MAX_WAIT_SECONDS = int(os.getenv("EPM_EARNINGS_REFRESH_MAX_WAIT_SECONDS", "1800"))
POLL_SECONDS = int(os.getenv("EPM_EARNINGS_REFRESH_POLL_SECONDS", "60"))
UNKNOWN_RELEASE_TIME_DEFAULT = os.getenv("EPM_EARNINGS_UNKNOWN_RELEASE_TIME", "AMC")

RELEASE_WINDOWS_ET = {
    "BMO": dt_time(8, 0),
    "AMC": dt_time(16, 15),
    "intraday": dt_time(12, 0),
}

TICKER_ALIASES = {
    "GOOGL": ["GOOGL", "GOOG"],
    "GOOG": ["GOOG", "GOOGL"],
}


def ticker_variants(ticker: str) -> List[str]:
    ticker = ticker.upper().strip()
    if ticker in TICKER_ALIASES:
        return TICKER_ALIASES[ticker]
    if "." in ticker:
        return [ticker, ticker.replace(".", "-")]
    if "-" in ticker:
        return [ticker, ticker.replace("-", ".")]
    return [ticker]


def _normalize_release_time(release_time: Optional[str]) -> Optional[str]:
    raw = str(release_time or "").strip().lower()
    if not raw:
        raw = UNKNOWN_RELEASE_TIME_DEFAULT.lower()
    if raw in {"bmo", "before", "before market open", "pre-market", "premarket"}:
        return "BMO"
    if raw in {"amc", "after", "after market close", "post-market", "postmarket"}:
        return "AMC"
    if raw in {"intraday", "during market", "market hours"}:
        return "intraday"
    return None


def release_not_before_utc(earnings_date: Optional[str], release_time: Optional[str]) -> Optional[str]:
    """Return an ISO UTC timestamp if a same-day earnings job should wait."""
    if not earnings_date:
        return None
    try:
        event_date = datetime.fromisoformat(str(earnings_date)).date()
    except Exception:
        return None

    now_et = datetime.now(tz=NY_TZ)
    if event_date != now_et.date():
        return None

    normalized = _normalize_release_time(release_time)
    if not normalized:
        return None

    release_dt_et = datetime.combine(event_date, RELEASE_WINDOWS_ET[normalized], tzinfo=NY_TZ)
    if now_et >= release_dt_et:
        return None
    return release_dt_et.astimezone(timezone.utc).isoformat()


def _load_releases() -> Dict[str, Any]:
    try:
        if EARNINGS_RELEASES_PATH.exists():
            return json.loads(EARNINGS_RELEASES_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_releases(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = EARNINGS_RELEASES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(EARNINGS_RELEASES_PATH)


def load_recent_earnings_release(ticker: str, max_age_days: int = 120) -> Optional[Dict[str, Any]]:
    ticker = ticker.upper().strip()
    releases = _load_releases()
    entry = releases.get(ticker)
    if not entry:
        return None
    try:
        as_of = pd.to_datetime(entry.get("as_of"), utc=True, errors="coerce")
        if pd.isna(as_of):
            return entry
        age_days = (pd.Timestamp.now(tz="UTC") - as_of).total_seconds() / 86400
        if age_days > max_age_days:
            return None
    except Exception:
        pass
    return entry


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _first_present(row: Any, *names: str) -> Any:
    for name in names:
        try:
            value = row.get(name)
            if value is not None and not pd.isna(value):
                return value
        except Exception:
            continue
    return None


def _fetch_yfinance_actuals(ticker: str, earnings_date: str) -> Dict[str, Any]:
    try:
        import yfinance as yf

        target = pd.to_datetime(earnings_date).date()
        for variant in ticker_variants(ticker):
            df = yf.Ticker(variant).earnings_dates
            if df is None or getattr(df, "empty", False):
                continue
            for idx, row in df.iterrows():
                try:
                    if pd.to_datetime(idx).date() != target:
                        continue
                except Exception:
                    continue
                estimate = _coerce_float(_first_present(row, "EPS Estimate", "epsEstimate"))
                actual = _coerce_float(_first_present(row, "Reported EPS", "epsActual"))
                surprise = _coerce_float(_first_present(row, "Surprise(%)", "surprisePct"))
                surprise_pct = None
                if actual is not None and estimate not in (None, 0):
                    surprise_pct = round((actual - estimate) / abs(estimate) * 100, 2)
                return {
                    "source": "yfinance",
                    "eps_estimate": estimate,
                    "eps_actual": actual,
                    "eps_surprise_pct": surprise_pct,
                    "actuals_available": actual is not None,
                }
    except Exception:
        logger.warning("yfinance actuals fetch failed for %s", ticker, exc_info=True)
    return {"source": None, "actuals_available": False}


def _fetch_finnhub_actuals(ticker: str, earnings_date: str) -> Dict[str, Any]:
    if not FINNHUB_KEY:
        return {"source": None, "actuals_available": False}
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"from": earnings_date, "to": earnings_date, "symbol": ticker.upper(), "token": FINNHUB_KEY},
            timeout=12,
        )
        r.raise_for_status()
        for row in (r.json().get("earningsCalendar") or []):
            if str(row.get("symbol", "")).upper() not in ticker_variants(ticker):
                continue
            actual = _coerce_float(row.get("epsActual"))
            estimate = _coerce_float(row.get("epsEstimate"))
            revenue_estimate = _coerce_float(row.get("revenueEstimate"))
            return {
                "source": "finnhub",
                "eps_estimate": estimate,
                "eps_actual": actual,
                "eps_surprise_pct": round((actual - estimate) / abs(estimate) * 100, 2) if actual is not None and estimate not in (None, 0) else None,
                "revenue_estimate": revenue_estimate,
                "release_time": str(row.get("hour", "") or "").upper() or None,
                "actuals_available": actual is not None,
            }
    except Exception:
        logger.warning("Finnhub actuals fetch failed for %s", ticker, exc_info=True)
    return {"source": None, "actuals_available": False}


def _article_row(ticker: str, article: Dict[str, Any]) -> Dict[str, Any]:
    content = article.get("content") if isinstance(article.get("content"), dict) else {}
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    canonical = content.get("canonicalUrl") if isinstance(content.get("canonicalUrl"), dict) else {}
    source = (article.get("source") or {}).get("name") if isinstance(article.get("source"), dict) else article.get("source")
    published = article.get("publishedAt") or content.get("pubDate") or article.get("datetime") or ""
    if isinstance(published, (int, float)):
        try:
            published = datetime.fromtimestamp(published, tz=timezone.utc).isoformat()
        except Exception:
            published = ""
    return {
        "Ticker": ticker.upper(),
        "Headline": article.get("title") or content.get("title") or article.get("headline") or "",
        "Summary": article.get("description") or article.get("summary") or content.get("summary") or content.get("description") or "",
        "Source": source or provider.get("displayName") or article.get("publisher") or "",
        "PublishedAt": published,
        "URL": article.get("url") or canonical.get("url") or content.get("url") or "",
        "ImageURL": article.get("image") or article.get("urlToImage") or article.get("image_url") or "",
        "Provider": article.get("provider") or "unknown",
    }


def _fetch_yfinance_news(ticker: str, limit: int = 12) -> List[Dict[str, Any]]:
    try:
        import yfinance as yf

        rows: List[Dict[str, Any]] = []
        for variant in ticker_variants(ticker):
            raw = yf.Ticker(variant).news or []
            for item in raw[:limit]:
                row = _article_row(ticker, {**item, "provider": "yfinance"})
                if row["Headline"]:
                    rows.append(row)
            if rows:
                break
        return rows
    except Exception:
        logger.warning("yfinance news fetch failed for %s", ticker, exc_info=True)
        return []


def _fetch_newsapi(company_name: str, ticker: str) -> List[Dict[str, Any]]:
    if not NEWSAPI_KEY:
        return []
    query = f'("{company_name}" OR {ticker}) AND (earnings OR revenue OR EPS OR guidance OR outlook)'
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "from": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "sortBy": "publishedAt",
                "apiKey": NEWSAPI_KEY,
                "language": "en",
                "pageSize": 20,
            },
            timeout=15,
        )
        r.raise_for_status()
        return [_article_row(ticker, {**a, "provider": "NewsAPI"}) for a in (r.json().get("articles") or [])]
    except Exception:
        logger.warning("NewsAPI fetch failed for %s", ticker, exc_info=True)
        return []


def _fetch_gnews(company_name: str, ticker: str) -> List[Dict[str, Any]]:
    if not GNEWS_KEY:
        return []
    query = f'"{company_name}" earnings OR revenue OR EPS OR guidance'
    try:
        r = requests.get(
            "https://gnews.io/api/v4/search",
            params={"q": query, "token": GNEWS_KEY, "lang": "en", "max": 20},
            timeout=15,
        )
        r.raise_for_status()
        return [_article_row(ticker, {**a, "provider": "GNews"}) for a in (r.json().get("articles") or [])]
    except Exception:
        logger.warning("GNews fetch failed for %s", ticker, exc_info=True)
        return []


def _fetch_finnhub_news(ticker: str) -> List[Dict[str, Any]]:
    if not FINNHUB_KEY:
        return []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows: List[Dict[str, Any]] = []
    for variant in ticker_variants(ticker):
        try:
            r = requests.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": variant, "from": today, "to": today, "token": FINNHUB_KEY},
                timeout=12,
            )
            r.raise_for_status()
            for a in (r.json() or [])[:12]:
                rows.append(_article_row(ticker, {**a, "provider": "Finnhub"}))
            if rows:
                break
        except Exception:
            logger.warning("Finnhub news fetch failed for %s variant %s", ticker, variant, exc_info=True)
            continue
    return rows


def _dedupe_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for row in rows:
        headline = str(row.get("Headline") or "").strip()
        if not headline:
            continue
        key = (str(row.get("URL") or "").strip() or headline.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    out.sort(key=lambda r: pd.to_datetime(r.get("PublishedAt"), utc=True, errors="coerce"), reverse=True)
    return out


def _earnings_relevant_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    terms = ("earnings", "revenue", "eps", "guidance", "outlook", "profit", "sales")
    selected = []
    for row in rows:
        text = f"{row.get('Headline', '')} {row.get('Summary', '')}".lower()
        if any(term in text for term in terms):
            selected.append(row)
    return selected


def persist_news_rows(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    store = load_news_store(retention_hours=NEWS_RETENTION_HOURS)
    merged = merge_news_store(store, rows, retention_hours=NEWS_RETENTION_HOURS)
    save_news_store(merged)
    export_news_snapshot(merged)


def refresh_same_day_earnings(ticker: str, earnings_date: str, company_name: Optional[str] = None) -> Dict[str, Any]:
    ticker = ticker.upper().strip()
    company_name = company_name or ticker
    if company_name == ticker:
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
            company_name = info.get("shortName") or info.get("longName") or company_name
        except Exception:
            pass

    logger.info("earnings refresh start: ticker=%s date=%s", ticker, earnings_date)
    yf_actuals = _fetch_yfinance_actuals(ticker, earnings_date)
    finnhub_actuals = _fetch_finnhub_actuals(ticker, earnings_date)
    actuals = yf_actuals if yf_actuals.get("actuals_available") else finnhub_actuals

    news_rows = _dedupe_rows(
        _fetch_yfinance_news(ticker)
        + _fetch_newsapi(company_name, ticker)
        + _fetch_gnews(company_name, ticker)
        + _fetch_finnhub_news(ticker)
    )
    relevant_news = _earnings_relevant_rows(news_rows)
    persist_news_rows(news_rows)

    logger.info(
        "earnings refresh done: ticker=%s actuals=%s(%s) news=%d relevant=%d",
        ticker, actuals.get("actuals_available"), actuals.get("source"),
        len(news_rows), len(relevant_news),
    )
    record = {
        "ticker": ticker,
        "earnings_date": earnings_date,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "actuals_available": bool(actuals.get("actuals_available")),
        "news_available": bool(relevant_news),
        "refresh_complete": bool(actuals.get("actuals_available")),
        "news_complete": bool(relevant_news),
        "source": actuals.get("source"),
        "eps_estimate": actuals.get("eps_estimate"),
        "eps_actual": actuals.get("eps_actual"),
        "eps_surprise_pct": actuals.get("eps_surprise_pct"),
        "revenue_estimate": actuals.get("revenue_estimate"),
        "release_time": actuals.get("release_time"),
        "headlines": [row.get("Headline") for row in relevant_news[:10] if row.get("Headline")],
    }

    releases = _load_releases()
    releases[ticker] = record
    _save_releases(releases)
    return record


def wait_for_same_day_earnings_data(
    ticker: str,
    earnings_date: str,
    release_time: Optional[str],
    company_name: Optional[str] = None,
) -> Dict[str, Any]:
    wait_until = release_not_before_utc(earnings_date, release_time)
    if wait_until:
        target = pd.to_datetime(wait_until, utc=True)
        delay = max((target - pd.Timestamp.now(tz="UTC")).total_seconds(), 0)
        if delay > 0:
            time.sleep(delay)

    deadline = time.monotonic() + max(MAX_WAIT_SECONDS, 0)
    last_record: Dict[str, Any] = {}
    while True:
        last_record = refresh_same_day_earnings(ticker, earnings_date, company_name=company_name)
        if last_record.get("refresh_complete") or time.monotonic() >= deadline:
            return last_record
        time.sleep(max(POLL_SECONDS, 5))
