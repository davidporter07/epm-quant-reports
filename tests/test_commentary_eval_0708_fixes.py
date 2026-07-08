"""Guardrail from the 2026-07-08 eval: the "Top Performers" panel rendered
"No data available" three days running while positive-return funds sat in the fund
metrics table. _backfill_winners_panel fills portfolio_spotlight_winners from the
authoritative input top performers when the model omits it (mirror of the watch backfill).
"""
import pytest

gmc = pytest.importorskip("generate_market_commentary")


def _winners():
    return [
        {"ticker": "JFNIX", "description": "John Hancock Fundamental All Cap Core",
         "return_1m": 12.08, "metric_label": "+12.1% (1M)"},
        {"ticker": "IXJ", "description": "iShares Global Healthcare",
         "return_1m": 6.76, "metric_label": "+6.8% (1M)"},
    ]


def test_empty_winners_panel_backfilled():
    data = {"portfolio_spotlight_winners": []}
    n = gmc._backfill_winners_panel(data, _winners(), known_tickers={"JFNIX", "IXJ"})
    assert n == 2
    tickers = [e["ticker"] for e in data["portfolio_spotlight_winners"]]
    assert tickers == ["JFNIX", "IXJ"]
    assert "Leading the portfolio" in data["portfolio_spotlight_winners"][0]["commentary"]


def test_existing_winners_not_overwritten():
    data = {"portfolio_spotlight_winners": [{"ticker": "AAA", "commentary": "keep me"}]}
    assert gmc._backfill_winners_panel(data, _winners(), known_tickers=None) == 0
    assert data["portfolio_spotlight_winners"][0]["ticker"] == "AAA"


def test_negative_returns_excluded():
    data = {"portfolio_spotlight_winners": []}
    losers = [{"ticker": "DOWN", "description": "x", "return_1m": -3.0,
               "metric_label": "-3.0% (1M)"}]
    assert gmc._backfill_winners_panel(data, losers, known_tickers=None) == 0
    assert data["portfolio_spotlight_winners"] == []


def test_off_universe_ticker_filtered():
    data = {"portfolio_spotlight_winners": []}
    gmc._backfill_winners_panel(data, _winners(), known_tickers={"JFNIX"})
    assert [e["ticker"] for e in data["portfolio_spotlight_winners"]] == ["JFNIX"]
