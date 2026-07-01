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


# --- off-topic emerging-market-bond scrub (2026-06-29) ---------------------

def test_em_bond_recap_misattribution_is_trimmed():
    # The lead recap bullet pinned a flat S&P on an EM-bond storyline — trim the causal clause.
    data = {"session_recap": [
        "S&P 500 closed lower at 7354.02, -0.05% as Federal Reserve Chairman Kevin Warsh "
        "disrupted emerging-market bond recovery with hawkish commentary."]}
    assert gmc._scrub_offtopic_em_bonds(data) == 1
    out = data["session_recap"][0]
    assert "emerging-market bond" not in out.lower()
    assert "7354.02" in out and "-0.05%" in out   # factual head preserved


def test_em_bond_offtopic_outlook_clause_is_trimmed():
    data = {"asset_class_outlooks": {
        "Commodities": {"label": "Bearish", "rationale":
            "WTI Crude fell to $69.23 on easing supply fears, while gold's rise signals a "
            "residual safe-haven bid given the Fed's challenge to emerging-market bond rallies."},
        "US Dollar": {"label": "Bearish", "rationale":
            "The dollar eased 0.07%, but the Fed's hawkish stance keeps it resilient against "
            "emerging-market bond rallies."},
    }}
    assert gmc._scrub_offtopic_em_bonds(data) == 2
    for cls in ("Commodities", "US Dollar"):
        assert "emerging-market bond" not in data["asset_class_outlooks"][cls]["rationale"].lower()
    assert "WTI Crude fell" in data["asset_class_outlooks"]["Commodities"]["rationale"]


def test_fixed_income_em_bond_context_is_exempt():
    # Fed rate-path context in the Treasury section is legitimate — must NOT be scrubbed.
    data = {"fixed_income_commentary":
            "The 10-year yield fell 2 bp to 4.38% as Warsh's hawkish stance on emerging-market "
            "bonds suggests US yields stay elevated."}
    assert gmc._scrub_offtopic_em_bonds(data) == 0
    assert "emerging-market bonds" in data["fixed_income_commentary"].lower()


def test_em_currencies_generic_not_touched():
    # "emerging-market currencies" (generic, on-topic via the dollar) is not an EM-bond aside.
    data = {"currencies_commentary":
            "The dollar's decline supports emerging-market currencies broadly."}
    assert gmc._scrub_offtopic_em_bonds(data) == 0


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


def test_direction_word_extended_losses_flagged_when_asset_rose():
    # 6/26 regression: gold ROSE on the day (+1.36% in this snapshot) yet two fields
    # said "extended losses" / "extension of losses". The verb-only flip map missed
    # the noun-phrase trend, so the contradiction shipped.
    data = {
        "commodities_commentary":
            "Gold extended losses to $4,045.59 (+0.97%) as the dollar weakened.",
        "cross_asset_synthesis":
            "Gold's extension of losses signals the safe-haven bid is insufficient.",
    }
    assert gmc._check_direction_words(data, _SNAP_0601)                 # flagged
    fixes = gmc._correct_direction_words(data, _SNAP_0601)
    assert fixes == 2                                                   # both fields fixed
    assert "extended gains" in data["commodities_commentary"]
    assert "extension of gains" in data["cross_asset_synthesis"]
    assert "loss" not in data["cross_asset_synthesis"].lower()
    assert gmc._check_direction_words(data, _SNAP_0601) == []           # clean after


def test_direction_word_pared_losses_on_up_day_is_left_alone():
    # "pared losses" describes a REVERSAL toward green — coherent on an up day, so the
    # trend-noun flip must NOT touch it (only trend-CONTINUATION verbs flip).
    data = {"commodities_commentary": "Gold pared losses to finish higher on the session."}
    assert gmc._correct_direction_words(data, _SNAP_0601) == 0
    assert gmc._check_direction_words(data, _SNAP_0601) == []


# --- Asian-index settled-close reconciliation (6/26 Nikkei staleness) -----------
import datetime as _dtmod


def _patch_fast_info(monkeypatch, last_price):
    class _FI:
        pass
    fi = _FI()
    fi.last_price = last_price

    class _Tk:
        def __init__(self, *a, **k):
            pass
        @property
        def fast_info(self):
            return fi
    monkeypatch.setattr(gmc.yf, "Ticker", _Tk)


_US_MORNING = _dtmod.datetime(2026, 6, 26, 13, 0, tzinfo=_dtmod.timezone.utc)   # 8am CDT
_TOKYO_OPEN = _dtmod.datetime(2026, 6, 26, 2, 0, tzinfo=_dtmod.timezone.utc)    # Asia trading


def test_asian_index_rolls_forward_to_settled_close(monkeypatch):
    # 6/26: daily bar carried the 6/25 Tokyo close (72,366.34, +4.61%); the true 6/26
    # settled close (69,360.88, -4.15%, the value Sevens printed) sits in fast_info.
    _patch_fast_info(monkeypatch, 69360.88)
    q = {"level": 72366.34, "change": 3191.0, "pct_change": 4.61}
    out = gmc._reconcile_asian_index_close("^N225", q, now_utc=_US_MORNING)
    assert out["level"] == 69360.88
    assert out["pct_change"] == -4.15            # vs the daily bar as the prior session
    assert q["level"] == 72366.34                # input dict not mutated


def test_asian_index_noop_during_asia_trading_hours(monkeypatch):
    # Inside Asian trading, fast_info is a LIVE intraday tick, not a settled close —
    # the time gate must prevent adopting it.
    _patch_fast_info(monkeypatch, 69360.88)
    q = {"level": 72366.34, "change": 3191.0, "pct_change": 4.61}
    out = gmc._reconcile_asian_index_close("^N225", q, now_utc=_TOKYO_OPEN)
    assert out == q


def test_asian_index_noop_when_daily_bar_already_current(monkeypatch):
    # fast_info == daily bar → nothing to roll forward.
    _patch_fast_info(monkeypatch, 72366.34)
    q = {"level": 72366.34, "change": 100.0, "pct_change": 0.14}
    out = gmc._reconcile_asian_index_close("^N225", q, now_utc=_US_MORNING)
    assert out == q


def test_asian_index_rejects_garbage_quote(monkeypatch):
    # A wildly out-of-band fast_info value (bad tick) must be ignored.
    _patch_fast_info(monkeypatch, 5.0)
    q = {"level": 72366.34, "change": 100.0, "pct_change": 0.14}
    out = gmc._reconcile_asian_index_close("^N225", q, now_utc=_US_MORNING)
    assert out == q


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
        # 6/25 YCharts API migration supplies pct econ as DECIMAL fractions
        # (0.042 = 4.2%), not percentages. _fmt must scale these or every print
        # renders "0.0%" (the 6/25 regression). prev -0.007 -> "-0.7%", not "-0.0%".
        "CPI (YoY)":              {"value": 0.042,    "prev_value": 0.038,    "date": old_date},
        "Retail Sales (MoM)":     {"value": 0.048,    "prev_value": -0.007,   "date": old_date},
    }}
    (tmp_path / "market_data_arbitrated.json").write_text(_json.dumps(arb), encoding="utf-8")
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    rows = {r["indicator"]: r for r in gmc.load_recent_macro_prints()}
    assert rows["Initial Jobless Claims"]["actual"] == "215k"
    assert rows["Initial Jobless Claims"]["prior"] == "210k"
    assert rows["Nonfarm Payrolls"]["actual"] == "115k"   # already-thousands, not "0k"
    assert rows["Core PCE (YoY)"]["actual"] == "3.3%"     # already-percent (legacy) preserved
    # Decimal-fraction inputs (YCharts API) must scale to percent, not render 0.0%.
    assert rows["CPI (YoY)"]["actual"] == "4.2%"
    assert rows["Retail Sales (MoM)"]["actual"] == "4.8%"
    assert rows["Retail Sales (MoM)"]["prior"] == "-0.7%"
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
    # Spotlight subtracts tracking-only names (MAG7 + active MANGOS); none here.
    monkeypatch.setattr(uc, "get_tracking_only_tickers", lambda: [])
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


# --- 2026-06-30: present-tense dollar verbs + euro inverse in asset-class boxes ----
# DXY fell -0.25% on the day; the asset-class outlook boxes are written in present tense.
_SNAP_DXY_DOWN = {
    "U.S. Dollar (DXY)": {"pct_change": -0.25, "pct_change_1w": 0.1, "level": 101.11},
}


def test_present_tense_dollar_verb_flipped():
    # "the dollar strengthens" while DXY fell — past-tense-only map missed this pre-fix.
    data = {"asset_class_outlooks": {
        "Commodities": {"label": "Neutral",
                        "rationale": "Gold falls 1.35% as the dollar strengthens relative to demand."}}}
    n = gmc._correct_dollar_direction(data, _SNAP_DXY_DOWN)
    assert n == 1
    rat = data["asset_class_outlooks"]["Commodities"]["rationale"]
    assert "the dollar weakens" in rat
    assert "strengthens" not in rat


