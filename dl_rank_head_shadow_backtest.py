"""Generate historical shadow logs for the rank-head ensemble.

This mirrors the live shadow log shape, but emits rows for historical dates
whose 21-day forward returns are already known. The output can be scored by
dl_rank_head_shadow_score.py.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from deep_learning_model import TARGET_COL, PanelSequenceDataset, _ensure_panel_schema, read_panel, time_split
from dl_rank_head_experiment import RankHeadTCN, _center_by_date
from dl_rank_head_shadow_forecast import HORIZON, MODEL_NAME, _assign_candidate_bucket, _load_scaler
from dl_sign_regularized_experiment import _resolve_device

DEFAULT_RESULTS = Path("data/experiment/rank_head_selection_objective_scaler_5seed.json")
DEFAULT_PANEL = Path("data/experiment/directional_feature_panel_fmp.parquet")
DEFAULT_OUTPUT = Path("data/experiment/rank_head_shadow_backtest_log.parquet")
DEFAULT_CSV = Path("data/experiment/rank_head_shadow_backtest_log.csv")


def _load_result_rows(results_path: Path, top_n: int) -> tuple[dict, list[dict]]:
    with results_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    rows = sorted(
        list(payload.get("results", [])),
        key=lambda row: float(row.get("selection_score", 0.0)),
        reverse=True,
    )
    if top_n > 0:
        rows = rows[:top_n]
    if not rows:
        raise RuntimeError(f"No result rows found in {results_path}")
    return payload, rows


def _predict_checkpoint_frame(
    row: dict,
    panel: pd.DataFrame,
    device: str,
    amp: bool,
) -> pd.DataFrame:
    scaler, feature_cols, seq_len, hidden, dropout = _load_scaler(Path(row["scaler_path"]))
    ds = PanelSequenceDataset(panel, scaler, feature_cols, seq_len)
    loader = DataLoader(ds, batch_size=1024, shuffle=False)
    model = RankHeadTCN(n_features=len(feature_cols), hidden=hidden, dropout=dropout).to(device)
    checkpoint = torch.load(Path(row["model_path"]), map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    raw_preds = []
    rank_preds = []
    actuals = []
    tickers = []
    dates = []
    with torch.no_grad():
        for xb, yb, batch_tickers, date_ns in loader:
            xb = xb.to(device)
            with torch.amp.autocast("cuda", enabled=amp and device.startswith("cuda")):
                mu, _, rank_score = model(xb)
            raw_preds.append(mu.detach().cpu().numpy().ravel())
            rank_preds.append(rank_score.detach().cpu().numpy().ravel())
            actuals.append(yb.detach().cpu().numpy().ravel())
            tickers.extend([str(t).upper().strip() for t in batch_tickers])
            dates.append(np.asarray(date_ns).ravel())

    raw = np.concatenate(raw_preds)
    rank = np.concatenate(rank_preds)
    actual = np.concatenate(actuals)
    date_arr = np.concatenate(dates)
    asof_dates = pd.Series(pd.to_datetime(date_arr)).dt.date.astype("string")
    return pd.DataFrame(
        {
            "AsOfDate": asof_dates,
            "Ticker": tickers,
            "Member": row.get("variant", Path(row["model_path"]).stem),
            "SelectionScore": float(row.get("selection_score", np.nan)),
            "RawForecastPct": raw * 100.0,
            "RankScore": rank,
            "CenteredRankScore": _center_by_date(rank, date_arr),
            "RealizedForwardReturn": actual,
        }
    )


def _build_shadow_log(member_preds: pd.DataFrame, model_label: str, source_results: Path) -> pd.DataFrame:
    grouped = (
        member_preds.groupby(["AsOfDate", "Ticker"], as_index=False)
        .agg(
            ShadowRankScore=("CenteredRankScore", "mean"),
            RawForecastPct=("RawForecastPct", "mean"),
            RankScoreStd=("CenteredRankScore", "std"),
            RawForecastStd=("RawForecastPct", "std"),
            RealizedForwardReturn=("RealizedForwardReturn", "mean"),
            MemberCount=("Member", "nunique"),
            MeanMemberSelectionScore=("SelectionScore", "mean"),
        )
        .sort_values(["AsOfDate", "ShadowRankScore"], ascending=[True, False])
        .reset_index(drop=True)
    )
    grouped["RankScoreStd"] = grouped["RankScoreStd"].fillna(0.0)
    grouped["RawForecastStd"] = grouped["RawForecastStd"].fillna(0.0)

    pieces = []
    for _, day in grouped.groupby("AsOfDate", sort=True):
        day = day.sort_values("ShadowRankScore", ascending=False).copy()
        n = len(day)
        day["RunDate"] = date.today().isoformat()
        day["Model"] = model_label
        day["Horizon"] = HORIZON
        day["Rank"] = np.arange(1, n + 1, dtype=int)
        day["RankPercentile"] = 1.0 - ((day["Rank"] - 1) / max(1, n - 1))
        day["CandidateBucket"] = [_assign_candidate_bucket(int(rank), n) for rank in day["Rank"]]
        day["SourceResults"] = str(source_results)
        pieces.append(day)

    if not pieces:
        return pd.DataFrame()
    out = pd.concat(pieces, ignore_index=True)
    return out[
        [
            "RunDate",
            "AsOfDate",
            "Ticker",
            "Model",
            "Horizon",
            "Rank",
            "RankPercentile",
            "ShadowRankScore",
            "RawForecastPct",
            "RankScoreStd",
            "RawForecastStd",
            "CandidateBucket",
            "MemberCount",
            "MeanMemberSelectionScore",
            "SourceResults",
            "RealizedForwardReturn",
        ]
    ]


def generate_shadow_backtest(
    results_path: Path,
    panel_path: Path | None,
    val_days: int | None,
    start_date: str | None,
    end_date: str | None,
    top_n: int,
    output: Path,
    csv_output: Path,
    device_arg: str,
    amp: bool,
) -> pd.DataFrame:
    payload, rows = _load_result_rows(results_path, top_n)
    resolved_panel = Path(panel_path) if panel_path is not None else Path(payload.get("panel_path", DEFAULT_PANEL))
    panel = _ensure_panel_schema(read_panel(resolved_panel))
    panel = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()

    if val_days is not None:
        cutoff, _ = time_split(panel, int(val_days))
        panel = panel[panel["Date"] >= cutoff].copy()
    if start_date:
        panel = panel[panel["Date"] >= pd.Timestamp(start_date)].copy()
    if end_date:
        panel = panel[panel["Date"] <= pd.Timestamp(end_date)].copy()
    if panel.empty:
        raise RuntimeError("No labeled panel rows remain after date filters.")

    device = _resolve_device(device_arg)
    use_amp = bool(amp and device.startswith("cuda"))
    model_label = f"{MODEL_NAME}{len(rows)}Backtest"
    frames = [_predict_checkpoint_frame(row, panel, device, use_amp) for row in rows]
    member_preds = pd.concat(frames, ignore_index=True)
    shadow_log = _build_shadow_log(member_preds, model_label, results_path)

    output.parent.mkdir(parents=True, exist_ok=True)
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    shadow_log.to_parquet(output, index=False)
    shadow_log.to_csv(csv_output, index=False)
    return shadow_log


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate historical rank-head shadow logs for scoring.")
    ap.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    ap.add_argument("--panel", type=Path, default=None)
    ap.add_argument("--val-days", type=int, default=252)
    ap.add_argument("--start-date", default=None)
    ap.add_argument("--end-date", default=None)
    ap.add_argument("--top-n", type=int, default=3)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--csv-output", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--amp", action="store_true")
    args = ap.parse_args()

    out = generate_shadow_backtest(
        results_path=args.results,
        panel_path=args.panel,
        val_days=args.val_days,
        start_date=args.start_date,
        end_date=args.end_date,
        top_n=int(args.top_n),
        output=args.output,
        csv_output=args.csv_output,
        device_arg=args.device,
        amp=bool(args.amp),
    )

    print(f"Rows: {len(out)}")
    print(f"AsOfDate range: {out['AsOfDate'].min()} -> {out['AsOfDate'].max()}")
    print(f"Saved parquet -> {args.output}")
    print(f"Saved csv -> {args.csv_output}")
    print("Latest rows:")
    print(out.tail(7)[["AsOfDate", "Ticker", "Rank", "ShadowRankScore", "CandidateBucket"]].to_string(index=False))


if __name__ == "__main__":
    main()
