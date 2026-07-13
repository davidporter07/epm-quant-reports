"""2026-07-13 email-eval fixes. The escalating geo grounding (correct for the weekend Hormuz
escalation) was applied to Friday's de-escalation recap, and several corrector gaps surfaced:

  #6 _fix_yield_direction learns "edged/ticked up/down" (30Y "edged up" vs a -1bp fall).
  #7 _scrub_oil_escalation_inversion — an oil DECLINE can't be "driven by" an escalation.
  #8 _correct_event_relative_week — "CPI ... next week" when CPI is this week.
  #9 _correct_gold_level_polarity — gold above = fear ON, below = fear OFF.
  #10 build_tactical_positioning demotes a value-led + defensive-co-leading tape to Mixed.
  #11 _scrub_ungrounded_earnings_driver — "Nvidia delivered a blockbuster quarter" not in sources.
"""
import json
from datetime import date, timedelta

import pytest

gmc = pytest.importorskip("generate_market_commentary")


# ---- #6 yield edged/ticked ------------------------------------------------------------

def _arb(tmp_path, monkeypatch, y2, y10, y30):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    (tmp_path / "market_data_arbitrated.json").write_text(json.dumps({
        "arbitrated_date": date.today().strftime("%Y-%m-%d"),
        "yield_curve": {
            "2-Year Yield":  {"level": 4.21, "change": y2},
            "10-Year Yield": {"level": 4.56, "change": y10},
            "30-Year Yield": {"level": 5.06, "change": y30},
        }}), encoding="utf-8")


def test_yield_edged_up_flipped_when_fell(tmp_path, monkeypatch):
    _arb(tmp_path, monkeypatch, -0.05, -0.02, -0.01)   # 30Y fell 1bp
    data = {"fixed_income_commentary": "The 30-year yield edged up 1 bp to 5.06%."}
    gmc._correct_yield_bp_magnitude(data)
    assert "edged down 1 bp" in data["fixed_income_commentary"]


def test_yield_ticked_down_flipped_when_rose(tmp_path, monkeypatch):
    _arb(tmp_path, monkeypatch, 0.05, 0.03, 0.02)      # all rose
    data = {"fixed_income_commentary": "The 10-year yield ticked down 3 bp."}
    gmc._correct_yield_bp_magnitude(data)
    assert "ticked up 3 bp" in data["fixed_income_commentary"]


# ---- #7 oil escalation inversion ------------------------------------------------------

def test_oil_escalation_inversion_stripped():
    snap = {"WTI Crude": {"pct_change": -0.93}}
    data = {"session_recap": ["WTI Crude fell to $71.41, -0.93%, driven by reports that Iran "
                              "closed the Strait of Hormuz and expanded attacks on Gulf states."]}
    assert gmc._scrub_oil_escalation_inversion(data, snap) == 1
    out = data["session_recap"][0]
    assert "hormuz" not in out.lower() and "-0.93%" in out


def test_oil_escalation_noop_when_oil_rose():
    snap = {"WTI Crude": {"pct_change": 3.2}}   # oil up -> escalation causation is coherent
    data = {"commodities_commentary": "WTI Crude rose 3.2% as Iran closed the Strait of Hormuz."}
    assert gmc._scrub_oil_escalation_inversion(data, snap) == 0


def test_oil_easing_decline_left_alone():
    snap = {"WTI Crude": {"pct_change": -1.5}}
    data = {"commodities_commentary": "WTI Crude fell 1.5% as ceasefire hopes drained the risk premium."}
    # 'ceasefire hopes' is an easing driver, not an escalation keyword -> untouched
    assert gmc._scrub_oil_escalation_inversion(data, snap) == 0


# ---- #8 relative week -----------------------------------------------------------------

