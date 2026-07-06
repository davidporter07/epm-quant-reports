"""Guardrails from the 2026-07-06 eval (first post-relocation run):
  FIX 1 — inverted yield-causality scrub (yield RISE attributed to a soft/miss print)
  FIX 3b — FUTURE econ-event weekday corrector tolerant of dropped name prefixes
  FIX 4 — 'Risk-off' stance softened to 'Defensive rotation' on a subdued VIX
"""
import json
import pytest

gmc = pytest.importorskip("generate_market_commentary")


# --- FIX 1: inverted yield causality -----------------------------------------

def test_yield_rise_driven_by_pmi_miss_is_scrubbed():
    data = {"fixed_income_commentary":
            "The 10-year Treasury yield rose 4 bp to 4.49%, extending a recent "
            "upward move driven by the ISM Manufacturing PMI miss."}
    n = gmc._scrub_inverted_yield_causation(data)
    assert n == 1
    txt = data["fixed_income_commentary"]
    assert "miss" not in txt.lower()
    assert txt.rstrip().endswith("upward move.")


def test_synthesis_two_clause_keeps_move_drops_inversion():
    data = {"cross_asset_synthesis":
            "The S&P 500 closed flat at 7,483.24 as defensive sectors outpaced growth "
            "names, while the 10-year yield rose 4 bp to 4.49% driven by the ISM "
            "Manufacturing PMI miss."}
    gmc._scrub_inverted_yield_causation(data)
    txt = data["cross_asset_synthesis"]
    assert "ISM Manufacturing PMI miss" not in txt
    assert "the 10-year yield rose 4 bp to 4.49%" in txt
    assert "defensive sectors outpaced growth names" in txt


def test_hawkish_driver_for_yield_rise_is_preserved():
    original = ("The 10-year yield rose 4 bp to 4.49% as strong jobs data and sticky "
                "inflation sustained higher-for-longer rate expectations.")
    data = {"fixed_income_commentary": original}
    n = gmc._scrub_inverted_yield_causation(data)
    assert n == 0
    assert data["fixed_income_commentary"] == original


def test_yield_fall_on_soft_data_is_preserved():
    # A FALL attributed to a soft print is correct causality — must be left alone.
    original = "The 10-year yield fell 4 bp to 4.41% as the ISM PMI missed expectations."
    data = {"fixed_income_commentary": original}
    n = gmc._scrub_inverted_yield_causation(data)
    assert n == 0
    assert data["fixed_income_commentary"] == original


def test_inverted_yield_scrub_is_idempotent():
    data = {"fixed_income_commentary":
            "The 10-year yield rose 4 bp to 4.49% driven by the ISM PMI miss."}
    gmc._scrub_inverted_yield_causation(data)
    once = data["fixed_income_commentary"]
    gmc._scrub_inverted_yield_causation(data)
    assert data["fixed_income_commentary"] == once


# --- FIX 3b: FUTURE econ-event weekday, prefix-tolerant -----------------------

def _write_cal(tmp_path, events):
    (tmp_path / "economic_calendar.json").write_text(
        json.dumps({"events": events}), encoding="utf-8")


def test_fomc_minutes_weekday_fixed_despite_fed_prefix(tmp_path, monkeypatch):
    # Calendar name carries a 'Fed ' prefix the prose drops. 2026-07-08 is a Wednesday.
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    _write_cal(tmp_path, [{"date": "2026-07-08", "event": "Fed FOMC Minutes",
                           "importance": "high"}])
    data = {"report_date": "2026-07-06",
            "cross_asset_synthesis":
            "The environment stays fragile ahead of Thursday's FOMC minutes."}
    n = gmc._correct_future_econ_event_weekday(data)
    assert n == 1
    assert "Wednesday's FOMC minutes" in data["cross_asset_synthesis"]
    assert "Thursday's" not in data["cross_asset_synthesis"]


def test_correct_weekday_is_left_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    _write_cal(tmp_path, [{"date": "2026-07-08", "event": "Fed FOMC Minutes",
                           "importance": "high"}])
    data = {"report_date": "2026-07-06",
            "cross_asset_synthesis": "Watch Wednesday's FOMC minutes for the tone."}
    n = gmc._correct_future_econ_event_weekday(data)
    assert n == 0


# --- FIX 4: risk-off vs subdued VIX ------------------------------------------

def _defensive_sectors():
    # Defensives lead, cyclicals lag → the 'Risk-off, defensive bid' branch.
    return [
        {"ticker": "XLV", "name": "Health", "pct_change": 2.6},
        {"ticker": "XLU", "name": "Util", "pct_change": 2.2},
        {"ticker": "XLP", "name": "Staples", "pct_change": 2.0},
        {"ticker": "XLF", "name": "Fin", "pct_change": 1.5},
        {"ticker": "XLY", "name": "Disc", "pct_change": -0.8},
        {"ticker": "XLK", "name": "Tech", "pct_change": -2.7},
    ]


def test_subdued_vix_softens_riskoff_to_rotation():
    tp = gmc.build_tactical_positioning(None, _defensive_sectors(), 15.99)
    assert tp.get("stance") == "Defensive rotation"


def test_elevated_vix_keeps_riskoff_label():
    tp = gmc.build_tactical_positioning(None, _defensive_sectors(), 26.0)
    assert tp.get("stance", "").startswith("Risk-off, defensive bid")


def test_missing_vix_keeps_riskoff_label():
    tp = gmc.build_tactical_positioning(None, _defensive_sectors(), None)
    assert tp.get("stance", "").startswith("Risk-off, defensive bid")
