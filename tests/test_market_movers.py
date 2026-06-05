import market_movers as mm


def _corpus(*texts):
    return [{"text": t, "source": "s", "url": ""} for t in texts]


# --- Task 1: _headline_share -------------------------------------------------
def test_headline_share_counts_matching_fraction():
    corpus = _corpus(
        "Broadcom plunges 13% on soft guidance",
        "AVGO drags chip sector lower",
        "Gold eases as dollar firms",
        "Treasury yields tick higher",
    )
    assert mm._headline_share(["broadcom", "avgo"], corpus) == 0.5
    assert mm._headline_share(["nonexistent"], corpus) == 0.0
    assert mm._headline_share([], corpus) == 0.0
    assert mm._headline_share(["avgo"], []) == 0.0


# --- Task 2: portfolio tickers + tie-in resolution ---------------------------
def test_portfolio_tickers_from_payload():
    payload = {"tactical_positioning": {
        "top_funds": [{"ticker": "xntk"}, {"ticker": "VSMIX"}],
        "bottom_funds": [{"ticker": "LVHI"}],
    }}
    assert mm._portfolio_tickers(payload) == {"XNTK", "VSMIX", "LVHI"}
    assert mm._portfolio_tickers({}) == set()


def test_resolve_tie_in_tickers_sector_etf_then_peers_no_holdings():
    ties = mm._resolve_tie_in_tickers("AVGO", sector="Technology", peers=["NVDA", "AMD", "AVGO"])
    assert ties[0] == "XLK"                 # sector ETF first
    assert ties[1:] == ["NVDA", "AMD"]      # peers next; the mover itself is excluded
    assert len(ties) == len(set(ties))      # deduped
    # unknown sector -> peers only
    assert mm._resolve_tie_in_tickers("ZZZZ", sector="", peers=["AAA"]) == ["AAA"]


# --- Task 3: _session_candidates ---------------------------------------------
def test_session_candidates_normalizes_feed_rows():
    movers = {
        "gainers": [{"ticker": "NVDA", "name": "NVIDIA", "day_change_pct": 0.06, "sector": "Technology"}],
        "losers":  [{"ticker": "AVGO", "name": "Broadcom", "day_change_pct": -0.13, "sector": "Technology"}],
    }
    corpus = _corpus("Broadcom plunges 13% on guidance", "AVGO drags chips", "NVIDIA steady")
    cands = mm._session_candidates(movers, corpus, payload={"tactical_positioning": {}})
    avgo = next(c for c in cands if c["mover_ticker"] == "AVGO")
    assert avgo["kind"] == "mover"
    assert avgo["mover_pct"] == -0.13 and avgo["mover_when"] == "session"
    assert abs(avgo["magnitude"] - 0.13) < 1e-9
    assert avgo["headline_share"] > 0
    assert "XLK" in avgo["candidate_funds"]
    small = {"gainers": [{"ticker": "KO", "name": "Coca-Cola", "day_change_pct": 0.01}], "losers": []}
    assert mm._session_candidates(small, corpus, {}) == []


# --- Task 4: _premarket_candidate --------------------------------------------
def test_premarket_candidate_verifies_pct_via_quote():
    scan = {"ticker": "AVGO", "company": "Broadcom", "pct": -0.10,
            "catalyst": "soft AI guidance", "sector": "Technology"}
    corpus = _corpus("Broadcom plunges 13% premarket", "AVGO guidance disappoints")
    cand = mm._premarket_candidate(scan, quote_fn=lambda t: {"day_change_pct": -0.13}, corpus=corpus, payload={})
    assert cand["mover_ticker"] == "AVGO" and cand["mover_when"] == "premarket"
    assert cand["mover_pct"] == -0.13
    assert "soft AI guidance" in cand["topic"]


def test_premarket_candidate_corroboration_gate_when_quote_missing():
    scan = {"ticker": "ZZZZ", "company": "Zeta", "pct": -0.09, "catalyst": "lawsuit", "sector": ""}
    assert mm._premarket_candidate(scan, quote_fn=lambda t: {}, corpus=_corpus("Zeta sued"), payload={}) is None
    corpus = _corpus("Zeta ZZZZ tumbles on lawsuit", "Zeta shares slide after suit")
    cand = mm._premarket_candidate(scan, quote_fn=lambda t: {}, corpus=corpus, payload={})
    assert cand is not None and abs(cand["mover_pct"] + 0.09) < 1e-9


def test_premarket_candidate_none_when_no_ticker():
    assert mm._premarket_candidate(None, quote_fn=lambda t: {}, corpus=[], payload={}) is None
    assert mm._premarket_candidate({"ticker": ""}, quote_fn=lambda t: {}, corpus=[], payload={}) is None


# --- Task 5: detect_market_mover ---------------------------------------------
def test_detect_market_mover_prefers_higher_prelim_score():
    movers = {"gainers": [], "losers": [
        {"ticker": "AVGO", "name": "Broadcom", "day_change_pct": -0.13, "sector": "Technology"},
        {"ticker": "XYZ",  "name": "Xyz Corp", "day_change_pct": -0.05, "sector": "Energy"},
    ]}
    corpus = _corpus("Broadcom plunges 13% premarket", "AVGO drags chip sector", "Xyz dips")
    got = mm.detect_market_mover(
        corpus, enrich_co_news=[], payload={},
        movers_fn=lambda: movers, quote_fn=lambda t: {}, scan_fn=lambda: None,
    )
    assert got["mover_ticker"] == "AVGO"


