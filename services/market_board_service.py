from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from threading import RLock
from time import time
from typing import Any, Callable

import pandas as pd
import re

_SVC_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR  = _SVC_ROOT / "data"

try:
    from services.ticker_page_service import TickerPageService  # type: ignore
except Exception:
    TickerPageService = None  # type: ignore

try:
    from snapshot_engine import (
        TickerSnapshotEngine,
        _annualized_volatility,
        _normalize_history,
        _pct_return,
        _safe_float,
        _trend_state,
        TRADING_DAYS_1M,
        TRADING_DAYS_PER_YEAR,
    )
except Exception:
    TickerSnapshotEngine = None  # type: ignore
    TRADING_DAYS_1M = 21
    TRADING_DAYS_PER_YEAR = 252

    def _safe_float(value: Any) -> float | None:
        try:
            return None if value is None else float(value)
        except Exception:
            return None

    def _pct_return(series: pd.Series, periods: int) -> float | None:
        if len(series) <= periods:
            return None
        start = _safe_float(series.iloc[-periods - 1])
        end = _safe_float(series.iloc[-1])
        if start in (None, 0) or end is None:
            return None
        return (end / start) - 1.0

    def _annualized_volatility(daily_returns: pd.Series) -> float | None:
        daily_returns = daily_returns.dropna()
        if len(daily_returns) < 20:
            return None
        return _safe_float(daily_returns.std(ddof=1) * (252 ** 0.5))

    def _normalize_history(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"], errors="coerce")
            out = out.sort_values("date").reset_index(drop=True)
        for col in ["open", "high", "low", "close", "volume"]:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        return out

    def _trend_state(last_price: float | None, ma50: float | None, ma200: float | None) -> str:
        if last_price is None or ma50 is None or ma200 is None:
            return "unknown"
        if last_price > ma50 > ma200:
            return "strong_uptrend"
        if last_price > ma200 and ma50 > ma200:
            return "uptrend"
        if last_price < ma50 < ma200:
            return "strong_downtrend"
        if last_price < ma200:
            return "downtrend"
        return "mixed"

try:
    from universe_config import get_index_comparison_tickers, get_mag7, get_portfolio_tickers
except Exception:
    get_index_comparison_tickers = None  # type: ignore
    get_mag7 = None  # type: ignore
    get_portfolio_tickers = None  # type: ignore

DEFAULT_HOME_MARKET_STRIP = ["^SPX", "^NDX", "^DJI", "^STOXX50E", "000001.SS", "^N225", "^KS11"]
DEFAULT_INDEX_SYMBOLS = ["^SPX", "^NDX", "^DJI", "^STOXX50E", "000001.SS", "^N225", "^KS11"]
DEFAULT_MARKET_UNIVERSE = [
    "SPY", "QQQ", "DIA", "IWM", "XLF", "XLK", "XLY", "XLP", "XLI", "XLB", "XLV", "XLU", "XLE", "XLRE", "XLC",
    "SMH", "SOXX", "IGV", "ARKK", "HYG", "LQD", "TLT", "IEF", "SHY", "UUP", "GLD", "SLV", "EEM", "FXI", "VNQ", "XBI"
]
DEFAULT_SECTOR_SYMBOLS = ["XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY", "XLB"]
DEFAULT_MARKET_MOVERS_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX", "ORCL", "CRM",
    "LMT", "RTX", "NOC", "GD", "BA", "GE", "PLTR", "SMCI", "DELL", "ARM", "MU", "QCOM", "INTC",
    "JPM", "BAC", "GS", "MS", "V", "MA", "UNH", "COST", "WMT", "KO", "PEP", "XOM", "CVX",
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO", "RSP", "VUG", "SMH", "SOXX", "IGV", "XBI", "ARKK",
    "XLE", "XLF", "XLK", "XLI", "XLP", "XLY", "XLV", "XLB", "XLU", "XLC", "XLRE", "KRE", "XME",
    "TLT", "IEF", "LQD", "HYG", "GLD", "SLV", "UUP", "EEM", "FXI", "EWJ", "VNQ"
]
DEFAULT_RISK_ON_CANDIDATES = ["QQQ", "IWM", "SMH", "SOXX", "IGV", "XLY", "XBI", "ARKK", "HYG", "XLE", "XLI", "VUG"]
DEFAULT_RISK_OFF_CANDIDATES = ["TLT", "IEF", "SHY", "GLD", "UUP", "XLU", "XLP", "LQD", "XLV", "BIL", "SGOV"]
DEFAULT_HOME_NEWS_SYMBOLS = ["SPY", "QQQ", "AAPL"]
DEFAULT_PERIOD = "6m"
DEFAULT_MAX_WORKERS = 3





DISPLAY_NAME_OVERRIDES = {
    "^SPX": "S&P 500 Index",
    "SPY": "S&P 500 ETF",
    "^NDX": "NASDAQ 100 Index",
    "QQQ": "NASDAQ 100 ETF",
    "^DJI": "Dow Jones Industrial Average",
    "DIA": "Dow Jones Industrial Average ETF",
    "^STOXX50E": "EURO STOXX 50 Index",
    "000001.SS": "Shanghai Composite Index",
    "^N225": "Nikkei 225 Index",
    "^KS11": "KOSPI Composite Index",
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
    "XLB": "Materials Select Sector SPDR Fund",
}

SECTOR_OVERRIDES = {
    "SPY": "Broad Market",
    "QQQ": "Nasdaq 100",
    "DIA": "Dow Industrials",
    "IWM": "Small Caps",
    "XLF": "Financials",
    "XLK": "Technology",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLV": "Health Care",
    "XLU": "Utilities",
    "XLE": "Energy",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
    "SMH": "Semiconductors",
    "SOXX": "Semiconductors",
    "IGV": "Software",
    "ARKK": "Innovation",
    "HYG": "High Yield Bonds",
    "LQD": "Investment Grade Bonds",
    "TLT": "Long Treasuries",
    "IEF": "Intermediate Treasuries",
    "SHY": "Short Treasuries",
    "UUP": "US Dollar",
    "GLD": "Gold",
    "SLV": "Silver",
    "EEM": "Emerging Markets",
    "FXI": "China Large Cap",
    "EWJ": "Japan",
    "VNQ": "Real Estate",
    "XBI": "Biotech",
}

