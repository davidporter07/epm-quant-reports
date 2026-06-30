"""Walk-forward backtest harness for the production DL model.

These tests cover the deterministic, no-training logic: decision-date spacing,
the look-ahead-free matured cutoff, and the scorer (independent N, Wilson CI,
significance). Actual TCN training is exercised by the smoke run, not unit tests.
"""
import numpy as np
import pandas as pd
import pytest

wf = pytest.importorskip("dl_walkforward_backtest")


def _panel(n_dates=400, tickers=("AAPL", "MSFT"), seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_dates)
    rows = []
    for t in tickers:
        for i, d in enumerate(dates):
            # Last HORIZON dates have no matured forward return (label NaN).
            tgt = rng.normal(0, 0.05) if i < n_dates - wf.HORIZON else np.nan
            rows.append({"Date": d, "Ticker": t, "Close": 100 + i, "Target_Forward_21D": tgt})
    return pd.DataFrame(rows)


# --- decision-date spacing ----------------------------------------------------

def test_decision_dates_are_horizon_spaced():
    p = _panel()
    dec = wf._decision_dates(p, None, None, cycles=0, step=wf.HORIZON)
    days = pd.to_datetime(pd.Series(dec))
    # Consecutive decision dates are HORIZON trading rows apart -> non-overlapping
    # 21-day forward windows by construction.
    all_dates = wf._all_dates(p[pd.to_numeric(p["Target_Forward_21D"], errors="coerce").notna()])
    idx = [all_dates.index(pd.Timestamp(d)) for d in dec]
    gaps = np.diff(idx)
    assert (gaps == wf.HORIZON).all()


def test_cycles_keeps_most_recent():
    p = _panel()
    dec_all = wf._decision_dates(p, None, None, cycles=0, step=wf.HORIZON)
    dec_3 = wf._decision_dates(p, None, None, cycles=3, step=wf.HORIZON)
    assert len(dec_3) == 3
    assert dec_3 == dec_all[-3:]


def test_only_labeled_dates_are_decision_dates():
    p = _panel()
    dec = wf._decision_dates(p, None, None, cycles=0, step=1)
    labeled_max = pd.to_datetime(
        p[pd.to_numeric(p["Target_Forward_21D"], errors="coerce").notna()]["Date"]
    ).max()
    # No decision date may fall in the un-matured tail.
    assert max(dec) <= labeled_max


# --- scorer -------------------------------------------------------------------

def _results(signs_by_ticker):
    rows = []
    for t, signs in signs_by_ticker.items():
        for i, s in enumerate(signs):
            # Forecast always +1%; realized sign chosen by the test.
            rows.append({"RunDate": f"2026-0{1 + i % 9}-01", "Ticker": t,
                         "Model": "DeepLearning_WF", "Horizon": 21,
                         "ForecastPct": 1.0, "RealizedPct": float(s)})
    return pd.DataFrame(rows)


def test_scorer_counts_independent_n_and_hitrate():
    res = _results({"AAPL": [1, 1, -1, 1]})  # 3 of 4 correct vs +1 forecast
    summary = wf.score_walkforward(res)
    row = summary[summary["Ticker"] == "AAPL"].iloc[0]
    assert row["N_Independent"] == 4.0
    assert row["Directional_Accuracy"] == pytest.approx(0.75)


def test_scorer_small_sample_not_significant():
    res = _results({"AAPL": [1, 1, -1]})  # 2/3
    summary = wf.score_walkforward(res)
    row = summary[summary["Ticker"] == "AAPL"].iloc[0]
    assert row["Significant"] == 0.0
    assert row["Dir_CI_Lower"] < 0.5 < row["Dir_CI_Upper"]


def test_scorer_large_consistent_sample_is_significant():
    res = _results({"AAPL": [1] * 30})  # 30/30 correct
    summary = wf.score_walkforward(res)
    row = summary[summary["Ticker"] == "AAPL"].iloc[0]
    assert row["Directional_Accuracy"] == pytest.approx(1.0)
    assert row["Significant"] == 1.0
    assert row["Dir_CI_Lower"] > 0.5


def test_scorer_pools_all_tickers():
    res = _results({"AAPL": [1, 1, 1], "MSFT": [1, 1, 1]})
    summary = wf.score_walkforward(res)
    allrow = summary[summary["Ticker"] == "ALL"].iloc[0]
    # Pooled across tickers = 6 independent obs, more than either ticker alone.
    assert allrow["N_Independent"] == 6.0
