"""Tests for _correct_yield_bp_magnitude in generate_market_commentary.

2026-07-02: the reconciled curve carried 30Y +5 bp but the model wrote "the 30-year yield
climbed 10 bp", and called a POSITIVE +32 bp 2s10s spread a "curve inversion". This corrector
forces each tenor's stated bp move to the authoritative arbitrated (YCharts) curve and fixes
the inverted/positive-spread mislabel.
"""
import json
from datetime import datetime

import generate_market_commentary as gmc


def _write_arb(tmp_path, monkeypatch, changes, levels):
    """Write a market_data_arbitrated.json dated TODAY and point DATA_DIR at it."""
    curve = {}
    for tenor in ("2-Year Yield", "10-Year Yield", "30-Year Yield"):
        curve[tenor] = {"level": levels[tenor], "change": changes[tenor]}
    (tmp_path / "market_data_arbitrated.json").write_text(json.dumps({
        "arbitrated_date": datetime.today().strftime("%Y-%m-%d"),
        "yield_curve": curve,
    }), encoding="utf-8")
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)


def test_wrong_30y_bp_corrected_to_curve(tmp_path, monkeypatch):
    _write_arb(tmp_path, monkeypatch,
               changes={"2-Year Yield": 0.04, "10-Year Yield": 0.06, "30-Year Yield": 0.05},
               levels={"2-Year Yield": 4.17, "10-Year Yield": 4.48, "30-Year Yield": 4.97})
    data = {"fixed_income_commentary":
            "The 10-year yield rose 6 bp to 4.49% while the 30-year yield climbed 10 bp to 4.98%. "
            "The 2-year yield increased 3 bp to 4.17%."}
    n = gmc._correct_yield_bp_magnitude(data)
    assert n == 1                                   # only the 30Y was materially wrong
    assert "30-year yield climbed 5 bp" in data["fixed_income_commentary"]
    assert "10-year yield rose 6 bp" in data["fixed_income_commentary"]   # correct, untouched
    assert "2-year yield increased 3 bp" in data["fixed_income_commentary"]  # 1bp gap tolerated


def test_positive_spread_inversion_label_fixed(tmp_path, monkeypatch):
    _write_arb(tmp_path, monkeypatch,
               changes={"2-Year Yield": 0.04, "10-Year Yield": 0.06, "30-Year Yield": 0.05},
               levels={"2-Year Yield": 4.17, "10-Year Yield": 4.48, "30-Year Yield": 4.97})
    data = {"fixed_income_commentary": "This curve inversion reflects a hawkish Fed; the curve remains inverted."}
    n = gmc._correct_yield_bp_magnitude(data)
    assert n >= 2
    assert "inversion" not in data["fixed_income_commentary"].lower()
    assert "positive" in data["fixed_income_commentary"].lower()


def test_correct_values_not_churned(tmp_path, monkeypatch):
    _write_arb(tmp_path, monkeypatch,
               changes={"2-Year Yield": 0.03, "10-Year Yield": 0.06, "30-Year Yield": 0.06},
               levels={"2-Year Yield": 4.17, "10-Year Yield": 4.48, "30-Year Yield": 4.97})
    text = "The 10-year yield rose 6 bp and the 30-year yield rose 6 bp to 4.97%."
    data = {"fixed_income_commentary": text}
    assert gmc._correct_yield_bp_magnitude(data) == 0
    assert data["fixed_income_commentary"] == text


def test_inverted_curve_kept_when_actually_inverted(tmp_path, monkeypatch):
    # 2Y above 10Y → genuinely inverted → do NOT rewrite the label.
    _write_arb(tmp_path, monkeypatch,
               changes={"2-Year Yield": 0.02, "10-Year Yield": 0.01, "30-Year Yield": 0.01},
               levels={"2-Year Yield": 4.60, "10-Year Yield": 4.40, "30-Year Yield": 4.50})
    data = {"fixed_income_commentary": "This curve inversion reflects recession risk."}
    assert gmc._correct_yield_bp_magnitude(data) == 0
    assert "curve inversion" in data["fixed_income_commentary"]


def test_stale_arbitrated_date_noops(tmp_path, monkeypatch):
    (tmp_path / "market_data_arbitrated.json").write_text(json.dumps({
        "arbitrated_date": "2020-01-01",
        "yield_curve": {"30-Year Yield": {"level": 4.97, "change": 0.05}},
    }), encoding="utf-8")
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    data = {"fixed_income_commentary": "The 30-year yield climbed 10 bp to 4.98%."}
    assert gmc._correct_yield_bp_magnitude(data) == 0   # stale curve → don't touch


def test_bp_fix_applies_in_nested_and_recap(tmp_path, monkeypatch):
    _write_arb(tmp_path, monkeypatch,
               changes={"2-Year Yield": 0.04, "10-Year Yield": 0.06, "30-Year Yield": 0.05},
               levels={"2-Year Yield": 4.17, "10-Year Yield": 4.48, "30-Year Yield": 4.97})
    data = {
        "session_recap": ["The 30-year yield climbed 10 bp to 4.98%."],
        "asset_class_outlooks": {"Fixed Income": {"rationale": "The 30-year yield jumped 12 bp."}},
    }
    n = gmc._correct_yield_bp_magnitude(data)
    assert n == 2
    assert "5 bp" in data["session_recap"][0]
    assert "5 bp" in data["asset_class_outlooks"]["Fixed Income"]["rationale"]
