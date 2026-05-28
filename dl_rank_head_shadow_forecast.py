"""Generate daily shadow forecasts from the rank-head ensemble.

This is intentionally separate from production DL inference. It writes a
shadow-only CSV and parquet log so the rank-head selection signal can be
tracked live before any promotion into production forecast columns.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from deep_learning_model import apply_scaler, read_panel, _ensure_panel_schema
from dl_rank_head_experiment import RankHeadTCN
from dl_sign_regularized_experiment import _resolve_device

DEFAULT_RESULTS = Path("data/experiment/rank_head_selection_objective_scaler_5seed.json")
DEFAULT_CSV = Path("data/rank_head_shadow_forecasts.csv")
DEFAULT_LOG = Path("data/rank_head_shadow_log.parquet")
DEFAULT_TICKERS = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]
MODEL_NAME = "RankHeadShadowTop"
HORIZON = 21


def _load_scaler(path: Path) -> tuple[dict, list[str], int, int, float]:
    with Path(path).open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return (
        payload["scaler"],
        list(payload["feature_cols"]),
        int(payload.get("seq_len", 60)),
        int(payload.get("hidden", 64)),
        float(payload.get("dropout", 0.10)),
    )


def _load_result_rows(results_path: Path, top_n: int) -> tuple[dict, list[dict]]:
    with Path(results_path).open("r", encoding="utf-8") as f:
        payload = json.load(f)
    rows = sorted(
        list(payload.get("results", [])),
        key=lambda row: float(row.get("selection_score", 0.0)),
        reverse=True,
    )
    if top_n > 0:
        rows = rows[:top_n]
    if not rows:
        raise RuntimeError(f"No rank-head result rows found in {results_path}")
    return payload, rows


def _latest_valid_window(
    ticker_panel: pd.DataFrame,
    scaler: dict,
    feature_cols: list[str],
    seq_len: int,
) -> pd.DataFrame | None:
    g = ticker_panel.sort_values("Date")
    if len(g) < seq_len:
        return None
    for end_pos in range(len(g), seq_len - 1, -1):
        window = g.iloc[end_pos - seq_len : end_pos].copy()
        X = apply_scaler(window, scaler, feature_cols)
        if np.isfinite(X).all():
            return window
    return None


def _predict_member(row: dict, panel: pd.DataFrame, tickers: list[str], device: str, amp: bool) -> pd.DataFrame:
    scaler, feature_cols, seq_len, hidden, dropout = _load_scaler(Path(row["scaler_path"]))
    model = RankHeadTCN(n_features=len(feature_cols), hidden=hidden, dropout=dropout).to(device)
    checkpoint = torch.load(Path(row["model_path"]), map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    rows = []
    with torch.no_grad():
        for ticker in tickers:
            g = panel[panel["Ticker"] == ticker]
            if len(g) < seq_len:
                print(f" {ticker}: not enough history for rank-head window ({len(g)}/{seq_len}).")
                continue

            tail = _latest_valid_window(g, scaler, feature_cols, seq_len)
            if tail is None:
                print(f" {ticker}: no fully finite rank-head feature window found.")
                continue

            X = apply_scaler(tail, scaler, feature_cols)
            xb = torch.from_numpy(X).unsqueeze(0).to(device)
            with torch.amp.autocast("cuda", enabled=amp and device.startswith("cuda")):
                raw_mu, _, rank_score = model(xb)

            rows.append(
                {
                    "Ticker": ticker,
                    "AsOfDate": pd.Timestamp(tail["Date"].iloc[-1]).date().isoformat(),
                    "Member": row.get("variant", Path(row["model_path"]).stem),
                    "SelectionScore": float(row.get("selection_score", np.nan)),
                    "RawForecastPct": float(raw_mu.detach().cpu().numpy().ravel()[0]) * 100.0,
                    "RankScore": float(rank_score.detach().cpu().numpy().ravel()[0]),
                }
            )
    return pd.DataFrame(rows)


def _assign_candidate_bucket(rank: int, n: int) -> str:
    if n <= 2:
        return "neutral"
    top_cut = max(1, int(np.floor(n * 0.20)))
    bottom_start = n - top_cut + 1
    if rank <= top_cut:
        return "long_candidate"
    if rank >= bottom_start:
        return "short_candidate"
    return "neutral"


def _build_ensemble(member_preds: pd.DataFrame, model_label: str, results_path: Path) -> pd.DataFrame:
    if member_preds.empty:
        return member_preds

    centered = member_preds.copy()
    centered["CenteredRankScore"] = centered["RankScore"] - centered.groupby("Member")["RankScore"].transform("mean")
    grouped = (
        centered.groupby(["Ticker", "AsOfDate"], as_index=False)
        .agg(
            ShadowRankScore=("CenteredRankScore", "mean"),
            RawForecastPct=("RawForecastPct", "mean"),
            RankScoreStd=("CenteredRankScore", "std"),
            RawForecastStd=("RawForecastPct", "std"),
            MemberCount=("Member", "nunique"),
            MeanMemberSelectionScore=("SelectionScore", "mean"),
        )
        .sort_values("ShadowRankScore", ascending=False)
        .reset_index(drop=True)
    )
    grouped["RankScoreStd"] = grouped["RankScoreStd"].fillna(0.0)
    grouped["RawForecastStd"] = grouped["RawForecastStd"].fillna(0.0)
    n = len(grouped)
    grouped["RunDate"] = date.today().isoformat()
    grouped["Model"] = model_label
    grouped["Horizon"] = HORIZON
    grouped["Rank"] = np.arange(1, n + 1, dtype=int)
    grouped["RankPercentile"] = 1.0 - ((grouped["Rank"] - 1) / max(1, n - 1))
    grouped["CandidateBucket"] = [
        _assign_candidate_bucket(int(rank), n) for rank in grouped["Rank"].to_numpy(dtype=int)
    ]
    grouped["SourceResults"] = str(results_path)
    return grouped[
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
        ]
    ]


def _append_log(rows: pd.DataFrame, log_path: Path) -> None:
    if rows.empty:
        return
    if log_path.exists():
        old = pd.read_parquet(log_path)
        combined = pd.concat([old, rows], ignore_index=True)
    else:
        combined = rows.copy()
    combined = combined.drop_duplicates(subset=["RunDate", "Ticker", "Model"], keep="last")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(log_path, index=False)


def generate_shadow_forecasts(
    results_path: Path,
    panel_path: Path | None,
    tickers: list[str],
    top_n: int,
    output_csv: Path,
    log_path: Path,
    device_arg: str,
    amp: bool,
) -> pd.DataFrame:
    payload, rows = _load_result_rows(results_path, top_n)
    resolved_panel = Path(panel_path) if panel_path is not None else Path(payload["panel_path"])
    panel = _ensure_panel_schema(read_panel(resolved_panel))
    tickers = [str(t).strip().upper().replace(".", "-") for t in tickers if str(t).strip()]
    device = _resolve_device(device_arg)
    use_amp = bool(amp and device.startswith("cuda"))
    model_label = f"{MODEL_NAME}{len(rows)}"

    member_frames = [_predict_member(row, panel, tickers, device, use_amp) for row in rows]
    member_preds = pd.concat([df for df in member_frames if not df.empty], ignore_index=True)
    ensemble = _build_ensemble(member_preds, model_label, results_path)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    ensemble.to_csv(output_csv, index=False)
    _append_log(ensemble, log_path)
    return ensemble


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    ap.add_argument("--panel", type=Path, default=None)
    ap.add_argument("--tickers", type=str, default=",".join(DEFAULT_TICKERS))
    ap.add_argument("--top-n", type=int, default=3)
    ap.add_argument("--output", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--log-path", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--amp", action="store_true")
    args = ap.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    out = generate_shadow_forecasts(
        results_path=args.results,
        panel_path=args.panel,
        tickers=tickers,
        top_n=int(args.top_n),
        output_csv=args.output,
        log_path=args.log_path,
        device_arg=args.device,
        amp=bool(args.amp),
    )

    if out.empty:
        print("No rank-head shadow forecasts were generated.")
        return

    print("Rank-head shadow forecasts:")
    print(out[["Ticker", "Rank", "RankPercentile", "ShadowRankScore", "CandidateBucket"]].to_string(index=False))
    print(f"Saved current snapshot -> {args.output}")
    print(f"Updated shadow log -> {args.log_path}")


if __name__ == "__main__":
    main()
