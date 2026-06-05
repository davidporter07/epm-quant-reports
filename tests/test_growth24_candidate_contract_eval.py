import argparse

import pandas as pd

import dl_growth24_candidate_contract_eval as candidate_contract


def _args(tmp_path):
    return argparse.Namespace(
        shadow_log=tmp_path / "shadow_log.parquet",
        long_n=1,
        short_n=1,
        expected_universe_count=3,
        practical_max_universe_score_std=0.085,
        practical_max_forecast_gap=4.0,
        research_max_consecutive=3,
        max_score_gaps="none",
        grid_max_forecast_gaps="none",
        grid_max_universe_score_stds="none",
        grid_max_consecutive="0",
        splits="18,24",
        min_train_cycles=12,
        min_test_cycles=8,
        score_start_dates="2024-10-11,2025-04-15",
        min_holdout_cycles_for_reporting=4,
        min_cycles_for_sensitivity=20,
        sensitivity_max_universe_score_stds="0.08,0.085,0.09",
        sensitivity_max_forecast_gaps="3.0,4.0,5.0",
        sensitivity_max_consecutive="0,3",
        min_holdout_allowed_cycles=4,
        min_holdout_filter_uplift=0.0,
        gate_min_mean_ls=0.0,
        gate_min_hit=0.50,
        gate_max_drawdown=-0.25,
        gate_min_coverage=0.25,
    )


def _replay_summary():
    return {
        "cycles": 12,
        "overlay_allowed_cycles": 7,
        "overlay_abstained_cycles": 5,
        "replacement_cycles": 0,
        "baseline_all_mean_long_short": 0.10,
        "overlay_allowed_mean_long_short": 0.12,
        "overlay_allowed_hit_rate": 0.70,
        "overlay_allowed_max_drawdown": -0.05,
        "baseline_allowed_mean_long_short": 0.10,
        "abstained_baseline_mean_long_short": 0.08,
        "mean_replacement_delta": None,
        "thresholds": {},
        "window": {},
    }


def _patch_common(monkeypatch, *, cycles, start_date, end_date, gate_status="pass"):
    monkeypatch.setattr(
        candidate_contract,
        "_available_cycles",
        lambda _: (cycles, start_date, end_date),
    )
    monkeypatch.setattr(
        candidate_contract,
        "build_gate_grid",
        lambda _: (
            {
                "status": gate_status,
                "passing_config_count": 1 if gate_status == "pass" else 0,
                "available_days": cycles,
                "baseline": {},
                "best_config": {},
            },
            pd.DataFrame(),
        ),
    )
    monkeypatch.setattr(
        candidate_contract,
        "build_replay",
        lambda _: (pd.DataFrame(), _replay_summary()),
    )


def test_short_history_candidate_is_provisional_and_does_not_score_pseudo_holdouts(tmp_path, monkeypatch):
    args = _args(tmp_path)
    _patch_common(
        monkeypatch,
        cycles=12,
        start_date="2025-05-15",
        end_date="2026-04-17",
    )

    report = candidate_contract.build_contract(args)

    assert report["status"] == "provisional"
    assert report["failures"] == []
    assert report["skipped_checks"] == ["walk_forward", "threshold_sensitivity"]
    assert [row["status"] for row in report["holdouts"]] == ["skipped", "skipped"]
    assert "Skipped checks: walk_forward, threshold_sensitivity" in candidate_contract._markdown(report)


def test_complete_candidate_requires_all_contract_checks_to_pass(tmp_path, monkeypatch):
    args = _args(tmp_path)
    _patch_common(
        monkeypatch,
        cycles=36,
        start_date="2023-04-12",
        end_date="2026-03-18",
    )
    monkeypatch.setattr(
        candidate_contract,
        "build_walk_forward_report",
        lambda _: {"status": "pass", "passing_split_count": 2, "splits": [{}, {}]},
    )
    monkeypatch.setattr(
        candidate_contract,
        "build_threshold_sensitivity",
        lambda _: (
            {
                "status": "pass",
                "config_count": 18,
                "passing_config_count": 17,
                "best_config": {},
            },
            pd.DataFrame(),
        ),
    )

    report = candidate_contract.build_contract(args)

    assert report["status"] == "pass"
    assert report["failures"] == []
    assert report["skipped_checks"] == []
    assert [row["status"] for row in report["holdouts"]] == ["scored", "scored"]


def test_failure_overrides_provisional_status(tmp_path, monkeypatch):
    args = _args(tmp_path)
    _patch_common(
        monkeypatch,
        cycles=12,
        start_date="2025-05-15",
        end_date="2026-04-17",
        gate_status="fail",
    )

    report = candidate_contract.build_contract(args)

    assert report["status"] == "fail"
    assert report["failures"] == ["gate_grid"]
    assert report["skipped_checks"] == ["walk_forward", "threshold_sensitivity"]
