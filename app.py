from __future__ import annotations

import csv
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from functools import lru_cache
from time import time
from pathlib import Path
from typing import Iterable

import pandas as pd

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from snapshot_engine import TickerSnapshotEngine
from services.market_board_service import MarketBoardService
from services.ticker_page_service import TickerPageService
from services.auth_service import (
    AuthError,
    change_username,
    consume_reset_token,
    create_reset_token,
    create_token,
    decode_token,
    get_user_by_email,
    get_user_prefs,
    register_user,
    reset_password,
    set_user_prefs,
    verify_login,
)
from services.email_service import EmailError, send_password_reset_email
from deep_analysis_worker import (cancel_job, enqueue, get_job_status, get_today_cached_job,
                                   invalidate_today_cache, start_worker, stop_worker)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"

# Cookie security: set SECURE_COOKIES=false in local dev (HTTP); always true in production (HTTPS).
_SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "true").lower() not in ("false", "0", "no")

_COOKIE_MAX_AGE_SHORT = 72 * 3600    # 3 days (no remember-me)
_COOKIE_MAX_AGE_LONG  = 720 * 3600   # 30 days (remember-me)


def _set_auth_cookie(response: JSONResponse, token: str, remember_me: bool) -> None:
    """Write the epm_token HttpOnly cookie onto an existing JSONResponse."""
    response.set_cookie(
        key="epm_token",
        value=token,
        httponly=True,
        secure=_SECURE_COOKIES,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE_LONG if remember_me else _COOKIE_MAX_AGE_SHORT,
        path="/",
    )

