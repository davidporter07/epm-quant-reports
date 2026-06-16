from __future__ import annotations

import csv
import hmac
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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from snapshot_engine import TickerSnapshotEngine
from services.market_board_service import MarketBoardService
from services.ticker_page_service import TickerPageService
from services.auth_service import (
    AuthError,
    EMAIL_PURPOSE_CONFIRM,
    EMAIL_PURPOSE_UNSUB,
    change_username,
    consume_reset_token,
    create_reset_token,
    create_token,
    decode_token,
    get_confirmed_subscribers,
    get_email_subscription,
    get_user_by_email,
    get_user_by_id,
    get_user_prefs,
    make_email_token,
    register_user,
    reset_password,
    set_email_confirmed,
    set_email_opt_in,
    set_user_prefs,
    verify_email_token,
    verify_login,
)
from services.email_service import (
    EmailError,
    send_password_reset_email,
    send_subscription_confirmation_email,
)
from deep_analysis_worker import (cancel_job, enqueue, get_job_status, get_today_cached_job,
                                   invalidate_today_cache, start_worker, stop_worker, worker_status)
from services.watchdog_service import start_watchdog, stop_watchdog, watchdog_status
from services.validators import (
    DEEP_TICKER_RE,
    env_flag,
    normalize_ticker,
    read_json_artifact,
)
from services import runtime_config as _rc

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"

# Cookie security: set SECURE_COOKIES=false in local dev (HTTP); always true in production (HTTPS).
_SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "true").lower() not in ("false", "0", "no")

# Public site origin used to build email links (confirm/unsubscribe). Falls back to
# the request's own base_url when unset. MUST be the public domain in production so
# links in emails point at epm-market-intelligence.com, not an internal host.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")

# Shared secret guarding the internal subscriber-list endpoint the laptop pipeline
# calls over Tailscale. If unset, the endpoint is disabled (returns 403).
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "").strip()


def _public_base_url(request: Request | None = None) -> str:
    """Origin for links embedded in emails. Prefers PUBLIC_BASE_URL; falls back to
    the request's base_url."""
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    if request is not None:
        return str(request.base_url).rstrip("/")
    return ""

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

# CORS: an explicit allowlist is REQUIRED when allow_credentials=True — a wildcard
# origin with credentials is invalid per the Fetch spec and unsafe for cookie auth.
# Configure via ALLOWED_ORIGINS (comma-separated) in .env; falls back to the known
# production + local-dev origins.
_DEFAULT_ALLOWED_ORIGINS = [
    "https://epm-market-intelligence.com",
    "https://www.epm-market-intelligence.com",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
_allowed_origins = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if o.strip()
] or _DEFAULT_ALLOWED_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def add_security_and_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    # Cache-Control
    if path.startswith('/static/'):
        response.headers.setdefault('Cache-Control', 'public, max-age=604800, immutable')
    elif path.startswith(('/api/auth/', '/api/user/', '/api/chat')):
        response.headers['Cache-Control'] = 'no-store'
    elif path.startswith('/api/'):
        response.headers.setdefault('Cache-Control', 'private, max-age=60')
    # Security headers (applied to every response)
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.plot.ly https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    # HSTS only over HTTPS (nginx handles TLS termination so we always set it)
    response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return response


# ── Simple in-memory sliding-window rate limiter (no external deps) ──────────
import time as _time
from collections import defaultdict, deque as _deque

_RL_STORE: dict[str, _deque] = defaultdict(_deque)


def _rate_limited(key: str, max_requests: int, window_s: int) -> bool:
    """Return True if key has exceeded max_requests within window_s seconds."""
    now = _time.monotonic()
    dq = _RL_STORE[key]
    while dq and dq[0] < now - window_s:
        dq.popleft()
    if len(dq) >= max_requests:
        return True
    dq.append(now)
    return False


