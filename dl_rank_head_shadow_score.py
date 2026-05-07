"""Score rank-head shadow forecasts against realized forward returns.

The shadow log is allowed to contain current rows whose 21-day forward returns
are not known yet. This scorer separates scoreable rows from pending rows and
writes both detailed joined rows and aggregate rank/selection metrics.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from deep_learning_model import TARGET_COL, read_panel, _ensure_panel_schema
from dl_rank_head_experiment import _selection_metrics
from dl_sign_regularized_experiment import _metrics

DEFAULT_LOG = Path("data/rank_head_shadow_log.parquet")
DEFAULT_PANEL = Path("data/experiment/directional_feature_panel_fmp.parquet")
DEFAULT_OUTPUT = Path("data/rank_head_shadow_scores.json")
DEFAULT_DETAIL = Path("data/rank_head_shadow_scores.csv")


def _load_shadow_log(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Shadow log not found: {path}")
    log = pd.read_parquet(path).copy()
    required = {"RunDate", "AsOfDate", "Ticker", "Model", "ShadowRankScore", "Rank", "CandidateBucket"}
    missing = required.difference(log.columns)
    if missing:
        raise ValueError(f"Shadow log missing required columns: {sorted(missing)}")
    log["RunDate"] = pd.to_datetime(log["RunDate"], errors="coerce").dt.date.astype("string")
    log["AsOfDate"] = pd.to_datetime(log["AsOfDate"], errors="coerce").dt.date.astype("string")
    log["Ticker"] = log["Ticker"].astype(str).str.upper().str.strip()
    return log


def _load_realized_targets(panel_path: Path) -> pd.DataFrame:
    panel = _ensure_panel_schema(read_panel(panel_path))
    panel = panel[["Date", "Ticker", TARGET_COL]].copy()
    panel["AsOfDate"] = pd.to_datetime(panel["Date"], errors="coerce").dt.date.astype("string")
    panel["Ticker"] = panel["Ticker"].astype(str).str.upper().str.strip()
    panel[TARGET_COL] = pd.to_numeric(panel[TARGET_COL], errors="coerce")
    return panel[["AsOfDate", "Ticker", TARGET_COL]]


def join_shadow_outcomes(log_path: Path, panel_path: Path) -> pd.DataFrame:
    log = _load_shadow_log(log_path)
    if "RealizedForwardReturn" in log.columns:
        joined = log.copy()
        joined["RealizedForwardReturn"] = pd.to_numeric(joined["RealizedForwardReturn"], errors="coerce")
        joined["ScoreStatus"] = np.where(joined["RealizedForwardReturn"].notna(), "scored", "pending")
        return joined

    realized = _load_realized_targets(panel_path)
    joined = log.merge(realized, on=["AsOfDate", "Ticker"], how="left")
    joined["RealizedForwardReturn"] = joined[TARGET_COL]
    joined["ScoreStatus"] = np.where(joined["RealizedForwardReturn"].notna(), "scored", "pending")
    return joined.drop(columns=[TARGET_COL])


def _candidate_metrics(scored: pd.DataFrame) -> dict:
    longs = scored[scored["CandidateBucket"] == "long_candidate"]
    shorts = scored[scored["CandidateBucket"] == "short_candidate"]
    long_mean = float(longs["RealizedForwardReturn"].mean()) if not longs.empty else float("nan")
    short_mean = float(shorts["RealizedForwardReturn"].mean()) if not shorts.empty else float("nan")
    return {
        "LongCandidateCount": int(len(longs)),
        "ShortCandidateCount": int(len(shorts)),
        "LongCandidateMeanReturn": long_mean,
        "ShortCandidateMeanReturn": short_mean,
        "LongMinusShortMeanReturn": float(long_mean - short_mean)
        if np.isfinite(long_mean) and np.isfinite(short_mean)
        else float("nan"),
        "LongHitRate": float((longs["RealizedForwardReturn"] > 0.0).mean()) if not longs.empty else float("nan"),
        "ShortHitRate": float((shorts["RealizedForwardReturn"] < 0.0).mean()) if not shorts.empty else float("nan"),
    }


def score_shadow_log(log_path: Path, panel_path: Path, detail_path: Path) -> dict:
    joined = join_shadow_outcomes(log_path, panel_path)
    detail_path.parent.mkdir(parents=True, exist_ok=True)
    joined.to_csv(detail_path, index=False)

    scored = joined[joined["ScoreStatus"] == "scored"].copy()
    pending = joined[joined["ScoreStatus"] == "pending"].copy()
    summary: dict[str, object] = {
        "log_path": str(log_path),
        "panel_path": str(panel_path),
        "detail_path": str(detail_path),
        "rows_total": int(len(joined)),
        "rows_scored": int(len(scored)),
        "rows_pending": int(len(pending)),
        "pending_asof_dates": sorted(pending["AsOfDate"].dropna().unique().tolist()),
    }

    if scored.empty:
        summary["status"] = "no_scoreable_rows"
        summary["metrics"] = {}
        return summary

    scored["DateNS"] = pd.to_datetime(scored["AsOfDate"]).astype("datetime64[ns]").astype("int64")
    pred = pd.to_numeric(scored["ShadowRankScore"], errors="coerce").to_numpy(dtype=np.float64)
    actual = pd.to_numeric(scored["RealizedForwardReturn"], errors="coerce").to_numpy(dtype=np.float64)
    dates = scored["DateNS"].to_numpy(dtype=np.int64)

    valid = np.isfinite(pred) & np.isfinite(actual)
    scored = scored.loc[valid].copy()
    pred = pred[valid]
    actual = actual[valid]
    dates = dates[valid]

    if len(scored) == 0:
        summary["status"] = "no_valid_scored_rows"
        summary["metrics"] = {}
        return summary

    metrics = _metrics(pred, actual, dates)
    metrics.update(_selection_metrics(pred, actual, dates))
    metrics.update(_candidate_metrics(scored))
    summary["status"] = "scored"
    summary["metrics"] = metrics
    summary["scored_asof_dates"] = sorted(scored["AsOfDate"].dropna().unique().tolist())
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Score rank-head shadow forecasts once outcomes mature.")
    ap.add_argument("--log-path", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--detail-output", type=Path, default=DEFAULT_DETAIL)
    args = ap.parse_args()

    summary = score_shadow_log(args.log_path, args.panel, args.detail_output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Rows total: {summary['rows_total']}")
    print(f"Rows scored: {summary['rows_scored']}")
    print(f"Rows pending: {summary['rows_pending']}")
    print(f"Status: {summary['status']}")
    if summary["metrics"]:
        for key, value in summary["metrics"].items():
            if isinstance(value, (int, np.integer)):
                print(f"{key}: {int(value)}")
            else:
                print(f"{key}: {float(value):.6f}")
    elif summary["pending_asof_dates"]:
        print(f"Pending AsOfDate values: {', '.join(summary['pending_asof_dates'])}")
    print(f"Saved summary -> {args.output}")
    print(f"Saved detail -> {args.detail_output}")


if __name__ == "__main__":
    main()
