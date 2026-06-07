import argparse

import pandas as pd

from scripts.growth24_policy_concentration_audit import build_report


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


def test_policy_concentration_audit_fails_dominant_slot_share(tmp_path):
    shadow_log = tmp_path / "shadow_log.parquet"
    rows = []
    for asof, top_ticker in [
        ("2026-01-01", "AAA"),
        ("2026-02-01", "AAA"),
        ("2026-03-01", "BBB"),
    ]:
        rows.extend(
            [
                _row(asof, top_ticker, 1, 0.03, 1.0, 0.20),
                _row(asof, "BBB" if top_ticker == "AAA" else "AAA", 2, 0.02, 0.5, 0.04),
                _row(asof, "CCC", 3, -0.01, 0.0, -0.02),
            ]
        )
    pd.DataFrame(rows).to_parquet(shadow_log, index=False)
    args = argparse.Namespace(
        shadow_log=shadow_log,
        long_n=1,
        short_n=1,
        expected_universe_count=3,
        policy="p0:0.05:4:0",
        start_date=None,
        end_date=None,
        score_start_date=None,
        score_end_date=None,
        max_slot_share=0.50,
        max_contribution_share=1.00,
        min_leave_one_out_uplift=0.0,
    )

    report = build_report(args)

    assert report["status"] == "fail"
    assert report["slot_concentration"]["max_slot_ticker"] == "AAA"
    assert report["slot_concentration"]["max_slot_share"] > 0.50
    assert any("max slot share" in failure for failure in report["failures"])
