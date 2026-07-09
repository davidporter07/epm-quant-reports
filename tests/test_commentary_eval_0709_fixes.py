"""Guardrail from the 2026-07-09 blocked send: WTI Crude closed +4.37% on the Iran
ceasefire collapse, but the LLM's commodities prose kept using bearish crude language
("selloff"/"collapse") that the flip map couldn't neutralize and that the field-global
numeric-consistency check flagged from anywhere in the field — so every retry failed,
the narrative fell back to deterministic prose, and the send gate blocked the email.

Two fixes:
  1. _DIR_DOWN_TO_UP / _DIR_UP_TO_DOWN learn selloff/sell-off/collapse so
     _correct_direction_words can actually flip them when they name the up asset.
  2. _check_numeric_consistency scopes its strong-word check to the asset's own
     sentence, so "gold plunged" (gold down) in the commodities field is no longer
     mis-attributed to WTI, and the validator only demands what the corrector delivers.
"""
import pytest

gmc = pytest.importorskip("generate_market_commentary")


def _snap(crude_pct=4.37, gold_pct=-1.2):
    return {
        "WTI Crude": {"pct_change": crude_pct},
        "Gold": {"pct_change": gold_pct},
        "S&P 500": {"pct_change": -0.28},
        "U.S. Dollar (DXY)": {"pct_change": 0.15},
    }


def test_corrector_flips_crude_selloff_on_up_day():
    data = {"commodities_commentary": "WTI crude saw a sharp selloff to $73.82."}
    n = gmc._correct_direction_words(data, _snap())
    assert n >= 1
    assert "selloff" not in data["commodities_commentary"].lower()
    # residual validator must now be clean
    assert not [v for v in gmc._check_numeric_consistency(data, _snap()) if "WTI" in v]


def test_corrector_flips_crude_collapse_on_up_day():
    data = {"commodities_commentary": "Crude collapsed even as tensions flared."}
    gmc._correct_direction_words(data, _snap())
    assert "collapsed" not in data["commodities_commentary"].lower()


def test_validator_ignores_gold_plunge_in_commodities_field():
    # Gold is DOWN and legitimately "plunged"; crude is UP. The bearish word belongs to
    # gold's sentence, not crude's, so it must NOT be flagged as a WTI contradiction.
    data = {"commodities_commentary":
            "Gold plunged as the safe-haven bid drained. WTI crude jumped on the supply shock."}
    viols = gmc._check_numeric_consistency(data, _snap())
    assert not [v for v in viols if "WTI" in v], viols


def test_validator_still_flags_uncorrected_crude_bearish_word():
    # A raw bearish word sharing crude's sentence, with no corrector run, is a real violation.
    data = {"commodities_commentary": "WTI crude tumbled hard despite the Iran escalation."}
    viols = gmc._check_numeric_consistency(data, _snap())
    assert any("WTI" in v and "bearish" in v for v in viols), viols


def test_full_correct_then_validate_passes_on_crude_selloff():
    data = {"commodities_commentary":
            "WTI crude suffered a selloff to $73.82. Gold plunged as havens unwound."}
    gmc._correct_direction_words(data, _snap())
    viols = gmc._check_numeric_consistency(data, _snap())
    assert not [v for v in viols if "WTI" in v], (data["commodities_commentary"], viols)


# --- 2026-07-09 email defect: gerund PRE-modifier of the asset noun -----------------
# Shipped synthesis said "a bearish regime where tumbling WTI crude (+4.37%)" while the
# commodities page said crude "surged". The gerund "tumbling" (a) wasn't in the validator's
# strong-word set and (b) sits BEFORE the "WTI" keyword, which the forward-only corrector
# never reached.

def test_validator_catches_gerund_premodifier():
    data = {"market_outlook_rationale":
            "A bearish regime where tumbling WTI crude compresses growth-name multiples."}
    viols = gmc._check_numeric_consistency(data, _snap())
    assert any("WTI" in v and "bearish" in v for v in viols), viols


def test_corrector_flips_gerund_premodifier():
    data = {"market_outlook_rationale":
            "A bearish regime where tumbling WTI crude compresses growth-name multiples."}
    gmc._correct_direction_words(data, _snap())
    assert "tumbling" not in data["market_outlook_rationale"].lower()
    assert "surging" in data["market_outlook_rationale"].lower()
    assert not [v for v in gmc._check_numeric_consistency(data, _snap()) if "WTI" in v]


def test_premodifier_fix_preserves_prior_down_asset_in_same_sentence():
    # The exact shipped sentence: S&P is DOWN (-0.28%, "decline" is correct) and WTI is UP
    # (+4.37%, "tumbling" is wrong). Fixing crude must NOT flip the S&P's "decline".
    sent = ("The S&P 500's 0.28% decline reflects a bearish regime where tumbling WTI crude "
            "(+4.37%) and rising 10-year yields compress growth-name multiples.")
    data = {"market_outlook_rationale": sent}
    gmc._correct_direction_words(data, _snap())
    out = data["market_outlook_rationale"].lower()
    assert "surging wti crude" in out          # crude pre-modifier flipped
    assert "decline" in out                    # S&P's own move untouched
    assert "advance" not in out                # decline NOT flipped to advance
    assert not [v for v in gmc._check_numeric_consistency(data, _snap()) if "WTI" in v]


def test_premodifier_does_not_touch_other_asset_verb():
    # "S&P 500 fell and WTI crude jumped" — both coherent; crude's backward pass must not
    # reach across "and" to flip the S&P's "fell".
    data = {"equities_commentary": "The S&P 500 fell and WTI crude jumped on supply fears."}
    n = gmc._correct_direction_words(data, _snap())
    assert "fell" in data["equities_commentary"].lower()
    assert "jumped" in data["equities_commentary"].lower()
