"""QuantConnect cross-sectional factor model.

Regression guard for the 6/29 fix: the old model collapsed five factors into one
fixed-weight scalar and regressed on it, producing near-constant forecasts for every
ticker. These tests assert the multivariate fit produces genuine cross-sectional
DISPERSION and reacts to a ticker's factor exposures.
"""
import numpy as np
import pandas as pd
import pytest

qc = pytest.importorskip("quantconnect_model")


def _synthetic_panel(n_dates=80, seed=0):
    """Panel where forward return is driven mostly by the 12M Return factor."""
    rng = np.random.default_rng(seed)
    tickers = qc.MAG7
    dates = pd.bdate_range("2025-01-01", periods=n_dates)
    rows = []
    for d in dates:
        for t in tickers:
            f = {
                "1M Return": rng.normal(0, 0.05),
                "3M Return": rng.normal(0, 0.08),
                "12M Return": rng.normal(0, 0.20),
                "Volatility": abs(rng.normal(0.3, 0.1)),
                "MA200 Gap": rng.normal(0, 0.10),
            }
            # Forward return is a real (noisy) function of the factors.
            fwd = 0.6 * f["12M Return"] - 0.3 * f["Volatility"] + 0.2 * f["1M Return"] + rng.normal(0, 0.01)
            rows.append({"Date": d, "Ticker": t, **f, "Forward Return": fwd})
    df = pd.DataFrame(rows).set_index("Date")
    return df


def test_zscore_handles_degenerate_input():
    s = pd.Series([2.0, 2.0, 2.0])
    z = qc._zscore(s)
    assert (z == 0.0).all()
    assert np.isfinite(z).all()


def test_fit_returns_model_with_enough_data():
    model = qc.fit_forecast_model(_synthetic_panel())
    assert model is not None


def test_fit_returns_none_when_too_few_rows():
    tiny = _synthetic_panel(n_dates=1).iloc[:3]
    assert qc.fit_forecast_model(tiny) is None


def test_forecast_is_dispersed_not_constant():
    """The core regression test: distinct tickers must get distinct forecasts."""
    panel = _synthetic_panel()
    model = qc.fit_forecast_model(panel)

    # Live cross-section with deliberately different factor exposures per ticker.
    live = pd.DataFrame([
        {"Ticker": "AAPL", "1M Return": 0.10, "3M Return": 0.15, "12M Return": 0.40, "Volatility": 0.20, "MA200 Gap": 0.10},
        {"Ticker": "MSFT", "1M Return": -0.05, "3M Return": -0.02, "12M Return": -0.30, "Volatility": 0.45, "MA200 Gap": -0.08},
        {"Ticker": "AMZN", "1M Return": 0.02, "3M Return": 0.05, "12M Return": 0.05, "Volatility": 0.30, "MA200 Gap": 0.00},
        {"Ticker": "NVDA", "1M Return": 0.20, "3M Return": 0.25, "12M Return": 0.60, "Volatility": 0.25, "MA200 Gap": 0.15},
        {"Ticker": "GOOG", "1M Return": -0.10, "3M Return": -0.12, "12M Return": -0.50, "Volatility": 0.50, "MA200 Gap": -0.12},
        {"Ticker": "META", "1M Return": 0.00, "3M Return": 0.00, "12M Return": 0.00, "Volatility": 0.35, "MA200 Gap": 0.00},
        {"Ticker": "TSLA", "1M Return": 0.05, "3M Return": -0.05, "12M Return": 0.10, "Volatility": 0.60, "MA200 Gap": 0.05},
    ])
    out = qc.forecast_cross_section(model, live)
    assert len(out) == 7
    fc = out["QuantConnect Forecast (%)"].to_numpy()
    # The old collapsed model produced a spread of ~0.16%; a working multivariate
    # model must disperse far more than that across these varied exposures.
    assert float(np.std(fc)) > 0.3
    assert (fc.max() - fc.min()) > 1.0


def test_high_momentum_ticker_beats_low_momentum():
    """12M Return is the dominant positive driver — the high-momentum, low-vol name
    should out-forecast the low-momentum, high-vol name."""
    panel = _synthetic_panel()
    model = qc.fit_forecast_model(panel)
    live = pd.DataFrame([
        {"Ticker": "HIGH", "1M Return": 0.15, "3M Return": 0.20, "12M Return": 0.60, "Volatility": 0.20, "MA200 Gap": 0.10},
        {"Ticker": "LOW", "1M Return": -0.10, "3M Return": -0.15, "12M Return": -0.50, "Volatility": 0.55, "MA200 Gap": -0.10},
    ])
    out = qc.forecast_cross_section(model, live).set_index("Ticker")
    assert out.loc["HIGH", "QuantConnect Forecast (%)"] > out.loc["LOW", "QuantConnect Forecast (%)"]


def test_forecast_cross_section_empty_on_no_model():
    out = qc.forecast_cross_section(None, pd.DataFrame({"Ticker": ["AAPL"], "1M Return": [0.1],
                                   "3M Return": [0.1], "12M Return": [0.1], "Volatility": [0.3], "MA200 Gap": [0.0]}))
    assert out.empty


def test_quant_score_weighted_composite():
    z = pd.Series({"1M Return": 1.0, "3M Return": 1.0, "12M Return": 1.0, "Volatility": 1.0, "MA200 Gap": 1.0})
    # All-ones z, weights sum to 1.0 -> composite 1.0
    assert abs(qc.quant_score(z) - 1.0) < 1e-9
