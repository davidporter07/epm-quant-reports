import argparse
import json

from scripts.growth24_seed_stability_audit import build_report


def _result(seed, spread):
    return {
        "seed": seed,
        "hard_gate": True,
        "selection_score": 0.5,
        "model_path": f"model_{seed}.pt",
        "scaler_path": f"model_{seed}_scaler.json",
        "rank_centered_metrics": {
            "Selection_Long_Short_Spread_Mean": spread,
            "Selection_Count": 10,
            "Selection_Spread_Positive_Rate": 0.7,
            "Daily_IC_Mean": 0.05,
            "Daily_Count": 10,
        },
    }


def test_seed_stability_audit_fails_negative_aggregate_seed(tmp_path):
    for idx, date in enumerate(["2026-01-01", "2026-02-01"], start=1):
        (tmp_path / f"c00{idx}_{date.replace('-', '')}_results.json").write_text(
            json.dumps(
                {
                    "cycle": f"c00{idx}_{date.replace('-', '')}",
                    "decision_date": date,
                    "results": [
                        _result(1, 0.04),
                        _result(2, -0.02),
                    ],
                }
            ),
            encoding="utf-8",
        )
    args = argparse.Namespace(
        results_glob=str(tmp_path / "*_results.json"),
        expected_seeds="1,2",
        min_selection_spread=0.0,
    )

    report = build_report(args)

    assert report["status"] == "fail"
    seed1 = next(seed for seed in report["seeds"] if seed["seed"] == "1")
    seed2 = next(seed for seed in report["seeds"] if seed["seed"] == "2")
    assert seed1["status"] == "pass"
    assert seed2["status"] == "fail"
    assert any("aggregate selection spread" in failure for failure in seed2["failures"])
