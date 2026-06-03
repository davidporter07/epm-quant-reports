"""Tests for services/research_store.py — the research enrichment cache."""
import importlib

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_DB_PATH", str(tmp_path / "research_cache.db"))
    import services.research_store as rs
    importlib.reload(rs)  # rebind _DB_PATH + reset _INITIALIZED to the temp db
    return rs


def test_put_get_roundtrip(store):
    store.put("prwcx", "manager", {"name": "David Giroux"}, ["http://a"], 0.9, ttl_days=60)
    row = store.get("PRWCX", "manager")
    assert row is not None
    assert row["content"] == {"name": "David Giroux"}
    assert row["sources"] == ["http://a"]
    assert row["confidence"] == 0.9
    assert row["stale"] is False


def test_get_missing_returns_none(store):
    assert store.get("NOPE", "manager") is None


def test_expiry(store):
    store.put("NVDA", "analyst_actions", {"x": 1}, ttl_days=-1)  # already expired
    assert store.get("NVDA", "analyst_actions") is None


def test_mark_stale_specific_topic(store):
    store.put("VOO", "manager", {"a": 1}, ttl_days=60)
    store.put("VOO", "strategy", {"b": 2}, ttl_days=60)
    n = store.mark_stale("VOO", ["manager"])
    assert n == 1
    assert store.get("VOO", "manager") is None      # stale -> hidden
    assert store.get("VOO", "strategy") is not None  # untouched


def test_mark_stale_all_topics(store):
    store.put("VOO", "manager", {"a": 1}, ttl_days=60)
    store.put("VOO", "strategy", {"b": 2}, ttl_days=60)
    assert store.mark_stale("VOO") == 2
    assert store.get_fresh_for_symbol("VOO") == {}


def test_put_clears_stale(store):
    store.put("ARKK", "manager", {"a": 1}, ttl_days=60)
    store.mark_stale("ARKK", ["manager"])
    assert store.get("ARKK", "manager") is None
    store.put("ARKK", "manager", {"a": 2}, ttl_days=60)  # re-research clears stale
    row = store.get("ARKK", "manager")
    assert row is not None and row["content"] == {"a": 2}


def test_get_fresh_for_symbol(store):
    store.put("PRWCX", "manager", {"name": "x"}, ttl_days=60)
    store.put("PRWCX", "developments", {"news": "y"}, ttl_days=5)
    store.put("PRWCX", "expired", {"z": 1}, ttl_days=-1)
    fresh = store.get_fresh_for_symbol("PRWCX")
    assert set(fresh.keys()) == {"manager", "developments"}
    assert fresh["manager"]["content"]["name"] == "x"
