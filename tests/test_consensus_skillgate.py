"""Skill-gated consensus: anti-correlated models are floored (not removed), DL is included,
and the consensus / winner come from the same walk-forward leaderboard the page shows.
"""
import numpy as np
import pandas as pd
import pytest

mr = pytest.importorskip("model_ranking")


def _empty_rankings():
    return pd.DataFrame(columns=["Ticker", "Observations", "RMSE", "Composite_Score", "Model",
                                 "MAE", "Directional_Accuracy", "Correlation", "Rank"])


# --- the directional-skill gate ------------------------------------------------

def test_anticorrelated_model_is_unskilled():
    assert mr._is_unskilled({"corr": -0.49, "dir": 0.40, "n": 60})


def test_sub_coinflip_direction_is_unskilled():
    assert mr._is_unskilled({"corr": 0.20, "dir": 0.30, "n": 60})


def test_skilled_model_is_not_gated():
    assert not mr._is_unskilled({"corr": 0.67, "dir": 0.76, "n": 62})


def test_small_sample_is_neutral_not_punished():
    # No edge on paper, but too few obs to trust — must NOT be floored.
    assert not mr._is_unskilled({"corr": -0.9, "dir": 0.1, "n": 3})


# --- consensus weighting -------------------------------------------------------

def _current(rows):
    return pd.DataFrame([{"Date": "2026-06-29", "Ticker": t, "Model": m, "Forecast_Return": f}
                         for t, m, f in rows])


def test_anticorrelated_model_is_floored_not_removed():
    current = _current([("AAPL", "DeepLearning", 0.05), ("AAPL", "Linear", -0.10)])
    skill = {
        ("AAPL", "DeepLearning"): {"rmse": 5.0, "corr": 0.6, "dir": 0.7, "n": 60, "rank": 1},
        ("AAPL", "Linear"):       {"rmse": 5.0, "corr": -0.5, "dir": 0.3, "n": 60, "rank": 2},
    }
    out = mr.build_consensus(current, _empty_rankings(), skill).set_index("Ticker")
    simple = (0.05 - 0.10) / 2
    # Both models still counted (none removed), but the skilled one dominates → above simple avg.
    assert out.loc["AAPL", "Model_Count"] == 2
    assert out.loc["AAPL", "Consensus_Forecast"] > simple
    assert out.loc["AAPL", "Consensus_Forecast"] > 0          # pulled toward the skilled +5% call
    assert out.loc["AAPL", "Top_Model"] == "DeepLearning"     # leaderboard rank-1
    assert out.loc["AAPL", "Consensus_Method"] == "SkillGatedInverseRMSE"


def test_dl_is_included_in_consensus():
    current = _current([("AAPL", "DeepLearning", 0.03), ("AAPL", "Institutional", 0.02)])
    skill = {
        ("AAPL", "DeepLearning"):  {"rmse": 6.0, "corr": 0.5, "dir": 0.7, "n": 60, "rank": 1},
        ("AAPL", "Institutional"): {"rmse": 7.0, "corr": 0.4, "dir": 0.6, "n": 60, "rank": 2},
    }
    out = mr.build_consensus(current, _empty_rankings(), skill).set_index("Ticker")
    assert out.loc["AAPL", "Model_Count"] == 2
    assert "DeepLearning" in mr.CURRENT_FORECAST_FILES   # DL is a registered consensus contributor


def test_pick_winners_uses_leaderboard_rank1():
    current = _current([("AAPL", "DeepLearning", 0.03), ("AAPL", "Linear", -0.05)])
    skill = {
        ("AAPL", "DeepLearning"): {"rmse": 5.0, "corr": 0.6, "dir": 0.7, "mae": 5.9, "n": 60, "rank": 1},
        ("AAPL", "Linear"):       {"rmse": 9.0, "corr": -0.5, "dir": 0.3, "mae": 9.4, "n": 60, "rank": 2},
    }
    winners = mr.pick_winners(_empty_rankings(), current, skill).set_index("Ticker")
    assert winners.loc["AAPL", "Winning_Model"] == "DeepLearning"
