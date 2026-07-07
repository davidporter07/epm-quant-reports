"""Guardrails from the 2026-07-07 eval:
  FIX 3b (extended) — FUTURE econ-event weekday corrector now also handles the
      weekday-AFTER-event, non-possessive form ("... Minutes scheduled for Thursday").
  FIX (econ direction) — flip an econ print's directional verb when it contradicts
      its own month-over-month numbers ("payrolls surged to 57k vs 129k prior").
"""
import json
import pytest

gmc = pytest.importorskip("generate_market_commentary")


def _write_cal(tmp_path, events):
    (tmp_path / "economic_calendar.json").write_text(
        json.dumps({"events": events}), encoding="utf-8")


# --- FIX 3b extended: weekday AFTER the event --------------------------------

def test_fomc_weekday_after_event_scheduled_for(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    _write_cal(tmp_path, [{"date": "2026-07-08", "event": "Fed FOMC Minutes",
                           "importance": "high"}])  # 2026-07-08 is a Wednesday
    data = {"report_date": "2026-07-07",
            "equities_commentary":
            "Traders are watching the Fed FOMC Minutes scheduled for Thursday to gauge the path."}
    n = gmc._correct_future_econ_event_weekday(data)
    assert n == 1
    assert "scheduled for Wednesday" in data["equities_commentary"]
    assert "Thursday" not in data["equities_commentary"]


def test_fomc_weekday_after_event_due(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    _write_cal(tmp_path, [{"date": "2026-07-08", "event": "Fed FOMC Minutes",
                           "importance": "high"}])
    data = {"report_date": "2026-07-07",
            "cross_asset_synthesis": "The FOMC Minutes are due Thursday."}
    gmc._correct_future_econ_event_weekday(data)
    assert "due Wednesday" in data["cross_asset_synthesis"]


def test_after_event_correct_weekday_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    _write_cal(tmp_path, [{"date": "2026-07-08", "event": "Fed FOMC Minutes",
                           "importance": "high"}])
    data = {"report_date": "2026-07-07",
            "equities_commentary": "The Fed FOMC Minutes scheduled for Wednesday are the catalyst."}
    assert gmc._correct_future_econ_event_weekday(data) == 0


def test_after_event_unrelated_weekday_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    _write_cal(tmp_path, [{"date": "2026-07-08", "event": "Fed FOMC Minutes",
                           "importance": "high"}])
    # A weekday not linked to the event by a scheduling phrase must be left alone.
    data = {"report_date": "2026-07-07",
            "equities_commentary": "The Fed FOMC Minutes loom, and stocks rallied Thursday last week."}
    assert gmc._correct_future_econ_event_weekday(data) == 0


def test_possessive_before_event_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    _write_cal(tmp_path, [{"date": "2026-07-08", "event": "Fed FOMC Minutes",
                           "importance": "high"}])
    data = {"report_date": "2026-07-07",
            "cross_asset_synthesis": "Fragile ahead of Thursday's FOMC minutes."}
    gmc._correct_future_econ_event_weekday(data)
    assert "Wednesday's FOMC minutes" in data["cross_asset_synthesis"]


# --- econ-print direction guard ----------------------------------------------

def test_payrolls_surged_but_declined_is_flipped():
    data = {"economics_commentary":
            "Nonfarm Payrolls surged to 57k vs 129k prior, and unemployment fell to 4.2%."}
    n = gmc._correct_econ_print_direction(data)
    assert n == 1
    assert "Nonfarm Payrolls fell to 57k vs 129k prior" in data["economics_commentary"]


def test_correct_up_direction_preserved():
    original = "Payrolls rose to 129k vs 57k prior, extending the rebound."
    data = {"economics_commentary": original}
    assert gmc._correct_econ_print_direction(data) == 0
    assert data["economics_commentary"] == original


def test_down_verb_contradicting_rise_is_flipped():
    data = {"economics_commentary": "The index fell to 55k vs 42k prior."}
    gmc._correct_econ_print_direction(data)
    assert "rose to 55k vs 42k prior" in data["economics_commentary"]


def test_expectation_baseline_not_touched():
    # "vs 45k expected" is actual-vs-consensus, not MoM — must be left alone.
    original = "Payrolls surged to 57k vs 45k expected."
    data = {"economics_commentary": original}
    assert gmc._correct_econ_print_direction(data) == 0


def test_unit_mismatch_not_touched():
    original = "Sales surged to 5m vs 129k prior."
    data = {"economics_commentary": original}
    assert gmc._correct_econ_print_direction(data) == 0


def test_capitalized_verb_case_preserved():
    data = {"session_recap": ["Surged to 57k vs 129k prior on a soft print."]}
    gmc._correct_econ_print_direction(data)
    assert data["session_recap"][0].startswith("Fell to 57k vs 129k prior")
