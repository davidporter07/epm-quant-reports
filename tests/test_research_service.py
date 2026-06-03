"""Tests for research_service.py — the generalized enrichment runner."""
import importlib

import pytest


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_DB_PATH", str(tmp_path / "research_cache.db"))
    import services.research_store as rs
    importlib.reload(rs)              # point store at temp db
    import research_service as svc
    importlib.reload(svc)            # rebind svc.research_store to the reloaded module
    return svc


class FakeSearx:
    """Counts searches so tests can assert cache hits skip the network."""
    def __init__(self, available=True):
        self._available = available
        self.calls = 0

    def available(self):
        return self._available

    def search(self, query, max_results=8, **k):
        self.calls += 1
        q = query.lower()
        if "portfolio manager" in q or "manager" in q:
            return [{"title": "Manager", "url": "http://m", "content": "Cathie Wood is the portfolio manager since 2014."}]
        return [{"title": "Info", "url": "http://i", "content": f"Relevant snippet about {query}."}]


def fake_ollama(prompt, timeout=60):
    if "JSON array" in prompt:
        return '["Cathie Wood"]'
    if "investment strategy" in prompt.lower():
        return "Seeks long-term capital appreciation via disruptive innovation."
    if "MATERIAL recent developments" in prompt:
        return "NONE"
    if "asset flows" in prompt.lower():
        return "Net outflows over the past quarter."
    # manager tenure summary
    return "Manager since 2014 (~11 years). Founder of ARK Invest."


ACTIVE_FUND = {"name": "ARK Innovation ETF", "category": "Technology",
               "objective": "Seeks long-term capital appreciation via disruptive innovation",
               "issue_type": "ETF", "expense_ratio_pct": 0.75}


def test_enrich_unavailable_returns_empty(svc):
    out = svc.enrich("ARKK", name="ARK", asset_kind="fund",
                     fund_profile=ACTIVE_FUND, searx=FakeSearx(available=False))
    assert out == {}


def test_enrich_fund_happy_path_and_cache(svc):
    fx = FakeSearx()
    out = svc.enrich("ARKK", name="ARK Innovation ETF", asset_kind="fund",
                     fund_profile=ACTIVE_FUND, searx=fx, ollama_call=fake_ollama)
    assert out["manager"]["summary"].startswith("Cathie Wood")
    assert out["manager"]["tenure_years"] == 11.0
    assert out["strategy"]["found"] is True
    assert "flows" in out
    assert "developments" not in out  # extractor returned NONE -> empty, not surfaced
    first_calls = fx.calls
    assert first_calls > 0

    # second call: everything cached -> no new searches
    fx2 = FakeSearx()
    out2 = svc.enrich("ARKK", name="ARK Innovation ETF", asset_kind="fund",
                      fund_profile=ACTIVE_FUND, searx=fx2, ollama_call=fake_ollama)
    assert fx2.calls == 0
    assert out2["manager"]["summary"].startswith("Cathie Wood")


def test_enrich_passive_fund_skips_manager(svc):
    passive = {"name": "Vanguard S&P 500 ETF", "category": "Large Blend",
               "objective": "Tracks the S&P 500 index", "issue_type": "ETF",
               "expense_ratio_pct": 0.03}
    out = svc.enrich("VOO", name="Vanguard S&P 500 ETF", asset_kind="fund",
                     fund_profile=passive, searx=FakeSearx(), ollama_call=fake_ollama)
    assert "manager" not in out  # gated out (passive)


def test_enrich_stock_topics(svc):
    def stock_ollama(prompt, timeout=60):
        return "CEO Jensen Huang remains; no leadership change reported."
    out = svc.enrich("NVDA", name="NVIDIA Corp", asset_kind="stock",
                     searx=FakeSearx(), ollama_call=stock_ollama)
    # stock topics ran (manager/strategy are fund-only and absent)
    assert "manager" not in out
    assert "management_changes" in out
    assert "analyst_actions" in out


def test_invalidate_from_news_marks_stale(svc, monkeypatch):
    import pandas as pd
    svc.research_store.put("ARKK", "manager", {"found": True, "summary": "old"}, ttl_days=60)
    # a fresh headline announcing a manager change
    df = pd.DataFrame([{
        "Ticker": "ARKK",
        "Headline": "Cathie Wood steps down as portfolio manager",
        "Summary": "",
        "PublishedAt": pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=1),
    }])
    monkeypatch.setattr("news_store.load_news_store", lambda *a, **k: df)
    names = svc.invalidate_from_news("ARKK")
    assert "manager" in names
    assert svc.research_store.get("ARKK", "manager") is None  # now stale
