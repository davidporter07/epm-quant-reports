"""dl_rank_head_distill_train.py

Self-distillation for rank-head TCN models.

Uses an existing N-seed ensemble as a teacher to produce soft rank targets,
then retrains new model variants with a blended distillation + original loss.

Goal: compress ensemble-level IC into single-model weights, improving the
504-day robustness gap (walk-forward W1 IC=0.088 is strong, but single seeds
at long horizons drop off; the ensemble is the stabiliser).

Workflow:
  1. Load top-N ensemble checkpoints from a walkforward results JSON.
  2. Run inference on the full training panel -> average ensemble rank scores.
  3. Train new seeds with:
       loss = distill_weight * MSE(student_rank, teacher_rank)
            + (1 - distill_weight) * (nll_weight * NLL + aux_weight * rank_loss)
  4. Evaluate on same validation split; save distilled checkpoints + metrics.

Example:
  python dl_rank_head_distill_train.py ^
    --results data\\experiment\\rank_head_walkforward_3w_5seed.json ^
    --window 1 ^
    --panel data\\experiment\\directional_feature_panel_fmp.parquet ^
    --top-n 3 --distill-weight 0.6 --epochs 8 --val-days 252 ^
    --seeds 20260601,20260602,20260603 ^
    --device auto --amp --pin-memory ^
    --date-grouped-batches --dates-per-batch 64 ^
    --output data\\experiment\\rank_head_distilled.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from deep_learning_model import (
    TARGET_COL,
    PanelSequenceDataset,
    _ensure_panel_schema,
    fit_scaler,
    gaussian_nll,
    read_panel,
    time_split,
)
from dl_rank_head_experiment import (
    RankHeadTCN,
    _center_by_date,
    _evaluate_rank_model,
    _rank_selection_score,
    _selection_metrics,
    _set_seed,
    _train_one,
)
from dl_sign_regularized_experiment import (
    DateGroupedBatchSampler,
    _feature_cols,
    _grouped_aux_loss,
    _metrics,
    _parse_floats,
    _parse_ints,
    _resolve_device,
    _transform_aux_target,
)

DISTILL_DIR = Path("models/experiment/distilled")
OUT_PATH = Path("data/experiment/rank_head_distilled.json")
CSV_PATH = Path("data/experiment/rank_head_distilled.csv")


# ---------------------------------------------------------------------------
# Load ensemble info from results JSON
# ---------------------------------------------------------------------------

def _load_window_rows(results_path: Path, window_idx: int | None, top_n: int) -> list[dict]:
    """Return top-N model rows from the specified window (or best overall)."""
    data = json.loads(results_path.read_text(encoding="utf-8"))

    if "window_rows" in data and isinstance(data["window_rows"], list):
        windows = data["window_rows"]
        if window_idx is not None:
            windows = [w for w in windows if str(w.get("window", "")).lstrip("w").startswith(str(window_idx))]
        if not windows:
            raise ValueError(f"No window {window_idx} in {results_path}")
        rows: list[dict] = []
        for w in windows:
            rows.extend(w.get("results", []))
    elif "results" in data:
        rows = data["results"]
    else:
        raise ValueError(f"Unrecognised results format in {results_path}")

    rows = [r for r in rows if r.get("model_path") and Path(r["model_path"]).exists()]
    rows = sorted(rows, key=lambda r: float(r.get("selection_score", 0.0)), reverse=True)
    if top_n > 0:
        rows = rows[:top_n]
    if not rows:
        raise RuntimeError("No valid checkpoint rows found (check model_path entries exist).")
    return rows


# ---------------------------------------------------------------------------
# Generate teacher soft targets
# ---------------------------------------------------------------------------

def _inference_with_tickers(
    model_path: Path,
    scaler_path: Path,
    panel: pd.DataFrame,
    device: str,
    amp: bool,
) -> pd.DataFrame:
    """Run rank-head inference; return DataFrame with (Ticker, date_ns, rank_score)."""
    with Path(scaler_path).open("r", encoding="utf-8") as f:
        payload = json.load(f)
    scaler = payload["scaler"]
    feature_cols = list(payload["feature_cols"])
    seq_len = int(payload.get("seq_len", 60))
    hidden = int(payload.get("hidden", 64))
    dropout = float(payload.get("dropout", 0.10))

    ds = PanelSequenceDataset(panel, scaler, feature_cols, seq_len)
    loader = DataLoader(ds, batch_size=1024, shuffle=False)
    model = RankHeadTCN(n_features=len(feature_cols), hidden=hidden, dropout=dropout).to(device)
    ckpt = torch.load(model_path, map_location=device, weights_only=True)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    tickers_out: list[str] = []
    date_ns_out: list[int] = []
    rank_out: list[float] = []

    with torch.no_grad():
        for xb, _yb, ticker_strs, date_ns in loader:
            xb = xb.to(device)
            with torch.amp.autocast("cuda", enabled=amp and device.startswith("cuda")):
                _mu, _log_sigma, rank_score = model(xb)
            rs = rank_score.detach().cpu().numpy().ravel()
            if isinstance(ticker_strs, (list, tuple)):
                tickers = list(ticker_strs)
            else:
                tickers = [str(t) for t in ticker_strs]
            dns = np.asarray(date_ns).ravel().tolist()
            tickers_out.extend(tickers)
            date_ns_out.extend([int(d) for d in dns])
            rank_out.extend(rs.tolist())

    return pd.DataFrame({"Ticker": tickers_out, "date_ns": date_ns_out, "rank_score": rank_out})


def _build_teacher_targets(
    rows: list[dict],
    train_panel: pd.DataFrame,
    device: str,
    amp: bool,
) -> pd.DataFrame:
    """Average rank scores from all ensemble members -> teacher DataFrame."""
    print(f"Generating teacher targets from {len(rows)} ensemble members...")
    member_dfs: list[pd.DataFrame] = []
    for i, row in enumerate(rows):
        print(f"  Member {i+1}/{len(rows)}: {Path(row['model_path']).name}")
        df = _inference_with_tickers(
            Path(row["model_path"]),
            Path(row["scaler_path"]),
            train_panel,
            device,
            amp,
        )
        df = df.rename(columns={"rank_score": f"rank_{i}"})
        member_dfs.append(df)

    merged = member_dfs[0]
    for df in member_dfs[1:]:
        merged = merged.merge(df, on=["Ticker", "date_ns"], how="inner")

    rank_cols = [c for c in merged.columns if c.startswith("rank_")]
    merged["teacher_rank"] = merged[rank_cols].mean(axis=1)
    teacher = merged[["Ticker", "date_ns", "teacher_rank"]].copy()
    print(f"Teacher targets: {len(teacher)} samples from {teacher['Ticker'].nunique()} tickers.")
    return teacher


def _dataset_teacher_keys(ds: PanelSequenceDataset) -> set[tuple[str, int]]:
    """Return the teacher lookup keys emitted by a sequence dataset."""
    keys: set[tuple[str, int]] = set()
    samples = getattr(ds, "_samples")
    tickers = getattr(ds, "_tickers")
    dates_ns = getattr(ds, "_dates_ns")
    for tkr_idx, end_i in samples:
        keys.add((str(tickers[int(tkr_idx)]), int(dates_ns[int(tkr_idx)][int(end_i)])))
    return keys


def _check_teacher_coverage(
    ds: PanelSequenceDataset,
    teacher_index: pd.Series,
    min_teacher_coverage: float,
) -> None:
    """Validate teacher coverage before training starts."""
    dataset_keys = _dataset_teacher_keys(ds)
    teacher_keys = set(teacher_index.index)
    matched = len(dataset_keys.intersection(teacher_keys))
    total = len(dataset_keys)
    coverage = matched / total if total else 0.0
    missing = total - matched
    print(f"[Distill] Teacher coverage: {matched}/{total} ({coverage:.1%}).")
    if coverage < float(min_teacher_coverage):
        raise RuntimeError(
            "[Distill] Teacher coverage below threshold: "
            f"matched={matched}, missing={missing}, total={total}, "
            f"coverage={coverage:.1%}, required={float(min_teacher_coverage):.1%}"
        )


# ---------------------------------------------------------------------------
# Distillation training
# ---------------------------------------------------------------------------

def _train_distilled(
    panel_path: Path,
    teacher_df: pd.DataFrame,
    seed: int,
    epochs: int,
    val_days: int,
    lr: float,
    scheduler_name: str,
    device: str,
    amp: bool,
    pin_memory: bool,
    distill_weight: float,
    nll_weight: float,
    corr_weight: float,
    date_grouped_batches: bool,
    dates_per_batch: int,
    extra_features: list[str],
    artifact_dir: Path,
    min_teacher_coverage: float,
    bullish_min: float = 0.30,
    bullish_max: float = 0.70,
    ic_min: float = 0.0,
    daily_ic_min: float = 0.0,
    spread_min: float = 0.0,
    spread_positive_rate_min: float = 0.50,
    target_mode: str = "date_excess",
) -> dict:
    _set_seed(seed)
    device = _resolve_device(device)
    use_amp = bool(amp and device.startswith("cuda"))
    pin = bool(pin_memory and device.startswith("cuda"))

    from dl_rank_head_experiment import _apply_target_mode
    panel = _ensure_panel_schema(read_panel(panel_path))
    panel = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    panel = _apply_target_mode(panel, target_mode)
    cutoff, _ = time_split(panel, val_days)
    train_panel = panel[panel["Date"] < cutoff]
    val_panel = panel[panel["Date"] >= cutoff]

    feature_cols = _feature_cols(panel_path, extra_features)
    scaler = fit_scaler(train_panel, feature_cols)

    # Build teacher lookup: (Ticker, date_ns) -> teacher_rank
    teacher_index = teacher_df.set_index(["Ticker", "date_ns"])["teacher_rank"]

    train_ds = PanelSequenceDataset(train_panel, scaler, feature_cols, 60, seed=seed)
    val_ds = PanelSequenceDataset(val_panel, scaler, feature_cols, 60, seed=seed + 1)
    _check_teacher_coverage(train_ds, teacher_index, min_teacher_coverage)

    loader_kwargs: dict = {"num_workers": 0, "pin_memory": pin}
    if date_grouped_batches:
        batch_sampler = DateGroupedBatchSampler(
            train_ds, seed=seed, min_batch_size=4, dates_per_batch=dates_per_batch
        )
        train_loader = DataLoader(train_ds, batch_sampler=batch_sampler, **loader_kwargs)
    else:
        train_loader = DataLoader(train_ds, batch_size=512, shuffle=True, drop_last=True, **loader_kwargs)
    val_loader = DataLoader(val_ds, batch_size=1024, shuffle=False, **loader_kwargs)

    model = RankHeadTCN(n_features=len(feature_cols), hidden=64, dropout=0.10).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    if scheduler_name == "cosine":
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.05)
    else:
        scheduler = None
    amp_scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    variant = f"distilled_seed{seed}_dw{str(distill_weight).replace('.','p')}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / f"dl_{variant}.pt"
    scaler_path = artifact_dir / f"dl_{variant}_scaler.json"

    best: dict = {"score": -float("inf"), "state": None, "raw_metrics": None, "rank_metrics": None, "rank_centered_metrics": None}

    for epoch in range(1, epochs + 1):
        model.train()
        epoch_losses: list[float] = []
        distill_losses: list[float] = []

        for xb, yb, ticker_strs, date_ns in train_loader:
            xb = xb.to(device, non_blocking=pin)
            yb = yb.to(device, non_blocking=pin)

            # Retrieve teacher rank scores for this batch. Uncovered rows are
            # excluded from the distillation term rather than imputed to zero.
            teacher_ranks: list[float] = []
            teacher_mask: list[bool] = []
            if isinstance(ticker_strs, (list, tuple)):
                tickers = list(ticker_strs)
            else:
                tickers = [str(t) for t in ticker_strs]
            dns_list = np.asarray(date_ns).ravel().tolist()
            for tkr, dns in zip(tickers, dns_list):
                key = (str(tkr), int(dns))
                if key in teacher_index.index:
                    teacher_ranks.append(float(teacher_index.loc[key]))
                    teacher_mask.append(True)
                else:
                    teacher_ranks.append(0.0)
                    teacher_mask.append(False)
            teacher_t = torch.tensor(teacher_ranks, dtype=torch.float32, device=device).unsqueeze(1)
            teacher_mask_t = torch.tensor(teacher_mask, dtype=torch.bool, device=device).unsqueeze(1)

            opt.zero_grad()
            with torch.amp.autocast("cuda", enabled=use_amp):
                mu, log_sigma, rank_score = model(xb)

                # Original losses
                nll = gaussian_nll(mu.float(), log_sigma.float(), yb.float())
                aux_target = _transform_aux_target(yb.float(), "zscore")
                if date_grouped_batches and hasattr(date_ns, "__iter__"):
                    date_ns_t = torch.as_tensor(np.asarray(date_ns).ravel(), device=device)
                    aux_loss = _grouped_aux_loss(
                        rank_score.float(), aux_target, date_ns_t, "corr", 0.05, "zscore", 4
                    )
                else:
                    aux_loss = torch.tensor(0.0, device=device)

                # Distillation loss: student rank vs teacher average.
                if teacher_mask_t.any():
                    distill_loss = F.mse_loss(rank_score.float()[teacher_mask_t], teacher_t.float()[teacher_mask_t])
                else:
                    distill_loss = torch.tensor(0.0, device=device)

                orig_loss = nll_weight * nll + corr_weight * aux_loss
                total_loss = distill_weight * distill_loss + (1.0 - distill_weight) * orig_loss

            amp_scaler.scale(total_loss).backward()
            amp_scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            amp_scaler.step(opt)
            amp_scaler.update()

            epoch_losses.append(float(total_loss.item()))
            distill_losses.append(float(distill_loss.item()))

        if scheduler is not None:
            scheduler.step()

        raw_m, rank_m, rank_c_m = _evaluate_rank_model(model, val_loader, device, use_amp, pin)
        score = _rank_selection_score(
            rank_c_m,
            bullish_min=bullish_min, bullish_max=bullish_max,
            ic_min=ic_min, daily_ic_min=daily_ic_min,
            spread_min=spread_min, spread_positive_rate_min=spread_positive_rate_min,
            hard_gate=False,
        )
        mean_loss = float(np.mean(epoch_losses))
        mean_distill = float(np.mean(distill_losses))
        print(
            f"  [seed={seed}] epoch {epoch}/{epochs}  "
            f"loss={mean_loss:.5f}  distill={mean_distill:.5f}  "
            f"val_score={score:.4f}  "
            f"IC={rank_c_m.get('IC_Spearman', float('nan')):.4f}  "
            f"spread={rank_c_m.get('Selection_Long_Short_Spread_Mean', float('nan')):.5f}"
        )
        if score > best["score"]:
            best["score"] = score
            best["state"] = {k: v.cpu() if hasattr(v, "cpu") else v for k, v in model.state_dict().items()}
            best["raw_metrics"] = raw_m
            best["rank_metrics"] = rank_m
            best["rank_centered_metrics"] = rank_c_m

    # Save best checkpoint
    if best["state"] is not None:
        torch.save({"state_dict": best["state"]}, model_path)
        scaler_payload = {
            "scaler": scaler,
            "feature_cols": feature_cols,
            "seq_len": 60,
            "hidden": 64,
            "dropout": 0.10,
        }
        scaler_path.write_text(json.dumps(scaler_payload, indent=2), encoding="utf-8")

    return {
        "variant": variant,
        "seed": seed,
        "distill_weight": distill_weight,
        "selection_score": best["score"],
        "model_path": str(model_path),
        "scaler_path": str(scaler_path),
        "rank_centered_metrics": best["rank_centered_metrics"],
        "raw_metrics": best["raw_metrics"],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Self-distillation for rank-head TCN")
    ap.add_argument("--results", type=Path, required=True,
                    help="Walkforward results JSON containing ensemble checkpoints")
    ap.add_argument("--window", type=int, default=None,
                    help="Which walk-forward window to use as teacher (default: use all)")
    ap.add_argument("--panel", type=Path, default=None,
                    help="Training panel parquet (default: inferred from results)")
    ap.add_argument("--top-n", type=int, default=3,
                    help="Number of top ensemble members to use as teacher")
    ap.add_argument("--distill-weight", type=float, default=0.60,
                    help="Weight for distillation MSE loss (0=no distill, 1=pure distill)")
    ap.add_argument("--min-teacher-coverage", type=float, default=0.99,
                    help="Minimum teacher coverage required before training starts")
    ap.add_argument("--seeds", type=str, default="20260601,20260602,20260603")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--val-days", type=int, default=252)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--scheduler", default="cosine", choices=["cosine", "none"])
    ap.add_argument("--device", default="auto")
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--pin-memory", action="store_true")
    ap.add_argument("--date-grouped-batches", action="store_true")
    ap.add_argument("--dates-per-batch", type=int, default=64)
    ap.add_argument("--nll-weight", type=float, default=0.5)
    ap.add_argument("--corr-weight", type=float, default=0.05)
    ap.add_argument("--extra-features", type=str, default=None)
    ap.add_argument("--target-mode", default="date_excess", choices=["raw", "date_excess"])
    ap.add_argument("--output", type=Path, default=OUT_PATH)
    ap.add_argument("--artifact-dir", type=Path, default=DISTILL_DIR)
    args = ap.parse_args()

    seeds = _parse_ints(args.seeds)
    extra_features: list[str] = _parse_floats(args.extra_features) if args.extra_features else []  # type: ignore[arg-type]
    # extra_features is a list of strings; reuse _parse_ints logic
    if args.extra_features:
        extra_features = [s.strip() for s in args.extra_features.split(",") if s.strip()]
    else:
        from dl_expanded_feature_seed_grid import DEFAULT_EXTRA_FEATURES
        extra_features = [s.strip() for s in DEFAULT_EXTRA_FEATURES.split(",") if s.strip()]

    device = _resolve_device(args.device)
    print(f"Device: {device}")

    # Load ensemble rows
    rows = _load_window_rows(args.results, args.window, args.top_n)
    print(f"Teacher ensemble: {len(rows)} members")
    for r in rows:
        print(f"  {Path(r['model_path']).name}  score={r.get('selection_score', 'n/a')}")

    # Determine panel path
    panel_path = args.panel
    if panel_path is None:
        from dl_expanded_feature_seed_grid import DEFAULT_PANEL
        panel_path = Path(DEFAULT_PANEL)
    if not panel_path.exists():
        print(f"[ERROR] Panel not found: {panel_path}", file=sys.stderr)
        sys.exit(1)

    # Load panel and split for teacher inference (training split only)
    panel = _ensure_panel_schema(read_panel(panel_path))
    panel = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()].copy()
    cutoff, _ = time_split(panel, args.val_days)
    train_panel = panel[panel["Date"] < cutoff]
    print(f"Training split: {train_panel['Date'].min().date()} to {train_panel['Date'].max().date()} ({len(train_panel)} rows)")

    # Generate teacher targets
    teacher_df = _build_teacher_targets(rows, train_panel, device, args.amp)

    # Train distilled models
    all_results: list[dict] = []
    for seed in seeds:
        print(f"\n=== Distilled training seed={seed} ===")
        result = _train_distilled(
            panel_path=panel_path,
            teacher_df=teacher_df,
            seed=seed,
            epochs=args.epochs,
            val_days=args.val_days,
            lr=args.lr,
            scheduler_name=args.scheduler,
            device=device,
            amp=args.amp,
            pin_memory=args.pin_memory,
            distill_weight=args.distill_weight,
            nll_weight=args.nll_weight,
            corr_weight=args.corr_weight,
            date_grouped_batches=args.date_grouped_batches,
            dates_per_batch=args.dates_per_batch,
            extra_features=extra_features,
            artifact_dir=args.artifact_dir,
            min_teacher_coverage=args.min_teacher_coverage,
            target_mode=args.target_mode,
        )
        all_results.append(result)
        m = result["rank_centered_metrics"] or {}
        print(
            f"  -> score={result['selection_score']:.4f}  "
            f"IC={m.get('IC_Spearman', float('nan')):.4f}  "
            f"DailyIC={m.get('Daily_IC_Mean', float('nan')):.4f}  "
            f"spread={m.get('Selection_Long_Short_Spread_Mean', float('nan')):.5f}"
        )

    # Aggregate
    scores = [r["selection_score"] for r in all_results]
    ics = [r["rank_centered_metrics"].get("IC_Spearman", float("nan")) for r in all_results if r["rank_centered_metrics"]]
    out = {
        "distill_weight": args.distill_weight,
        "teacher_members": len(rows),
        "seeds": seeds,
        "mean_selection_score": float(np.nanmean(scores)),
        "mean_IC_Spearman": float(np.nanmean(ics)),
        "results": all_results,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved results -> {args.output}")

    csv_rows = []
    for r in all_results:
        m = r.get("rank_centered_metrics") or {}
        csv_rows.append({
            "seed": r["seed"],
            "distill_weight": r["distill_weight"],
            "selection_score": r["selection_score"],
            "IC_Spearman": m.get("IC_Spearman"),
            "Daily_IC_Mean": m.get("Daily_IC_Mean"),
            "Selection_Long_Short_Spread_Mean": m.get("Selection_Long_Short_Spread_Mean"),
            "Selection_Spread_Positive_Rate": m.get("Selection_Spread_Positive_Rate"),
        })
    csv_path = args.output.with_suffix(".csv")
    pd.DataFrame(csv_rows).to_csv(csv_path, index=False)
    print(f"Saved CSV    -> {csv_path}")
    print(f"\nMean IC_Spearman: {float(np.nanmean(ics)):.4f}")
    print(f"Mean selection score: {float(np.nanmean(scores)):.4f}")


if __name__ == "__main__":
    main()
