from __future__ import annotations

from typing import Any

from snapshot_engine import TickerSnapshotEngine
from services.news_ranker import rank_news


class TickerPageService:
    def __init__(self, snapshot_engine: TickerSnapshotEngine | None = None) -> None:
        self.snapshot_engine = snapshot_engine or TickerSnapshotEngine()

    def build_fund_search_payload(
        self,
        ticker: str,
        period: str = "1y",
        include_news: bool = True,
    ) -> dict[str, Any]:
        snapshot = self.snapshot_engine.build_snapshot(ticker=ticker, include_news=include_news)
        chart = self.snapshot_engine.build_chart_payload(ticker=ticker, period=period)

        ranked_news = rank_news(
            items=snapshot.get("news", []) if include_news else [],
            ticker=snapshot.get("ticker", ticker),
            name=snapshot.get("name"),
        )[:5]

        price = snapshot.get("price", {})
        returns = snapshot.get("returns", {})
        risk = snapshot.get("risk", {})
        trend = snapshot.get("trend", {})
        fundamentals = snapshot.get("fundamentals", {})

        prev_close = price.get("prev_close")
        last_price = price.get("last_price")

        day_change = None
        day_change_pct = None
        if last_price is not None and prev_close not in (None, 0):
            day_change = last_price - prev_close
            day_change_pct = day_change / prev_close

        quick_stats = [
            {"label": "1M", "value": returns.get("return_1m"), "kind": "percent"},
            {"label": "YTD", "value": returns.get("return_ytd"), "kind": "percent"},
            {"label": "Beta", "value": risk.get("beta_1y"), "kind": "number"},
            {"label": "Volatility", "value": risk.get("volatility_1y"), "kind": "percent"},
            {"label": "Market Cap", "value": fundamentals.get("market_cap"), "kind": "currency_compact"},
        ]

        trend_bullets = []
        if trend.get("price_vs_ma50_pct") is not None:
            trend_bullets.append({"label": "vs 50D MA", "value": trend["price_vs_ma50_pct"], "kind": "percent"})
        if trend.get("price_vs_ma200_pct") is not None:
            trend_bullets.append({"label": "vs 200D MA", "value": trend["price_vs_ma200_pct"], "kind": "percent"})
        if chart.get("resistance") is not None:
            trend_bullets.append({"label": "Range High", "value": chart["resistance"], "kind": "price"})

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
            "quick_stats": [x for x in quick_stats if x["value"] is not None],
            "insight_panel": {
                "summary": snapshot.get("summary"),
                "about": snapshot.get("short_description") or snapshot.get("description"),
                "trend_bullets": trend_bullets,
            },
            "ranked_news": ranked_news,
            "raw_snapshot": snapshot,
        }
