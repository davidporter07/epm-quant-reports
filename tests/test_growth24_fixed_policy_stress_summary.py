import argparse

import pandas as pd

from scripts.growth24_fixed_policy_stress_summary import build_report


def _write_ledger(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)


def _row(asof, status, baseline, overlay=None):
    return {
        "AsOfDate": asof,
        "OverlayStatus": status,
        "BaselineLongShortReturn": baseline,
        "OverlayLongShortReturn": overlay,
    }


def _args(tmp_path, primary_policy="p0"):
    return argparse.Namespace(
        input_dir=tmp_path,
        policy_prefix="stress_",
        baseline_note=None,
        primary_policy=primary_policy,
        expected_regimes="current_2026,gfc_2008,q4_2018_drawdown,rate_bear_2022",
        min_allowed_decisions=4,
        min_mean_long_short=0.0,
        min_hit_rate=0.50,
        max_drawdown=-0.25,
        min_window_mean_long_short=-0.05,
        max_drawdown_worsening=0.05,
    )


def test_fixed_policy_stress_summary_scores_primary_policy(tmp_path):
    _write_ledger(
        tmp_path / "stress_current_2026_p0.csv",
        [
            _row("2026-02-03", "paper_overlay_allowed", 0.02, 0.02),
            _row("2026-03-05", "paper_overlay_allowed", -0.01, -0.01),
            _row("2026-04-06", "paper_overlay_abstain", 0.10),
        ],
    )
    _write_ledger(
        tmp_path / "stress_gfc_2008_p0.csv",
        [
            _row("2009-04-02", "paper_overlay_abstain", 0.05),
            _row("2009-05-01", "paper_overlay_abstain", 0.04),
            _row("2009-06-03", "paper_overlay_abstain", 0.03),
        ],
    )
    _write_ledger(
        tmp_path / "stress_q4_2018_drawdown_p0.csv",
        [
            _row("2018-10-03", "paper_overlay_abstain", -0.03),
            _row("2018-11-01", "paper_overlay_abstain", 0.02),
            _row("2018-12-03", "paper_overlay_abstain", 0.01),
        ],
    )
    _write_ledger(
        tmp_path / "stress_rate_bear_2022_p0.csv",
        [
            _row("2022-10-04", "paper_overlay_allowed", 0.08, 0.08),
            _row("2022-11-02", "paper_overlay_allowed", 0.04, 0.04),
            _row("2022-12-02", "paper_overlay_allowed", 0.03, 0.03),
        ],
    )
    _write_ledger(
        tmp_path / "stress_current_2026_s0.csv",
        [
            _row("2026-02-03", "paper_overlay_allowed", 0.02, 0.02),
            _row("2026-03-05", "paper_overlay_allowed", -0.08, -0.08),
            _row("2026-04-06", "paper_overlay_abstain", 0.10),
        ],
    )
    for regime in ["gfc_2008", "q4_2018_drawdown", "rate_bear_2022"]:
        _write_ledger(
            tmp_path / f"stress_{regime}_s0.csv",
            [
                _row("2026-01-01", "paper_overlay_abstain", 0.01),
                _row("2026-02-01", "paper_overlay_abstain", 0.01),
                _row("2026-03-01", "paper_overlay_abstain", 0.01),
            ],
        )

    report = build_report(_args(tmp_path))

    assert report["status"] == "pass"
    p0 = next(policy for policy in report["policies"] if policy["policy"] == "p0")
    s0 = next(policy for policy in report["policies"] if policy["policy"] == "s0")
    assert p0["allowed"]["cycles"] == 5
    assert p0["status"] == "pass"
    assert s0["status"] == "fail"
    assert any("allowed decisions 2 < 4" in failure for failure in s0["failures"])


def test_fixed_policy_stress_summary_fails_when_primary_missing_regime(tmp_path):
    _write_ledger(
        tmp_path / "stress_current_2026_p0.csv",
        [
            _row("2026-02-03", "paper_overlay_allowed", 0.02, 0.02),
            _row("2026-03-05", "paper_overlay_allowed", 0.03, 0.03),
            _row("2026-04-06", "paper_overlay_allowed", 0.04, 0.04),
        ],
    )

    report = build_report(_args(tmp_path))

    assert report["status"] == "fail"
    assert any("missing regimes" in failure for failure in report["failures"])
