"""Tests for the always-on geopolitical grounding pass in generate_market_commentary.

2026-07-02 regression: the rates/FX/gold sections invoked a US-Iran storyline with the WRONG
direction ("fading hopes for a peace deal fuelled inflation") because they grounded on STALE
corpus headlines ("Iran war caution") — no fresh Iran source was consulted. build_geopolitical_context
now fetches a FRESH read and pins the direction, or returns a signal that tells the narrative to
DROP geopolitical causation when the fresh read is ambiguous.
"""
import generate_market_commentary as gmc


# --- direction classifier (deterministic) -------------------------------------
def test_clean_easing_classified_easing():
    hl = [{"title": "US and Iran resume ceasefire talks as Hormuz shipping reopens"},
          {"title": "Iran peace negotiations progress; tensions ease, oil slips"},
          {"title": "Diplomats report de-escalation in Persian Gulf standoff"}]
    assert gmc._classify_geo_direction(hl)["direction"] == "easing"


def test_clean_escalating_classified_escalating():
    hl = [{"title": "Iran strikes tanker near Hormuz; US warns of retaliation"},
          {"title": "Missile attack escalates conflict as talks collapse"},
          {"title": "Iran threatens to blockade strait, seizes vessel"}]
    assert gmc._classify_geo_direction(hl)["direction"] == "escalating"


def test_contested_news_is_unclear():
    # Both sides substantial (the real 2026-07-02 picture: "Iran war" beside "talks progress").
    # A contested read must resolve to 'unclear' so the narrative drops geo causation.
    hl = [{"title": "Iran war live: decisive response vows Tehran"},
          {"title": "Talks pause for funeral after mediators claim progress"},
          {"title": "Iran war ignites clash between Trump and Riyadh"},
          {"title": "Tehran warns not to attack during funeral"},
          {"title": "US dangles rewards to open Hormuz, Iran isn't budging"},
          {"title": "US tries to talk Iran out of tolls as talks resume in Doha"}]
    assert gmc._classify_geo_direction(hl)["direction"] == "unclear"


def test_empty_headlines_unclear():
    assert gmc._classify_geo_direction([])["direction"] == "unclear"


# --- the gate + orchestrator --------------------------------------------------
def test_gate_skips_fetch_when_no_geo_in_corpus():
    # No Iran/Middle-East mention in the day's corpus → return None WITHOUT fetching.
    called = {"n": 0}

    def _fetch():
        called["n"] += 1
        return [{"title": "Iran ceasefire holds"}]

    out = gmc.build_geopolitical_context(["Apple earnings beat", "Fed holds rates steady"], fetch_fn=_fetch)
    assert out is None
    assert called["n"] == 0  # never fetched on a quiet day


def test_gate_fires_and_grounds_easing():
    feed = [{"title": "US-Iran ceasefire talks progress; Hormuz reopens, tensions ease"},
            {"title": "Diplomats report de-escalation as peace negotiations advance"},
            {"title": "Oil slips as Iran truce holds and shipping resumes"}]
    out = gmc.build_geopolitical_context(["Oil dips on US-Iran tensions"], fetch_fn=lambda: feed)
    assert out is not None
    assert out["direction"] == "easing"
    assert "MUST match this direction" in out["instruction"]
    assert out["basis"]


def test_gate_returns_none_on_empty_feed():
    # Storyline in corpus but the fresh fetch yields nothing → None (no grounded driver).
    assert gmc.build_geopolitical_context(["Iran tensions weigh on oil"], fetch_fn=lambda: []) is None


def test_gate_unclear_instructs_drop_causation():
    contested = [{"title": "Iran war live: Tehran warns of forceful response"},
                 {"title": "Talks resume in Doha as mediators claim progress"},
                 {"title": "Iran war escalates; US strikes reported"},
                 {"title": "Iran isn't budging on Hormuz tolls despite ceasefire push"}]
    out = gmc.build_geopolitical_context(["US-Iran war caution hits currencies"], fetch_fn=lambda: contested)
    assert out is not None
    assert out["direction"] == "unclear"
    assert "Do NOT attribute" in out["instruction"]


# --- trigger regex ------------------------------------------------------------
def test_trigger_matches_geopolitics_and_ignores_unrelated():
    assert gmc._GEO_TRIGGER_RE.search("Oil rises on Strait of Hormuz risk")
    assert gmc._GEO_TRIGGER_RE.search("Tehran and Israel exchange strikes")
    assert gmc._GEO_TRIGGER_RE.search("US-Iran ceasefire in doubt")
    assert not gmc._GEO_TRIGGER_RE.search("Nvidia earnings beat lifts semis")


def test_build_context_none_never_raises_on_fetch_error():
    def _boom():
        raise RuntimeError("network down")
    # Fetch errors must fail soft to None, never propagate into the pipeline.
    assert gmc.build_geopolitical_context(["Iran tensions"], fetch_fn=_boom) is None
