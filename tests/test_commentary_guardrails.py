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
    from datetime import datetime, timedelta
    # Dates relative to today so the "recent" assertion never decays with the
    # calendar: claims observed 2 days ago (inside the 10-day window), PCE 60
    # days ago (outside it).
    recent_date = (datetime.today() - timedelta(days=2)).strftime("%Y-%m-%d")
    old_date    = (datetime.today() - timedelta(days=60)).strftime("%Y-%m-%d")
    arb = {"economics": {
        "Initial Jobless Claims": {"value": 215000.0, "prev_value": 210000.0, "date": recent_date},
        "Nonfarm Payrolls":       {"value": 115.0,    "prev_value": 185.0,    "date": old_date},
        "Core PCE (YoY)":         {"value": 3.28919,  "prev_value": 3.23629,  "date": old_date},
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


# --- Fix #1: dollar direction + window in recap arrays (2026-06-02) ----------
# DXY rose +0.29% on the day but fell on the week.
_SNAP_DXY_UP_WEEK_DOWN = {
    "U.S. Dollar (DXY)": {"pct_change": 0.29, "pct_change_1w": -0.4, "level": 99.20},
}


def test_weaker_dollar_flipped_to_stronger_in_session_recap():
    data = {"session_recap": [
        "Gold fell 1.87% as a weaker dollar drove investors toward oil and equities."]}
    n = gmc._correct_dollar_direction(data, _SNAP_DXY_UP_WEEK_DOWN)
    assert n == 1
    assert "stronger dollar" in data["session_recap"][0]
    assert "weaker dollar" not in data["session_recap"][0]


def test_dollar_weekly_gain_becomes_daily_when_week_down():
    data = {"session_recap": [
        "Rising yields powered the dollar's weekly gain and rate expectations firmed."]}
    gmc._correct_dollar_direction(data, _SNAP_DXY_UP_WEEK_DOWN)
    assert "daily gain" in data["session_recap"][0]
    assert "weekly gain" not in data["session_recap"][0]


def test_dollar_verb_after_token_flipped():
    data = {"currencies_commentary": "The dollar weakened on the session."}
    gmc._correct_dollar_direction(data, _SNAP_DXY_UP_WEEK_DOWN)
    assert "strengthened" in data["currencies_commentary"]


def test_dollar_direction_in_pre_market_bullets():
    data = {"pre_market_bullets": ["DXY context: a softer dollar capped gold."]}
    gmc._correct_dollar_direction(data, _SNAP_DXY_UP_WEEK_DOWN)
    assert "firmer dollar" in data["pre_market_bullets"][0]


def test_dollar_correct_prose_left_alone():
    data = {"currencies_commentary": "The dollar strengthened 0.29% as yields firmed."}
    before = data["currencies_commentary"]
    assert gmc._correct_dollar_direction(data, _SNAP_DXY_UP_WEEK_DOWN) == 0
    assert data["currencies_commentary"] == before


def test_dollar_direction_idempotent():
    data = {"session_recap": ["A weaker dollar lifted exporters."]}
    gmc._correct_dollar_direction(data, _SNAP_DXY_UP_WEEK_DOWN)
    once = data["session_recap"][0]
    gmc._correct_dollar_direction(data, _SNAP_DXY_UP_WEEK_DOWN)
    assert data["session_recap"][0] == once


def test_dollar_direction_noop_on_empty_snapshot():
    data = {"session_recap": ["A weaker dollar lifted exporters."]}
    assert gmc._correct_dollar_direction(data, {}) == 0


# --- Fix #2: off-narrative geopolitical hallucination scrub ------------------
_HEADLINES_US_IRAN = "US-Iran ceasefire talks resume; Israel Hezbollah; NVDA Computex AI chips"


def test_offnarrative_russia_clause_stripped_from_bullet():
    data = {"pre_market_bullets": [
        "Markets held gains as ceasefire hopes persisted despite reports of heavy Russian attacks on Ukrainian cities."]}
    n = gmc._scrub_offnarrative_geopolitics(data, _HEADLINES_US_IRAN)
    assert n == 1
    out = data["pre_market_bullets"][0]
    assert "Russian" not in out and "Ukrainian" not in out
    assert "ceasefire hopes persisted" in out


def test_offnarrative_russia_clause_stripped_from_prose():
    data = {"equities_commentary":
            "The VIX stayed contained at 16.08, reflecting calm despite headlines of heavy Russian attacks on Ukraine."}
    gmc._scrub_offnarrative_geopolitics(data, _HEADLINES_US_IRAN)
    assert "Russian" not in data["equities_commentary"]
    assert "VIX stayed contained" in data["equities_commentary"]


def test_offnarrative_main_subject_sentence_dropped():
    data = {"equities_commentary":
            "Stocks rose on tech strength. Russian forces shelled Kyiv overnight. The S&P held 7,600."}
    gmc._scrub_offnarrative_geopolitics(data, _HEADLINES_US_IRAN)
    assert "Russian" not in data["equities_commentary"]
    assert "tech strength" in data["equities_commentary"]
    assert "held 7,600" in data["equities_commentary"]


def test_geopolitics_kept_when_present_in_headlines():
    data = {"pre_market_bullets": ["Oil rose as Russian export sanctions tightened."]}
    n = gmc._scrub_offnarrative_geopolitics(data, "Russia oil export sanctions widen; OPEC meets")
    assert n == 0
    assert "Russian" in data["pre_market_bullets"][0]


# --- Fix #3: Fed rate-hike language reframed to higher-for-longer ------------
def test_fed_hike_expectations_reframed():
    data = {"fixed_income_commentary": "Yields rose as Fed hike expectations returned."}
    n = gmc._correct_fed_hike_language(data)
    assert n == 1
    assert "hike" not in data["fixed_income_commentary"].lower()
    assert "higher-for-longer rate expectations" in data["fixed_income_commentary"]


def test_fed_hike_midsentence_not_capitalized():
    data = {"session_recap": ["The 10-year yield rose as Fed hike expectations returned."]}
    gmc._correct_fed_hike_language(data)
    assert "as higher-for-longer" in data["session_recap"][0]
    assert "Higher-for-longer" not in data["session_recap"][0]


def test_rate_cut_language_untouched():
    data = {"fixed_income_commentary": "Yields fell as rate cut hopes returned."}
    assert gmc._correct_fed_hike_language(data) == 0
    assert "rate cut hopes" in data["fixed_income_commentary"]


def test_fed_hike_idempotent():
    data = {"economics_commentary": "Rate hike fears drove the dollar up."}
    gmc._correct_fed_hike_language(data)
    once = data["economics_commentary"]
    gmc._correct_fed_hike_language(data)
    assert data["economics_commentary"] == once


# --- foreign-macro trivia scrub --------------------------------------------
def test_foreign_macro_lead_dropped():
    data = {"economics_commentary":
            "JOLTS at 6.88 matched consensus. Australian government spending was flat in Q1. The Fed stays patient."}
    assert gmc._scrub_foreign_macro_lead(data) == 1
    out = data["economics_commentary"]
    assert "Australian" not in out and "JOLTS" in out and "Fed stays patient" in out


def test_us_macro_not_dropped():
    data = {"economics_commentary": "U.S. payrolls grew 115k and manufacturing held firm."}
    assert gmc._scrub_foreign_macro_lead(data) == 0


# --- safe-haven causal-inversion scrub -------------------------------------
def test_safe_haven_inversion_clause_stripped():
    data = {"session_recap": [
        "Gold fell 1.87% to $4475.20 as geopolitical volatility drove investors toward oil and equities."]}
    gmc._scrub_safe_haven_inversion(data)
    assert data["session_recap"][0] == "Gold fell 1.87% to $4475.20."


def test_safe_haven_legit_kept():
    data = {"commodities_commentary": "Gold rose as safe-haven demand increased on war fears."}
    assert gmc._scrub_safe_haven_inversion(data) == 0
    assert "safe-haven demand" in data["commodities_commentary"]


# --- sanitize_commentary orchestrator --------------------------------------
def test_sanitize_commentary_idempotent_and_clean():
    snap = {"U.S. Dollar (DXY)": {"pct_change": 0.29, "pct_change_1w": -0.4}}
    data = {"session_recap": ["A weaker dollar lifted exporters as Fed hike expectations returned."]}
    n1 = gmc.sanitize_commentary(data, snap)
    n2 = gmc.sanitize_commentary(data, snap)
    assert n1 > 0 and n2 == 0
    s = data["session_recap"][0]
    assert "stronger dollar" in s and "higher-for-longer" in s and "hike" not in s.lower()


def test_sanitize_scrubs_geo_with_source_text():
    data = {"pre_market_bullets": ["Markets held gains despite reports of Russian attacks on Kyiv."]}
    n = gmc.sanitize_commentary(data, {}, source_text="US-Iran ceasefire; OPEC oil output")
    assert n >= 1 and "Russian" not in data["pre_market_bullets"][0]


def test_sanitize_no_source_text_skips_geo():
    data = {"pre_market_bullets": ["Markets held gains despite Russian attacks on Kyiv."]}
    gmc.sanitize_commentary(data, {}, source_text="")
    assert "Russian" in data["pre_market_bullets"][0]  # geo scrub needs the corpus


# --- post_run.sync_to_server failure signalling (Fix: silent exit-0 deploy) -
def test_sync_to_server_returns_false_on_failure(monkeypatch):
    post_run = pytest.importorskip("post_run")
    monkeypatch.setattr(post_run, "SYNC_DIRS", ["data"])  # real dir, so .exists() is True
    monkeypatch.setattr(post_run, "SYNC_PY_FILES", [])
    monkeypatch.setattr(post_run, "_scp_dir", lambda *a, **k: 1)  # every transfer fails
    assert post_run.sync_to_server() is False


def test_sync_to_server_returns_true_on_success(monkeypatch):
    post_run = pytest.importorskip("post_run")
    monkeypatch.setattr(post_run, "SYNC_DIRS", ["data"])
    monkeypatch.setattr(post_run, "SYNC_PY_FILES", [])
    monkeypatch.setattr(post_run, "_scp_dir", lambda *a, **k: 0)
    assert post_run.sync_to_server() is True


# --- GPU preflight: fail loudly on CPU fallback / unreachable Ollama --------
# 2026-06-03 incident: a dead GPU driver made Ollama silently fall back to 100%
# CPU; the narrative ground for >1h and the run looked hung. _preflight_gpu_check
# must abort in seconds. Healthy = size_vram>0 (partial offload on the 6GB A2000
# is NORMAL), so the bar is >0 not full residency.

class _FakeResp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def _ps(vram, total=9_500_000_000):
    return _FakeResp({"models": [{"name": gmc.OLLAMA_MODEL, "size": total, "size_vram": vram}]})


def test_preflight_blocks_when_model_runs_on_cpu(monkeypatch):
    monkeypatch.delenv("EPM_SKIP_GPU_PREFLIGHT", raising=False)
    monkeypatch.setattr(gmc.requests, "get", lambda *a, **k: _ps(0))
    err = gmc._preflight_gpu_check(None)
    assert err and "100% on CPU" in err


def test_preflight_passes_on_partial_gpu_offload(monkeypatch):
    monkeypatch.delenv("EPM_SKIP_GPU_PREFLIGHT", raising=False)
    monkeypatch.setattr(gmc.requests, "get", lambda *a, **k: _ps(5_200_000_000))
    assert gmc._preflight_gpu_check(None) is None


def test_preflight_blocks_when_ollama_unreachable(monkeypatch):
    monkeypatch.delenv("EPM_SKIP_GPU_PREFLIGHT", raising=False)
    def _boom(*a, **k):
        raise gmc.requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(gmc.requests, "get", _boom)
    monkeypatch.setattr(gmc.requests, "post", _boom)
    err = gmc._preflight_gpu_check(None)
    assert err and "unreachable" in err.lower()


def test_preflight_skip_flag_bypasses_check(monkeypatch):
    monkeypatch.setenv("EPM_SKIP_GPU_PREFLIGHT", "1")
    # requests.get must never be called when skipped
    def _fail(*a, **k):
        raise AssertionError("preflight should not probe when skip flag set")
    monkeypatch.setattr(gmc.requests, "get", _fail)
    assert gmc._preflight_gpu_check(None) is None


# --- Tactical positioning: factor_read must not contradict the daily stance -----
# The stance is TODAY's sector tilt; factor_read is a TRAILING-1M beta read. When they
# diverge, factor_read must frame the divergence, not assert the opposite risk posture
# ("risk-on positioning" under a "Risk-off, defensive bid" header read as a contradiction).
import pandas as _pd


def _sector(ticker, name, pct):
    return {"ticker": ticker, "name": name, "pct_change": pct}


_RISK_OFF_SECTORS = [
    _sector("XLV", "Health", 1.0), _sector("XLP", "Staples", 1.0), _sector("XLU", "Util", 0.7),
    _sector("XLI", "Indus", 0.3), _sector("XLF", "Fin", -1.0), _sector("XLY", "Disc", -1.2),
    _sector("XLK", "Tech", -1.4),
]
_RISK_ON_SECTORS = [
    _sector("XLK", "Tech", 1.6), _sector("XLY", "Disc", 1.3), _sector("XLF", "Fin", 1.0),
    _sector("XLI", "Indus", 0.4), _sector("XLU", "Util", -0.8), _sector("XLP", "Staples", -1.0),
    _sector("XLV", "Health", -1.2),
]


def _fund_df():
    import universe_config as u
    port = [t for t in u.get_portfolio_tickers() if t not in set(u.get_mag7())][:5]
    # leaders high-beta, laggards low-beta
    rows = [
        {"Ticker": port[0], "1M Return": 19.6, "Beta (3Y)": 1.63},
        {"Ticker": port[1], "1M Return": 7.8, "Beta (3Y)": 1.13},
        {"Ticker": port[2], "1M Return": 4.8, "Beta (3Y)": 0.79},
        {"Ticker": port[3], "1M Return": -1.5, "Beta (3Y)": 0.72},
        {"Ticker": port[4], "1M Return": -2.9, "Beta (3Y)": 0.50},
    ]
    return _pd.DataFrame(rows)


def test_tactical_factor_read_no_contradiction_under_risk_off():
    out = gmc.build_tactical_positioning(_fund_df(), _RISK_OFF_SECTORS, 16.0)
    assert out["stance"].startswith("Risk-off"), out["stance"]
    fr = out["factor_read"]
    assert "counter to today's defensive rotation" in fr, fr
    assert "consistent with risk-on positioning" not in fr, fr


def test_tactical_factor_read_concordant_when_risk_on():
    out = gmc.build_tactical_positioning(_fund_df(), _RISK_ON_SECTORS, 16.0)
    assert out["stance"].startswith("Risk-on"), out["stance"]
    # high-beta leaders AGREE with a risk-on stance -> keep the plain concordant phrasing
    assert "consistent with risk-on positioning" in out["factor_read"], out["factor_read"]


# --- Email: inline logo must sit inside multipart/related (CID resolves in Gmail) ---
def test_email_logo_nested_in_related_with_pdf_at_mixed_level():
    se = pytest.importorskip("send_email")
    msg = se.build_email(to_addr="t@x.com", unsubscribe_url="https://x/u")
    assert msg.get_content_type() == "multipart/mixed"
    parts = msg.get_payload()
    related = next(p for p in parts if p.get_content_type() == "multipart/related")
    # the inline logo lives inside the related container, next to the HTML it references
    imgs = [p for p in related.get_payload() if p.get_content_type() == "image/png"]
    assert imgs and imgs[0].get("Content-ID") == "<epm_logo_png_cid>"
    # the PDF (if present) is a true attachment at the outer mixed level, NOT in related
    assert all(p.get_content_type() != "application/pdf" for p in related.get_payload())


# --- Email: the spotlight mover teaser renders in the Pre-Market Look block --------
def test_email_premarket_renders_spotlight_teaser():
    se = pytest.importorskip("send_email")
    html, txt = se._build_premarket_block({
        "spotlight_teaser": "Mover: AVGO -13.0% premarket on soft AI guidance - watch SMH, XLK",
        "futures_table": {"S&P 500 Futures": {"level": 7555.0, "pct_change": 0.16}},
    })
    assert "AVGO -13.0%" in html and "Mover:" in html
    assert any("AVGO -13.0%" in line for line in txt)
    # absent teaser is a clean no-op
    html2, _ = se._build_premarket_block({"futures_table": {}})
    assert "Mover:" not in html2


# --- "Tomorrow's <event>" slip corrected when the scenario event is today ---------
def test_correct_event_day_slip_today():
    data = {
        "scenario_event": "Initial Jobless Claims",
        "scenario_event_day": "today",
        "cross_asset_synthesis": "Tomorrow's Initial Jobless Claims print at 10:00 AM ET is the key threshold.",
        "fixed_income_commentary": "Traders await tomorrow's CPI, a separate report later in the week.",
    }
    n = gmc._correct_event_day_slip(data)
    assert n >= 1
    assert "Today's Initial Jobless Claims" in data["cross_asset_synthesis"]
    assert "Tomorrow" not in data["cross_asset_synthesis"]
    # a 'tomorrow' tied to a DIFFERENT event (no jobless-claims mention) is left alone
    assert "tomorrow's CPI" in data["fixed_income_commentary"]


def test_correct_event_day_slip_skips_genuine_future_event():
    data = {
        "scenario_event": "Nonfarm Payrolls",
        "scenario_event_day": "tomorrow",
        "cross_asset_synthesis": "Tomorrow's Nonfarm Payrolls print is the key catalyst.",
    }
    assert gmc._correct_event_day_slip(data) == 0
    assert "Tomorrow's Nonfarm Payrolls" in data["cross_asset_synthesis"]


# --- economics_commentary must not assert values for not-yet-released events -------
def test_scrub_unreleased_econ_prints_drops_future_event_readings(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)  # no calendar -> upcoming = scenario event only
    data = {
        "scenario_event": "Initial Jobless Claims",
        "scenario_event_day": "today",
        "report_date": "2026-06-04",
        "economics_commentary": (
            "Initial Jobless Claims at 215k vs 210k prior suggests resilient labor demand. "
            "The latest Core PCE reading at 3.3% YoY beat the 3.2% prior. "
            "Traders are watching the Initial Jobless Claims print at 10:00 AM ET to gauge resilience."
        ),
    }
    assert gmc._scrub_unreleased_econ_prints(data) == 1
    ec = data["economics_commentary"]
    assert "215k" not in ec                    # fabricated future print dropped
    assert "Core PCE reading at 3.3%" in ec    # released, non-upcoming print kept
    assert "10:00 AM ET" in ec                 # value-free event preview kept


# --- ungrounded Fed-official attribution is de-personalized ------------------------
def test_scrub_ungrounded_fed_attribution_neutralizes_unsourced_name():
    data = {
        "fixed_income_commentary": "The 10-year yield rose as Fed President Beth Hammack signaled higher-for-longer rates.",
        "cross_asset_synthesis": "This confirms Fed President Hammack's hawkish pivot.",
        "fed_speakers": [{"speaker": "Vice Chair for Supervision Michelle W. Bowman"}],
    }
    src = "stocks fall on chip earnings; new Fed Chair Warsh inherits inflation"  # no Hammack
    assert gmc._scrub_ungrounded_fed_attribution(data, src) >= 1
    assert "Hammack" not in data["fixed_income_commentary"]
    assert "the Fed signaled higher-for-longer" in data["fixed_income_commentary"]
    assert "the Fed's hawkish pivot" in data["cross_asset_synthesis"]


def test_scrub_ungrounded_fed_attribution_keeps_scheduled_speaker():
    data = {
        "economics_commentary": "Governor Bowman said supervision reform is overdue.",
        "fed_speakers": [{"speaker": "Vice Chair for Supervision Michelle W. Bowman"}],
    }
    assert gmc._scrub_ungrounded_fed_attribution(data, source_text="") == 0
    assert "Bowman" in data["economics_commentary"]


# --- JOLTS now surfaces in the recent-prints recap (was missing 2026-06-03) -------
def test_jolts_surfaces_in_recent_macro_prints(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    payload = {"economics": {
        "JOLTS Job Openings":     {"value": 7618.0, "prev_value": 6887.0, "date": "2026-04-01"},
        "Initial Jobless Claims": {"value": 215000.0, "prev_value": 210000.0, "date": "2026-05-23"},
    }}
    (tmp_path / "market_data_arbitrated.json").write_text(_json.dumps(payload), encoding="utf-8")
    out = gmc.load_recent_macro_prints()
    jolts = next((r for r in out if r["indicator"] == "JOLTS Job Openings"), None)
    assert jolts is not None, "JOLTS missing from recap"
    assert jolts["actual"] == "7.62M", jolts["actual"]   # 7618 thousands -> 7.62M
    assert jolts["prior"] == "6.89M", jolts["prior"]


# --- Gold: report SPOT (XAUUSD=X), fall back to futures (GC=F) ----------------
# 2026-06-04 eval: EPM snapshot gold read ~$40 high vs Sevens because we quoted
# COMEX futures (contango basis); spot is the desk/Sevens convention.
def test_fetch_gold_quote_prefers_spot(monkeypatch):
    seen = {}

    def _fake(ticker, prev_close=None, mode="eod"):
        seen[ticker] = True
        if ticker == "XAUUSD=X":
            return {"level": 4475.40, "change": -44.0, "pct_change": -0.98}
        return {"level": 4436.70, "change": -52.0, "pct_change": -1.17}  # GC=F futures

    monkeypatch.setattr(gmc, "_fetch_quote", _fake)
    q = gmc._fetch_gold_quote()
    assert q["level"] == 4475.40, "should return the spot level"
    assert "GC=F" not in seen, "futures must not be fetched when spot is good"


def test_fetch_gold_quote_falls_back_to_futures_when_spot_empty(monkeypatch):
    def _fake(ticker, prev_close=None, mode="eod"):
        if ticker == "XAUUSD=X":
            return None                       # spot feed flaked (yfinance XAUUSD=X is fragile)
        return {"level": 4436.70, "change": -52.0, "pct_change": -1.17}

    monkeypatch.setattr(gmc, "_fetch_quote", _fake)
    assert gmc._fetch_gold_quote()["level"] == 4436.70


def test_fetch_gold_quote_falls_back_when_spot_level_zero(monkeypatch):
    def _fake(ticker, prev_close=None, mode="eod"):
        if ticker == "XAUUSD=X":
            return {"level": 0, "change": None, "pct_change": None}   # present but unusable
        return {"level": 4436.70, "change": -52.0, "pct_change": -1.17}

    monkeypatch.setattr(gmc, "_fetch_quote", _fake)
    assert gmc._fetch_gold_quote()["level"] == 4436.70


# --- Fed speakers: harvest regional presidents from the news wire -------------
# federalreserve.gov/json/calendar.json is Board-of-Governors-only, so regional
# reserve-bank presidents (Barkin/Richmond, Daly/SF) never appear even when they
# speak (2026-06-04: Sevens had Barkin 8:30 + Daly 1:10; EPM had only Bowman).
def test_harvest_fed_speakers_picks_regional_presidents_from_news():
    headlines = [
        "Fed's Daly says policy is in a good place as inflation cools",
        "Richmond Fed President Barkin speaks at 8:30 a.m. ET on labor market",
        "Apple unveils new iPhone lineup at fall event",
    ]
    out = gmc._harvest_fed_speakers_from_news(headlines, existing_speakers=[])
    names = " ".join(s["speaker"] for s in out)
    assert "Daly" in names and "Barkin" in names
    barkin = next(s for s in out if "Barkin" in s["speaker"])
    assert "8:30" in barkin["time_et"], barkin


def test_harvest_fed_dedupes_against_existing_governors():
    # Bowman already came from the JSON feed — do not double-list her.
    existing = [{"speaker": "Vice Chair for Supervision Michelle W. Bowman"}]
    headlines = ["Fed's Bowman testifies before Senate Banking Committee"]
    out = gmc._harvest_fed_speakers_from_news(headlines, existing_speakers=existing)
    assert out == [], "Bowman is already scheduled; should not be re-added"


def test_harvest_fed_ignores_nonfed_surname_collisions():
    # 'Cook' / 'Williams' appear but with no Fed context -> not Fed speakers.
    headlines = [
        "Tim Cook unveils new iPhone at Apple event",
        "Serena Williams announces tennis comeback",
    ]
    assert gmc._harvest_fed_speakers_from_news(headlines, existing_speakers=[]) == []


def test_harvest_fed_dedupes_repeated_mentions():
    headlines = [
        "Fed's Daly: rate cuts still on the table this year",
        "San Francisco Fed's Daly reiterates patience on policy",
        "Daly of the Fed speaks on financial stability",
    ]
    out = gmc._harvest_fed_speakers_from_news(headlines, existing_speakers=[])
    daly = [s for s in out if "Daly" in s["speaker"]]
    assert len(daly) == 1, f"expected one Daly entry, got {daly}"


# --- unreleased-event attribution scrub (#1a, regression 2026-06-05) ---------
# session_recap/pre_market_bullets pinned a PAST move on NFP, which was that day's
# unreleased scenario event. Value-less causal attribution slipped the value-only
# econ-print scrub and these list fields were never scanned.

def test_unreleased_nfp_attribution_stripped_from_session_recap():
    data = {
        "scenario_event": "Non-Farm Payrolls / Jobs Report",
        "scenario_event_day": "today",
        "session_recap": [
            "S&P 500 closed higher at 7584.31, 0.41% driven by robust May nonfarm payrolls data that reinforced rate expectations.",
            "10-year yield fell 2 bp to 4.47% as the strong jobs report initially lifted yields before cooling.",
        ],
    }
    gmc._scrub_unreleased_event_attribution(data)
    assert data["session_recap"][0] == "S&P 500 closed higher at 7584.31, 0.41%."
    assert data["session_recap"][1] == "10-year yield fell 2 bp to 4.47%."


def test_unreleased_attribution_stripped_from_pre_market_bullets():
    data = {
        "scenario_event": "Non-Farm Payrolls / Jobs Report",
        "pre_market_bullets": [
            "S&P 500 futures firmed on the back of upcoming jobs report optimism.",
        ],
    }
    gmc._scrub_unreleased_event_attribution(data)
    assert data["pre_market_bullets"][0] == "S&P 500 futures firmed."


def test_legitimate_event_preview_is_preserved():
    # A forward-looking preview names the event but makes no past-causal claim.
    data = {
        "scenario_event": "Non-Farm Payrolls / Jobs Report",
        "pre_market_bullets": [
            "Key data today: Non-Farm Payrolls at 8:30 AM ET; consensus 85K vs prior 172K.",
        ],
        "watch_today": ["Traders await the jobs report at 8:30 AM ET."],
    }
    before = (list(data["pre_market_bullets"]), list(data["watch_today"]))
    gmc._scrub_unreleased_event_attribution(data)
    assert (data["pre_market_bullets"], data["watch_today"]) == (before[0], before[1])


def test_unreleased_attribution_is_idempotent():
    data = {
        "scenario_event": "Non-Farm Payrolls / Jobs Report",
        "session_recap": ["S&P 500 closed higher at 7584.31, 0.41% driven by robust May nonfarm payrolls data."],
    }
    gmc._scrub_unreleased_event_attribution(data)
    once = list(data["session_recap"])
    gmc._scrub_unreleased_event_attribution(data)
    assert data["session_recap"] == once


def test_no_scenario_event_is_noop():
    data = {"session_recap": ["S&P 500 rose as the jobs report fueled buying."]}
    assert gmc._scrub_unreleased_event_attribution(data) == 0


def test_non_event_causal_clause_is_left_alone():
    # "as tech rallied" is not an econ-event attribution — must not be touched.
    data = {
        "scenario_event": "Non-Farm Payrolls / Jobs Report",
        "session_recap": ["The S&P 500 rose 0.4% as technology shares rallied broadly."],
    }
    before = list(data["session_recap"])
    gmc._scrub_unreleased_event_attribution(data)
    assert data["session_recap"] == before


# --- fabricated kinetic-attack detail scrub (#1b, regression 2026-06-05) -----
# pre_market_bullets carried "Iran fired warning missiles and drones at US warships
# in the Gulf of Oman" — specifics absent from the corpus, contradicting the ceasefire.

_GEO_CORPUS = ("israel-lebanon ceasefire; gulf hostilities flared; u.s. and iran trade "
               "strikes; iran peace talks continue")


def test_fabricated_kinetic_clause_is_dropped():
    data = {"pre_market_bullets": [
        "Markets closed higher — S&P 500 +0.41% to 7,584.31; Iran fired warning "
        "missiles and drones at US warships in the Gulf of Oman, heightening risk premiums."
    ]}
    gmc._scrub_fabricated_kinetic_detail(data, _GEO_CORPUS)
    assert data["pre_market_bullets"][0] == "Markets closed higher — S&P 500 +0.41% to 7,584.31."


def test_grounded_kinetic_framing_is_preserved():
    # "strikes" IS in the corpus → general framing survives (no ungrounded weapon noun).
    data = {"session_recap": ["Oil rose as U.S. and Iran trade strikes in the region."]}
    before = list(data["session_recap"])
    gmc._scrub_fabricated_kinetic_detail(data, _GEO_CORPUS)
    assert data["session_recap"] == before


def test_grounded_weapon_noun_is_preserved():
    # When the corpus DOES mention tankers, a tanker-strike claim is grounded → kept.
    corpus = _GEO_CORPUS + "; oil tanker struck near hormuz"
    data = {"pre_market_bullets": ["A tanker was struck near the Strait of Hormuz."]}
    before = list(data["pre_market_bullets"])
    gmc._scrub_fabricated_kinetic_detail(data, corpus)
    assert data["pre_market_bullets"] == before


def test_kinetic_scrub_is_idempotent():
    data = {"pre_market_bullets": [
        "Equities firmed to 7,584; Iran fired drones at US warships overnight."]}
    gmc._scrub_fabricated_kinetic_detail(data, _GEO_CORPUS)
    once = list(data["pre_market_bullets"])
    gmc._scrub_fabricated_kinetic_detail(data, _GEO_CORPUS)
    assert data["pre_market_bullets"] == once