@dataclass(slots=True)
class MarketBoardConfig:
    home_market_strip: list[str] = field(default_factory=lambda: list(DEFAULT_HOME_MARKET_STRIP))
    index_symbols: list[str] = field(default_factory=lambda: list(DEFAULT_INDEX_SYMBOLS))
    market_universe: list[str] = field(default_factory=lambda: list(DEFAULT_MARKET_UNIVERSE))
    market_movers_universe: list[str] = field(default_factory=lambda: list(DEFAULT_MARKET_MOVERS_UNIVERSE))
    sector_symbols: list[str] = field(default_factory=lambda: list(DEFAULT_SECTOR_SYMBOLS))
    risk_on_candidates: list[str] = field(default_factory=lambda: list(DEFAULT_RISK_ON_CANDIDATES))
    risk_off_candidates: list[str] = field(default_factory=lambda: list(DEFAULT_RISK_OFF_CANDIDATES))
    home_news_symbols: list[str] = field(default_factory=lambda: list(DEFAULT_HOME_NEWS_SYMBOLS))
    default_period: str = DEFAULT_PERIOD
    top_news_per_symbol: int = 2
    top_news_limit: int = 5
    leaders_count: int = 6
    laggards_count: int = 6
    sector_leaders_count: int = 5
    sector_laggards_count: int = 5
    max_workers: int = DEFAULT_MAX_WORKERS
    cache_ttl_seconds: int = 600


