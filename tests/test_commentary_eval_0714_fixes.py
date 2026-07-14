"""2026-07-14 fixes. The 8am scheduled send was correctly BLOCKED (freshness gate) because the
LLM fell to deterministic prose after exhausting every Call-2/Call-4 retry on a violent US-Iran
escalation day (WTI +9.42%, S&P -0.79%). Two validator gaps drove / leaked past that:

  #1 negation-blind regime check — "This escalation invalidates the risk-on regime, forcing
     investors to flee equities for safety" is directionally CORRECT on a risk-OFF day, but the
     (D) branch matched the substring "risk-on regime" and ignored the negating verb, burning all
     4 retries. _REGIME_GONE_VERBS now counts invalidate/reverse/overturn/... as fading.
  #2 Fed rate-hike reframe missed two spots: (a) the HYPHENATED "rate-hike narrative" evaded the
     bare catch-all (whitespace-only) and had no suffix rule; (b) scenarios[]/levels_to_watch[]
     are nested, so _map_all_prose never scanned them ("rekindle rate-hike expectations" shipped
     in the Hot scenario's rates line).
"""
import pytest

gmc = pytest.importorskip("generate_market_commentary")


# ---- #1 negation-aware risk-regime validator -------------------------------------------

_RISKOFF_SNAP = {"S&P 500": {"pct_change": -0.79}}
_RISKON_SNAP = {"S&P 500": {"pct_change": +0.85}}


def test_invalidated_risk_on_regime_not_flagged_on_riskoff_day():
    # The exact 2026-07-14 sentence that burned all 4 Call-2 retries.
    data = {"market_outlook_rationale":
            "This escalation invalidates the risk-on regime, forcing investors to flee "
            "equities for safety."}
    assert gmc._check_risk_polarity_inversion(data, _RISKOFF_SNAP) == []


@pytest.mark.parametrize("verb", [
    "invalidates", "reverses", "overturns", "undermines", "dismantles",
    "shatters", "nullifies", "upends", "ends", "breaks",
])
def test_negation_verbs_excuse_regime_label(verb):
    data = {"market_outlook_rationale": f"Today's selloff {verb} the risk-on regime."}
    assert gmc._check_risk_polarity_inversion(data, _RISKOFF_SNAP) == []


def test_genuine_wrong_regime_still_flagged():
    # A plain wrong assertion (no fading/negation verb) must STILL be caught.
    data = {"market_outlook_rationale":
            "A clear risk-on regime dominated as dip buyers stepped in."}
    assert gmc._check_risk_polarity_inversion(data, _RISKOFF_SNAP)


def test_fading_regime_still_excused():
    data = {"market_outlook_rationale": "The risk-on regime faded through the afternoon."}
    assert gmc._check_risk_polarity_inversion(data, _RISKOFF_SNAP) == []


def test_wrong_riskoff_on_riskon_day_still_flagged():
    data = {"market_outlook_rationale":
            "A defensive risk-off regime gripped the tape all session."}
    assert gmc._check_risk_polarity_inversion(data, _RISKON_SNAP)


# ---- #2 Fed rate-hike reframe: hyphenated narrative + nested scenarios ------------------

def test_hyphenated_rate_hike_narrative_reframed():
    data = {"watch_today": ["Traders watch whether the CPI print sustains the rate-hike narrative."]}
    gmc._correct_fed_hike_language(data)
    txt = data["watch_today"][0].lower()
    assert "rate-hike" not in txt and "hike" not in txt
    assert "higher-for-longer" in txt


def test_rate_hike_reframe_reaches_scenarios_and_levels():
    data = {
        "scenarios": [
            {"label": "Hot (>0.3%)", "thesis": "A hot CPI validates the hawkish stance.",
             "rates": "10-year yield spikes 10-15 bp as inflation fears rekindle rate-hike expectations.",
             "equities": "S&P falls 1-1.5%.", "commodities": "Gold retreats.", "tickers": ["XLP"]},
        ],
        "levels_to_watch": [
            {"asset": "10-Yr Yield", "level": 4.62,
             "significance": "A break above signals a renewed rate-hike bias from the Fed."},
        ],
    }
    n = gmc._correct_fed_hike_language(data)
    assert n >= 2
    assert "hike" not in data["scenarios"][0]["rates"].lower()
    assert "higher-for-longer" in data["scenarios"][0]["rates"].lower()
    assert "hike" not in data["levels_to_watch"][0]["significance"].lower()


def test_rate_hike_reframe_idempotent_on_scenarios():
    data = {"scenarios": [{"rates": "inflation fears rekindle rate-hike expectations."}]}
    gmc._correct_fed_hike_language(data)
    once = data["scenarios"][0]["rates"]
    gmc._correct_fed_hike_language(data)
    assert data["scenarios"][0]["rates"] == once  # no re-hit, no drift
