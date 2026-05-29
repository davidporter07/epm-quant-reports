import argparse

import pandas as pd

from dl_growth24_current_control_gate import build_gate, write_plan_overlay


def _inputs(tmp_path, max_universe_score_std=0.10):
    forecast = tmp_path / "forecast.csv"
    summary = tmp_path / "summary.json"
    panel_diagnostics = tmp_path / "panel_diagnostics.json"
    paper_plan = tmp_path / "paper_plan.csv"

    pd.DataFrame(
        [
            {
                "AsOfDate": "2026-05-28",
                "Ticker": "AAA",
                "Model": "Growth24RankHeadShadowTop2StressW2",
                "Rank": 1,
                "ShadowRankScore": 0.20,
                "RawForecastPct": 1.0,
                "MemberCount": 2,
                "SourceResults": "results.json",
            },
            {
                "AsOfDate": "2026-05-28",
                "Ticker": "BBB",
                "Model": "Growth24RankHeadShadowTop2StressW2",
                "Rank": 2,
                "ShadowRankScore": 0.10,
                "RawForecastPct": 0.5,
                "MemberCount": 2,
                "SourceResults": "results.json",
            },
            {
                "AsOfDate": "2026-05-28",
                "Ticker": "CCC",
                "Model": "Growth24RankHeadShadowTop2StressW2",
                "Rank": 3,
                "ShadowRankScore": -0.10,
                "RawForecastPct": -0.5,
                "MemberCount": 2,
                "SourceResults": "results.json",
            },
            {
                "AsOfDate": "2026-05-28",
                "Ticker": "DDD",
                "Model": "Growth24RankHeadShadowTop2StressW2",
                "Rank": 4,
                "ShadowRankScore": -0.20,
                "RawForecastPct": -1.0,
                "MemberCount": 2,
                "SourceResults": "results.json",
            },
        ]
    ).to_csv(forecast, index=False)
    summary.write_text('{"status": "selected", "selected_tickers": "AAA,BBB"}', encoding="utf-8")
    panel_diagnostics.write_text('{"passed": true}', encoding="utf-8")
    pd.DataFrame(
        [
            {
                "RunDate": "2026-05-28",
                "AsOfDate": "2026-05-28",
                "Model": "Growth24RankHeadShadowTop2StressW2",
                "Status": "selected",
                "LongTickers": "AAA,BBB",
                "CandidateTickers": "AAA,BBB",
                "SourceResults": "results.json",
            }
        ]
    ).to_csv(paper_plan, index=False)

    return argparse.Namespace(
        forecast=forecast,
        summary=summary,
        panel_diagnostics=panel_diagnostics,
        paper_plan=paper_plan,
        long_n=2,
        short_n=2,
        expected_universe_count=4,
        max_universe_score_std=max_universe_score_std,
        max_score_gap=None,
    )


def test_abstain_overlay_does_not_modify_current_paper_plan(tmp_path):
    args = _inputs(tmp_path, max_universe_score_std=0.10)
    original_plan = args.paper_plan.read_text(encoding="utf-8")

    report = build_gate(args)
    overlay_path = tmp_path / "paper_plan_overlay.csv"
    write_plan_overlay(overlay_path, report)

    assert report["status"] == "paper_control_abstain"
    assert report["paper_plan_overlay"]["status"] == "paper_overlay_abstain"
    assert report["paper_plan_overlay"]["paper_plan_changed"] is False
    assert args.paper_plan.read_text(encoding="utf-8") == original_plan

    overlay = pd.read_csv(overlay_path).iloc[0]
    assert overlay["PlanStatus"] == "selected"
    assert overlay["PlanLongTickers"] == "AAA,BBB"
    assert overlay["GateStatus"] == "paper_control_abstain"
    assert overlay["OverlayStatus"] == "paper_overlay_abstain"
    assert not bool(overlay["PaperPlanChanged"])


def test_allowed_overlay_marks_plan_allowed(tmp_path):
    args = _inputs(tmp_path, max_universe_score_std=0.20)

    report = build_gate(args)

    assert report["status"] == "paper_control_allowed"
    assert report["paper_plan_overlay"]["status"] == "paper_overlay_allowed"
    assert report["paper_plan_overlay"]["plan_long_tickers"] == ["AAA", "BBB"]