class MarketBoardService:
    def __init__(self, page_service: Any | None = None, snapshot_engine: Any | None = None, config: MarketBoardConfig | None = None) -> None:
        self.config = config or MarketBoardConfig()
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._cache_lock = RLock()

        if page_service is not None:
            self.page_service = page_service
        elif TickerPageService is not None:
            self.page_service = TickerPageService(snapshot_engine=snapshot_engine or None)
        else:
            self.page_service = None

        if snapshot_engine is not None:
            self.snapshot_engine = snapshot_engine
        elif self.page_service is not None and hasattr(self.page_service, "snapshot_engine"):
            self.snapshot_engine = self.page_service.snapshot_engine
        elif TickerSnapshotEngine is not None:
            self.snapshot_engine = TickerSnapshotEngine()
        else:
            self.snapshot_engine = None

        if self.page_service is None and self.snapshot_engine is None:
            raise RuntimeError("MarketBoardService requires either a page_service or a snapshot_engine.")

    def get_home_payload(self) -> dict[str, Any]:
        cache_key = ("home_payload",)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        market_strip_symbols = self._safe_symbol_list(self._load_universe_or_default("home_market_strip", self.config.home_market_strip))
        mag7_symbols = self._safe_symbol_list(self._load_mag7())
        portfolio_symbols = self._safe_symbol_list(self._load_portfolio_symbols())

        mag7_set = {s.upper() for s in mag7_symbols}
        watchlist_symbols = [s for s in portfolio_symbols if s.upper() not in mag7_set][:4]
        payload = {
            "generated_at": self._today_iso(),
            "market_strip": self._decorate_index_cards(self.build_symbol_cards(market_strip_symbols[:7], period="3m")),
            "featured_cards": self.build_symbol_cards(mag7_symbols[:4], period="6m"),
            "portfolio_watchlist": self.build_symbol_cards(watchlist_symbols, period="6m"),
            "top_news": self.get_top_news_feed(self.config.home_news_symbols),
            "universe": {
                "market_strip": market_strip_symbols[:7],
                "featured": mag7_symbols[:4],
                "portfolio_watchlist": watchlist_symbols,
            },
        }
        return self._cache_set(cache_key, payload)

    def _load_world_news(self, limit: int = 15) -> list[dict]:
        """Read world news articles saved by generate_market_commentary.py."""
        path = _DATA_DIR / "world_news.json"
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("articles", [])[:limit]
        except Exception:
            return []

    def _load_economic_calendar(self, weeks: int = 4) -> list[dict]:
        """Read upcoming economic events saved by generate_market_commentary.py.

        Filters to the next `weeks` weeks and drops low-importance entries so
        the calendar is not swamped by foreign holidays and minor auctions.
        """
        path = _DATA_DIR / "economic_calendar.json"
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            from datetime import date, timedelta
            today = date.today()
            end = today + timedelta(weeks=weeks)
            out = []
            for ev in data.get("events", []):
                d = (ev.get("date") or "")[:10]
                if not d:
                    continue
                try:
                    ev_d = date.fromisoformat(d)
                except ValueError:
                    continue
                if ev_d < today or ev_d > end:
                    continue
                if (ev.get("importance") or "").lower() == "low":
                    continue
                out.append(ev)
            return out
        except Exception:
            return []

    def get_markets_payload(self) -> dict[str, Any]:
        cache_key = ("markets_payload",)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        index_symbols = self._safe_symbol_list(self._load_index_symbols())[:7]
        core_universe = self._safe_symbol_list(self.config.market_universe)
        sector_symbols = self._safe_symbol_list(self.config.sector_symbols)
        mover_symbols = self._safe_symbol_list(self.config.market_movers_universe)

        index_cards = self._decorate_index_cards([card for card in self.build_symbol_cards(index_symbols, period="3m") if not card.get("error")])
        market_cards = [card for card in self.build_symbol_cards(core_universe, period="3m") if not card.get("error")]
        mover_cards = [card for card in self.build_symbol_cards(mover_symbols, period="1m") if not card.get("error")]
        sector_cards = [card for card in self.build_symbol_cards(sector_symbols, period="1y") if not card.get("error")]

        risk_board = {
            "risk_on": self._select_cards_from_candidates(market_cards, self.config.risk_on_candidates, metric="return_1m", count=4),
            "risk_off": self._select_cards_from_candidates(market_cards, self.config.risk_off_candidates, metric="return_1m", count=4),
        }
        leaders, laggards = self._rank_cards_by_return(mover_cards, metric="day_change_pct", directional=True)
        sector_leaders, sector_laggards = self._rank_cards_by_return(sector_cards, metric="return_ytd", directional=True)
        trend_table = self._build_trend_table(market_cards)[:12]

        payload = {
            "generated_at": self._today_iso(),
            "indexes": index_cards,
            "index_comparison": self._build_index_comparison(index_symbols),
            "macro_lens_charts": self._build_macro_lens_charts(),
            "risk_board": risk_board,
            "leaders": leaders,
            "laggards": laggards,
            "movers_box": {"gainers": leaders[:5], "losers": laggards[:5]},
            "sector_leaders": sector_leaders[: self.config.sector_leaders_count],
            "sector_laggards": sector_laggards[: self.config.sector_laggards_count],
            "sector_rotation": self._build_sector_rotation_data(sector_cards),
            "trend_table": trend_table,
            "risk_dashboard": self._build_markets_dashboard(index_cards, sector_cards, risk_board, leaders, laggards),
            "market_read": self._build_markets_read(index_cards, sector_cards, risk_board, leaders, laggards, trend_table),
            "universe": {
                "indexes": index_symbols,
                "market_universe": core_universe,
                "market_movers_universe": mover_symbols,
                "sector_symbols": sector_symbols,
            },
            "world_news":         self._load_world_news(),
            "economic_calendar":  self._load_economic_calendar(),
        }
        return self._cache_set(cache_key, payload)

    def get_portfolios_payload(self) -> dict[str, Any]:
        cache_key = ("portfolios_payload",)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        mag7_set = {s.upper() for s in self._safe_symbol_list(self._load_mag7())}
        portfolio_symbols = [s for s in self._safe_symbol_list(self._load_portfolio_symbols()) if s.upper() not in mag7_set]
        portfolio_cards = self.build_symbol_cards(portfolio_symbols, period="6m")
        live_cards = [card for card in portfolio_cards if not card.get("error")]
        leaders, laggards = self._rank_cards_by_return(live_cards, metric="day_change_pct", directional=True)

        payload = {
            "generated_at": self._today_iso(),
            "portfolio_universe": portfolio_cards,
            "leaders": leaders,
            "laggards": laggards,
            "universe": {"portfolio": portfolio_symbols},
        }
        return self._cache_set(cache_key, payload)

    def build_symbol_card(self, symbol: str, period: str | None = None, include_news: bool = False) -> dict[str, Any]:
        symbol = self._normalize_symbol(symbol)
        period = (period or self.config.default_period).lower().strip()
        cache_key = ("symbol_card", symbol, period, bool(include_news))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            payload = self._build_page_payload(symbol=symbol, period=period, include_news=include_news)
            card = self._card_from_payload(symbol=symbol, payload=payload)
            return self._cache_set(cache_key, card)
        except Exception:
            pass

        try:
            card = self._build_lightweight_card(symbol=symbol, period=period)
            return self._cache_set(cache_key, card)
        except Exception as exc:
            return self._cache_set(cache_key, {"ticker": symbol, "name": symbol, "period": period, "error": str(exc)})

    def build_symbol_cards(self, symbols: list[str], period: str | None = None, include_news: bool = False) -> list[dict[str, Any]]:
        clean_symbols = self._safe_symbol_list(symbols)
        if not clean_symbols:
            return []

        period = (period or self.config.default_period).lower().strip()
        max_workers = max(1, min(self.config.max_workers, len(clean_symbols)))
        ordered_results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(self.build_symbol_card, sym, period, include_news): sym for sym in clean_symbols}
            for future in as_completed(future_map):
                sym = future_map[future]
                try:
                    ordered_results[sym] = future.result()
                except Exception as exc:
                    ordered_results[sym] = {"ticker": sym, "name": sym, "period": period, "error": str(exc)}
        return [ordered_results[sym] for sym in clean_symbols if sym in ordered_results]

    def get_top_news_feed(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        symbols = self._safe_symbol_list(symbols or self.config.home_news_symbols)
        cache_key = ("top_news", tuple(symbols))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        items: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                payload = self._build_page_payload(symbol=symbol, period="1m", include_news=True)
                identity = payload.get("identity", {})
                header = payload.get("header", {})
                news_items = payload.get("ranked_news") or payload.get("news") or []
                for news in news_items[: self.config.top_news_per_symbol]:
                    items.append(
                        {
                            "ticker": symbol,
                            "name": identity.get("name") or header.get("title") or symbol,
                            "title": news.get("title"),
                            "source": news.get("source"),
                            "url": news.get("url"),
                            "summary": self._short_text(news.get("summary"), 140),
                            "date": news.get("date"),
                            "score": news.get("score", 0.0),
                        }
                    )
            except Exception:
                continue

        deduped = self._dedupe_news(items)
        deduped.sort(key=lambda x: (x.get("score") or 0.0, x.get("date") or ""), reverse=True)
        return self._cache_set(cache_key, deduped[: self.config.top_news_limit])

    def _build_page_payload(self, symbol: str, period: str, include_news: bool) -> dict[str, Any]:
        if self.page_service is not None:
            builder_candidates: list[Callable[..., dict[str, Any]]] = []
            for name in ("build_fund_search_payload", "build_ticker_payload", "build_page_payload"):
                fn = getattr(self.page_service, name, None)
                if callable(fn):
                    builder_candidates.append(fn)

            for fn in builder_candidates:
                try:
                    return fn(symbol, period=period, include_news=include_news)
                except TypeError:
                    try:
                        return fn(symbol, period=period)
                    except TypeError:
                        return fn(symbol)

        if self.snapshot_engine is None:
            raise RuntimeError("No snapshot engine available for fallback payload generation.")

        snapshot = self.snapshot_engine.build_snapshot(symbol, include_news=include_news)
        chart = self.snapshot_engine.build_chart_payload(symbol, period=period)
        return self._fallback_payload_from_snapshot(snapshot=snapshot, chart=chart)

    def _fallback_payload_from_snapshot(self, snapshot: dict[str, Any], chart: dict[str, Any]) -> dict[str, Any]:
        price = snapshot.get("price", {})
        returns = snapshot.get("returns", {})
        risk = snapshot.get("risk", {})
        trend = snapshot.get("trend", {})
        fundamentals = snapshot.get("fundamentals", {})
        prev_close = price.get("prev_close")
        last_price = price.get("last_price")

        day_change = None
        day_change_pct = None
        if self._is_number(last_price) and self._is_number(prev_close) and prev_close not in (0, None):
            day_change = float(last_price) - float(prev_close)
            day_change_pct = day_change / float(prev_close)

        return {
            "identity": {
                "ticker": snapshot.get("ticker"),
                "name": snapshot.get("name"),
                "asset_type": snapshot.get("asset_type"),
                "description": snapshot.get("description"),
                "short_description": snapshot.get("short_description"),
                "long_description": snapshot.get("long_description"),
            },
            "header": {
                "title": f"{snapshot.get('name') or snapshot.get('ticker')} ({snapshot.get('ticker')})",
                "last_price": last_price,
                "day_change": day_change,
                "day_change_pct": day_change_pct,
                "trend_state": trend.get("trend_state"),
                "sector": fundamentals.get("sector"),
                "industry": fundamentals.get("industry"),
                "updated_at": snapshot.get("as_of"),
            },
            "chart": chart,
            "quick_stats": [
                {"label": "1M", "value": returns.get("return_1m"), "kind": "percent"},
                {"label": "YTD", "value": returns.get("return_ytd"), "kind": "percent"},
                {"label": "Beta", "value": risk.get("beta_1y"), "kind": "number"},
                {"label": "Vol", "value": risk.get("volatility_1y"), "kind": "percent"},
            ],
            "insight_panel": {
                "summary": snapshot.get("summary"),
                "about": snapshot.get("short_description") or snapshot.get("description"),
                "trend_bullets": [
                    {"label": "vs 50D MA", "value": trend.get("price_vs_ma50_pct"), "kind": "percent"},
                    {"label": "vs 200D MA", "value": trend.get("price_vs_ma200_pct"), "kind": "percent"},
                ],
            },
            "ranked_news": snapshot.get("news", []),
            "raw_snapshot": snapshot,
        }

    def _build_lightweight_card(self, symbol: str, period: str) -> dict[str, Any]:
        if self.snapshot_engine is None:
            raise RuntimeError("No snapshot engine available for lightweight card generation.")

        chart = self.snapshot_engine.build_chart_payload(symbol, period=period)
        if self._sparkline_is_too_flat(chart.get("close") or []):
            try:
                fallback_chart = self.snapshot_engine.build_chart_payload(symbol, period="1y")
                chart["dates"] = (fallback_chart.get("dates") or [])[-90:]
                chart["close"] = (fallback_chart.get("close") or [])[-90:]
            except Exception:
                pass
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=420)
        hist = self.snapshot_engine.provider.get_history(symbol=symbol, start_date=start_dt.isoformat(), end_date=end_dt.isoformat())
        hist = _normalize_history(hist)
        if hist.empty or "close" not in hist.columns:
            raise ValueError(f"No usable history returned for ticker: {symbol}")

        close = pd.to_numeric(hist["close"], errors="coerce").dropna()
        last_price = _safe_float(close.iloc[-1]) if not close.empty else None
        prev_close = _safe_float(close.iloc[-2]) if len(close) >= 2 else None
        day_change = (last_price - prev_close) if last_price is not None and prev_close not in (None, 0) else None
        day_change_pct = (day_change / prev_close) if day_change is not None and prev_close not in (None, 0) else None

        hist["ma_50"] = hist["close"].rolling(50).mean()
        hist["ma_200"] = hist["close"].rolling(200).mean()
        ma50 = _safe_float(hist["ma_50"].iloc[-1]) if not hist.empty else None
        ma200 = _safe_float(hist["ma_200"].iloc[-1]) if not hist.empty else None
        daily_returns = close.pct_change()

        ytd_return = None
        if "date" in hist.columns:
            current_year = pd.Timestamp(end_dt).year
            ytd_df = hist[hist["date"].dt.year == current_year]
            if len(ytd_df) >= 2:
                start_price = _safe_float(ytd_df["close"].iloc[0])
                end_price = _safe_float(ytd_df["close"].iloc[-1])
                if start_price not in (None, 0) and end_price is not None:
                    ytd_return = (end_price / start_price) - 1.0

        profile = {}
        try:
            profile = self.snapshot_engine.provider.get_profile(symbol) or {}
        except Exception:
            profile = {}

        description = profile.get("short_description") or profile.get("long_description") or profile.get("industry_category") or profile.get("sector") or "Live market card"

        return {
            "ticker": symbol,
            "name": self._resolve_name(symbol, profile.get("name") or symbol),
            "asset_type": profile.get("issue_type"),
            "description": self._short_text(description, 110),
            "last_price": last_price or chart.get("last_price"),
            "day_change": day_change,
            "day_change_pct": day_change_pct,
            "return_1m": _pct_return(close, TRADING_DAYS_1M),
            "return_3m": _pct_return(close, 63),
            "return_ytd": ytd_return,
            "return_1y": _pct_return(close, min(TRADING_DAYS_PER_YEAR, max(len(close) - 1, 0))),
            "volatility_1y": _annualized_volatility(daily_returns),
            "beta_1y": _safe_float(profile.get("beta")),
            "sharpe_1y": None,
            "max_drawdown_1y": None,
            "trend_state": self._ensure_trend_state(symbol, _trend_state(last_price, ma50, ma200)),
            "sector": self._resolve_sector(symbol, profile.get("sector")),
            "industry": profile.get("industry_category"),
            "market_cap": _safe_float(profile.get("market_cap")),
            "support": chart.get("support"),
            "resistance": chart.get("resistance"),
            "updated_at": end_dt.isoformat(),
            "sparkline": self._build_payload_sparkline(symbol, chart),
            "sparkline_label": "1M price path",
            "chart_period": chart.get("period"),
            "headline": None,
            "raw_payload": {"chart": chart},
        }

    def _card_from_payload(self, symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
        identity = payload.get("identity", {})
        header = payload.get("header", {})
        chart = payload.get("chart", {})
        raw_snapshot = payload.get("raw_snapshot", {})
        returns = raw_snapshot.get("returns", {})
        risk = raw_snapshot.get("risk", {})
        fundamentals = raw_snapshot.get("fundamentals", {})

        day_change = header.get("day_change")
        day_change_pct = header.get("day_change_pct")
        if day_change is None or day_change_pct is None:
            price = raw_snapshot.get("price", {})
            last_price = price.get("last_price")
            prev_close = price.get("prev_close")
            if self._is_number(last_price) and self._is_number(prev_close) and prev_close not in (0, None):
                day_change = float(last_price) - float(prev_close)
                day_change_pct = day_change / float(prev_close)

        description = identity.get("short_description") or identity.get("description") or fundamentals.get("industry") or fundamentals.get("sector") or "Live market card"

        return {
            "ticker": identity.get("ticker") or symbol,
            "name": self._resolve_name(symbol, identity.get("name") or symbol),
            "asset_type": identity.get("asset_type"),
            "description": self._short_text(description, 120),
            "last_price": header.get("last_price") or chart.get("last_price"),
            "day_change": day_change,
            "day_change_pct": day_change_pct,
            "return_1m": returns.get("return_1m"),
            "return_3m": returns.get("return_3m"),
            "return_ytd": returns.get("return_ytd"),
            "return_1y": returns.get("return_1y"),
            "volatility_1y": risk.get("volatility_1y"),
            "beta_1y": risk.get("beta_1y"),
            "sharpe_1y": risk.get("sharpe_1y"),
            "max_drawdown_1y": risk.get("max_drawdown_1y"),
            "trend_state": self._ensure_trend_state(symbol, header.get("trend_state") or raw_snapshot.get("trend", {}).get("trend_state")),
            "sector": self._resolve_sector(symbol, header.get("sector") or fundamentals.get("sector")),
            "industry": header.get("industry") or fundamentals.get("industry"),
            "market_cap": fundamentals.get("market_cap"),
            "support": chart.get("support"),
            "resistance": chart.get("resistance"),
            "updated_at": header.get("updated_at"),
            "sparkline": self._build_payload_sparkline(symbol, chart),
            "sparkline_label": "1M price path",
            "chart_period": chart.get("period"),
            "headline": self._select_headline(payload),
            "raw_payload": payload,
        }

    def _build_preferred_sparkline(self, symbol: str, hist: pd.DataFrame) -> dict[str, list[Any]]:
        if hist.empty or "date" not in hist.columns or "close" not in hist.columns:
            return {"dates": [], "close": []}
        dates = hist["date"].dt.strftime("%Y-%m-%d").tolist()
        closes = pd.to_numeric(hist["close"], errors="coerce").tolist()
        spark = self._sanitize_sparkline(dates, closes, window=75)
        if self._sparkline_is_too_flat(spark.get("close") or []):
            spark = self._sanitize_sparkline(dates, closes, window=180)
        return spark

    def _build_payload_sparkline(self, symbol: str, chart: dict[str, Any]) -> dict[str, list[Any]]:
        spark = self._sanitize_sparkline(chart.get("dates") or [], chart.get("close") or [], window=75)
        if not self._sparkline_is_too_flat(spark.get("close") or []):
            return spark
        if self.snapshot_engine is None:
            return spark
        try:
            end_dt = date.today()
            start_dt = end_dt - timedelta(days=540)
            hist = self.snapshot_engine.provider.get_history(symbol=symbol, start_date=start_dt.isoformat(), end_date=end_dt.isoformat())
            hist = _normalize_history(hist)
            if hist.empty:
                return spark
            return self._build_preferred_sparkline(symbol, hist)
        except Exception:
            return spark

    def _rank_cards_by_return(self, cards: list[dict[str, Any]], metric: str = "day_change_pct", directional: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        valid = [card for card in cards if self._is_number(card.get(metric))]
        valid.sort(key=lambda x: float(x.get(metric)), reverse=True)

        if not directional:
            leaders = valid[: self.config.leaders_count]
            laggards = list(reversed(valid[-self.config.laggards_count :]))
            return leaders, laggards

        positives = [card for card in valid if float(card.get(metric)) >= 0]
        negatives = [card for card in valid if float(card.get(metric)) < 0]

        def extend_unique(seed: list[dict[str, Any]], pool: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
            out = list(seed)
            seen = {self._normalize_symbol(card.get("ticker", "")) for card in out}
            for card in pool:
                key = self._normalize_symbol(card.get("ticker", ""))
                if not key or key in seen:
                    continue
                out.append(card)
                seen.add(key)
                if len(out) >= target:
                    break
            return out[:target]

        leaders = extend_unique(positives[: self.config.leaders_count], valid, self.config.leaders_count)
        laggards_seed = list(reversed(negatives[-self.config.laggards_count :]))
        laggards = extend_unique(laggards_seed, list(reversed(valid)), self.config.laggards_count)
        return leaders, laggards

    def _select_cards_from_candidates(self, cards: list[dict[str, Any]], candidates: list[str], metric: str, count: int) -> list[dict[str, Any]]:
        candidate_set = {self._normalize_symbol(x) for x in candidates}
        pool = [card for card in cards if self._normalize_symbol(card.get("ticker", "")) in candidate_set and self._is_number(card.get(metric))]
        pool.sort(key=lambda x: float(x.get(metric)), reverse=True)
        selected = pool[:count]
        if len(selected) < count:
            seen = {self._normalize_symbol(card.get("ticker", "")) for card in selected}
            supplements = [card for card in cards if self._is_number(card.get(metric)) and self._normalize_symbol(card.get("ticker", "")) not in seen]
            supplements.sort(key=lambda x: float(x.get(metric)), reverse=True)
            for card in supplements:
                selected.append(card)
                seen.add(self._normalize_symbol(card.get("ticker", "")))
                if len(selected) >= count:
                    break
        return selected[:count]

    def _build_trend_table(self, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for card in cards:
            rows.append(
                {
                    "ticker": card.get("ticker"),
                    "name": self._resolve_name(card.get("ticker"), card.get("name")),
                    "last_price": card.get("last_price"),
                    "day_change_pct": card.get("day_change_pct"),
                    "return_1m": card.get("return_1m"),
                    "return_ytd": card.get("return_ytd"),
                    "beta_1y": card.get("beta_1y"),
                    "volatility_1y": card.get("volatility_1y"),
                    "trend_state": card.get("trend_state"),
                    "sector": self._resolve_sector(card.get("ticker"), card.get("sector")),
                }
            )
        rows.sort(key=lambda x: (self._trend_rank(x.get("trend_state")), -(float(x["return_1m"]) if self._is_number(x.get("return_1m")) else -999.0)))
        return rows

    def _build_index_comparison(self, symbols: list[str]) -> list[dict[str, Any]]:
        if self.snapshot_engine is None:
            return []
        out: list[dict[str, Any]] = []
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=365 * 3 + 45)
        for symbol in self._safe_symbol_list(symbols):
            try:
                hist = self.snapshot_engine.provider.get_history(symbol=symbol, start_date=start_dt.isoformat(), end_date=end_dt.isoformat())
                hist = _normalize_history(hist)
                if hist.empty or "date" not in hist.columns or "close" not in hist.columns:
                    continue
                hist = hist.dropna(subset=["date", "close"]).copy()
                if len(hist) < 30:
                    continue
                out.append({
                    "ticker": symbol,
                    "label": self._resolve_name(symbol, symbol),
                    "dates": hist["date"].dt.strftime("%Y-%m-%d").tolist(),
                    "close": [_safe_float(v) for v in hist["close"].tolist()],
                })
            except Exception:
                continue
        return out

    def _build_markets_dashboard(
        self,
        index_cards: list[dict[str, Any]],
        sector_cards: list[dict[str, Any]],
        risk_board: dict[str, list[dict[str, Any]]],
        leaders: list[dict[str, Any]],
        laggards: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        avg = self._avg_metric
        positives_ytd = sum(1 for card in sector_cards if self._is_number(card.get("return_ytd")) and float(card.get("return_ytd")) > 0)
        cards = [
            {"label": "S&P 500 Index", "value": self._fmt_pct_value(self._lookup_card_metric(index_cards, "^SPX", "day_change_pct")), "note": "Today"},
            {"label": "Risk On", "value": self._fmt_pct_value(avg(risk_board.get("risk_on", []), "return_1m")), "note": "Avg 1M"},
            {"label": "Risk Off", "value": self._fmt_pct_value(avg(risk_board.get("risk_off", []), "return_1m")), "note": "Avg 1M"},
            {"label": "Sector Breadth", "value": f"{positives_ytd}/{len(sector_cards)}", "note": "Positive YTD sectors"},
            {"label": "Best Mover", "value": self._fmt_card_move(leaders[0], 'day_change_pct') if leaders else "N/A", "note": leaders[0].get("ticker") if leaders else "Broad market"},
            {"label": "Worst Mover", "value": self._fmt_card_move(laggards[0], 'day_change_pct') if laggards else "N/A", "note": laggards[0].get("ticker") if laggards else "Broad market"},
        ]
        # Append BLS macro KPIs from enrichment.json (written by fetch_enrichment.py)
        try:
            enrichment_path = _DATA_DIR / "enrichment.json"
            fred = json.loads(enrichment_path.read_text(encoding="utf-8")).get("fred_proxies", {})
            unemp = fred.get("unemployment_rate", {})
            cpi   = fred.get("cpi_yoy", {})
            nfp   = fred.get("nonfarm_payrolls", {})
            if unemp.get("value") is not None:
                cards.append({"label": "Unemployment Rate", "value": f"{unemp['value']:.1f}%", "note": f"As of {unemp.get('date', 'latest')}"})
            if cpi.get("value") is not None:
                cards.append({"label": "CPI Inflation YoY", "value": f"{cpi['value']:.1f}%", "note": f"As of {cpi.get('date', 'latest')}"})
            if nfp.get("value") is not None:
                cards.append({"label": "Nonfarm Payrolls", "value": f"{nfp['value']:,.0f}K", "note": f"Total as of {nfp.get('date', 'latest')}"})
        except Exception:
            pass
        return cards

    def _build_markets_read(
        self,
        index_cards: list[dict[str, Any]],
        sector_cards: list[dict[str, Any]],
        risk_board: dict[str, list[dict[str, Any]]],
        leaders: list[dict[str, Any]],
        laggards: list[dict[str, Any]],
        trend_table: list[dict[str, Any]],
    ) -> dict[str, Any]:
        avg = self._avg_metric
        avg_risk_on = avg(risk_board.get("risk_on", []), "day_change_pct")
        avg_risk_off = avg(risk_board.get("risk_off", []), "day_change_pct")
        spy_move = self._lookup_card_metric(index_cards, "SPY", "day_change_pct")
        if self._is_number(avg_risk_on) and self._is_number(avg_risk_off):
            if float(avg_risk_on) >= float(avg_risk_off) and (not self._is_number(spy_move) or float(spy_move) > -0.01):
                regime = "Risk-on tilt"
            else:
                regime = "Risk-off tilt"
        else:
            regime = "Mixed backdrop"

        sector_leaders, sector_laggards = self._rank_cards_by_return(sector_cards, metric="return_ytd", directional=True)
        day_up = sum(1 for row in trend_table if self._is_number(row.get("day_change_pct")) and float(row.get("day_change_pct")) > 0)
        lead_text = ", ".join(self._card_label_text(card, "day_change_pct") for card in leaders[:3]) or "N/A"
        lag_text = ", ".join(self._card_label_text(card, "day_change_pct") for card in laggards[:3]) or "N/A"
        sector_text = ", ".join(self._card_label_text(card, "return_ytd") for card in sector_leaders[:3]) or "N/A"
        sector_lag_text = ", ".join(self._card_label_text(card, "return_ytd") for card in sector_laggards[:3]) or "N/A"
        index_moves = []
        for card in index_cards[:3]:
            move = self._fmt_pct_value(card.get("day_change_pct"))
            index_moves.append(f"{card.get('name') or card.get('ticker')} {move}")
        return {
            "regime": regime,
            "indices": "; ".join(index_moves) or "Index snapshot unavailable.",
            "leaders": lead_text,
            "laggards": lag_text,
            "sector_leaders": sector_text,
            "sector_laggards": sector_lag_text,
            "breadth": f"{day_up}/{len(trend_table)} names in the trend table are positive today.",
            "risk_on_vs_off": f"Risk-on basket avg day move {self._fmt_pct_value(avg_risk_on)} versus {self._fmt_pct_value(avg_risk_off)} for the defensive basket.",
        }

    @staticmethod
    def _avg_metric(cards: list[dict[str, Any]], field: str) -> float | None:
        nums = [float(card.get(field)) for card in cards if MarketBoardService._is_number(card.get(field))]
        return (sum(nums) / len(nums)) if nums else None

    @staticmethod
    def _fmt_pct_value(value: Any) -> str:
        if not MarketBoardService._is_number(value):
            return "N/A"
        num = float(value) * 100.0
        return f"{num:+.2f}%"

    @staticmethod
    def _lookup_card_metric(cards: list[dict[str, Any]], ticker: str, field: str) -> Any:
        target = MarketBoardService._normalize_symbol(ticker)
        for card in cards:
            if MarketBoardService._normalize_symbol(card.get("ticker", "")) == target:
                return card.get(field)
        return None

    def _fmt_card_move(self, card: dict[str, Any] | None, field: str) -> str:
        if not card:
            return "N/A"
        return self._fmt_pct_value(card.get(field))

    def _card_label_text(self, card: dict[str, Any], field: str) -> str:
        ticker = str(card.get("ticker") or "").strip() or "—"
        return f"{ticker} ({self._fmt_pct_value(card.get(field))})"

    def _load_portfolio_symbols(self) -> list[str]:
        if callable(get_portfolio_tickers):
            try:
                values = list(get_portfolio_tickers())
                if values:
                    return values
            except Exception:
                pass
        return ["BUFR", "CGDV", "FLQM", "AUSF", "DIVO", "IXJ", "JAAA", "EFAA", "PFF", "XNTK", "RLY"]

    def _load_mag7(self) -> list[str]:
        if callable(get_mag7):
            try:
                return list(get_mag7())
            except Exception:
                pass
        return ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]

    def _load_index_symbols(self) -> list[str]:
        # Keep the monitored headline index strip aligned across Home and Markets.
        # This intentionally uses headline indexes only, not duplicate ETF proxies.
        desired = self._safe_symbol_list(self.config.index_symbols)
        return desired[:7] if desired else ["^SPX", "^NDX", "^DJI", "^STOXX50E", "000001.SS", "^N225", "^KS11"]

    def _load_universe_or_default(self, name: str, default: list[str]) -> list[str]:
        if name == "home_market_strip":
            loaded = self._load_index_symbols()
            return loaded[:7] if loaded else list(default)
        return list(default)

    @staticmethod
    def _select_headline(payload: dict[str, Any]) -> dict[str, Any] | None:
        for key in ("ranked_news", "news"):
            items = payload.get(key) or []
            if items:
                first = items[0]
                return {
                    "title": first.get("title"),
                    "source": first.get("source"),
                    "url": first.get("url"),
                    "summary": first.get("summary"),
                    "date": first.get("date"),
                    "score": first.get("score"),
                }
        return None

    def _ensure_trend_state(self, symbol: str, current: Any) -> str:
        value = str(current or "").strip().lower()
        if value and value != "unknown":
            return value
        if self.snapshot_engine is None:
            return "unknown"
        try:
            end_dt = date.today()
            start_dt = end_dt - timedelta(days=420)
            hist = self.snapshot_engine.provider.get_history(
                symbol=symbol,
                start_date=start_dt.isoformat(),
                end_date=end_dt.isoformat(),
            )
            hist = _normalize_history(hist)
            if hist.empty or "close" not in hist.columns:
                return "unknown"
            close = pd.to_numeric(hist["close"], errors="coerce")
            if close.dropna().shape[0] < 200:
                return "unknown"
            ma50 = _safe_float(close.rolling(50).mean().iloc[-1])
            ma200 = _safe_float(close.rolling(200).mean().iloc[-1])
            last_price = _safe_float(close.dropna().iloc[-1]) if not close.dropna().empty else None
            return _trend_state(last_price, ma50, ma200)
        except Exception:
            return "unknown"

    @staticmethod
    def _trend_rank(value: str | None) -> int:
        order = {"strong_uptrend": 0, "uptrend": 1, "mixed": 2, "downtrend": 3, "strong_downtrend": 4, "unknown": 5}
        return order.get(str(value or "unknown"), 5)

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        value = str(symbol).replace("M:", "").strip().upper().replace(" ", "")
        if re.fullmatch(r"[A-Z]{1,5}-[A-Z]", value):
            return value.replace("-", ".")
        return value

    @staticmethod
    def _safe_symbol_list(symbols: list[str] | tuple[str, ...] | None) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in symbols or []:
            value = MarketBoardService._normalize_symbol(raw)
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    @staticmethod
    def _dedupe_news(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for item in items:
            key = f"{str(item.get('ticker', '')).lower()}::{str(item.get('title', '')).strip().lower()}"
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    @staticmethod
    def _sanitize_sparkline(dates: list[Any], close: list[Any], window: int = 45) -> dict[str, list[Any]]:
        paired: list[tuple[Any, float]] = []
        prev: float | None = None
        for d, value in zip(dates, close):
            num = _safe_float(value)
            if num is None or num <= 0:
                continue
            if prev not in (None, 0) and abs((num / prev) - 1.0) > 0.45:
                num = prev
            paired.append((d, num))
            prev = num
        if not paired:
            return {"dates": [], "close": []}
        trimmed = paired[-window:]
        return {"dates": [d for d, _ in trimmed], "close": [v for _, v in trimmed]}

    @staticmethod
    def _sparkline_is_too_flat(close: list[Any]) -> bool:
        nums = [float(v) for v in close if MarketBoardService._is_number(v)]
        if len(nums) < 5:
            return True
        unique = len({round(v, 4) for v in nums})
        if unique < 4:
            return True
        low, high = min(nums), max(nums)
        if low <= 0:
            return False
        return ((high / low) - 1.0) < 0.003



    def _decorate_index_cards(self, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for card in cards:
            updated = dict(card)
            symbol = self._normalize_symbol(updated.get("ticker", ""))
            updated["name"] = self._resolve_name(symbol, updated.get("name") or symbol)
            updated["ticker_label"] = ""
            out.append(updated)
        return out

    def _resolve_name(self, symbol: Any, raw_name: Any) -> str:
        clean_symbol = self._normalize_symbol(str(symbol or ""))
        clean_name = str(raw_name or "").strip()
        override = DISPLAY_NAME_OVERRIDES.get(clean_symbol)
        if override:
            return override
        if clean_name and clean_name not in {clean_symbol, "N/A", "None", "null"}:
            return clean_name
        return SECTOR_OVERRIDES.get(clean_symbol) or clean_symbol


    def _load_broad_market_movers(self, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        provider = getattr(getattr(self.snapshot_engine, 'provider', None), 'get_market_movers', None)
        if not callable(provider):
            return [], []
        try:
            payload = provider(limit=max(5, int(limit or 5))) or {}
        except Exception:
            return [], []

        def normalize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for row in rows or []:
                ticker = self._normalize_symbol(row.get('ticker') or row.get('symbol') or '')
                if not ticker:
                    continue
                name = self._resolve_name(ticker, row.get('name') or ticker)
                try:
                    pct = float(row.get('day_change_pct')) if row.get('day_change_pct') is not None else None
                except Exception:
                    pct = None
                out.append({
                    'ticker': ticker,
                    'name': name,
                    'last_price': _safe_float(row.get('last_price')),
                    'day_change': _safe_float(row.get('day_change')),
                    'day_change_pct': pct,
                    'period': '1d',
                    'description': self._short_text(name, 110),
                })
            return out

        return normalize(payload.get('gainers') or []), normalize(payload.get('losers') or [])

    def _build_sector_rotation_data(self, sector_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for card in sector_cards:
            value = card.get("return_ytd")
            if not self._is_number(value):
                continue
            rows.append({
                "ticker": card.get("ticker"),
                "name": self._resolve_sector(card.get("ticker"), card.get("sector")) or card.get("name") or card.get("ticker"),
                "value": float(value) * 100.0,
            })
        rows.sort(key=lambda row: row["value"])
        return rows

    def _build_macro_lens_charts(self) -> dict[str, Any]:
        if self.snapshot_engine is None:
            return {}
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=430)

        def load_series(symbol: str) -> dict[str, list[Any]] | None:
            try:
                hist = self.snapshot_engine.provider.get_history(symbol=symbol, start_date=start_dt.isoformat(), end_date=end_dt.isoformat())
                hist = _normalize_history(hist)
                if hist.empty or "date" not in hist.columns or "close" not in hist.columns:
                    return None
                hist = hist.dropna(subset=["date", "close"]).copy()
                if len(hist) < 20:
                    return None
                hist["close"] = pd.to_numeric(hist["close"], errors="coerce")
                hist = hist.dropna(subset=["close"]).copy()
                dates = hist["date"].dt.strftime("%Y-%m-%d").tolist()
                close = [float(v) for v in hist["close"].tolist()]
                return {"dates": dates, "close": close}
            except Exception:
                return None

        def load_first(symbols: list[str]) -> dict[str, list[Any]] | None:
            for symbol in symbols:
                series = load_series(symbol)
                if series:
                    return series
            return None

        def rebase(series: dict[str, list[Any]] | None) -> dict[str, list[Any]] | None:
            if not series:
                return None
            close = [float(v) for v in series["close"] if v is not None]
            if len(close) < 2:
                return None
            base = close[0] or 1.0
            return {"dates": series["dates"][:len(close)], "close": [((v / base) - 1.0) * 100.0 for v in close]}

        return {
            "equity_risk": {
                "SPY": load_series("SPY"),
                "VIX": load_series("^VIX"),
            },
            "rates_credit": {
                "10Y": load_series("^TNX"),
                "HYG": self._rebase_series(load_series("HYG")),
                "IEF": self._rebase_series(load_series("IEF")),
                "LQD": self._rebase_series(load_series("LQD")),
            },
            "dollar_commodities": self._build_dollar_commodities_series(load_first),
        }


    @staticmethod
    def _rebase_series(series: dict[str, list[Any]] | None) -> dict[str, list[Any]] | None:
        if not series:
            return None
        dates = list(series.get("dates") or [])
        raw_close = list(series.get("close") or [])
        paired: list[tuple[str, float]] = []
        for d, v in zip(dates, raw_close):
            try:
                if v is None:
                    continue
                paired.append((str(d), float(v)))
            except Exception:
                continue
        if len(paired) < 2:
            return None
        base = paired[0][1] or 1.0
        return {"dates": [d for d, _ in paired], "close": [((v / base) - 1.0) * 100.0 for _, v in paired]}

    def _build_dollar_commodities_series(self, load_first: Callable[[list[str]], dict[str, list[Any]] | None]) -> dict[str, Any]:
        series_map: dict[str, Any] = {}
        inputs = [
            ("Dollar purchasing power (DXY)", ["DX-Y.NYB", "DX=F", "UUP"], False),
            ("Gold spot", ["GC=F", "GLD"], True),
            ("Silver spot", ["SI=F", "SLV"], True),
            ("Copper", ["HG=F", "CPER", "DBB"], True),
            ("WTI crude", ["CL=F", "USO"], True),
            ("Broad commodities", ["DBC", "GSG"], True),
        ]
        for label, symbols, append_price in inputs:
            series = load_first(symbols)
            rebased = self._rebase_series(series)
            if not rebased:
                continue
            final_label = label
            if append_price and series and series.get("close"):
                last = _safe_float(series["close"][-1])
                if last is not None:
                    final_label = f"{label} (${last:,.2f})"
            series_map[final_label] = rebased
        return series_map

    @staticmethod
    def _resolve_sector(symbol: Any, sector: Any) -> str | None:
        clean = str(sector or "").strip()
        if clean and clean not in {"—", "N/A", "None", "null"}:
            return clean
        return SECTOR_OVERRIDES.get(MarketBoardService._normalize_symbol(str(symbol or "")))

    @staticmethod
    def _is_number(value: Any) -> bool:
        try:
            return value is not None and pd.notna(value)
        except Exception:
            return False

    @staticmethod
    def _today_iso() -> str:
        return date.today().isoformat()

    @staticmethod
    def _short_text(value: Any, max_len: int = 160) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_len:
            return text
        return text[: max_len - 1].rstrip() + "…"

    def _cache_get(self, key: tuple[Any, ...]) -> Any | None:
        ttl = max(int(self.config.cache_ttl_seconds), 0)
        if ttl <= 0:
            return None
        with self._cache_lock:
            hit = self._cache.get(key)
            if not hit:
                return None
            expires_at, value = hit
            if expires_at < time():
                self._cache.pop(key, None)
                return None
            return value

    def _cache_set(self, key: tuple[Any, ...], value: Any) -> Any:
        ttl = max(int(self.config.cache_ttl_seconds), 0)
        if ttl > 0:
            with self._cache_lock:
                self._cache[key] = (time() + ttl, value)
        return value
