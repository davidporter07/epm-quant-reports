"""Evaluate abstention gates on historical rank-head shadow logs.

The paper-trading ledgers force a long/short book on every decision date.
This script replays the same shadow logs with optional no-trade rules based
only on information available at the decision date: score dispersion from the
shadow forecast and validation metrics saved by the cycle result JSON.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import regime_detector


STRESS_REGIMES = {
    "gfc_2008",
    "q4_2018_drawdown",
    "rate_bear_2022",
    "current_2026",
}

_HMM_STRESS_CACHE: dict[tuple[str, str], set[str]] = {}


def _parse_float_list(value: str) -> list[float]:
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def _parse_int_list(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return float("nan")
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def _safe_float(value: object, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if np.isfinite(out) else default


def _get_hmm_stress_dates(start: str, end: str) -> set[str]:
    key = (str(start), str(end))
    if key in _HMM_STRESS_CACHE:
        return _HMM_STRESS_CACHE[key]
    series = regime_detector.get_regime_series(start, end)
    stress_dates = {
        idx.date().isoformat()
        for idx, label in series.items()
        if str(label) in regime_detector.STRESS_LABELS
    }
    _HMM_STRESS_CACHE[key] = stress_dates
    return stress_dates


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
    raw = best.get("raw_metrics") or {}
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
        "ValidationRankIC": _safe_float(centered.get("IC_Spearman"), _safe_float(rank.get("IC_Spearman"))),
        "ValidationRawDailyIC": _safe_float(raw.get("Daily_IC_Mean")),
    }


def _load_decision_frame(shadow_log: Path, long_n: int, short_n: int) -> pd.DataFrame:
    rows = pd.read_parquet(shadow_log).copy()
    required = {"AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"}
    missing = required.difference(rows.columns)
    if missing:
        raise ValueError(f"{shadow_log} missing required columns: {sorted(missing)}")

    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce")
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    rows["Rank"] = pd.to_numeric(rows["Rank"], errors="coerce")
    rows["RealizedForwardReturn"] = pd.to_numeric(rows["RealizedForwardReturn"], errors="coerce")
    rows["ShadowRankScore"] = pd.to_numeric(rows.get("ShadowRankScore"), errors="coerce")
    rows["RawForecastPct"] = pd.to_numeric(rows.get("RawForecastPct"), errors="coerce")
    rows["MeanMemberSelectionScore"] = pd.to_numeric(rows.get("MeanMemberSelectionScore"), errors="coerce")
    rows = rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"]).copy()

    out_rows: list[dict[str, Any]] = []
    for asof, group in rows.groupby("AsOfDate", sort=True):
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
        longs = ordered.head(long_n).copy()
        shorts = ordered.tail(short_n).copy()
        if longs.empty or shorts.empty:
            continue
        if set(longs["Ticker"]).intersection(set(shorts["Ticker"])):
            continue

        long_ret = float(longs["RealizedForwardReturn"].mean())
        short_ret = float(shorts["RealizedForwardReturn"].mean())
        source = ordered["SourceResults"].dropna().iloc[0] if "SourceResults" in ordered.columns and ordered["SourceResults"].notna().any() else ""
        row = {
            "AsOfDate": asof.date().isoformat(),
            "LongTickers": ",".join(longs["Ticker"].tolist()),
            "ShortTickers": ",".join(shorts["Ticker"].tolist()),
            "LongReturn": long_ret,
            "ShortReturn": short_ret,
            "LongShortReturn": long_ret - short_ret,
            "LongAvgRankScore": _safe_float(longs["ShadowRankScore"].mean()),
            "ShortAvgRankScore": _safe_float(shorts["ShadowRankScore"].mean()),
            "ScoreGap": _safe_float(longs["ShadowRankScore"].mean() - shorts["ShadowRankScore"].mean()),
            "LongAvgForecastPct": _safe_float(longs["RawForecastPct"].mean()),
            "ShortAvgForecastPct": _safe_float(shorts["RawForecastPct"].mean()),
            "ForecastGapPct": _safe_float(longs["RawForecastPct"].mean() - shorts["RawForecastPct"].mean()),
            "MeanMemberSelectionScore": _safe_float(ordered["MeanMemberSelectionScore"].dropna().iloc[0])
            if ordered["MeanMemberSelectionScore"].notna().any()
            else float("nan"),
            "UniverseCount": int(len(ordered)),
            "SourceResults": str(source),
        }
        row.update(_load_validation_metrics(source))
        out_rows.append(row)

    return pd.DataFrame(out_rows)


def _summarize_ledger(ledger: pd.DataFrame, regime: str, long_n: int, short_n: int, config: dict[str, float]) -> dict[str, Any]:
    if ledger.empty:
        return {
            "status": "no_trades",
            "regime": regime,
            "basket": f"top{long_n}_bottom{short_n}",
            "trade_days": 0,
            **config,
        }

    returns = pd.to_numeric(ledger["LongShortReturn"], errors="coerce")
    equity = (1.0 + returns).cumprod()
    hmm_summary: dict[str, Any] = {
        "hmm_stress_available": False,
        "hmm_stress_trade_days": 0,
        "hmm_stress_spread": float("nan"),
        "hmm_stress_hit": float("nan"),
        "hmm_stress_drawdown": float("nan"),
    }
    try:
        stress_dates = _get_hmm_stress_dates(str(ledger["AsOfDate"].iloc[0]), str(ledger["AsOfDate"].iloc[-1]))
        asof_dates = pd.to_datetime(ledger["AsOfDate"], errors="coerce").dt.date.astype(str)
        hmm_mask = asof_dates.isin(stress_dates)
        hmm_returns = returns[hmm_mask.to_numpy()]
        if not hmm_returns.empty:
            hmm_equity = (1.0 + hmm_returns).cumprod()
            hmm_summary = {
                "hmm_stress_available": True,
                "hmm_stress_trade_days": int(len(hmm_returns)),
                "hmm_stress_spread": float(hmm_returns.mean()),
                "hmm_stress_hit": float((hmm_returns > 0.0).mean()),
                "hmm_stress_drawdown": _max_drawdown(hmm_equity),
            }
    except Exception as exc:
        hmm_summary["hmm_stress_error"] = str(exc)
    return {
        "status": "scored",
        "regime": regime,
        "basket": f"top{long_n}_bottom{short_n}",
        "long_n": int(long_n),
        "short_n": int(short_n),
        "trade_days": int(len(ledger)),
        "asof_start": str(ledger["AsOfDate"].iloc[0]),
        "asof_end": str(ledger["AsOfDate"].iloc[-1]),
        "coverage": float(len(ledger) / max(1, int(config["available_days"]))),
        "mean_long_return": float(pd.to_numeric(ledger["LongReturn"], errors="coerce").mean()),
        "mean_short_return": float(pd.to_numeric(ledger["ShortReturn"], errors="coerce").mean()),
        "mean_long_short_return": float(returns.mean()),
        "spread_hit_rate": float((returns > 0.0).mean()),
        "cumulative_long_short_equity": float(equity.iloc[-1]),
        "max_drawdown": _max_drawdown(equity),
        **hmm_summary,
        **config,
    }


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


def _gate_report(
    rows: list[dict[str, Any]],
    min_spread: float,
    min_hit: float,
    max_drawdown: float,
    min_trade_days: int,
    min_stress_coverage: float,
) -> dict[str, Any]:
    failures: list[str] = []
    stress_rows = [row for row in rows if row["regime"] in STRESS_REGIMES]
    stress_by_regime = {row["regime"]: row for row in stress_rows}
    stress_coverages = [stress_by_regime.get(regime, {}).get("coverage", 0.0) for regime in STRESS_REGIMES]
    mean_coverage_stress = float(np.mean(stress_coverages)) if stress_coverages else 0.0
    if mean_coverage_stress < min_stress_coverage:
        failures.append(f"stress coverage {mean_coverage_stress:.2%} < {min_stress_coverage:.2%}")
    for row in stress_rows:
        if row["trade_days"] < min_trade_days:
            failures.append(f"{row['regime']} trade_days {row['trade_days']} < {min_trade_days}")
        if row["mean_long_short_return"] < min_spread:
            failures.append(f"{row['regime']} spread {row['mean_long_short_return']:.6f} < {min_spread:.6f}")
        if row["spread_hit_rate"] < min_hit:
            failures.append(f"{row['regime']} hit {row['spread_hit_rate']:.2%} < {min_hit:.2%}")
        if row["max_drawdown"] < max_drawdown:
            failures.append(f"{row['regime']} drawdown {row['max_drawdown']:.2%} < {max_drawdown:.2%}")
    hmm_rows = [row for row in rows if int(row.get("hmm_stress_trade_days", 0) or 0) > 0]
    hmm_checked = int(sum(int(row.get("hmm_stress_trade_days", 0) or 0) for row in hmm_rows))
    hmm_passes = 0
    for row in hmm_rows:
        if (
            row.get("hmm_stress_spread", float("nan")) >= min_spread
            and row.get("hmm_stress_hit", float("nan")) >= min_hit
            and row.get("hmm_stress_drawdown", float("nan")) >= max_drawdown
        ):
            hmm_passes += int(row.get("hmm_stress_trade_days", 0) or 0)
    hmm_pass_rate = float(hmm_passes / hmm_checked) if hmm_checked else float("nan")

    return {
        "status": "pass" if stress_rows and not failures else "fail",
        "failures": failures,
        "stress_regimes_checked": len(stress_rows),
        "mean_spread_all": float(np.mean([row["mean_long_short_return"] for row in rows])) if rows else float("nan"),
        "mean_spread_stress": float(np.mean([row["mean_long_short_return"] for row in stress_rows])) if stress_rows else float("nan"),
        "worst_stress_drawdown": float(min([row["max_drawdown"] for row in stress_rows], default=float("nan"))),
        "mean_coverage_stress": mean_coverage_stress,
        "hmm_stress_decisions": hmm_checked,
        "hmm_stress_pass_rate": hmm_pass_rate,
        "hmm_stress_mean_spread": float(np.mean([row["hmm_stress_spread"] for row in hmm_rows])) if hmm_rows else float("nan"),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DL Abstention Gate Evaluation",
        "",
        f"- Results dir: `{report['results_dir']}`",
        f"- Status: `{report['status']}`",
        f"- Candidate configs: {len(report['configs'])}",
        f"- Passing configs: {len(report['passing_configs'])}",
        "",
        "## Best Configs",
        "",
        "| Status | Basket | Score Gap | Forecast Gap | Val Score | Val Daily IC | Val Spread | Val Spread Hit | Stress Spread | Stress DD | Stress Coverage |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for config in report["configs"][:20]:
        lines.append(
            f"| {config['gate']['status']} | {config['basket']} | {config['min_score_gap']:.4f} | "
            f"{config['min_forecast_gap']:.4f} | {config['min_validation_score']:.4f} | "
            f"{config['min_validation_daily_ic']:.4f} | {config['min_validation_spread']:.4f} | "
            f"{config['min_validation_spread_positive_rate']:.2%} | {config['gate']['mean_spread_stress']:.6f} | "
            f"{config['gate']['worst_stress_drawdown']:.2%} | {config['gate']['mean_coverage_stress']:.2%} |"
        )

    if report["passing_configs"]:
        lines.extend(["", "## Passing Configs", ""])
        for config in report["passing_configs"][:20]:
            lines.append(
                f"- {config['basket']}: score_gap>={config['min_score_gap']:.4f}, "
                f"forecast_gap>={config['min_forecast_gap']:.4f}, "
                f"val_score>={config['min_validation_score']:.4f}, "
                f"val_daily_ic>={config['min_validation_daily_ic']:.4f}, "
                f"val_spread>={config['min_validation_spread']:.4f}, "
                f"val_spread_hit>={config['min_validation_spread_positive_rate']:.2%}"
            )
    lines.extend(
        [
            "",
            "## HMM Regime Stress",
            "",
            "[HMM regime] Rows add decision-date stress diagnostics using `regime_detector.get_regime_series()` and `STRESS_LABELS`.",
            "",
        ]
    )
    for config in report["configs"][:10]:
        gate = config["gate"]
        pass_rate = gate.get("hmm_stress_pass_rate")
        pass_text = "n/a" if not np.isfinite(_safe_float(pass_rate)) else f"{float(pass_rate):.2%}"
        lines.append(
            f"- [HMM regime] {config['basket']}: decisions={gate.get('hmm_stress_decisions', 0)}, "
            f"pass_rate={pass_text}, mean_spread={_safe_float(gate.get('hmm_stress_mean_spread')):.6f}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate abstention gates on DL regime shadow logs.")
    ap.add_argument("--results-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown-output", type=Path, default=None)
    ap.add_argument("--long-n-values", default="1,2,3")
    ap.add_argument("--short-n-values", default="1,2,3")
    ap.add_argument("--min-score-gaps", default="0,0.02,0.04,0.06,0.08,0.10")
    ap.add_argument("--min-forecast-gaps", default="0,0.5,1.0,1.5,2.0")
    ap.add_argument("--min-validation-scores", default="-10,-1,0,0.1,0.25")
    ap.add_argument("--min-validation-daily-ics", default="-0.20,-0.05,0,0.05,0.10")
    ap.add_argument("--min-validation-spreads", default="-0.10,-0.02,0,0.02,0.05")
    ap.add_argument("--min-validation-spread-positive-rates", default="0,0.45,0.50,0.55,0.60")
    ap.add_argument("--gate-min-spread", type=float, default=0.0)
    ap.add_argument("--gate-min-hit", type=float, default=0.50)
    ap.add_argument("--gate-max-drawdown", type=float, default=-0.25)
    ap.add_argument("--gate-min-trade-days", type=int, default=2)
    ap.add_argument("--gate-min-stress-coverage", type=float, default=0.10)
    args = ap.parse_args()

    long_values = _parse_int_list(args.long_n_values)
    short_values = _parse_int_list(args.short_n_values)
    score_gaps = _parse_float_list(args.min_score_gaps)
    forecast_gaps = _parse_float_list(args.min_forecast_gaps)
    validation_scores = _parse_float_list(args.min_validation_scores)
    validation_daily_ics = _parse_float_list(args.min_validation_daily_ics)
    validation_spreads = _parse_float_list(args.min_validation_spreads)
    validation_spread_positive_rates = _parse_float_list(args.min_validation_spread_positive_rates)

    logs = sorted(args.results_dir.rglob("*_shadow_log.parquet"))
    decision_cache: dict[tuple[Path, int, int], pd.DataFrame] = {}
    configs: list[dict[str, Any]] = []

    for long_n in long_values:
        for short_n in short_values:
            if long_n != short_n:
                continue
            basket = f"top{long_n}_bottom{short_n}"
            base_decisions: dict[str, pd.DataFrame] = {}
            for log in logs:
                regime = log.parent.name
                decisions = _load_decision_frame(log, long_n, short_n)
                base_decisions[regime] = decisions
                decision_cache[(log, long_n, short_n)] = decisions

            for min_score_gap in score_gaps:
                for min_forecast_gap in forecast_gaps:
                    for min_validation_score in validation_scores:
                        for min_validation_daily_ic in validation_daily_ics:
                            for min_validation_spread in validation_spreads:
                                for min_validation_spread_positive_rate in validation_spread_positive_rates:
                                    rows = []
                                    for regime, decisions in base_decisions.items():
                                        kept = _apply_gate(
                                            decisions,
                                            min_score_gap,
                                            min_forecast_gap,
                                            min_validation_score,
                                            min_validation_daily_ic,
                                            min_validation_spread,
                                            min_validation_spread_positive_rate,
                                        )
                                        if kept.empty:
                                            continue
                                        config = {
                                            "available_days": int(len(decisions)),
                                            "min_score_gap": float(min_score_gap),
                                            "min_forecast_gap": float(min_forecast_gap),
                                            "min_validation_score": float(min_validation_score),
                                            "min_validation_daily_ic": float(min_validation_daily_ic),
                                            "min_validation_spread": float(min_validation_spread),
                                            "min_validation_spread_positive_rate": float(min_validation_spread_positive_rate),
                                        }
                                        rows.append(_summarize_ledger(kept, regime, long_n, short_n, config))
                                    gate = _gate_report(
                                        rows,
                                        args.gate_min_spread,
                                        args.gate_min_hit,
                                        args.gate_max_drawdown,
                                        args.gate_min_trade_days,
                                        args.gate_min_stress_coverage,
                                    )
                                    configs.append(
                                        {
                                            "basket": basket,
                                            "long_n": int(long_n),
                                            "short_n": int(short_n),
                                            "min_score_gap": float(min_score_gap),
                                            "min_forecast_gap": float(min_forecast_gap),
                                            "min_validation_score": float(min_validation_score),
                                            "min_validation_daily_ic": float(min_validation_daily_ic),
                                            "min_validation_spread": float(min_validation_spread),
                                            "min_validation_spread_positive_rate": float(min_validation_spread_positive_rate),
                                            "gate": gate,
                                            "rows": rows,
                                        }
                                    )

    configs.sort(
        key=lambda item: (
            item["gate"]["status"] != "pass",
            -_safe_float(item["gate"]["mean_spread_stress"], -1.0e9),
            _safe_float(item["gate"]["worst_stress_drawdown"], -1.0e9),
            -_safe_float(item["gate"]["mean_coverage_stress"], 0.0),
        )
    )
    passing = [config for config in configs if config["gate"]["status"] == "pass"]
    report = {
        "status": "pass" if passing else "fail",
        "results_dir": str(args.results_dir),
        "stress_regimes": sorted(STRESS_REGIMES),
        "gate_config": {
            "min_spread": args.gate_min_spread,
            "min_hit": args.gate_min_hit,
            "max_drawdown": args.gate_max_drawdown,
            "min_trade_days": args.gate_min_trade_days,
            "min_stress_coverage": args.gate_min_stress_coverage,
        },
        "logs": [str(path) for path in logs],
        "passing_configs": passing[:50],
        "configs": configs[:100],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    print(f"Status: {report['status']}")
    print(f"Candidate configs: {len(configs)}")
    print(f"Passing configs: {len(passing)}")
    if configs:
        best = configs[0]
        print(
            "Best: "
            f"{best['basket']} status={best['gate']['status']} "
            f"stress_spread={best['gate']['mean_spread_stress']:.6f} "
            f"worst_dd={best['gate']['worst_stress_drawdown']:.2%} "
            f"coverage={best['gate']['mean_coverage_stress']:.2%}"
        )
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
