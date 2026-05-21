"""Evaluate HMM stress-date abstention on a rank-head shadow log.

This is a post-prediction filter report. It does not retrain and does not
change the live pipeline. It asks whether skipping decision dates labeled as
HMM stress would improve the current research champion's long-only behavior.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import regime_detector


DEFAULT_SHADOW_LOG = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet"
)
DEFAULT_OUTPUT = Path(
    "data/experiment/historical_blind_rank_head/"
    "growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_hmm_abstention.json"
)
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_36c_8e_feature_probe_hmm_abstention.md")


def _max_drawdown(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return float("nan")
    equity = (1.0 + values).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def _fmt_pct(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not np.isfinite(number):
        return "n/a"
    return f"{number * 100:.{digits}f}%"


def _load_log(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Shadow log not found: {path}")
    rows = pd.read_parquet(path).copy()
    required = {"AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"}
    missing = required.difference(rows.columns)
    if missing:
        raise ValueError(f"{path} missing required columns: {sorted(missing)}")
    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce")
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    rows["Rank"] = pd.to_numeric(rows["Rank"], errors="coerce")
    rows["ShadowRankScore"] = pd.to_numeric(rows.get("ShadowRankScore"), errors="coerce")
    rows["RealizedForwardReturn"] = pd.to_numeric(rows["RealizedForwardReturn"], errors="coerce")
    rows = rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "RealizedForwardReturn"]).copy()
    return rows.sort_values(["AsOfDate", "Rank", "ShadowRankScore"], ascending=[True, True, False])


def _build_longs(rows: pd.DataFrame, top_n: int) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    for asof, group in rows.groupby("AsOfDate", sort=True):
        ordered = group.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False])
        longs = ordered.head(int(top_n)).copy()
        if longs.empty:
            continue
        long_return = float(longs["RealizedForwardReturn"].mean())
        universe_return = float(ordered["RealizedForwardReturn"].mean())
        out.append(
            {
                "AsOfDate": asof.date().isoformat(),
                "LongTickers": ",".join(longs["Ticker"].tolist()),
                "LongReturn": long_return,
                "UniverseReturn": universe_return,
                "LongExcessReturn": long_return - universe_return,
                "UniverseCount": int(len(ordered)),
            }
        )
    return pd.DataFrame(out)


def _attach_hmm(ledger: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return ledger.copy()
    start = str(ledger["AsOfDate"].iloc[0])
    end = str(ledger["AsOfDate"].iloc[-1])
    regimes = regime_detector.get_regime_series(start, end)
    regime_by_date = {idx.date().isoformat(): str(label) for idx, label in regimes.items()}
    out = ledger.copy()
    out["HMM_Regime"] = out["AsOfDate"].map(regime_by_date)
    out["HMM_Stress"] = out["HMM_Regime"].isin(regime_detector.STRESS_LABELS)
    return out


def _summarize(ledger: pd.DataFrame, available_days: int) -> dict[str, Any]:
    if ledger.empty:
        return {"status": "no_trades", "trade_days": 0, "coverage": 0.0}
    long_returns = pd.to_numeric(ledger["LongReturn"], errors="coerce")
    excess_returns = pd.to_numeric(ledger["LongExcessReturn"], errors="coerce")
    return {
        "status": "scored",
        "trade_days": int(len(ledger)),
        "coverage": float(len(ledger) / max(1, int(available_days))),
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
    }


def build_report(shadow_log: Path, top_n: int) -> dict[str, Any]:
    rows = _load_log(shadow_log)
    all_longs = _attach_hmm(_build_longs(rows, top_n))
    available_days = int(len(all_longs))
    stress = all_longs[all_longs["HMM_Stress"].eq(True)].copy()
    non_stress = all_longs[~all_longs["HMM_Stress"].eq(True)].copy()

    return {
        "status": "scored",
        "shadow_log": str(shadow_log),
        "top_n": int(top_n),
        "stress_labels": sorted(regime_detector.STRESS_LABELS),
        "all": _summarize(all_longs, available_days),
        "trade_only_non_hmm_stress": _summarize(non_stress, available_days),
        "hmm_stress_only": _summarize(stress, available_days),
        "skipped_hmm_stress_days": int(len(stress)),
        "kept_non_hmm_stress_days": int(len(non_stress)),
        "hmm_regime_counts": all_longs["HMM_Regime"].fillna("missing").value_counts().to_dict(),
    }


def _markdown(report: dict[str, Any]) -> str:
    all_summary = report["all"]
    filtered = report["trade_only_non_hmm_stress"]
    stress = report["hmm_stress_only"]
    lines = [
        "# Growth24 HMM Abstention Filter Report",
        "",
        f"- Shadow log: `{report['shadow_log']}`",
        f"- Top N: {report['top_n']}",
        f"- HMM stress labels: {', '.join(report['stress_labels'])}",
        "",
        "## Summary",
        "",
        "| Book | Trade Days | Coverage | Mean Excess | Excess Hit | Excess Max DD |",
        "|---|---:|---:|---:|---:|---:|",
        (
            f"| All decisions | {all_summary.get('trade_days', 0)} | {_fmt_pct(all_summary.get('coverage'))} | "
            f"{_fmt_pct(all_summary.get('mean_long_excess_return'))} | {_fmt_pct(all_summary.get('excess_hit_rate'))} | "
            f"{_fmt_pct(all_summary.get('excess_max_drawdown'))} |"
        ),
        (
            f"| Skip HMM stress | {filtered.get('trade_days', 0)} | {_fmt_pct(filtered.get('coverage'))} | "
            f"{_fmt_pct(filtered.get('mean_long_excess_return'))} | {_fmt_pct(filtered.get('excess_hit_rate'))} | "
            f"{_fmt_pct(filtered.get('excess_max_drawdown'))} |"
        ),
        (
            f"| HMM stress only | {stress.get('trade_days', 0)} | {_fmt_pct(stress.get('coverage'))} | "
            f"{_fmt_pct(stress.get('mean_long_excess_return'))} | {_fmt_pct(stress.get('excess_hit_rate'))} | "
            f"{_fmt_pct(stress.get('excess_max_drawdown'))} |"
        ),
        "",
        "## Regime Counts",
        "",
    ]
    for label, count in sorted(report["hmm_regime_counts"].items()):
        lines.append(f"- {label}: {count}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate HMM stress abstention on a rank-head shadow log.")
    parser.add_argument("--shadow-log", type=Path, default=DEFAULT_SHADOW_LOG)
    parser.add_argument("--top-n", type=int, default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    report = build_report(args.shadow_log, int(args.top_n))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    filtered = report["trade_only_non_hmm_stress"]
    stress = report["hmm_stress_only"]
    print("Status: scored")
    print(f"All trade days: {report['all']['trade_days']}")
    print(f"Skipped HMM stress days: {report['skipped_hmm_stress_days']}")
    print(f"Non-stress mean excess: {_fmt_pct(filtered.get('mean_long_excess_return'))}")
    print(f"Stress-only mean excess: {_fmt_pct(stress.get('mean_long_excess_return'))}")
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
