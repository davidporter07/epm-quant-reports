import argparse

import pandas as pd
import pytest

from dl_growth24_post_prediction_gate_grid import _config_rank_key, build_report
from dl_growth24_post_prediction_gate_walk_forward import build_walk_forward_report


def _shadow_row(asof, ticker, rank, score, forecast, realized):
    return {
        "AsOfDate": asof,
        "Cycle": asof,
        "Ticker": ticker,
        "Rank": rank,
        "ShadowRankScore": score,
        "RawForecastPct": forecast,
        "RealizedForwardReturn": realized,
    }


def test_grid_ranks_dispersion_gate_when_it_skips_bad_cycle(tmp_path):
    shadow_log = tmp_path / "shadow_log.parquet"
    pd.DataFrame(
        [
            _shadow_row("2026-01-01", "AAA", 1, 0.030, 1.0, 0.10),
            _shadow_row("2026-01-01", "BBB", 2, 0.020, 0.5, 0.02),
            _shadow_row("2026-01-01", "CCC", 3, 0.010, -0.5, 0.00),
            _shadow_row("2026-01-01", "DDD", 4, 0.000, -1.0, -0.05),
            _shadow_row("2026-02-01", "AAA", 1, 0.500, 5.0, -0.20),
            _shadow_row("2026-02-01", "BBB", 2, 0.100, 1.0, 0.01),
            _shadow_row("2026-02-01", "CCC", 3, -0.100, -1.0, 0.02),
            _shadow_row("2026-02-01", "DDD", 4, -0.500, -5.0, 0.10),
            _shadow_row("2026-03-01", "BBB", 1, 0.040, 1.0, 0.08),
            _shadow_row("2026-03-01", "AAA", 2, 0.020, 0.5, 0.02),
            _shadow_row("2026-03-01", "CCC", 3, 0.010, -0.5, 0.01),
            _shadow_row("2026-03-01", "DDD", 4, 0.000, -1.0, -0.02),
        ]
    ).to_parquet(shadow_log, index=False)

    args = argparse.Namespace(
        shadow_log=shadow_log,
        long_n=1,
        short_n=1,
        max_score_gaps="none",
        max_forecast_gaps="none",
        max_universe_score_stds="none,0.05",
        max_long_ticker_shares="1.0",
        cooldown_cycles="0",
        max_consecutive="0",
        gate_min_mean_ls=0.0,
        gate_min_hit=0.50,
        gate_max_drawdown=-0.25,
        gate_min_coverage=0.50,
    )

    report, best_ledger = build_report(args)

    assert report["status"] == "pass"
    assert report["baseline"]["trade_days"] == 3
    assert report["baseline"]["mean_long_short_return"] == pytest.approx(-0.0166666667)
    assert report["best_config"]["name"] == "universe_score_std_max=0.05"
    assert report["best_config"]["summary"]["mean_long_short_return"] == pytest.approx(0.125)
    assert best_ledger["AsOfDate"].tolist() == ["2026-01-01", "2026-03-01"]


def test_config_rank_key_prefers_lower_drawdown_on_metric_tie():
    items = [
        {
            "gate": {"status": "pass"},
            "summary": {
                "mean_long_short_return": 0.10,
                "spread_hit_rate": 0.75,
                "max_drawdown": -0.20,
                "coverage": 0.80,
            },
        },
        {
            "gate": {"status": "pass"},
            "summary": {
                "mean_long_short_return": 0.10,
                "spread_hit_rate": 0.75,
                "max_drawdown": -0.05,
                "coverage": 0.80,
            },
        },
    ]

    assert sorted(items, key=_config_rank_key)[0]["summary"]["max_drawdown"] == -0.05


def test_walk_forward_selects_gate_on_train_and_scores_holdout(tmp_path):
    shadow_log = tmp_path / "walk_forward_shadow_log.parquet"
    pd.DataFrame(
        [
            _shadow_row("2026-01-01", "AAA", 1, 0.030, 1.0, 0.10),
            _shadow_row("2026-01-01", "BBB", 2, 0.020, 0.5, 0.02),
            _shadow_row("2026-01-01", "CCC", 3, 0.010, -0.5, 0.00),
            _shadow_row("2026-01-01", "DDD", 4, 0.000, -1.0, -0.05),
            _shadow_row("2026-02-01", "AAA", 1, 0.500, 5.0, -0.20),
            _shadow_row("2026-02-01", "BBB", 2, 0.100, 1.0, 0.01),
            _shadow_row("2026-02-01", "CCC", 3, -0.100, -1.0, 0.02),
            _shadow_row("2026-02-01", "DDD", 4, -0.500, -5.0, 0.10),
            _shadow_row("2026-03-01", "BBB", 1, 0.040, 1.0, 0.08),
            _shadow_row("2026-03-01", "AAA", 2, 0.020, 0.5, 0.02),
            _shadow_row("2026-03-01", "CCC", 3, 0.010, -0.5, 0.01),
            _shadow_row("2026-03-01", "DDD", 4, 0.000, -1.0, -0.02),
            _shadow_row("2026-04-01", "AAA", 1, 0.600, 5.0, -0.18),
            _shadow_row("2026-04-01", "BBB", 2, 0.100, 1.0, 0.01),
            _shadow_row("2026-04-01", "CCC", 3, -0.100, -1.0, 0.02),
            _shadow_row("2026-04-01", "DDD", 4, -0.600, -5.0, 0.12),
        ]
    ).to_parquet(shadow_log, index=False)
    args = argparse.Namespace(
        shadow_log=shadow_log,
        long_n=1,
        short_n=1,
        splits="2",
        min_train_cycles=2,
        min_test_cycles=2,
        max_score_gaps="none",
        max_forecast_gaps="none",
        max_universe_score_stds="none,0.05",
        max_long_ticker_shares="1.0",
        cooldown_cycles="0",
        max_consecutive="0",
        gate_min_mean_ls=0.0,
        gate_min_hit=0.50,
        gate_max_drawdown=-0.25,
        gate_min_coverage=0.50,
    )

    report = build_walk_forward_report(args)
    split = report["splits"][0]

    assert report["status"] == "pass"
    assert split["selected_train_config"]["name"] == "universe_score_std_max=0.05"
    assert split["selected_test"]["gate"]["status"] == "pass"
    assert split["selected_test"]["summary"]["mean_long_short_return"] > split["baseline_test"]["mean_long_short_return"]