def test_weaker_euro_flipped_when_dollar_falls():
    # euro is ~58% of DXY: a falling dollar means a STRONGER euro, so "a weaker euro" is wrong.
    data = {"asset_class_outlooks": {
        "US Dollar": {"label": "Bearish",
                      "rationale": "The dollar index slips 0.25% as a weaker euro drives pairs higher."}}}
    n = gmc._correct_dollar_direction(data, _SNAP_DXY_DOWN)
    assert n == 1
    rat = data["asset_class_outlooks"]["US Dollar"]["rationale"]
    assert "stronger euro" in rat
    assert "weaker euro" not in rat


def test_present_tense_dollar_idempotent():
    data = {"asset_class_outlooks": {
        "Commodities": {"label": "Neutral", "rationale": "The dollar strengthens on the session."}}}
    gmc._correct_dollar_direction(data, _SNAP_DXY_DOWN)
    once = data["asset_class_outlooks"]["Commodities"]["rationale"]
    gmc._correct_dollar_direction(data, _SNAP_DXY_DOWN)
    assert data["asset_class_outlooks"]["Commodities"]["rationale"] == once


def test_correct_present_tense_dollar_left_alone():
    # DXY down + "the dollar weakens" is already correct — no change.
    data = {"asset_class_outlooks": {
        "US Dollar": {"label": "Bearish", "rationale": "The dollar weakens as risk appetite returns."}}}
    assert gmc._correct_dollar_direction(data, _SNAP_DXY_DOWN) == 0


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
    monkeypatch.setattr(post_run, "_git_dirty_code_paths", lambda: [])
    monkeypatch.setattr(post_run, "_unlisted_root_py", lambda: [])
    monkeypatch.setattr(post_run, "_scp_dir", lambda *a, **k: 1)  # every transfer fails
    assert post_run.sync_to_server() is False


def test_sync_to_server_returns_true_on_success(monkeypatch):
    post_run = pytest.importorskip("post_run")
    monkeypatch.setattr(post_run, "SYNC_DIRS", ["data"])
    monkeypatch.setattr(post_run, "SYNC_PY_FILES", [])
    monkeypatch.setattr(post_run, "_git_dirty_code_paths", lambda: [])
    monkeypatch.setattr(post_run, "_unlisted_root_py", lambda: [])
    monkeypatch.setattr(post_run, "_restart_service", lambda dest, key_args: True)
    monkeypatch.setattr(post_run, "_probe_health_origin", lambda **kw: (True, "origin status=ok"))
    monkeypatch.setattr(post_run, "_probe_health", lambda **kw: (True, "status=ok"))
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


# --- 2026-06-18 #6: wrong WEEKDAY name on a today event ("Friday's Philly Fed") -------
def test_event_day_slip_corrects_wrong_weekday_name():
    data = {
        "scenario_event": "Philly Fed",
        "scenario_event_day": "today",
        "report_date": "2026-06-18",   # a Thursday
        "cross_asset_synthesis": "Friday's Philly Fed survey is the next macro test.",
    }
    n = gmc._correct_event_day_slip(data)
    assert n >= 1
    assert "Today's Philly Fed" in data["cross_asset_synthesis"]  # capitalized at sentence start
    assert "Friday's Philly Fed" not in data["cross_asset_synthesis"]


def test_event_day_slip_keeps_weekday_when_it_matches_today():
    # 6/19 is a Friday — "Friday's Philly Fed" on a Friday is correct, leave it alone.
    data = {
        "scenario_event": "Philly Fed",
        "scenario_event_day": "today",
        "report_date": "2026-06-19",   # a Friday
        "cross_asset_synthesis": "Friday's Philly Fed survey is the next macro test.",
    }
    assert gmc._correct_event_day_slip(data) == 0
    assert "Friday's Philly Fed" in data["cross_asset_synthesis"]


def test_event_day_slip_weekday_is_forward_only():
    # A different weekday AFTER the event (event precedes it) must not be rewritten.
    data = {
        "scenario_event": "Philly Fed",
        "scenario_event_day": "today",
        "report_date": "2026-06-18",   # Thursday
        "cross_asset_synthesis": "Today's Philly Fed follows Wednesday's CPI revision.",
    }
    assert gmc._correct_event_day_slip(data) == 0
    assert "Wednesday's CPI" in data["cross_asset_synthesis"]


# --- 2026-06-30: "Friday's FHFA/JOLTS" when those print TODAY but scenario event is later
def _write_econ_cal(tmp_path, events):
    import json as _json
    (tmp_path / "economic_calendar.json").write_text(
        _json.dumps({"updated": "2026-06-30", "events": events}), encoding="utf-8")


