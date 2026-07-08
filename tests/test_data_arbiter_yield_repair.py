"""Tests for the degenerate yield-curve change-column repair in data_arbiter.

Regression 2026-06-30: nearly every Treasury tenor printed "+0.000%" because the YCharts
'previous' point resolved to the same observation as the latest (prev_value == level),
fabricating a flat curve and a bogus "yields held 0 bp" narrative. The repair cross-checks
a degenerate change column against FRED's distinct two-point series and recomputes only the
changes FRED proves are real, keeping the YCharts levels untouched.
"""
import pytest

import data_arbiter as da


@pytest.fixture(autouse=True)
def _no_ambient_yield_history(monkeypatch):
    """Isolate the prior-session fallback from any real data/yield_level_history.json so the
    FRED-path tests assert FRED behavior only. Prior-session tests re-patch this."""
    monkeypatch.setattr(da, "_load_yield_history", lambda: {})


def _frozen_curve():
    """A curve whose change column is degenerate (every tenor change == 0)."""
    tenors = {
        "1-Month Yield": 3.71, "3-Month Yield": 3.87, "6-Month Yield": 4.00,
        "1-Year Yield": 3.97, "2-Year Yield": 4.10, "3-Year Yield": 4.10,
        "5-Year Yield": 4.14, "7-Year Yield": 4.24, "10-Year Yield": 4.38,
        "20-Year Yield": 4.86, "30-Year Yield": 4.86,
    }
    return {lbl: {"level": lv, "change": 0.0, "pct_change": 0.0,
                  "prev_value": lv, "source": "ycharts"}
            for lbl, lv in tenors.items()}


def test_frozen_curve_repaired_from_fred(monkeypatch):
    curve = _frozen_curve()
    # FRED shows the curve actually moved (a real session), so changes must be recomputed.
    fake_fred = {
        "10Y": {"value": 4.37, "prev_value": 4.32},   # +5 bp
        "2Y":  {"value": 4.11, "prev_value": 4.09},   # +2 bp
        "30Y": {"value": 4.86, "prev_value": 4.87},   # -1 bp
    }
    monkeypatch.setattr(da, "_fetch_fred_yield_curve", lambda: fake_fred)
    n = da._repair_degenerate_yield_curve(curve)
    assert n == 3
    # Level preserved, change taken from FRED's delta.
    assert curve["10-Year Yield"]["level"] == 4.38
    assert curve["10-Year Yield"]["change"] == 0.05
    assert curve["10-Year Yield"]["change_source"] == "fred_recompute"
    assert curve["30-Year Yield"]["change"] == -0.01
    # Tenors FRED didn't cover stay flat (no fabricated change).
    assert curve["5-Year Yield"]["change"] == 0.0


def test_genuinely_flat_curve_left_alone(monkeypatch):
    curve = _frozen_curve()
    # FRED agrees the session was flat — nothing to repair.
    flat_fred = {"10Y": {"value": 4.38, "prev_value": 4.38},
                 "2Y": {"value": 4.10, "prev_value": 4.10}}
    monkeypatch.setattr(da, "_fetch_fred_yield_curve", lambda: flat_fred)
    assert da._repair_degenerate_yield_curve(curve) == 0
    assert curve["10-Year Yield"]["change"] == 0.0


def test_healthy_curve_skips_fred(monkeypatch):
    # A curve with real dispersion must not even call FRED.
    curve = _frozen_curve()
    curve["10-Year Yield"]["change"] = 0.05
    curve["2-Year Yield"]["change"] = 0.03
    curve["30-Year Yield"]["change"] = -0.02
    curve["5-Year Yield"]["change"] = 0.04
    curve["7-Year Yield"]["change"] = 0.03

    def _boom():
        raise AssertionError("FRED should not be queried for a healthy curve")
    monkeypatch.setattr(da, "_fetch_fred_yield_curve", _boom)
    assert da._repair_degenerate_yield_curve(curve) == 0


def test_fred_unavailable_leaves_curve(monkeypatch):
    curve = _frozen_curve()
    monkeypatch.setattr(da, "_fetch_fred_yield_curve", lambda: {})
    assert da._repair_degenerate_yield_curve(curve) == 0
    assert curve["10-Year Yield"]["change"] == 0.0


def test_insane_fred_delta_rejected(monkeypatch):
    # A 2-point FRED artefact (e.g. a missing obs producing a 3pp jump) must not be applied.
    curve = _frozen_curve()
    monkeypatch.setattr(da, "_fetch_fred_yield_curve",
                        lambda: {"10Y": {"value": 4.38, "prev_value": 1.00}})  # +338 bp — absurd
    assert da._repair_degenerate_yield_curve(curve) == 0
    assert curve["10-Year Yield"]["change"] == 0.0


