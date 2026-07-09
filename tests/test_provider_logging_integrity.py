"""PR I: production logging integrity — _suppress_yf_call must never touch
the process-global sys.stdout/sys.stderr.

Root cause (2026-07-08): the old implementation wrapped yfinance calls in
contextlib.redirect_stdout/redirect_stderr inside ThreadPoolExecutor workers.
redirect_* swaps the GLOBAL sys.stdout — not thread-safe — and under the app's
concurrent request pools production stdout ended up permanently bound to a
dead StringIO, silently swallowing every print() in the process
([rate_limit][WARN], [api_error], deep-worker output) for the entire 27-day
warn window.

These tests pin: stream identity survives normal / concurrent / timed-out
provider calls; prints (including representative [api_error] and
[rate_limit][WARN] lines) remain observable afterwards; timeout/fallback
semantics are unchanged; suppression stays scoped to the yfinance logger.
"""
import logging
import sys
import time as _time
from concurrent.futures import ThreadPoolExecutor

import pytest

from providers.openbb_provider import OpenBBProvider


# ---------------------------------------------------------------------------
# 1-3. Stream identity survives provider calls
# ---------------------------------------------------------------------------

def test_streams_intact_after_normal_call():
    out, err = sys.stdout, sys.stderr
    assert OpenBBProvider._suppress_yf_call(lambda: 42) == 42
    assert sys.stdout is out
    assert sys.stderr is err


def test_streams_intact_after_concurrent_calls():
    out, err = sys.stdout, sys.stderr

    def _mixed(i):
        if i % 3 == 0:
            return OpenBBProvider._suppress_yf_call(lambda: _time.sleep(0.05) or i)
        if i % 3 == 1:
            return OpenBBProvider._suppress_yf_call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        return OpenBBProvider._suppress_yf_call(lambda: i)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_mixed, range(24)))
    assert sys.stdout is out
    assert sys.stderr is err


def test_streams_intact_after_timed_out_worker_completes():
    """A call that exceeds its timeout (returns None) whose worker finishes
    later must not disturb the global streams once it completes."""
    out, err = sys.stdout, sys.stderr

    def _slow():
        _time.sleep(0.3)
        print("late worker output", flush=True)
        return "late"

    assert OpenBBProvider._suppress_yf_call(_slow, timeout=0.05) is None
    _time.sleep(0.4)  # let the abandoned worker finish for certain
    assert sys.stdout is out
    assert sys.stderr is err


# ---------------------------------------------------------------------------
# 4-6. Application print output stays observable afterwards
# ---------------------------------------------------------------------------

def test_prints_observable_after_provider_calls(capsys):
    OpenBBProvider._suppress_yf_call(lambda: 1)
    OpenBBProvider._suppress_yf_call(lambda: _time.sleep(0.2), timeout=0.05)
    print("post-provider observability check", flush=True)
    assert "post-provider observability check" in capsys.readouterr().out


def test_api_error_print_capturable_after_provider_calls(capsys):
    pytest.importorskip("fastapi")
    from app import _api_error
    OpenBBProvider._suppress_yf_call(lambda: _time.sleep(0.2), timeout=0.05)
    _time.sleep(0.3)
    _api_error("get_chart", RuntimeError("SECRET_INTERNAL_DETAIL"), 400, "public")
    out = capsys.readouterr().out
    assert "[api_error] handler=get_chart" in out
    assert "SECRET_INTERNAL_DETAIL" in out


def test_rate_limit_warn_print_capturable_after_provider_calls(capsys):
    OpenBBProvider._suppress_yf_call(lambda: _time.sleep(0.2), timeout=0.05)
    _time.sleep(0.3)
    # Representative of app.py's rate_limit_middleware warn line.
    print("[rate_limit][WARN] would-429 bucket=auth_login path=/api/auth/login ip=203.0.113.9",
          flush=True)
    assert "would-429 bucket=auth_login" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 7. Timeout / fallback semantics unchanged
# ---------------------------------------------------------------------------

def test_fast_call_returns_value():
    assert OpenBBProvider._suppress_yf_call(lambda: {"a": 1}) == {"a": 1}


def test_hanging_call_returns_none():
    assert OpenBBProvider._suppress_yf_call(lambda: _time.sleep(0.5), timeout=0.05) is None


def test_raising_call_returns_none():
    def _boom():
        raise ValueError("provider exploded")
    assert OpenBBProvider._suppress_yf_call(_boom) is None


# ---------------------------------------------------------------------------
# 8. Suppression scoped to the yfinance logger only
# ---------------------------------------------------------------------------

def test_yfinance_logger_suppressed():
    assert logging.getLogger("yfinance").level == logging.CRITICAL


def test_unrelated_loggers_not_silenced():
    for name in ("uvicorn", "uvicorn.access", "httpx", "app", "services"):
        lg = logging.getLogger(name)
        assert lg.level != logging.CRITICAL, f"logger {name} was silenced"
        assert not lg.disabled, f"logger {name} was disabled"
    assert logging.getLogger().level != logging.CRITICAL  # root untouched


def test_no_stream_redirection_in_source():
    """Structural lint: the provider module must never reintroduce
    process-global stream redirection."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "providers" / "openbb_provider.py").read_text(encoding="utf-8")
    for banned in ("redirect_stdout", "redirect_stderr", "sys.stdout =", "sys.stderr ="):
        assert banned not in src, f"banned stream mutation found: {banned}"
