"""Tests for the 4-round adversarial debate engine.

Covers the two structural fixes:
  - assigned cross-examination so the bull AND bear poles are always rebutted
    (no advocate goes "unchallenged"), and
  - the 4-round structure with the vote tallied from the final round.
"""

import local_council as lc


def _r1(name, stance):
    return {
        "name": name,
        "title": name.replace("_", " ").title(),
        "take": f"STANCE: {stance}\nCLAIM: c\nEVIDENCE: e\nMECHANISM: m\nWHAT WOULD CHANGE MY MIND: w",
    }


def test_parse_stance():
    assert lc._parse_stance("STANCE: bullish\n...") == "bull"
    assert lc._parse_stance("STANCE: bearish") == "bear"
    assert lc._parse_stance("STANCE: base") == "base"
    assert lc._parse_stance("no stance line") == "base"


def test_assign_challenges_covers_both_poles():
    # Default roster shape: 1 bull + 1 bear + neutrals.
    personas = list(lc.PERSONAS)
    takes = []
    for p in personas:
        s = "bullish" if p.kind == "bull" else "bearish" if p.kind == "bear" else "base"
        takes.append(_r1(p.name, s))
    assignments = lc._assign_challenges(takes, personas)
    targets = [t["name"] for t in assignments.values()]
    # The bull advocate and bear advocate must each be cross-examined by someone.
    assert "bull_analyst" in targets, "bull pole went unchallenged"
    assert "bear_analyst" in targets, "bear pole went unchallenged"
    # Nobody challenges themselves.
    for challenger, target in assignments.items():
        assert challenger != target["name"]
    # Full coverage: EVERY member receives at least one incoming challenge.
    from collections import Counter
    indeg = Counter(t["name"] for t in assignments.values())
    for p in personas:
        assert indeg.get(p.name, 0) >= 1, f"{p.name} left unchallenged"


def test_assign_challenges_pole_from_stance_when_no_advocate():
    # Degenerate roster with no bull/bear kind — poles fall back to stance.
    personas = [p for p in lc.PERSONAS if p.kind == "neutral"][:4]
    takes = [
        _r1(personas[0].name, "bullish"),
        _r1(personas[1].name, "bearish"),
        _r1(personas[2].name, "base"),
        _r1(personas[3].name, "base"),
    ]
    assignments = lc._assign_challenges(takes, personas)
    targets = [t["name"] for t in assignments.values()]
    assert personas[0].name in targets  # the lone bull-stance take
    assert personas[1].name in targets  # the lone bear-stance take


def test_challengers_of():
    personas = list(lc.PERSONAS)
    takes_r1 = [_r1(p.name, "bullish" if p.kind == "bull" else "bearish" if p.kind == "bear" else "base") for p in personas]
    assignments = lc._assign_challenges(takes_r1, personas)
    takes_r2 = [{"name": p.name, "title": p.title, "take": "STANCE: base"} for p in personas]
    challengers = lc._challengers_of("bull_analyst", assignments, takes_r2)
    # At least one analyst challenged the bull pole, and we can resolve their R2 take.
    assert len(challengers) >= 1
    assert all("name" in c for c in challengers)


def test_clean_memo_strips_keyfacts_and_fills_placeholders():
    kf = {"current_price": 307.34, "trailing_pe": 35.9, "forward_pe": 38.5,
          "rel_perf_1m_diff_pct": -0.8, "mna_note": "acquired AI-focused firms",
          "volatility_regime": "ELEVATED"}
    # (KEY_FACTS: field) citation removed (value precedes it).
    assert lc._clean_memo("trades at $307.34 (KEY_FACTS: current_price).", kf) == "trades at $307.34."
    # Unfilled [field] placeholders substituted from KEY_FACTS.
    out = lc._clean_memo("P/E of [trailing_pe] and [forward_pe].", kf)
    assert "35.9" in out and "38.5" in out and "[" not in out
    # Negative pct placeholder filled.
    assert lc._clean_memo("differential of [rel_perf_1m_diff_pct]%.", kf) == "differential of -0.8%."
    # Parenthesized bracket citation removed entirely.
    assert lc._clean_memo("firms ([mna_note]) position it.", kf) == "firms position it."
    # Bare (KEY_FACTS) tag removed.
    assert lc._clean_memo("risk (KEY_FACTS: volatility_regime) rises.", kf) == "risk rises."
    # Legit parenthetical (not a field token) preserved.
    assert "(14-day)" in lc._clean_memo("RSI (14-day) at 58.3 (rsi_14).", kf)