def test_today_event_weekday_corrected_when_scenario_event_is_later(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    _write_econ_cal(tmp_path, [
        {"date": "2026-06-30", "event": "FHFA House Price Index", "importance": "medium"},
        {"date": "2026-06-30", "event": "JOLTS Job Openings", "importance": "medium"},
        {"date": "2026-07-01", "event": "ADP Employment Report", "importance": "high"},
    ])
    data = {
        "report_date": "2026-06-30",   # a Tuesday; FHFA/JOLTS print today, ADP is Wednesday
        "scenario_event": "ADP Employment Report",
        "scenario_event_day": "tomorrow",
        "cross_asset_synthesis": ("Friday's FHFA House Price Index and JOLTS Job Openings "
                                  "prints are the immediate catalysts to watch."),
    }
    n = gmc._correct_today_econ_event_weekday(data)
    assert n >= 1
    syn = data["cross_asset_synthesis"]
    # capitalized at sentence start, lowercase mid-sentence — either way "today's"
    assert "oday's FHFA House Price Index" in syn
    assert "Friday's FHFA" not in syn


def test_today_event_weekday_leaves_genuine_future_event(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    _write_econ_cal(tmp_path, [
        {"date": "2026-06-30", "event": "FHFA House Price Index", "importance": "medium"},
        {"date": "2026-07-02", "event": "Nonfarm Payrolls", "importance": "high"},
    ])
    data = {
        "report_date": "2026-06-30",
        "cross_asset_synthesis": "Thursday's Nonfarm Payrolls print is the week's main catalyst.",
    }
    # NFP is genuinely Thursday and not a today-event — must not be rewritten.
    assert gmc._correct_today_econ_event_weekday(data) == 0
    assert "Thursday's Nonfarm Payrolls" in data["cross_asset_synthesis"]


def test_today_event_weekday_idempotent_and_noops_without_calendar(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)   # empty dir → no calendar file
    data = {
        "report_date": "2026-06-30",
        "cross_asset_synthesis": "Friday's FHFA House Price Index prints today.",
    }
    assert gmc._correct_today_econ_event_weekday(data) == 0   # no calendar → no-op
    _write_econ_cal(tmp_path, [
        {"date": "2026-06-30", "event": "FHFA House Price Index", "importance": "medium"}])
    gmc._correct_today_econ_event_weekday(data)
    once = data["cross_asset_synthesis"]
    gmc._correct_today_econ_event_weekday(data)
    assert data["cross_asset_synthesis"] == once


# --- 2026-07-01: wrong weekday on a FUTURE event ("Friday's NFP" when NFP is Thursday) ----
def test_future_event_weekday_corrected_to_actual_day(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    _write_econ_cal(tmp_path, [
        {"date": "2026-07-02", "event": "Non-Farm Payrolls", "importance": "high"},   # Thursday
    ])
    data = {
        "report_date": "2026-07-01",   # Wednesday
        "cross_asset_synthesis": "Friday's Non-Farm Payrolls report is the key catalyst.",
        "economics_commentary": "Traders await Friday's Non-Farm Payrolls report.",
    }
    n = gmc._correct_future_econ_event_weekday(data)
    assert n >= 1
    assert "Thursday's Non-Farm Payrolls" in data["cross_asset_synthesis"]
    assert "Friday's Non-Farm Payrolls" not in data["cross_asset_synthesis"]
    assert "Thursday's Non-Farm Payrolls" in data["economics_commentary"]


def test_future_event_weekday_leaves_correct_day(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    _write_econ_cal(tmp_path, [
        {"date": "2026-07-02", "event": "Non-Farm Payrolls", "importance": "high"}])
    data = {
        "report_date": "2026-07-01",
        "cross_asset_synthesis": "Thursday's Non-Farm Payrolls print is the key catalyst.",
    }
    assert gmc._correct_future_econ_event_weekday(data) == 0
    assert "Thursday's Non-Farm Payrolls" in data["cross_asset_synthesis"]


def test_future_event_weekday_ignores_distant_event(tmp_path, monkeypatch):
    monkeypatch.setattr(gmc, "DATA_DIR", tmp_path)
    # CPI is 3 weeks out — a stray "Friday's CPI" should not be relabelled off a far date.
    _write_econ_cal(tmp_path, [
        {"date": "2026-07-22", "event": "CPI (YoY)", "importance": "high"}])
    data = {"report_date": "2026-07-01",
            "cross_asset_synthesis": "Friday's CPI (YoY) is the next inflation test."}
    assert gmc._correct_future_econ_event_weekday(data) == 0


# --- 2026-06-18 #6: US market-holiday awareness (NYSE calendar, not federal) ----------
def test_is_us_market_holiday_juneteenth():
    assert gmc._is_us_market_holiday("2026-06-19") is True       # Juneteenth — NYSE closed


def test_is_us_market_holiday_open_days():
    assert gmc._is_us_market_holiday("2026-06-18") is False      # ordinary Thursday
    assert gmc._is_us_market_holiday("2026-10-12") is False      # Columbus Day — NYSE OPEN
    assert gmc._is_us_market_holiday("") is False
    assert gmc._is_us_market_holiday("not-a-date") is False


# --- 2026-06-18 #6: email what-to-watch lead == scenario "Primary event" -------------
# Two same-day HIGH events. Raw feed order put Philly Fed first (→ watch_today[0], the email's
# first what-to-watch item) while catalyst priority ranks Initial Jobless Claims first
# (→ scenario_event, the "Primary event" header), so the two surfaces named different primary
# events on one page. Both the today_econ lead and the scenario picker sort by _catalyst_priority,
# so they must now agree on the same catalyst regardless of feed order.
def test_today_econ_lead_matches_scenario_primary_event():
    today = "2026-06-18"
    econ = [
        {"event": "Philadelphia Fed Manufacturing Index", "date": today, "importance": "high"},
        {"event": "Initial Jobless Claims", "date": today, "importance": "high"},
    ]
    today_econ = sorted(
        (e for e in econ if str(e.get("date", ""))[:10] == today),
        key=lambda e: gmc._catalyst_priority(e.get("event", "")),
    )
    today_events = sorted(  # mirrors the scenario picker's _today_events selection
        (e for e in econ if str(e.get("date", ""))[:10] == today and e.get("importance") == "high"),
        key=lambda e: gmc._catalyst_priority(e.get("event", "")),
    )
    assert today_econ[0]["event"] == today_events[0]["event"] == "Initial Jobless Claims"
    # And the priority itself must rank a known catalyst above an unmatched (default) one.
    assert gmc._catalyst_priority("Initial Jobless Claims") < gmc._catalyst_priority("Philadelphia Fed Manufacturing Index")


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

    def _fake(ticker, prev_close=None, mode="eod", verify_fresh=False):
        seen[ticker] = True
        if ticker == "XAUUSD=X":
            return {"level": 4475.40, "change": -44.0, "pct_change": -0.98}
        return {"level": 4436.70, "change": -52.0, "pct_change": -1.17}  # GC=F futures

    monkeypatch.setattr(gmc, "_fetch_quote", _fake)
    q = gmc._fetch_gold_quote()
    assert q["level"] == 4475.40, "should return the spot level"
    assert "GC=F" not in seen, "futures must not be fetched when spot is good"


def test_fetch_gold_quote_falls_back_to_futures_when_spot_and_gld_empty(monkeypatch):
    # Futures is now the LAST resort — reached only when both spot and the GLD proxy fail.
    def _fake(ticker, prev_close=None, mode="eod", verify_fresh=False):
        if ticker in ("XAUUSD=X", "GLD"):
            return None                       # spot feed flaked AND GLD proxy unavailable
        return {"level": 4436.70, "change": -52.0, "pct_change": -1.17}  # GC=F futures

    monkeypatch.setattr(gmc, "_fetch_quote", _fake)
    assert gmc._fetch_gold_quote()["level"] == 4436.70


def test_fetch_gold_quote_falls_back_when_spot_level_zero(monkeypatch):
    # A present-but-zero spot level is unusable → falls through (GLD also down here → futures).
    def _fake(ticker, prev_close=None, mode="eod", verify_fresh=False):
        if ticker == "XAUUSD=X":
            return {"level": 0, "change": None, "pct_change": None}   # present but unusable
        if ticker == "GLD":
            return None
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


# --- scenario buckets must be anchored to consensus (#2, regression 2026-06-05) --
# NFP consensus was 85K but the calendar feed had no consensus, so scenario_consensus
# was null and the LLM invented "Hot (<220K) / In Line (220K-240K) / Cold (>240K)".

def test_unanchored_scenario_thresholds_are_stripped():
    scenarios = [
        {"label": "Hot (<220K)", "thesis": "weak print fuels dovish bets"},
        {"label": "In Line (220K-240K)", "thesis": "matches consensus"},
        {"label": "Cold (>240K)", "thesis": "hot print revives rate fears"},
    ]
    n = gmc._strip_unanchored_scenario_thresholds(scenarios, None)
    assert n == 3
    assert [s["label"] for s in scenarios] == ["Hot", "In Line", "Cold"]


def test_anchored_scenario_thresholds_are_kept():
    scenarios = [
        {"label": "Hot (<70K)"}, {"label": "In Line (70K-100K)"}, {"label": "Cold (>100K)"},
    ]
    before = [s["label"] for s in scenarios]
    n = gmc._strip_unanchored_scenario_thresholds(scenarios, "85K")
    assert n == 0
    assert [s["label"] for s in scenarios] == before


def test_qualitative_parenthetical_without_number_is_kept():
    scenarios = [{"label": "Hot (dovish)"}, {"label": "In Line"}, {"label": "Cold (hawkish)"}]
    before = [s["label"] for s in scenarios]
    assert gmc._strip_unanchored_scenario_thresholds(scenarios, None) == 0
    assert [s["label"] for s in scenarios] == before


def test_unanchored_scenario_strip_is_idempotent():
    scenarios = [{"label": "Hot (<220K)"}, {"label": "In Line (220K-240K)"}, {"label": "Cold (>240K)"}]
    gmc._strip_unanchored_scenario_thresholds(scenarios, None)
    once = [s["label"] for s in scenarios]
    gmc._strip_unanchored_scenario_thresholds(scenarios, None)
    assert [s["label"] for s in scenarios] == once


# --- Fed-speaker harvest must require a SPEAKING event (#4, regression 2026-06-05) --
# "Fed's Warsh inherits economy increasingly squeezed by inflation ..." (a profile of the
# incoming chair) was harvested as a scheduled speaker. Require a speaking-context verb.

def test_harvest_skips_news_profile_without_speaking_verb():
    headlines = ["Fed's Warsh inherits economy increasingly squeezed by inflation. "
                 "New Fed Chair Kevin Warsh faces a challenging economy as policymakers "
                 "grow concerned about inflation."]
    assert gmc._harvest_fed_speakers_from_news(headlines) == []


def test_harvest_keeps_genuine_speaking_headlines():
    headlines = [
        "Fed's Daly says inflation remains too elevated for comfort",
        "Richmond Fed President Barkin speaks at 8:30 a.m. ET on the labor market",
    ]
    rows = gmc._harvest_fed_speakers_from_news(headlines)
    names = {r["speaker"] for r in rows}
    assert names == {"Fed's Daly", "Fed's Barkin"}
    barkin = next(r for r in rows if r["speaker"] == "Fed's Barkin")
    assert "8:30" in barkin["time_et"]


def test_harvest_skips_non_fed_context():
    # Apple's Tim Cook — surname collision, no Fed context → never harvested.
    assert gmc._harvest_fed_speakers_from_news(["Apple CEO Tim Cook says iPhone sales are strong"]) == []


def test_harvest_dedupes_against_existing_speakers():
    headlines = ["Fed's Daly speaks on the economic outlook this afternoon"]
    rows = gmc._harvest_fed_speakers_from_news(headlines, existing_speakers=[{"speaker": "Mary Daly"}])
    assert rows == []


# --- 2026-06-23: third-party commentary about the Fed is not a Fed speaking event --
def test_harvest_rejects_third_party_commentary_about_fed():
    # The exact 6/23 failure: a JPMorgan-sourced headline about Warsh became a "Fed's Warsh"
    # slot (Sevens carried NO Fed speakers that day). Warsh is the OBJECT, not the speaker.
    headlines = ["Circle Your Calendars for July 29. JPMorgan Executive Says Fed Chair "
                 "Kevin Warsh Could Raise Rates in As Little as Six Weeks."]
    assert gmc._harvest_fed_speakers_from_news(headlines, existing_speakers=[]) == []


def test_harvest_rejects_analyst_commentary_about_fed():
    headlines = ["Goldman strategist says the Fed's Waller will dissent at the next meeting"]
    assert gmc._harvest_fed_speakers_from_news(headlines, existing_speakers=[]) == []


def test_harvest_still_keeps_genuine_speaker_despite_bank_word():
    # A genuine Fed-speak headline where the official is the agent must still be harvested.
    headlines = ["Fed's Daly says bank capital rules need not slow lending, in 1:10 p.m. remarks"]
    rows = gmc._harvest_fed_speakers_from_news(headlines, existing_speakers=[])
    assert any("Daly" in r["speaker"] for r in rows)


# --- 2026-06-23: ungrounded Wall-Street-figure name scrub (invented "Bob Michael") --
def test_ungrounded_analyst_name_scrubbed():
    data = {"equities_commentary": (
        "Traders are watching the July 29 FOMC, where JPMorgan CIO Bob Michael suggests "
        "every meeting is now live.")}
    src = "JPMorgan Executive Says Fed Chair Kevin Warsh Could Raise Rates"
    gmc._scrub_ungrounded_analyst_attribution(data, src)
    out = data["equities_commentary"]
    assert "Bob Michael" not in out
    assert "a JPMorgan executive suggests" in out


def test_grounded_analyst_name_preserved():
    # A name present in the source headlines is a real quote — keep it intact.
    data = {"economics_commentary": "Goldman Sachs CEO David Solomon said rates stay higher."}
    src = "Goldman Sachs CEO David Solomon warns on higher-for-longer policy"
    gmc._scrub_ungrounded_analyst_attribution(data, src)
    assert "David Solomon" in data["economics_commentary"]


def test_ungrounded_analyst_possessive_form_scrubbed():
    data = {"cross_asset_synthesis": "Pimco's Jane Doe expects duration to outperform."}
    gmc._scrub_ungrounded_analyst_attribution(data, "no relevant names in the wire today")
    out = data["cross_asset_synthesis"]
    assert "Jane Doe" not in out and "Pimco executive" in out


def test_analyst_scrub_noop_without_source():
    data = {"economics_commentary": "JPMorgan CIO Bob Michael sees cuts."}
    assert gmc._scrub_ungrounded_analyst_attribution(data, "") == 0


# --- gold spot: 3-tier fallback XAUUSD=X -> GLD*ratio -> futures (#5, 2026-06-05) --
# XAUUSD=X 404s intermittently. We then report a GLD-derived SPOT level (GLD is
# physically-backed spot gold), scaled by a ratio that self-calibrates off live spot;
# futures are only the last resort. Each test redirects the ratio cache to a tmp file.

def _gold_quotes(spot=None, gld=None, fut=None):
    def fake(ticker, prev_close=None, mode="eod", verify_fresh=False):
        if ticker == gmc.GOLD_SPOT_TICKER:
            return spot
        if ticker == gmc.GOLD_GLD_PROXY_TICKER:
            return gld
        if ticker == gmc.GOLD_FUTURES_TICKER:
            return fut
        return None
    return fake


def test_gold_uses_true_spot_and_recalibrates_ratio(monkeypatch, tmp_path):
    monkeypatch.setattr(gmc, "GOLD_GLD_RATIO_PATH", tmp_path / "ratio.json")
    monkeypatch.setattr(gmc, "_fetch_quote", _gold_quotes(
        spot={"level": 4340.0, "change": 38.0, "pct_change": 0.88},
        gld={"level": 396.24, "change": 3.5, "pct_change": 0.89}))
    q = gmc._fetch_gold_quote()
    assert q["level"] == 4340.0 and q["_source"] == gmc.GOLD_SPOT_TICKER
    # ratio cached for future outages: 4340/396.24 ~= 10.953
    assert abs(gmc._load_gld_spot_ratio() - (4340.0 / 396.24)) < 1e-3


def test_gold_uses_gld_derived_spot_when_spot_down(monkeypatch, tmp_path, capsys):
    # Seed a calibrated ratio, then drop the spot feed.
    rp = tmp_path / "ratio.json"
    rp.write_text('{"ratio": 10.95}', encoding="utf-8")
    monkeypatch.setattr(gmc, "GOLD_GLD_RATIO_PATH", rp)
    monkeypatch.setattr(gmc, "_fetch_quote", _gold_quotes(
        spot=None, gld={"level": 396.24, "change": 3.5, "pct_change": 0.89},
        fut={"level": 4353.9, "change": 38.0, "pct_change": 0.88}))
    q = gmc._fetch_gold_quote()
    assert q["level"] == round(10.95 * 396.24, 2)        # GLD-derived spot, not futures
    assert q["pct_change"] == 0.89                        # daily % preserved from GLD
    assert q["_source"].startswith("GLD*")
    assert "gld-derived" in capsys.readouterr().out.lower()


def test_gold_falls_back_to_futures_only_when_gld_also_down(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(gmc, "GOLD_GLD_RATIO_PATH", tmp_path / "ratio.json")
    monkeypatch.setattr(gmc, "_fetch_quote", _gold_quotes(
        spot=None, gld=None, fut={"level": 4353.9, "change": 38.0, "pct_change": 0.88}))
    q = gmc._fetch_gold_quote()
    assert q["level"] == 4353.9 and q["_source"] == gmc.GOLD_FUTURES_TICKER
    assert "futures" in capsys.readouterr().out.lower()


def test_gld_ratio_cache_rejects_implausible_values(monkeypatch, tmp_path):
    rp = tmp_path / "ratio.json"
    monkeypatch.setattr(gmc, "GOLD_GLD_RATIO_PATH", rp)
    gmc._save_gld_spot_ratio(4340.0, 396.24)             # ~10.95 → saved
    assert abs(gmc._load_gld_spot_ratio() - 10.953) < 0.01
    gmc._save_gld_spot_ratio(4340.0, 4505.8)             # ~0.96 → out of band, rejected
    assert abs(gmc._load_gld_spot_ratio() - 10.953) < 0.01  # unchanged
    rp.write_text("{not json", encoding="utf-8")          # corrupt → seed
    assert gmc._load_gld_spot_ratio() == gmc.GOLD_GLD_RATIO_SEED


def test_kinetic_scrub_robust_to_us_abbreviation():
    # Regression 2026-06-05: "U.S. warships" split the sentence at "S." in the naive
    # splitter, separating verb from noun so the clause survived. Must be stripped now,
    # keeping the grounded lead ("Gulf hostilities flared" — corpus vocabulary).
    data = {"session_recap": [
        "WTI Crude fell 3.1% to $93.04 as Gulf hostilities flared and Iranian attacks on "
        "U.S. warships in the Gulf of Oman boosted safe-haven demand for oil."
    ]}
    gmc._scrub_fabricated_kinetic_detail(data, _GEO_CORPUS)
    out = data["session_recap"][0]
    assert "warship" not in out.lower()
    assert out.startswith("WTI Crude fell 3.1% to $93.04 as Gulf hostilities flared")


def test_unreleased_attribution_catches_employment_data_phrasing():
    # "the strong employment data" is the same unreleased-NFP attribution, phrased loosely.
    data = {
        "scenario_event": "Non-Farm Payrolls / Jobs Report",
        "session_recap": ["10-year yield fell 2 bp to 4.47% as the strong employment data lifted yields."],
    }
    gmc._scrub_unreleased_event_attribution(data)
    assert data["session_recap"][0] == "10-year yield fell 2 bp to 4.47%."


# --- 2026-06-15: degenerate LLM repetition loop in economics_commentary ------
_ECON_LOOP_UNIT = (
    "vs 0.5% prior indicates a robust economy. "
    "The latest Unemployment Rate at 4.3% vs 4.3% prior remains stable. "
    "The latest PPI reading at 13.1% YoY vs 9.4% prior shows rising input costs. "
)


def test_degenerate_repetition_collapsed_and_leading_fragment_trimmed():
    # Reproduces the 6/15 failure: the same 3-sentence block looped ~40 times,
    # opening mid-clause with "vs 0.5% prior ...".
    data = {"economics_commentary": (_ECON_LOOP_UNIT * 40).strip()}
    fixes = gmc._scrub_degenerate_repetition(data)
    assert fixes == 1
    out = data["economics_commentary"]
    # the dangling lowercase opener is dropped
    assert not out.startswith("vs ")
    # each surviving sentence appears exactly once
    assert out.count("remains stable") == 1
    assert out.count("shows rising input costs") == 1
    # grounded content is preserved
    assert "Unemployment Rate at 4.3%" in out


def test_degenerate_repetition_sweeps_all_prose_fields():
    dupe = "Materials led the session as risk appetite returned."
    data = {"equities_commentary": f"{dupe} {dupe} {dupe}"}
    assert gmc._scrub_degenerate_repetition(data) == 1
    assert data["equities_commentary"] == dupe


def test_degenerate_repetition_idempotent_and_clean_prose_untouched():
    clean = ("The S&P 500 rose 0.5% to 7,431 as peace-deal hopes lifted risk appetite. "
             "Materials led while Communication Services lagged.")
    data = {"equities_commentary": clean}
    assert gmc._scrub_degenerate_repetition(data) == 0
    assert data["equities_commentary"] == clean


def test_degenerate_repetition_preserves_legit_short_repeats():
    # short identical fragments (<=20 chars normalized) are not treated as dupes
    data = {"pre_market_bullets": ["Yields fell. Yields fell."]}
    gmc._scrub_degenerate_repetition(data)
    assert data["pre_market_bullets"][0] == "Yields fell. Yields fell."


def test_interior_connector_fragment_dropped():
    # a mid-paragraph sentence opening with a lowercase connector ("vs ...") is a
    # loop/truncation artifact and must be removed even when it is not the lead.
    data = {"economics_commentary":
            "The economy looks solid. vs 0.5% prior indicates a robust economy. Claims rose to 229k."}
    assert gmc._scrub_degenerate_repetition(data) == 1
    out = data["economics_commentary"]
    assert "vs 0.5%" not in out
    assert out.startswith("The economy looks solid")
    assert "Claims rose to 229k" in out


def test_lowercase_brand_sentence_preserved():
    # legit sentences that open with a lowercase brand (xAI) are NOT fragments
    data = {"equities_commentary":
            "Chip names led the tape. xAI's compute demand lifted NVDA. Tech closed green."}
    assert gmc._scrub_degenerate_repetition(data) == 0
    assert "xAI's compute demand lifted NVDA" in data["equities_commentary"]


# --- 2026-06-15: scenario catalyst priority (FOMC must anchor over Retail Sales) ---
def test_catalyst_priority_fomc_beats_retail_sales():
    assert gmc._catalyst_priority("FOMC Meeting / Rate Decision") < gmc._catalyst_priority("Retail Sales")


def test_catalyst_priority_decision_beats_minutes():
    assert gmc._catalyst_priority("FOMC Meeting / Rate Decision") < gmc._catalyst_priority("Fed FOMC Minutes")


def test_catalyst_priority_high_data_beats_nowcast():
    # a high macro print outranks a medium nowcast (GDPNow) on tie-break
    assert gmc._catalyst_priority("CPI Inflation Report") < gmc._catalyst_priority("Atlanta Fed GDPNow Estimate")
    assert gmc._catalyst_priority("Retail Sales") < gmc._catalyst_priority("Atlanta Fed GDPNow Estimate")


def test_catalyst_priority_same_date_sort_picks_fomc():
    # mirrors the 6/17 collision: FOMC + Retail Sales same day -> FOMC selected
    econ = [
        {"date": "2026-06-17", "event": "Retail Sales", "importance": "high"},
        {"date": "2026-06-17", "event": "FOMC Meeting / Rate Decision", "importance": "high"},
    ]
    pick = sorted(econ, key=lambda e: (e["date"], gmc._catalyst_priority(e["event"])))[0]
    assert pick["event"] == "FOMC Meeting / Rate Decision"


# --- spec #4: prescriptive -> non-advice optioned framing (spotlight) ----------
def test_spotlight_softens_prescriptive_directive():
    txt = "Investors should express this view by leaning into ARKK, which captures innovation."
    out = gmc._scrub_spotlight_text(txt)
    assert "should express this view by leaning into" not in out
    assert "One way to express this view is via ARKK" in out


def test_spotlight_softens_generic_should_buy():
    out = gmc._scrub_spotlight_text("Investors should buy SPY here.")
    assert "should buy" not in out
    assert out.startswith("One way to express this is via SPY")


def test_spotlight_scrub_leaves_optioned_text_alone():
    txt = "One way to express this is via SMH; the thesis breaks if hyperscaler capex falls."
    assert gmc._scrub_spotlight_text(txt) == txt


# --- spec #2: stance-stability (a sharp reversal must be explained) ------------
def test_stance_notch_distance_bearish_to_bullish_is_three():
    assert gmc._stance_notch_distance("Bearish", "Bullish") == 3
    assert gmc._stance_notch_distance("Cautious", "Bullish") == 2
    assert gmc._stance_notch_distance("Neutral", "Bullish") == 1
    assert gmc._stance_notch_distance("Bullish", "Bullish") == 0
    assert gmc._stance_notch_distance(None, "Bullish") == 0   # no prior -> no distance


def test_sharp_reversal_unexplained_is_flagged():
    data = {"market_outlook_label": "Bullish",
            "market_outlook_rationale": "Equities advance as the peace deal lifts risk appetite. Fed policy is the risk."}
    assert gmc._check_stance_reversal_unexplained(data, "Bearish")


def test_sharp_reversal_acknowledged_passes():
    data = {"market_outlook_label": "Bullish",
            "market_outlook_rationale": "The view flips from bearish as the peace deal removes the Hormuz risk. Fed policy is the risk."}
    assert gmc._check_stance_reversal_unexplained(data, "Bearish") == ""


def test_small_stance_move_not_flagged():
    data = {"market_outlook_label": "Neutral",
            "market_outlook_rationale": "Balanced macro keeps the tape range-bound. A hot print is the risk."}
    # Cautious -> Neutral is one notch; no explanation required
    assert gmc._check_stance_reversal_unexplained(data, "Cautious") == ""


# --- 2026-06-17: growth-multiple causal-inversion guard (#3) ----------------
# Falling oil / falling yields RELIEVE growth multiples; they cannot compress them.
_TAILWIND_SNAP = {"WTI Crude": {"pct_change": -5.82}, "10-Yr Yield": {"bp_change": -4.0}}


def test_growth_multiple_inversion_flagged_on_tailwind_day():
    data = {"cross_asset_synthesis": (
        "Equities fell because the US-Iran peace deal removed the Hormuz disruption premium, "
        "causing WTI Crude to plunge 5.82% to $76.05 and compressing tech multiples.")}
    assert gmc._check_growth_multiple_inversion(data, _TAILWIND_SNAP)


def test_growth_multiple_inversion_not_flagged_on_oil_yield_up_day():
    # On an oil/yield-UP day, multiple compression is the CORRECT direction — must pass.
    up_snap = {"WTI Crude": {"pct_change": 2.1}, "10-Yr Yield": {"bp_change": 6.0}}
    data = {"cross_asset_synthesis": "Rising yields and surging oil compressed tech multiples sharply."}
    assert gmc._check_growth_multiple_inversion(data, up_snap) == []


def test_growth_multiple_relief_phrasing_is_clean():
    # The correct causal direction (relief, not compression) must not trip the guard.
    data = {"fixed_income_commentary": (
        "At a 10-year yield near 4.43%, the curve's flattening supports growth-name multiples "
        "by reducing discount rates.")}
    assert gmc._check_growth_multiple_inversion(data, _TAILWIND_SNAP) == []


# --- 2026-06-18: de-escalation/premium-removal compression is ALWAYS inverted ---
# Regression: on a day oil/yields ROSE, "the removal of the Hormuz disruption premium
# compressed tech multiples" slipped through because the snapshot gate (built for the
# falling-oil/yield family) suppressed the whole check. Removing an inflation premium is
# disinflationary — it relieves multiples — so this family must fire regardless of the tick.
_UP_SNAP = {"WTI Crude": {"pct_change": 0.97}, "10-Yr Yield": {"bp_change": 6.0}}


def test_deescalation_compression_flagged_even_on_oil_yield_up_day():
    data = {"market_outlook_rationale": (
        "The removal of the Hormuz disruption premium compressed tech multiples and lifted the dollar.")}
    assert gmc._check_growth_multiple_inversion(data, _UP_SNAP)


def test_peace_deal_as_cause_of_compression_flagged():
    data = {"equities_commentary": (
        "The peace deal removed the inflation premium and compressed growth multiples.")}
    assert gmc._check_growth_multiple_inversion(data, _UP_SNAP)


def test_compression_despite_peace_deal_is_concessive_and_clean():
    # "compressing multiples DESPITE the peace deal" — the deal is the foil, not the cause.
    data = {"cross_asset_synthesis": (
        "A hawkish Fed compressed growth-name multiples despite the peace deal that reopened Hormuz.")}
    assert gmc._check_growth_multiple_inversion(data, _UP_SNAP) == []


# --- 2026-06-18: sector daily change must anchor to the last COMPLETED session ---
def test_completed_daily_change_drops_partial_today_bar():
    import pandas as pd
    from datetime import date
    idx = pd.to_datetime(["2026-06-16", "2026-06-17", "2026-06-18"])
    closes = pd.Series([100.0, 98.79, 99.60], index=idx)  # 6/18 = partial intraday bounce
    pct, last = gmc._completed_daily_change(closes, date(2026, 6, 18))
    assert pct == -1.21 and last == 98.79  # 6/17 vs 6/16, partial 6/18 dropped


def test_completed_daily_change_keeps_prior_session_when_no_today_bar():
    import pandas as pd
    from datetime import date
    idx = pd.to_datetime(["2026-06-16", "2026-06-17"])
    closes = pd.Series([100.0, 98.79], index=idx)
    pct, last = gmc._completed_daily_change(closes, date(2026, 6, 18))
    assert pct == -1.21 and last == 98.79


# --- 2026-06-18: gold snapshot↔commodities-table cross-wire reconciliation (#4) ---
# The two tables fetch gold independently; an intermittent XAUUSD=X 404 can split them
# across tiers (futures vs spot) with opposite signs. _reconcile_gold forces both onto
# the better-tier quote so they can never disagree.

def test_gold_tier_rank_orders_spot_proxy_futures():
    assert gmc._gold_tier_rank({"_source": gmc.GOLD_SPOT_TICKER}) == 0
    assert gmc._gold_tier_rank({"_source": "GLD*0.091"}) == 1
    assert gmc._gold_tier_rank({"_source": gmc.GOLD_FUTURES_TICKER}) == 2
    assert gmc._gold_tier_rank({}) == 3
    assert gmc._gold_tier_rank(None) == 3


def test_reconcile_gold_prefers_spot_over_futures_and_mirrors_both():
    # 6/18 replay: snapshot fell to COMEX futures (+1.06%, contango), table got spot (-2.27%).
    snapshot = {"Gold": {"level": 4300.17, "pct_change": 1.06, "_source": gmc.GOLD_FUTURES_TICKER}}
    cmdty    = {"Gold": {"level": 4255.17, "pct_change": -2.27, "_source": gmc.GOLD_SPOT_TICKER}}
    canon = gmc._reconcile_gold(snapshot, cmdty)
    assert canon["_source"] == gmc.GOLD_SPOT_TICKER
    assert canon["pct_change"] == -2.27
    # Both tables now carry the identical (spot) quote — no level or sign divergence.
    assert snapshot["Gold"]["level"] == cmdty["Gold"]["level"] == 4255.17
    assert snapshot["Gold"]["pct_change"] == cmdty["Gold"]["pct_change"] == -2.27


def test_reconcile_gold_keeps_spot_when_snapshot_already_better():
    snapshot = {"Gold": {"level": 4255.0, "pct_change": -2.27, "_source": gmc.GOLD_SPOT_TICKER}}
    cmdty    = {"Gold": {"level": 4300.0, "pct_change": 1.06, "_source": gmc.GOLD_FUTURES_TICKER}}
    canon = gmc._reconcile_gold(snapshot, cmdty)
    assert canon["_source"] == gmc.GOLD_SPOT_TICKER
    assert snapshot["Gold"] == cmdty["Gold"]


def test_reconcile_gold_noop_when_gold_missing():
    assert gmc._reconcile_gold({}, {"Gold": {"level": 1.0, "_source": "GLD*0.09"}}) is None
    assert gmc._reconcile_gold({"Gold": {"level": 1.0}}, {}) is None


# --- #3 belt-and-suspenders: same-day tactical stance vs 4-6wk outlook label ---

def test_tactical_riskon_vs_bearish_label_gets_reconciliation_note():
    data = {"market_outlook_label": "Bearish",
            "tactical_positioning": {"stance": "Risk-on, pro-cyclical",
                                     "stance_detail": "Leading: Tech +2.5%."}}
    assert gmc._reconcile_tactical_stance_with_outlook(data) == 1
    detail = data["tactical_positioning"]["stance_detail"]
    assert "single-session" in detail and "Bearish" in detail and "4-6 week" in detail


def test_tactical_riskoff_vs_bullish_label_gets_reconciliation_note():
    data = {"market_outlook_label": "Bullish",
            "tactical_positioning": {"stance": "Risk-off, defensive bid", "stance_detail": "Leading: Utilities."}}
    assert gmc._reconcile_tactical_stance_with_outlook(data) == 1
    assert "single-session" in data["tactical_positioning"]["stance_detail"]


def test_tactical_stance_aligned_with_label_is_left_alone():
    data = {"market_outlook_label": "Bearish",
            "tactical_positioning": {"stance": "Risk-off, defensive bid", "stance_detail": "Leading: Staples."}}
    assert gmc._reconcile_tactical_stance_with_outlook(data) == 0
    assert data["tactical_positioning"]["stance_detail"] == "Leading: Staples."


def test_tactical_reconciliation_is_idempotent():
    data = {"market_outlook_label": "Bearish",
            "tactical_positioning": {"stance": "Risk-on, pro-cyclical", "stance_detail": "Leading: Tech."}}
    assert gmc._reconcile_tactical_stance_with_outlook(data) == 1
    assert gmc._reconcile_tactical_stance_with_outlook(data) == 0  # second pass adds nothing


def test_tactical_reconciliation_noop_without_label_or_stance():
    assert gmc._reconcile_tactical_stance_with_outlook({"tactical_positioning": {"stance": "Risk-on"}}) == 0
    assert gmc._reconcile_tactical_stance_with_outlook({"market_outlook_label": "Bearish"}) == 0
    assert gmc._reconcile_tactical_stance_with_outlook({}) == 0


# --- 2026-06-17: asset-class stance↔rationale coherence guard (#4) -----------

def test_aco_bearish_label_bullish_opener_is_flagged():
    part2 = {"asset_class_outlooks": {
        "Equities": {"label": "Bearish",
                     "rationale": "Forward earnings growth remains robust. Concentration risk amplifies volatility."}}}
    assert gmc._check_asset_class_stance_coherence(part2)


def test_aco_bullish_label_bearish_opener_is_flagged():
    part2 = {"asset_class_outlooks": {
        "Fixed Income": {"label": "Bullish",
                         "rationale": "Decelerating demand and margin pressure weigh on the complex."}}}
    assert gmc._check_asset_class_stance_coherence(part2)


def test_aco_coherent_rows_pass():
    part2 = {"asset_class_outlooks": {
        "Equities": {"label": "Bullish",
                     "rationale": "Forward earnings growth remains robust as AI capex accelerates."},
        "Fixed Income": {"label": "Bearish",
                         "rationale": "Decelerating demand and sticky inflation pressure duration."}}}
    assert gmc._check_asset_class_stance_coherence(part2) is None


def test_aco_neutral_label_not_enforced():
    part2 = {"asset_class_outlooks": {
        "US Dollar": {"label": "Neutral",
                      "rationale": "Robust rate differentials keep the dollar range-bound."}}}
    assert gmc._check_asset_class_stance_coherence(part2) is None


# --- 2026-06-17: off-universe currency scrub (#5) ----------------------------

def test_offuniverse_currency_clause_trimmed():
    data = {"currencies_commentary": (
        "The dollar's decline reflects easing inflation concerns and lower Treasury yields, "
        "with the ringgit opening higher against the US dollar on Fed hold expectations.")}
    assert gmc._scrub_offuniverse_currency(data) == 1
    assert "ringgit" not in data["currencies_commentary"]
    assert "easing inflation concerns" in data["currencies_commentary"]


def test_offuniverse_currency_clean_prose_left_alone():
    data = {"currencies_commentary": "The dollar fell 0.2% as EUR/USD rose and the yen firmed."}
    assert gmc._scrub_offuniverse_currency(data) == 0


def test_offuniverse_currency_scrub_is_idempotent():
    data = {"currencies_commentary": (
        "The dollar slipped, with the peso sliding 1% on local risk and the rupee softer too.")}
    gmc._scrub_offuniverse_currency(data)
    once = data["currencies_commentary"]
    gmc._scrub_offuniverse_currency(data)
    assert data["currencies_commentary"] == once


# --- 2026-06-22: risk-on / risk-off polarity guard --------------------------
# A clearly RISK-ON session (S&P +1.08% on Iran de-escalation, gold/oil falling as the
# geopolitical premium unwound) was repeatedly labeled "risk-off". De-escalation that
# drains the safe-haven bid while equities rally is risk-ON, not risk-off.
_RISKON_SNAP = {"S&P 500": {"pct_change": 1.08}}
_RISKOFF_SNAP = {"S&P 500": {"pct_change": -1.0}}


def test_risk_off_supporting_equities_flagged_on_up_day():
    # The exact 6/22 page-2 failure (family A).
    data = {"equities_commentary": (
        "The S&P 500 closed higher at 7,500.58 as U.S.-Iran peace talks provided a "
        "risk-off backdrop that supported broad equities.")}
    assert gmc._check_risk_polarity_inversion(data, _RISKON_SNAP)


def test_risk_off_dominant_theme_flagged_on_up_day():
    # The exact 6/22 synthesis failure framing (family B / C).
    data = {"cross_asset_synthesis": (
        "Risk-off sentiment from peace talks is the dominant cross-asset theme as the "
        "dollar firms.")}
    assert gmc._check_risk_polarity_inversion(data, _RISKON_SNAP)


def test_falling_safe_haven_labeled_risk_off_flagged():
    # The exact 6/22 commodities failure (family C) — falling silver called risk-off.
    data = {"commodities_commentary": (
        "Silver tumbled 6.28% to $66.26, reflecting broader risk-off sentiment in "
        "precious metals.")}
    assert gmc._check_risk_polarity_inversion(data, _RISKON_SNAP)


def test_risk_on_with_falling_equities_flagged():
    # Symmetric family A: risk-on label on a day equities fell.
    data = {"cross_asset_synthesis": "Risk-on conditions pushed the S&P 500 sharply lower."}
    assert gmc._check_risk_polarity_inversion(data, _RISKOFF_SNAP)


def test_session_recap_list_field_is_scanned():
    # session_recap is a list[str]; the guard must expand it.
    data = {"session_recap": [
        "S&P 500 closed higher at 7,500.58, +1.08%.",
        "Gold slipped to $4,207 as risk-off sentiment gripped bullion.",
        "WTI fell on easing supply fears."]}
    assert gmc._check_risk_polarity_inversion(data, _RISKON_SNAP)


def test_coherent_risk_off_on_down_day_is_clean():
    # Genuine risk-off day: equities fell, havens bid. Must NOT flag.
    data = {"cross_asset_synthesis": (
        "Risk-off was the prevailing theme as the S&P 500 fell 1.2% and gold rallied "
        "on a safe-haven bid.")}
    assert gmc._check_risk_polarity_inversion(data, _RISKOFF_SNAP) == []


def test_cross_asset_divergence_on_down_day_not_flagged():
    # The exact false-positive we engineered against: a down-day verb on the OTHER asset.
    data = {"cross_asset_synthesis": (
        "Risk-off dominated the tape as the S&P 500 fell and Treasuries rallied.")}
    assert gmc._check_risk_polarity_inversion(data, _RISKOFF_SNAP) == []


def test_concessive_risk_off_divergence_is_clean():
    # Explicitly-stated divergence with a concessive — coherent, must pass.
    data = {"cross_asset_synthesis": (
        "Equities rallied even as a residual bid for Treasuries signaled risk-off "
        "caution beneath the surface.")}
    assert gmc._check_risk_polarity_inversion(data, _RISKON_SNAP) == []


def test_risk_off_fading_is_clean():
    # "risk-off faded" = the regime DECREASING; falling havens are then correct.
    data = {"fixed_income_commentary": "Treasuries fell as risk-off faded across the board."}
    assert gmc._check_risk_polarity_inversion(data, _RISKON_SNAP) == []


def test_plain_risk_on_rally_is_clean():
    # Correct usage: risk-on + equities up. Must never flag.
    data = {"equities_commentary": "Risk-on flows lifted the S&P 500 as cyclicals led."}
    assert gmc._check_risk_polarity_inversion(data, _RISKON_SNAP) == []


# --- 2026-06-23: direct "risk-on/off environment" assertion vs the session sign (family D) --
# The polarity guard fixed the LABEL layer on 6/22 but the 6/23 synthesis still asserted "...are
# the dominant drivers, confirming a risk-on environment" on a -0.37% (risk-OFF) day. The singular
# `\bdriver\b` theme-marker missed the plural "drivers", and the broad concessive skip swallowed
# the commodities line via a trailing "despite". Family D flags the direct regime assertion.
def test_risk_on_environment_asserted_on_down_day_flagged():
    data = {"cross_asset_synthesis": (
        "Gold declined 0.65% as the dollar firmed, confirming a risk-on environment where "
        "hawkish Fed expectations are the dominant drivers.")}
    assert gmc._check_risk_polarity_inversion(data, _RISKOFF_SNAP)


def test_risk_on_environment_despite_clause_not_excused():
    # A trailing "...despite <other thing>" must NOT license the wrong regime label.
    data = {"commodities_commentary": (
        "The complex is trading in a risk-on environment where the dollar's strength and "
        "hawkish Fed expectations are the dominant drivers, suppressing safe-haven demand "
        "despite lingering geopolitical uncertainty.")}
    assert gmc._check_risk_polarity_inversion(data, _RISKOFF_SNAP)


def test_dominant_drivers_plural_theme_marker_flagged():
    # The plural "drivers" must trip family B just like singular "driver".
    data = {"cross_asset_synthesis": (
        "Risk-off positioning is among the dominant drivers as the S&P 500 advanced.")}
    assert gmc._check_risk_polarity_inversion(data, _RISKON_SNAP)


def test_risk_off_environment_faded_is_clean():
    # Fading carve-out still applies to the direct-assertion family.
    data = {"commodities_commentary": (
        "Commodities firmed as the risk-off environment faded into the close.")}
    assert gmc._check_risk_polarity_inversion(data, _RISKON_SNAP) == []


def test_risk_on_environment_on_up_day_is_clean():
    # Correct usage: a risk-on environment asserted on an up day must never flag.
    data = {"cross_asset_synthesis": (
        "Equities led broadly in a risk-on environment where cyclicals are the dominant drivers.")}
    assert gmc._check_risk_polarity_inversion(data, _RISKON_SNAP) == []


# --- 2026-06-23: "interest rate hike" compound must reframe grammatically -----
# The bare `rate hikes?` rule stripped only "rate hike" and orphaned "interest", shipping the
# ungrammatical "...Federal Reserve interest higher-for-longer rates in December".
def test_interest_rate_hike_compound_reframed_grammatically():
    data = {"commodities_commentary": (
        "Gold fell on rising expectations of a Federal Reserve interest rate hike in December.")}
    gmc._correct_fed_hike_language(data)
    out = data["commodities_commentary"]
    assert "hike" not in out.lower()
    assert "interest higher-for-longer" not in out.lower()   # no orphaned "interest"
    assert "Federal Reserve higher-for-longer rate path in December" in out


def test_interest_rate_hike_idempotent():
    data = {"economics_commentary": "Markets priced an interest rate hike."}
    gmc._correct_fed_hike_language(data)
    first = data["economics_commentary"]
    gmc._correct_fed_hike_language(data)
    assert data["economics_commentary"] == first
    assert "hike" not in first.lower()


# --- 2026-06-23: spotlight topic-coherence guard (PRIM teaser over a Roblox body) --
def test_spotlight_offtopic_mover_detects_drift():
    sel = {"kind": "mover", "mover_ticker": "PRIM",
           "topic": "Primoris Services Corporation (PRIM) -27.5%"}
    roblox_body = ("The market's defensive rotation intensified as Roblox (RBLX) fell 9%, "
                   "extending its drawdown while communication services lagged the tape.")
    assert gmc._spotlight_offtopic_mover(roblox_body, sel) is True
    on_topic = ("Primoris cratered 27% after slashing guidance, dragging industrials lower.")
    assert gmc._spotlight_offtopic_mover(on_topic, sel) is False
    assert gmc._spotlight_offtopic_mover("Shares of PRIM collapsed on the print.", sel) is False
    # non-mover spotlights are never off-topic
    assert gmc._spotlight_offtopic_mover(roblox_body, {"kind": "theme", "topic": "x"}) is False


# --- 2026-06-22: global central-bank event harvester (#1 macro feed) ---------
# The econ calendar is US-only; foreign CB decisions reach the LLM only via the news
# wire. EPM missed the BOJ 25bp hike on 6/18 and 6/22.

def test_boj_hike_harvested_from_news_dict():
    buckets = {"economy": [
        "Bank of Japan raises rates 25 bp to highest since 1995 in hawkish surprise",
        "Some unrelated equity headline about chips"]}
    rows = gmc._harvest_global_macro_from_news(buckets)
    assert any(r["institution"] == "BOJ" for r in rows)


def test_ecb_hold_harvested_from_flat_list():
    rows = gmc._harvest_global_macro_from_news([
        "ECB holds rates steady, signals data-dependent path ahead"])
    assert any(r["institution"] == "ECB" for r in rows)


def test_central_bank_mention_without_action_not_harvested():
    # A speaker mention with no policy action must NOT register as an event.
    rows = gmc._harvest_global_macro_from_news([
        "ECB's Lagarde to attend a panel discussion in Frankfurt next week"])
    assert rows == []


def test_non_central_bank_headline_ignored():
    rows = gmc._harvest_global_macro_from_news([
        "Apple unveils new product lineup; analysts raise price targets"])
    # "raise" is an action token but no CB institution → must not register.
    assert rows == []


def test_global_macro_harvest_dedupes_by_institution():
    rows = gmc._harvest_global_macro_from_news([
        "Bank of Japan hikes to 31-year high",
        "BOJ raises rates again in surprise move",
        "ECB cuts 25 bp"])
    insts = [r["institution"] for r in rows]
    assert insts.count("BOJ") == 1 and "ECB" in insts


def test_speculative_rate_chatter_not_harvested():
    # The exact 6/22 live false-positive: speculative India/RBI commentary, no decision.
    rows = gmc._harvest_global_macro_from_news([
        "Falling crude oil prices might boost growth beyond central bank forecasts, "
        "potentially easing rate hike needs for the RBI"])
    assert rows == []


def test_future_tense_cb_announcement_not_harvested():
    # "to hike next week" / "will raise" are not DECISIONS.
    rows = gmc._harvest_global_macro_from_news([
        "ECB expected to hike next week; BOJ may raise rates if inflation persists"])
    assert rows == []


# --- 2026-06-22: Quant Desk Read synthesis (#2 quant moat) -------------------
_TP_RISKON = {
    "stance": "Risk-on, pro-cyclical",
    "top_funds": [{"ticker": "EMEQ", "ret_1m": 21.4},
                  {"ticker": "BPTIX", "ret_1m": 16.3, "beta": 1.066},
                  {"ticker": "XNTK", "ret_1m": 13.4, "beta": 1.627}],
    "bottom_funds": [{"ticker": "XLG", "ret_1m": -2.6, "beta": 1.051},
                     {"ticker": "RLY", "ret_1m": -4.0, "beta": 0.2596}],
}
_MAG7_DEFENSIVE = {"AAPL": {"consensus": 1.49}, "TSLA": {"consensus": 0.19},
                   "AMZN": {"consensus": -3.76}, "MSFT": {"consensus": -1.0},
                   "GOOGL": {"consensus": -0.5}, "META": {"consensus": -1.2},
                   "NVDA": {"consensus": -2.0}}


def test_desk_read_riskon_tape_vs_defensive_models():
    out = gmc._build_quant_desk_read(_TP_RISKON, _MAG7_DEFENSIVE)
    assert "agree on risk-on" in out
    assert "β 1.35 vs laggards 0.66" in out
    assert "skew defensive" in out
    assert "AMZN weakest" in out
    assert "soft spot rather than its engine" in out


def test_desk_read_is_never_advice():
    # Compliance: interpretive only — no directive verbs.
    out = gmc._build_quant_desk_read(_TP_RISKON, _MAG7_DEFENSIVE).lower()
    for word in ("buy", "sell", " lean", "trim", "overweight", "underweight", "we recommend"):
        assert word not in out, f"desk read must not contain advice term {word!r}"


def test_desk_read_models_concur_riskon():
    mag7_bull = {"AAPL": {"consensus": 2.0}, "MSFT": {"consensus": 1.5},
                 "NVDA": {"consensus": 3.0}, "META": {"consensus": 0.8},
                 "AMZN": {"consensus": -0.5}}
    out = gmc._build_quant_desk_read(_TP_RISKON, mag7_bull)
    assert "models concur" in out and "risk-on" in out


def test_desk_read_empty_on_thin_inputs():
    assert gmc._build_quant_desk_read({"stance": "Risk-on"}, {}) == ""
    assert gmc._build_quant_desk_read({}, _MAG7_DEFENSIVE) == ""


# --- 2026-06-22: official central-bank decision RSS feed (#1 dedicated source) ---
class _FakeRSSResp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status


def test_cb_decision_title_regex_matches_decisions_not_speeches():
    R = gmc._CB_DECISION_TITLE_RE
    assert R.search("Monetary policy decisions")
    assert R.search("Statement on Monetary Policy")
    assert R.search("Interest Rate Announcement")
    assert R.search("Bank Rate maintained at 4.00%")
    assert not R.search("Christine Lagarde: Hearing of the Committee on Economic Affairs")
    assert not R.search("ECB publishes consolidated banking data")


def test_parse_rss_items_handles_rdf_dc_date():
    rdf = ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
           'xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<item rdf:about="http://x"><title>Interest Rate Announcement</title>'
           '<link>http://x</link><dc:date>2026-06-04T10:00:00-04:00</dc:date></item></rdf:RDF>')
    items = gmc._parse_rss_items(rdf)
    assert items and items[0]["title"] == "Interest Rate Announcement"
    assert items[0]["date"] is not None


def test_fetch_global_cb_decisions_filters_recency_minutes_and_dedupes(monkeypatch):
    from datetime import datetime, timezone
    now = datetime(2026, 6, 22, tzinfo=timezone.utc)
    rss = ('<?xml version="1.0"?><rss version="2.0"><channel>'
           '<item><title>Bank Rate maintained at 4.00% - June 2026</title><link>http://x/1</link>'
           '<pubDate>Thu, 18 Jun 2026 12:00:00 +0100</pubDate>'
           '<description>The MPC voted to maintain Bank Rate.</description></item>'
           '<item><title>Minutes of the Monetary Policy Committee meeting</title><link>http://x/2</link>'
           '<pubDate>Wed, 17 Jun 2026 09:00:00 +0100</pubDate></item>'
           '<item><title>Governor speech on financial stability</title><link>http://x/3</link>'
           '<pubDate>Thu, 18 Jun 2026 10:00:00 +0100</pubDate></item>'
           '<item><title>Bank Rate decision</title><link>http://x/4</link>'
           '<pubDate>Thu, 01 Jan 2026 12:00:00 +0000</pubDate></item>'
           '<item><title>Interest Rate Announcement</title><link>http://x/5</link>'
           '<pubDate>Wed, 09 Dec 2026 09:45:00 +0000</pubDate></item>'
           '</channel></rss>')
    monkeypatch.setattr(gmc, "_CB_RSS_FEEDS", (("BoE", "http://feed"),))
    monkeypatch.setattr(gmc.requests, "get", lambda *a, **k: _FakeRSSResp(rss))
    rows = gmc.fetch_global_cb_decisions(recency_days=5, now=now)
    assert len(rows) == 1     # minutes + speech + stale + FUTURE-dated all dropped
    assert rows[0]["institution"] == "BoE"
    assert "Bank Rate maintained" in rows[0]["headline"]
    assert rows[0]["date"] == "2026-06-18"
    assert rows[0]["url"] == "http://x/1"


def test_fetch_global_cb_decisions_dead_feed_is_safe(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(gmc, "_CB_RSS_FEEDS", (("ECB", "http://feed"),))
    monkeypatch.setattr(gmc.requests, "get", _boom)
    assert gmc.fetch_global_cb_decisions() == []


# ── 2026-06-24 eval fixes: guard-leak coverage extensions ──────────────────────

def test_risk_polarity_scans_asset_class_outlook_rationale():
    """#2 leak (6/24): a 'risk-on environment' assertion in the nested
    asset_class_outlooks[*].rationale evaded the polarity scan, which only covered flat
    commentary fields. The Long-Term Fundamental Outlook prose must be scanned too."""
    snap = {"S&P 500": {"pct_change": -1.44}}
    data = {"asset_class_outlooks": {
        "Commodities": {"label": "Bearish", "rationale":
            "Gold declined 1.89% as the safe-haven bid evaporated in a risk-on "
            "environment driven by higher-for-longer rate expectations."}}}
    viol = gmc._check_risk_polarity_inversion(data, snap)
    assert any("asset_class_outlooks[Commodities]" in v for v in viol)
    # Same wording on an UP day is coherent — must not flag.
    assert gmc._check_risk_polarity_inversion(data, {"S&P 500": {"pct_change": 1.2}}) == []


def test_fed_hike_singular_reframes_grammatically():
    """#3 regression (6/24): the bare plural 'higher-for-longer rates' orphaned a singular
    discrete-event 'rate hike' under a determiner into nonsense. Singular -> 'rate path'."""
    d = {"equities_commentary": "Every meeting is now live for a potential rate hike.",
         "economics_commentary": "Traders watch the next scheduled rate hike.",
         "currencies_commentary": "Markets priced multiple rate hikes this year."}
    gmc._correct_fed_hike_language(d)
    assert d["equities_commentary"] == "Every meeting is now live for a potential higher-for-longer rate path."
    assert d["economics_commentary"] == "Traders watch the next scheduled higher-for-longer rate path."
    assert "higher-for-longer rates" in d["currencies_commentary"]   # plural keeps plural
    # Idempotent: no residual "hike" to re-trigger.
    before = dict(d)
    gmc._correct_fed_hike_language(d)
    assert d == before


def test_harvest_rejects_official_named_in_editorial_headline():
    """#4 regression (6/24): "Fed's Warsh - ... History Says Don't" was harvested as a
    speaker because the editorial 'History Says' tripped the speak-token gate while Warsh
    was only NAMED. Require the surname to be the verb's subject."""
    warsh = ("Fed's Warsh - The Dollar Just Hit A 13-Month High On Warsh's "
             "Hawkish Debut: History Says Don't")
    assert gmc._harvest_fed_speakers_from_news([warsh]) == []
    # Genuine schedule/quote entries still harvest.
    assert any("Daly" in r["speaker"] for r in
               gmc._harvest_fed_speakers_from_news(["Fed's Daly says data shows inflation cooling"]))
    assert any("Barkin" in r["speaker"] for r in
               gmc._harvest_fed_speakers_from_news(["Richmond Fed President Barkin speaks at 8:30 a.m. ET"]))


def test_spotlight_evergreen_drift_flags_session_irrelevant_filler():
    """#1 family (6/24): an on-theme spotlight smuggled in evergreen tropes (the '4%
    retirement rule', household wealth-share stats). They must be flagged for a rewrite."""
    body = ("Technology led the decline. The potential failure of the 4% retirement rule "
            "looms if markets repeat 2000s-style collapses. The top 20% of Americans now "
            "account for nearly 60% of spending.")
    hits = gmc._spotlight_evergreen_drift(body)
    assert hits, "expected evergreen tropes to be flagged"
    # A genuinely session-grounded paragraph is clean.
    assert gmc._spotlight_evergreen_drift(
        "The XLK index fell 4.14% as memory and chip names led declines on AI-capex doubts.") == []


def test_tradingview_headlines_maps_wire_items_to_article_shape(monkeypatch):
    """#6 substance gap (6/24): the macro feed was a single retail content farm. The new
    TradingView wire must map its public-widget JSON into the exact article shape
    fetch_world_news emits (title/summary/source/published_at/url/category) and survive a
    network failure by returning []."""
    import io, json as _json, urllib.request as _ur

    payload = {"items": [
        {"id": "DJN_X:0", "title": "Asian Stocks Rise After Micron Earnings Ease AI Fears",
         "provider": "dow-jones", "source": "Dow Jones Newswires", "published": 1782359580,
         "relatedSymbols": [{"symbol": "NASDAQ:MU"}, {"symbol": "TVC:NI225"}],
         "storyPath": "/news/DJN_X:0/"},
        {"id": "RTR_Y:0", "title": "", "provider": "reuters", "published": 1782359399,
         "storyPath": "/news/RTR_Y:0/"},  # empty title must be dropped
        {"id": "TE_Z:0", "title": "Flash Composite PMI Beats at 52.2", "provider": "trading-economics",
         "published": 1782359340, "storyPath": "/news/TE_Z:0/"},
    ]}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return _json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(_ur, "urlopen", lambda *a, **k: _Resp())
    arts = gmc.fetch_tradingview_headlines(limit=40)

    assert len(arts) == 2, "empty-title item must be dropped"
    a = arts[0]
    assert sorted(a.keys()) == ["category", "published_at", "source", "summary", "title", "url"]
    assert a["title"].startswith("Asian Stocks Rise")
    assert a["source"] == "Dow Jones Newswires"
    assert a["url"] == "https://www.tradingview.com/news/DJN_X:0/"
    assert a["published_at"].startswith("2026-")          # unix ts -> ISO
    assert "MU" in a["summary"] and "NI225" in a["summary"]  # related-symbol hint
    # Trading-Economics carries the flash-PMI print EPM had been missing.
    assert any("PMI" in x["title"] and x["source"] == "Trading Economics" for x in arts)

    # Network failure must fail soft (no exception, empty list).
    def _boom(*a, **k): raise OSError("network down")
    monkeypatch.setattr(_ur, "urlopen", _boom)
    assert gmc.fetch_tradingview_headlines() == []
