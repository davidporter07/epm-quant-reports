"""2026-07-10 email eval fixes.

The synthesis was the weak field: it inverted a yield direction ("the 10-year yield's 1 bp
fall" while the 10Y rose +1bp) and named the wrong CPI weekday ("Thursday's CPI" — it's
Tuesday). Plus a "higher higher-for-longer" duplication in the recap, and economics went
bland after the stale-macro drop. Four targeted fixes:

  #1 _fix_yield_direction — flip a yield verb/noun to the arbitrated tenor-change sign
     (yields are excluded from _correct_direction_words, so they had no guard).
  #2 _name_variants leading-acronym — bind a possessive weekday to "CPI print" when the
     calendar event is "CPI Inflation Report".
  #3 _dedup_repeated_words — collapse an adjacent duplicate function word / modifier.
  #4 load_recent_macro_prints(recent_only=True) keeps ONE inflation anchor as context.
"""
import json
from datetime import date, timedelta

import pytest

gmc = pytest.importorskip("generate_market_commentary")


# ---- #1 yield direction ---------------------------------------------------------------

def _arb(tmp_path, monkeypatch, y2, y10, y30):
    arb = {
        "arbitrated_date": date.today().strftime("%Y-%m-%d"),
        "yield_curve": {
            "2-Year Yield":  {"level": 4.16, "change": y2},
            "10-Year Yield": {"level": 4.54, "change": y10},
            "30-Year Yield": {"level": 5.05, "change": y30},
        },
    }
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    (tmp_path / "market_data_arbitrated.json").write_text(json.dumps(arb), encoding="utf-8")


def test_yield_noun_fall_flipped_when_rose(tmp_path, monkeypatch):
    _arb(tmp_path, monkeypatch, 0.02, 0.01, 0.01)   # all rose
    data = {"cross_asset_synthesis": "The 10-year yield's 1 bp fall confirms the easing."}
    gmc._correct_yield_bp_magnitude(data)
    assert "1 bp rise" in data["cross_asset_synthesis"]
    assert "fall" not in data["cross_asset_synthesis"]


def test_yield_verb_slipped_flipped_when_rose(tmp_path, monkeypatch):
    _arb(tmp_path, monkeypatch, 0.02, 0.01, 0.01)
    data = {"fixed_income_commentary":
            "The 30-year yield slipped 1 bp to 5.05%, while the 2-year yield climbed 2 bp to 4.16%."}
    gmc._correct_yield_bp_magnitude(data)
    assert "30-year yield rose 1 bp" in data["fixed_income_commentary"]
    assert "2-year yield climbed 2 bp" in data["fixed_income_commentary"]   # already correct, untouched


def test_yield_verb_flipped_down_when_fell(tmp_path, monkeypatch):
    _arb(tmp_path, monkeypatch, -0.02, -0.03, -0.02)   # all fell
    data = {"fixed_income_commentary": "The 10-year yield climbed 3 bp as inflation fears built."}
    gmc._correct_yield_bp_magnitude(data)
    assert "10-year yield slipped 3 bp" in data["fixed_income_commentary"]


def test_yield_direction_leaves_correct_verb_and_flat_tenor(tmp_path, monkeypatch):
    _arb(tmp_path, monkeypatch, 0.02, 0.0, 0.01)   # 10Y flat
    data = {"fixed_income_commentary": "The 10-year yield eased on the auction."}
    gmc._correct_yield_bp_magnitude(data)
    assert data["fixed_income_commentary"] == "The 10-year yield eased on the auction."  # <0.5bp: skip


def test_yield_direction_does_not_cross_into_other_tenor_clause(tmp_path, monkeypatch):
    _arb(tmp_path, monkeypatch, 0.02, -0.03, 0.01)   # 2Y up, 10Y down
    data = {"fixed_income_commentary": "The 2-year yield rose 2 bp and the 10-year yield fell 3 bp."}
    gmc._correct_yield_bp_magnitude(data)
    # 2Y rose (correct, kept); 10Y fell (correct, kept) — no cross-contamination
    assert "2-year yield rose 2 bp" in data["fixed_income_commentary"]
    assert "10-year yield fell 3 bp" in data["fixed_income_commentary"]


# ---- #2 weekday acronym ---------------------------------------------------------------

def test_weekday_acronym_binds_cpi(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    cal = {"events": [{"date": "2026-07-14", "event": "CPI Inflation Report"}]}
    (tmp_path / "economic_calendar.json").write_text(json.dumps(cal), encoding="utf-8")
    data = {"report_date": "2026-07-10",
            "cross_asset_synthesis": "Thursday's CPI print is the critical threshold."}
    assert gmc._correct_future_econ_event_weekday(data) == 1
    assert data["cross_asset_synthesis"].startswith("Tuesday's CPI")


# ---- #3 dedup -------------------------------------------------------------------------

def test_dedup_higher_higher():
    data = {"session_recap": ["markets priced in higher higher-for-longer rate path risks"]}
    assert gmc._dedup_repeated_words(data) == 1
    assert data["session_recap"][0] == "markets priced in higher-for-longer rate path risks"


def test_dedup_leaves_distinct_words():
    data = {"equities_commentary": "The higher yield weighed on lower-rated credit."}
    assert gmc._dedup_repeated_words(data) == 0


# ---- #4 inflation anchor --------------------------------------------------------------

def test_recent_only_keeps_one_inflation_anchor(tmp_path, monkeypatch):
    today = date.today()
    fresh = (today - timedelta(days=2)).strftime("%Y-%m-%d")
    stale = (today - timedelta(days=39)).strftime("%Y-%m-%d")
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    (tmp_path / "market_data_arbitrated.json").write_text(json.dumps({"economics": {
        "Initial Jobless Claims": {"value": 215000, "prev_value": 210000, "date": fresh},
        "Core PCE (YoY)":         {"value": 0.034,  "prev_value": 0.034,  "date": stale},
        "PPI (YoY)":              {"value": 0.065,  "prev_value": 0.065,  "date": stale},
    }}), encoding="utf-8")
    monkeypatch.setattr(gmc, "_recent_calendar_release_names", lambda cutoff: set())
    kept = {r["indicator"] for r in gmc.load_recent_macro_prints(recent_only=True)}
    assert "Initial Jobless Claims" in kept
    assert "Core PCE (YoY)" in kept     # inflation anchor retained as context
    assert "PPI (YoY)" not in kept      # other stale prints still dropped
