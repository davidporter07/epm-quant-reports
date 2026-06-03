"""Tests for GET /api/research/{symbol} — display-only enrichment endpoint."""
import types

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

try:
    from fastapi.testclient import TestClient
    import app as appmod
    from app import app
except Exception as exc:  # pragma: no cover
    pytest.skip(f"web app deps unavailable: {exc}", allow_module_level=True)


def _patch_common(monkeypatch):
    monkeypatch.setattr(appmod, "_require_user", lambda request: {"username": "t"})
    monkeypatch.setattr(appmod.engine, "provider",
                        types.SimpleNamespace(get_profile=lambda s: {"name": "ARK Innovation ETF", "issue_type": "ETF"}))


def test_research_endpoint_fund(monkeypatch):
    _patch_common(monkeypatch)
    import deep_analysis
    monkeypatch.setattr(deep_analysis, "_get_fund_profile", lambda s: {
        "name": "ARK Innovation ETF", "issue_type": "ETF", "category": "Technology",
        "top_holdings": [{"symbol": "TSLA", "weight_pct": 9.0}],
        "top10_concentration_pct": 55.0, "objective": "Disruptive innovation.",
        "expense_ratio_pct": 0.75, "fund_family": "ARK",
    })
    from services import research_store
    monkeypatch.setattr(research_store, "get_fresh_for_symbol", lambda s: {
        "manager": {"content": {"found": True, "summary": "Cathie Wood leads since 2014.",
                                "tenure_years": 11.0, "managers": ["Cathie Wood"]},
                    "sources": ["http://ark"], "fetched_at": "2026-06-03T12:00:00+00:00"},
        "empty": {"content": {"found": False}, "sources": [], "fetched_at": "2026-06-03T12:00:00+00:00"},
    })
    r = TestClient(app).get("/api/research/ARKK")
    assert r.status_code == 200
    b = r.json()
    assert b["is_fund"] is True
    assert b["profile"]["expense_ratio_pct"] == 0.75
    assert b["research"]["manager"]["summary"].startswith("Cathie Wood")
    assert b["research"]["manager"]["researched"] == "2026-06-03"
    assert "empty" not in b["research"]          # found:False filtered out
    assert b["has_research"] is True


def test_research_endpoint_stock_no_cache(monkeypatch):
    _patch_common(monkeypatch)
    import deep_analysis
    monkeypatch.setattr(deep_analysis, "_get_fund_profile", lambda s: {})  # not a fund
    from services import research_store
    monkeypatch.setattr(research_store, "get_fresh_for_symbol", lambda s: {})
    r = TestClient(app).get("/api/research/NVDA")
    assert r.status_code == 200
    b = r.json()
    assert b["is_fund"] is False
    assert b["research"] == {}
    assert b["has_research"] is False


def test_research_endpoint_invalid_symbol(monkeypatch):
    _patch_common(monkeypatch)
    r = TestClient(app).get("/api/research/TOOLONGSYMBOL123")
    assert r.status_code == 400