def test_next_week_corrected_to_this_week(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    (tmp_path / "economic_calendar.json").write_text(
        json.dumps({"events": [{"date": "2026-07-14", "event": "CPI Inflation Report"}]}), encoding="utf-8")
    data = {"report_date": "2026-07-13",
            "watch_today": ["Monitor the 10-year yield ahead of the CPI report next week."]}
    assert gmc._correct_event_relative_week(data) == 1
    assert "this week" in data["watch_today"][0] and "next week" not in data["watch_today"][0]


def test_next_week_left_when_event_genuinely_next_week(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    (tmp_path / "economic_calendar.json").write_text(
        json.dumps({"events": [{"date": "2026-07-27", "event": "CPI Inflation Report"}]}), encoding="utf-8")
    data = {"report_date": "2026-07-13",
            "watch_today": ["The CPI report next week is the key catalyst."]}
    assert gmc._correct_event_relative_week(data) == 0   # genuinely next week -> untouched


# ---- #9 gold polarity -----------------------------------------------------------------

def test_gold_above_easing_flipped_to_rising():
    data = {"levels_to_watch": [{"asset": "Gold", "level": 4128.26, "significance":
            "A breach above indicates de-escalating inflation fears while a drop below reflects a stronger dollar."}]}
    assert gmc._correct_gold_level_polarity(data) == 1
    sig = data["levels_to_watch"][0]["significance"]
    assert "rising inflation fears" in sig
    assert "de-escalating" not in sig
    assert "stronger dollar" in sig   # correct 'below' side untouched


# ---- #10 stance demotion --------------------------------------------------------------

def _sec(t, n, p):
    return {"ticker": t, "name": n, "pct_change": p}


def test_value_led_defensive_coleading_demoted_to_mixed():
    sectors = [_sec("XLB", "Matrl", 1.2), _sec("XLP", "Stapl", 1.1), _sec("XLC", "Comm", 1.0),
               _sec("XLU", "Util", 0.6), _sec("XLI", "Indus", 0.5), _sec("XLY", "Disc", 0.3),
               _sec("XLF", "Fin", 0.3), _sec("XLK", "Tech", 0.2), _sec("XLV", "Health", -0.8)]
    tp = gmc.build_tactical_positioning(None, sectors, 15.0)
    assert tp["stance"] == "Mixed signals", tp["stance"]


def test_growth_led_tape_still_risk_on():
    sectors = [_sec("XLK", "Tech", 1.6), _sec("XLY", "Disc", 1.3), _sec("XLF", "Fin", 1.0),
               _sec("XLI", "Indus", 0.4), _sec("XLU", "Util", -0.8), _sec("XLP", "Stapl", -1.0),
               _sec("XLV", "Health", -1.2)]
    tp = gmc.build_tactical_positioning(None, sectors, 16.0)
    assert tp["stance"].startswith("Risk-on"), tp["stance"]


# ---- #11 ungrounded earnings driver ---------------------------------------------------

def test_ungrounded_earnings_driver_hedged(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    (tmp_path / "enrichment.json").write_text(json.dumps({
        "earnings_calendar": [{"symbol": "FBK"}, {"symbol": "AERO"}],
        "company_news": [], "market_news": []}), encoding="utf-8")
    data = {"session_recap": ["S&P 500 rose 0.42% as Nvidia and SanDisk delivered blockbuster "
                              "quarters that pulled the sector higher."]}
    assert gmc._scrub_ungrounded_earnings_driver(data) == 1
    out = data["session_recap"][0]
    assert "Nvidia and SanDisk led gains" in out
    assert "blockbuster" not in out


def test_grounded_earnings_driver_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    (tmp_path / "enrichment.json").write_text(json.dumps({
        "earnings_calendar": [{"symbol": "NVDA"}],   # NVDA reported -> grounded, keep
        "company_news": [], "market_news": []}), encoding="utf-8")
    data = {"session_recap": ["Nvidia delivered a blockbuster quarter that lifted chips."]}
    assert gmc._scrub_ungrounded_earnings_driver(data) == 0
    assert "blockbuster quarter" in data["session_recap"][0]


def test_unrecognised_name_not_touched(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    (tmp_path / "enrichment.json").write_text(json.dumps({
        "earnings_calendar": [], "company_news": [], "market_news": []}), encoding="utf-8")
    data = {"session_recap": ["Acme Widgets delivered a blockbuster quarter."]}
    assert gmc._scrub_ungrounded_earnings_driver(data) == 0   # unknown -> cannot verify -> leave
