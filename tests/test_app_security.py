"""PR 0/1 security fixes: /api/chat auth gate, explicit CORS, forgot-password rate limit."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # required by Starlette's TestClient

# The web app pulls in server-only deps (bcrypt, PyJWT, ...) that aren't present
# in the pipeline-only venv. Skip cleanly there; run wherever the full stack is
# installed (server / CI).
try:
    from fastapi.testclient import TestClient
    import app as app_module
    from app import app
except Exception as exc:  # pragma: no cover - environment-dependent
    pytest.skip(f"web app deps unavailable: {exc}", allow_module_level=True)


@pytest.fixture
def client():
    # Plain constructor (no `with`) so we don't trigger startup/worker threads.
    return TestClient(app)


# --- /api/chat must require auth -------------------------------------------

def test_chat_requires_auth(client):
    # Valid body so we pass Pydantic validation and actually reach the auth check.
    resp = client.post("/api/chat", json={"message": "hello", "history": []})
    assert resp.status_code == 401, resp.text


# --- CORS allowlist is explicit, never "*" ---------------------------------

def test_cors_origins_are_explicit():
    assert "*" not in app_module._allowed_origins
    assert any("epm-market-intelligence.com" in o for o in app_module._allowed_origins)


def test_cors_allows_known_origin_only(client):
    good = "https://epm-market-intelligence.com"
    r_good = client.get("/api/health", headers={"Origin": good})
    assert r_good.headers.get("access-control-allow-origin") == good

    r_bad = client.get("/api/health", headers={"Origin": "https://evil.example.com"})
    acao = r_bad.headers.get("access-control-allow-origin")
    assert acao != "*"
    assert acao != "https://evil.example.com"


# --- rate limiter primitive + forgot-password throttling -------------------

def test_rate_limiter_fires_after_threshold():
    key = "unit-test-key-xyz"
    app_module._RL_STORE.pop(key, None)
    assert app_module._rate_limited(key, max_requests=3, window_s=60) is False
    assert app_module._rate_limited(key, max_requests=3, window_s=60) is False
    assert app_module._rate_limited(key, max_requests=3, window_s=60) is False
    assert app_module._rate_limited(key, max_requests=3, window_s=60) is True


def test_forgot_password_throttles_outbound_email(client, monkeypatch):
    app_module._RL_STORE.clear()
    sent = {"count": 0}

    def _fake_send(*args, **kwargs):
        sent["count"] += 1

    monkeypatch.setattr(app_module, "get_user_by_email",
                        lambda email: {"id": 1, "username": "u", "email": email})
    monkeypatch.setattr(app_module, "create_reset_token", lambda uid: "tok")
    monkeypatch.setattr(app_module, "send_password_reset_email", _fake_send)

    email = "throttle-test@example.com"
    for _ in range(10):
        r = client.post("/api/auth/forgot-password", json={"email": email})
        # Always a generic 200 (anti-enumeration), throttled or not.
        assert r.status_code == 200

    # Email limiter caps at 3 per 900s; IP limiter caps at 5 per 300s.
    assert sent["count"] <= 3, f"rate limit did not fire; {sent['count']} emails sent"
