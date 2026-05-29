"""Combine chunked Growth24 stress-weighted 36-cycle replay artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from dl_rank_head_paper_trade import build_paper_ledger


STEM = "growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed"
OUT_DIR = Path("data/experiment/historical_blind_rank_head")
CHUNK_DIR = OUT_DIR / STEM
FINAL_LOG = OUT_DIR / f"{STEM}_shadow_log.parquet"
FINAL_CSV = OUT_DIR / f"{STEM}_shadow_log.csv"
SUMMARY_PATH = OUT_DIR / f"{STEM}_summary.json"


def main() -> None:
    logs = sorted(CHUNK_DIR.glob(f"{STEM}_chunk*_shadow_log.parquet"))
    if len(logs) != 6:
        raise RuntimeError(f"Expected 6 chunk logs under {CHUNK_DIR}, found {len(logs)}")

    frames = []
    for log in logs:
        rows = pd.read_parquet(log).copy()
        rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce").dt.date.astype(str)
        frames.append(rows)
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["AsOfDate", "Rank"]).reset_index(drop=True)

    dates = sorted(combined["AsOfDate"].dropna().unique().tolist())
    if len(dates) != 36:
        raise RuntimeError(f"Expected 36 unique AsOfDate values, found {len(dates)}")
    cycle_map = {date: f"c{idx:03d}_{pd.Timestamp(date).strftime('%Y%m%d')}" for idx, date in enumerate(dates, 1)}
    combined["Cycle"] = combined["AsOfDate"].map(cycle_map)

    ordered_cols = [
        "RunDate",
        "Cycle",
        "TrainLabelThrough",
        "AsOfDate",
        "Ticker",
        "Model",
        "Horizon",
        "Rank",
        "RankPercentile",
        "ShadowRankScore",
        "RawForecastPct",
        "CandidateBucket",
        "MemberCount",
        "MeanMemberSelectionScore",
        "SourceResults",
        "RealizedForwardReturn",
    ]
    combined = combined[ordered_cols]

    FINAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(FINAL_LOG, index=False)
    combined.to_csv(FINAL_CSV, index=False)

    paper_outputs: dict[str, dict] = {}
    for n in (1, 2, 3):
        ledger, summary = build_paper_ledger(FINAL_LOG, n, n)
        ledger_path = OUT_DIR / f"{STEM}_top{n}_bottom{n}.csv"
        summary_path = OUT_DIR / f"{STEM}_top{n}_bottom{n}.json"
        ledger.to_csv(ledger_path, index=False)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        paper_outputs[f"top{n}_bottom{n}"] = {
            "ledger": str(ledger_path),
            "summary": str(summary_path),
            "metrics": summary,
        }

    primary_ledger, primary_summary = build_paper_ledger(FINAL_LOG, 2, 2)
    primary_ledger_path = OUT_DIR / f"{STEM}_shadow_log_paper_ledger.csv"
    primary_summary_path = OUT_DIR / f"{STEM}_shadow_log_paper_summary.json"
    primary_ledger.to_csv(primary_ledger_path, index=False)
    primary_summary_path.write_text(json.dumps(primary_summary, indent=2), encoding="utf-8")

    cycle_summaries = []
    for asof, group in combined.groupby("AsOfDate", sort=True):
        long_rows = group[group["CandidateBucket"] == "long_candidate"]
        short_rows = group[group["CandidateBucket"] == "short_candidate"]
        long_ret = pd.to_numeric(long_rows["RealizedForwardReturn"], errors="coerce").mean()
        short_ret = pd.to_numeric(short_rows["RealizedForwardReturn"], errors="coerce").mean()
        cycle_summaries.append(
            {
                "cycle": cycle_map[str(asof)],
                "decision_date": str(asof),
                "train_label_through": str(group["TrainLabelThrough"].iloc[0]),
                "long_ticker": ",".join(long_rows["Ticker"].astype(str).tolist()),
                "short_ticker": ",".join(short_rows["Ticker"].astype(str).tolist()),
                "long_return": float(long_ret),
                "short_return": float(short_ret),
                "long_short_return": float(long_ret - short_ret),
            }
        )

    summary = {
        "status": "scored",
        "panel": "data/experiment/dl_research_panels/research_growth_24_price_earnings_av_panel.parquet",
        "cycles": int(len(dates)),
        "top_n": 1,
        "paper_long_n": 2,
        "paper_short_n": 2,
        "output": str(FINAL_LOG),
        "csv_output": str(FINAL_CSV),
        "paper_ledger": str(primary_ledger_path),
        "paper_summary": str(primary_summary_path),
        "stress_loss_weight": 2.0,
        "stress_feature_min": 2.0,
        "stress_drawdown_threshold": -0.20,
        "reconstructed_from_chunked_run": True,
        "chunk_dir": str(CHUNK_DIR),
        "chunk_logs": [str(path) for path in logs],
        "cycle_summaries": cycle_summaries,
        "paper_metrics": primary_summary,
        "basket_outputs": paper_outputs,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("Status: combined")
    print(f"Cycles: {summary['cycles']}")
    print(f"Rows: {len(combined)}")
    print(f"Top2 mean long-short return: {primary_summary['mean_long_short_return']:.6f}")
    print(f"Top2 spread hit rate: {primary_summary['spread_hit_rate']:.6f}")
    print(f"Saved shadow log -> {FINAL_LOG}")
    print(f"Saved summary -> {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
