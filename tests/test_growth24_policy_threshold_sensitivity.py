import argparse

import pandas as pd

import dl_growth24_shadow_policy_replay as shadow_policy_replay
from dl_growth24_policy_threshold_sensitivity import build_report


def _row(asof, ticker, rank, score, forecast, realized):
    return {
        "AsOfDate": asof,
        "Cycle": asof,
        "Ticker": ticker,
        "Rank": rank,
        "ShadowRankScore": score,
        "RawForecastPct": forecast,
        "RealizedForwardReturn": realized,
    }


def _args(tmp_path):
    return argparse.Namespace(
        shadow_log=tmp_path / "shadow_log.parquet",
        long_n=1,
        short_n=1,
        expected_universe_count=3,
        max_universe_score_stds="0.05,0.20",
        max_forecast_gaps="4.0",
        max_consecutive="0",
        score_start_dates="2026-03-01,2026-04-01",
        start_date=None,
        end_date=None,
        score_end_date=None,
        min_holdout_allowed_cycles=1,
        min_holdout_filter_uplift=0.001,
        gate_min_hit=0.50,
        gate_max_drawdown=-0.25,
    )


def _shadow_log_rows():
    rows = []
    cycles = [
        ("2026-01-01", "good"),
        ("2026-02-01", "good"),
        ("2026-03-01", "good"),
        ("2026-04-01", "bad_high_dispersion"),
        ("2026-05-01", "good"),
    ]
    for asof, kind in cycles:
        if kind == "good":
            scores = (0.03, 0.02, -0.02)
            aaa_return = 0.08
            ccc_return = -0.02
        else:
            scores = (0.20, 0.00, -0.20)
            aaa_return = -0.10
            ccc_return = 0.03
        rows.extend(
            [
                _row(asof, "AAA", 1, scores[0], 1.0, aaa_return),
                _row(asof, "BBB", 2, scores[1], 0.5, 0.01),
                _row(asof, "CCC", 3, scores[2], -1.0, ccc_return),
            ]
        )
    frame = pd.DataFrame(rows)
    frame["AsOfDate"] = pd.to_datetime(frame["AsOfDate"])
    return frame


def test_threshold_sensitivity_prefers_robust_strict_dispersion_gate(tmp_path, monkeypatch):
    args = _args(tmp_path)
    rows = _shadow_log_rows()
    monkeypatch.setattr(shadow_policy_replay, "_load_shadow_log", lambda _: rows.copy())

    report, rows = build_report(args)

    assert report["status"] == "pass"
    assert report["passing_config_count"] == 1
    assert report["best_config"]["config"]["max_universe_score_std"] == 0.05
    assert report["best_config"]["robust_gate"]["status"] == "pass"
    assert report["best_config"]["aggregate"]["min_holdout_filter_uplift"] > 0.0
    assert rows.iloc[0]["max_universe_score_std"] == 0.05
    assert rows.iloc[0]["status"] == "pass"
    assert rows.iloc[1]["status"] == "fail"


def test_threshold_sensitivity_requires_holdout_windows(tmp_path, monkeypatch):
    args = _args(tmp_path)
    args.score_start_dates = "none"
    shadow_rows = _shadow_log_rows()
    monkeypatch.setattr(shadow_policy_replay, "_load_shadow_log", lambda _: shadow_rows.copy())

    report, rows = build_report(args)

    assert report["status"] == "fail"
    assert report["passing_config_count"] == 0
    assert rows["status"].tolist() == ["fail", "fail"]
    assert "no holdout score-start dates configured" in rows.iloc[0]["failures"]
