"""PR H commit C1: _api_error helper — server-side logging, controlled public detail.

The helper is the single conversion point for unexpected exceptions on data
endpoints: the real exception repr goes to the service journal (stdout,
flush=True) with the [api_error] prefix; the API client receives only the
caller-supplied public message under the existing {"detail": ...} envelope
and the caller's original status code. No handler calls it yet (C1 adds the
helper + tests only; C2 migrates the 8 leak sites).
"""
import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException

from app import _api_error


# Forward slashes so the string survives repr() verbatim (backslashes would be
# escape-doubled in the logged repr and defeat the literal containment check).
PLANTED = "SECRET_INTERNAL_PATH /opt/providers/yfinance/creds.py line 42"


def test_returns_http_exception_with_status_and_public_detail():
    exc = ValueError("boom")
    result = _api_error("get_snapshot", exc, 400, "Snapshot data is unavailable.")
    assert isinstance(result, HTTPException)
    assert result.status_code == 400
    assert result.detail == "Snapshot data is unavailable."


def test_preserves_caller_status_code_500():
    result = _api_error("get_live_quotes", RuntimeError("x"), 500, "Quotes unavailable.")
    assert result.status_code == 500


def test_logs_handler_name_and_exception_repr(capsys):
    exc = RuntimeError("connection reset by provider")
    _api_error("get_chart", exc, 400, "Chart data is unavailable.")
    out = capsys.readouterr().out
    assert "[api_error]" in out
    assert "handler=get_chart" in out
    assert repr(exc) in out


def test_planted_internal_string_reaches_log_but_never_detail(capsys):
    exc = FileNotFoundError(PLANTED)
    result = _api_error("get_fund_page_payload", exc, 400, "Fund page data is unavailable.")
    out = capsys.readouterr().out
    assert PLANTED in out                       # ops can diagnose from the journal
    assert PLANTED not in str(result.detail)    # the client never sees internals
    assert "SECRET_INTERNAL_PATH" not in str(result.detail)


def test_returns_rather_than_raises():
    """Callers `raise _api_error(...)` — the helper itself must not raise."""
    try:
        result = _api_error("h", Exception("e"), 400, "m")
    except Exception as exc:  # pragma: no cover
        pytest.fail(f"_api_error raised instead of returning: {exc!r}")
    assert isinstance(result, HTTPException)
