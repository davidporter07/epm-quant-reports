"""PR2: /api/health returns aggregated checks and leaks no host/secret."""
import types

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

try:
    from fastapi.testclient import TestClient
    from app import app
except Exception as exc:  # pragma: no cover - env-dependent
    pytest.skip(f"web app deps unavailable: {exc}", allow_module_level=True)


def test_health_returns_aggregated_checks(monkeypatch):
    # Avoid a real 3s Ollama network call; make reachability deterministic.
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: types.SimpleNamespace(ok=True))

    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    checks = body["checks"]
    for key in ("commentary", "data_files", "deep_worker", "ollama"):
        assert key in checks
    # Ollama check exposes ONLY reachability — never the host/IP.
    assert set(checks["ollama"].keys()) == {"reachable"}


def test_health_does_not_leak_ollama_host(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: types.SimpleNamespace(ok=True))
    client = TestClient(app)
    text = client.get("/api/health").text
    assert "11434" not in text       # no ollama port
    assert "192.168" not in text     # no LAN IP


def test_health_commentary_check_is_self_contained(monkeypatch):
    # Regression: /api/health must not import check_site_freshness — that module is a
    # laptop-only CLI not shipped to the server, so importing it ImportError'd in prod
    # and the commentary check silently degraded to {"error": "check_failed"}.
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: types.SimpleNamespace(ok=True))
    client = TestClient(app)
    commentary = client.get("/api/health").json()["checks"]["commentary"]
    assert "error" not in commentary
    assert {"present", "report_date", "market_open", "fresh"} <= set(commentary.keys())


def test_health_source_does_not_import_laptop_only_module():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    assert "from check_site_freshness import" not in src