def test_clean_memo_field_in_paren_with_prose():
    kf = {"ma50": 282.32, "kronos_base_target": 385, "mna_note": "acquiring six AI firms",
          "legal_regulatory_note": "privacy lawsuits", "eps_release_surprise_pct": 3.61,
          "mom_5d_pct": 2.68, "beta": 1.2}
    # No-underscore field token "(ma50)" removed.
    assert lc._clean_memo("MA ($282.32 (ma50) level).", kf) == "MA ($282.32 level)."
    # Field token embedded with prose: strip the token (+ dangling connector), keep the prose.
    assert lc._clean_memo("target $385 (kronos_base_target, implying 25% upside).", kf) \
        == "target $385 (25% upside)."
    assert lc._clean_memo("shifts (legal_regulatory_note mentions privacy lawsuits) hurt.", kf) \
        == "shifts (privacy lawsuits) hurt."
    # "(value field)" keeps the value.
    assert lc._clean_memo("beat (3.61% eps_release_surprise_pct) seen.", kf) == "beat (3.61%) seen."
    # Legit parens preserved through the field-aware pass.
    for legit in ["(14-day)", "(QQQ)", "($316.94)", "(June)", "(ELEVATED — top third)"]:
        assert legit in lc._clean_memo(f"text {legit} more.", kf), legit


def _stub_ollama(prompt, timeout=600, mode=None):
    if "Write your final" in prompt:
        # Bull advocate keeps a bullish final vote (markdown-bold to exercise tally);
        # everyone else votes bear.
        if "You are the bull analyst" in prompt:
            return "**FINAL STANCE:** bull\nRATIONALE: x\nPOSITION SHIFTED: no\nWHY: y"
        return "FINAL STANCE: bear\nRATIONALE: x\nPOSITION SHIFTED: no\nWHY: y"
    if "Respond ONLY with valid JSON" in prompt:
        return "{}"
    if mode == "synthesis":
        return "Our required recommendation is UNDERWEIGHT."
    if "This is Round 1" in prompt:
        if "You are the bull analyst" in prompt:
            return "STANCE: bullish\nCLAIM: up\nEVIDENCE: e\nMECHANISM: m\nWHAT WOULD CHANGE MY MIND: w"
        if "You are the bear analyst" in prompt:
            return "STANCE: bearish\nCLAIM: dn\nEVIDENCE: e\nMECHANISM: m\nWHAT WOULD CHANGE MY MIND: w"
        return "STANCE: base\nCLAIM: c\nEVIDENCE: e\nMECHANISM: m\nWHAT WOULD CHANGE MY MIND: w"
    return "STANCE: base\nCLAIM: c\nEVIDENCE: e\nMECHANISM: m\nDISAGREEMENT: d\nWHAT WOULD CHANGE MY MIND: w"


def test_run_council_produces_four_rounds_and_counts_final_vote(monkeypatch):
    monkeypatch.setattr(lc, "_call_ollama", _stub_ollama)
    res = lc.run_council("AAPL", "", {"ticker": "AAPL", "current_price": 200.0})
    tbr = res["takes_by_round"]
    assert sorted(tbr.keys()) == [1, 2, 3, 4]
    # 8 personas each appear in every round.
    assert all(len(tbr[r]) == len(lc.PERSONAS) for r in (1, 2, 3, 4))
    # Round 4 is the vote round; the bull's markdown-bold vote is counted.
    votes = lc._count_final_votes(tbr[4])
    assert votes["bullish"] == 1
    assert votes["bearish"] == len(lc.PERSONAS) - 1
    assert "**Round 4**" in res["raw_markdown"]
