"""Compare original regime ledgers against ticker-cooldown replay ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_ORIGINAL_DIR = Path("data/experiment/final4_growth24_earnings_regime_probe")
DEFAULT_CHALLENGER_DIR = Path("data/experiment/final4_growth24_earnings_ticker_cooldown_probe")
DEFAULT_OUTPUT = Path(
    "data/experiment/final4_growth24_earnings_ticker_cooldown_probe/stress_diff_report.json"
)
DEFAULT_MARKDOWN_OUTPUT = Path("notes/final4_growth24_earnings_ticker_cooldown_stress_diff.md")
STRESS_REGIMES = {
    "gfc_2008",
    "q4_2018_drawdown",
    "rate_bear_2022",
    "current_2026",
}


def _read_csv(path: Path) -> pd.DataFrame:
    rows = pd.read_csv(path)
    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce").dt.date.astype(str)
    for col in ("LongReturn", "ShortReturn", "LongShortReturn"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce")
    rows["LongTickers"] = rows["LongTickers"].astype(str).str.upper().str.strip()
    rows["ShortTickers"] = rows["ShortTickers"].astype(str).str.upper().str.strip()
    return rows.dropna(subset=["AsOfDate", "LongShortReturn"]).copy()


def _read_shadow_log(path: Path) -> pd.DataFrame:
    rows = pd.read_parquet(path).copy()
    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce").dt.date.astype(str)
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    for col in ("Rank", "ShadowRankScore", "RawForecastPct", "RealizedForwardReturn"):
        if col in rows.columns:
            rows[col] = pd.to_numeric(rows[col], errors="coerce")
    return rows.dropna(subset=["AsOfDate", "Ticker"]).copy()


def _single_ticker(value: Any) -> str:
    return str(value).split(",")[0].strip().upper()


def _candidate_lookup(shadow_log: pd.DataFrame, asof: str, ticker: str) -> dict[str, Any]:
    rows = shadow_log[(shadow_log["AsOfDate"] == asof) & (shadow_log["Ticker"] == ticker)]
    if rows.empty:
        return {}
    row = rows.iloc[0]
    return {
        "rank": float(row["Rank"]) if "Rank" in row and pd.notna(row["Rank"]) else None,
        "rank_score": float(row["ShadowRankScore"])
        if "ShadowRankScore" in row and pd.notna(row["ShadowRankScore"])
        else None,
        "forecast_pct": float(row["RawForecastPct"])
        if "RawForecastPct" in row and pd.notna(row["RawForecastPct"])
        else None,
        "realized_forward_return": float(row["RealizedForwardReturn"])
        if "RealizedForwardReturn" in row and pd.notna(row["RealizedForwardReturn"])
        else None,
    }


def _compare_regime(
    regime: str,
    original_path: Path,
    challenger_path: Path,
    shadow_log_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    original = _read_csv(original_path)
    challenger = _read_csv(challenger_path)
    shadow_log = _read_shadow_log(shadow_log_path)
    merged = original.merge(
        challenger,
        on="AsOfDate",
        suffixes=("_original", "_challenger"),
        how="outer",
        indicator=True,
    )
    rows: list[dict[str, Any]] = []
    for _, row in merged.sort_values("AsOfDate").iterrows():
        original_long = _single_ticker(row.get("LongTickers_original", ""))
        challenger_long = _single_ticker(row.get("LongTickers_challenger", ""))
        original_meta = _candidate_lookup(shadow_log, row["AsOfDate"], original_long)
        challenger_meta = _candidate_lookup(shadow_log, row["AsOfDate"], challenger_long)
        original_score = original_meta.get("rank_score")
        challenger_score = challenger_meta.get("rank_score")
        rows.append(
            {
                "regime": regime,
                "asof_date": row["AsOfDate"],
                "matched": row["_merge"] == "both",
                "long_changed": original_long != challenger_long,
                "short_changed": _single_ticker(row.get("ShortTickers_original", ""))
                != _single_ticker(row.get("ShortTickers_challenger", "")),
                "original_long": original_long,
                "challenger_long": challenger_long,
                "original_short": _single_ticker(row.get("ShortTickers_original", "")),
                "challenger_short": _single_ticker(row.get("ShortTickers_challenger", "")),
                "original_spread": float(row.get("LongShortReturn_original", float("nan"))),
                "challenger_spread": float(row.get("LongShortReturn_challenger", float("nan"))),
                "spread_delta": float(
                    row.get("LongShortReturn_challenger", float("nan"))
                    - row.get("LongShortReturn_original", float("nan"))
                ),
                "original_long_return": float(row.get("LongReturn_original", float("nan"))),
                "challenger_long_return": float(row.get("LongReturn_challenger", float("nan"))),
                "original_rank": original_meta.get("rank"),
                "challenger_rank": challenger_meta.get("rank"),
                "original_rank_score": original_score,
                "challenger_rank_score": challenger_score,
                "rank_score_gap": None
                if original_score is None or challenger_score is None
                else float(original_score - challenger_score),
            }
        )
    row_df = pd.DataFrame(rows)
    changed = row_df[row_df["long_changed"]].copy()
    summary = {
        "regime": regime,
        "days": int(len(row_df)),
        "changed_long_days": int(row_df["long_changed"].sum()),
        "original_mean_spread": float(row_df["original_spread"].mean()),
        "challenger_mean_spread": float(row_df["challenger_spread"].mean()),
        "mean_spread_delta": float(row_df["spread_delta"].mean()),
        "changed_mean_spread_delta": float(changed["spread_delta"].mean()) if not changed.empty else 0.0,
        "worst_delta": float(row_df["spread_delta"].min()),
        "best_delta": float(row_df["spread_delta"].max()),
    }
    return rows, summary


def build_report(original_dir: Path, challenger_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for regime in sorted(STRESS_REGIMES):
        original_path = original_dir / regime / f"{regime}_3c_3e_top1_bottom1.csv"
        challenger_path = challenger_dir / regime / f"{regime}_ticker_cooldown_top1_bottom1.csv"
        shadow_log_path = original_dir / regime / f"{regime}_3c_3e_shadow_log.parquet"
        missing = [path for path in (original_path, challenger_path, shadow_log_path) if not path.exists()]
        if missing:
            raise FileNotFoundError(f"{regime} missing required files: {missing}")
        regime_rows, summary = _compare_regime(regime, original_path, challenger_path, shadow_log_path)
        rows.extend(regime_rows)
        summaries.append(summary)

    row_df = pd.DataFrame(rows)
    changed = row_df[row_df["long_changed"]].copy()
    return {
        "status": "scored",
        "original_dir": str(original_dir),
        "challenger_dir": str(challenger_dir),
        "stress_regimes": sorted(STRESS_REGIMES),
        "stress_days": int(len(row_df)),
        "changed_long_days": int(row_df["long_changed"].sum()),
        "original_mean_spread": float(row_df["original_spread"].mean()),
        "challenger_mean_spread": float(row_df["challenger_spread"].mean()),
        "mean_spread_delta": float(row_df["spread_delta"].mean()),
        "changed_mean_spread_delta": float(changed["spread_delta"].mean()) if not changed.empty else 0.0,
        "summaries": summaries,
        "worst_changed_days": changed.sort_values("spread_delta").head(10).to_dict(orient="records"),
        "rows": rows,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Growth24 Ticker Cooldown Stress Diff",
        "",
        f"- Original dir: `{report['original_dir']}`",
        f"- Challenger dir: `{report['challenger_dir']}`",
        f"- Stress days: {report['stress_days']}",
        f"- Changed long-selection days: {report['changed_long_days']}",
        f"- Original stress mean spread: {report['original_mean_spread']:.6f}",
        f"- Challenger stress mean spread: {report['challenger_mean_spread']:.6f}",
        f"- Mean spread delta: {report['mean_spread_delta']:.6f}",
        f"- Changed-day mean spread delta: {report['changed_mean_spread_delta']:.6f}",
        "",
        "## Regime Summary",
        "",
        "| Regime | Days | Changed Longs | Original Spread | Challenger Spread | Delta | Worst Delta |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["summaries"]:
        lines.append(
            f"| {row['regime']} | {row['days']} | {row['changed_long_days']} | "
            f"{row['original_mean_spread']:.6f} | {row['challenger_mean_spread']:.6f} | "
            f"{row['mean_spread_delta']:.6f} | {row['worst_delta']:.6f} |"
        )

    lines.extend(
        [
            "",
            "## Worst Changed Decisions",
            "",
            "| Regime | Date | Original Long | Challenger Long | Original Rank | Challenger Rank | Score Gap | Original Spread | Challenger Spread | Delta |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["worst_changed_days"]:
        lines.append(
            f"| {row['regime']} | {row['asof_date']} | {row['original_long']} | "
            f"{row['challenger_long']} | {row.get('original_rank') or ''} | "
            f"{row.get('challenger_rank') or ''} | "
            f"{row['rank_score_gap'] if row.get('rank_score_gap') is not None else ''} | "
            f"{row['original_spread']:.6f} | {row['challenger_spread']:.6f} | "
            f"{row['spread_delta']:.6f} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare original and ticker-cooldown stress ledgers.")
    parser.add_argument("--original-dir", type=Path, default=DEFAULT_ORIGINAL_DIR)
    parser.add_argument("--challenger-dir", type=Path, default=DEFAULT_CHALLENGER_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    report = build_report(args.original_dir, args.challenger_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    print("Status: scored")
    print(f"Stress days: {report['stress_days']}")
    print(f"Changed long days: {report['changed_long_days']}")
    print(f"Original stress spread: {report['original_mean_spread']:.6f}")
    print(f"Challenger stress spread: {report['challenger_mean_spread']:.6f}")
    print(f"Mean delta: {report['mean_spread_delta']:.6f}")
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
