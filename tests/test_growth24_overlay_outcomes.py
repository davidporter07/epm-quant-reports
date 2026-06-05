import pandas as pd
import pytest

from dl_growth24_paper_maturity_check import (
    _build_control_overlay_outcomes,
    _summarize_control_overlay_outcomes,
)


def _row(run_date, asof, model, status, tickers, source):
    return {
        "RunDate": run_date,
        "AsOfDate": asof,
        "Model": model,
        "Status": status,
        "LongTickers": tickers,
        "CandidateTickers": tickers,
        "PaperTopN": 2,
        "SourceResults": source,
    }


def _forecast_rows(run_date, asof, model, source, scores, forecasts=None):
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    forecasts = forecasts or [1.0, 0.5, -0.5, -1.0]
    return [
        {
            "RunDate": run_date,
            "AsOfDate": asof,
            "Ticker": ticker,
            "Model": model,
            "Rank": idx + 1,
            "ShadowRankScore": score,
            "RawForecastPct": forecast,
            "SourceResults": source,
        }
        for idx, (ticker, score, forecast) in enumerate(zip(tickers, scores, forecasts, strict=True))
    ]


def _trade_rows(run_date, asof, model, source, tickers, realized, excess):
    return [
        {
            "RunDate": run_date,
            "AsOfDate": asof,
            "Model": model,
            "SourceResults": source,
            "Status": "matured",
            "Ticker": ticker,
            "RealizedForward21D": ret,
            "RealizedExcess21D": ex,
            "Hit": ret > 0.0,
            "ExcessHit": ex > 0.0,
        }
        for ticker, ret, ex in zip(tickers, realized, excess, strict=True)
    ]


def test_control_overlay_outcome_ledger_compares_allowed_and_abstained_plans():
    model = "Growth24RankHeadShadowTop2StressW2"
    plan_log = pd.DataFrame(
        [
            _row("2026-01-01", "2026-01-01", model, "selected", "AAA,BBB", "res_a.json"),
            _row("2026-02-01", "2026-02-01", model, "selected", "AAA,BBB", "res_b.json"),
        ]
    )
    forecasts = pd.DataFrame(
        [
            *_forecast_rows("2026-01-01", "2026-01-01", model, "res_a.json", [0.03, 0.01, -0.01, -0.03]),
            *_forecast_rows("2026-02-01", "2026-02-01", model, "res_b.json", [0.20, 0.10, -0.10, -0.20]),
        ]
    )
    trades = pd.DataFrame(
        [
            *_trade_rows("2026-01-01", "2026-01-01", model, "res_a.json", ["AAA", "BBB"], [0.10, 0.06], [0.07, 0.03]),
            *_trade_rows("2026-02-01", "2026-02-01", model, "res_b.json", ["AAA", "BBB"], [-0.08, -0.04], [-0.10, -0.06]),
        ]
    )

    ledger = _build_control_overlay_outcomes(
        plan_log=plan_log,
        forecasts=forecasts,
        trades=trades,
        max_universe_score_std=0.05,
        expected_universe_count=4,
    )
    summary = _summarize_control_overlay_outcomes(ledger)

    assert ledger["OverlayStatus"].tolist() == ["paper_overlay_allowed", "paper_overlay_abstain"]
    assert ledger["OverlayTradeStatus"].tolist() == ["matured", "abstained_matured"]
    assert ledger["AbstentionClassification"].tolist() == ["", "avoided_loss"]
    assert summary["base_matured_plans"] == 2
    assert summary["overlay_matured_plans"] == 1
    assert summary["abstained_matured_plans"] == 1
    assert summary["avoided_loss_plans"] == 1
    assert summary["skipped_gain_plans"] == 0
    assert summary["overlay_matured_mean_forward_21d"] == pytest.approx(0.08)
    assert summary["abstained_matured_mean_forward_21d"] == pytest.approx(-0.06)


def test_control_overlay_outcome_ledger_abstains_on_forecast_gap():
    model = "Growth24RankHeadShadowTop2StressW2"
    plan_log = pd.DataFrame(
        [
            _row("2026-01-01", "2026-01-01", model, "selected", "AAA,BBB", "res_a.json"),
            _row("2026-02-01", "2026-02-01", model, "selected", "AAA,BBB", "res_b.json"),
        ]
    )
    forecasts = pd.DataFrame(
        [
            *_forecast_rows(
                "2026-01-01",
                "2026-01-01",
                model,
                "res_a.json",
                [0.03, 0.01, -0.01, -0.03],
                [1.0, 0.5, -0.5, -1.0],
            ),
            *_forecast_rows(
                "2026-02-01",
                "2026-02-01",
                model,
                "res_b.json",
                [0.03, 0.01, -0.01, -0.03],
                [5.0, 4.0, -1.0, -2.0],
            ),
        ]
    )
    trades = pd.DataFrame(
        [
            *_trade_rows("2026-01-01", "2026-01-01", model, "res_a.json", ["AAA", "BBB"], [0.10, 0.06], [0.07, 0.03]),
            *_trade_rows("2026-02-01", "2026-02-01", model, "res_b.json", ["AAA", "BBB"], [-0.08, -0.04], [-0.10, -0.06]),
        ]
    )

    ledger = _build_control_overlay_outcomes(
        plan_log=plan_log,
        forecasts=forecasts,
        trades=trades,
        max_universe_score_std=0.20,
        expected_universe_count=4,
        max_forecast_gap=4.0,
    )

    assert ledger["OverlayStatus"].tolist() == ["paper_overlay_allowed", "paper_overlay_abstain"]
    assert ledger["LongShortForecastGapPct"].tolist() == [pytest.approx(1.5), pytest.approx(6.0)]
    assert "long-short forecast gap 6.000000 > 4.000000" in ledger["GateFailures"].iloc[1]
