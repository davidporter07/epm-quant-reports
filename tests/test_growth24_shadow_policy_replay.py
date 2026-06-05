import argparse

import pandas as pd

from dl_growth24_shadow_policy_replay import build_replay


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


def _args(tmp_path, max_consecutive=2):
    return argparse.Namespace(
        shadow_log=tmp_path / "shadow_log.parquet",
        long_n=1,
        short_n=1,
        expected_universe_count=3,
        max_universe_score_std=0.05,
        max_forecast_gap=4.0,
        max_consecutive=max_consecutive,
        start_date=None,
        end_date=None,
        score_start_date=None,
        score_end_date=None,
    )


def test_shadow_policy_replay_attributes_replacement_delta(tmp_path):
    args = _args(tmp_path, max_consecutive=2)
    rows = []
    for asof, aaa_return, bbb_return in [
        ("2026-01-01", 0.05, 0.03),
        ("2026-02-01", 0.06, 0.04),
        ("2026-03-01", -0.10, 0.08),
        ("2026-04-01", 0.07, 0.05),
    ]:
        rows.extend(
            [
                _row(asof, "AAA", 1, 0.03, 1.0, aaa_return),
                _row(asof, "BBB", 2, 0.02, 0.5, bbb_return),
                _row(asof, "CCC", 3, -0.02, -1.0, -0.02),
            ]
        )
    pd.DataFrame(rows).to_parquet(args.shadow_log, index=False)

    ledger, summary = build_replay(args)

    assert ledger["OverlayLongTickers"].tolist() == ["AAA", "AAA", "BBB", "AAA"]
    assert ledger["ReplacementTickers"].tolist() == ["", "", "BBB", ""]
    assert summary["replacement_cycles"] == 1
    assert summary["replacement_ticker_counts"] == {"BBB": 1}
    assert summary["mean_replacement_delta"] > 0.0


def test_shadow_policy_replay_abstains_on_forecast_gap(tmp_path):
    args = _args(tmp_path, max_consecutive=2)
    pd.DataFrame(
        [
            _row("2026-01-01", "AAA", 1, 0.03, 5.0, 0.05),
            _row("2026-01-01", "BBB", 2, 0.02, 0.0, 0.04),
            _row("2026-01-01", "CCC", 3, -0.02, -1.0, -0.02),
        ]
    ).to_parquet(args.shadow_log, index=False)

    ledger, summary = build_replay(args)

    assert ledger["OverlayStatus"].tolist() == ["paper_overlay_abstain"]
    assert "long-short forecast gap 6.000000 > 4.000000" in ledger["GateFailures"].iloc[0]
    assert summary["overlay_abstained_cycles"] == 1


def test_shadow_policy_replay_filters_date_window(tmp_path):
    args = _args(tmp_path, max_consecutive=2)
    args.start_date = "2026-02-01"
    args.end_date = "2026-03-01"
    pd.DataFrame(
        [
            _row("2026-01-01", "AAA", 1, 0.03, 1.0, 0.05),
            _row("2026-01-01", "BBB", 2, 0.02, 0.5, 0.04),
            _row("2026-01-01", "CCC", 3, -0.02, -1.0, -0.02),
            _row("2026-02-01", "AAA", 1, 0.03, 1.0, 0.05),
            _row("2026-02-01", "BBB", 2, 0.02, 0.5, 0.04),
            _row("2026-02-01", "CCC", 3, -0.02, -1.0, -0.02),
            _row("2026-03-01", "AAA", 1, 0.03, 1.0, 0.05),
            _row("2026-03-01", "BBB", 2, 0.02, 0.5, 0.04),
            _row("2026-03-01", "CCC", 3, -0.02, -1.0, -0.02),
        ]
    ).to_parquet(args.shadow_log, index=False)

    ledger, summary = build_replay(args)

    assert ledger["AsOfDate"].tolist() == ["2026-02-01", "2026-03-01"]
    assert summary["cycles"] == 2
    assert summary["window"] == {
        "start_date": "2026-02-01",
        "end_date": "2026-03-01",
        "score_start_date": "2026-02-01",
        "score_end_date": "2026-03-01",
    }


def test_shadow_policy_replay_score_window_preserves_warmup_streaks(tmp_path):
    args = _args(tmp_path, max_consecutive=2)
    args.score_start_date = "2026-03-01"
    rows = []
    for asof, aaa_return, bbb_return in [
        ("2026-01-01", 0.05, 0.03),
        ("2026-02-01", 0.06, 0.04),
        ("2026-03-01", -0.10, 0.08),
    ]:
        rows.extend(
            [
                _row(asof, "AAA", 1, 0.03, 1.0, aaa_return),
                _row(asof, "BBB", 2, 0.02, 0.5, bbb_return),
                _row(asof, "CCC", 3, -0.02, -1.0, -0.02),
            ]
        )
    pd.DataFrame(rows).to_parquet(args.shadow_log, index=False)

    ledger, summary = build_replay(args)

    assert ledger["AsOfDate"].tolist() == ["2026-03-01"]
    assert ledger["OverlayLongTickers"].tolist() == ["BBB"]
    assert ledger["ReplacementTickers"].tolist() == ["BBB"]
    assert summary["replacement_cycles"] == 1
    assert summary["window"]["score_start_date"] == "2026-03-01"


def test_shadow_policy_replay_does_not_count_warmup_replacements(tmp_path):
    args = _args(tmp_path, max_consecutive=2)
    args.score_start_date = "2026-04-01"
    rows = []
    for asof, aaa_return, bbb_return in [
        ("2026-01-01", 0.05, 0.03),
        ("2026-02-01", 0.06, 0.04),
        ("2026-03-01", -0.10, 0.08),
        ("2026-04-01", 0.07, 0.05),
    ]:
        rows.extend(
            [
                _row(asof, "AAA", 1, 0.03, 1.0, aaa_return),
                _row(asof, "BBB", 2, 0.02, 0.5, bbb_return),
                _row(asof, "CCC", 3, -0.02, -1.0, -0.02),
            ]
        )
    pd.DataFrame(rows).to_parquet(args.shadow_log, index=False)

    ledger, summary = build_replay(args)

    assert ledger["AsOfDate"].tolist() == ["2026-04-01"]
    assert ledger["ReplacementTickers"].tolist() == [""]
    assert summary["replacement_cycles"] == 0
    assert summary["replacement_ticker_counts"] == {}
