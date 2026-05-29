"""PR 0/1 credibility guardrails: move-significance + unsourced-superlative validators."""
import pytest

gmc = pytest.importorskip("generate_market_commentary")


# --- move significance: noise move cannot 'confirm a bias' -----------------

def test_noise_move_with_bias_language_is_flagged():
    snapshot = {"S&P 500": {"pct_change": 0.02, "level": 7520.0}}
    data = {"market_outlook_rationale": "The 0.02% advance confirms a bullish bias as tech leads."}
    issues = gmc._check_move_significance(data, snapshot)
    assert issues, "expected a noise-as-signal violation"


def test_large_move_with_directional_language_is_allowed():
    snapshot = {"S&P 500": {"pct_change": 1.6, "level": 7600.0}}
    data = {"market_outlook_rationale": "The 1.6% rally confirms a bullish bias as tech leads."}
    assert gmc._check_move_significance(data, snapshot) == []


def test_noise_move_with_neutral_language_is_allowed():
    snapshot = {"S&P 500": {"pct_change": 0.02, "level": 7520.0}}
    data = {"equities_commentary": "The index was essentially flat; Energy fell -1.5% while Staples gained."}
    assert gmc._check_move_significance(data, snapshot) == []


# --- unsourced superlatives / geopolitical claims --------------------------

def test_unsourced_historical_superlative_is_flagged():
    data = {"equities_commentary":
            "Korean equities outpaced U.S. tech by the widest margin in 25 years."}
    issues = gmc._check_unsourced_superlatives(data, headlines=[])
    assert issues, "expected an unsourced superlative violation"


def test_superlative_supported_by_headline_is_allowed():
    data = {"equities_commentary":
            "Korean equities outpaced U.S. tech by the widest margin in 25 years."}
    headlines = ["Korean equities post widest outperformance versus US tech in decades"]
    assert gmc._check_unsourced_superlatives(data, headlines) == []


def test_unsourced_geopolitical_claim_is_flagged():
    data = {"commodities_commentary": "Fresh U.S. strikes on Iran pushed crude sharply higher."}
    assert gmc._check_unsourced_superlatives(data, headlines=["Apple earnings beat estimates"])


def test_geopolitical_claim_with_headline_is_allowed():
    data = {"commodities_commentary": "Fresh U.S. strikes on Iran pushed crude sharply higher."}
    headlines = ["US strikes Iran nuclear facility overnight"]
    assert gmc._check_unsourced_superlatives(data, headlines) == []


def test_plain_52week_high_is_not_flagged():
    # Data-derived technical level — no in/since-<time> qualifier — must not trip.
    data = {"equities_commentary": "The index traded at its 52-week high of 7,520.36."}
    assert gmc._check_unsourced_superlatives(data, headlines=[]) == []
