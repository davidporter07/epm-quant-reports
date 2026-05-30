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


# --- pre-market data-bullet enforcement (level hallucination guard) ---------
# Regression: 2026-05-29 shipped page-1 bullets with hallucinated levels
# (10-Yr "3.92%", gold "$2,680", DXY "98.42", BTC "$1.28") while the snapshot
# was correct. Numeric data bullets must be rebuilt from the snapshot.

_SNAP_0529 = {
    "S&P 500":           {"level": 7563.63, "pct_change": 0.58},
    "Nasdaq 100":        {"level": 30223.89, "pct_change": 0.84},
    "10-Yr Yield":       {"level": 4.450, "change": -0.030, "pct_change": -0.67},
    "WTI Crude":         {"level": 88.90, "pct_change": 0.25},
    "Gold":              {"level": 4499.30, "pct_change": 1.16},
    "U.S. Dollar (DXY)": {"level": 99.02, "pct_change": -0.19},
}


def test_hallucinated_levels_are_replaced_with_snapshot_truth():
    bullets = [
        "Markets closed higher; S&P 500 +0.58% to 7,563.63, Nasdaq 100 +0.84%; record highs.",
        "10-yr yield fell 3 bp to 3.92% ahead of inflation data.",
        "Dollar Index (DXY) edged up 1.16% to 98.42, while gold dipped 0.71% to $2,680/oz.",
        "Bitcoin slipped below $1.28 amid risk-off flows.",
    ]
    out, replaced = gmc._enforce_pre_market_data_bullets(bullets, _SNAP_0529)
    assert replaced == 3
    joined = " ".join(out)
    # Correct snapshot levels present
    assert "4.450%" in joined
    assert "99.02" in joined
    assert "4,499.30" in joined
    assert "88.90" in joined
    # Hallucinated levels gone
    for bad in ("3.92%", "98.42", "2,680", "1.28"):
        assert bad not in joined, f"hallucinated value {bad} survived"


def test_opener_and_narrative_bullets_are_preserved():
    opener = "Markets closed higher; S&P 500 +0.58% to 7,563.63, Nasdaq 100 +0.84%; record highs."
    sector = "Sector leaders: Health Care (+1.4%), Technology (+1.31%); laggards: Utilities (-1.13%)."
    fg = "Fear & Greed Index sits at 59.8 (Greed)."
    bullets = [opener, "10-yr yield at 3.92%.", sector, fg]
    out, _ = gmc._enforce_pre_market_data_bullets(bullets, _SNAP_0529)
    assert out[0] == opener          # deterministic opener untouched
    assert sector in out             # narrative kept (no tracked key-asset term)
    assert fg in out


def test_enforce_is_output_idempotent():
    bullets = [
        "Markets closed higher; S&P 500 +0.58% to 7,563.63.",
        "10-yr yield fell 3 bp to 3.92%.",
        "gold dipped to $2,680.",
    ]
    out1, _ = gmc._enforce_pre_market_data_bullets(bullets, _SNAP_0529)
    out2, _ = gmc._enforce_pre_market_data_bullets(out1, _SNAP_0529)
    assert out1 == out2


def test_enforce_no_ops_on_empty_snapshot():
    bullets = ["Markets closed higher.", "10-yr yield fell 3 bp to 3.92%."]
    assert gmc._enforce_pre_market_data_bullets(bullets, {}) == (bullets, 0)
    assert gmc._enforce_pre_market_data_bullets([], _SNAP_0529) == ([], 0)


def test_enforce_does_not_fabricate_missing_assets():
    # Only yield in snapshot → only the yield line is substituted; no gold/DXY invented.
    bullets = ["Markets closed higher.", "10-yr yield fell 3 bp to 3.92%.", "gold to $2,680."]
    out, replaced = gmc._enforce_pre_market_data_bullets(
        bullets, {"10-Yr Yield": {"level": 4.45, "change": -0.03}}
    )
    joined = " ".join(out)
    assert "4.450%" in joined
    assert "4,499" not in joined and "99.02" not in joined  # nothing fabricated
