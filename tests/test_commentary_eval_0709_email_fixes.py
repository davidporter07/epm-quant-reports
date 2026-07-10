"""2026-07-09 email eval — the two shippable lower-priority fixes.

#2 10s-2s slope DIRECTION: the report said "narrowing the 10s-2s spread by 1 bp to 35 bps"
   while 10Y rose 7 bp vs 2Y +6 bp — the spread WIDENED (steepened). _fix_spread_direction
   recomputes the slope from the tenor deltas (the spread's own arbitrated change is a
   degenerate 0.0) and flips only the verb.

#3 stale macro prints: load_recent_macro_prints(recent_only=True) must drop a stale monthly
   series so the model can't recap a 39-day-old PCE as current inflation. (The ISM 53.3 the
   eval flagged was actually grounded + recent — this fix targets the genuinely-stale ones.)
"""
import json
from datetime import date, timedelta

import pytest

gmc = pytest.importorskip("generate_market_commentary")


# ---- #2 spread direction --------------------------------------------------------------

def test_spread_direction_flips_narrowing_when_widened():
    text = "The curve steepened as the 10s-2s spread narrowed by 1 bp to 35 bps."
    out, n = gmc._fix_spread_direction(text, spread_chg_bp=1.0)   # widened
    assert n == 1
    assert "widened by 1 bp to 35 bps" in out
    assert "narrowed" not in out


def test_spread_direction_flips_widening_when_narrowed():
    text = "The 10s-2s spread widened, steepening the yield curve."
    out, n = gmc._fix_spread_direction(text, spread_chg_bp=-2.0)  # flattened
    assert "narrowed" in out and "flattening" in out
    assert n == 2


def test_spread_direction_preserves_figures_and_case():
    text = "Flattening the 2s10s spread by 3 bps."
    out, _ = gmc._fix_spread_direction(text, spread_chg_bp=4.0)   # steepened
    assert out.startswith("Steepening")
    assert "by 3 bps" in out


def test_spread_direction_ignores_credit_spread():
    text = "Credit spreads narrowed as risk appetite returned."
    out, n = gmc._fix_spread_direction(text, spread_chg_bp=5.0)
    assert n == 0 and out == text


def test_spread_direction_noop_when_flat_or_unknown():
    text = "The 10s-2s spread narrowed slightly."
    assert gmc._fix_spread_direction(text, 0.2)[1] == 0     # sub-0.5bp: ambiguous
    assert gmc._fix_spread_direction(text, None)[1] == 0


def test_yield_bp_corrector_flips_spread_direction_end_to_end(tmp_path, monkeypatch):
    # 10Y +7bp, 2Y +6bp -> spread +1bp (widened); prose says "narrowing" -> must flip.
    arb = {
        "arbitrated_date": date.today().strftime("%Y-%m-%d"),
        "yield_curve": {
            "2-Year Yield":  {"level": 4.21, "change": 0.060},
            "10-Year Yield": {"level": 4.56, "change": 0.070},
            "30-Year Yield": {"level": 5.06, "change": 0.060},
        },
    }
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    (tmp_path / "market_data_arbitrated.json").write_text(json.dumps(arb), encoding="utf-8")
    data = {"fixed_income_commentary":
            "The curve stayed positively sloped, narrowing the 10s-2s spread by 1 bp to 35 bps."}
    gmc._correct_yield_bp_magnitude(data)
    assert "widening the 10s-2s spread by 1 bp to 35 bps" in data["fixed_income_commentary"]


# ---- #3 stale macro prints ------------------------------------------------------------

def _write_econ(tmp_path, monkeypatch, econ):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    (tmp_path / "market_data_arbitrated.json").write_text(
        json.dumps({"economics": econ}), encoding="utf-8")


def test_recent_only_drops_stale_monthly(tmp_path, monkeypatch):
    # Uses PPI (a stale NON-inflation-anchor series) so the drop is tested independently of the
    # 2026-07-10 inflation-anchor exception (which retains one CPI/PCE gauge — see the 0710 file).
    today = date.today()
    fresh = (today - timedelta(days=2)).strftime("%Y-%m-%d")     # weekly claims, recent
    stale = (today - timedelta(days=39)).strftime("%Y-%m-%d")    # PPI ~39d old, not recent
    _write_econ(tmp_path, monkeypatch, {
        "Initial Jobless Claims": {"value": 215000, "prev_value": 210000, "date": fresh},
        "PPI (YoY)":              {"value": 0.065,  "prev_value": 0.065,  "date": stale},
    })
    monkeypatch.setattr(gmc, "_recent_calendar_release_names", lambda cutoff: set())

    all_rows = {r["indicator"] for r in gmc.load_recent_macro_prints()}
    assert "PPI (YoY)" in all_rows                       # default keeps it (contract intact)

    recent_rows = {r["indicator"] for r in gmc.load_recent_macro_prints(recent_only=True)}
    assert "Initial Jobless Claims" in recent_rows
    assert "PPI (YoY)" not in recent_rows                # recent_only drops the stale non-anchor print
