"""Walk-forward validation for rank-head selection ensembles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from deep_learning_model import TARGET_COL, _ensure_panel_schema, read_panel, time_split
from dl_directional_loss_experiment import _parse_features
from dl_expanded_feature_seed_grid import DEFAULT_EXTRA_FEATURES, DEFAULT_PANEL
from dl_rank_head_ensemble_eval import _predict_checkpoint, _score
from dl_rank_head_experiment import _train_one
from dl_sign_regularized_experiment import _parse_floats, _parse_ints, _resolve_device

OUT_PATH = Path("data/experiment/rank_head_walkforward.json")
CSV_PATH = Path("data/experiment/rank_head_walkforward.csv")
WINDOW_PANEL_DIR = Path("data/experiment/walkforward_panels")


def _window_end_dates(panel: pd.DataFrame, val_days: int, windows: int) -> list[pd.Timestamp]:
    dates = pd.to_datetime(panel["Date"]).drop_duplicates().sort_values().reset_index(drop=True)
    out: list[pd.Timestamp] = []
    for window_idx in range(int(windows)):
        end_pos = len(dates) - 1 - window_idx * int(val_days)
        start_pos = end_pos - int(val_days) + 1
        if start_pos <= 0:
            break
        out.append(pd.Timestamp(dates.iloc[end_pos]))
    return out


def _write_window_panel(panel: pd.DataFrame, end_date: pd.Timestamp, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    window_panel = panel[panel["Date"] <= end_date].copy()
    window_panel.to_parquet(path, index=False)
    return path


def _ensemble_metrics(
    rows: list[dict],
    panel: pd.DataFrame,
    val_days: int,
    top_n: int,
    device: str,
    amp: bool,
) -> dict:
    rows = sorted(rows, key=lambda row: float(row.get("selection_score", 0.0)), reverse=True)
    if int(top_n) > 0:
        rows = rows[: int(top_n)]
    if not rows:
        raise RuntimeError("No model rows available for ensemble metrics.")

    cutoff, _ = time_split(panel, val_days)
    val_panel = panel[panel["Date"] >= cutoff]
    rank_members = []
    raw_members = []
    actual_ref = None
    dates_ref = None
    member_metrics = []
    for row in rows:
        raw, rank_centered, actual, dates = _predict_checkpoint(
            Path(row["model_path"]),
            Path(row["scaler_path"]),
            val_panel,
            device,
            amp,
        )
        if actual_ref is None:
            actual_ref = actual
            dates_ref = dates
        elif not np.array_equal(actual_ref, actual) or not np.array_equal(dates_ref, dates):
            raise RuntimeError("Walk-forward ensemble members are not sample-aligned.")
        raw_members.append(raw)
        rank_members.append(rank_centered)
        member_metrics.append(
            {
                "variant": row["variant"],
                "selection_score": row.get("selection_score"),
                **_score(rank_centered, actual, dates),
            }
        )

    assert actual_ref is not None and dates_ref is not None
    raw_ensemble = np.mean(np.stack(raw_members, axis=0), axis=0)
    rank_ensemble = np.mean(np.stack(rank_members, axis=0), axis=0)
    return {
        "member_count": len(rows),
        "members": [row["variant"] for row in rows],
        "raw_ensemble": _score(raw_ensemble, actual_ref, dates_ref),
        "rank_centered_ensemble": _score(rank_ensemble, actual_ref, dates_ref),
        "member_metrics": member_metrics,
    }


def _flatten_window(row: dict) -> dict:
    metrics = row["ensemble"]["rank_centered_ensemble"]
    return {
        "window": row["window"],
        "end_date": row["end_date"],
        "start_date": row["start_date"],
        "member_count": row["ensemble"]["member_count"],
        "IC_Spearman": metrics["IC_Spearman"],
        "Daily_IC_Mean": metrics["Daily_IC_Mean"],
        "Daily_IC_Positive_Rate": metrics["Daily_IC_Positive_Rate"],
        "Directional_Accuracy": metrics["Directional_Accuracy"],
        "pct_bullish_pred": metrics["pct_bullish_pred"],
        "Selection_Long_Short_Spread_Mean": metrics["Selection_Long_Short_Spread_Mean"],
        "Selection_Spread_Positive_Rate": metrics["Selection_Spread_Positive_Rate"],
        "Selection_Long_Hit_Rate": metrics["Selection_Long_Hit_Rate"],
        "Selection_Short_Hit_Rate": metrics["Selection_Short_Hit_Rate"],
        "N": metrics["N"],
        "Daily_Count": metrics["Daily_Count"],
    }


def _aggregate(flat_rows: list[dict]) -> dict:
    df = pd.DataFrame(flat_rows)
    metrics = [
        "IC_Spearman",
        "Daily_IC_Mean",
        "Daily_IC_Positive_Rate",
        "Directional_Accuracy",
        "pct_bullish_pred",
        "Selection_Long_Short_Spread_Mean",
        "Selection_Spread_Positive_Rate",
        "Selection_Long_Hit_Rate",
        "Selection_Short_Hit_Rate",
    ]
    out = {}
    for metric in metrics:
        vals = pd.to_numeric(df[metric], errors="coerce").dropna()
        out[metric] = {
            "mean": float(vals.mean()) if not vals.empty else float("nan"),
            "min": float(vals.min()) if not vals.empty else float("nan"),
            "max": float(vals.max()) if not vals.empty else float("nan"),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--extra-features", default=DEFAULT_EXTRA_FEATURES)
    ap.add_argument("--windows", type=int, default=3)
    ap.add_argument("--val-days", type=int, default=252)
    ap.add_argument("--top-n", type=int, default=3)
    ap.add_argument("--seeds", default="20260505,20260506,20260507")
    ap.add_argument("--corr-weight", type=float, default=0.05)
    ap.add_argument("--rank-weight", type=float, default=0.005)
    ap.add_argument("--nll-weight", type=float, default=0.5)
    ap.add_argument("--aux-target-transform", choices=["raw", "demean", "zscore"], default="zscore")
    ap.add_argument("--rank-temperature", type=float, default=0.02)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--scheduler", choices=["cosine", "onecycle", "none"], default="cosine")
    ap.add_argument("--max-lr", type=float, default=None)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--pin-memory", action="store_true")
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument("--date-grouped-batches", action="store_true")
    ap.add_argument("--min-date-batch-size", type=int, default=2)
    ap.add_argument("--dates-per-batch", type=int, default=64)
    ap.add_argument("--daily-ic-min", type=float, default=-0.02)
    ap.add_argument("--spread-min", type=float, default=0.0)
    ap.add_argument("--spread-positive-rate-min", type=float, default=0.55)
    ap.add_argument("--output", type=Path, default=OUT_PATH)
    ap.add_argument("--csv-output", type=Path, default=CSV_PATH)
    args = ap.parse_args()

    device = _resolve_device(args.device)
    use_amp = bool(args.amp and device.startswith("cuda"))
    panel = _ensure_panel_schema(read_panel(args.panel))
    panel = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    extra_features = _parse_features(args.extra_features)
    end_dates = _window_end_dates(panel, args.val_days, args.windows)
    if not end_dates:
        raise RuntimeError("No walk-forward windows available for this panel and val-days setting.")

    window_rows = []
    for window_idx, end_date in enumerate(end_dates, start=1):
        window_name = f"w{window_idx}_{end_date.strftime('%Y%m%d')}"
        panel_path = WINDOW_PANEL_DIR / f"rank_head_{window_name}.parquet"
        _write_window_panel(panel, end_date, panel_path)
        window_panel = _ensure_panel_schema(read_panel(panel_path))
        cutoff, _ = time_split(window_panel, args.val_days)
        print(f"\n=== walk-forward {window_name}: train < {cutoff.date()} validate {cutoff.date()}..{end_date.date()} ===")

        results = []
        for seed in _parse_ints(args.seeds):
            results.append(
                _train_one(
                    panel_path=panel_path,
                    extra_features=extra_features,
                    seed=seed,
                    epochs=int(args.epochs),
                    batch_size=int(args.batch_size),
                    val_days=int(args.val_days),
                    lr=float(args.lr),
                    scheduler_name=args.scheduler,
                    max_lr=args.max_lr,
                    onecycle_pct_start=0.45,
                    onecycle_div_factor=10.0,
                    onecycle_final_div_factor=1000.0,
                    device=device,
                    amp=use_amp,
                    num_workers=int(args.num_workers),
                    pin_memory=bool(args.pin_memory),
                    nll_weight=float(args.nll_weight),
                    corr_weight=float(args.corr_weight),
                    rank_weight=float(args.rank_weight),
                    aux_target_transform=args.aux_target_transform,
                    rank_temperature=float(args.rank_temperature),
                    date_grouped_batches=bool(args.date_grouped_batches),
                    min_date_batch_size=int(args.min_date_batch_size),
                    dates_per_batch=int(args.dates_per_batch),
                    bullish_min=0.35,
                    bullish_max=0.75,
                    ic_min=0.0,
                    daily_ic_min=float(args.daily_ic_min),
                    spread_min=float(args.spread_min),
                    spread_positive_rate_min=float(args.spread_positive_rate_min),
                    selection_score_mode="selection",
                    direction_min=0.5085,
                    hard_gate=True,
                    daily_ic_weight=0.75,
                )
            )

        ensemble = _ensemble_metrics(
            results,
            window_panel,
            int(args.val_days),
            int(args.top_n),
            device,
            use_amp,
        )
        window_rows.append(
            {
                "window": window_name,
                "start_date": str(pd.Timestamp(cutoff).date()),
                "end_date": str(end_date.date()),
                "panel_path": str(panel_path),
                "results": results,
                "ensemble": ensemble,
            }
        )

    flat_rows = [_flatten_window(row) for row in window_rows]
    aggregate = _aggregate(flat_rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(flat_rows).to_csv(args.csv_output, index=False)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "panel_path": str(args.panel),
                "extra_features": extra_features,
                "windows": int(args.windows),
                "val_days": int(args.val_days),
                "top_n": int(args.top_n),
                "seeds": _parse_ints(args.seeds),
                "corr_weight": float(args.corr_weight),
                "rank_weight": float(args.rank_weight),
                "nll_weight": float(args.nll_weight),
                "aggregate": aggregate,
                "flat_rows": flat_rows,
                "window_rows": window_rows,
            },
            f,
            indent=2,
        )

    print("\nWalk-forward rank-centered ensemble:")
    print(pd.DataFrame(flat_rows).to_string(index=False))
    print(f"\nSaved -> {args.output}")


if __name__ == "__main__":
    main()
