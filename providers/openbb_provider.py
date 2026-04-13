from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from threading import RLock
from time import time
import re
from typing import Any

import pandas as pd


@dataclass
class OpenBBProviderConfig:
    price_provider: str = "yfinance"
    profile_provider: str = "yfinance"
    news_provider: str | None = None
    cache_ttl_seconds: int = 900


class OpenBBProvider:
    """Thin wrapper around OpenBB with graceful fallbacks.

    The app should be importable even when optional data packages are not
    installed. Live requests will still use OpenBB/yfinance whenever they are
    available in the user's environment.
    """

    def __init__(self, config: OpenBBProviderConfig | None = None) -> None:
        self.config = config or OpenBBProviderConfig()
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._cache_lock = RLock()
        self.obb = self._try_import_openbb()

    @staticmethod
    def _try_import_openbb() -> Any | None:
        try:
            from openbb import obb  # type: ignore
            return obb
        except Exception:
            return None

    @staticmethod
    def _try_import_yfinance() -> Any | None:
        try:
            import yfinance as yf  # type: ignore
            return yf
        except Exception:
            return None

    @staticmethod
    def _result_to_dict(item: Any) -> dict[str, Any]:
        if item is None:
            return {}
        if isinstance(item, dict):
            return item
        if hasattr(item, "model_dump"):
            return item.model_dump()
        if hasattr(item, "__dict__"):
            return dict(item.__dict__)
        return {"value": item}

    def _response_results(self, response: Any) -> list[dict[str, Any]]:
        results = getattr(response, "results", None)
        if not results:
            return []
        return [self._result_to_dict(x) for x in results]

    @staticmethod
    def _pick_first(mapping: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = mapping.get(key)
            if value not in (None, "", "N/A", "None", "null"):
                return value
        return None

    @staticmethod
    def _nested_pick(mapping: dict[str, Any] | None, *keys: str) -> Any:
        base = mapping or {}
        for key in keys:
            value = base.get(key)
            if value not in (None, "", "N/A", "None", "null"):
                return value
        return None

    @staticmethod
    def _merge_dicts(*parts: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for part in parts:
            if isinstance(part, dict):
                out.update(part)
        return out
    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        value = str(symbol or "").strip().upper()
        if not value:
            return ""
        if "." in value and value.count(".") == 1:
            base, suffix = value.split(".", 1)
            if re.fullmatch(r"[A-Z]{1,5}", base) and re.fullmatch(r"[A-Z]", suffix):
                return f"{base}.{suffix}"
        if "-" in value and value.count("-") == 1:
            base, suffix = value.split("-", 1)
            if re.fullmatch(r"[A-Z]{1,5}", base) and re.fullmatch(r"[A-Z]", suffix):
                return f"{base}.{suffix}"
        return value

    @classmethod
    def _symbol_variants(cls, symbol: str) -> list[str]:
        value = cls._normalize_symbol(symbol)
        if not value:
            return []
        variants = [value]
        if "." in value and value.count(".") == 1:
            base, suffix = value.split(".", 1)
            if re.fullmatch(r"[A-Z]{1,5}", base) and re.fullmatch(r"[A-Z]", suffix):
                variants.append(f"{base}-{suffix}")
        elif "-" in value and value.count("-") == 1:
            base, suffix = value.split("-", 1)
            if re.fullmatch(r"[A-Z]{1,5}", base) and re.fullmatch(r"[A-Z]", suffix):
                variants.append(f"{base}.{suffix}")
        dedup: list[str] = []
        seen: set[str] = set()
        for candidate in variants:
            if candidate and candidate not in seen:
                seen.add(candidate)
                dedup.append(candidate)
        return dedup

    def _normalize_profile_payload(self, raw: dict[str, Any], symbol: str) -> dict[str, Any]:
        pick = lambda *keys: self._pick_first(raw, *keys)
        summary_profile = raw.get("summaryProfile") if isinstance(raw.get("summaryProfile"), dict) else {}
        asset_profile = raw.get("assetProfile") if isinstance(raw.get("assetProfile"), dict) else {}
        quote_summary = raw.get("quoteSummary") if isinstance(raw.get("quoteSummary"), dict) else {}
        summary_detail = raw.get("summaryDetail") if isinstance(raw.get("summaryDetail"), dict) else {}
        default_stats = raw.get("defaultKeyStatistics") if isinstance(raw.get("defaultKeyStatistics"), dict) else {}
        fund_profile = raw.get("fundProfile") if isinstance(raw.get("fundProfile"), dict) else {}
        price_block = raw.get("price") if isinstance(raw.get("price"), dict) else {}

        description = (
            pick("long_description", "description", "business_summary", "longBusinessSummary", "longBusinessDescription", "fundOverview")
            or self._nested_pick(asset_profile, "longBusinessSummary", "description")
            or self._nested_pick(summary_profile, "longBusinessSummary", "description", "longDescription", "shortDescription")
            or self._nested_pick(quote_summary, "longBusinessSummary", "description")
            or self._nested_pick(fund_profile, "fundOverview")
        )
        sector = (
            pick("sector", "category", "sector_name", "gics_sector")
            or self._nested_pick(asset_profile, "sector")
            or self._nested_pick(summary_profile, "sector")
            or self._nested_pick(fund_profile, "categoryName", "category")
        )
        industry = (
            pick("industry_category", "industry", "industry_group", "fundFamily", "gics_industry", "industry_title")
            or self._nested_pick(asset_profile, "industry")
            or self._nested_pick(summary_profile, "industry")
            or self._nested_pick(fund_profile, "family")
        )
        employees = (
            pick("employees", "fullTimeEmployees", "full_time_employees", "employee_count")
            or self._nested_pick(asset_profile, "fullTimeEmployees")
            or self._nested_pick(summary_profile, "fullTimeEmployees")
        )
        return {
            "name": pick("name", "company_name", "title", "shortName", "longName")
            or self._nested_pick(price_block, "shortName", "longName")
            or symbol,
            "long_description": description,
            "short_description": pick("short_description", "summary", "shortDescription")
            or self._nested_pick(asset_profile, "longBusinessSummary")
            or self._nested_pick(summary_profile, "shortDescription")
            or self._nested_pick(fund_profile, "fundOverview")
            or description,
            "sector": sector,
            "industry_category": industry,
            "market_cap": pick("market_cap", "marketCap", "totalAssets")
            or self._nested_pick(price_block, "marketCap")
            or self._nested_pick(default_stats, "marketCap", "totalAssets")
            or self._nested_pick(summary_detail, "marketCap")
            or self._nested_pick(fund_profile, "totalAssets"),
            "employees": employees,
            "dividend_yield": pick("dividend_yield", "dividendYield", "yield")
            or self._nested_pick(summary_detail, "dividendYield", "yield")
            or self._nested_pick(fund_profile, "yield"),
            "shares_outstanding": pick("shares_outstanding", "sharesOutstanding", "share_class_shares_outstanding")
            or self._nested_pick(default_stats, "sharesOutstanding")
            or self._nested_pick(price_block, "sharesOutstanding"),
            "beta": pick("beta", "beta3Year")
            or self._nested_pick(default_stats, "beta", "beta3Year")
            or self._nested_pick(summary_detail, "beta"),
            "currency": pick("currency") or self._nested_pick(price_block, "currency"),
            "issue_type": pick("issue_type", "quoteType", "typeDisp", "asset_type")
            or self._nested_pick(price_block, "quoteType")
            or self._nested_pick(default_stats, "quoteType"),
        }

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

    @staticmethod
    def _normalize_download(raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        out = raw.copy()
        if isinstance(out.columns, pd.MultiIndex):
            out.columns = [c[0] if isinstance(c, tuple) else c for c in out.columns]
        out = out.reset_index()
        out.columns = [str(c).lower() for c in out.columns]
        out = out.rename(columns={"adj close": "adj_close"})
        if "date" not in out.columns and "datetime" in out.columns:
            out = out.rename(columns={"datetime": "date"})
        if "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"], errors="coerce", utc=True).dt.tz_localize(None)
            out = out.sort_values("date").reset_index(drop=True)
        return out

    @staticmethod
    def _suppress_yf_call(fn):
        sink = StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            return fn()

    def _yfinance_history(
        self,
        symbol: str,
        *,
        period: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        yf = self._try_import_yfinance()
        if yf is None:
            return pd.DataFrame()

        symbol = self._normalize_symbol(symbol)
        symbol_variants = self._symbol_variants(symbol)

        def via_ticker_history(candidate_symbol: str) -> pd.DataFrame:
            ticker = yf.Ticker(candidate_symbol)
            kwargs: dict[str, Any] = {"interval": interval, "auto_adjust": False}
            if period:
                kwargs["period"] = period
            else:
                kwargs["start"] = start_date
                kwargs["end"] = end_date
            raw = self._suppress_yf_call(lambda: ticker.history(**kwargs))
            return self._normalize_download(raw)

        def via_download(candidate_symbol: str) -> pd.DataFrame:
            kwargs: dict[str, Any] = {
                "tickers": candidate_symbol,
                "interval": interval,
                "auto_adjust": False,
                "progress": False,
                "threads": False,
            }
            if period:
                kwargs["period"] = period
            else:
                kwargs["start"] = start_date
                kwargs["end"] = end_date
            raw = self._suppress_yf_call(lambda: yf.download(**kwargs))
            return self._normalize_download(raw)

        for candidate_symbol in symbol_variants or [symbol]:
            for candidate in (via_ticker_history, via_download):
                try:
                    df = candidate(candidate_symbol)
                    if not df.empty:
                        return df
                except Exception:
                    continue
        return pd.DataFrame()

    def get_quote(self, symbol: str) -> dict[str, Any]:
        symbol = self._normalize_symbol(symbol)
        cache_key = ("quote", symbol)
        symbol_variants = self._symbol_variants(symbol)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        if self.obb is not None:
            try:
                for candidate_symbol in symbol_variants or [symbol]:
                    response = self.obb.equity.price.quote(symbol=candidate_symbol, provider=self.config.price_provider)
                    rows = self._response_results(response)
                    if rows:
                        row = rows[0]
                        row.setdefault("symbol", symbol)
                        row.setdefault("name", row.get("name") or symbol)
                        return self._cache_set(cache_key, row)
            except Exception:
                pass

        yf = self._try_import_yfinance()
        if yf is not None:
            try:
                for candidate_symbol in symbol_variants or [symbol]:
                    ticker = yf.Ticker(candidate_symbol)
                    fast = getattr(ticker, "fast_info", None) or {}
                    info = self._suppress_yf_call(lambda: ticker.info) or {}
                    quote = {
                    "symbol": symbol,
                    "name": info.get("shortName") or info.get("longName") or symbol,
                    "prev_close": fast.get("previousClose") or info.get("previousClose") or info.get("regularMarketPreviousClose"),
                    "open": fast.get("open") or info.get("open") or info.get("regularMarketOpen"),
                    "high": fast.get("dayHigh") or info.get("dayHigh") or info.get("regularMarketDayHigh"),
                    "low": fast.get("dayLow") or info.get("dayLow") or info.get("regularMarketDayLow"),
                    "volume": fast.get("lastVolume") or info.get("volume") or info.get("regularMarketVolume"),
                    "currency": info.get("currency"),
                    "year_high": fast.get("yearHigh") or info.get("fiftyTwoWeekHigh"),
                    "year_low": fast.get("yearLow") or info.get("fiftyTwoWeekLow"),
                    "asset_type": info.get("quoteType") or info.get("typeDisp"),
                }
                    if any(v is not None for v in quote.values()):
                        return self._cache_set(cache_key, quote)
            except Exception:
                pass

        hist = self.get_history(symbol=symbol, period="6mo")
        if hist.empty or "close" not in hist.columns:
            raise ValueError(f"No quote returned for ticker: {symbol}")

        close = pd.to_numeric(hist["close"], errors="coerce").dropna()
        open_vals = pd.to_numeric(hist.get("open"), errors="coerce").dropna() if "open" in hist.columns else pd.Series(dtype=float)
        high_vals = pd.to_numeric(hist.get("high"), errors="coerce").dropna() if "high" in hist.columns else pd.Series(dtype=float)
        low_vals = pd.to_numeric(hist.get("low"), errors="coerce").dropna() if "low" in hist.columns else pd.Series(dtype=float)
        volume_vals = pd.to_numeric(hist.get("volume"), errors="coerce").dropna() if "volume" in hist.columns else pd.Series(dtype=float)
        quote = {
            "symbol": symbol,
            "name": symbol,
            "prev_close": float(close.iloc[-2]) if len(close) >= 2 else None,
            "open": float(open_vals.iloc[-1]) if not open_vals.empty else None,
            "high": float(high_vals.iloc[-1]) if not high_vals.empty else None,
            "low": float(low_vals.iloc[-1]) if not low_vals.empty else None,
            "volume": float(volume_vals.iloc[-1]) if not volume_vals.empty else None,
            "currency": None,
            "year_high": float(close.max()) if not close.empty else None,
            "year_low": float(close.min()) if not close.empty else None,
            "asset_type": None,
        }
        return self._cache_set(cache_key, quote)

    def get_profile(self, symbol: str) -> dict[str, Any]:
        symbol = self._normalize_symbol(symbol)
        cache_key = ("profile", symbol)
        symbol_variants = self._symbol_variants(symbol)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        if self.obb is not None:
            try:
                for candidate_symbol in symbol_variants or [symbol]:
                    kwargs = {"symbol": candidate_symbol}
                    if self.config.profile_provider:
                        kwargs["provider"] = self.config.profile_provider
                    response = self.obb.equity.profile(**kwargs)
                    rows = self._response_results(response)
                    if rows:
                        return self._cache_set(cache_key, self._normalize_profile_payload(rows[0], symbol))
            except Exception:
                pass

        yf = self._try_import_yfinance()
        if yf is not None:
            try:
                for candidate_symbol in symbol_variants or [symbol]:
                    ticker = yf.Ticker(candidate_symbol)
                    info = self._suppress_yf_call(lambda: ticker.info) or {}
                    get_info = {}
                    try:
                        get_info = self._suppress_yf_call(lambda: ticker.get_info()) or {}
                    except Exception:
                        get_info = {}
                    funds_data = getattr(ticker, "funds_data", None)
                    fund_profile = {}
                    if funds_data is not None:
                        try:
                            fund_profile = self._merge_dicts(
                                getattr(funds_data, "fund_profile", None),
                                getattr(funds_data, "description", None),
                                getattr(funds_data, "top_holdings", None),
                            )
                        except Exception:
                            pass
                    merged = self._merge_dicts(info, get_info, {"fundProfile": fund_profile})
                    profile = self._normalize_profile_payload(merged, symbol)
                    if profile and any(profile.get(key) not in (None, "", symbol) for key in ("name", "long_description", "short_description", "sector", "industry_category")):
                        return self._cache_set(cache_key, profile)
            except Exception:
                pass

        fallback = {"name": symbol}
        return self._cache_set(cache_key, fallback)

    def get_history(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        interval: str = "1d",
        period: str | None = None,
    ) -> pd.DataFrame:
        symbol = self._normalize_symbol(symbol)
        cache_key = ("history", symbol, start_date, end_date, interval, period)
        symbol_variants = self._symbol_variants(symbol)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached.copy()

        if period:
            df = self._yfinance_history(symbol, period=period, interval=interval)
            if not df.empty:
                return self._cache_set(cache_key, df.copy())
            raise ValueError(f"No historical data returned for ticker: {symbol}.")

        if self.obb is not None:
            try:
                for candidate_symbol in symbol_variants or [symbol]:
                    kwargs: dict[str, Any] = {"symbol": candidate_symbol, "provider": self.config.price_provider, "interval": interval}
                    if start_date:
                        kwargs["start_date"] = start_date
                    if end_date:
                        kwargs["end_date"] = end_date
                    response = self.obb.equity.price.historical(**kwargs)
                    rows = self._response_results(response)
                    df = pd.DataFrame(rows)
                    if not df.empty:
                        for col in ("date", "datetime"):
                            if col in df.columns:
                                df[col] = pd.to_datetime(df[col], errors="coerce", utc=True).dt.tz_localize(None)
                                df = df.sort_values(col).reset_index(drop=True)
                                break
                        return self._cache_set(cache_key, df.copy())
            except Exception:
                pass

        df = self._yfinance_history(symbol, start_date=start_date, end_date=end_date, interval=interval)
        if not df.empty:
            return self._cache_set(cache_key, df.copy())
        raise ValueError(f"No historical data returned for ticker: {symbol}.")

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        symbol = self._normalize_symbol(symbol)
        cache_key = ("news", symbol, limit)
        symbol_variants = self._symbol_variants(symbol)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return list(cached)

        if self.obb is not None:
            try:
                for candidate_symbol in symbol_variants or [symbol]:
                    kwargs: dict[str, Any] = {"symbol": candidate_symbol, "limit": limit}
                    if self.config.news_provider:
                        kwargs["provider"] = self.config.news_provider
                    response = self.obb.news.company(**kwargs)
                    rows = self._response_results(response)
                    if rows:
                        return self._cache_set(cache_key, rows[:limit])
            except Exception:
                pass

        yf = self._try_import_yfinance()
        if yf is not None:
            try:
                normalized = []
                for candidate_symbol in symbol_variants or [symbol]:
                    raw_items = self._suppress_yf_call(lambda: getattr(yf.Ticker(candidate_symbol), "news", [])) or []
                    if raw_items:
                        break
                for item in raw_items[:limit]:
                    # yfinance >= 0.2.40 nests all fields under item['content']
                    content = item.get("content") if isinstance(item.get("content"), dict) else {}
                    provider_info = content.get("provider") or {}
                    canonical_url = content.get("canonicalUrl") or {}
                    normalized.append(
                        {
                            "date": (
                                content.get("pubDate") or content.get("displayTime")
                                or item.get("providerPublishTime") or item.get("pubDate") or item.get("published_at")
                            ),
                            "title": content.get("title") or item.get("title"),
                            "source": (
                                (provider_info.get("displayName") if isinstance(provider_info, dict) else None)
                                or item.get("publisher") or item.get("source")
                            ),
                            "url": (
                                (canonical_url.get("url") if isinstance(canonical_url, dict) else None)
                                or content.get("url") or item.get("link") or item.get("url")
                            ),
                            "summary": content.get("summary") or content.get("description") or item.get("summary") or item.get("description"),
                        }
                    )
                return self._cache_set(cache_key, normalized[:limit])
            except Exception:
                pass

        return self._cache_set(cache_key, [])


    def _normalize_market_mover_rows(self, rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows or []:
            symbol = str(self._pick_first(row, 'symbol', 'ticker') or '').upper().strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            pct = self._pick_first(row, 'percent_change', 'change_percent', 'change_pct', 'pct_change')
            try:
                pct_val = float(pct) if pct is not None else None
            except Exception:
                pct_val = None
            if pct_val is not None and abs(pct_val) > 1:
                pct_val = pct_val / 100.0
            out.append({
                'ticker': symbol,
                'name': self._pick_first(row, 'name', 'company_name', 'title') or symbol,
                'last_price': self._pick_first(row, 'price', 'last_price', 'last_sale_price'),
                'day_change': self._pick_first(row, 'change', 'price_change', 'day_change'),
                'day_change_pct': pct_val,
                'volume': self._pick_first(row, 'volume', 'last_volume'),
                'exchange': self._pick_first(row, 'exchange', 'venue'),
            })
            if len(out) >= limit:
                break
        return out

    def _openbb_market_mover_rows(self, kind: str, limit: int) -> list[dict[str, Any]]:
        if self.obb is None:
            return []
        equity = getattr(self.obb, 'equity', None)
        if equity is None:
            return []
        discovery = getattr(equity, 'discovery', None)
        providers = []
        for candidate in (self.config.price_provider, 'yfinance', 'standard', 'nasdaq', 'fmp', None):
            if candidate not in providers:
                providers.append(candidate)

        fn = getattr(discovery, kind, None) if discovery is not None else None
        if callable(fn):
            for provider in providers:
                kwargs: dict[str, Any] = {'limit': limit}
                if provider:
                    kwargs['provider'] = provider
                try:
                    rows = self._response_results(fn(**kwargs))
                    if rows:
                        return rows
                except Exception:
                    continue

        screener = getattr(equity, 'screener', None)
        signal = 'top_gainers' if kind == 'gainers' else 'top_losers'
        if callable(screener):
            for provider in providers:
                kwargs = {'signal': signal, 'limit': limit}
                if provider:
                    kwargs['provider'] = provider
                try:
                    rows = self._response_results(screener(**kwargs))
                    if rows:
                        return rows
                except Exception:
                    continue
        return []

    def _yfinance_screen_movers(self, screen_id: str, limit: int) -> list[dict[str, Any]]:
        """Fetch real market-wide movers via yfinance.screen() (v1.2+)."""
        yf = self._try_import_yfinance()
        if yf is None or not hasattr(yf, 'screen'):
            return []
        try:
            result = self._suppress_yf_call(lambda: yf.screen(screen_id)) or {}
            quotes = result.get('quotes', [])
            out = []
            for q in quotes[:limit]:
                pct = q.get('regularMarketChangePercent')
                try:
                    pct_val = float(pct) / 100.0 if pct is not None else None
                except Exception:
                    pct_val = None
                symbol = str(q.get('symbol') or '').upper().strip()
                if not symbol:
                    continue
                out.append({
                    'ticker': symbol,
                    'name': q.get('shortName') or q.get('longName') or symbol,
                    'last_price': q.get('regularMarketPrice'),
                    'day_change': q.get('regularMarketChange'),
                    'day_change_pct': pct_val,
                    'volume': q.get('regularMarketVolume'),
                    'exchange': q.get('exchange') or q.get('fullExchangeName'),
                })
            return out
        except Exception:
            return []

    def get_market_movers(self, limit: int = 10) -> dict[str, list[dict[str, Any]]]:
        cache_key = ('market_movers', int(limit))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return dict(cached)

        # Try OpenBB discovery first, then yfinance screener (real market-wide data)
        gainers = self._normalize_market_mover_rows(self._openbb_market_mover_rows('gainers', limit), limit)
        if not gainers:
            gainers = self._yfinance_screen_movers('day_gainers', limit)

        losers = self._normalize_market_mover_rows(self._openbb_market_mover_rows('losers', limit), limit)
        if not losers:
            losers = self._yfinance_screen_movers('day_losers', limit)

        payload = {'gainers': gainers, 'losers': losers}
        return self._cache_set(cache_key, payload)

    def get_basic_bundle(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        news_limit: int = 10,
    ) -> dict[str, Any]:
        symbol = symbol.upper().strip()
        cache_key = ("bundle", symbol, start_date, end_date, news_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return dict(cached)

        try:
            quote = self.get_quote(symbol)
        except Exception:
            quote = {"symbol": symbol}
        try:
            profile = self.get_profile(symbol)
        except Exception:
            profile = {"name": symbol}

        history = self.get_history(symbol=symbol, start_date=start_date, end_date=end_date)
        news = self.get_company_news(symbol=symbol, limit=news_limit) if news_limit else []
        bundle = {"ticker": symbol, "quote": quote, "profile": profile, "history": history, "news": news}
        return self._cache_set(cache_key, bundle)
