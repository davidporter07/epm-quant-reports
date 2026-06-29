"""verify_fresh roll must not corrupt a FRESH daily bar with a STALE fast_info close.

2026-06-29 regression: Nasdaq 100's true -1.09% Friday close (daily bar 29,118.24) was
flipped to +1.11% because fast_info.previous_close lagged a session (29,440.32, Thursday)
and the roll swapped the fresh latest into prev. Guarded by a date-staleness gate.
"""
from datetime import datetime, timedelta

import pytest

pd = pytest.importorskip("pandas")
gmc = pytest.importorskip("generate_market_commentary")


class _FakeFastInfo:
    def __init__(self, previous_close):
        self.previous_close = previous_close
        self.last_price = previous_close


class _FakeTicker:
    def __init__(self, prev_close):
        self.fast_info = _FakeFastInfo(prev_close)


class _FakeYF:
    """Minimal yfinance stand-in: a fixed download frame + a fixed fast_info."""
    def __init__(self, frame, fast_prev_close):
        self._frame = frame
        self._fast_prev_close = fast_prev_close

    def download(self, *a, **k):
        return self._frame

    def Ticker(self, ticker):
        return _FakeTicker(self._fast_prev_close)


def _frame(dates_and_closes):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in dates_and_closes])
    return pd.DataFrame({"Close": [c for _, c in dates_and_closes]}, index=idx)


def test_fresh_bar_is_not_rolled_by_stale_fast_info(monkeypatch):
    today = datetime.today().date()
    lcs = gmc._last_completed_session(today)          # last completed session (fresh-bar date)
    prev_sess = gmc._last_completed_session(lcs)       # session before it
    # Daily bar is FRESH (carries the last completed session); fast_info lags a session.
    frame = _frame([(prev_sess, 29440.32), (lcs, 29118.24)])
    monkeypatch.setattr(gmc, "yf", _FakeYF(frame, fast_prev_close=29440.32))

    q = gmc._fetch_quote("^NDX", verify_fresh=True)
    assert q is not None
    assert q["level"] == pytest.approx(29118.24, abs=0.01), "fresh bar must be kept"
    assert q["pct_change"] < 0, "Friday Nasdaq fell — sign must not invert to +"


def test_genuinely_stale_bar_still_rolls_forward(monkeypatch):
    today = datetime.today().date()
    lcs = gmc._last_completed_session(today)
    prev_sess = gmc._last_completed_session(lcs)
    older = gmc._last_completed_session(prev_sess)
    # Daily bar is STALE (latest dated prev_sess, one session behind lcs); fast_info is fresh.
    frame = _frame([(older, 29220.06), (prev_sess, 29440.32)])
    monkeypatch.setattr(gmc, "yf", _FakeYF(frame, fast_prev_close=29118.24))

    q = gmc._fetch_quote("^NDX", verify_fresh=True)
    assert q is not None
    assert q["level"] == pytest.approx(29118.24, abs=0.01), "stale bar must roll to official close"


def test_last_completed_session_skips_weekend():
    # Monday's last completed session is the prior Friday, never Sunday/Saturday.
    monday = datetime(2026, 6, 29).date()   # a Monday
    lcs = gmc._last_completed_session(monday)
    assert lcs == datetime(2026, 6, 26).date()
