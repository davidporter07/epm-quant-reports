"""PR F commit 3: new rate-limit buckets behind RATE_LIMIT_ENFORCE=0.

Tests cover:
- warn mode: over-limit requests still return 200 + log [rate_limit][WARN]
- enforce mode: over-limit returns 429 + Retry-After + Cache-Control:no-store
- bucket isolation (auth_login spam doesn't burn data_cheap budget)
- /api/health + OPTIONS are never limited
- deep_enqueue per-user and per-IP independent budgets
"""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

try:
    from fastapi.testclient import TestClient
    import app as app_module
    from app import app
except Exception as exc:
    pytest.skip(f"web app deps unavailable: {exc}", allow_module_level=True)


@pytest.fixture(autouse=True)
def _clear_rl_store():
    app_module._RL_STORE.clear()
    yield
    app_module._RL_STORE.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def enforce_client(monkeypatch):
    monkeypatch.setattr(app_module, "_RATE_LIMIT_ENFORCE", True)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Warn mode (default): over-limit requests still succeed, log is emitted
# ---------------------------------------------------------------------------

def test_warn_mode_over_limit_still_200(client, capsys):
    """In warn mode the request proceeds (200) even over the auth_login bucket limit."""
    # Exhaust the auth_login bucket for this IP (15/300s).
    for _ in range(15):
        app_module._rate_limited("rl:auth_login:testclient", 15, 300)

    # Next request is over-limit. In warn mode it must still reach the handler.
    # POST /api/auth/login will 422 (bad body) or 401, not 429.
    r = client.post(
        "/api/auth/login",
        json={"username": "u", "password": "p", "remember_me": False},
        headers={"CF-Connecting-IP": "testclient"},
    )
    assert r.status_code != 429, "warn mode must not return 429"


def test_warn_mode_logs_would_429(client, capsys):
    """Over-limit in warn mode must emit [rate_limit][WARN] would-429."""
    for _ in range(15):
        app_module._rate_limited("rl:auth_login:testip", 15, 300)

    client.post(
        "/api/auth/login",
        json={"username": "u", "password": "p", "remember_me": False},
        headers={"CF-Connecting-IP": "testip"},
    )
    out = capsys.readouterr().out
    assert "[rate_limit][WARN]" in out
    assert "would-429" in out
    assert "auth_login" in out


# ---------------------------------------------------------------------------
# Enforce mode: 429 + Retry-After + no-store
# ---------------------------------------------------------------------------

def test_enforce_mode_returns_429_after_limit(enforce_client):
    """auth_login bucket: exactly 15 succeed then 16th is 429."""
    for i in range(15):
        r = enforce_client.post(
            "/api/auth/login",
            json={"username": "u", "password": "p", "remember_me": False},
            headers={"CF-Connecting-IP": "enforcetestip"},
        )
        assert r.status_code != 429, f"request {i+1} should not be 429 yet"

    r16 = enforce_client.post(
        "/api/auth/login",
        json={"username": "u", "password": "p", "remember_me": False},
        headers={"CF-Connecting-IP": "enforcetestip"},
    )
    assert r16.status_code == 429


def test_enforce_mode_429_has_retry_after(enforce_client):
    for _ in range(15):
        app_module._rate_limited("rl:auth_login:raip", 15, 300)

    r = enforce_client.post(
        "/api/auth/login",
        json={"username": "u", "password": "p", "remember_me": False},
        headers={"CF-Connecting-IP": "raip"},
    )
    assert r.status_code == 429
    assert "retry-after" in r.headers


def test_enforce_mode_429_has_no_store(enforce_client):
    for _ in range(15):
        app_module._rate_limited("rl:auth_login:nsip", 15, 300)

    r = enforce_client.post(
        "/api/auth/login",
        json={"username": "u", "password": "p", "remember_me": False},
        headers={"CF-Connecting-IP": "nsip"},
    )
    assert r.status_code == 429
    assert "no-store" in r.headers.get("cache-control", "")


# ---------------------------------------------------------------------------
# Bucket isolation
# ---------------------------------------------------------------------------

def test_auth_login_spam_does_not_burn_data_cheap_budget(enforce_client):
    """Exhausting auth_login for an IP must not count against data_cheap."""
    for _ in range(15):
        app_module._rate_limited("rl:auth_login:isoip", 15, 300)

    # data_cheap bucket for the same IP should be untouched.
    r = enforce_client.get("/api/quotes", headers={"CF-Connecting-IP": "isoip"})
    assert r.status_code != 429, "data_cheap bucket was incorrectly shared with auth_login"


