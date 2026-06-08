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
