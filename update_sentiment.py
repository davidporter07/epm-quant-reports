# update_sentiment.py
"""
Fetches recent headlines and produces sentiment signals for MAG7.

- Uses epm_secrets.py for API keys (local-only).
- Saves raw headlines to: data/news_headlines.csv
- Updates sentiment columns in: data/features.parquet

Expected columns added/updated (for MAG7 tickers):
- News_Sentiment_Score
- Sentiment_Trend
- Sentiment_Updated

Notes:
- FinBERT download/load can take time the first run.
- If NewsAPI rate-limits or errors, it falls back to GNews.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Any
import re

import numpy as np
import pandas as pd
import requests

from news_store import export_news_snapshot, load_news_store, merge_news_store, save_news_store

try:
    from epm_secrets import NEWSAPI_KEY, GNEWS_KEY
except Exception:
    NEWSAPI_KEY = ""
    GNEWS_KEY = ""

NEWSAPI_KEY = (NEWSAPI_KEY or "").strip()
GNEWS_KEY = (GNEWS_KEY or "").strip()


# --- Configuration ---
TICKERS: Dict[str, str] = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "NVDA": "NVIDIA",
    "GOOG": "Google",
    "META": "Meta",
    "TSLA": "Tesla",
}

MAG7 = list(TICKERS.keys())

SEARCH_QUERIES: Dict[str, List[str]] = {
    "AAPL": ['("Apple" OR iPhone OR iOS OR Mac OR "Tim Cook")'],
    "MSFT": ['("Microsoft" OR Azure OR Windows OR Xbox OR "Satya Nadella")'],
    "AMZN": ['("Amazon" OR AWS OR "Amazon Web Services" OR "Andy Jassy")'],
    "NVDA": ['(NVIDIA OR Nvidia OR GPU OR GPUs OR "Jensen Huang")'],
    "GOOG": ['("Google" OR Alphabet OR YouTube OR Waymo OR Gemini)'],
    "META": ['("Meta" OR Facebook OR Instagram OR WhatsApp OR Threads OR Zuckerberg)'],
    "TSLA": ['(Tesla OR "Elon Musk" OR EV OR deliveries OR Autopilot)'],
}

LOW_SIGNAL_PATTERNS = [
    r"\bpypi\.org\b",
    r"\bslickdeals?\b",
    r"\bdealnews\b",
    r"\bpromo code\b",
    r"\bcoupon\b",
    r"^\(pr\)",
]

PREFERRED_SOURCES = {
    "reuters", "bloomberg", "cnbc", "marketwatch", "barron's", "financial times",
    "the wall street journal", "wsj", "associated press", "ap news", "seeking alpha"
}

LOW_SIGNAL_SOURCES = {
    "slickdeals.net", "dealnews.com", "benzinga", "cointelegraph", "coingape",
    "devdiscourse", "republic world", "the motley fool australia", "7news australia"
}

DATA_DIR = "data"
FEATURES_PATH = os.path.join(DATA_DIR, "features.parquet")
HEADLINES_PATH = os.path.join(DATA_DIR, "news_headlines.csv")
NEWS_STORE_PATH = os.path.join(DATA_DIR, "news_store.parquet")

TEST_MODE = False
DEBUG_PRINT = False
LOOKBACK_DAYS = 2
MARKET_QUERY = "(\"Federal Reserve\" OR FOMC OR inflation OR CPI OR yields OR tariff OR payrolls OR GDP OR recession)"

mock_titles = {
    "AAPL": ["Apple stock crashes after poor earnings", "Massive layoffs at Apple", "Apple under SEC investigation"],
    "MSFT": ["Microsoft hits record revenue", "Azure sees strong growth", "Positive outlook for Microsoft"],
    "AMZN": ["Amazon reports disappointing holiday sales", "FTC files suit against Amazon", "Layoffs hit logistics arm"],
    "NVDA": ["NVIDIA posts record-breaking earnings", "AI boom lifts NVIDIA", "Analysts upgrade NVIDIA stock"],
    "GOOG": ["Google faces antitrust probe", "YouTube ad revenue drops", "Google misses earnings"],
    "META": ["Meta sees user growth rebound", "Strong ad revenue for Meta", "Meta unveils new AR device"],
    "TSLA": ["Tesla under fire for recalls", "Musk faces shareholder lawsuit", "Slower EV demand hits Tesla"],
}


def _safe_get(url: str, params: dict, timeout: int = 20) -> requests.Response:
    return requests.get(url, params=params, timeout=timeout)


def _normalize_article(a: Dict[str, Any], provider: str) -> Dict[str, Any]:
    return {
        "title": a.get("title", ""),
        "description": a.get("description", ""),
        "content": a.get("content", ""),
        "source": {"name": (a.get("source") or {}).get("name", "")},
        "publishedAt": a.get("publishedAt", ""),
        "url": a.get("url", ""),
        "image": a.get("urlToImage", "") or a.get("image", ""),
        "provider": provider,
    }


def _dedupe_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for a in articles:
        key = (str(a.get("url", "")).strip() or str(a.get("title", "")).strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def _article_published_at(article: Dict[str, Any]) -> pd.Timestamp:
    try:
        ts = pd.to_datetime(article.get("publishedAt", ""), utc=True, errors="coerce")
        if pd.isna(ts):
            return pd.NaT
        return ts
    except Exception:
        return pd.NaT


def _sort_articles_newest_first(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        articles,
        key=lambda a: _article_published_at(a) if pd.notna(_article_published_at(a)) else pd.Timestamp.min.tz_localize("UTC"),
        reverse=True,
    )


def _newest_story_age_hours(articles: List[Dict[str, Any]]) -> float | None:
    if not articles:
        return None
    timestamps = [ts for ts in (_article_published_at(a) for a in articles) if pd.notna(ts)]
    if not timestamps:
        return None
    newest = max(timestamps)
    return max((datetime.now(timezone.utc) - newest.to_pydatetime()).total_seconds() / 3600.0, 0.0)


def _article_text(article: Dict[str, Any]) -> str:
    return " ".join(str(article.get(k, "")) for k in ("title", "description", "content")).lower()


def _contains_term(text: str, term: str) -> bool:
    txt = str(text or "").lower()
    token = str(term or "").lower().strip()
    if not token:
        return False
    if " " in token or any(ch in token for ch in "/&.-"):
        return token in txt
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", txt) is not None


def _contains_any(text: str, terms: List[str]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def _source_name(article: Dict[str, Any]) -> str:
    return str((article.get("source") or {}).get("name", "")).strip().lower()


def _source_rank(article: Dict[str, Any]) -> int:
    src = _source_name(article)
    if src in PREFERRED_SOURCES:
        return 3
    if src in LOW_SIGNAL_SOURCES:
        return 0
    return 1


def _article_signal_score(ticker: str, article: Dict[str, Any]) -> int:
    text = _article_text(article)
    score = 0
    if _contains_any(text, ["earnings", "guidance", "outlook", "revenue", "margin"]):
        score += 3
    if _contains_any(text, ["ai", "cloud", "chip", "data center", "copilot", "gemini", "aws"]):
        score += 2
    if _contains_any(text, ["antitrust", "doj", "ftc", "lawsuit", "regulation", "recall", "deliveries", "production", "demand"]):
        score += 2
    if ticker == "MARKET" and _contains_any(text, ["federal reserve", "fed", "rates", "yield", "inflation", "cpi", "payrolls", "gdp", "tariff", "recession", "treasury", "credit", "oil", "dollar"]):
        score += 3
    return score


def _is_relevant_company_article(ticker: str, article: Dict[str, Any]) -> bool:
    text = _article_text(article)
    source = _source_name(article)
    title = str(article.get("title", "")).strip()

    if not title:
        return False
    if any(re.search(pattern, text) for pattern in LOW_SIGNAL_PATTERNS):
        return False

    if ticker == "AAPL":
        if _contains_any(text, ["big apple", "nyc", "new yorkers"]):
            return False
        return _contains_any(text, ["apple", "iphone", "ios", "mac", "ipad", "tim cook", "airpods", "watch"])

    if ticker == "AMZN":
        if source in {"amazon.com", "slickdeals.net", "dealnews.com"}:
            return False
        if _contains_any(text, ["deal", "deals", "coupon", "free shipping", "sale", "prime day", "shop now", "buy now"]):
            return False
        return _contains_any(text, ["amazon", "aws", "amazon web services", "andy jassy", "advertising", "cloud", "antitrust", "ftc", "doj", "fulfillment", "logistics"])

    if ticker == "GOOG":
        if _contains_any(text, ["google-auth", "google-cloud-", "package", "library", "pypi"]):
            return False
        return _contains_any(text, ["google", "alphabet", "youtube", "waymo", "gemini", "sundar pichai"])

    if ticker == "META":
        if _contains_any(text, ["meta-ads-mcp", "package", "library", "pypi"]):
            return False
        return _contains_any(text, ["meta", "facebook", "instagram", "whatsapp", "threads", "zuckerberg"])

    if ticker == "MSFT":
        return _contains_any(text, ["microsoft", "azure", "windows", "xbox", "satya nadella"])
    if ticker == "NVDA":
        return _contains_any(text, ["nvidia", "gpu", "gpus", "jensen huang", "chip", "data center"])
    if ticker == "TSLA":
        return _contains_any(text, ["tesla", "elon musk", "ev", "deliveries", "autopilot", "gigafactory", "recall"])

    return True


def _filter_company_articles(ticker: str, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered = [a for a in articles if _is_relevant_company_article(ticker, a)]
    pool = filtered if filtered else articles
    pool = sorted(
        pool,
        key=lambda a: (
            _source_rank(a),
            _article_signal_score(ticker, a),
            _article_published_at(a) if pd.notna(_article_published_at(a)) else pd.Timestamp.min.tz_localize("UTC"),
        ),
        reverse=True,
    )
    seen_sources = {}
    curated = []
    for a in pool:
        src = _source_name(a) or "unknown"
        seen_sources[src] = seen_sources.get(src, 0) + 1
        if seen_sources[src] > 3:
            continue
        curated.append(a)
    return curated


def fetch_headlines_newsapi(query_text: str) -> List[Dict[str, Any]]:
    if not NEWSAPI_KEY:
        return []
    base_url = "https://newsapi.org/v2/everything"
    date_from = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    params = {"q": query_text, "from": date_from, "sortBy": "publishedAt", "apiKey": NEWSAPI_KEY, "language": "en", "pageSize": 20}
    for attempt in range(3):
        try:
            r = _safe_get(base_url, params=params)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            articles = r.json().get("articles", []) or []
            return _dedupe_articles([_normalize_article(a, "NewsAPI") for a in articles])
        except Exception:
            if attempt == 2:
                return []
            time.sleep(1.0)
    return []


def fetch_headlines_gnews(query_text: str) -> List[Dict[str, Any]]:
    if not GNEWS_KEY:
        return []
    url = "https://gnews.io/api/v4/search"
    params = {"q": query_text, "token": GNEWS_KEY, "lang": "en", "max": 20}
    try:
        r = _safe_get(url, params=params)
        r.raise_for_status()
        articles = r.json().get("articles", []) or []
        return _dedupe_articles([_normalize_article(a, "GNews") for a in articles])
    except Exception:
        return []


def fetch_headlines(ticker: str, company_name: str) -> List[Dict[str, Any]]:
    queries = SEARCH_QUERIES.get(ticker, [f'"{company_name}"']) + [f'"{company_name}"']
    combined: List[Dict[str, Any]] = []
    for query in queries:
        combined.extend(fetch_headlines_newsapi(query))
        if len(combined) >= 12:
            break
    if not combined:
        for query in queries:
            combined.extend(fetch_headlines_gnews(query))
            if len(combined) >= 12:
                break
    combined = _dedupe_articles(combined)
    filtered = _filter_company_articles(ticker, combined)
    filtered = _sort_articles_newest_first(filtered)

    newest_age = _newest_story_age_hours(filtered)
    needs_freshness_rescue = (len(filtered) < 3) or (newest_age is not None and newest_age > 12.0)
    if needs_freshness_rescue:
        freshness_queries = [
            f'{company_name} earnings OR guidance OR outlook',
            f'{company_name} regulation OR antitrust OR lawsuit',
            f'{company_name} AI OR cloud OR data center',
            f'{ticker} stock earnings',
        ]
        rescue: List[Dict[str, Any]] = []
        for query in freshness_queries:
            rescue.extend(fetch_headlines_newsapi(query))
            rescue.extend(fetch_headlines_gnews(query))
            if len(rescue) >= 12:
                break
        combined = _dedupe_articles(filtered + rescue)
        filtered = _filter_company_articles(ticker, combined)
        filtered = _sort_articles_newest_first(filtered)
    return filtered[:12]


def _is_relevant_market_article(article: Dict[str, Any]) -> bool:
    text = _article_text(article)
    source = _source_name(article)
    if source in LOW_SIGNAL_SOURCES:
        return False
    if any(re.search(pattern, text) for pattern in LOW_SIGNAL_PATTERNS):
        return False
    if not _contains_any(text, ["federal reserve", "fed", "rates", "yield", "inflation", "cpi", "payrolls", "gdp", "tariff", "recession", "treasury", "credit", "oil", "dollar"]):
        return False
    return _article_signal_score("MARKET", article) >= 3


def fetch_market_headlines() -> List[Dict[str, Any]]:
    queries = [
        '("Federal Reserve" OR FOMC OR inflation OR CPI OR yields OR payrolls OR GDP OR recession)',
        '(treasury yields OR bond market OR credit spreads OR dollar index OR DXY)',
        '(oil prices OR crude oil OR tariff OR tariffs OR consumer sentiment OR retail sales)',
    ]
    combined: List[Dict[str, Any]] = []
    for query in queries:
        combined.extend(fetch_headlines_newsapi(query))
        combined.extend(fetch_headlines_gnews(query))
        if len(combined) >= 24:
            break
    combined = _dedupe_articles(combined)
    filtered = [a for a in combined if _is_relevant_market_article(a)]
    pool = filtered if filtered else combined
    pool = sorted(
        pool,
        key=lambda a: (
            _source_rank(a),
            _article_signal_score("MARKET", a),
            _article_published_at(a) if pd.notna(_article_published_at(a)) else pd.Timestamp.min.tz_localize("UTC"),
        ),
        reverse=True,
    )
    return pool[:12]


def load_finbert_pipeline():
    try:
        from transformers import pipeline
    except Exception as e:
        print(f" transformers not available ({e}). Sentiment will be NaN.")
        return None
    try:
        print(" Loading FinBERT model (ProsusAI/finbert)...")
        device = 0
        try:
            import torch
            if not torch.cuda.is_available():
                device = -1
        except Exception:
            device = -1
        return pipeline("sentiment-analysis", model="ProsusAI/finbert", tokenizer="ProsusAI/finbert", device=device)
    except Exception as e:
        print(f" Failed to load FinBERT ({e}). Sentiment will be NaN.")
        return None


def analyze_sentiment(sentiment_model, headlines: List[Dict[str, Any]], ticker: str) -> Tuple[float, str]:
    titles = mock_titles.get(ticker, []) if TEST_MODE else [h.get("title", "") for h in headlines if h.get("title")]
    titles = [t.strip() for t in titles if t and t.strip()]
    if not titles or sentiment_model is None:
        return (np.nan, "")
    try:
        results = sentiment_model(titles)
    except Exception:
        return (np.nan, "")
    signed = []
    for res in results:
        label = str(res.get("label", "")).lower()
        score = float(res.get("score", 0.0))
        if label == "positive":
            signed.append(+score)
        elif label == "negative":
            signed.append(-score)
        else:
            signed.append(0.0)
    if not signed:
        return (np.nan, "")
    avg = float(np.mean(signed))
    trend = "" if avg > 0.05 else "" if avg < -0.05 else "flat"
    if DEBUG_PRINT:
        print(f"\n FinBERT classifications for {ticker}:")
        for title, res in zip(titles, results):
            print(f"   {res.get('label')} ({float(res.get('score', 0)):.3f})  {title}")
    return (round(avg, 4), trend)


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_features_parquet() -> pd.DataFrame:
    if os.path.exists(FEATURES_PATH):
        try:
            return pd.read_parquet(FEATURES_PATH)
        except Exception as e:
            print(f" Could not read {FEATURES_PATH}: {e}")
    return pd.DataFrame()


def upsert_sentiment_into_features(features_df: pd.DataFrame, sent_df: pd.DataFrame) -> pd.DataFrame:
    if features_df is None or features_df.empty:
        return sent_df.reset_index()
    df = features_df.copy()
    if "Ticker" not in df.columns:
        df = df.reset_index()
    df["Ticker"] = df["Ticker"].astype(str).str.strip()
    sent_df = sent_df.copy()
    sent_df.index = sent_df.index.astype(str).str.strip()
    df = df.set_index("Ticker", drop=False)
    cols_to_update = ["News_Sentiment_Score", "Sentiment_Trend", "Sentiment_Updated"]
    for c in cols_to_update:
        if c not in df.columns:
            df[c] = np.nan
    if "News_Sentiment_Score" in df.columns:
        df["News_Sentiment_Score"] = pd.to_numeric(df["News_Sentiment_Score"], errors="coerce")
    if "Sentiment_Trend" in df.columns:
        df["Sentiment_Trend"] = df["Sentiment_Trend"].astype(object)
    if "Sentiment_Updated" in df.columns:
        df["Sentiment_Updated"] = df["Sentiment_Updated"].astype(object)
    for tkr in sent_df.index:
        if tkr in df.index:
            for c in cols_to_update:
                df.loc[tkr, c] = sent_df.loc[tkr, c]
        else:
            new_row = {col: np.nan for col in df.columns}
            new_row["Ticker"] = tkr
            for c in cols_to_update:
                new_row[c] = sent_df.loc[tkr, c]
            df.loc[tkr] = new_row
    df = df.reset_index(drop=True)
    df = df.loc[:, ~df.columns.duplicated()]
    return df


def main():
    ensure_data_dir()
    sentiment_model = load_finbert_pipeline()
    rows = []
    headline_log = []
    for ticker, name in TICKERS.items():
        print(f"\n Analyzing sentiment for {ticker} ({name})...")
        articles = [] if TEST_MODE else fetch_headlines(ticker, name)
        print(f" {ticker} fetched {len(articles)} headlines")
        avg_score, trend = analyze_sentiment(sentiment_model, articles, ticker)
        print(f"{ticker}: Sentiment score = {avg_score}, trend = {trend}")
        rows.append({"Ticker": ticker, "News_Sentiment_Score": avg_score, "Sentiment_Trend": trend, "Sentiment_Updated": pd.Timestamp.now(tz="UTC")})
        for a in articles:
            headline_log.append({
                "Ticker": ticker,
                "Headline": a.get("title", ""),
                "Summary": a.get("description", "") or a.get("content", ""),
                "Source": (a.get("source") or {}).get("name", ""),
                "PublishedAt": a.get("publishedAt", ""),
                "URL": a.get("url", ""),
                "ImageURL": a.get("image", ""),
                "Provider": a.get("provider", ""),
            })
    market_articles = [] if TEST_MODE else fetch_market_headlines()
    for a in market_articles:
        headline_log.append({
            "Ticker": "MARKET",
            "Headline": a.get("title", ""),
            "Summary": a.get("description", "") or a.get("content", ""),
            "Source": (a.get("source") or {}).get("name", ""),
            "PublishedAt": a.get("publishedAt", ""),
            "URL": a.get("url", ""),
            "ImageURL": a.get("image", ""),
            "Provider": a.get("provider", ""),
        })
    news_store = load_news_store(NEWS_STORE_PATH, retention_hours=LOOKBACK_DAYS * 24)
    news_store = merge_news_store(news_store, headline_log, retention_hours=LOOKBACK_DAYS * 24)
    save_news_store(news_store, NEWS_STORE_PATH)
    export_news_snapshot(news_store, HEADLINES_PATH)
    print(f" Updated rolling news store: {NEWS_STORE_PATH}")
    print(f" Exported curated news snapshot: {HEADLINES_PATH}")
    sent_df = pd.DataFrame(rows).set_index("Ticker")
    features_all = load_features_parquet()
    updated = upsert_sentiment_into_features(features_all, sent_df)
    try:
        updated.to_parquet(FEATURES_PATH, index=False)
        print(" Sentiment signals updated in features.parquet")
        print(f" features.parquet now has shape: {updated.shape}")
    except Exception as e:
        print(f" Failed to write {FEATURES_PATH}: {e}")


if __name__ == "__main__":
    main()
