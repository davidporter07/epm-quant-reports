"""Evaluate saved rank-head experiment checkpoints as an ensemble."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from deep_learning_model import TARGET_COL, PanelSequenceDataset, _ensure_panel_schema, read_panel, time_split
from dl_rank_head_experiment import RankHeadTCN, _center_by_date, _selection_metrics
from dl_sign_regularized_experiment import _metrics, _resolve_device

OUT_PATH = Path("data/experiment/rank_head_ensemble_eval.json")
CSV_PATH = Path("data/experiment/rank_head_ensemble_eval.csv")


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


def _predict_checkpoint(
    model_path: Path,
    scaler_path: Path,
    panel: pd.DataFrame,
    device: str,
    amp: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    scaler, feature_cols, seq_len, hidden, dropout = _load_scaler(scaler_path)
    ds = PanelSequenceDataset(panel, scaler, feature_cols, seq_len)
    loader = DataLoader(ds, batch_size=1024, shuffle=False)
    model = RankHeadTCN(n_features=len(feature_cols), hidden=hidden, dropout=dropout).to(device)
    checkpoint = torch.load(model_path, map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    raw_preds = []
    rank_preds = []
    actuals = []
    dates = []
    with torch.no_grad():
        for xb, yb, _, date_ns in loader:
            xb = xb.to(device)
            with torch.amp.autocast("cuda", enabled=amp and device.startswith("cuda")):
                mu, _, rank_score = model(xb)
            raw_preds.append(mu.detach().cpu().numpy().ravel())
            rank_preds.append(rank_score.detach().cpu().numpy().ravel())
            actuals.append(yb.detach().cpu().numpy().ravel())
            dates.append(np.asarray(date_ns).ravel())

    raw = np.concatenate(raw_preds)
    rank = np.concatenate(rank_preds)
    actual = np.concatenate(actuals)
    date_arr = np.concatenate(dates)
    return raw, _center_by_date(rank, date_arr), actual, date_arr


def _score(pred: np.ndarray, actual: np.ndarray, dates: np.ndarray) -> dict:
    metrics = _metrics(pred, actual, dates)
    metrics.update(_selection_metrics(pred, actual, dates))
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--panel", type=Path, default=None)
    ap.add_argument("--val-days", type=int, default=None)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--top-n", type=int, default=0)
    ap.add_argument("--output", type=Path, default=OUT_PATH)
    ap.add_argument("--csv-output", type=Path, default=CSV_PATH)
    args = ap.parse_args()

    device = _resolve_device(args.device)
    use_amp = bool(args.amp and device.startswith("cuda"))
    with args.results.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    rows = list(payload["results"])
    rows = sorted(rows, key=lambda row: float(row.get("selection_score", 0.0)), reverse=True)
    if int(args.top_n) > 0:
        rows = rows[: int(args.top_n)]
    if not rows:
        raise RuntimeError("No result rows available for ensemble evaluation.")

    panel_path = Path(args.panel) if args.panel is not None else Path(payload["panel_path"])
    val_days = int(args.val_days if args.val_days is not None else payload.get("val_days", 252))
    panel = _ensure_panel_schema(read_panel(panel_path))
    panel = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    cutoff, _ = time_split(panel, val_days)
    val_panel = panel[panel["Date"] >= cutoff]

    raw_members = []
    rank_members = []
    actual_ref = None
    dates_ref = None
    member_rows = []
    for row in rows:
        if "scaler_path" not in row:
            raise RuntimeError(f"Result row is missing scaler_path: {row.get('variant')}")
        raw, rank_centered, actual, dates = _predict_checkpoint(
            Path(row["model_path"]),
            Path(row["scaler_path"]),
            val_panel,
            device,
            use_amp,
        )
        if actual_ref is None:
            actual_ref = actual
            dates_ref = dates
        elif not np.array_equal(actual_ref, actual) or not np.array_equal(dates_ref, dates):
            raise RuntimeError("Checkpoint validation samples are not aligned; ensemble would be invalid.")
        raw_members.append(raw)
        rank_members.append(rank_centered)
        member_metrics = _score(rank_centered, actual, dates)
        member_rows.append(
            {
                "variant": row["variant"],
                "selection_score": row.get("selection_score"),
                **{f"member_{k}": v for k, v in member_metrics.items()},
            }
        )

    assert actual_ref is not None and dates_ref is not None
    raw_ensemble = np.mean(np.stack(raw_members, axis=0), axis=0)
    rank_ensemble = np.mean(np.stack(rank_members, axis=0), axis=0)
    metrics = {
        "raw_ensemble": _score(raw_ensemble, actual_ref, dates_ref),
        "rank_centered_ensemble": _score(rank_ensemble, actual_ref, dates_ref),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(member_rows).to_csv(args.csv_output, index=False)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "results": str(args.results),
                "panel_path": str(panel_path),
                "val_days": val_days,
                "device": device,
                "amp": use_amp,
                "member_count": len(rows),
                "members": [row["variant"] for row in rows],
                "metrics": metrics,
                "member_metrics": member_rows,
            },
            f,
            indent=2,
        )

    print("Rank-centered ensemble metrics:")
    for key in [
        "IC_Spearman",
        "Daily_IC_Mean",
        "Selection_Long_Short_Spread_Mean",
        "Selection_Spread_Positive_Rate",
        "pct_bullish_pred",
        "Directional_Accuracy",
    ]:
        print(f"{key}: {metrics['rank_centered_ensemble'][key]:.6f}")
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
