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


# --- direction-word / superlative guard (Fix #1) ---------------------------
# Regression: 2026-06-01 shipped "Gold slipped 1.36% ... falling to a two-month
# low" while gold was +1.36%. The cited percent's sign was already correct, so the
# sign/magnitude correctors passed it — only the verb + superlative were wrong.

_SNAP_0601 = {
    "Gold":              {"level": 4560.5, "pct_change": 1.36},
    "WTI Crude":         {"level": 87.36,  "pct_change": -1.73},
    "S&P 500":           {"level": 7580.06, "pct_change": 0.22},
    "U.S. Dollar (DXY)": {"level": 98.91,  "pct_change": -0.11},
}


def test_direction_word_gold_contradiction_is_flagged():
    data = {"commodities_commentary":
            "Gold slipped 1.36% to $4,560.50, falling to a two-month low as risk eased."}
    assert gmc._check_direction_words(data, _SNAP_0601)


def test_direction_word_gold_contradiction_is_corrected():
    data = {"commodities_commentary":
            "Gold slipped 1.36% to $4,560.50, falling to a two-month low as risk eased."}
    fixes = gmc._correct_direction_words(data, _SNAP_0601)
    assert fixes == 1
    prose = data["commodities_commentary"].lower()
    assert "slipped" not in prose and "falling to a two-month low" not in prose
    assert "rose" in prose or "rising" in prose
    assert gmc._check_direction_words(data, _SNAP_0601) == []  # clean after correction


def test_direction_word_does_not_touch_driver_clause():
    # "easing ... tensions" describes the DRIVER, not gold's price — must survive.
    data = {"cross_asset_synthesis":
            "Gold's drop to a two-month low validates that easing Middle East tensions help."}
    gmc._correct_direction_words(data, _SNAP_0601)
    assert "easing Middle East tensions" in data["cross_asset_synthesis"]
    assert "drop to a two-month low" not in data["cross_asset_synthesis"].lower()


def test_direction_word_correct_prose_is_left_alone():
    # WTI is down and the prose says "fell" — no change.
    data = {"commodities_commentary": "WTI Crude fell -1.73% to $87.36 on easing supply fears."}
    assert gmc._correct_direction_words(data, _SNAP_0601) == 0
    assert gmc._check_direction_words(data, _SNAP_0601) == []


def test_direction_word_is_idempotent():
    data = {"commodities_commentary":
            "Gold slipped 1.36% to $4,560.50, falling to a two-month low as risk eased."}
    gmc._correct_direction_words(data, _SNAP_0601)
    once = data["commodities_commentary"]
    gmc._correct_direction_words(data, _SNAP_0601)
    assert data["commodities_commentary"] == once


def test_direction_word_noop_on_empty_snapshot():
    data = {"commodities_commentary": "Gold slipped 1.36% to a two-month low."}
    assert gmc._correct_direction_words(data, {}) == 0
    assert gmc._check_direction_words(data, {}) == []


# --- fabricated corporate-action guard (Fix #2) ----------------------------
# Regression: 2026-06-01 shipped "Nvidia's 2,400% dividend hike reshapes S&P 500
# income streams" (and echoed it into the Equities outlook + XNTK spotlight).
# No dividend/buyback/split feed exists, so any such claim is a hallucination.

def test_fabricated_dividend_is_flagged():
    data = {"equities_commentary":
            "The index trades above its 200-day MA. Nvidia's 2,400% dividend hike reshapes income streams."}
    assert gmc._check_fabricated_corporate_actions(data)


def test_fabricated_dividend_in_spotlight_is_flagged():
    data = {"portfolio_spotlight_winners": [
        {"ticker": "XNTK", "commentary": "XNTK surges, driven by Nvidia's massive dividend hike."}]}
    assert gmc._check_fabricated_corporate_actions(data)


def test_fabricated_dividend_is_scrubbed():
    data = {"equities_commentary":
            "Technology led the rally. Nvidia's 2,400% dividend hike reshapes income streams. Volatility stayed low."}
    fixes = gmc._scrub_fabricated_corporate_actions(data)
    assert fixes == 1
    assert "dividend" not in data["equities_commentary"].lower()
    assert "Technology led the rally" in data["equities_commentary"]
    assert gmc._check_fabricated_corporate_actions(data) == []


def test_no_corporate_action_claim_is_clean():
    data = {"equities_commentary": "Technology led the rally as AI capex demand stayed robust."}
    assert gmc._check_fabricated_corporate_actions(data) == []
    assert gmc._scrub_fabricated_corporate_actions(data) == 0


# --- recent macro prints loader (Fix #5) -----------------------------------
# Regression: 2026-06-01 economics paragraph fabricated "211k in line with 211k
# prior" because no claims value was passed to the model. The loader must surface
# the real figures with correct units (claims are a raw count → "215k"; NFP is
# already in thousands → "115k", must NOT become "0k").