def test_detect_market_mover_none_when_nothing_qualifies():
    got = mm.detect_market_mover(
        _corpus("quiet day"), enrich_co_news=[], payload={},
        movers_fn=lambda: {"gainers": [], "losers": []},
        quote_fn=lambda t: {}, scan_fn=lambda: None,
    )
    assert got is None


# --- Task 6: theme_candidate + select_spotlight_candidate --------------------
def test_select_spotlight_candidate_prevalence_gate():
    corpus = _corpus(*(["AI capex theme"] * 3 + ["Broadcom plunges 13%"] * 2 + ["misc"] * 5))
    theme = mm.theme_candidate(
        topic="AI capex", topic_keywords=["ai capex"], why_now="w", category="theme",
        candidate_funds=["SMH"], matching=[1, 1, 1], corpus=corpus, payload={},
    )
    mover = mm._mover_candidate("AVGO", "Broadcom", -0.13, "premarket", "Technology", "guidance",
                                corpus, payload={})
    win = mm.select_spotlight_candidate([mover, theme])
    assert win["kind"] == "mover"

    weak = mm._mover_candidate("XYZ", "Xyz", -0.05, "session", "Energy", "", corpus, payload={})
    assert mm.select_spotlight_candidate([weak, theme])["kind"] == "theme"


def test_select_spotlight_candidate_floor_returns_none():
    corpus = _corpus("nothing relevant here", "still nothing")
    weak = mm._mover_candidate("XYZ", "Xyz", -0.04, "session", "", "", corpus, payload={})
    assert mm.select_spotlight_candidate([weak]) is None


def test_select_spotlight_candidate_portfolio_boost_breaks_tie():
    corpus = _corpus("AVGO moves", "NVDA moves", "filler", "filler")
    held = mm._mover_candidate("AVGO", "Broadcom", -0.05, "session", "Technology", "",
                               corpus, payload={"tactical_positioning": {"top_funds": [{"ticker": "AVGO"}]}})
    notheld = mm._mover_candidate("NVDA", "NVIDIA", -0.05, "session", "Technology", "", corpus, payload={})
    assert mm.select_spotlight_candidate([notheld, held])["mover_ticker"] == "AVGO"


# --- Task 7: build_spotlight_teaser ------------------------------------------
def test_build_spotlight_teaser_mover():
    win = {"kind": "mover", "mover_ticker": "AVGO", "mover_pct": -0.13, "mover_when": "premarket",
           "mover_catalyst": "soft AI guidance", "candidate_funds": ["SMH", "XLK", "NVDA"], "topic": "x"}
    t = mm.build_spotlight_teaser(win)
    assert "AVGO" in t and "-13.0%" in t and "premarket" in t
    assert "soft AI guidance" in t and "SMH" in t and "XLK" in t


def test_build_spotlight_teaser_theme_and_empty():
    assert mm.build_spotlight_teaser({"kind": "theme", "topic": "AI capex cycle"}).endswith("AI capex cycle")
    assert mm.build_spotlight_teaser(None) == ""
    assert mm.build_spotlight_teaser({"kind": "mover", "mover_ticker": "", "topic": ""}) == ""


# --- #3: blockbuster override + sector empty-funds floor (regression 2026-06-05) --
def test_blockbuster_mover_beats_dominant_theme():
    # Theme dominates headline share (in most of the corpus); a 15% single-name move
    # must still take the slot via the blockbuster override.
    corpus = _corpus(*(["Israel-Lebanon ceasefire as gulf tensions ease"] * 16
                       + ["Broadcom AVGO plunges on guidance"] * 2 + ["misc"] * 22))
    theme = mm.theme_candidate(
        topic="Israel-Lebanon Ceasefire", topic_keywords=["ceasefire"], why_now="w",
        category="theme", candidate_funds=["GLD"], matching=[1] * 16, corpus=corpus, payload={},
    )
    mover = mm._mover_candidate("AVGO", "Broadcom", -0.15, "premarket", "Technology",
                                "guidance", corpus, payload={})
    assert theme["headline_share"] > mover["headline_share"]      # theme is more prevalent
    win = mm.select_spotlight_candidate([theme, mover])
    assert win["kind"] == "mover" and win["mover_ticker"] == "AVGO"


def test_blockbuster_picks_largest_move():
    corpus = _corpus("AVGO plunges", "NVDA slides", "filler")
    avgo = mm._mover_candidate("AVGO", "Broadcom", -0.15, "premarket", "Technology", "", corpus, {})
    nvda = mm._mover_candidate("NVDA", "NVIDIA", 0.11, "session", "Technology", "", corpus, {})
    assert mm.select_spotlight_candidate([nvda, avgo])["mover_ticker"] == "AVGO"


def test_sub_blockbuster_mover_does_not_override_theme():
    # A 6% mover is below the 10% threshold → no override; a strong theme can still win.
    corpus = _corpus(*(["AI capex supercycle"] * 20 + ["small mover"] * 1 + ["x"] * 9))
    theme = mm.theme_candidate(
        topic="AI capex", topic_keywords=["ai capex"], why_now="w", category="theme",
        candidate_funds=["SMH"], matching=[1] * 20, corpus=corpus, payload={},
    )
    mover = mm._mover_candidate("XYZ", "Xyz", -0.06, "session", "Energy", "", corpus, {})
    assert mm.select_spotlight_candidate([mover, theme])["kind"] == "theme"


def test_sector_candidate_floors_empty_funds_with_sector_etf():
    corpus = _corpus("tech sells off", "filler")
    sec = mm.theme_candidate(
        topic="Technology Sector Sell-Off", topic_keywords=["technology"], why_now="w",
        category="sector_catalyst", candidate_funds=[], matching=[1], corpus=corpus, payload={},
    )
    assert sec["candidate_funds"] == ["XLK"]
