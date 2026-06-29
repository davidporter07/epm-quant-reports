"""Conformal calibration of the DL prediction interval.

The point forecast (mu) is never touched — these tests only assert that the band
multiplier is computed and loaded correctly, with a safe fallback to z=1.96 so a
missing/corrupt calibration file can never break inference (or remove the model).
"""
import json

import numpy as np
import pytest

dl = pytest.importorskip("deep_learning_model")


# --- finite-sample split-conformal quantile -----------------------------------

def test_multiplier_is_the_finite_sample_quantile():
    # 100 scores 1..100; for level 0.95 the rank is ceil(101*0.95)=96 -> 96th value.
    scores = np.arange(1, 101, dtype=float)
    q = dl._conformal_multiplier(scores, 0.95)
    assert q == 96.0


def test_multiplier_grows_with_coverage_level():
    rng = np.random.default_rng(0)
    scores = np.abs(rng.normal(size=5000))
    q80 = dl._conformal_multiplier(scores, 0.80)
    q90 = dl._conformal_multiplier(scores, 0.90)
    q95 = dl._conformal_multiplier(scores, 0.95)
    assert q80 < q90 < q95


def test_empirical_coverage_matches_target():
    rng = np.random.default_rng(1)
    scores = np.abs(rng.normal(size=10000))
    q95 = dl._conformal_multiplier(scores, 0.95)
    cov = float(np.mean(scores <= q95))
    assert abs(cov - 0.95) < 0.02


def test_too_few_points_returns_nan_for_fallback():
    # rank = ceil((n+1)*0.95); with n=5 -> ceil(5.7)=6 > 5 -> NaN (can't certify 95%).
    scores = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
    assert np.isnan(dl._conformal_multiplier(scores, 0.95))


def test_empty_scores_returns_nan():
    assert np.isnan(dl._conformal_multiplier(np.array([]), 0.95))


# --- loader + fallback --------------------------------------------------------

def test_loader_returns_conformal_value(tmp_path):
    path = tmp_path / "dl_conformal.json"
    path.write_text(json.dumps({"multipliers": {"0.95": 4.31, "0.80": 2.72}}))
    q, source = dl._load_conformal_multiplier(path, level=0.95)
    assert q == 4.31
    assert source == "conformal"


def test_loader_falls_back_when_file_missing(tmp_path):
    q, source = dl._load_conformal_multiplier(tmp_path / "nope.json", level=0.95)
    assert q == dl._CONFORMAL_FALLBACK_Z
    assert source == "fallback_z"


def test_loader_falls_back_on_corrupt_file(tmp_path):
    path = tmp_path / "dl_conformal.json"
    path.write_text("{ not valid json")
    q, source = dl._load_conformal_multiplier(path, level=0.95)
    assert q == dl._CONFORMAL_FALLBACK_Z
    assert source == "fallback_z"


def test_loader_falls_back_when_level_missing(tmp_path):
    path = tmp_path / "dl_conformal.json"
    path.write_text(json.dumps({"multipliers": {"0.80": 2.72}}))  # no 0.95
    q, source = dl._load_conformal_multiplier(path, level=0.95)
    assert q == dl._CONFORMAL_FALLBACK_Z
    assert source == "fallback_z"


def test_loader_ignores_null_multiplier(tmp_path):
    # An uncertifiable level is stored as null — must fall back, not crash.
    path = tmp_path / "dl_conformal.json"
    path.write_text(json.dumps({"multipliers": {"0.95": None}}))
    q, source = dl._load_conformal_multiplier(path, level=0.95)
    assert q == dl._CONFORMAL_FALLBACK_Z
    assert source == "fallback_z"