def test_macro_prints_units(tmp_path, monkeypatch):
    import json as _json
    arb = {"economics": {
        "Initial Jobless Claims": {"value": 215000.0, "prev_value": 210000.0, "date": "2026-05-23"},
        "Nonfarm Payrolls":       {"value": 115.0,    "prev_value": 185.0,    "date": "2026-04-01"},
        "Core PCE (YoY)":         {"value": 3.28919,  "prev_value": 3.23629,  "date": "2026-04-01"},
    }}
    (tmp_path / "market_data_arbitrated.json").write_text(_json.dumps(arb), encoding="utf-8")
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    rows = {r["indicator"]: r for r in gmc.load_recent_macro_prints()}
    assert rows["Initial Jobless Claims"]["actual"] == "215k"
    assert rows["Initial Jobless Claims"]["prior"] == "210k"
    assert rows["Nonfarm Payrolls"]["actual"] == "115k"   # already-thousands, not "0k"
    assert rows["Core PCE (YoY)"]["actual"] == "3.3%"
    # weekly claims (recent obs date) flagged recent; monthly PCE not
    assert rows["Initial Jobless Claims"]["recent"] is True
    assert rows["Core PCE (YoY)"]["recent"] is False


def test_macro_prints_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)  # no arbitrated file present
    assert gmc.load_recent_macro_prints() == []


# --- spotlight/tactical use the FRESH 1M return, not stale YCharts (Fix #7) -
# Regression: 2026-06-01 spotlight showed XNTK +24.8%/TMFC +13.8% from the stale
# YCharts "1M Return" (2026-05-08 scrape) instead of the fresh yfinance value in
# "1M Return_enrich" (XNTK 19.9%/TMFC 5.5%). The stale column even mis-ranked the book.

def test_fresh_1m_col_prefers_enrich():
    assert gmc._fresh_1m_col(["1M Return", "1M Return_enrich"]) == "1M Return_enrich"


def test_fresh_1m_col_falls_back_to_forward_then_stale():
    assert gmc._fresh_1m_col(["1M Return", "Forward Return"]) == "Forward Return"
    assert gmc._fresh_1m_col(["1M Return"]) == "1M Return"
    assert gmc._fresh_1m_col(["Sharpe (3Y)"]) is None


def test_spotlight_uses_enriched_1m_return(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(gmc, "get_portfolio_tickers", lambda: ["XNTK", "IXJ"], raising=False)
    # build_portfolio_spotlight imports these names from universe_config at call time;
    # patch the module it imports from.
    import universe_config as uc
    monkeypatch.setattr(uc, "get_portfolio_tickers", lambda: ["XNTK", "IXJ"])
    monkeypatch.setattr(uc, "get_mag7", lambda: [])
    df = pd.DataFrame([
        {"Ticker": "XNTK", "1M Return": 0.2482, "1M Return_enrich": 0.1988},
        {"Ticker": "IXJ",  "1M Return": -0.0177, "1M Return_enrich": 0.0058},
    ])
    winners, watch = gmc.build_portfolio_spotlight(df)
    labels = {e["ticker"]: e["return_1m"] for e in winners + watch}
    assert labels["XNTK"] == 19.88   # fresh, not stale 24.82
    assert labels["IXJ"] == 0.58     # fresh +0.58 (sign flips from stale -1.77)


# --- editorial contradiction guard (window/superlative/causal) -------------
# Regression 2026-06-01: "rising yields powering the dollar's biggest weekly gain"
# (yields flat/down, DXY down), "the dollar hits a six-week high" (DXY fell), and
# "WTI fell as renewed tensions fuel supply shocks" (decline w/ bullish driver).

_SNAP_EDIT = {
    "U.S. Dollar (DXY)": {"pct_change": -0.11, "pct_change_1w": -0.28},
    "10-Yr Yield":       {"bp_change": 0, "bp_change_1w": -13.3},
    "WTI Crude":         {"pct_change": -1.73},
}


def test_dollar_strength_superlative_flagged_when_dxy_fell():
    data = {"currencies_commentary": "EM could struggle as the dollar hits a six-week high amid risk."}
    assert gmc._check_editorial_contradictions(data, _SNAP_EDIT)


def test_rising_yields_flagged_when_flat_down():
    data = {"fixed_income_commentary": "Muted Fed, but rising yields are powering the move."}
    assert gmc._check_editorial_contradictions(data, _SNAP_EDIT)


def test_tenor_specific_yield_rise_not_flagged():
    # "the 30-year yield rose 1 bp" is factual & tenor-specific — must NOT trip.
    data = {"fixed_income_commentary": "The 30-year yield rose 1 bp to 4.99%, while the 2-year slipped 1 bp."}
    assert gmc._check_editorial_contradictions(data, _SNAP_EDIT) == []


def test_oil_decline_with_bullish_driver_flagged():
    data = {"commodities_commentary": "WTI Crude fell -1.73% as renewed Middle East tensions fuel inflation and supply shocks."}
    assert gmc._check_editorial_contradictions(data, _SNAP_EDIT)


def test_scrub_drops_dollar_strength_keeps_facts():
    data = {"fixed_income_commentary":
            "The 10-year held at 4.45%. Rising yields are powering the dollar's biggest weekly gain in months. "
            "The 30-year yield rose 1 bp to 4.99%."}
    fixes = gmc._scrub_false_weekly_claims(data, _SNAP_EDIT)
    assert fixes == 1
    prose = data["fixed_income_commentary"]
    assert "biggest weekly gain" not in prose
    assert "30-year yield rose 1 bp" in prose   # factual sentence preserved
    assert "10-year held at 4.45%" in prose


def test_editorial_clean_prose_passes():
    data = {"currencies_commentary": "The dollar fell -0.11% to 98.91 as peace talks progressed."}
    assert gmc._check_editorial_contradictions(data, _SNAP_EDIT) == []
    assert gmc._scrub_false_weekly_claims(data, _SNAP_EDIT) == 0
