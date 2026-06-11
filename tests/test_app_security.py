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


# --- PR F commit 2: _client_ip() precedence ---------------------------------

class _FakeClient:
    def __init__(self, host="127.0.0.1"):
        self.host = host


def _make_request(headers: dict, host: str = "127.0.0.1"):
    """Build a minimal fake Request-like object for _client_ip tests."""
    from starlette.datastructures import Headers
    from starlette.requests import Request as _Req
    from starlette.testclient import TestClient as _TC

    class _Scope:
        def __init__(self):
            raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
            self.scope = {
                "type": "http",
                "headers": raw,
                "method": "GET",
                "path": "/",
                "query_string": b"",
                "root_path": "",
            }
            self.scope["client"] = (host, 12345)

    s = _Scope()

    class _MockReq:
        def __init__(self):
            from starlette.datastructures import Headers as _H
            self.headers = _H(scope=s.scope)
            self.client = _FakeClient(host)

    return _MockReq()


def test_client_ip_prefers_cf_connecting_ip():
    req = _make_request({"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "9.9.9.9"})
    assert app_module._client_ip(req) == "1.2.3.4"


def test_client_ip_falls_back_to_xff_first_hop():
    req = _make_request({"X-Forwarded-For": "5.6.7.8, 10.0.0.1"})
    assert app_module._client_ip(req) == "5.6.7.8"


def test_client_ip_strips_whitespace_in_xff():
    req = _make_request({"X-Forwarded-For": "  5.6.7.8 , 10.0.0.1"})
    assert app_module._client_ip(req) == "5.6.7.8"


def test_client_ip_falls_back_to_client_host():
    req = _make_request({}, host="192.168.1.1")
    assert app_module._client_ip(req) == "192.168.1.1"


def test_forgot_password_different_cf_ips_get_independent_budgets(monkeypatch):
    """Two distinct CF-Connecting-IP values must NOT share the IP rate-limit bucket."""
    app_module._RL_STORE.clear()
    monkeypatch.setattr(app_module, "get_user_by_email", lambda e: None)

    client_a = TestClient(app)
    client_b = TestClient(app)

    # Exhaust the budget for IP A (5 per 300s).
    for _ in range(5):
        client_a.post(
            "/api/auth/forgot-password",
            json={"email": "x@example.com"},
            headers={"CF-Connecting-IP": "11.22.33.44"},
        )

    # IP B should still have a fresh budget — its 1st request must NOT be throttled.
    # Use a different email so the email-key bucket from IP A's requests can't throttle it.
    # We verify by checking that get_user_by_email was invoked (throttle returns early).
    called = {"n": 0}
    monkeypatch.setattr(app_module, "get_user_by_email",
                        lambda e: called.__setitem__("n", called["n"] + 1) or None)
    r = client_b.post(
        "/api/auth/forgot-password",
        json={"email": "ipb-unique@example.com"},
        headers={"CF-Connecting-IP": "99.88.77.66"},
    )
    assert r.status_code == 200
    assert called["n"] >= 1, "IP B budget was shared with IP A — keying bug still present"
