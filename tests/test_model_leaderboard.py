"""Non-overlapping directional-accuracy metric for the model leaderboard.

Daily forecasts of a 21-trading-day return overlap ~95%, so a hit-rate over all of them
is built on only a few independent outcomes. _metrics now also reports the honest hit-rate
over the independent (non-overlapping) windows.
"""
import numpy as np
import pandas as pd
import pytest

mlb = pytest.importorskip("model_leaderboard")


def _synthetic_group(realized_signs, ticker="AAPL", n=63, horizon=21):
    """n consecutive business-day forecasts (all +1) with chosen realized signs on the
    three windows the greedy non-overlap selector will keep (indices 0, 21, 42)."""
    dates = pd.bdate_range("2026-01-01", periods=n + horizon + 5)
    realized = [1.0] * n  # default positive (matches the +1 forecast)
    for idx, sign in realized_signs.items():
        realized[idx] = sign
    rows = []
    for i in range(n):
        rows.append({
            "Ticker": ticker,
            "Model": "DeepLearning",
            "StartTradingDay": dates[i].date().isoformat(),
            "EndTradingDay": dates[i + horizon].date().isoformat(),
            "ForecastPct": 1.0,
            "RealizedPct": realized[i],
            "CI_Lower": np.nan,
            "CI_Upper": np.nan,
        })
    return pd.DataFrame(rows)


def test_nonoverlap_selects_one_window_per_horizon():
    g = _synthetic_group({})
    keep = mlb._greedy_nonoverlap(g)
    # 63 daily forecasts / 21-day horizon -> 3 independent windows.
    assert len(keep) == 3
    # The kept windows must not overlap: each start >= previous end.
    s = pd.to_datetime(keep["StartTradingDay"]).tolist()
    e = pd.to_datetime(keep["EndTradingDay"]).tolist()
    assert all(s[i] >= e[i - 1] for i in range(1, len(s)))


def test_metrics_reports_honest_hitrate():
    # Picked windows are indices 0, 21, 42; make 2 of 3 correct (forecast is +1).
    g = _synthetic_group({0: 5.0, 21: 3.0, 42: -2.0})
    m = mlb._metrics(g)
    assert m["N_NonOverlap"] == 3.0
    assert m["Directional_Accuracy_NO"] == pytest.approx(2 / 3)
    # The overlapping figure is computed over all 63 rows — a different (larger) sample.
    assert m["N"] == 63.0


def test_nonoverlap_pools_per_ticker():
    # Two tickers, each contributing 3 independent windows -> 6 pooled, not collapsed.
    g = pd.concat([_synthetic_group({}, ticker="AAPL"),
                   _synthetic_group({}, ticker="MSFT")], ignore_index=True)
    assert len(mlb._nonoverlap_pool(g)) == 6


# --- Wilson CI + significance on the independent hit-rate ----------------------

def test_wilson_interval_brackets_proportion():
    lo, hi = mlb._wilson_interval(2, 3)
    assert 0.0 <= lo <= 2 / 3 <= hi <= 1.0
    # Tiny sample -> wide interval that still includes a coin flip.
    assert lo < 0.5 < hi


def test_wilson_interval_zero_n_is_nan():
    lo, hi = mlb._wilson_interval(0, 0)
    assert np.isnan(lo) and np.isnan(hi)


def test_small_sample_hitrate_is_not_significant():
    # 2 of 3 right on independent windows — a coin flip can't be ruled out.
    g = _synthetic_group({0: 5.0, 21: 3.0, 42: -2.0})
    m = mlb._metrics(g)
    assert m["N_NonOverlap"] == 3.0
    assert m["Dir_NO_Significant"] == 0.0
    assert m["Dir_NO_CI_Lower"] < 0.5 < m["Dir_NO_CI_Upper"]


def test_strong_independent_sample_is_significant():
    # Build many independent windows that are mostly correct, so the Wilson CI
    # clears 0.5 and the model reads as a genuine directional edge.
    n = 21 * 20 + 5  # ~20 independent windows
    g = _synthetic_group({}, n=n)  # all forecasts +1, all realized +1 -> 100% hit
    m = mlb._metrics(g)
    assert m["N_NonOverlap"] >= 18
    assert m["Directional_Accuracy_NO"] == pytest.approx(1.0)
    assert m["Dir_NO_Significant"] == 1.0
    assert m["Dir_NO_CI_Lower"] > 0.5
