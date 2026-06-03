"""Tests for fund-holdings / mandate-aware deep analysis (Plan 2, Phase 1).

Covers:
  - OpenBBProvider._extract_funds_data: DataFrame/str funds_data survive the flatten
  - OpenBBProvider._normalize_profile_payload: additive fund keys, equity contract intact
  - deep_analysis._get_fund_profile: fund vs ordinary stock
  - deep_analysis.build_seed_doc: FUND COMPOSITION section + FUND STRUCTURE persona swap
"""
import pandas as pd
import pytest

from providers.openbb_provider import OpenBBProvider
import deep_analysis


# --------------------------------------------------------------------------- #
# _extract_funds_data
# --------------------------------------------------------------------------- #
class _FakeFundsData:
    # Mirrors real yfinance FundsData attribute names.
    fund_overview = {
        "categoryName": "Large Blend",
        "family": "Vanguard",
        "legalType": "Exchange Traded Fund",
    }
    description = "Tracks the performance of the S&P 500 Index."
    top_holdings = pd.DataFrame(
        {"Name": ["Apple Inc", "Microsoft"], "Holding Percent": [0.071, 0.065]},
        index=["AAPL", "MSFT"],
    )
    sector_weightings = {"technology": 0.30, "financial_services": 0.13}
    fund_operations = pd.DataFrame(
        {"VOO": [0.0003, 0.02], "Category Average": [0.0072, 0.5]},
        index=["Annual Report Expense Ratio", "Annual Holdings Turnover"],
    )


def test_extract_funds_data_preserves_str_and_dataframe():
    ex = OpenBBProvider._extract_funds_data(_FakeFundsData())
    assert ex["fundOverview"].startswith("Tracks")
    assert ex["topHoldings"][0] == {"symbol": "AAPL", "name": "Apple Inc", "weight": 0.071}
    assert ex["sectorWeightings"]["technology"] == 0.30
    # dict fund_profile keys still present
    assert ex["categoryName"] == "Large Blend"


def test_extract_funds_data_none_safe():
    assert OpenBBProvider._extract_funds_data(None) == {}


# --------------------------------------------------------------------------- #
# _normalize_profile_payload
# --------------------------------------------------------------------------- #
def _norm_fund():
    p = OpenBBProvider()
    ex = OpenBBProvider._extract_funds_data(_FakeFundsData())
    raw = {
        "longName": "Vanguard S&P 500 ETF",
        "quoteType": "ETF",
        "marketCap": 1_000_000_000,
        "fundProfile": ex,
    }
    return p._normalize_profile_payload(raw, "VOO")


def test_normalize_adds_fund_keys():
    norm = _norm_fund()
    assert norm["category"] == "Large Blend"
    assert norm["fund_family"] == "Vanguard"
    assert norm["expense_ratio"] == 0.0003
    assert norm["top_holdings"][1]["symbol"] == "MSFT"
    assert norm["fund_overview"].startswith("Tracks")


def test_normalize_equity_contract_intact():
    p = OpenBBProvider()
    stock = p._normalize_profile_payload({"longName": "Apple Inc", "quoteType": "EQUITY"}, "AAPL")
    # existing keys still present
    assert stock["name"] == "Apple Inc"
    assert stock["issue_type"] == "EQUITY"
    # new fund keys present but null for an equity
    assert stock["top_holdings"] is None
    assert stock["expense_ratio"] is None
    assert stock["category"] is None


# --------------------------------------------------------------------------- #
# _get_fund_profile
# --------------------------------------------------------------------------- #
def test_get_fund_profile_fund(monkeypatch):
    norm = _norm_fund()
    monkeypatch.setattr(OpenBBProvider, "get_profile", lambda self, sym: norm)
    fp = deep_analysis._get_fund_profile("VOO")
    assert fp["is_fund"] is True
    assert fp["expense_ratio_pct"] == 0.03
    assert fp["top_holdings"][0]["weight_pct"] == 7.1
    assert fp["top10_concentration_pct"] == 13.6
    assert fp["sector_tilt"][0][0] == "Technology"


def test_get_fund_profile_stock_returns_empty(monkeypatch):
    stock = OpenBBProvider()._normalize_profile_payload(
        {"longName": "Apple Inc", "quoteType": "EQUITY"}, "AAPL")
    monkeypatch.setattr(OpenBBProvider, "get_profile", lambda self, sym: stock)
    assert deep_analysis._get_fund_profile("AAPL") == {}


def test_get_fund_profile_provider_error_safe(monkeypatch):
    def boom(self, sym):
        raise RuntimeError("network down")
    monkeypatch.setattr(OpenBBProvider, "get_profile", boom)
    assert deep_analysis._get_fund_profile("VOO") == {}


# --------------------------------------------------------------------------- #
# build_seed_doc rendering (fetchers stubbed)
# --------------------------------------------------------------------------- #
_TECH = {
    "current": 500.0, "ma50": 490.0, "ma200": 470.0,
    "high52": 520.0, "low52": 440.0, "pct_from_high": -3.8, "pct_from_low": 13.6,
    "rsi": 55.0, "mom5": 1.2, "mom20": 2.5, "vol_ratio": 1.1,
}


