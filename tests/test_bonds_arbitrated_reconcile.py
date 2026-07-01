"""Tests for _reconcile_bonds_with_arbitrated in generate_market_commentary.

Regression 2026-07-01: Treasury.gov's daily-yield XML lagged a session (its latest row was
6/29's 10Y=4.372) and _fetch_treasury_gov_yields blindly treated it as the 6/30 close. That
stale value was synced into the snapshot and inverted the rates narrative ("10Y fell 2 bp"
when it actually rose ~6 bp). The fresh arbitrated (YCharts) curve had 10Y=4.44; the reconciler
prefers it and treats the stale Treasury.gov value as the prior session to recover the change.
"""
import generate_market_commentary as gmc


def _arb_curve():
    # Fresh arbitrated (YCharts) levels for the 6/30 close.
    return {
        "2-Year Yield":  {"level": 4.14},
        "10-Year Yield": {"level": 4.44},
        "30-Year Yield": {"level": 4.91},
    }


def test_lagging_treasury_10y_reconciled_to_arbitrated():
    bonds = {
        "2-Year Yield":  {"level": 4.11, "change": -0.01, "pct_change": -0.24},
        "10-Year Yield": {"level": 4.372, "change": -0.020, "pct_change": -0.46},
        "30-Year Yield": {"level": 4.864, "change": 0.006, "pct_change": 0.12},
        "10s-2s Spread": {"level": 26.2, "change": None, "pct_change": None},
    }
    n = gmc._reconcile_bonds_with_arbitrated(bonds, _arb_curve())
    assert n == 3
    y10 = bonds["10-Year Yield"]
    assert y10["level"] == 4.44                 # adopted the fresh level
    assert y10["change"] == 0.068               # 4.44 - 4.372 (stale row = prior session)
    assert y10["change"] > 0                     # direction now correct (rose)
    assert y10["_reconciled"] == "arbitrated_curve"
    # spread rebuilt off reconciled 2Y/10Y: (4.44 - 4.14) * 100 = 30.0 bp
    assert bonds["10s-2s Spread"]["level"] == 30.0


def test_fresh_treasury_left_alone():
    # Treasury.gov agrees with the arbitrated curve within rounding → keep it (don't churn).
    bonds = {
        "2-Year Yield":  {"level": 4.14, "change": 0.03},
        "10-Year Yield": {"level": 4.44, "change": 0.06},
        "30-Year Yield": {"level": 4.91, "change": 0.05},
    }
    before = {k: dict(v) for k, v in bonds.items()}
    assert gmc._reconcile_bonds_with_arbitrated(bonds, _arb_curve()) == 0
    assert bonds == before


def test_insane_divergence_not_applied():
    # A >50 bp/day gap is a data artefact, not a real move — don't apply it.
    bonds = {"10-Year Yield": {"level": 3.50, "change": 0.0}}
    assert gmc._reconcile_bonds_with_arbitrated(bonds, {"10-Year Yield": {"level": 4.44}}) == 0
    assert bonds["10-Year Yield"]["level"] == 3.50


def test_missing_treasury_tenor_adopts_arbitrated():
    bonds = {}  # Treasury.gov gave nothing for 10Y
    n = gmc._reconcile_bonds_with_arbitrated(bonds, {"10-Year Yield": {"level": 4.44, "change": 0.06}})
    assert n == 1
    assert bonds["10-Year Yield"]["level"] == 4.44
    assert bonds["10-Year Yield"]["change"] == 0.06


def test_reconcile_noops_on_empty():
    assert gmc._reconcile_bonds_with_arbitrated({}, {}) == 0
    assert gmc._reconcile_bonds_with_arbitrated({"10-Year Yield": {"level": 4.37}}, {}) == 0
    assert gmc._reconcile_bonds_with_arbitrated(None, {"10-Year Yield": {"level": 4.44}}) == 0
