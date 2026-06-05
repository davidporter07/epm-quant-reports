import argparse

import pandas as pd

from dl_growth24_overlay_candidate_sim import build_simulation


def _plan(asof):
    return {
        "RunDate": asof,
        "AsOfDate": asof,
        "Model": "Growth24RankHeadShadowTop2StressW2",
        "Status": "selected",
        "LongTickers": "AAA",
        "CandidateTickers": "AAA",
        "PaperTopN": 1,
        "SourceResults": f"{asof}.json",
    }


def _forecast(asof, forecasts=None):
    forecasts = forecasts or [1.0, 0.5, -0.5]
    rows = []
    for rank, (ticker, score, forecast) in enumerate(
        zip(["AAA", "BBB", "CCC"], [0.03, 0.02, -0.02], forecasts, strict=True),
        start=1,
    ):
        rows.append(
            {
                "RunDate": asof,
                "AsOfDate": asof,
                "Model": "Growth24RankHeadShadowTop2StressW2",
                "Ticker": ticker,
                "Rank": rank,
                "ShadowRankScore": score,
                "RawForecastPct": forecast,
                "SourceResults": f"{asof}.json",
            }
        )
    return rows


def _panel_rows(dates):
    return [
        {
            "Date": asof,
            "Ticker": ticker,
            "Close": 100.0,
            "Raw_Target_Forward_21D": 0.05 if ticker != "CCC" else -0.02,
            "Market_Forward_21D": 0.01,
            "Target_Forward_21D": 0.04 if ticker != "CCC" else -0.03,
        }
        for asof in dates
        for ticker in ["AAA", "BBB", "CCC"]
    ]


def _args(tmp_path, max_consecutive=2):
    return argparse.Namespace(
        paper_plan_log=tmp_path / "plans.csv",
        forecast_log=tmp_path / "forecasts.parquet",
        panel=tmp_path / "panel.parquet",
        long_n=1,
        short_n=1,
        expected_universe_count=3,
        max_universe_score_std=0.05,
        max_forecast_gap=4.0,
        max_consecutive=max_consecutive,
    )


def test_simulation_selects_replacement_after_max_consecutive(tmp_path):
    dates = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]
    args = _args(tmp_path, max_consecutive=2)
    pd.DataFrame([_plan(asof) for asof in dates]).to_csv(args.paper_plan_log, index=False)
    pd.DataFrame([row for asof in dates for row in _forecast(asof)]).to_parquet(args.forecast_log, index=False)
    pd.DataFrame(_panel_rows(dates)).to_parquet(args.panel, index=False)

    ledger, summary = build_simulation(args)

    assert ledger["OverlayLongTickers"].tolist() == ["AAA", "AAA", "BBB", "AAA"]
    assert ledger["ReplacementTickers"].tolist() == ["", "", "BBB", ""]
    assert summary["replacement_plan_count"] == 1
    assert summary["replacement_ticker_counts"] == {"BBB": 1}


def test_simulation_abstains_on_forecast_gap(tmp_path):
    dates = ["2026-01-01"]
    args = _args(tmp_path, max_consecutive=2)
    pd.DataFrame([_plan(asof) for asof in dates]).to_csv(args.paper_plan_log, index=False)
    pd.DataFrame([row for asof in dates for row in _forecast(asof, [5.0, 0.0, -1.0])]).to_parquet(
        args.forecast_log,
        index=False,
    )
    pd.DataFrame(_panel_rows(dates)).to_parquet(args.panel, index=False)

    ledger, summary = build_simulation(args)

    assert ledger["OverlayStatus"].tolist() == ["paper_overlay_abstain"]
    assert "long-short forecast gap 6.000000 > 4.000000" in ledger["GateFailures"].iloc[0]
    assert summary["overlay_abstained_plans"] == 1
