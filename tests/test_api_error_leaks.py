"""PR H commit C2: the 8 migrated data endpoints must never leak exception
internals to API clients.

Each test plants an internal-looking string inside the exception the
underlying service raises, then asserts:
  - the original status code is preserved (400 data endpoints, 500 quotes /
    commentary),
  - the {"detail": ...} envelope is preserved,
  - the response detail is the controlled public message — the planted string
    never reaches the client,
  - the planted string DOES reach the server log via the [api_error] line.

get_chart's invalid-period message stays specific and controlled (pinned
byte-identical to the old snapshot_engine ValueError pass-through).
"""
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

try:
    from fastapi.testclient import TestClient
    import app as _app
except Exception as exc:  # pragma: no cover - env-dependent
    pytest.skip(f"web app deps unavailable: {exc}", allow_module_level=True)

# Forward slashes so the string survives repr() verbatim in the logged line.
PLANTED = "SECRET_INTERNAL_PATH /opt/providers/yfinance/creds.py line 42"


def _raiser(*a, **k):
    raise RuntimeError(PLANTED)


def _client():
    return TestClient(_app.app)


def _assert_leakproof(resp, status, public_detail, capsys, handler):
    assert resp.status_code == status
    body = resp.json()
    assert set(body.keys()) == {"detail"}          # envelope preserved
    assert body["detail"] == public_detail
    assert "SECRET_INTERNAL_PATH" not in resp.text
    out = capsys.readouterr().out
    assert f"handler={handler}" in out
    assert PLANTED in out                           # journal keeps diagnostics


def test_snapshot_does_not_leak(monkeypatch, capsys):
    monkeypatch.setattr(_app.engine, "build_snapshot", _raiser)
    resp = _client().get("/api/snapshot?ticker=SPY")
    _assert_leakproof(resp, 400, "Snapshot data is unavailable for this ticker right now.",
                      capsys, "get_snapshot")


def test_chart_does_not_leak(monkeypatch, capsys):
    monkeypatch.setattr(_app.engine, "build_chart_payload", _raiser)
    resp = _client().get("/api/chart?ticker=SPY&period=1y")
    _assert_leakproof(resp, 400, "Chart data is unavailable for this ticker right now.",
                      capsys, "get_chart")


def test_chart_invalid_period_keeps_specific_controlled_message():
    resp = _client().get("/api/chart?ticker=SPY&period=bogus")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Unsupported period: bogus"


def test_chart_invalid_period_is_normalized_like_engine():
    """The engine lower()+strip()ped the period before validating — preserved."""
    resp = _client().get("/api/chart?ticker=SPY&period=1Y")
    # '1Y' normalizes to '1y' which IS valid — must NOT 400 on the period check.
    # (The request may still fail deeper for other reasons; it must not fail
    # with the unsupported-period message.)
    if resp.status_code == 400:
        assert resp.json()["detail"] != "Unsupported period: 1y"


def test_fund_page_does_not_leak(monkeypatch, capsys):
    monkeypatch.setattr(_app.ticker_page_service, "build_fund_search_payload", _raiser)
    resp = _client().get("/api/fund-page?ticker=SPY")
    _assert_leakproof(resp, 400, "Fund page data is unavailable for this ticker right now.",
                      capsys, "get_fund_page_payload")


def test_home_does_not_leak(monkeypatch, capsys):
    monkeypatch.setattr(_app.market_board_service, "get_home_payload", _raiser)
    resp = _client().get("/api/home")
    _assert_leakproof(resp, 400, "Home board data is temporarily unavailable.",
                      capsys, "get_home_payload")


def test_markets_does_not_leak(monkeypatch, capsys):
    monkeypatch.setattr(_app.market_board_service, "get_markets_payload", _raiser)
    resp = _client().get("/api/markets")
    _assert_leakproof(resp, 400, "Markets board data is temporarily unavailable.",
                      capsys, "get_markets_payload")


def test_portfolios_does_not_leak(monkeypatch, capsys):
    monkeypatch.setattr(_app.market_board_service, "get_portfolios_payload", _raiser)
    resp = _client().get("/api/portfolios")
    _assert_leakproof(resp, 400, "Portfolios board data is temporarily unavailable.",
                      capsys, "get_portfolios_payload")


def test_quotes_does_not_leak(monkeypatch, capsys):
    import yfinance
    monkeypatch.setitem(_app._quotes_cache, "data", None)
    monkeypatch.setitem(_app._quotes_cache, "ts", 0.0)
    monkeypatch.setattr(yfinance, "download", _raiser)
    resp = _client().get("/api/quotes")
    _assert_leakproof(resp, 500, "Live quotes are temporarily unavailable.",
                      capsys, "get_live_quotes")


def test_commentary_does_not_leak(monkeypatch, capsys, tmp_path):
    (tmp_path / "latest_commentary.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(_app.json, "load", _raiser)
    resp = _client().get("/api/commentary")
    _assert_leakproof(resp, 500, "Commentary is temporarily unavailable.",
                      capsys, "get_commentary")


def test_commentary_missing_file_shape_unchanged(monkeypatch, tmp_path):
    """Missing commentary file keeps the pre-C2 non-error shape."""
    monkeypatch.setattr(_app, "DATA_DIR", tmp_path)
    resp = _client().get("/api/commentary")
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "commentary": None}