def _stub_fetchers(monkeypatch, fund_payload):
    da = deep_analysis
    monkeypatch.setattr(da, "_get_ohlcv", lambda t, days=252: [
        {"date": "2026-05-2{}".format(i % 9), "open": 499.0, "high": 501.0,
         "low": 498.0, "close": 500.0, "volume": 1e6} for i in range(60)
    ])
    monkeypatch.setattr(da, "_get_kronos_scenarios", lambda *a, **k: [])
    monkeypatch.setattr(da, "_compute_technicals", lambda ohlcv: dict(_TECH))
    monkeypatch.setattr(da, "_get_epm_forecasts", lambda t: None)
    monkeypatch.setattr(da, "_get_news_headlines", lambda t, max_headlines=10: [])
    monkeypatch.setattr(da, "_get_company_info", lambda t: {
        "name": "Vanguard S&P 500 ETF", "sector": None, "industry": None, "country": "US"})
    monkeypatch.setattr(da, "_get_vix", lambda: 15.0)
    monkeypatch.setattr(da, "_get_spy_trend", lambda: {})
    monkeypatch.setattr(da, "_get_earnings_info", lambda t: None)
    monkeypatch.setattr(da, "_get_fundamentals", lambda t: {})
    monkeypatch.setattr(da, "_get_volatility_regime", lambda ohlcv: {"regime": "N/A"})
    monkeypatch.setattr(da, "_get_relative_performance", lambda t, s: {})
    monkeypatch.setattr(da, "_get_overnight_stats", lambda ohlcv: {})
    monkeypatch.setattr(da, "_get_earnings_surprise_history", lambda t: [])
    monkeypatch.setattr(da, "load_recent_earnings_release", lambda t: None)
    monkeypatch.setattr(da, "_get_fund_profile", lambda t: fund_payload)


def test_build_seed_doc_fund_section(monkeypatch):
    fund = {
        "is_fund": True, "name": "Vanguard S&P 500 ETF", "issue_type": "ETF",
        "category": "Large Blend", "fund_family": "Vanguard",
        "expense_ratio_pct": 0.03,
        "top_holdings": [
            {"symbol": "AAPL", "name": "Apple Inc", "weight_pct": 7.1},
            {"symbol": "MSFT", "name": "Microsoft", "weight_pct": 6.5},
        ],
        "top10_concentration_pct": 13.6,
        "sector_tilt": [("Technology", 30.0), ("Financial Services", 13.0)],
        "objective": "Seeks to track the S&P 500 Index.",
    }
    _stub_fetchers(monkeypatch, fund)
    doc, key_facts = deep_analysis.build_seed_doc("VOO", pred_len=5)
    assert "FUND COMPOSITION & MANDATE" in doc
    assert "FUND STRUCTURE ANALYST" in doc
    assert "EARNINGS CATALYST ANALYST" not in doc
    assert "Apple Inc" in doc and "7.10%" in doc
    assert "Expense ratio: 0.03%" in doc
    assert "this fund" in doc
    assert key_facts["is_fund"] is True
    assert key_facts["top10_concentration_pct"] == 13.6
    assert key_facts["fund_category"] == "Large Blend"


def test_run_council_swaps_persona_for_fund(monkeypatch):
    import local_council as lc
    monkeypatch.setattr(lc, "_call_ollama", lambda prompt, timeout=600: "{}")
    res = lc.run_council("VOO", "── FUND COMPOSITION & MANDATE ──\nTop Holdings: AAPL 7%",
                         {"ticker": "VOO", "is_fund": True, "current_price": 500.0})
    raw = res["raw_markdown"]
    assert "Fund Structure Analyst" in raw
    assert "Earnings Catalyst Analyst" not in raw


def test_run_council_keeps_earnings_persona_for_stock(monkeypatch):
    import local_council as lc
    monkeypatch.setattr(lc, "_call_ollama", lambda prompt, timeout=600: "{}")
    res = lc.run_council("AAPL", "── EARNINGS CATALYST PERSPECTIVE ──\n",
                         {"ticker": "AAPL", "current_price": 200.0})
    raw = res["raw_markdown"]
    assert "Earnings Catalyst Analyst" in raw
    assert "Fund Structure Analyst" not in raw


def test_build_seed_doc_stock_has_no_fund_section(monkeypatch):
    _stub_fetchers(monkeypatch, {})
    monkeypatch.setattr(deep_analysis, "_get_company_info", lambda t: {
        "name": "Apple Inc", "sector": "Technology", "industry": "Consumer Electronics", "country": "US"})
    doc, key_facts = deep_analysis.build_seed_doc("AAPL", pred_len=5)
    assert "FUND COMPOSITION & MANDATE" not in doc
    assert "FUND STRUCTURE ANALYST" not in doc
    assert "EARNINGS CATALYST ANALYST" in doc
    assert "this stock" in doc
    assert "is_fund" not in key_facts
