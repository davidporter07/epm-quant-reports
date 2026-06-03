"""Tests for Plan 2 Phase 2 — SearxNG provider + PM-discovery agent.

All offline: requests and Ollama are stubbed. The hard contract under test is
that every failure mode degrades to empty rather than raising.
"""
import pm_research as pmr
from providers.searxng_provider import SearxNGProvider


# --------------------------------------------------------------------------- #
# SearxNGProvider
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_searx_search_parses_results(monkeypatch):
    payload = {"results": [
        {"title": "Fund X PM", "url": "http://a", "content": "Jane Smith manages"},
        {"title": "No url", "content": "skip me"},  # dropped (no url)
        {"title": "Fund X", "url": "http://b", "content": "since 2015"},
    ]}
    monkeypatch.setattr("providers.searxng_provider.requests.get",
                        lambda *a, **k: _Resp(200, payload))
    out = SearxNGProvider("http://searx").search("query")
    assert [r["url"] for r in out] == ["http://a", "http://b"]
    assert out[0]["content"] == "Jane Smith manages"


def test_searx_returns_empty_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("conn refused")
    monkeypatch.setattr("providers.searxng_provider.requests.get", boom)
    assert SearxNGProvider("http://searx").search("q") == []
    assert SearxNGProvider("http://searx").available() is False


def test_searx_empty_query():
    assert SearxNGProvider("http://searx").search("   ") == []


def test_searx_non_200(monkeypatch):
    monkeypatch.setattr("providers.searxng_provider.requests.get",
                        lambda *a, **k: _Resp(503, {}))
    assert SearxNGProvider("http://searx").search("q") == []


# --------------------------------------------------------------------------- #
# looks_actively_managed
# --------------------------------------------------------------------------- #
def test_active_detection():
    # index markers => passive
    assert pmr.looks_actively_managed(name="Vanguard S&P 500 ETF", category="Large Blend") is False
    assert pmr.looks_actively_managed(objective="Seeks to track the MSCI World index") is False
    # cheap expense => passive
    assert pmr.looks_actively_managed(name="Some Fund", expense_ratio_pct=0.03) is False
    # active fund => True
    assert pmr.looks_actively_managed(
        name="ARK Innovation ETF", category="Technology",
        objective="Seeks long-term capital appreciation via disruptive innovation",
        expense_ratio_pct=0.75) is True


# --------------------------------------------------------------------------- #
# _parse_json_list
# --------------------------------------------------------------------------- #
def test_parse_json_list_tolerates_prose():
    assert pmr._parse_json_list('Here you go: ["Jane Smith", "John Doe"] done') == ["Jane Smith", "John Doe"]
    assert pmr._parse_json_list("no array here") == []
    # empties + N/A + unknown-prefixed placeholders are all filtered out
    assert pmr._parse_json_list('["", "N/A", "unknown"]') == []


# --------------------------------------------------------------------------- #
# research_fund_management
# --------------------------------------------------------------------------- #
class _FakeSearx:
    def __init__(self, available=True, results=None):
        self._available = available
        self._results = results if results is not None else [
            {"title": "Cathie Wood", "url": "http://ark", "content": "Cathie Wood is the portfolio manager"},
        ]

    def available(self):
        return self._available

    def search(self, query, max_results=8):
        return list(self._results)


def test_research_unavailable_returns_empty():
    assert pmr.research_fund_management("ARKK", "ARK Innovation", searx=_FakeSearx(available=False)) == {}


def test_research_happy_path():
    calls = {"n": 0}

    def fake_ollama(prompt, timeout=90):
        calls["n"] += 1
        if "JSON array" in prompt:
            return '["Cathie Wood"]'
        return "Manager since 2014 (~11 years). Founder of ARK Invest, previously at AllianceBernstein."

    res = pmr.research_fund_management(
        "ARKK", "ARK Innovation ETF",
        searx=_FakeSearx(), ollama_call=fake_ollama)
    assert res["manager_summary"].startswith("Cathie Wood:")
    assert res["manager_tenure_years"] == 11.0
    assert "http://ark" in res["source_urls"]
    assert res["managers"][0]["name"] == "Cathie Wood"


def test_research_no_names_returns_empty():
    res = pmr.research_fund_management(
        "XYZ", "Mystery Fund",
        searx=_FakeSearx(), ollama_call=lambda p, t=90: "[]")
    assert res == {}


def test_research_ollama_failure_safe():
    def boom(p, t=90):
        raise RuntimeError("ollama down")
    res = pmr.research_fund_management("ARKK", "ARK Innovation", searx=_FakeSearx(), ollama_call=boom)
    # name extraction failed -> empty, no raise
    assert res == {}


def test_research_swallows_all_exceptions():
    class Broken:
        def available(self):
            return True
        def search(self, *a, **k):
            raise RuntimeError("boom")
    assert pmr.research_fund_management("ARKK", "ARK", searx=Broken()) == {}
