"""Evaluate post-prediction Growth24 gates on saved shadow logs.

This is research-only. It compares the raw top/bottom rank-head book against
paper-control overlays such as forecast-gap caps, dispersion caps, ticker-share
caps, and simple reuse cooldowns. It does not change live policy or paper-plan
files.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_SHADOW_LOG = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet"
)
DEFAULT_OUTPUT = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_post_prediction_gate_grid.json"
)
DEFAULT_LEDGER_OUTPUT = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_post_prediction_gate_grid_best.csv"
)
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_36c_8e_post_prediction_gate_grid.md")


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _fmt_pct(value: Any, digits: int = 2) -> str:
    number = _safe_float(value)
    if not np.isfinite(number):
        return "n/a"
    return f"{number * 100:.{digits}f}%"


def _fmt_num(value: Any, digits: int = 3) -> str:
    number = _safe_float(value)
    if not np.isfinite(number):
        return "n/a"
    return f"{number:.{digits}f}"


def _parse_float_grid(value: str, *, include_none: bool = True) -> list[float | None]:
    out: list[float | None] = []
    for part in value.split(","):
        token = part.strip().lower()
        if not token:
            continue
        if include_none and token in {"none", "null", "na", "n/a"}:
            out.append(None)
        else:
            out.append(float(token))
    return out


def _parse_int_grid(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def _max_drawdown(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return float("nan")
    equity = (1.0 + values).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def _load_shadow_log(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Shadow log not found: {path}")
    rows = pd.read_parquet(path).copy()
    required = {"AsOfDate", "Ticker", "Rank", "ShadowRankScore", "RealizedForwardReturn"}
    missing = required.difference(rows.columns)
    if missing:
        raise ValueError(f"{path} missing required columns: {sorted(missing)}")

    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce")
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    rows["Rank"] = pd.to_numeric(rows["Rank"], errors="coerce")
    rows["ShadowRankScore"] = pd.to_numeric(rows["ShadowRankScore"], errors="coerce")
    rows["RawForecastPct"] = pd.to_numeric(rows.get("RawForecastPct"), errors="coerce")
    rows["RealizedForwardReturn"] = pd.to_numeric(rows["RealizedForwardReturn"], errors="coerce")
    rows = rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "ShadowRankScore", "RealizedForwardReturn"]).copy()
    return rows.sort_values(["AsOfDate", "Rank", "ShadowRankScore"], ascending=[True, True, False])


def _cycle_frame(rows: pd.DataFrame, long_n: int, short_n: int) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    for asof, group in rows.groupby("AsOfDate", sort=True):
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
        longs = ordered.head(int(long_n))
        shorts = ordered.tail(int(short_n))
        if len(longs) < int(long_n) or len(shorts) < int(short_n):
            continue
        long_return = float(longs["RealizedForwardReturn"].mean())
        short_return = float(shorts["RealizedForwardReturn"].mean())
        long_score = float(longs["ShadowRankScore"].mean())
        short_score = float(shorts["ShadowRankScore"].mean())
        long_forecast = _safe_float(longs["RawForecastPct"].mean())
        short_forecast = _safe_float(shorts["RawForecastPct"].mean())
        out.append(
            {
                "AsOfDate": asof.date().isoformat(),
                "Cycle": str(ordered["Cycle"].dropna().iloc[0])
                if "Cycle" in ordered.columns and ordered["Cycle"].notna().any()
                else "",
                "LongTickers": ",".join(longs["Ticker"].tolist()),
                "ShortTickers": ",".join(shorts["Ticker"].tolist()),
                "LongReturn": long_return,
                "ShortReturn": short_return,
                "LongShortReturn": long_return - short_return,
                "UniverseScoreStd": float(ordered["ShadowRankScore"].std(ddof=0)),
                "LongShortScoreGap": long_score - short_score,
                "LongShortForecastGapPct": long_forecast - short_forecast,
                "LongAvgRankScore": long_score,
                "ShortAvgRankScore": short_score,
                "LongAvgForecastPct": long_forecast,
                "ShortAvgForecastPct": short_forecast,
            }
        )
    return pd.DataFrame(out)


def _summarize(ledger: pd.DataFrame, available_days: int, long_n: int) -> dict[str, Any]:
    if ledger.empty:
        return {"status": "no_trades", "trade_days": 0, "coverage": 0.0}
    returns = pd.to_numeric(ledger["LongShortReturn"], errors="coerce")
    long_returns = pd.to_numeric(ledger["LongReturn"], errors="coerce")
    short_returns = pd.to_numeric(ledger["ShortReturn"], errors="coerce")
    std = float(returns.std(ddof=1)) if len(returns) > 1 else float("nan")
    mean = float(returns.mean())
    long_counts = (
        ledger["LongTickers"]
        .astype(str)
        .str.split(",")
        .explode()
        .str.strip()
        .str.upper()
        .replace("", np.nan)
        .dropna()
        .value_counts()
        .to_dict()
    )
    slots = max(1, int(len(ledger) * int(long_n)))
    return {
        "status": "scored",
        "trade_days": int(len(ledger)),
        "coverage": float(len(ledger) / max(1, int(available_days))),
        "asof_start": str(ledger["AsOfDate"].iloc[0]),
        "asof_end": str(ledger["AsOfDate"].iloc[-1]),
        "mean_long_return": float(long_returns.mean()),
        "mean_short_return": float(short_returns.mean()),
        "mean_long_short_return": mean,
        "median_long_short_return": float(returns.median()),
        "std_long_short_return": std,
        "spread_hit_rate": float((returns > 0.0).mean()),
        "long_hit_rate": float((long_returns > 0.0).mean()),
        "short_hit_rate": float((short_returns < 0.0).mean()),
        "max_drawdown": _max_drawdown(returns),
        "naive_sharpe": float(mean / std * np.sqrt(252.0)) if std > 0 else float("nan"),
        "long_ticker_counts": long_counts,
        "max_long_ticker_slot_share": float(max(long_counts.values(), default=0) / slots),
    }


def _within_cap(counts: Counter[str], ticker: str, total_after: int, max_share: float) -> bool:
    if max_share >= 1.0:
        return True
    allowed = max(1, math.floor(float(max_share) * int(total_after)))
    return counts[str(ticker)] + 1 <= allowed


def _blocked_by_reuse(
    ticker: str,
    cycle_index: int,
    last_selected_cycle: dict[str, int],
    consecutive_selected: dict[str, int],
    cooldown_cycles: int,
    max_consecutive: int,
) -> bool:
    last_cycle = last_selected_cycle.get(str(ticker))
    if last_cycle is None:
        return False
    if cooldown_cycles > 0 and cycle_index - last_cycle <= cooldown_cycles:
        return True
    if max_consecutive > 0 and last_cycle == cycle_index - 1:
        return consecutive_selected.get(str(ticker), 0) >= max_consecutive
    return False


def _select_longs(
    ordered: pd.DataFrame,
    long_n: int,
    counts: Counter[str],
    selected_slots: int,
    max_long_ticker_share: float,
    cycle_index: int,
    last_selected_cycle: dict[str, int],
    consecutive_selected: dict[str, int],
    cooldown_cycles: int,
    max_consecutive: int,
) -> pd.DataFrame:
    picked: list[int] = []
    scratch = Counter(counts)
    total = int(selected_slots)
    for idx, row in ordered.iterrows():
        ticker = str(row["Ticker"]).upper().strip()
        if _blocked_by_reuse(
            ticker,
            cycle_index,
            last_selected_cycle,
            consecutive_selected,
            int(cooldown_cycles),
            int(max_consecutive),
        ):
            continue
        if not _within_cap(scratch, ticker, total + 1, float(max_long_ticker_share)):
            continue
        picked.append(idx)
        scratch[ticker] += 1
        total += 1
        if len(picked) >= int(long_n):
            break
    if len(picked) < int(long_n):
        return ordered.iloc[0:0].copy()
    return ordered.loc[picked].copy()


def _update_reuse_state(
    tickers: list[str],
    cycle_index: int,
    last_selected_cycle: dict[str, int],
    consecutive_selected: dict[str, int],
) -> None:
    for ticker in tickers:
        previous = last_selected_cycle.get(ticker)
        if previous == cycle_index - 1:
            consecutive_selected[ticker] = consecutive_selected.get(ticker, 0) + 1
        else:
            consecutive_selected[ticker] = 1
        last_selected_cycle[ticker] = cycle_index


def _config_name(config: dict[str, Any]) -> str:
    parts = []
    for key, label in [
        ("max_score_gap", "score_gap_max"),
        ("max_forecast_gap", "forecast_gap_max"),
        ("max_universe_score_std", "universe_score_std_max"),
    ]:
        value = config.get(key)
        if value is not None:
            parts.append(f"{label}={value:g}")
    if float(config["max_long_ticker_share"]) < 1.0:
        parts.append(f"long_share<={float(config['max_long_ticker_share']):g}")
    if int(config["cooldown_cycles"]) > 0:
        parts.append(f"cooldown={int(config['cooldown_cycles'])}")
    if int(config["max_consecutive"]) > 0:
        parts.append(f"max_consecutive={int(config['max_consecutive'])}")
    return "; ".join(parts) if parts else "baseline"


def _passes_metrics(cycle: pd.Series, config: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    max_score_gap = config.get("max_score_gap")
    if max_score_gap is not None and _safe_float(cycle["LongShortScoreGap"]) > float(max_score_gap):
        failures.append("score_gap_max")
    max_forecast_gap = config.get("max_forecast_gap")
    if max_forecast_gap is not None and _safe_float(cycle["LongShortForecastGapPct"]) > float(max_forecast_gap):
        failures.append("forecast_gap_max")
    max_universe_score_std = config.get("max_universe_score_std")
    if max_universe_score_std is not None and _safe_float(cycle["UniverseScoreStd"]) > float(max_universe_score_std):
        failures.append("universe_score_std_max")
    return not failures, failures


def _build_config_ledger(rows: pd.DataFrame, cycles: pd.DataFrame, config: dict[str, Any], long_n: int, short_n: int) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    selected_slots = 0
    last_selected_cycle: dict[str, int] = {}
    consecutive_selected: dict[str, int] = {}
    cycle_index_by_date = {date: idx for idx, date in enumerate(cycles["AsOfDate"].tolist())}

    for _, cycle in cycles.iterrows():
        asof = str(cycle["AsOfDate"])
        cycle_index = int(cycle_index_by_date[asof])
        passes, failures = _passes_metrics(cycle, config)
        if not passes:
            continue
        group = rows[pd.to_datetime(rows["AsOfDate"]).dt.date.astype(str).eq(asof)].copy()
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False])
        shorts = ordered.tail(int(short_n))
        longs = _select_longs(
            ordered,
            int(long_n),
            counts,
            selected_slots,
            float(config["max_long_ticker_share"]),
            cycle_index,
            last_selected_cycle,
            consecutive_selected,
            int(config["cooldown_cycles"]),
            int(config["max_consecutive"]),
        )
        if len(longs) < int(long_n) or len(shorts) < int(short_n):
            continue
        long_tickers = [str(ticker).upper().strip() for ticker in longs["Ticker"].tolist()]
        counts.update(long_tickers)
        selected_slots += len(long_tickers)
        _update_reuse_state(long_tickers, cycle_index, last_selected_cycle, consecutive_selected)

        long_return = float(longs["RealizedForwardReturn"].mean())
        short_return = float(shorts["RealizedForwardReturn"].mean())
        out.append(
            {
                "AsOfDate": asof,
                "Cycle": str(cycle.get("Cycle", "")),
                "LongTickers": ",".join(long_tickers),
                "ShortTickers": ",".join(shorts["Ticker"].tolist()),
                "LongReturn": long_return,
                "ShortReturn": short_return,
                "LongShortReturn": long_return - short_return,
                "BaselineLongTickers": cycle["LongTickers"],
                "BaselineShortTickers": cycle["ShortTickers"],
                "BaselineLongShortReturn": float(cycle["LongShortReturn"]),
                "SkipFailures": ";".join(failures),
                "UniverseScoreStd": float(cycle["UniverseScoreStd"]),
                "LongShortScoreGap": float(cycle["LongShortScoreGap"]),
                "LongShortForecastGapPct": float(cycle["LongShortForecastGapPct"]),
            }
        )
    return pd.DataFrame(out)


def _gate_status(summary: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    failures: list[str] = []
    if summary.get("coverage", 0.0) < float(args.gate_min_coverage):
        failures.append(f"coverage {summary.get('coverage', 0.0):.2%} < {float(args.gate_min_coverage):.2%}")
    if summary.get("mean_long_short_return", float("-inf")) < float(args.gate_min_mean_ls):
        failures.append(
            f"mean long-short {summary.get('mean_long_short_return', float('nan')):.6f} < {float(args.gate_min_mean_ls):.6f}"
        )
    if summary.get("spread_hit_rate", 0.0) < float(args.gate_min_hit):
        failures.append(f"spread hit {summary.get('spread_hit_rate', 0.0):.2%} < {float(args.gate_min_hit):.2%}")
    if summary.get("max_drawdown", -1.0) < float(args.gate_max_drawdown):
        failures.append(f"max drawdown {summary.get('max_drawdown', float('nan')):.2%} < {float(args.gate_max_drawdown):.2%}")
    return {"status": "pass" if not failures else "fail", "failures": failures}


def _config_rank_key(item: dict[str, Any]) -> tuple[bool, float, float, float, float]:
    summary = item["summary"]
    return (
        item["gate"]["status"] != "pass",
        -_safe_float(summary.get("mean_long_short_return"), -1.0e9),
        -_safe_float(summary.get("spread_hit_rate"), 0.0),
        -_safe_float(summary.get("max_drawdown"), -1.0),
        -_safe_float(summary.get("coverage"), 0.0),
    )


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame]:
    rows = _load_shadow_log(args.shadow_log)
    cycles = _cycle_frame(rows, int(args.long_n), int(args.short_n))
    available_days = int(len(cycles))
    baseline_summary = _summarize(cycles, available_days, int(args.long_n))

    configs: list[dict[str, Any]] = []
    for max_score_gap in _parse_float_grid(args.max_score_gaps):
        for max_forecast_gap in _parse_float_grid(args.max_forecast_gaps):
            for max_universe_score_std in _parse_float_grid(args.max_universe_score_stds):
                for max_long_ticker_share in _parse_float_grid(args.max_long_ticker_shares, include_none=False):
                    for cooldown_cycles in _parse_int_grid(args.cooldown_cycles):
                        for max_consecutive in _parse_int_grid(args.max_consecutive):
                            config = {
                                "max_score_gap": max_score_gap,
                                "max_forecast_gap": max_forecast_gap,
                                "max_universe_score_std": max_universe_score_std,
                                "max_long_ticker_share": float(max_long_ticker_share),
                                "cooldown_cycles": int(cooldown_cycles),
                                "max_consecutive": int(max_consecutive),
                            }
                            ledger = _build_config_ledger(rows, cycles, config, int(args.long_n), int(args.short_n))
                            summary = _summarize(ledger, available_days, int(args.long_n))
                            configs.append(
                                {
                                    "name": _config_name(config),
                                    "config": config,
                                    "summary": summary,
                                    "gate": _gate_status(summary, args),
                                }
                            )

    configs.sort(key=_config_rank_key)
    passing = [config for config in configs if config["gate"]["status"] == "pass"]
    best = configs[0] if configs else None
    best_ledger = pd.DataFrame()
    if best:
        best_ledger = _build_config_ledger(rows, cycles, best["config"], int(args.long_n), int(args.short_n))

    report = {
        "status": "pass" if passing else "fail",
        "shadow_log": str(args.shadow_log),
        "long_n": int(args.long_n),
        "short_n": int(args.short_n),
        "available_days": available_days,
        "gate_config": {
            "min_mean_ls": float(args.gate_min_mean_ls),
            "min_hit": float(args.gate_min_hit),
            "max_drawdown": float(args.gate_max_drawdown),
            "min_coverage": float(args.gate_min_coverage),
        },
        "baseline": baseline_summary,
        "passing_config_count": len(passing),
        "best_config": best,
        "configs": configs,
    }
    return report, best_ledger


def _markdown(report: dict[str, Any]) -> str:
    baseline = report["baseline"]
    lines = [
        "# Growth24 Post-Prediction Gate Grid",
        "",
        f"- Shadow log: `{report['shadow_log']}`",
        f"- Long/short book: top {report['long_n']} / bottom {report['short_n']}",
        f"- Available cycles: {report['available_days']}",
        f"- Overall status: `{report['status']}`",
        f"- Passing configs: {report['passing_config_count']}",
        "",
        "## Baseline",
        "",
        "| Days | Coverage | Mean LS | Median LS | Hit | Max DD | Sharpe | Max Long Share |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {baseline.get('trade_days', 0)} | {_fmt_pct(baseline.get('coverage'))} | "
            f"{_fmt_pct(baseline.get('mean_long_short_return'))} | "
            f"{_fmt_pct(baseline.get('median_long_short_return'))} | "
            f"{_fmt_pct(baseline.get('spread_hit_rate'))} | "
            f"{_fmt_pct(baseline.get('max_drawdown'))} | "
            f"{_fmt_num(baseline.get('naive_sharpe'))} | "
            f"{_fmt_pct(baseline.get('max_long_ticker_slot_share'))} |"
        ),
        "",
        "## Best Configs",
        "",
        "| Status | Config | Days | Coverage | Mean LS | Median LS | Hit | Max DD | Sharpe | Max Long Share |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["configs"][:25]:
        summary = item["summary"]
        lines.append(
            f"| {item['gate']['status']} | {item['name']} | "
            f"{summary.get('trade_days', 0)} | {_fmt_pct(summary.get('coverage'))} | "
            f"{_fmt_pct(summary.get('mean_long_short_return'))} | "
            f"{_fmt_pct(summary.get('median_long_short_return'))} | "
            f"{_fmt_pct(summary.get('spread_hit_rate'))} | "
            f"{_fmt_pct(summary.get('max_drawdown'))} | "
            f"{_fmt_num(summary.get('naive_sharpe'))} | "
            f"{_fmt_pct(summary.get('max_long_ticker_slot_share'))} |"
        )
    best = report.get("best_config") or {}
    best_summary = best.get("summary") or {}
    if best_summary:
        lines.extend(["", "## Best Ticker Counts", "", f"`{best_summary.get('long_ticker_counts', {})}`", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate post-prediction Growth24 gates on a saved shadow log.")
    parser.add_argument("--shadow-log", type=Path, default=DEFAULT_SHADOW_LOG)
    parser.add_argument("--long-n", type=int, default=2)
    parser.add_argument("--short-n", type=int, default=2)
    parser.add_argument("--max-score-gaps", default="none,0.36,0.32")
    parser.add_argument("--max-forecast-gaps", default="none,4.0")
    parser.add_argument("--max-universe-score-stds", default="none,0.09,0.085")
    parser.add_argument("--max-long-ticker-shares", default="1.0,0.5")
    parser.add_argument("--cooldown-cycles", default="0,2")
    parser.add_argument("--max-consecutive", default="0,3")
    parser.add_argument("--gate-min-mean-ls", type=float, default=0.0)
    parser.add_argument("--gate-min-hit", type=float, default=0.50)
    parser.add_argument("--gate-max-drawdown", type=float, default=-0.25)
    parser.add_argument("--gate-min-coverage", type=float, default=0.25)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ledger-output", type=Path, default=DEFAULT_LEDGER_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    report, best_ledger = build_report(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.ledger_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(report), indent=2), encoding="utf-8")
    best_ledger.to_csv(args.ledger_output, index=False)
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    baseline = report["baseline"]
    best = report.get("best_config") or {}
    best_summary = best.get("summary") or {}
    print(f"Status: {report['status']}")
    print(f"Configs: {len(report['configs'])}")
    print(f"Passing configs: {report['passing_config_count']}")
    print(
        "Baseline: "
        f"mean_ls={_fmt_pct(baseline.get('mean_long_short_return'))} "
        f"hit={_fmt_pct(baseline.get('spread_hit_rate'))} "
        f"max_dd={_fmt_pct(baseline.get('max_drawdown'))}"
    )
    print(
        "Best: "
        f"{best.get('name', 'n/a')} "
        f"mean_ls={_fmt_pct(best_summary.get('mean_long_short_return'))} "
        f"hit={_fmt_pct(best_summary.get('spread_hit_rate'))} "
        f"max_dd={_fmt_pct(best_summary.get('max_drawdown'))} "
        f"coverage={_fmt_pct(best_summary.get('coverage'))}"
    )
    print(f"Saved -> {args.output}")
    print(f"Saved -> {args.ledger_output}")
    print(f"Saved -> {args.markdown_output}")


if __name__ == "__main__":
    main()
