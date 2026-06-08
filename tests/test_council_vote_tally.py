"""Regression tests for council Round-3 vote tallying.

Guards the bug where an advocate persona that emits its verdict in markdown
bold ("**FINAL STANCE:** bull") had its vote silently dropped, because the
counter regex used a plain \\s* that could not cross the asterisks. The
result was a tally like 6-bearish/1-base/0-bullish even though the debate
map clearly showed the Bull Analyst holding a bullish final stance.
"""

import local_council


def _take(text):
    return {"take": text}


def test_plain_final_stance_counted():
    takes = [_take("FINAL STANCE: bear"), _take("FINAL STANCE: base")]
    votes = local_council._count_final_votes(takes)
    assert votes == {"bearish": 1, "base": 1, "bullish": 0}


def test_markdown_wrapped_stance_counted():
    # The exact shape an advocate persona emitted in the live AAPL run.
    takes = [_take("**FINAL STANCE:** bull")]
    votes = local_council._count_final_votes(takes)
    assert votes["bullish"] == 1


def test_mixed_roster_tally_includes_advocate_vote():
    takes = [
        _take("FINAL STANCE: bear"),
        _take("FINAL STANCE: bear"),
        _take("FINAL STANCE: bear"),
        _take("FINAL STANCE: bear"),
        _take("FINAL STANCE: bear"),
        _take("**FINAL STANCE:** bull"),  # Bull Analyst, markdown-bold
        _take("FINAL STANCE: bear"),
        _take("FINAL STANCE: base"),
    ]
    votes = local_council._count_final_votes(takes)
    # 6 bearish / 1 base / 1 bullish — the bull vote must NOT be dropped.
    assert votes == {"bearish": 6, "base": 1, "bullish": 1}


def test_stance_variants_and_punctuation():
    takes = [
        _take("Final Stance:   bearish"),
        _take("**FINAL STANCE**: bullish"),
        _take("FINAL STANCE:base"),
    ]
    votes = local_council._count_final_votes(takes)
    assert votes == {"bearish": 1, "base": 1, "bullish": 1}


def test_missing_stance_ignored():
    takes = [_take("no verdict here"), _take("FINAL STANCE: bull")]
    votes = local_council._count_final_votes(takes)
    assert votes == {"bearish": 0, "base": 0, "bullish": 1}
