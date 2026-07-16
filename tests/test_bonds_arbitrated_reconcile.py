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
    # (_arb_curve carries no change values, so the change-alignment branch is a no-op here.)
    bonds = {
        "2-Year Yield":  {"level": 4.14, "change": 0.03},
        "10-Year Yield": {"level": 4.44, "change": 0.06},
        "30-Year Yield": {"level": 4.91, "change": 0.05},
    }
    before = {k: dict(v) for k, v in bonds.items()}
    assert gmc._reconcile_bonds_with_arbitrated(bonds, _arb_curve()) == 0
    assert bonds == before


def test_change_aligned_when_levels_agree():
    # 2026-07-02 regression: 30Y level agrees (~4.97) but bonds_tbl's daily change (+11 bp, off a
    # stale yfinance prior close) diverges from the authoritative arbitrated +5 bp. Adopt the
    # arbitrated change so the recap's "rose N bp" matches our curve; level stays put.
    bonds = {"30-Year Yield": {"level": 4.97, "change": 0.11, "pct_change": 2.27}}
    arb   = {"30-Year Yield": {"level": 4.97, "change": 0.05, "pct_change": 1.01}}
    assert gmc._reconcile_bonds_with_arbitrated(bonds, arb) == 1
    y30 = bonds["30-Year Yield"]
    assert y30["level"] == 4.97                    # unchanged — levels already agreed
    assert y30["change"] == 0.05                   # aligned to the authoritative curve
    assert y30["pct_change"] == 1.01
    assert y30["_reconciled"] == "arbitrated_change"


def test_sign_inverting_arbitrated_change_rejected():
    # 2026-07-15 regression: levels agree (~4.58) but the arbitrated change (+6 bp, off a stale
    # prev_value) INVERTS the sign vs Treasury.gov's own consecutive-row change (−4 bp, 4.62 →
    # 4.58). Keep Treasury.gov's own change so the recap doesn't ship "10Y rose 6 bp" on a day it
    # fell. Without the guard this shipped an inverted rates narrative to subscribers.
    bonds = {"10-Year Yield": {"level": 4.58, "change": -0.04, "pct_change": -0.87}}
    arb   = {"10-Year Yield": {"level": 4.58, "change": 0.06, "pct_change": 1.31}}
    assert gmc._reconcile_bonds_with_arbitrated(bonds, arb) == 0
    y10 = bonds["10-Year Yield"]
    assert y10["change"] == -0.04                  # Treasury.gov's own (correct) change kept
    assert y10["change"] < 0                        # direction preserved (fell)
    assert "_reconciled" not in y10                 # arbitrated change was NOT adopted


def test_same_sign_magnitude_gap_still_aligned():
    # Guard must NOT regress the 2026-07-02 case: same sign (both up), magnitude differs
    # (+11 vs +5) → still adopt the authoritative arbitrated change.
    bonds = {"30-Year Yield": {"level": 4.97, "change": 0.11, "pct_change": 2.27}}
    arb   = {"30-Year Yield": {"level": 4.97, "change": 0.05, "pct_change": 1.01}}
    assert gmc._reconcile_bonds_with_arbitrated(bonds, arb) == 1
    assert bonds["30-Year Yield"]["change"] == 0.05
    assert bonds["30-Year Yield"]["_reconciled"] == "arbitrated_change"


def test_sign_conflict_below_1bp_is_noise_not_blocked():
    # A "sign conflict" where one side is sub-1 bp is just rounding noise around zero, not a
    # real inversion — the guard should NOT trigger; normal adoption proceeds.
    bonds = {"10-Year Yield": {"level": 4.58, "change": -0.004, "pct_change": -0.09}}
    arb   = {"10-Year Yield": {"level": 4.58, "change": 0.03, "pct_change": 0.66}}
    assert gmc._reconcile_bonds_with_arbitrated(bonds, arb) == 1
    assert bonds["10-Year Yield"]["change"] == 0.03
    assert bonds["10-Year Yield"]["_reconciled"] == "arbitrated_change"


def test_change_not_touched_when_already_agrees():
    # Levels agree AND daily changes agree within rounding → no churn.
    bonds = {"10-Year Yield": {"level": 4.48, "change": 0.06, "pct_change": 1.34}}
    arb   = {"10-Year Yield": {"level": 4.48, "change": 0.061, "pct_change": 1.35}}
    before = {k: dict(v) for k, v in bonds.items()}
    assert gmc._reconcile_bonds_with_arbitrated(bonds, arb) == 0
    assert bonds == before


def test_change_alignment_skips_insane_arb_change():
    # A >50 bp arbitrated daily change is an artefact — don't adopt it even if levels agree.
    bonds = {"10-Year Yield": {"level": 4.48, "change": 0.06}}
    arb   = {"10-Year Yield": {"level": 4.48, "change": 0.90}}
    assert gmc._reconcile_bonds_with_arbitrated(bonds, arb) == 0
    assert bonds["10-Year Yield"]["change"] == 0.06


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