def test_auth_register_bucket_is_independent(enforce_client):
    """auth_register uses its own bucket (5/3600) independent of auth_login."""
    for _ in range(5):
        app_module._rate_limited("rl:auth_register:regip", 5, 3600)

    # auth_login budget for same IP must be untouched.
    r = enforce_client.post(
        "/api/auth/login",
        json={"username": "u", "password": "p", "remember_me": False},
        headers={"CF-Connecting-IP": "regip"},
    )
    assert r.status_code != 429


# ---------------------------------------------------------------------------
# Never-limited paths
# ---------------------------------------------------------------------------

def test_health_never_rate_limited(enforce_client):
    """POST to exhaust auth_login, then /api/health must still be 200."""
    for _ in range(20):
        app_module._rate_limited("rl:auth_login:hlip", 15, 300)

    r = enforce_client.get("/api/health", headers={"CF-Connecting-IP": "hlip"})
    assert r.status_code == 200


def test_options_never_rate_limited(enforce_client):
    """OPTIONS preflight must bypass rate limiting entirely."""
    for _ in range(200):
        app_module._rate_limited("rl:data_cheap:optip", 120, 60)

    r = enforce_client.options("/api/quotes", headers={"CF-Connecting-IP": "optip"})
    assert r.status_code != 429


# ---------------------------------------------------------------------------
# data_cheap bucket covers expected paths
# ---------------------------------------------------------------------------

def test_data_cheap_ticker_tape_is_limited(enforce_client):
    for _ in range(120):
        app_module._rate_limited("rl:data_cheap:tapeip", 120, 60)

    r = enforce_client.get("/api/ticker-tape", headers={"CF-Connecting-IP": "tapeip"})
    assert r.status_code == 429


def test_data_cheap_suggest_tickers_is_limited(enforce_client):
    for _ in range(120):
        app_module._rate_limited("rl:data_cheap:sugip", 120, 60)

    r = enforce_client.get("/api/suggest-tickers?q=AAPL", headers={"CF-Connecting-IP": "sugip"})
    assert r.status_code == 429


# ---------------------------------------------------------------------------
# data_expensive bucket
# ---------------------------------------------------------------------------

def test_data_expensive_snapshot_is_limited(enforce_client):
    for _ in range(30):
        app_module._rate_limited("rl:data_expensive:snapip", 30, 60)

    r = enforce_client.get("/api/snapshot?ticker=AAPL", headers={"CF-Connecting-IP": "snapip"})
    assert r.status_code == 429


# ---------------------------------------------------------------------------
# Production probe reproduction (2026-06-11): repeated real GETs to
# /api/suggest-tickers?q=aa must emit would-429 once the 120/60s window fills.
# The live probe saw no warn log because a sequential curl loop through
# Cloudflare TLS runs slower than 120 req per SLIDING 60s window — the limiter
# correctly never crossed the threshold. This test proves the full
# middleware → bucket-match → warn-log chain works for this exact endpoint.
# ---------------------------------------------------------------------------

def test_suggest_tickers_burst_emits_would_429_in_warn_mode(client, monkeypatch, capsys):
    """121 sequential GET /api/suggest-tickers?q=aa from one IP: all 200, and
    request 121 (first over-limit) must log [rate_limit][WARN] would-429."""
    # Stub the handler's data/network internals — the middleware under test
    # runs before the handler, but the request must complete end-to-end.
    monkeypatch.setattr(app_module, "_suggestion_index", lambda: ())
    monkeypatch.setattr(app_module, "_direct_symbol_candidate", lambda q: None)
    monkeypatch.setattr(app_module, "_remote_yf_suggestions", lambda q, limit: [])

    headers = {"CF-Connecting-IP": "probe-ip-2600"}

    for i in range(120):
        r = client.get("/api/suggest-tickers?q=aa", headers=headers)
        assert r.status_code == 200, f"request {i+1} failed: {r.text}"
    out_under = capsys.readouterr().out
    assert "would-429" not in out_under, "warn fired before the 120-request threshold"

    r121 = client.get("/api/suggest-tickers?q=aa", headers=headers)
    assert r121.status_code == 200, "warn mode must not block"
    out_over = capsys.readouterr().out
    assert "[rate_limit][WARN]" in out_over
    assert "would-429" in out_over
    assert "bucket=data_cheap" in out_over
    assert "path=/api/suggest-tickers" in out_over
    assert "ip=probe-ip-2600" in out_over