app = FastAPI(title="EPM Market Intelligence", version="0.7.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith('/static/'):
        response.headers.setdefault('Cache-Control', 'public, max-age=604800, immutable')
    elif path.startswith('/api/'):
        response.headers.setdefault('Cache-Control', 'private, max-age=60')
    return response


engine = TickerSnapshotEngine()
ticker_page_service = TickerPageService(snapshot_engine=engine)
market_board_service = MarketBoardService(page_service=ticker_page_service, snapshot_engine=engine)

SUGGESTION_NAME_MAP: dict[str, str] = {
    "A": "Agilent Technologies, Inc.",
    "AAPL": "Apple Inc.",
    "ABBV": "AbbVie Inc.",
    "ABNB": "Airbnb, Inc.",
    "AMD": "Advanced Micro Devices, Inc.",
    "AMGN": "Amgen Inc.",
    "AMZN": "Amazon.com, Inc.",
    "AVGO": "Broadcom Inc.",
    "AXP": "American Express Company",
    "BA": "The Boeing Company",
    "BAC": "Bank of America Corporation",
    "BRK.B": "Berkshire Hathaway Inc. Class B",
    "CGDV": "Capital Group Dividend Value ETF",
    "CRM": "Salesforce, Inc.",
    "CSCO": "Cisco Systems, Inc.",
    "CVX": "Chevron Corporation",
    "DIA": "SPDR Dow Jones Industrial Average ETF Trust",
    "DIS": "The Walt Disney Company",
    "DIVO": "Amplify CWP Enhanced Dividend Income ETF",
    "EEM": "iShares MSCI Emerging Markets ETF",
    "EFAA": "Invesco MSCI EAFE Income Advantage ETF",
    "EWJ": "iShares MSCI Japan ETF",
    "F": "Ford Motor Company",
    "FXI": "iShares China Large-Cap ETF",
    "GLD": "SPDR Gold Shares",
    "GOOG": "Alphabet Inc. Class C",
    "GOOGL": "Alphabet Inc. Class A",
    "GS": "The Goldman Sachs Group, Inc.",
    "HD": "The Home Depot, Inc.",
    "HYG": "iShares iBoxx $ High Yield Corporate Bond ETF",
    "IEF": "iShares 7-10 Year Treasury Bond ETF",
    "IGV": "iShares Expanded Tech-Software Sector ETF",
    "INTC": "Intel Corporation",
    "IWM": "iShares Russell 2000 ETF",
    "JAAA": "Janus Henderson AAA CLO ETF",
    "JFNIX": "Janus Henderson Global Life Sciences Fund",
    "JMST": "JPMorgan Ultra-Short Municipal ETF",
    "JNJ": "Johnson & Johnson",
    "JPM": "JPMorgan Chase & Co.",
    "KO": "The Coca-Cola Company",
    "LMT": "Lockheed Martin Corporation",
    "LQD": "iShares iBoxx $ Investment Grade Corporate Bond ETF",
    "MA": "Mastercard Incorporated",
    "META": "Meta Platforms, Inc.",
    "MS": "Morgan Stanley",
    "MSFT": "Microsoft Corporation",
    "NFLX": "Netflix, Inc.",
    "NKE": "NIKE, Inc.",
    "NVDA": "NVIDIA Corporation",
    "OMFYX": "Invesco AMT-Free Municipal Income Fund Class Y",
    "ORCL": "Oracle Corporation",
    "PEP": "PepsiCo, Inc.",
    "PG": "The Procter & Gamble Company",
    "PRWCX": "T. Rowe Price Capital Appreciation Fund",
    "QQQ": "Invesco QQQ Trust",
    "RSP": "Invesco S&P 500 Equal Weight ETF",
    "SGIIX": "First Eagle Global Fund Class I",
    "SHLD": "Global X Defense Tech ETF",
    "SHY": "iShares 1-3 Year Treasury Bond ETF",
    "SLV": "iShares Silver Trust",
    "SMH": "VanEck Semiconductor ETF",
    "SOXX": "iShares Semiconductor ETF",
    "SPY": "SPDR S&P 500 ETF Trust",
    "TLT": "iShares 20+ Year Treasury Bond ETF",
    "TMFC": "Motley Fool 100 Index ETF",
    "XNTK": "SPDR NYSE Technology ETF",
    "RLY": "SPDR SSgA Multi-Asset Real Return ETF",
    "TSLA": "Tesla, Inc.",
    "UUP": "Invesco DB US Dollar Index Bullish Fund",
    "UNH": "UnitedHealth Group Incorporated",
    "V": "Visa Inc.",
    "VNQ": "Vanguard Real Estate ETF",
    "VOO": "Vanguard S&P 500 ETF",
    "VTI": "Vanguard Total Stock Market ETF",
    "VUG": "Vanguard Growth ETF",
    "XBI": "SPDR S&P Biotech ETF",
    "XLB": "Materials Select Sector SPDR Fund",
    "XLC": "Communication Services Select Sector SPDR Fund",
    "XLE": "Energy Select Sector SPDR Fund",
    "XLF": "Financial Select Sector SPDR Fund",
    "XLI": "Industrial Select Sector SPDR Fund",
    "XLK": "Technology Select Sector SPDR Fund",
    "XLP": "Consumer Staples Select Sector SPDR Fund",
    "XLRE": "Real Estate Select Sector SPDR Fund",
    "XLU": "Utilities Select Sector SPDR Fund",
    "XLV": "Health Care Select Sector SPDR Fund",
    "XLY": "Consumer Discretionary Select Sector SPDR Fund",
    "ZBRA": "Zebra Technologies Corporation",
    "LHX": "L3Harris Technologies, Inc.",
    "NOC": "Northrop Grumman Corporation",
    "GD": "General Dynamics Corporation",
    "RTX": "RTX Corporation",
    "HON": "Honeywell International Inc.",
    "DE": "Deere & Company",
    "CAT": "Caterpillar Inc.",
}

EXTRA_MAJOR_FUNDS: dict[str, str] = {
    "IVV": "iShares Core S&P 500 ETF",
    "SCHD": "Schwab U.S. Dividend Equity ETF",
    "JEPI": "JPMorgan Equity Premium Income ETF",
    "JEPQ": "JPMorgan Nasdaq Equity Premium Income ETF",
    "VYM": "Vanguard High Dividend Yield ETF",
    "DGRO": "iShares Core Dividend Growth ETF",
    "SCHG": "Schwab U.S. Large-Cap Growth ETF",
    "VTV": "Vanguard Value ETF",
    "VIG": "Vanguard Dividend Appreciation ETF",
    "BND": "Vanguard Total Bond Market ETF",
    "AGG": "iShares Core U.S. Aggregate Bond ETF",
    "BIL": "SPDR Bloomberg 1-3 Month T-Bill ETF",
    "SGOV": "iShares 0-3 Month Treasury Bond ETF",
    "TIP": "iShares TIPS Bond ETF",
    "MUB": "iShares National Muni Bond ETF",
    "EMB": "iShares J.P. Morgan USD Emerging Markets Bond ETF",
    "VXUS": "Vanguard Total International Stock ETF",
    "VEA": "Vanguard FTSE Developed Markets ETF",
    "VWO": "Vanguard FTSE Emerging Markets ETF",
    "IEFA": "iShares Core MSCI EAFE ETF",
    "ACWI": "iShares MSCI ACWI ETF",
    "VT": "Vanguard Total World Stock ETF",
    "USO": "United States Oil Fund",
    "UNG": "United States Natural Gas Fund",
    "DBC": "Invesco DB Commodity Index Tracking Fund",
    "BITO": "ProShares Bitcoin Strategy ETF",
    "IBIT": "iShares Bitcoin Trust ETF",
    "FBTC": "Fidelity Wise Origin Bitcoin Fund",
    "ARKB": "ARK 21Shares Bitcoin ETF",
    "PFF": "iShares Preferred and Income Securities ETF",
    "XME": "SPDR S&P Metals and Mining ETF",
    "KRE": "SPDR S&P Regional Banking ETF",
    "EFA": "iShares MSCI EAFE ETF",
    "FXAIX": "Fidelity 500 Index Fund",
    "VFIAX": "Vanguard 500 Index Fund Admiral Shares",
    "SWPPX": "Schwab S&P 500 Index Fund",
    "VTSAX": "Vanguard Total Stock Market Index Fund Admiral Shares",
    "VBTLX": "Vanguard Total Bond Market Index Fund Admiral Shares",
    "FCNTX": "Fidelity Contrafund",
    "VWENX": "Vanguard Wellington Fund Admiral Shares",
    "VSMIX": "Invesco Small Cap Value Fund",
    "LBIIX": "Thrivent Limited Maturity Bond Fund",
    "SUBFX": "Carillon Reams Unconstrained Bond Fund",
    "WCPBX": "Weitz Core Plus Income Fund",
    "RTX": "RTX Corporation",
    "LHX": "L3Harris Technologies, Inc.",
    "NOC": "Northrop Grumman Corporation",
    "GD": "General Dynamics Corporation",
}
SUGGESTION_NAME_MAP.update(EXTRA_MAJOR_FUNDS)

NAME_ALIASES: dict[str, list[str]] = {
    "GOOG": ["google", "alphabet"],
    "GOOGL": ["google", "alphabet"],
    "BRK.B": ["berkshire", "berkshire hathaway"],
    "META": ["facebook", "meta"],
    "LMT": ["lockheed", "lockheed martin"],
    "BA": ["boeing"],
    "UNH": ["unitedhealth"],
    "JPM": ["jpmorgan", "jp morgan"],
    "GS": ["goldman", "goldman sachs"],
    "MS": ["morgan stanley"],
    "XLE": ["energy sector"],
    "XLF": ["financial sector"],
    "XLK": ["technology sector", "tech sector"],
    "QQQ": ["nasdaq 100"],
    "DIA": ["dow jones", "dow"],
    "SPY": ["s&p 500", "sp500"],
    "VOO": ["vanguard 500"],
    "VTI": ["total stock market"],
    "VXUS": ["total international"],
    "LMT": ["lockheed", "lockheed martin"],
    "ZBRA": ["zebra", "zebra technologies"],
    "RTX": ["raytheon", "rtx"],
    "NOC": ["northrop", "northrop grumman"],
    "GD": ["general dynamics"],
}

POPULAR_SUGGESTIONS = ["AAPL", "MSFT", "AMZN", "NVDA", "META", "GOOG", "AVGO", "QQQ", "SPY", "VOO", "VTI", "LMT"]

TOP100_SP500_BY_WEIGHT_SYMBOLS = [
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "AVGO", "TSLA", "BRK.B",
    "WMT", "LLY", "JPM", "XOM", "V", "JNJ", "MU", "MA", "COST", "ORCL",
    "CVX", "NFLX", "ABBV", "PLTR", "BAC", "PG", "AMD", "KO", "HD", "CAT",
    "CSCO", "GE", "LRCX", "AMAT", "MRK", "RTX", "MS", "PM", "UNH", "GS",
    "WFC", "TMUS", "GEV", "IBM", "LIN", "MCD", "INTC", "VZ", "PEP", "AXP",
    "T", "KLAC", "C", "AMGN", "NEE", "ABT", "CRM", "DIS", "TMO", "TJX",
    "TXN", "GILD", "ISRG", "SCHW", "ANET", "APH", "COP", "PFE", "BA", "UBER",
    "DE", "ADI", "APP", "BLK", "LMT", "HON", "UNP", "QCOM", "ETN", "BKNG",
    "WELL", "DHR", "PANW", "SYK", "SPGI", "LOW", "INTU", "CB", "ACN", "PGR",
    "PLD", "BMY", "NOW", "VRTX", "PH", "COF", "MDT", "HCA", "CME", "MCK",
]

TICKER_TAPE_SYMBOLS = [
    "AAPL",
    "ABBV",
    "ADBE",
    "AMD",
    "AMGN",
    "AMZN",
    "AVGO",
    "BAC",
    "BRK.B",
    "CAT",
    "COST",
    "CRM",
    "CSCO",
    "CVX",
    "DE",
    "DHR",
    "GD",
    "GE",
    "GOOG",
    "GOOGL",
    "HD",
    "HON",
    "INTU",
    "JNJ",
    "JPM",
    "KO",
    "LIN",
    "LLY",
    "LMT",
    "LOW",
    "MA",
    "MCD",
    "META",
    "MSFT",
    "NFLX",
    "NOC",
    "NVDA",
    "ORCL",
    "PEP",
    "PG",
    "QCOM",
    "RTX",
    "TMO",
    "TXN",
    "UNH",
    "V",
    "WMT",
    "XOM",
]


@lru_cache(maxsize=1)
def _forecast_store() -> dict[str, dict]:
    """Load MAG7 forecast data from all model CSVs. Cached per process lifetime (daily restarts)."""
    try:
        summary = pd.read_csv(DATA_DIR / "report_forecast_summary.csv")
        summary = summary.set_index("Ticker")

        arimax_df = pd.read_csv(DATA_DIR / "arimax_forecasts.csv")
        arimax_map = dict(zip(arimax_df["Ticker"], arimax_df["Forecast_Return"]))

        feats = pd.read_parquet(DATA_DIR / "features.parquet")
        feats = feats.set_index("Ticker")

        rankings_df = pd.read_csv(DATA_DIR / "model_rankings.csv")

        result: dict[str, dict] = {}
        for ticker in summary.index:
            row = summary.loc[ticker]
            feat = feats.loc[ticker] if ticker in feats.index else None

            def _safe(v) -> float | None:
                try:
                    f = float(v)
                    return None if pd.isna(f) else f
                except Exception:
                    return None

            def _pct(v) -> float | None:
                """All *Forecast (%)* columns are stored in percent form — always divide by 100."""
                f = _safe(v)
                return None if f is None else round(f / 100.0, 6)

            models: dict[str, dict] = {}
            if feat is not None:
                for col, key in [
                    ("ML Forecast (%)", "ML"),
                    ("Linear Model Forecast (%)", "Linear"),
                    ("DL Forecast (%)", "DL"),
                    ("Institutional Forecast (%)", "Institutional"),
                    ("QuantConnect Forecast (%)", "QuantConnect"),
                    ("FF Forecast (%)", "FamaFrench"),
                ]:
                    val = _pct(feat.get(col))
                    if val is not None:
                        entry: dict = {"forecast": val}
                        if key == "ML":
                            entry["ci_lower"] = _pct(feat.get("ML_CI_Lower"))
                            entry["ci_upper"] = _pct(feat.get("ML_CI_Upper"))
                        elif key == "Linear":
                            entry["ci_lower"] = _pct(feat.get("Linear_CI_Lower"))
                            entry["ci_upper"] = _pct(feat.get("Linear_CI_Upper"))
                        elif key == "DL":
                            entry["ci_lower"] = _pct(feat.get("DL_CI_Lower"))
                            entry["ci_upper"] = _pct(feat.get("DL_CI_Upper"))
                        models[key] = entry

            arimax_val = _safe(arimax_map.get(ticker))
            if arimax_val is not None:
                models["ARIMAX"] = {"forecast": round(arimax_val, 6)}

            ticker_rankings = (
                rankings_df[rankings_df["Ticker"] == ticker][
                    ["Model", "Rank", "Composite_Score", "RMSE", "Directional_Accuracy", "MAE"]
                ]
                .sort_values("Rank")
                .to_dict(orient="records")
            )

            result[ticker] = {
                "consensus": _safe(row.get("Consensus_Forecast")),
                "confidence_label": str(row.get("Confidence_Label") or ""),
                "agreement_ratio": _safe(row.get("Agreement_Ratio")),
                "std_dev": _safe(row.get("Forecast_StdDev")),
                "winning_model": str(row.get("Winning_Model") or ""),
                "winning_forecast": _safe(row.get("Winning_Forecast")),
                "models": models,
                "rankings": ticker_rankings,
            }
        return result
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _sentiment_store() -> dict[str, dict]:
    """Load sentiment data from features.parquet. Cached per process lifetime."""
    try:
        feats = pd.read_parquet(DATA_DIR / "features.parquet")
        result: dict[str, dict] = {}
        for _, row in feats.iterrows():
            ticker = str(row.get("Ticker") or "").strip().upper()
            if not ticker:
                continue
            score = row.get("News_Sentiment_Score")
            trend = row.get("Sentiment_Trend")
            updated = row.get("Sentiment_Updated")
            try:
                score_f = float(score) if score is not None and not pd.isna(score) else None
            except Exception:
                score_f = None
            result[ticker] = {
                "status": "ok" if score_f is not None else "no_data",
                "score": round(score_f, 4) if score_f is not None else None,
                "trend": str(trend) if trend and not (isinstance(trend, float) and pd.isna(trend)) else None,
                "updated": str(updated) if updated is not None else None,
                "label": (
                    "bullish" if score_f is not None and score_f > 0.05
                    else "bearish" if score_f is not None and score_f < -0.05
                    else "neutral" if score_f is not None
                    else "not_available"
                ),
            }
        return result
    except Exception:
        return {}


_POS_WORDS = {
    "beat", "beats", "surge", "surges", "soar", "soars", "record", "growth", "profit", "gain",
    "gains", "rally", "rallies", "strong", "upgrade", "upgrades", "outperform", "buy", "rise",
    "rises", "high", "success", "win", "wins", "positive", "boost", "boosts", "increase",
    "increases", "expand", "expands", "exceeds", "exceeded", "raised", "raise", "top", "tops",
    "bullish", "recovery", "recover", "accelerate",
}
_NEG_WORDS = {
    "miss", "misses", "missed", "cut", "cuts", "fall", "falls", "fell", "drop", "drops",
    "decline", "declines", "declined", "loss", "losses", "weak", "concern", "concerns", "risk",
    "risks", "downgrade", "downgrades", "underperform", "sell", "down", "low", "fail", "fails",
    "failed", "negative", "decrease", "decreases", "shrink", "below", "struggle", "struggles",
    "slump", "plunge", "warning", "layoff", "layoffs", "lawsuit", "bearish", "recession",
    "debt", "bankruptcy", "disappoints", "disappointing", "weaker", "volatile",
}


def _compute_news_sentiment(news_items: list[dict]) -> dict:
    """Keyword-based sentiment from news headlines when FinBERT data is not available."""
    titles = [str(item.get("title") or item.get("summary") or "").lower() for item in news_items if item.get("title") or item.get("summary")]
    if not titles:
        return {"status": "no_data", "score": None, "trend": None, "label": "not_available", "updated": None}
    pos = sum(len({w for w in t.split() if w in _POS_WORDS}) for t in titles)
    neg = sum(len({w for w in t.split() if w in _NEG_WORDS}) for t in titles)
    total = pos + neg
    score = round((pos - neg) / max(total, 1) * 0.4, 4) if total > 0 else 0.0
    label = "bullish" if score > 0.05 else "bearish" if score < -0.05 else "neutral"
    return {"status": "ok", "score": score, "trend": "news-derived", "label": label, "updated": None}


def _enrich_snapshot(snapshot: dict, ticker: str) -> dict:
    """Replace placeholder sentiment and forecast fields with real data."""
    ticker = str(ticker).upper().strip()
    snap = dict(snapshot)

    sentiment = _sentiment_store().get(ticker)
    if sentiment:
        snap["sentiment"] = sentiment
    else:
        # Compute real-time sentiment from whatever news the snapshot already has
        news = snap.get("news") or []
        if news:
            snap["sentiment"] = _compute_news_sentiment(news)
        else:
            # Fetch a small batch of news specifically for sentiment
            try:
                live_news = engine.provider.get_company_news(ticker, limit=8)
                if live_news and any(item.get("title") for item in live_news):
                    snap["sentiment"] = _compute_news_sentiment(live_news)
            except Exception:
                pass

    forecast_entry = _forecast_store().get(ticker)
    if forecast_entry:
        snap["forecast"] = {"supported": True, **forecast_entry}

    return snap


def _page(name: str) -> FileResponse:
    target = STATIC_DIR / name
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Page not found: {name}")
    return FileResponse(target)


def _candidate_pdf_files() -> Iterable[Path]:
    for folder in (BASE_DIR / "archive", BASE_DIR / "epm-quant-reports"):
        if folder.exists():
            yield from folder.rglob("*.pdf")


def _normalize_symbol(raw: str) -> str:
    symbol = str(raw or "").strip().upper().replace(" ", "")
    if re.fullmatch(r"[A-Z]{1,5}-[A-Z]", symbol):
        return symbol.replace("-", ".")
    return symbol


@lru_cache(maxsize=1)
def _sp500_symbol_rows() -> tuple[dict[str, str], ...]:
    rows: list[dict[str, str]] = []
    candidate = DATA_DIR / "sp500_tickers_cache.csv"
    if not candidate.exists():
        return tuple()
    try:
        with candidate.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ticker = _normalize_symbol(row.get("Symbol") or row.get("symbol") or row.get("ticker") or "")
                if not ticker or not _looks_like_core_us_symbol(ticker):
                    continue
                name = str(row.get("Name") or row.get("name") or row.get("Security") or row.get("security") or "").strip()
                rows.append({"ticker": ticker, "name": name or SUGGESTION_NAME_MAP.get(ticker, "")})
    except Exception:
        return tuple()
    dedup: dict[str, dict[str, str]] = {}
    for row in rows:
        dedup[row["ticker"]] = row
    return tuple(dedup[k] for k in sorted(dedup))


def _tape_symbol_list(max_symbols: int = 100) -> list[str]:
    configured = [sym for sym in TOP100_SP500_BY_WEIGHT_SYMBOLS if _looks_like_core_us_symbol(sym)]
    available = {row["ticker"] for row in _sp500_symbol_rows()}
    if available:
        configured = [sym for sym in configured if sym in available]
    if not configured:
        configured = [sym for sym in TICKER_TAPE_SYMBOLS if _looks_like_core_us_symbol(sym)]
    ranked = sorted(dict.fromkeys(configured), key=lambda value: value.replace('.', ''))
    return ranked[:max_symbols]


def _optional_symbol_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    candidates = [DATA_DIR / "sp500_tickers_cache.csv", DATA_DIR / "major_funds.csv"]
    if DATA_DIR.exists():
        for extra in sorted(DATA_DIR.glob('*.csv')):
            if extra not in candidates:
                candidates.append(extra)
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            with candidate.open("r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                headers = {str(h or '').strip().lower() for h in (reader.fieldnames or [])}
                if not ({'symbol', 'ticker'} & headers):
                    continue
                for row in reader:
                    ticker = _normalize_symbol(row.get("Symbol") or row.get("symbol") or row.get("ticker") or "")
                    if not ticker:
                        continue
                    raw_name = str(row.get("Name") or row.get("name") or row.get("Security") or row.get("security") or "").strip()
                    name = raw_name or SUGGESTION_NAME_MAP.get(ticker, "")
                    rows.append({"ticker": ticker, "name": name})
        except Exception:
            continue
    return rows


@lru_cache(maxsize=1)
def _search_universe() -> tuple[dict[str, str], ...]:
    records: dict[str, dict[str, str]] = {}
    for ticker, name in SUGGESTION_NAME_MAP.items():
        records[ticker] = {"ticker": ticker, "name": name, "aliases": " | ".join(NAME_ALIASES.get(ticker, []))}
    for row in _optional_symbol_rows():
        ticker = row["ticker"]
        base = records.get(ticker, {"ticker": ticker, "name": row["name"], "aliases": ""})
        if base.get("name") == ticker and row.get("name"):
            base["name"] = row["name"]
        base["aliases"] = " | ".join(filter(None, [base.get("aliases", ""), *NAME_ALIASES.get(ticker, [])])).strip(" |")
        records[ticker] = base

    for maybe_list in (
        getattr(market_board_service.config, "market_universe", []),
        getattr(market_board_service.config, "market_movers_universe", []),
        getattr(market_board_service.config, "risk_on_candidates", []),
        getattr(market_board_service.config, "risk_off_candidates", []),
        getattr(market_board_service.config, "index_symbols", []),
        getattr(market_board_service.config, "home_market_strip", []),
    ):
        for raw in maybe_list:
            ticker = str(raw).upper().strip()
            if ticker and ticker not in records:
                records[ticker] = {"ticker": ticker, "name": SUGGESTION_NAME_MAP.get(ticker, ticker), "aliases": " | ".join(NAME_ALIASES.get(ticker, []))}

    return tuple(records[k] for k in sorted(records))


def _looks_like_core_us_symbol(query: str) -> bool:
    value = str(query or '').strip().upper()
    return bool(re.fullmatch(r"[A-Z]{1,5}(?:[.-][A-Z])?", value))


def _remote_symbol_allowed(symbol: str) -> bool:
    raw = str(symbol or '').strip().upper()
    if not raw:
        return False
    if raw.startswith('^'):
        return True
    if any(ch in raw for ch in ['/', '=', ':']):
        return False
    # Filter likely option chains / warrants / non-core instruments from suggestion ranking.
    if any(ch.isdigit() for ch in raw) and len(raw) > 6:
        return False
    disallowed_suffixes = ('.BO', '.NS', '.SW', '.SA', '.L', '.TO', '.V', '.PA', '.AX', '.F', '.MX', '.HK')
    if raw.endswith(disallowed_suffixes):
        return False
    return True


def _remote_quote_type_allowed(item: dict[str, str], query: str) -> bool:
    quote_type = str(item.get('quoteType') or item.get('quote_type') or item.get('typeDisp') or '').strip().lower()
    if not quote_type:
        return True
    if any(bad in quote_type for bad in ('option', 'future', 'warrant', 'currency', 'crypt', 'bond')):
        return False
    allowed = ('equity', 'etf', 'mutualfund', 'fund', 'index')
    return any(ok in quote_type for ok in allowed)


def _remote_exchange_allowed(item: dict[str, str]) -> bool:
    exchange = str(item.get('exchange') or item.get('exchDisp') or item.get('exch') or '').strip().lower()
    if not exchange:
        return True
    # Allow major US exchanges only  excludes OTC/Pink Sheets where most penny stocks trade
    allowed_tokens = ('nasdaq', 'nyse', 'nyq', 'nms', 'arca', 'amex', 'bats', 'cboe', 'pcx', 'ase')
    return any(token in exchange for token in allowed_tokens)


@lru_cache(maxsize=2048)
def _symbol_has_live_data_cached(symbol: str) -> bool:
    ticker = str(symbol or '').strip().upper()
    if not ticker:
        return False
    provider = getattr(engine, 'provider', None)
    if provider is not None:
        try:
            quote = provider.get_quote(ticker) or {}
            if any(quote.get(key) not in (None, '', 0) for key in ('last_price', 'price', 'regularMarketPrice', 'close', 'volume', 'regularMarketVolume')):
                return True
        except Exception:
            pass
        try:
            hist = provider.get_history(symbol=ticker, period='1mo')
            if getattr(hist, 'empty', True) is False:
                return True
        except Exception:
            pass
    try:
        import yfinance as yf
        ticker_obj = yf.Ticker(ticker)
        fast = getattr(ticker_obj, 'fast_info', None) or {}
        if fast.get('lastPrice') not in (None, 0) or fast.get('regularMarketPrice') not in (None, 0):
            return True
    except Exception:
        pass
    return False


@lru_cache(maxsize=1024)
def _direct_symbol_candidate_cached(query: str) -> tuple[str, str] | None:
    symbol = str(query or '').strip().upper()
    if not _looks_like_core_us_symbol(symbol):
        return None
    if symbol in SUGGESTION_NAME_MAP:
        return symbol, SUGGESTION_NAME_MAP[symbol]

    provider = getattr(engine, 'provider', None)
    if provider is not None:
        try:
            profile = provider.get_profile(symbol) or {}
            issue_type = str(profile.get('issue_type') or '').strip().lower()
            name = str(profile.get('name') or '').strip()
            if issue_type and any(bad in issue_type for bad in ('option', 'future', 'currency', 'warrant')):
                return None
            if name and name.upper() != symbol:
                return symbol, name
        except Exception:
            pass
        try:
            quote = provider.get_quote(symbol) or {}
            name = str(quote.get('name') or '').strip()
            if name and name.upper() != symbol:
                return symbol, name
        except Exception:
            pass
        try:
            hist = provider.get_history(symbol=symbol, period='1mo')
            if getattr(hist, 'empty', True) is False:
                return symbol, _resolve_remote_symbol_name(symbol) or symbol
        except Exception:
            pass

    resolved = _resolve_remote_symbol_name(symbol)
    if resolved:
        return symbol, resolved
    return None


def _direct_symbol_candidate(query: str) -> dict[str, str] | None:
    result = _direct_symbol_candidate_cached(query)
    if not result:
        return None
    ticker, name = result
    return {'ticker': ticker, 'name': name}


def _suggestion_score(record: dict[str, str], query: str) -> float:
    q = query.strip().lower()
    if not q:
        return 0.0
    ticker = record["ticker"].lower()
    name = record["name"].lower()
    aliases = str(record.get("aliases") or "").lower()
    q_tokens = [token for token in q.replace('.', ' ').replace(',', ' ').split() if token]
    name_tokens = [token for token in name.replace('.', ' ').replace(',', ' ').split() if token]
    alias_parts = [x.strip() for x in aliases.split("|") if x.strip()] if aliases else []

    score = 0.0
    if ticker == q:
        score += 200
    elif ticker.startswith(q):
        score += 140
    elif q in ticker:
        score += 95 - min(ticker.index(q), 20)

    if name == q:
        score += 170
    elif name.startswith(q):
        score += 120
    elif any(token.startswith(q) for token in name_tokens):
        score += 86
    elif q in name:
        score += 60

    if q_tokens and all(any(token.startswith(qt) or qt in token for token in name_tokens) for qt in q_tokens):
        score += 72
    elif q_tokens and any(any(token.startswith(qt) for token in name_tokens) for qt in q_tokens):
        score += 24

    if alias_parts:
        if any(alias == q for alias in alias_parts):
            score += 110
        elif any(alias.startswith(q) for alias in alias_parts):
            score += 72
        elif any(q in alias for alias in alias_parts):
            score += 48
        if q_tokens and all(any(qt in alias for alias in alias_parts) for qt in q_tokens):
            score += 36

    if score > 0 and record["ticker"] in POPULAR_SUGGESTIONS:
        score += 8
    return score


@lru_cache(maxsize=512)
def _remote_yf_suggestions_cached(query: str, limit: int) -> tuple[tuple[str, str], ...]:
    query = query.strip()
    if len(query) < 2:
        return tuple()
    try:
        import yfinance as yf
        search = yf.Search(query=query, max_results=max(limit * 3, 24), news_count=0, enable_fuzzy_query=True)
        quotes = getattr(search, 'quotes', []) or []
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in quotes:
            ticker = _normalize_symbol(item.get('symbol') or '')
            if not ticker or ticker in seen:
                continue
            if not _remote_symbol_allowed(ticker):
                continue
            if not _remote_quote_type_allowed(item, query):
                continue
            if not _remote_exchange_allowed(item):
                continue
            name = str(item.get('shortname') or item.get('longname') or item.get('displayName') or ticker).strip()
            seen.add(ticker)
            out.append((ticker, name))
            if len(out) >= max(limit * 2, 18):
                break
        return tuple(out)
    except Exception:
        return tuple()


def _remote_yf_suggestions(query: str, limit: int) -> list[dict[str, str]]:
    return [{"ticker": ticker, "name": name} for ticker, name in _remote_yf_suggestions_cached(query, limit)]


@lru_cache(maxsize=4096)
def _resolve_remote_symbol_name(ticker: str) -> str:
    symbol = _normalize_symbol(ticker or '')
    if not symbol:
        return ""
    try:
        import yfinance as yf
        search = yf.Search(query=symbol, max_results=6, news_count=0, enable_fuzzy_query=False)
        quotes = getattr(search, "quotes", []) or []
        for item in quotes:
            candidate = str(item.get("symbol") or "").strip().upper()
            if candidate != symbol:
                continue
            name = str(item.get("shortname") or item.get("longname") or item.get("displayName") or "").strip()
            if name and name.upper() != symbol:
                return name
    except Exception:
        pass
    return ""


def _enrich_suggestion_names(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        name = str(row.get("name") or "").strip()
        if not name or name.upper() == ticker:
            name = SUGGESTION_NAME_MAP.get(ticker, "") or _resolve_remote_symbol_name(ticker) or ticker
        out.append({"ticker": ticker, "name": name})
    return out


def _clean_suggestions(rows: list[dict[str, str]], query: str) -> list[dict[str, str]]:
    normalized_query = _normalize_symbol(query or "").replace(".", "")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        ticker = _normalize_symbol(row.get("ticker") or "")
        name = str(row.get("name") or "").strip()
        if not ticker or ticker in seen:
            continue
        upper_name = name.upper()
        if len(ticker) <= 3 and (not name or upper_name == ticker) and ticker not in SUGGESTION_NAME_MAP:
            continue
        if normalized_query:
            comparable_ticker = ticker.replace(".", "")
            comparable_name = re.sub(r"[^A-Z0-9]", "", upper_name)
            if normalized_query not in comparable_ticker and normalized_query not in comparable_name:
                continue
        seen.add(ticker)
        out.append({"ticker": ticker, "name": name or ticker})
    return out


# ---------------------------------------------------------------------------
# Auth request/response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class UserPrefsUpdate(BaseModel):
    featured_tickers: list[str] | None = None
    tape_tickers: list[str] | None = None
    profile_color: str | None = None
    profile_avatar: str | None = None


class ChangeUsernameRequest(BaseModel):
    new_username: str
    password: str


def _get_token(request: Request) -> str | None:
    """Extract bearer token from Authorization header or epm_token cookie."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() or None
    return request.cookies.get("epm_token") or None


def _require_user(request: Request) -> dict:
    """Decode token from the request; raise 401 if missing or invalid."""
    token = _get_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        return decode_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


# ---------------------------------------------------------------------------
# Auth + user prefs routes
# ---------------------------------------------------------------------------

@app.get("/login")
def login_page() -> FileResponse:
    return _page("login.html")


@app.get("/reset-password")
def reset_password_page() -> FileResponse:
    return _page("reset-password.html")


@app.post("/api/auth/login")
async def api_login(body: LoginRequest) -> JSONResponse:
    try:
        user = verify_login(body.username, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    token = create_token(user, remember_me=body.remember_me)
    prefs = get_user_prefs(user["id"])
    response = JSONResponse({
        "ok": True,
        "remember_me": body.remember_me,
        "user": {"id": user["id"], "username": user["username"]},
        "prefs": prefs,
    })
    _set_auth_cookie(response, token, body.remember_me)
    return response


@app.post("/api/auth/register")
async def api_register(body: RegisterRequest) -> JSONResponse:
    try:
        user = register_user(body.username, body.password, body.email)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    token = create_token(user, remember_me=False)
    response = JSONResponse({
        "ok": True,
        "remember_me": False,
        "user": {"id": user["id"], "username": user["username"]},
        "prefs": {"featured_tickers": [], "tape_tickers": []},
    })
    _set_auth_cookie(response, token, remember_me=False)
    return response


@app.post("/api/auth/forgot-password")
async def api_forgot_password(request: Request, body: ForgotPasswordRequest) -> JSONResponse:
    # Always return the same message regardless of whether the email exists 
    # prevents user enumeration attacks.
    generic_ok = JSONResponse({"ok": True, "message": "If that email is registered, a reset link has been sent."})

    user = get_user_by_email(body.email.strip())
    if not user:
        return generic_ok

    try:
        plain_token = create_reset_token(user["id"])
        base_url = str(request.base_url).rstrip("/")
        reset_url = f"{base_url}/reset-password?token={plain_token}"
        send_password_reset_email(user["email"], user["username"], reset_url)
    except (EmailError, Exception):
        # Log but don't expose errors to caller
        pass

    return generic_ok


@app.post("/api/auth/reset-password")
async def api_reset_password(body: ResetPasswordRequest) -> JSONResponse:
    try:
        user_id = consume_reset_token(body.token.strip())
        reset_password(user_id, body.new_password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return JSONResponse({"ok": True, "message": "Password updated successfully."})


@app.get("/api/auth/me")
async def api_me(request: Request) -> JSONResponse:
    """Validate token and return user + prefs. Used by the frontend auth guard."""
    payload = _require_user(request)
    user_id = int(payload["sub"])
    prefs = get_user_prefs(user_id)
    return JSONResponse({
        "ok": True,
        "user": {"id": user_id, "username": payload["username"]},
        "prefs": prefs,
    })


@app.get("/api/user/prefs")
async def api_get_prefs(request: Request) -> JSONResponse:
    payload = _require_user(request)
    prefs = get_user_prefs(int(payload["sub"]))
    return JSONResponse({"ok": True, "prefs": prefs})


@app.put("/api/user/prefs")
async def api_set_prefs(request: Request, body: UserPrefsUpdate) -> JSONResponse:
    payload = _require_user(request)
    prefs = set_user_prefs(
        int(payload["sub"]),
        featured_tickers=body.featured_tickers,
        tape_tickers=body.tape_tickers,
        profile_color=body.profile_color,
        profile_avatar=body.profile_avatar,
    )
    return JSONResponse({"ok": True, "prefs": prefs})


@app.put("/api/user/username")
async def api_change_username(request: Request, body: ChangeUsernameRequest) -> JSONResponse:
    """Change username with password confirmation. Returns a fresh JWT."""
    payload = _require_user(request)
    user_id = int(payload["sub"])
    try:
        updated_user = change_username(user_id, body.new_username, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    # Re-issue token so the embedded username stays current
    remember = payload.get("remember", False)
    new_token = create_token(updated_user, remember_me=remember)
    response = JSONResponse({"ok": True, "user": updated_user})
    _set_auth_cookie(response, new_token, remember_me=remember)
    return response


@app.post("/api/auth/logout")
async def api_logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(key="epm_token", path="/", httponly=True, samesite="lax")
    return response


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.get("/")
def home() -> FileResponse:
    return _page("index.html")


@app.get("/markets")
def markets() -> FileResponse:
    return _page("markets.html")


@app.get("/forecasting")
def forecasting() -> FileResponse:
    return _page("forecasting.html")


@app.get("/portfolios")
def portfolios() -> FileResponse:
    return _page("portfolios.html")


@app.get("/search")
def search_page() -> FileResponse:
    return _page("search.html")


@app.get("/download/current-report")
def download_current_report() -> FileResponse:
    pdfs = [p for p in _candidate_pdf_files() if p.is_file()]
    if not pdfs:
        raise HTTPException(status_code=404, detail="No report PDF found.")
    latest = max(pdfs, key=lambda p: p.stat().st_mtime)
    return FileResponse(latest, filename=latest.name, media_type="application/pdf")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/suggest-tickers")
def suggest_tickers(q: str = Query("", max_length=60), limit: int = Query(15, ge=1, le=20)) -> dict:
    query = _normalize_symbol(q.strip())
    if not query:
        suggestions = _clean_suggestions(_enrich_suggestion_names([{'ticker': t, 'name': SUGGESTION_NAME_MAP.get(t, '')} for t in POPULAR_SUGGESTIONS[:limit]]), query)
        return {'ok': True, 'suggestions': suggestions}

    merged: dict[str, dict[str, str]] = {row['ticker']: dict(row) for row in _search_universe()}

    direct = _direct_symbol_candidate(query)
    if direct is not None:
        ticker = direct['ticker']
        existing = merged.get(ticker, {'ticker': ticker, 'name': direct.get('name') or ticker, 'aliases': ''})
        if (not existing.get('name') or existing.get('name') == ticker) and direct.get('name'):
            existing['name'] = direct['name']
        merged[ticker] = existing

    for row in _remote_yf_suggestions(query, limit=max(limit * 2, 12)):
        ticker = row['ticker']
        existing = merged.get(ticker, {'ticker': ticker, 'name': row.get('name') or ticker, 'aliases': ''})
        if (not existing.get('name') or existing.get('name') == ticker) and row.get('name'):
            existing['name'] = row['name']
        merged[ticker] = existing

    ranked = [(score, record) for record in merged.values() if (score := _suggestion_score(record, query)) > 0]
    ranked.sort(key=lambda item: (-item[0], len(item[1]['ticker']), item[1]['ticker']))
    suggestions = _clean_suggestions(_enrich_suggestion_names([{'ticker': r['ticker'], 'name': r.get('name', '')} for _, r in ranked[:limit]]), query)
    return {'ok': True, 'suggestions': suggestions}


_background_cache_stop = threading.Event()
_background_cache_thread: threading.Thread | None = None
BACKGROUND_WARM_INTERVAL_SECONDS = max(60, int(os.getenv("EPM_WARM_INTERVAL_SECONDS", "300")))


def _warm_ticker_tape_cache(total: int = 100) -> None:
    symbols = _tape_symbol_list(max_symbols=total)
    if not symbols:
        return
    now = time()
    stale = [symbol for symbol in symbols if not (_ticker_tape_item_cache.get(symbol) and _ticker_tape_item_cache[symbol][0] > now)]
    if not stale:
        return
    max_workers = max(1, min(8, len(stale)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_build_ticker_tape_item, symbol): symbol for symbol in stale}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                item = future.result()
            except Exception:
                item = None
            if item is not None:
                _ticker_tape_item_cache[symbol] = (time() + 300, item)


def _warm_core_payloads() -> None:
    try:
        _search_universe()
    except Exception:
        pass
    # Build home/markets/portfolios payloads in parallel, then warm tape + forecast chart separately
    loaders = (market_board_service.get_home_payload, market_board_service.get_markets_payload, market_board_service.get_portfolios_payload)
    with ThreadPoolExecutor(max_workers=len(loaders)) as executor:
        futures = {executor.submit(loader): loader for loader in loaders}
        for future in as_completed(futures):
            loader = futures[future]
            try:
                result = future.result()
                # Persist fresh payloads to disk for instant cold-start serve
                if loader is market_board_service.get_markets_payload:
                    _save_payload_to_disk(_MARKETS_DISK_CACHE, result)
                elif loader is market_board_service.get_home_payload:
                    _save_payload_to_disk(_HOME_DISK_CACHE, result)
            except Exception:
                pass
    try:
        _warm_ticker_tape_cache(total=100)
        _save_tape_cache_to_disk()
    except Exception:
        pass
    try:
        get_forecast_chart_data()
    except Exception:
        pass


def _background_cache_loop() -> None:
    while not _background_cache_stop.is_set():
        _warm_core_payloads()
        if _background_cache_stop.wait(BACKGROUND_WARM_INTERVAL_SECONDS):
            break


def _start_background_cache_warmer() -> None:
    global _background_cache_thread
    if _background_cache_thread is not None and _background_cache_thread.is_alive():
        return
    _background_cache_stop.clear()
    _background_cache_thread = threading.Thread(target=_background_cache_loop, name="epm-cache-warmer", daemon=True)
    _background_cache_thread.start()


def _stop_background_cache_warmer() -> None:
    _background_cache_stop.set()


_ticker_tape_item_cache: dict[str, tuple[float, dict[str, object]]] = {}
_forecast_chart_cache: tuple[float, dict] | None = None

_TAPE_DISK_CACHE    = os.path.join("data", "ticker_tape_cache.json")
_MARKETS_DISK_CACHE = os.path.join("data", "markets_payload_cache.json")
_HOME_DISK_CACHE    = os.path.join("data", "home_payload_cache.json")


def _save_payload_to_disk(path: str, payload: object) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ts": time(), "payload": payload}, f)
    except Exception:
        pass


def _load_payload_from_disk(path: str, max_age_seconds: float = 3600) -> object | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if time() - float(data.get("ts", 0)) > max_age_seconds:
            return None
        return data.get("payload")
    except Exception:
        return None


def _save_tape_cache_to_disk() -> None:
    try:
        now = time()
        payload = {
            sym: {"expires": ts, "item": item}
            for sym, (ts, item) in _ticker_tape_item_cache.items()
            if ts > now
        }
        with open(_TAPE_DISK_CACHE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass


def _load_tape_cache_from_disk() -> None:
    try:
        with open(_TAPE_DISK_CACHE, encoding="utf-8") as f:
            data = json.load(f)
        now = time()
        for sym, entry in data.items():
            # Clamp TTL to 60 s so stale data gets refreshed quickly on first warm cycle
            expires = min(float(entry["expires"]), now + 60)
            _ticker_tape_item_cache[sym] = (expires, entry["item"])
    except Exception:
        pass


def _build_ticker_tape_item(symbol: str) -> dict[str, object] | None:
    provider = getattr(engine, "provider", None)
    quote: dict[str, object] = {}
    profile: dict[str, object] = {}
    try:
        if provider is not None and hasattr(provider, "get_quote"):
            quote = provider.get_quote(symbol) or {}
        if provider is not None and hasattr(provider, "get_profile") and symbol not in SUGGESTION_NAME_MAP:
            profile = provider.get_profile(symbol) or {}
    except Exception:
        quote = quote or {}
    last_price = quote.get("last_price") or quote.get("price") or quote.get("regularMarketPrice") or quote.get("close")
    day_change_pct = quote.get("change_percent") or quote.get("changePct") or quote.get("regularMarketChangePercent")
    prev_close = quote.get("prev_close") or quote.get("previousClose") or quote.get("regularMarketPreviousClose")
    try:
        if day_change_pct is None and last_price not in (None, 0) and prev_close not in (None, 0):
            day_change_pct = (float(last_price) / float(prev_close)) - 1.0
    except Exception:
        pass
    if last_price is None and day_change_pct is None:
        try:
            card = market_board_service.build_symbol_card(symbol, period="1m", include_news=False)
        except Exception:
            return None
        if card.get("error"):
            return None
        last_price = card.get("last_price")
        day_change_pct = card.get("day_change_pct")
        name = card.get("name") or SUGGESTION_NAME_MAP.get(symbol, symbol)
    else:
        name = SUGGESTION_NAME_MAP.get(symbol) or str(profile.get("name") or "").strip() or symbol
    return {
        "ticker": symbol,
        "name": name,
        "last_price": last_price,
        "day_change_pct": day_change_pct,
    }


@app.on_event("startup")
def _startup_deep_worker() -> None:
    start_worker()


@app.on_event("shutdown")
def _shutdown_deep_worker() -> None:
    stop_worker()


@app.on_event("startup")
def _startup_cache_warmer() -> None:
    _load_tape_cache_from_disk()  # instant ticker tape from previous run
    # Pre-inject markets + home payloads into the service's in-memory cache
    # so the first request is served from disk rather than triggering live fetches
    _markets_disk = _load_payload_from_disk(_MARKETS_DISK_CACHE, max_age_seconds=7200)
    if _markets_disk is not None:
        market_board_service._cache_set(("markets_payload",), _markets_disk)
    _home_disk = _load_payload_from_disk(_HOME_DISK_CACHE, max_age_seconds=7200)
    if _home_disk is not None:
        market_board_service._cache_set(("home_payload",), _home_disk)
    _start_background_cache_warmer()


@app.on_event("shutdown")
def _shutdown_cache_warmer() -> None:
    _stop_background_cache_warmer()


@app.get("/api/ticker-tape")
def get_ticker_tape(offset: int = Query(0, ge=0, le=500), limit: int = Query(100, ge=20, le=250), total: int = Query(100, ge=20, le=250)) -> dict:
    symbols = _tape_symbol_list(max_symbols=total)
    selected = symbols[offset: offset + limit]
    if not selected:
        return {"ok": True, "items": [], "total": len(symbols), "offset": offset, "count": 0, "has_more": False}

    now = time()
    items: dict[str, dict[str, object]] = {}
    missing: list[str] = []
    for symbol in selected:
        cached = _ticker_tape_item_cache.get(symbol)
        if cached and cached[0] > now:
            items[symbol] = cached[1]
        else:
            missing.append(symbol)

    if missing:
        max_workers = max(1, min(8, len(missing)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_build_ticker_tape_item, symbol): symbol for symbol in missing}
            try:
                completed = as_completed(futures, timeout=10)
                for future in completed:
                    symbol = futures[future]
                    try:
                        item = future.result()
                    except Exception:
                        item = None
                    if item is not None:
                        items[symbol] = item
                        _ticker_tape_item_cache[symbol] = (now + 300, item)
            except FuturesTimeoutError:
                # Cold cache: return whatever completed within the timeout window
                for future, symbol in futures.items():
                    if future.done():
                        try:
                            item = future.result()
                        except Exception:
                            item = None
                        if item is not None:
                            items[symbol] = item
                            _ticker_tape_item_cache[symbol] = (now + 300, item)

    ordered = [items[symbol] for symbol in selected if symbol in items]
    return {
        "ok": True,
        "items": ordered,
        "total": len(symbols),
        "offset": offset,
        "count": len(ordered),
        "has_more": offset + limit < len(symbols),
    }


def _fallback_snapshot_description(snapshot: dict, ticker: str, name: str) -> str:
    asset_type = str(snapshot.get("asset_type") or "").strip().lower()
    fundamentals = snapshot.get("fundamentals") or {}
    sector = str(fundamentals.get("sector") or "").strip()
    industry = str(fundamentals.get("industry") or "").strip()
    label = name or ticker
    if sector and industry:
        return f"{label} is a U.S.-listed {asset_type or 'security'} in the {sector} sector and {industry} industry."
    if sector:
        return f"{label} is a U.S.-listed {asset_type or 'security'} in the {sector} sector."
    if asset_type:
        return f"{label} is a U.S.-listed {asset_type}."
    return "No description available yet."


def _postprocess_snapshot_metadata(snapshot: dict, ticker: str) -> dict:
    snap = dict(snapshot or {})
    symbol = str(ticker or snap.get('ticker') or '').upper().strip()
    name = str(snap.get('name') or '').strip()
    resolved_remote = _resolve_remote_symbol_name(symbol)
    mapped_name = SUGGESTION_NAME_MAP.get(symbol, '')
    needs_name = not name or name.upper() == symbol

    def _looks_truncated(value: str) -> bool:
        text = str(value or '').strip()
        if len(text) < 18:
            return False
        last_token = text.split()[-1] if text.split() else text
        return last_token.isalpha() and len(last_token) >= 7 and not text.endswith(('Inc.', 'Corp.', 'Corporation', 'Company', 'Fund', 'ETF', 'Trust', 'Ltd.', 'LP', 'PLC', 'Class A', 'Class B'))

    replacement = ''
    if needs_name:
        replacement = mapped_name or resolved_remote
    else:
        candidates = [candidate for candidate in (mapped_name, resolved_remote) if candidate and candidate.upper() != symbol]
        for candidate in candidates:
            if candidate == name:
                replacement = candidate
                break
            if candidate.startswith(name) and len(candidate) > len(name):
                replacement = candidate
                break
            if _looks_truncated(name) and len(candidate) >= len(name):
                replacement = candidate
                break
            if len(candidate) >= len(name) + 6:
                replacement = candidate
                break
    if replacement and replacement.upper() != symbol:
        name = replacement
        snap['name'] = replacement

    desc = str(snap.get('description') or snap.get('short_description') or snap.get('long_description') or '').strip()
    if not desc or desc.lower() in {'n/a', 'none', 'null', 'no description available yet.'}:
        desc = _fallback_snapshot_description(snap, symbol, name or symbol)
        snap['description'] = desc
        snap.setdefault('short_description', desc)
    return snap



@app.get("/api/snapshot")
def get_snapshot(ticker: str = Query(..., min_length=1, max_length=15), include_news: bool = True) -> dict:
    try:
        snapshot = _postprocess_snapshot_metadata(engine.build_snapshot(ticker=ticker, include_news=include_news), ticker)
        snapshot = _enrich_snapshot(snapshot, ticker)
        return {"ok": True, "snapshot": snapshot}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/chart")
def get_chart(ticker: str = Query(..., min_length=1, max_length=15), period: str = Query("1y")) -> dict:
    try:
        return {"ok": True, "chart": engine.build_chart_payload(ticker=ticker, period=period)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/fund-page")
def get_fund_page_payload(ticker: str = Query(..., min_length=1, max_length=15), period: str = Query("ytd"), include_news: bool = True) -> dict:
    try:
        payload = ticker_page_service.build_fund_search_payload(ticker=ticker, period=period, include_news=include_news)
        raw_snapshot = payload.get("raw_snapshot") or {}
        fixed_snapshot = _postprocess_snapshot_metadata(raw_snapshot, ticker)
        payload["raw_snapshot"] = fixed_snapshot
        security = payload.get("security") or {}
        security["name"] = fixed_snapshot.get("name") or security.get("name")
        security["description"] = fixed_snapshot.get("description") or security.get("description")
        security["short_description"] = fixed_snapshot.get("short_description") or security.get("short_description")
        payload["security"] = security
        insight_panel = payload.get("insight_panel") or {}
        insight_panel["about"] = fixed_snapshot.get("short_description") or fixed_snapshot.get("description") or insight_panel.get("about")
        payload["insight_panel"] = insight_panel
        enriched_snapshot = _enrich_snapshot(fixed_snapshot, ticker)
        payload["raw_snapshot"] = enriched_snapshot
        return {"ok": True, "payload": payload}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/home")
def get_home_payload(request: Request, featured: str = Query("", max_length=300)) -> dict:
    try:
        payload = dict(market_board_service.get_home_payload())
        # Override featured cards with user-specified tickers (per-user watchlist)
        custom_tickers = [_normalize_symbol(t) for t in featured.split(",") if t.strip()][:8]
        if custom_tickers:
            payload = dict(payload)
            payload["featured_cards"] = market_board_service.build_symbol_cards(custom_tickers, period="6m")
            payload["universe"] = dict(payload.get("universe") or {})
            payload["universe"]["featured"] = custom_tickers
        return {"ok": True, "payload": payload}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/markets")
def get_markets_payload() -> dict:
    try:
        return {"ok": True, "payload": market_board_service.get_markets_payload()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/portfolios")
def get_portfolios_payload() -> dict:
    try:
        return {"ok": True, "payload": market_board_service.get_portfolios_payload()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# /api/quotes  — lightweight live index strip (55-second server-side cache)
# Single yf.download() call for all tickers; client polls every 60 s.
# ---------------------------------------------------------------------------
_QUOTES_INDEX_SYMBOLS = ["^SPX", "^NDX", "^DJI", "^STOXX50E", "000001.SS", "^N225", "^KS11"]
_QUOTES_INDEX_NAMES = {
    "^SPX":       "S&P 500",
    "^NDX":       "Nasdaq 100",
    "^DJI":       "Dow Jones",
    "^STOXX50E":  "Euro Stoxx 50",
    "000001.SS":  "Shanghai",
    "^N225":      "Nikkei 225",
    "^KS11":      "KOSPI",
}
_quotes_cache: dict = {"data": None, "ts": 0.0}
_QUOTES_TTL = 55  # seconds

@app.get("/api/quotes")
def get_live_quotes() -> dict:
    now = time()
    if _quotes_cache["data"] is not None and (now - _quotes_cache["ts"]) < _QUOTES_TTL:
        return {"ok": True, "payload": _quotes_cache["data"], "cached": True}
    try:
        import yfinance as yf
        symbols = _QUOTES_INDEX_SYMBOLS
        # One HTTP round-trip for all tickers — 2 daily bars gives prev close + today
        hist = yf.download(
            " ".join(symbols), period="2d", interval="1d",
            progress=False, auto_adjust=True, threads=False,
        )
        # Multi-ticker download returns a MultiIndex: ('Close', ticker)
        close = hist.get("Close", hist)
        cards = []
        for sym in symbols:
            try:
                series = (
                    close[sym].dropna() if hasattr(close, "columns") and sym in close.columns
                    else pd.Series()
                )
                if len(series) < 1:
                    continue
                last_price = float(series.iloc[-1])
                prev_close = float(series.iloc[-2]) if len(series) >= 2 else last_price
                day_change_pct = (last_price - prev_close) / prev_close if prev_close else 0.0
                cards.append({
                    "ticker": sym,
                    "name": _QUOTES_INDEX_NAMES.get(sym, sym),
                    "ticker_label": "",
                    "last_price": last_price,
                    "day_change_pct": day_change_pct,
                })
            except Exception:
                pass
        from datetime import datetime as _dt
        result = {"cards": cards, "generated_at": _dt.now().strftime("%-I:%M %p")}
        _quotes_cache["data"] = result
        _quotes_cache["ts"] = now
        return {"ok": True, "payload": result, "cached": False}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


MAG7_NAMES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "NVDA": "NVIDIA",
    "GOOG": "Alphabet",
    "META": "Meta",
    "TSLA": "Tesla",
}


@app.get("/api/forecasts")
def get_forecasts() -> dict:
    """Return MAG7 forecast data: consensus, per-model, confidence, rankings, commentary."""
    store = _forecast_store()
    commentary: dict = {}
    as_of = ""
    try:
        commentary_path = DATA_DIR / "latest_commentary.json"
        if commentary_path.exists():
            with commentary_path.open("r", encoding="utf-8") as fh:
                commentary = json.load(fh)
    except Exception:
        pass
    try:
        summary = pd.read_csv(DATA_DIR / "report_forecast_summary.csv")
        if "Date" in summary.columns and not summary.empty:
            as_of = str(summary["Date"].iloc[0])
    except Exception:
        pass

    tickers_out: dict[str, dict] = {}
    for ticker, data in store.items():
        entry = dict(data)
        entry["name"] = MAG7_NAMES.get(ticker, ticker)
        tickers_out[ticker] = entry

    return {"ok": True, "as_of": as_of, "tickers": tickers_out, "commentary": commentary}


@app.get("/api/commentary")
def get_commentary() -> dict:
    """Return latest daily commentary from the pipeline."""
    try:
        commentary_path = DATA_DIR / "latest_commentary.json"
        if not commentary_path.exists():
            return {"ok": False, "commentary": None}
        with commentary_path.open("r", encoding="utf-8") as fh:
            commentary = json.load(fh)
        return {"ok": True, "commentary": commentary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/enrichment")
def get_enrichment() -> dict:
    """Return enrichment data for the EPM Sentiment gauge and supporting signals."""
    try:
        enrichment_path = DATA_DIR / "enrichment.json"
        if not enrichment_path.exists():
            return {"ok": False}
        with enrichment_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {
            "ok":               True,
            "epm_sentiment":    data.get("epm_sentiment_index", {}),
            "fear_greed":       data.get("fear_greed", {}),
            "alt_fg":           data.get("alternative_me_fg", {}),
            "stocktwits":       data.get("stocktwits_sentiment", {}),
            "oecd_cli":         data.get("oecd_cli", {}),
            "rsi_spy":          data.get("rsi_spy", {}),
            "sec_insider":      data.get("sec_insider_activity", {}),
            "updated":          data.get("updated", ""),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/forecast-chart-data")
def get_forecast_chart_data() -> dict:
    """Price history + fan chart data + 21-day lookback for MAG7."""
    global _forecast_chart_cache
    now = time()
    if _forecast_chart_cache and _forecast_chart_cache[0] > now:
        return _forecast_chart_cache[1]

    import yfinance as yf
    import numpy as np
    from datetime import date, timedelta

    MAG7 = ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOG", "TSLA"]
    today = date.today()
    history_start = today - timedelta(days=90)

    forecasts = _forecast_store()

    #  21-day lookback from prediction_log 
    lookback_by_ticker: dict[str, dict] = {}
    try:
        pred_log = pd.read_parquet(DATA_DIR / "prediction_log.parquet")
        pred_log["RunDate"] = pd.to_datetime(pred_log["RunDate"])
        # Calculate 21 business days ago (skip weekends)
        cutoff = today
        bdays = 0
        while bdays < 21:
            cutoff -= timedelta(days=1)
            if cutoff.weekday() < 5:
                bdays += 1
        eligible = pred_log[pred_log["RunDate"].dt.date <= cutoff]
        if not eligible.empty:
            run_date = eligible["RunDate"].max()
            run_rows = pred_log[pred_log["RunDate"] == run_date]
            for ticker in MAG7:
                t_rows = run_rows[run_rows["Ticker"] == ticker]
                if not t_rows.empty:
                    preds: dict[str, float] = {}
                    for _, row in t_rows.iterrows():
                        model = str(row["Model"])
                        try:
                            val = float(row["ForecastPct"])
                        except Exception:
                            continue
                        # All ForecastPct values are in percent form — always divide by 100
                        preds[model] = round(val / 100.0, 6)
                    lookback_by_ticker[ticker] = {
                        "run_date": str(run_date.date()),
                        "predictions": preds,
                    }
    except Exception:
        pass

    #  Price history (single yfinance call for all tickers)
    history_by_ticker: dict[str, list] = {}
    current_prices: dict[str, float] = {}
    try:
        import concurrent.futures as _cf
        def _yf_download():
            return yf.download(
                MAG7,
                start=str(history_start),
                end=str(today + timedelta(days=1)),
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
            _fut = _ex.submit(_yf_download)
            raw = _fut.result(timeout=20)
        close = raw["Close"] if "Close" in raw.columns else raw
        for ticker in MAG7:
            try:
                series = close[ticker].dropna()
                if not series.empty:
                    history_by_ticker[ticker] = [
                        {"date": str(idx.date()), "price": round(float(p), 4)}
                        for idx, p in series.items()
                    ]
                    current_prices[ticker] = round(float(series.iloc[-1]), 4)
            except Exception:
                pass
    except Exception:
        pass

    #  Build 21 future business dates 
    future_dates: list[str] = []
    d = today
    while len(future_dates) < 21:
        d += timedelta(days=1)
        if d.weekday() < 5:
            future_dates.append(str(d))

    #  Per-ticker chart payload 
    result: dict[str, dict] = {}
    for ticker in MAG7:
        fc = forecasts.get(ticker, {})
        consensus = fc.get("consensus")
        std_dev = float(fc.get("std_dev") or 0)
        models = fc.get("models", {})
        history = history_by_ticker.get(ticker, [])
        current = current_prices.get(ticker)

        # Fan chart projection
        fan: dict | None = None
        if current and consensus is not None:
            steps = len(future_dates)

            def _proj(pct_val: float) -> list[float]:
                target = current * (1 + pct_val)
                return [round(current + (target - current) * i / steps, 4) for i in range(1, steps + 1)]

            fan = {
                "dates": future_dates,
                "consensus": _proj(consensus),
                "band_1_upper": _proj(consensus + std_dev),
                "band_1_lower": _proj(consensus - std_dev),
                "band_2_upper": _proj(consensus + 2 * std_dev),
                "band_2_lower": _proj(consensus - 2 * std_dev),
                "band_3_upper": _proj(consensus + 3 * std_dev),
                "band_3_lower": _proj(consensus - 3 * std_dev),
                "model_paths": {
                    key: _proj(m["forecast"])
                    for key, m in models.items()
                    if m.get("forecast") is not None
                },
            }

        # 21-day lookback: predicted pct vs actual
        lookback = dict(lookback_by_ticker.get(ticker, {}))
        if lookback and current and history:
            run_date_str = lookback.get("run_date", "")
            run_price: float | None = None
            for h in history:
                if h["date"] <= run_date_str:
                    run_price = h["price"]
            if run_price and run_price > 0:
                lookback["actual_pct"] = round((current - run_price) / run_price, 6)
                lookback["start_price"] = round(run_price, 4)
                lookback["end_price"] = round(current, 4)

        result[ticker] = {
            "history": history,
            "current_price": current,
            "fan": fan,
            "lookback_21d": lookback or None,
        }

    payload = {"ok": True, "tickers": result}
    _forecast_chart_cache = (now + 600, payload)
    return payload


# ---------------------------------------------------------------------------
# AI Chat
# ---------------------------------------------------------------------------

_CHAT_OLLAMA_HOST = os.getenv("LOCAL_OLLAMA_URL", "http://192.168.1.145:11434")
_CHAT_OLLAMA_MODEL = os.getenv("LOCAL_OLLAMA_MODEL", "qwen2.5:14b")
_CHAT_TIMEOUT = int(os.getenv("LOCAL_OLLAMA_TIMEOUT", "60"))

_CHAT_SYSTEM_PROMPT = """You are EPM Market Intelligence's AI assistant  a concise, professional market strategist.
You help users understand market data, forecast models, fund metrics, and portfolio strategy.

Rules:
- Only reference data from the market context provided below. Do not invent prices, returns, or events.
- Do not give explicit buy/sell recommendations.
- Be direct and concrete. Avoid generic phrases like "it's important to note" or "market regime."
- Keep answers brief (2-4 sentences unless a detailed breakdown is requested).
- If asked about something not in the context, say so honestly.
- Never use markdown formatting  plain text only.

{context}"""


def _build_chat_context() -> str:
    """Build a rich plain-text context block from all available data files."""
    import csv as _csv
    from datetime import date as _date
    lines: list[str] = []

    # ── Daily commentary ────────────────────────────────────────────────────
    try:
        c = json.loads((DATA_DIR / "latest_commentary.json").read_text(encoding="utf-8"))
        if c.get("report_date"):
            lines.append(f"Report date: {c['report_date']}")
        if c.get("market_outlook_label"):
            label = c["market_outlook_label"]
            rationale = c.get("market_outlook_rationale") or c.get("rationale") or ""
            lines.append(f"Market outlook: {label}" + (f" — {rationale}" if rationale else ""))
        if c.get("fear_greed_score") is not None:
            lines.append(f"Fear/Greed index: {c['fear_greed_score']} ({c.get('fear_greed_rating', '')})")
        bullets = c.get("pre_market_bullets") or c.get("top_bullets") or []
        if bullets:
            lines.append("Key bullets: " + " | ".join(str(b) for b in bullets[:6]))
        for label, key in (
            ("Equities", "equities_commentary"),
            ("Fixed income", "fixed_income_commentary"),
            ("Commodities", "commodities_commentary"),
            ("Currencies", "currencies_commentary"),
            ("Economics", "economics_commentary"),
        ):
            val = c.get(key) or c.get(key.replace("_commentary", ""))
            if val:
                lines.append(f"{label}: {str(val)[:300]}")
        if c.get("tactical_outperforming"):
            lines.append(f"Tactical outperforming: {c['tactical_outperforming']}")
        if c.get("tactical_underperforming"):
            lines.append(f"Tactical underperforming: {c['tactical_underperforming']}")
        if c.get("watch_today"):
            lines.append(f"Watch today: {str(c['watch_today'])[:200]}")
        # portfolio_spotlight omitted — reflects last pipeline run and may not match
        # current holdings after manual portfolio changes. Regenerate commentary to refresh.
    except Exception:
        pass

    # ── Yield curve + macro from arbitrated data ────────────────────────────
    try:
        arb = json.loads((DATA_DIR / "market_data_arbitrated.json").read_text(encoding="utf-8"))
        yc = arb.get("yield_curve", {})
        yc_parts = []
        for tenor in ("2-Year Yield", "10-Year Yield", "30-Year Yield"):
            entry = yc.get(tenor)
            if entry and entry.get("level") is not None:
                yc_parts.append(f"{tenor.replace(' Yield', '')}={entry['level']:.2f}%")
        if yc_parts:
            lines.append("Yield curve: " + ", ".join(yc_parts))
        econ = arb.get("economics", {})
        econ_parts = []
        for indicator in ("CPI (YoY)", "Core CPI (YoY)", "PCE (YoY)", "Unemployment Rate", "GDP Growth (QoQ)"):
            entry = econ.get(indicator)
            if entry and entry.get("value") is not None:
                val = entry["value"]
                formatted = f"{val*100:.1f}%" if abs(val) < 1 else f"{val:.1f}%"
                econ_parts.append(f"{indicator}={formatted}")
        if econ_parts:
            lines.append("Macro indicators: " + ", ".join(econ_parts))
    except Exception:
        pass

    # ── Fund forecasts (ML + DL + Institutional) ────────────────────────────
    try:
        ml, dl, inst = {}, {}, {}
        ml_path = DATA_DIR / "ml_forecasts.csv"
        if ml_path.exists():
            with ml_path.open() as f:
                for row in _csv.DictReader(f):
                    try:
                        ml[row["Ticker"]] = float(row["ML Forecast (%)"])
                    except (KeyError, ValueError):
                        pass
        dl_path = DATA_DIR / "dl_forecasts.csv"
        if dl_path.exists():
            with dl_path.open() as f:
                for row in _csv.DictReader(f):
                    try:
                        dl[row["Ticker"]] = float(row["DL Forecast (%)"])
                    except (KeyError, ValueError):
                        pass
        inst_path = DATA_DIR / "institutional_forecasts.csv"
        if inst_path.exists():
            with inst_path.open() as f:
                for row in _csv.DictReader(f):
                    try:
                        inst[row["Ticker"]] = float(row["Institutional Forecast (%)"])
                    except (KeyError, ValueError):
                        pass
        tickers = sorted(set(ml) | set(dl) | set(inst))
        if tickers:
            forecast_parts = []
            for t in tickers:
                parts = []
                if t in ml:
                    parts.append(f"ML={ml[t]:+.1f}%")
                if t in dl:
                    parts.append(f"DL={dl[t]:+.1f}%")
                if t in inst:
                    parts.append(f"Inst={inst[t]:+.1f}%")
                forecast_parts.append(f"{t}[{', '.join(parts)}]")
            lines.append("Model forecasts: " + "  ".join(forecast_parts))
    except Exception:
        pass

    # ── Upcoming economic calendar (next 14 days) ───────────────────────────
    try:
        cal = json.loads((DATA_DIR / "economic_calendar.json").read_text(encoding="utf-8"))
        today = _date.today()
        cutoff = today.toordinal() + 14
        upcoming = [
            e for e in cal.get("events", [])
            if _date.fromisoformat(e["date"]).toordinal() >= today.toordinal()
            and _date.fromisoformat(e["date"]).toordinal() <= cutoff
        ]
        if upcoming:
            cal_parts = [f"{e['date']} {e['event']} [{e['importance']}]" for e in upcoming[:12]]
            lines.append("Upcoming economic events: " + " | ".join(cal_parts))
    except Exception:
        pass

    if not lines:
        return "No market context currently available."
    return "MARKET CONTEXT:\n" + "\n".join(lines)


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


@app.post("/api/chat")
async def api_chat(body: ChatRequest) -> JSONResponse:
    """AI market assistant  proxies to local Ollama with market context injected."""
    import requests as _req

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    context = _build_chat_context()
    system_content = _CHAT_SYSTEM_PROMPT.format(context=context)

    messages = [{"role": "system", "content": system_content}]
    for h in body.history[-10:]:  # cap history at last 10 turns
        if h.role in ("user", "assistant") and h.content.strip():
            messages.append({"role": h.role, "content": h.content.strip()})
    messages.append({"role": "user", "content": message})

    try:
        resp = _req.post(
            f"{_CHAT_OLLAMA_HOST}/api/chat",
            json={"model": _CHAT_OLLAMA_MODEL, "messages": messages, "stream": False},
            timeout=_CHAT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data.get("message", {}).get("content", "").strip()
        if not reply:
            raise ValueError("Empty response from model.")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI assistant unavailable: {exc}")

    return JSONResponse({"ok": True, "reply": reply})


_DEEP_TICKER_RE = re.compile(r'^[A-Z]{1,10}$')


@app.get("/deep-report")
def deep_report_page() -> FileResponse:
    return _page("deep-report.html")


@app.post("/api/deep/{ticker}")
def deep_analysis_start(ticker: str, request: Request) -> JSONResponse:
    _require_user(request)
    t = ticker.strip().upper()
    if not _DEEP_TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail="Invalid ticker.")

    force_fresh = request.query_params.get("force_fresh") == "1"
    earnings_triggered = False

    if not force_fresh:
        cached = get_today_cached_job(t)
        if cached:
            from datetime import datetime as _dt
            key_facts = cached.get("key_facts") or {}
            next_earnings_date = key_facts.get("next_earnings_date")
            today_str = _dt.utcnow().strftime("%Y-%m-%d")
            if next_earnings_date == today_str:
                from deep_analysis import check_earnings_released
                if check_earnings_released(t, next_earnings_date):
                    invalidate_today_cache(t)
                    force_fresh = True
                    earnings_triggered = True

    job_id = enqueue(t, force_fresh=force_fresh)
    return JSONResponse({"ok": True, "job_id": job_id, "ticker": t,
                         "earnings_triggered": earnings_triggered})


@app.get("/api/deep/{job_id}/status")
def deep_analysis_status(job_id: str, request: Request) -> JSONResponse:
    _require_user(request)
    status = get_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JSONResponse({"ok": True, **status})


@app.delete("/api/deep/{job_id}")
def deep_analysis_cancel(job_id: str, request: Request) -> JSONResponse:
    _require_user(request)
    ok = cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found or already finished.")
    return JSONResponse({"ok": True})


@app.get("/api/deep/{job_id}/agents")
def deep_analysis_agents(job_id: str, request: Request) -> JSONResponse:
    """Return council analyst submissions for a completed job.

    Each persona now has up to 3 posts (R1, R2, R3). The timeline includes
    real round numbers (1, 2, 3). Backwards-compat: old jobs without
    takes_by_round fall back to the flat takes list with round = idx+1.
    """
    _require_user(request)
    status = get_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if status.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Job not completed yet.")

    result = (status.get("result") or {})
    from local_council import PERSONAS
    persona_meta = {p.name: p for p in PERSONAS}

    takes_by_round = result.get("takes_by_round")

    if takes_by_round:
        # New 3-round format
        # Normalise keys: JSON serialises int keys as strings
        tbr = {int(k): v for k, v in takes_by_round.items()}
        # Build per-persona post lists in round order
        posts_by_name: dict = {}
        for rnd in sorted(tbr.keys()):
            for t in tbr[rnd]:
                pname = t.get("name", "")
                body  = (t.get("take") or "").strip()
                if body:
                    posts_by_name.setdefault(pname, []).append(body)

        agents = []
        timeline = []
        for p in PERSONAS:
            meta  = persona_meta.get(p.name)
            bio   = meta.system_prompt.split(". ")[0] + "." if meta else ""
            posts = posts_by_name.get(p.name, [])
            agents.append({
                "name":       p.title,
                "username":   p.name,
                "bio":        bio,
                "persona":    meta.system_prompt if meta else "",
                "post_count": len(posts),
                "posts":      posts,
            })
            for rnd in sorted(tbr.keys()):
                round_takes = {t["name"]: t for t in tbr[rnd]}
                t = round_takes.get(p.name)
                if t:
                    body = (t.get("take") or "").strip()
                    if body:
                        timeline.append({"agent": p.title, "content": body, "round": rnd})
    else:
        # Legacy fallback: flat takes list, round = idx+1
        takes = result.get("takes") or []
        agents = []
        timeline = []
        for idx, t in enumerate(takes):
            pname = t.get("name", "")
            title = t.get("title", pname.replace("_", " ").title() if pname else f"Analyst {idx+1}")
            body  = (t.get("take") or "").strip()
            meta  = persona_meta.get(pname)
            bio   = meta.system_prompt.split(". ")[0] + "." if meta else ""
            agents.append({
                "name":       title,
                "username":   pname,
                "bio":        bio,
                "persona":    meta.system_prompt if meta else "",
                "post_count": 1 if body else 0,
                "posts":      [body] if body else [],
            })
            if body:
                timeline.append({"agent": title, "content": body, "round": idx + 1})

    return JSONResponse({"ok": True, "agents": agents, "timeline": timeline})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