def _client_ip(request: Request) -> str:
    """Return the real client IP in a Cloudflare + nginx + uvicorn stack.

    Precedence: CF-Connecting-IP (set by Cloudflare, one authoritative IP) →
    first hop of X-Forwarded-For (set by nginx) → request.client.host fallback.

    Spoofable only by direct-origin callers that bypass Cloudflare — acceptable
    for rate-limiting (worst case = key rotation). NEVER use for auth or audit.
    """
    cf = request.headers.get("CF-Connecting-IP", "").strip()
    if cf:
        return cf
    xff = request.headers.get("X-Forwarded-For", "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "anon"


# ── New rate-limit buckets (warn-only until RATE_LIMIT_ENFORCE=1) ─────────────
# RATE_LIMIT_ENFORCE=0 (default): over-limit requests proceed + log
#   [rate_limit][WARN] would-429 bucket=… path=… ip=…
# RATE_LIMIT_ENFORCE=1: returns 429 + Retry-After.
# Existing proven limits (forgot-password, reset-password, chat) are
# unconditionally enforced regardless of this flag.
# Single uvicorn worker in prod → in-memory store is correct. If --workers is
# ever added, these limits silently become per-worker; add Redis then.
# Canonical parsing (validators.env_flag, decision D1): truthy {1,true,yes,on},
# falsey {0,false,no,off}; garbage/empty -> default. Edge change from the old
# `not in ("","0","false")` idiom: "no"/"off" now DISABLE (were silently truthy).
_RATE_LIMIT_ENFORCE: bool = env_flag("RATE_LIMIT_ENFORCE", default=False)

# (frozenset[methods], frozenset[exact_paths], max_requests, window_s, bucket_name)
_RL_BUCKETS: list[tuple[frozenset, frozenset, int, int, str]] = [
    (frozenset({"POST"}),       frozenset({"/api/auth/login"}),                                          15,  300, "auth_login"),
    (frozenset({"POST"}),       frozenset({"/api/auth/register"}),                                        5, 3600, "auth_register"),
    (frozenset({"GET", "POST"}),frozenset({"/email/confirm", "/unsubscribe"}),                            30,  600, "email_links"),
    (frozenset({"GET"}),        frozenset({"/api/ticker-tape", "/api/quotes", "/api/home",
                                           "/api/markets", "/api/portfolios", "/api/forecasts",
                                           "/api/commentary", "/api/enrichment",
                                           "/api/suggest-tickers"}),                                    120,   60, "data_cheap"),
    (frozenset({"GET"}),        frozenset({"/api/snapshot", "/api/chart",
                                           "/api/fund-page", "/api/forecast-chart-data"}),               30,   60, "data_expensive"),
]

# Paths that must never be rate-limited (health, key-gated internal, static).
_RL_NEVER = frozenset({"/api/health"})


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """New-bucket rate limiting middleware (RATE_LIMIT_ENFORCE controls enforcement).

    Registered after add_security_and_cache_headers → runs outermost → 429
    short-circuits skip the security-header middleware (sets its own headers).
    """
    method = request.method
    if method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if path in _RL_NEVER or path.startswith(("/api/internal/", "/static/")):
        return await call_next(request)

    ip = _client_ip(request)
    for methods, paths, max_req, window, bucket in _RL_BUCKETS:
        if method in methods and path in paths:
            if _rate_limited(f"rl:{bucket}:{ip}", max_req, window):
                if _RATE_LIMIT_ENFORCE:
                    return JSONResponse(
                        {"detail": "Too many requests. Please slow down."},
                        status_code=429,
                        headers={
                            "Retry-After": str(window),
                            "Cache-Control": "no-store",
                            "X-Content-Type-Options": "nosniff",
                        },
                    )
                print(f"[rate_limit][WARN] would-429 bucket={bucket} path={path} ip={ip}", flush=True)
            break

    return await call_next(request)


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
    "SPCX": "SpaceX",
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
    "SUBFX": "Carillon Reams Unconstrained Bond Fund",
    "WCPBX": "Weitz Core Plus Income Fund",
    "RTX": "RTX Corporation",
    "LHX": "L3Harris Technologies, Inc.",
    "NOC": "Northrop Grumman Corporation",
    "GD": "General Dynamics Corporation",
    # Portfolio funds added 2026-06-15 (2026-06-02 EPM models workbook)
    "AVLV": "Avantis U.S. Large Cap Value ETF",
    "BPTIX": "Baron Partners Fund",
    "DYNF": "iShares U.S. Equity Factor Rotation Active ETF",
    "EMEQ": "Nomura Focused Emerging Markets Equity ETF",
    "FLMI": "Franklin Dynamic Municipal Bond ETF",
    "FWD": "AB Disruptors ETF",
    "MFSB": "MFS Active Core Plus Bond ETF",
    "TAXF": "American Century Diversified Municipal Bond ETF",
    "TDI": "Touchstone Dynamic International ETF",
    "XMMO": "Invesco S&P MidCap Momentum ETF",
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

def _merge_alias_text(*groups: object) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        if not group:
            continue
        if isinstance(group, str):
            parts = group.split("|")
        else:
            try:
                parts = list(group)
            except TypeError:
                parts = [str(group)]
        for part in parts:
            alias = str(part or "").strip()
            key = alias.lower()
            if alias and key not in seen:
                seen.add(key)
                out.append(alias)
    return " | ".join(out)

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

        leaderboard_path = DATA_DIR / "model_leaderboard_by_ticker.csv"
        if leaderboard_path.exists():
            rankings_df = pd.read_csv(leaderboard_path)
            rankings_df = rankings_df.sort_values(["Ticker", "MAE", "RMSE"]).copy()
            rankings_df["Rank"] = rankings_df.groupby("Ticker").cumcount() + 1
            if "Composite_Score" not in rankings_df.columns:
                rankings_df["Composite_Score"] = float("nan")
        else:
            rankings_df = pd.read_csv(DATA_DIR / "model_rankings.csv")

        model_key_map = {
            "DeepLearning": "DL",
            "Deep Learning": "DL",
            "Fama-French": "FamaFrench",
        }

        def _model_key(name) -> str:
            raw = str(name or "").strip()
            return model_key_map.get(raw, raw)

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

            ranking_cols = [
                "Model",
                "Rank",
                "Composite_Score",
                "RMSE",
                "Directional_Accuracy",
                "MAE",
                "N",
                "Corr",
                "CI_Coverage",
            ]
            available_ranking_cols = [c for c in ranking_cols if c in rankings_df.columns]
            ticker_rankings = (
                rankings_df[rankings_df["Ticker"] == ticker][available_ranking_cols]
                .sort_values("Rank")
                .to_dict(orient="records")
            )
            for r in ticker_rankings:
                r["Model"] = _model_key(r.get("Model"))
            winning_model = ticker_rankings[0]["Model"] if ticker_rankings else _model_key(row.get("Winning_Model"))
            winning_forecast = (
                models.get(winning_model, {}).get("forecast")
                if winning_model in models
                else _safe(row.get("Winning_Forecast"))
            )

            result[ticker] = {
                "consensus": _safe(row.get("Consensus_Forecast")),
                "confidence_label": str(row.get("Confidence_Label") or ""),
                "agreement_ratio": _safe(row.get("Agreement_Ratio")),
                "std_dev": _safe(row.get("Forecast_StdDev")),
                "winning_model": winning_model,
                "winning_forecast": winning_forecast,
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
    # Rule extracted to services/validators.py (PR G) — this wrapper keeps the
    # 9 internal call sites and their behavior untouched.
    return normalize_ticker(raw)


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
        records[ticker] = {"ticker": ticker, "name": name, "aliases": _merge_alias_text(NAME_ALIASES.get(ticker, []))}
    for row in _optional_symbol_rows():
        ticker = row["ticker"]
        base = records.get(ticker, {"ticker": ticker, "name": row["name"], "aliases": ""})
        if base.get("name") == ticker and row.get("name"):
            base["name"] = row["name"]
        base["aliases"] = _merge_alias_text(base.get("aliases", ""), NAME_ALIASES.get(ticker, []))
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
                records[ticker] = {"ticker": ticker, "name": SUGGESTION_NAME_MAP.get(ticker, ticker), "aliases": _merge_alias_text(NAME_ALIASES.get(ticker, []))}

    return tuple(records[k] for k in sorted(records))


def _suggestion_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[^A-Z0-9]+", str(value or "").upper()) if token)


def _suggestion_record(
    ticker: str,
    name: str = "",
    aliases: str = "",
    source_priority: int = 50,
) -> dict[str, object]:
    clean_ticker = _normalize_symbol(ticker)
    clean_name = str(name or "").strip() or clean_ticker
    clean_aliases = _merge_alias_text(aliases, NAME_ALIASES.get(clean_ticker, []))
    return {
        "ticker": clean_ticker,
        "name": clean_name,
        "aliases": clean_aliases,
        "ticker_key": clean_ticker.replace(".", ""),
        "alias_tokens": _suggestion_tokens(clean_aliases),
        "source_priority": source_priority,
        "popular_rank": POPULAR_SUGGESTIONS.index(clean_ticker) if clean_ticker in POPULAR_SUGGESTIONS else 999,
    }


@lru_cache(maxsize=1)
def _suggestion_index() -> tuple[dict[str, object], ...]:
    return tuple(
        _suggestion_record(
            str(row.get("ticker") or ""),
            str(row.get("name") or ""),
            str(row.get("aliases") or ""),
            source_priority=0 if row.get("ticker") in SUGGESTION_NAME_MAP else 20,
        )
        for row in _search_universe()
        if row.get("ticker")
    )


def _prefix_match_rank(record: dict[str, object], query: str) -> Optional[tuple[int, int]]:
    q = _normalize_symbol(query).replace(".", "")
    if not q:
        return None
    ticker_key = str(record.get("ticker_key") or "")
    alias_tokens = tuple(record.get("alias_tokens") or ())

    if ticker_key == q:
        return (0, 0)
    if ticker_key.startswith(q):
        return (1, len(ticker_key))
    if len(q) >= 2:
        alias_lengths = [len(token) for token in alias_tokens if token.startswith(q)]
        if alias_lengths:
            return (2, min(alias_lengths))
    return None


def _rank_prefix_suggestions(rows: Iterable[dict[str, object]], query: str, limit: int) -> list[dict[str, str]]:
    ranked: list[tuple[tuple[int, int, int, int, str], dict[str, object]]] = []
    seen: set[str] = set()
    for row in rows:
        ticker = _normalize_symbol(str(row.get("ticker") or ""))
        if not ticker or ticker in seen:
            continue
        match = _prefix_match_rank(row, query)
        if match is None:
            continue
        seen.add(ticker)
        sort_key = (
            match[0],
            int(row.get("popular_rank") or 999),
            match[1],
            int(row.get("source_priority") or 99),
            ticker,
        )
        ranked.append((sort_key, row))

    ranked.sort(key=lambda item: item[0])
    return [
        {
            "ticker": str(row.get("ticker") or ""),
            "name": str(row.get("name") or row.get("ticker") or ""),
            "aliases": str(row.get("aliases") or ""),
        }
        for _, row in ranked[:limit]
    ]


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
    email_opt_in: bool = False


class EmailPrefsUpdate(BaseModel):
    email_opt_in: bool


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
async def api_register(request: Request, body: RegisterRequest) -> JSONResponse:
    try:
        user = register_user(body.username, body.password, body.email, email_opt_in=body.email_opt_in)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    # If they opted in at signup, send the double-opt-in confirmation. Never let a
    # mail failure break account creation.
    if body.email_opt_in:
        try:
            token = make_email_token(user["id"], EMAIL_PURPOSE_CONFIRM, ttl_hours=168)
            confirm_url = f"{_public_base_url(request)}/email/confirm?t={token}"
            send_subscription_confirmation_email(user["email"], user["username"], confirm_url)
        except Exception:
            pass
    token = create_token(user, remember_me=False)
    response = JSONResponse({
        "ok": True,
        "remember_me": False,
        "user": {"id": user["id"], "username": user["username"]},
        "prefs": get_user_prefs(user["id"]),
    })
    _set_auth_cookie(response, token, remember_me=False)
    return response


@app.post("/api/auth/forgot-password")
async def api_forgot_password(request: Request, body: ForgotPasswordRequest) -> JSONResponse:
    # Always return the same message regardless of whether the email exists
    # prevents user enumeration attacks.
    generic_ok = JSONResponse({"ok": True, "message": "If that email is registered, a reset link has been sent."})

    # Rate-limit to prevent reset-email bombing / abuse of our outbound mail.
    # Gate on BOTH source IP and the target email so neither axis can be hammered.
    _ip = _client_ip(request)
    _email_key = (body.email or "").strip().lower()
    if (_rate_limited(f"forgot-ip:{_ip}", max_requests=5, window_s=300)
            or (_email_key and _rate_limited(f"forgot-email:{_email_key}", max_requests=3, window_s=900))):
        # Return the same generic OK so we don't leak that throttling occurred.
        return generic_ok

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
async def api_reset_password(request: Request, body: ResetPasswordRequest) -> JSONResponse:
    if _rate_limited(f"reset:{_client_ip(request)}", max_requests=10, window_s=60):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
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


@app.post("/api/user/email-prefs")
async def api_set_email_prefs(request: Request, body: EmailPrefsUpdate) -> JSONResponse:
    """Toggle the daily-recap subscription. Turning it on for an unconfirmed
    address triggers a double-opt-in confirmation email."""
    payload = _require_user(request)
    user_id = int(payload["sub"])
    set_email_opt_in(user_id, body.email_opt_in)
    sub = get_email_subscription(user_id)
    confirmation_sent = False
    if body.email_opt_in and not sub["email_confirmed"]:
        user = get_user_by_id(user_id)
        if user and user.get("email"):
            try:
                token = make_email_token(user_id, EMAIL_PURPOSE_CONFIRM, ttl_hours=168)
                confirm_url = f"{_public_base_url(request)}/email/confirm?t={token}"
                send_subscription_confirmation_email(user["email"], user["username"], confirm_url)
                confirmation_sent = True
            except Exception:
                pass
    return JSONResponse({
        "ok": True,
        "email_opt_in": sub["email_opt_in"],
        "email_confirmed": sub["email_confirmed"],
        "confirmation_sent": confirmation_sent,
    })


def _email_action_page(title: str, message: str) -> str:
    """Minimal standalone HTML page for confirm/unsubscribe landings."""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — EPM Market Intelligence</title>
<style>
  body{{font-family:Inter,system-ui,sans-serif;background:#f5f8fd;margin:0;padding:0;color:#0d1c2e;}}
  .card{{max-width:520px;margin:64px auto;background:#fff;border:1px solid #dfe6f0;border-radius:16px;
        box-shadow:0 4px 24px rgba(0,0,0,.07);overflow:hidden;}}
  .hd{{background:#061326;padding:24px 32px;color:#c8a84b;font-size:13px;font-weight:700;
       letter-spacing:.08em;text-transform:uppercase;}}
  .bd{{padding:32px;}} h1{{font-size:22px;margin:0 0 12px;}} p{{color:#3a5070;line-height:1.6;margin:0 0 8px;}}
  a{{color:#3b82f6;}}
</style></head>
<body><div class="card"><div class="hd">EPM Market Intelligence</div>
<div class="bd"><h1>{title}</h1><p>{message}</p>
<p style="margin-top:20px;"><a href="{_public_base_url()}/">Return to EPM Market Intelligence</a></p>
</div></div></body></html>"""


@app.get("/email/confirm")
async def email_confirm(t: str = "") -> HTMLResponse:
    """Double-opt-in landing: validates the signed token and marks the address confirmed."""
    try:
        user_id = verify_email_token(t, EMAIL_PURPOSE_CONFIRM)
    except AuthError as exc:
        return HTMLResponse(_email_action_page("Link invalid", str(exc)), status_code=400)
    set_email_confirmed(user_id, True)
    set_email_opt_in(user_id, True)
    return HTMLResponse(_email_action_page(
        "Subscription confirmed",
        "You're all set — you'll receive the EPM daily market recap. You can unsubscribe "
        "anytime from the footer of any email or your profile.",
    ))


@app.get("/unsubscribe")
async def unsubscribe_get(t: str = "") -> HTMLResponse:
    """One-click unsubscribe landing (browser GET)."""
    try:
        user_id = verify_email_token(t, EMAIL_PURPOSE_UNSUB)
    except AuthError as exc:
        return HTMLResponse(_email_action_page("Link invalid", str(exc)), status_code=400)
    set_email_opt_in(user_id, False)
    return HTMLResponse(_email_action_page(
        "Unsubscribed",
        "You've been unsubscribed from the EPM daily market recap. You can re-subscribe "
        "anytime from your profile.",
    ))


@app.post("/unsubscribe")
async def unsubscribe_post(t: str = "") -> PlainTextResponse:
    """RFC 8058 one-click unsubscribe (List-Unsubscribe-Post). Mail clients POST here."""
    try:
        user_id = verify_email_token(t, EMAIL_PURPOSE_UNSUB)
    except AuthError:
        return PlainTextResponse("Invalid link.", status_code=400)
    set_email_opt_in(user_id, False)
    return PlainTextResponse("Unsubscribed.", status_code=200)


@app.get("/api/internal/daily-recipients")
async def internal_daily_recipients(request: Request) -> JSONResponse:
    """Server-internal: the confirmed-opt-in recipient list with per-user unsubscribe
    URLs, fetched by the laptop pipeline over Tailscale right before the daily send.
    Guarded by INTERNAL_API_KEY (constant-time compare); disabled if the key is unset."""
    key = request.headers.get("X-Internal-Key", "")
    if not INTERNAL_API_KEY or not hmac.compare_digest(key, INTERNAL_API_KEY):
        raise HTTPException(status_code=403, detail="Forbidden.")
    base = _public_base_url(request)
    recipients = []
    for sub in get_confirmed_subscribers():
        tok = make_email_token(sub["user_id"], EMAIL_PURPOSE_UNSUB)
        recipients.append({
            "email": sub["email"],
            "username": sub["username"],
            "unsubscribe_url": f"{base}/unsubscribe?t={tok}",
        })
    return JSONResponse({"ok": True, "recipients": recipients})


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


def _prev_market_day(d, *, _us_holidays=None):
    """Return the most recent market day strictly before d. Pure + testable."""
    from datetime import timedelta
    if _us_holidays is None:
        try:
            import holidays as _hol
            _us_holidays = _hol.US()
        except Exception:
            _us_holidays = frozenset()
    prev = d - timedelta(days=1)
    for _ in range(14):
        if prev.weekday() < 5 and prev not in _us_holidays:
            return prev
        prev -= timedelta(days=1)
    return prev


@app.get("/api/health")
def health() -> dict:
    """Operational health for monitoring. Aggregates lightweight checks and never
    raises. Returns status 'ok' or 'degraded'. Intentionally exposes NO secrets,
    host/IPs, or filesystem paths — only booleans, the (already-public) report date,
    and bare filenames for any missing data file.
    """
    checks: dict = {}
    overall_ok = True
    reasons: list = []

    # 1. Commentary present + fresh on market days.
    # NOTE: computed inline (not imported from check_site_freshness) — that module is a
    # laptop-side CLI that probes the live site from OUTSIDE and is not shipped to the
    # server, so importing it here would ImportError in production and mark health degraded.
    try:
        from datetime import date as _date, datetime as _dt
        try:
            from zoneinfo import ZoneInfo as _ZI
            today_s = _dt.now(_ZI("America/Chicago")).strftime("%Y-%m-%d")
        except Exception:
            today_s = _date.today().isoformat()
        _td = _date.today()
        mkt_open = _td.weekday() < 5
        if mkt_open:
            try:
                import holidays as _hol
                mkt_open = _td not in _hol.US()
            except Exception:
                pass
        cpath = DATA_DIR / "latest_commentary.json"
        _c_doc, _c_status = read_json_artifact(cpath)
        if _c_status == "malformed":
            # Preserve original semantics: malformed commentary -> the outer
            # except path (check_failed + degraded), exactly as json.load raising did.
            raise ValueError("malformed latest_commentary.json")
        report_date = (_c_doc or {}).get("report_date")
        fresh = (report_date == today_s) if mkt_open else True
        checks["commentary"] = {
            "present": bool(report_date),
            "report_date": report_date,
            "market_open": mkt_open,
            "fresh": fresh,
        }
        if not report_date or (mkt_open and not fresh):
            overall_ok = False
    except Exception:
        checks["commentary"] = {"ok": False, "error": "check_failed"}
        overall_ok = False

    # 2. Critical data files present (bare filenames only)
    try:
        required = ["latest_commentary.json", "consensus_forecasts.csv",
                    "forecast_confidence.csv", "enrichment.json"]
        missing = [f for f in required if not (DATA_DIR / f).exists()]
        checks["data_files"] = {"all_present": not missing, "missing": missing}
        if missing:
            overall_ok = False
    except Exception:
        checks["data_files"] = {"ok": False}
        overall_ok = False

    # 3. Deep-analysis worker liveness
    try:
        ws = worker_status()
        checks["deep_worker"] = ws
        if not ws.get("alive"):
            overall_ok = False
    except Exception:
        checks["deep_worker"] = {"alive": False}
        overall_ok = False

    # 4. Ollama reachability + required model availability
    try:
        import requests as _req
        r = _req.get(f"{_CHAT_OLLAMA_HOST}/api/tags", timeout=3)
        checks["ollama"] = {"reachable": bool(r.ok)}
        if not r.ok:
            overall_ok = False
        else:
            try:
                _tags = r.json()
                _loaded = {m.get("name", "") for m in (_tags.get("models") or [])}
                _chat_m = _CHAT_OLLAMA_MODEL
                _council_m = _rc.council_model()
                _missing_m = [m for m in (_chat_m, _council_m) if m not in _loaded]
                checks["ollama"]["models"] = {
                    "chat": _chat_m in _loaded,
                    "council": _council_m in _loaded,
                }
                for _m in _missing_m:
                    overall_ok = False
                    reasons.append(f"ollama_model_missing:{_m}")
            except Exception:
                checks["ollama"]["models"] = {"check_failed": True}
    except Exception:
        checks["ollama"] = {"reachable": False}
        overall_ok = False

    # 5. Last pipeline run (status file pushed from laptop by post_run.push_status_file)
    try:
        from datetime import date as _d2
        _status_path = DATA_DIR / "run_daily_status.json"
        _sr, _sr_status = read_json_artifact(_status_path)
        if _sr_status == "missing":
            checks["last_run"] = {"present": False}
            # Info-only — first deploy before any push has happened
        elif _sr is None:  # malformed — same shape the old except path produced
            checks["last_run"] = {"present": False, "error": "check_failed"}
        else:
            _ts_str = _sr.get("ts", "")
            _stage = _sr.get("stage", "")
            _ok_flag = bool(_sr.get("ok", False))
            _age_h = None
            _run_date = None
            try:
                from datetime import datetime as _dt2, timezone as _tz2
                _run_ts = _dt2.fromisoformat(_ts_str.replace("Z", "+00:00"))
                _age_h = (_dt2.now(_tz2.utc) - _run_ts.astimezone(_tz2.utc)).total_seconds() / 3600
                _run_date = _run_ts.astimezone(_tz2.utc).date()
            except Exception:
                pass
            _run_stale = False
            if _run_date is not None:
                try:
                    _prev = _prev_market_day(_d2.today())
                    _run_stale = _run_date < _prev
                except Exception:
                    pass
            checks["last_run"] = {
                "present": True,
                "ts": _ts_str,
                "stage": _stage,
                "ok": _ok_flag,
                "age_hours": round(_age_h, 1) if _age_h is not None else None,
            }
            if not _ok_flag:
                overall_ok = False
                reasons.append(f"last_run_failed:{_stage}")
            elif _run_stale:
                overall_ok = False
                reasons.append("last_run_stale")
    except Exception:
        checks["last_run"] = {"present": False, "error": "check_failed"}

    # 6. Database writability (users.db + research cache)
    try:
        import sqlite3 as _sqlite3
        from services.auth_service import DB_PATH as _users_db_path
        _research_db_path = Path(os.getenv("RESEARCH_DB_PATH", "research_cache.db"))
        _db_results: dict = {}
        _any_readonly = False
        for _db_name, _db_path in [("users", _users_db_path), ("research", _research_db_path)]:
            if not Path(_db_path).exists():
                _db_results[_db_name] = {"exists": False}
                continue
            try:
                _conn = _sqlite3.connect(str(_db_path), timeout=2)
                _conn.execute("BEGIN IMMEDIATE")
                _conn.execute("ROLLBACK")
                _conn.close()
                _db_results[_db_name] = {"writable": True}
            except _sqlite3.OperationalError as _exc:
                _emsg = str(_exc).lower()
                if "readonly" in _emsg:
                    _db_results[_db_name] = {"writable": False}
                    _any_readonly = True
                    reasons.append(f"db_readonly:{_db_name}")
                elif "locked" in _emsg:
                    _db_results[_db_name] = {"writable": True, "busy": True}
                else:
                    _db_results[_db_name] = {"writable": False, "error": str(_exc)[:80]}
                    _any_readonly = True
                    reasons.append(f"db_error:{_db_name}")
            except Exception as _exc:
                _db_results[_db_name] = {"writable": False, "error": "check_failed"}
                _any_readonly = True
                reasons.append(f"db_error:{_db_name}")
        checks["db"] = _db_results
        if _any_readonly:
            overall_ok = False
    except Exception:
        checks["db"] = {"error": "check_failed"}

    # 7. Watchdog thread liveness
    try:
        checks["watchdog"] = watchdog_status()
    except Exception:
        checks["watchdog"] = {"alive": False, "error": "check_failed"}

    # 8. Data freshness — reads the report written by the laptop pipeline
    # (data/data_freshness.json, synced via data/ SYNC_DIRS). File absent = not
    # degraded (first deploy before the pipeline has run). Degrades only when
    # the persisted report shows critical failures AND enforce was on AND market open.
    try:
        _df_path = DATA_DIR / "data_freshness.json"
        _df_payload, _df_status = read_json_artifact(_df_path)
        if _df_status == "missing":
            checks["data_freshness"] = {"present": False}
        elif _df_payload is None:  # malformed — same shape the old except path produced
            checks["data_freshness"] = {"present": False, "error": "check_failed"}
        else:
            _df_enforce = bool(_df_payload.get("enforce", False))
            _df_results = _df_payload.get("results", [])
            _df_critical_failing = [r["name"] for r in _df_results
                                     if r.get("critical") and not r.get("ok")
                                     and r.get("status") != "skipped"]
            _df_failing = [r["name"] for r in _df_results
                           if not r.get("ok") and r.get("status") != "skipped"]
            checks["data_freshness"] = {
                "present": True,
                "ts": _df_payload.get("ts"),
                "enforce": _df_enforce,
                "failing": _df_failing,
                "critical_failing": _df_critical_failing,
            }
            if _df_enforce and _df_critical_failing and mkt_open:
                overall_ok = False
                for _dfn in _df_critical_failing:
                    reasons.append(f"data_freshness:{_dfn}")
    except Exception:
        checks["data_freshness"] = {"present": False, "error": "check_failed"}

    # 9. Email send summary — reads the counts-only report written by the laptop pipeline
    # (data/email_send_summary.json, synced via data/ SYNC_DIRS). File absent = not
    # degraded (no run yet today). Degrades only when date == today AND market open.
    # NEVER exposes email addresses — subscriber PII stays in the laptop-local ledger.
    try:
        _es_path = DATA_DIR / "email_send_summary.json"
        _es, _es_status = read_json_artifact(_es_path)
        if _es_status == "missing":
            checks["email_send"] = {"present": False}
        elif _es is None:  # malformed — same shape the old except path produced
            checks["email_send"] = {"present": False, "error": "check_failed"}
        else:
            checks["email_send"] = {
                "present": True,
                "date": _es.get("date"),
                "ts": _es.get("ts"),
                "attempts": _es.get("attempts"),
                "total": _es.get("total"),
                "sent": _es.get("sent"),
                "failed": _es.get("failed"),
                "internal_ok": _es.get("internal_ok"),
                "fetch_ok": _es.get("fetch_ok"),
                "fallback_used": _es.get("fallback_used"),
                "pdf_ok": _es.get("pdf_ok"),
            }
            import datetime as _dt
            _es_today = _es.get("date") == _dt.date.today().isoformat()
            if _es_today and mkt_open:
                if _es.get("failed", 0) > 0:
                    overall_ok = False
                    reasons.append("email_send:partial_failure")
                if _es.get("internal_ok") is False:
                    overall_ok = False
                    reasons.append("email_send:internal_failed")
                if _es.get("fetch_ok") is False:
                    overall_ok = False
                    reasons.append("email_send:subscriber_fetch_failed")
    except Exception:
        checks["email_send"] = {"present": False, "error": "check_failed"}

    # 10. Deploy stamp — info-only: which commit is live and when it was deployed.
    # Written by post_run._write_deploy_stamp() and synced via data/. Absent = not
    # yet deployed via post_run (no degradation). Never touches overall_ok.
    # Counts/flags only — no IPs, paths, secrets, or emails in the response.
    try:
        _ds_path = DATA_DIR / "deploy_stamp.json"
        _ds, _ds_status = read_json_artifact(_ds_path)
        if _ds_status == "missing":
            checks["deploy"] = {"present": False}
        elif _ds is None:  # malformed — same shape the old except path produced
            checks["deploy"] = {"present": False, "error": "check_failed"}
        else:
            import datetime as _ddt
            _ds_ts = _ds.get("ts")
            _ds_age_hours: float | None = None
            if _ds_ts:
                try:
                    _ds_dt = _ddt.datetime.fromisoformat(_ds_ts)
                    if _ds_dt.tzinfo is None:
                        _ds_dt = _ds_dt.replace(tzinfo=_ddt.timezone.utc)
                    _ds_age_hours = round(
                        (_ddt.datetime.now(_ddt.timezone.utc) - _ds_dt).total_seconds() / 3600, 1
                    )
                except Exception:
                    pass
            checks["deploy"] = {
                "present": True,
                "commit": _ds.get("commit"),
                "ts": _ds_ts,
                "age_hours": _ds_age_hours,
            }
    except Exception:
        checks["deploy"] = {"present": False, "error": "check_failed"}

    # Rate-limit flag (info-only, counts/flags only).
    checks["rate_limit"] = {"enforce": _RATE_LIMIT_ENFORCE}

    return {"status": "ok" if overall_ok else "degraded", "checks": checks, "reasons": reasons}


@app.get("/api/suggest-tickers")
def suggest_tickers(q: str = Query("", max_length=60), limit: int = Query(15, ge=1, le=20)) -> dict:
    query = _normalize_symbol(q.strip())
    if not query:
        suggestions = [
            {
                "ticker": t,
                "name": SUGGESTION_NAME_MAP.get(t, t),
                "aliases": _merge_alias_text(NAME_ALIASES.get(t, [])),
            }
            for t in POPULAR_SUGGESTIONS[:limit]
        ]
        return {'ok': True, 'suggestions': suggestions}

    records: dict[str, dict[str, object]] = {
        str(row["ticker"]): dict(row) for row in _suggestion_index()
    }

    direct = _direct_symbol_candidate(query)
    if direct is not None:
        ticker = direct['ticker']
        records[ticker] = _suggestion_record(
            ticker,
            direct.get('name') or records.get(ticker, {}).get("name") or ticker,
            str(records.get(ticker, {}).get("aliases") or ""),
            source_priority=5,
        )

    for row in _remote_yf_suggestions(query, limit=max(limit * 2, 12)):
        ticker = row['ticker']
        if ticker in records:
            if (not records[ticker].get("name") or records[ticker].get("name") == ticker) and row.get("name"):
                records[ticker]["name"] = row["name"]
            continue
        records[ticker] = _suggestion_record(ticker, row.get('name') or ticker, "", source_priority=40)

    suggestions = _rank_prefix_suggestions(records.values(), query, limit)
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
def _startup_watchdog() -> None:
    start_watchdog()


@app.on_event("shutdown")
def _shutdown_watchdog() -> None:
    stop_watchdog()


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


_PROVIDER_DESC_CACHE: dict[str, str] = {}


def _provider_description(symbol: str) -> str:
    """Real company/fund description from the data provider (long business summary).

    The snapshot builder doesn't always include it for every ticker, so this fetches
    it directly from provider.get_profile — the same source the deep-analysis council
    uses — so a description is available on search without running a full analysis.
    Successful results are cached for the process; misses are not cached so they retry.
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return ""
    if sym in _PROVIDER_DESC_CACHE:
        return _PROVIDER_DESC_CACHE[sym]
    provider = getattr(engine, "provider", None)
    if provider is None or not hasattr(provider, "get_profile"):
        return ""
    try:
        prof = provider.get_profile(sym) or {}
    except Exception:
        return ""
    desc = str(prof.get("long_description") or prof.get("description") or prof.get("short_description") or "").strip()
    if not desc or desc.lower() in {"n/a", "none", "null"}:
        return ""
    _PROVIDER_DESC_CACHE[sym] = desc
    return desc


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
        # Try the provider's real long business summary before the generic placeholder.
        desc = _provider_description(symbol) or _fallback_snapshot_description(snap, symbol, name or symbol)
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
        entry = dict(data)  # shallow copy — safe to round top-level scalars
        entry["name"] = MAG7_NAMES.get(ticker, ticker)
        # Trim spurious precision (the consensus CSV stores ~17 sig figs). Display
        # layers already round, but don't leak it raw through the API either.
        for _k in ("consensus", "agreement_ratio", "forecast_stddev"):
            if isinstance(entry.get(_k), (int, float)):
                entry[_k] = round(float(entry[_k]), 4)
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
                        model = {
                            "DeepLearning": "DL",
                            "Deep Learning": "DL",
                            "Fama-French": "FamaFrench",
                        }.get(model, model)
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

def _council_is_running() -> bool:
    """Return True if any deep-analysis job is currently running."""
    jobs_dir = Path("data/jobs")
    if not jobs_dir.exists():
        return False
    for f in jobs_dir.glob("*.json"):
        try:
            if json.loads(f.read_text()).get("status") == "running":
                return True
        except Exception:
            pass
    return False


_CHAT_OLLAMA_HOST = _rc.ollama_url()
_CHAT_OLLAMA_MODEL = _rc.chat_model()
_CHAT_TIMEOUT = int(os.getenv("LOCAL_OLLAMA_TIMEOUT", "120"))

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
        if c.get("cross_asset_synthesis"):
            lines.append(f"Market synthesis: {str(c['cross_asset_synthesis'])[:400]}")
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
async def api_chat(request: Request, body: ChatRequest) -> JSONResponse:
    """AI market assistant — proxies to local Ollama with market context injected.

    Auth-gated: this drives the local Ollama instance (shared, finite GPU), so it
    must not be open to anonymous callers. Mirrors the /api/deep/* auth pattern.
    """
    import requests as _req

    payload = _require_user(request)

    # Rate-limit per authenticated user (falls back to IP if sub is missing).
    _rl_key = f"chat:{payload.get('sub') or _client_ip(request)}"
    if _rate_limited(_rl_key, max_requests=20, window_s=60):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait before sending another message.")

    if _council_is_running():
        raise HTTPException(
            status_code=409,
            detail="Investment Council deliberation in progress — chat is paused for ~20 min while the council deliberates. Please try again shortly.",
        )

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")
    if len(message) > 2000:
        raise HTTPException(status_code=400, detail="Message exceeds 2000 character limit.")

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
            json={"model": _CHAT_OLLAMA_MODEL, "messages": messages, "stream": False,
                  "options": {"num_ctx": 4096}},
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


# Canonical pattern lives in services/validators.py (PR G); alias preserved
# for the two match sites below and any external import.
_DEEP_TICKER_RE = DEEP_TICKER_RE


@app.get("/deep-report")
def deep_report_page() -> FileResponse:
    return _page("deep-report.html")


@app.get("/api/research/{symbol}")
def research_profile(symbol: str, request: Request) -> JSONResponse:
    """Display-only: cached web-research enrichment + Phase-1 fund profile for a
    symbol. Does NOT trigger fresh research — that happens during deep analysis."""
    _require_user(request)
    s = symbol.strip().upper()
    if not _DEEP_TICKER_RE.match(s):
        raise HTTPException(status_code=400, detail="Invalid symbol.")

    from services import research_store
    import deep_analysis as _da

    provider = getattr(engine, "provider", None)
    base: dict = {}
    if provider is not None:
        try:
            base = provider.get_profile(s) or {}
        except Exception:
            base = {}

    try:
        fund = _da._get_fund_profile(s) or {}
    except Exception:
        fund = {}
    is_fund = bool(fund)

    research: dict = {}
    for topic, row in research_store.get_fresh_for_symbol(s).items():
        content = row.get("content") or {}
        if not content.get("found"):
            continue
        entry = {k: v for k, v in content.items() if k != "found"}
        entry["sources"] = row.get("sources") or []
        entry["researched"] = str(row.get("fetched_at") or "")[:10]
        research[topic] = entry

    profile = {
        "name":                    fund.get("name") or base.get("name") or s,
        "category":                fund.get("category"),
        "fund_family":             fund.get("fund_family"),
        "expense_ratio_pct":       fund.get("expense_ratio_pct"),
        "top_holdings":            fund.get("top_holdings"),
        "top10_concentration_pct": fund.get("top10_concentration_pct"),
        "objective":               fund.get("objective") or base.get("long_description"),
        "sector":                  base.get("sector"),
        "industry":                base.get("industry_category"),
    }
    return JSONResponse({
        "ok": True, "symbol": s, "is_fund": is_fund,
        "asset_type": fund.get("issue_type") or base.get("issue_type"),
        "profile": profile, "research": research, "has_research": bool(research),
    })


@app.post("/api/deep/{ticker}")
async def deep_analysis_start(ticker: str, request: Request) -> JSONResponse:
    _user_payload = _require_user(request)
    t = ticker.strip().upper()
    if not _DEEP_TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail="Invalid ticker.")

    # Deep-analysis rate limits (post-auth so per-user keying is available).
    # 6 enqueues/hour per user + 12 enqueues/hour per IP (GPU cost gate).
    _deep_user_key = f"rl:deep_enqueue:user:{_user_payload.get('sub', 'anon')}"
    _deep_ip_key   = f"rl:deep_enqueue:ip:{_client_ip(request)}"
    _deep_over = (_rate_limited(_deep_user_key, 6, 3600)
                  or _rate_limited(_deep_ip_key, 12, 3600))
    if _deep_over:
        if _RATE_LIMIT_ENFORCE:
            raise HTTPException(status_code=429, detail="Deep analysis rate limit reached. Try again later.")
        print(f"[rate_limit][WARN] would-429 bucket=deep_enqueue path=/api/deep/{t}"
              f" user={_user_payload.get('sub')} ip={_client_ip(request)}", flush=True)

    # Optional custom council roster (JSON body {"roster": [...]}). No body =
    # default 8-member council (unchanged behaviour).
    import council_roster
    roster = None
    roster_sig = "default"
    try:
        body = await request.json()
    except Exception:
        body = None
    if isinstance(body, dict) and body.get("roster"):
        roster = body["roster"]
        ok, err = council_roster.validate_roster(roster)
        if not ok:
            raise HTTPException(status_code=400, detail=err)
        roster_sig = council_roster.roster_signature(roster)
        if roster_sig == "default":
            roster = None  # canonical roster — share the default daily cache

    force_fresh = request.query_params.get("force_fresh") == "1"
    earnings_triggered = False

    not_before = None
    earnings_refresh_required = False

    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZoneInfo
    today_str = _dt.now(tz=_ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    from earnings_calendar import get_next_earnings_date
    next_earnings_date, release_time = get_next_earnings_date(t)
    if next_earnings_date == today_str:
        from earnings_refresh import release_not_before_utc
        not_before = release_not_before_utc(today_str, release_time)
        invalidate_today_cache(t)
        force_fresh = True
        earnings_triggered = True
        earnings_refresh_required = True

    # Post-earnings backfill: if earnings_releases.json was updated AFTER the last
    # cached run for this ticker, that run predates the actuals and must be rebuilt.
    # Fires when next_earnings_date has already advanced past today (ticker already
    # reported) but fresh actuals just landed via refresh_same_day_earnings.
    if not force_fresh:
        from earnings_refresh import load_recent_earnings_release
        rel = load_recent_earnings_release(t, max_age_days=2)
        cached = get_today_cached_job(t)
        if rel and cached:
            rel_as_of = pd.to_datetime(rel.get("as_of"), utc=True, errors="coerce")
            cached_at = pd.to_datetime(cached.get("completed_at"), utc=True, errors="coerce")
            if pd.notna(rel_as_of) and pd.notna(cached_at) and rel_as_of > cached_at:
                invalidate_today_cache(t)
                force_fresh = True
                earnings_triggered = True
                earnings_refresh_required = True

    job_id = enqueue(
        t,
        force_fresh=force_fresh,
        not_before=not_before,
        earnings_refresh_required=earnings_refresh_required,
        roster=roster,
        roster_sig=roster_sig,
    )
    return JSONResponse({"ok": True, "job_id": job_id, "ticker": t,
                         "earnings_triggered": earnings_triggered,
                         "not_before": not_before})


@app.get("/api/council/library")
def council_library(request: Request) -> JSONResponse:
    """Library of selectable analysts + trait axes for the Council Builder UI."""
    _require_user(request)
    import council_roster
    return JSONResponse({"ok": True, **council_roster.library_payload()})


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

    Each persona has up to 4 posts (R1-R4). The timeline includes real round
    numbers. The display roster comes from the job's resolved council (custom
    rosters) or the static default. Backwards-compat: old jobs without
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
    import council_roster as _cr
    # Display roster: the job's resolved council if present (custom rosters),
    # else the static default. system_prompt (for bios) looked up from the library.
    roster_meta = result.get("council_roster")
    if roster_meta:
        roster_list = [
            {"name": m.get("name", ""), "title": m.get("title", ""),
             "kind": m.get("kind", "neutral"), "blurb": m.get("blurb", "")}
            for m in roster_meta
        ]
    else:
        roster_list = [
            {"name": p.name, "title": p.title, "kind": p.kind, "blurb": ""}
            for p in PERSONAS
        ]
    _sp_by_name = {p.name: p.system_prompt for p in _cr.LIBRARY}
    _sp_by_name.update({p.name: p.system_prompt for p in PERSONAS})

    takes_by_round = result.get("takes_by_round")

    def _parse_r3_verdict(take_body: str) -> dict:
        stance_m  = re.search(r'FINAL\s+STANCE:\s*(bear(?:ish)?|base|bull(?:ish)?)', take_body, re.IGNORECASE)
        rat_m     = re.search(r'RATIONALE:\s*(.+?)(?:\n|$)', take_body, re.IGNORECASE)
        shifted_m = re.search(r'POSITION\s+SHIFTED:\s*(yes|no)', take_body, re.IGNORECASE)
        why_m     = re.search(r'\bWHY:\s*(.+?)(?:\n|$)', take_body, re.IGNORECASE)
        raw = stance_m.group(1).lower() if stance_m else "base"
        stance = "bearish" if raw.startswith("bear") else "base" if raw == "base" else "bullish"
        shifted = shifted_m.group(1).lower() == "yes" if shifted_m else False
        return {
            "stance":       stance,
            "rationale":    rat_m.group(1).strip() if rat_m else "",
            "shifted":      shifted,
            "shift_reason": why_m.group(1).strip() if (shifted and why_m) else "",
        }

    if takes_by_round:
        # Multi-round format (3 or 4 rounds). Normalise keys: JSON serialises int keys as strings
        tbr = {int(k): v for k, v in takes_by_round.items()}
        # Build per-persona post lists in round order
        posts_by_name: dict = {}
        for rnd in sorted(tbr.keys()):
            for t in tbr[rnd]:
                pname = t.get("name", "")
                body  = (t.get("take") or "").strip()
                if body:
                    posts_by_name.setdefault(pname, []).append(body)

        # Final-round takes keyed by persona name — used for per-agent verdict card.
        # The last round is the vote round, whether there are 3 or 4 rounds.
        final_round = max(tbr.keys()) if tbr else 1
        r3_by_name = {t.get("name", ""): (t.get("take") or "").strip() for t in tbr.get(final_round, [])}

        agents = []
        timeline = []
        for rp in roster_list:
            sys_prompt = _sp_by_name.get(rp["name"], "")
            bio   = rp.get("blurb") or (sys_prompt.split(". ")[0] + "." if sys_prompt else "")
            posts = posts_by_name.get(rp["name"], [])
            r3_body = r3_by_name.get(rp["name"], "")
            agents.append({
                "name":       rp["title"],
                "username":   rp["name"],
                "bio":        bio,
                "persona":    sys_prompt,
                "kind":       rp.get("kind", "neutral"),
                "post_count": len(posts),
                "posts":      posts,
                "verdict":    _parse_r3_verdict(r3_body) if r3_body else {"stance": "base", "rationale": "", "shifted": False, "shift_reason": ""},
            })
            for rnd in sorted(tbr.keys()):
                round_takes = {t["name"]: t for t in tbr[rnd]}
                t = round_takes.get(rp["name"])
                if t:
                    body = (t.get("take") or "").strip()
                    if body:
                        timeline.append({"agent": rp["title"], "content": body, "round": rnd})
    else:
        # Legacy fallback: flat takes list, round = idx+1
        takes = result.get("takes") or []
        agents = []
        timeline = []
        for idx, t in enumerate(takes):
            pname = t.get("name", "")
            title = t.get("title", pname.replace("_", " ").title() if pname else f"Analyst {idx+1}")
            body  = (t.get("take") or "").strip()
            sys_prompt = _sp_by_name.get(pname, "")
            bio   = sys_prompt.split(". ")[0] + "." if sys_prompt else ""
            agents.append({
                "name":       title,
                "username":   pname,
                "bio":        bio,
                "persona":    sys_prompt,
                "post_count": 1 if body else 0,
                "posts":      [body] if body else [],
            })
            if body:
                timeline.append({"agent": title, "content": body, "round": idx + 1})

    return JSONResponse({"ok": True, "agents": agents, "timeline": timeline})


@app.get("/api/deep/active")
def deep_active(request: Request) -> JSONResponse:
    """Returns {busy: true} if a council analysis is currently running."""
    _require_user(request)
    return JSONResponse({"busy": _council_is_running()})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