def test_repair_noops_on_empty():
    assert da._repair_degenerate_yield_curve({}) == 0
    assert da._repair_degenerate_yield_curve(None) == 0


# --- prior-session fallback (2026-07-08: FRED lags a day, both sources flat) ----------

def test_prior_session_fallback_when_fred_lags(monkeypatch):
    curve = _frozen_curve()  # 10Y level 4.38, all changes 0
    monkeypatch.setattr(da, "_fetch_fred_yield_curve", lambda: {})  # FRED lags/unavailable
    monkeypatch.setattr(da, "TODAY_STR", "2026-07-08")
    monkeypatch.setattr(da, "_load_yield_history",
                        lambda: {"2026-07-07": {"10-Year Yield": 4.33, "2-Year Yield": 4.08}})
    n = da._repair_degenerate_yield_curve(curve)
    assert n == 2
    assert curve["10-Year Yield"]["change"] == 0.05          # 4.38 - 4.33
    assert curve["10-Year Yield"]["change_source"] == "prior_session"
    assert curve["2-Year Yield"]["change"] == 0.02
    assert curve["5-Year Yield"]["change"] == 0.0            # no prior level → stays flat


def test_prior_session_used_only_after_fred(monkeypatch):
    # FRED covers the 10Y; the prior-session sidecar fills a tenor FRED missed.
    curve = _frozen_curve()
    monkeypatch.setattr(da, "_fetch_fred_yield_curve",
                        lambda: {"10Y": {"value": 4.37, "prev_value": 4.32}})  # +5bp
    monkeypatch.setattr(da, "TODAY_STR", "2026-07-08")
    monkeypatch.setattr(da, "_load_yield_history",
                        lambda: {"2026-07-07": {"2-Year Yield": 4.07}})   # +3bp for 2Y
    da._repair_degenerate_yield_curve(curve)
    assert curve["10-Year Yield"]["change_source"] == "fred_recompute"
    assert curve["2-Year Yield"]["change"] == 0.03
    assert curve["2-Year Yield"]["change_source"] == "prior_session"


def test_prior_session_skipped_on_outage_gap(monkeypatch):
    curve = _frozen_curve()
    monkeypatch.setattr(da, "_fetch_fred_yield_curve", lambda: {})
    monkeypatch.setattr(da, "TODAY_STR", "2026-07-08")
    # prior stored session is 10 days stale (a pipeline outage) — don't span it as a "daily" move
    monkeypatch.setattr(da, "_load_yield_history",
                        lambda: {"2026-06-28": {"10-Year Yield": 4.10}})
    assert da._repair_degenerate_yield_curve(curve) == 0
    assert curve["10-Year Yield"]["change"] == 0.0


def test_prior_session_ignores_same_day_rerun(monkeypatch):
    curve = _frozen_curve()
    monkeypatch.setattr(da, "_fetch_fred_yield_curve", lambda: {})
    monkeypatch.setattr(da, "TODAY_STR", "2026-07-08")
    # only a same-day entry (a re-run) — no strictly-earlier baseline → leave flat
    monkeypatch.setattr(da, "_load_yield_history",
                        lambda: {"2026-07-08": {"10-Year Yield": 4.38}})
    assert da._repair_degenerate_yield_curve(curve) == 0


def test_prior_session_rejects_insane_move(monkeypatch):
    curve = _frozen_curve()
    monkeypatch.setattr(da, "_fetch_fred_yield_curve", lambda: {})
    monkeypatch.setattr(da, "TODAY_STR", "2026-07-08")
    monkeypatch.setattr(da, "_load_yield_history",
                        lambda: {"2026-07-07": {"10-Year Yield": 1.00}})   # +338bp absurd
    assert da._repair_degenerate_yield_curve(curve) == 0
    assert curve["10-Year Yield"]["change"] == 0.0


def test_persist_yield_levels_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "YIELD_HISTORY", tmp_path / "yh.json")
    monkeypatch.setattr(da, "_load_yield_history",
                        lambda: da._load_json(tmp_path / "yh.json") or {})
    da._persist_yield_levels({"10-Year Yield": {"level": 4.55}}, "2026-07-08")
    da._persist_yield_levels({"10-Year Yield": {"level": 4.60}}, "2026-07-09")
    hist = da._load_json(tmp_path / "yh.json")
    assert hist["2026-07-08"]["10-Year Yield"] == 4.55
    assert hist["2026-07-09"]["10-Year Yield"] == 4.60
