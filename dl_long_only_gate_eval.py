"""Evaluate long-only abstention gates on rank-head shadow logs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _parse_float_list(value: str) -> list[float]:
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def _parse_int_list(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def _safe_float(value: object, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if np.isfinite(out) else default


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return float("nan")
    equity = (1.0 + returns).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def _load_validation_metrics(path: object) -> dict[str, float]:
    if not isinstance(path, str) or not path.strip():
        return {}
    result_path = Path(path)
    if not result_path.exists():
        return {}
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return {}

    best = max(results, key=lambda item: _safe_float(item.get("selection_score"), -1.0e9))
    centered = best.get("rank_centered_metrics") or {}
    rank = best.get("rank_metrics") or {}
    return {
        "ValidationSelectionScore": _safe_float(best.get("selection_score")),
        "ValidationDailyIC": _safe_float(centered.get("Daily_IC_Mean"), _safe_float(rank.get("Daily_IC_Mean"))),
        "ValidationSpread": _safe_float(
            centered.get("Selection_Long_Short_Spread_Mean"),
            _safe_float(rank.get("Selection_Long_Short_Spread_Mean")),
        ),
        "ValidationSpreadPositiveRate": _safe_float(
            centered.get("Selection_Spread_Positive_Rate"),
            _safe_float(rank.get("Selection_Spread_Positive_Rate")),
        ),
    }


def _load_decisions(log_path: Path, top_n: int) -> pd.DataFrame:
    rows = pd.read_parquet(log_path).copy()
    required = {"AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"}
    missing = required.difference(rows.columns)
    if missing:
        raise ValueError(f"{log_path} missing required columns: {sorted(missing)}")

    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce")
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    rows["Rank"] = pd.to_numeric(rows["Rank"], errors="coerce")
    rows["RealizedForwardReturn"] = pd.to_numeric(rows["RealizedForwardReturn"], errors="coerce")
    rows["ShadowRankScore"] = pd.to_numeric(rows.get("ShadowRankScore"), errors="coerce")
    rows["RawForecastPct"] = pd.to_numeric(rows.get("RawForecastPct"), errors="coerce")
    rows = rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"]).copy()

    out_rows: list[dict[str, Any]] = []
    for asof, group in rows.groupby("AsOfDate", sort=True):
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
        longs = ordered.head(top_n).copy()
        if longs.empty:
            continue
        universe_return = float(ordered["RealizedForwardReturn"].mean())
        source = ordered["SourceResults"].dropna().iloc[0] if "SourceResults" in ordered.columns and ordered["SourceResults"].notna().any() else ""
        row = {
            "AsOfDate": asof.date().isoformat(),
            "LongTickers": ",".join(longs["Ticker"].tolist()),
            "LongReturn": float(longs["RealizedForwardReturn"].mean()),
            "UniverseReturn": universe_return,
            "LongExcessReturn": float(longs["RealizedForwardReturn"].mean() - universe_return),
            "TopAvgRankScore": _safe_float(longs["ShadowRankScore"].mean()),
            "UniverseAvgRankScore": _safe_float(ordered["ShadowRankScore"].mean()),
            "ScoreGap": _safe_float(longs["ShadowRankScore"].mean() - ordered["ShadowRankScore"].mean()),
            "TopAvgForecastPct": _safe_float(longs["RawForecastPct"].mean()),
            "UniverseAvgForecastPct": _safe_float(ordered["RawForecastPct"].mean()),
            "ForecastGapPct": _safe_float(longs["RawForecastPct"].mean() - ordered["RawForecastPct"].mean()),
            "UniverseCount": int(len(ordered)),
            "SourceResults": str(source),
        }
        row.update(_load_validation_metrics(source))
        out_rows.append(row)
    return pd.DataFrame(out_rows)


def _apply_gate(
    decisions: pd.DataFrame,
    min_score_gap: float,
    min_forecast_gap: float,
    min_validation_score: float,
    min_validation_daily_ic: float,
    min_validation_spread: float,
    min_validation_spread_positive_rate: float,
) -> pd.DataFrame:
    if decisions.empty:
        return decisions.copy()
    keep = pd.Series(True, index=decisions.index)
    keep &= pd.to_numeric(decisions["ScoreGap"], errors="coerce") >= min_score_gap
    keep &= pd.to_numeric(decisions["ForecastGapPct"], errors="coerce") >= min_forecast_gap
    keep &= pd.to_numeric(decisions["ValidationSelectionScore"], errors="coerce") >= min_validation_score
    keep &= pd.to_numeric(decisions["ValidationDailyIC"], errors="coerce") >= min_validation_daily_ic
    keep &= pd.to_numeric(decisions["ValidationSpread"], errors="coerce") >= min_validation_spread
    keep &= pd.to_numeric(decisions["ValidationSpreadPositiveRate"], errors="coerce") >= min_validation_spread_positive_rate
    return decisions.loc[keep].copy()


def _summarize(ledger: pd.DataFrame, available_days: int) -> dict[str, Any]:
    if ledger.empty:
        return {"status": "no_trades", "trade_days": 0, "coverage": 0.0}
    long_returns = pd.to_numeric(ledger["LongReturn"], errors="coerce")
    excess_returns = pd.to_numeric(ledger["LongExcessReturn"], errors="coerce")
    ticker_counts = (
        ledger["LongTickers"]
        .astype(str)
        .str.split(",")
        .explode()
        .str.strip()
        .str.upper()
        .value_counts()
        .to_dict()
    )
    max_ticker_share = max(ticker_counts.values(), default=0) / max(1, int(len(ledger)))
    return {
        "status": "scored",
        "trade_days": int(len(ledger)),
        "coverage": float(len(ledger) / max(1, available_days)),
        "asof_start": str(ledger["AsOfDate"].iloc[0]),
        "asof_end": str(ledger["AsOfDate"].iloc[-1]),
        "mean_long_return": float(long_returns.mean()),
        "mean_long_excess_return": float(excess_returns.mean()),
        "long_hit_rate": float((long_returns > 0.0).mean()),
        "excess_hit_rate": float((excess_returns > 0.0).mean()),
        "long_max_drawdown": _max_drawdown(long_returns),
        "excess_max_drawdown": _max_drawdown(excess_returns),
        "cumulative_long_equity": float((1.0 + long_returns).cumprod().iloc[-1]),
        "cumulative_excess_equity": float((1.0 + excess_returns).cumprod().iloc[-1]),
        "long_ticker_counts": ticker_counts,
        "max_ticker_share": float(max_ticker_share),
    }


def _gate_status(
    summary: dict[str, Any],
    min_excess: float,
    min_hit: float,
    max_drawdown: float,
    min_coverage: float,
    max_ticker_share: float,
) -> dict[str, Any]:
    failures = []
    if summary["coverage"] < min_coverage:
        failures.append(f"coverage {summary['coverage']:.2%} < {min_coverage:.2%}")
    if summary.get("max_ticker_share", 1.0) > max_ticker_share:
        failures.append(f"max ticker share {summary.get('max_ticker_share', 1.0):.2%} > {max_ticker_share:.2%}")
    if summary.get("mean_long_excess_return", float("-inf")) < min_excess:
        failures.append(f"mean excess {summary.get('mean_long_excess_return', float('nan')):.6f} < {min_excess:.6f}")
    if summary.get("excess_hit_rate", 0.0) < min_hit:
        failures.append(f"excess hit {summary.get('excess_hit_rate', 0.0):.2%} < {min_hit:.2%}")
    if summary.get("long_max_drawdown", -1.0) < max_drawdown:
        failures.append(f"long drawdown {summary.get('long_max_drawdown', float('nan')):.2%} < {max_drawdown:.2%}")
    return {"status": "pass" if not failures else "fail", "failures": failures}


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DL Long-Only Gate Evaluation",
        "",
        f"- Log path: `{report['log_path']}`",
        f"- Status: `{report['status']}`",
        f"- Candidate configs: {len(report['configs'])}",
        f"- Passing configs: {len(report['passing_configs'])}",
        "",
        "## Best Configs",
        "",
        "| Status | Top N | Score Gap | Forecast Gap | Val Score | Val IC | Val Spread | Val Hit | Mean Long | Mean Excess | Excess Hit | Coverage | Max Ticker | Long DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for config in report["configs"][:20]:
        summary = config["summary"]
        lines.append(
            f"| {config['gate']['status']} | {config['top_n']} | {config['min_score_gap']:.4f} | "
            f"{config['min_forecast_gap']:.4f} | {config['min_validation_score']:.4f} | "
            f"{config['min_validation_daily_ic']:.4f} | {config['min_validation_spread']:.4f} | "
            f"{config['min_validation_spread_positive_rate']:.2%} | "
            f"{summary.get('mean_long_return', float('nan')):.6f} | "
            f"{summary.get('mean_long_excess_return', float('nan')):.6f} | "
            f"{summary.get('excess_hit_rate', float('nan')):.2%} | "
            f"{summary.get('coverage', 0.0):.2%} | "
            f"{summary.get('max_ticker_share', float('nan')):.2%} | "
            f"{summary.get('long_max_drawdown', float('nan')):.2%} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate long-only abstention gates.")
    ap.add_argument("--log-path", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown-output", type=Path, default=None)
    ap.add_argument("--top-n-values", default="1,2,3")
    ap.add_argument("--min-score-gaps", default="0,0.01,0.02,0.04,0.08")
    ap.add_argument("--min-forecast-gaps", default="-10,0,0.5,1.0,1.5,2.0")
    ap.add_argument("--min-validation-scores", default="0,0.25,0.5")
    ap.add_argument("--min-validation-daily-ics", default="-0.05,0,0.05")
    ap.add_argument("--min-validation-spreads", default="0,0.02,0.05")
    ap.add_argument("--min-validation-spread-positive-rates", default="0.45,0.50,0.55")
    ap.add_argument("--gate-min-excess", type=float, default=0.0)
    ap.add_argument("--gate-min-hit", type=float, default=0.50)
    ap.add_argument("--gate-max-drawdown", type=float, default=-0.25)
    ap.add_argument("--gate-min-coverage", type=float, default=0.25)
    ap.add_argument("--gate-max-ticker-share", type=float, default=1.0)
    args = ap.parse_args()

    configs = []
    for top_n in _parse_int_list(args.top_n_values):
        decisions = _load_decisions(args.log_path, top_n)
        available_days = len(decisions)
        for min_score_gap in _parse_float_list(args.min_score_gaps):
            for min_forecast_gap in _parse_float_list(args.min_forecast_gaps):
                for min_validation_score in _parse_float_list(args.min_validation_scores):
                    for min_validation_daily_ic in _parse_float_list(args.min_validation_daily_ics):
                        for min_validation_spread in _parse_float_list(args.min_validation_spreads):
                            for min_validation_spread_positive_rate in _parse_float_list(args.min_validation_spread_positive_rates):
                                kept = _apply_gate(
                                    decisions,
                                    min_score_gap,
                                    min_forecast_gap,
                                    min_validation_score,
                                    min_validation_daily_ic,
                                    min_validation_spread,
                                    min_validation_spread_positive_rate,
                                )
                                summary = _summarize(kept, available_days)
                                gate = _gate_status(
                                    summary,
                                    args.gate_min_excess,
                                    args.gate_min_hit,
                                    args.gate_max_drawdown,
                                    args.gate_min_coverage,
                                    args.gate_max_ticker_share,
                                )
                                configs.append(
                                    {
                                        "top_n": int(top_n),
                                        "min_score_gap": float(min_score_gap),
                                        "min_forecast_gap": float(min_forecast_gap),
                                        "min_validation_score": float(min_validation_score),
                                        "min_validation_daily_ic": float(min_validation_daily_ic),
                                        "min_validation_spread": float(min_validation_spread),
                                        "min_validation_spread_positive_rate": float(min_validation_spread_positive_rate),
                                        "gate": gate,
                                        "summary": summary,
                                    }
                                )

    configs.sort(
        key=lambda item: (
            item["gate"]["status"] != "pass",
            -_safe_float(item["summary"].get("mean_long_excess_return"), -1.0e9),
            -_safe_float(item["summary"].get("excess_hit_rate"), 0.0),
            _safe_float(item["summary"].get("long_max_drawdown"), -1.0),
            -_safe_float(item["summary"].get("coverage"), 0.0),
        )
    )
    passing = [item for item in configs if item["gate"]["status"] == "pass"]
    report = {
        "status": "pass" if passing else "fail",
        "log_path": str(args.log_path),
        "gate_config": {
            "min_excess": args.gate_min_excess,
            "min_hit": args.gate_min_hit,
            "max_drawdown": args.gate_max_drawdown,
            "min_coverage": args.gate_min_coverage,
            "max_ticker_share": args.gate_max_ticker_share,
        },
        "passing_configs": passing,
        "configs": configs,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    best = configs[0]
    print(f"Status: {report['status']}")
    print(f"Candidate configs: {len(configs)}")
    print(f"Passing configs: {len(passing)}")
    print(
        f"Best: top{best['top_n']} status={best['gate']['status']} "
        f"long={best['summary'].get('mean_long_return', float('nan')):.6f} "
        f"excess={best['summary'].get('mean_long_excess_return', float('nan')):.6f} "
        f"hit={best['summary'].get('excess_hit_rate', float('nan')):.2%} "
        f"coverage={best['summary'].get('coverage', 0.0):.2%}"
    )
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
