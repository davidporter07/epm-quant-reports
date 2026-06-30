"""dl_walkforward_backtest.py

Honest walk-forward backtest of the PRODUCTION DL model (the TCNForecaster the
forecasting page scores), built to answer the one question the live log can't yet:
is DeepLearning's directional edge real, or is it 3 lucky coin flips?

WHY
---
The live leaderboard has only ~3 non-overlapping 21-day windows per ticker, so even
a 67% hit-rate has a Wilson CI of ~[21%, 94%] — statistically a coin flip (Lever 3
makes that visible). A backfill can't fix it for DL without look-ahead. The rigorous
fix is a walk-forward retrain: step through history 21 trading days at a time, and at
each step train the model on ONLY the data whose labels had matured by that date,
then forecast that date. Every window is non-overlapping BY CONSTRUCTION, so a
multi-year run yields hundreds of genuinely independent outcomes.

HONESTY
-------
At decision date t the training panel is restricted to rows whose 21-day forward
return had already matured (Date <= t - 21 trading days). Inference uses only the
feature window ending at t. The realized return at t is attached AFTER inference,
for scoring only. No future information ever reaches a forecast.

By default the run is warm-start chained (cold once at the first step, then a short
fine-tune per step) — this faithfully replays how the live model actually behaves
(a daily 2-epoch warm-start). Pass --from-scratch-each for the stricter variant
where every step trains from random init (purest, but slower and not how prod runs).

This is an OFFLINE research artifact. It writes its OWN results
(data/dl_walkforward_results.csv) and never touches the live prediction_log — the
walk-forward DL track is labeled "DeepLearning_WF" so it can never be confused with
the live point-in-time log.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import torch

from deep_learning_model import (
    FEATURE_COLS_DEFAULT,
    MAG7_DEFAULT,
    TARGET_COL,
    TrainConfig,
    _ensure_panel_schema,
    apply_scaler,
    load_model_and_scaler,
    read_panel,
    train_model,
)
from model_leaderboard import _wilson_interval

HORIZON = 21
PANEL_PATH_DEFAULT = Path("data") / "training_panel.parquet"
WF_DIR = Path("models") / "experiment" / "dl_walkforward"
RESULTS_CSV = Path("data") / "dl_walkforward_results.csv"
SUMMARY_CSV = Path("data") / "dl_walkforward_summary.csv"
SUMMARY_JSON = Path("data") / "dl_walkforward_summary.json"


def _all_dates(panel: pd.DataFrame) -> List[pd.Timestamp]:
    d = pd.to_datetime(panel["Date"], errors="coerce").dropna().drop_duplicates().sort_values()
    return [pd.Timestamp(x) for x in d.tolist()]


def _decision_dates(panel: pd.DataFrame, start: Optional[str], end: Optional[str],
                    cycles: int, step: int) -> List[pd.Timestamp]:
    """Labeled dates spaced `step` trading days apart (non-overlapping at step=HORIZON)."""
    labeled = panel[pd.to_numeric(panel[TARGET_COL], errors="coerce").notna()]
    dates = _all_dates(labeled)
    if start:
        dates = [d for d in dates if d >= pd.Timestamp(start)]
    if end:
        dates = [d for d in dates if d <= pd.Timestamp(end)]
    if not dates:
        raise RuntimeError("No labeled decision dates after filters.")
    sel = dates[:: max(1, int(step))]
    if cycles > 0:
        sel = sel[-int(cycles):]
    return sel


@torch.no_grad()
def _infer_mu_asof(model, scaler, feature_cols, seq_len, panel, decision_date, tickers, device):
    """Production-faithful inference: the seq_len feature window ENDING at decision_date."""
    model.eval()
    out: Dict[str, float] = {}
    for t in tickers:
        g = panel[(panel["Ticker"] == t) & (panel["Date"] <= decision_date)].sort_values("Date")
        if len(g) < seq_len:
            continue
        tail = g.iloc[-seq_len:]
        if pd.Timestamp(tail["Date"].iloc[-1]).normalize() != pd.Timestamp(decision_date).normalize():
            continue  # no bar exactly on the decision date for this ticker
        X = apply_scaler(tail, scaler, feature_cols)
        if not np.isfinite(X).all():
            continue
        xb = torch.from_numpy(X).unsqueeze(0).to(device)
        mu, _ = model(xb)
        out[t] = float(mu.cpu().numpy().ravel()[0])
    return out


def run_walkforward(panel_path: Path, start: Optional[str], end: Optional[str], cycles: int,
                    step: int, tickers: List[str], device: str, first_epochs: int,
                    warm_epochs: int, from_scratch_each: bool, seq_len: int) -> pd.DataFrame:
    panel = _ensure_panel_schema(read_panel(panel_path))
    panel["_target"] = pd.to_numeric(panel[TARGET_COL], errors="coerce")
    all_dates = _all_dates(panel)
    decisions = _decision_dates(panel, start, end, cycles, step)
    print(f" Walk-forward: {len(decisions)} decision dates, step={step}TD, "
          f"{'from-scratch each' if from_scratch_each else 'warm-start chained'} ({first_epochs}/{warm_epochs} ep)")

    if WF_DIR.exists():
        shutil.rmtree(WF_DIR)
    WF_DIR.mkdir(parents=True, exist_ok=True)
    model_path = WF_DIR / "wf_tcn.pt"
    scaler_path = WF_DIR / "wf_scaler.json"
    panel_tmp = WF_DIR / "wf_train_panel.parquet"

    rows = []
    have_ckpt = False
    for i, t in enumerate(decisions, 1):
        pos = all_dates.index(pd.Timestamp(t))
        cutoff_pos = pos - HORIZON
        if cutoff_pos <= seq_len:
            print(f"  [{i}/{len(decisions)}] {t.date()}: too little matured history; skipping.")
            continue
        matured = all_dates[cutoff_pos]

        train_panel = panel[(panel["Date"] <= matured) & panel["_target"].notna()].copy()
        if train_panel["Date"].nunique() < seq_len + 5:
            print(f"  [{i}/{len(decisions)}] {t.date()}: train panel too short; skipping.")
            continue
        train_panel.drop(columns=["_target"]).to_parquet(panel_tmp, index=False)

        warm = have_ckpt and not from_scratch_each
        epochs = warm_epochs if warm else first_epochs
        cfg = TrainConfig(seq_len=seq_len, epochs=epochs, batch_size=256, val_days=126, patience=2)
        try:
            train_model(panel_path=panel_tmp, model_path=model_path, scaler_path=scaler_path,
                        feature_cols=FEATURE_COLS_DEFAULT, cfg=cfg, device=device, warm_start=warm)
            have_ckpt = True
        except Exception as e:
            print(f"  [{i}/{len(decisions)}] {t.date()}: train failed ({e}); skipping.")
            continue

        model, scaler, fcols, sl = load_model_and_scaler(model_path, scaler_path, device)
        mus = _infer_mu_asof(model, scaler, fcols, sl, panel, t, tickers, device)

        for tk, mu in mus.items():
            realized = panel.loc[(panel["Ticker"] == tk) & (panel["Date"] == t), "_target"]
            if realized.empty or not np.isfinite(realized.iloc[0]):
                continue
            r = float(realized.iloc[0])
            rows.append({
                "RunDate": t.date().isoformat(),
                "Ticker": tk,
                "Model": "DeepLearning_WF",
                "Horizon": HORIZON,
                "ForecastPct": mu * 100.0,
                "RealizedPct": r * 100.0,
                "TrainLabelThrough": matured.date().isoformat(),
                "Source": "walkforward",
            })
        print(f"  [{i}/{len(decisions)}] {t.date()}: trained<= {matured.date()}, "
              f"forecast {len(mus)} tickers.")

    res = pd.DataFrame(rows)
    if not res.empty:
        RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
        res.to_csv(RESULTS_CSV, index=False)
        print(f" Wrote {len(res)} walk-forward forecasts -> {RESULTS_CSV}")
    return res


def score_walkforward(res: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker honest metrics. Windows are already non-overlapping (step=HORIZON),
    so every observation is independent — Dir here IS the independent hit-rate."""
    out = []

    def _block(g: pd.DataFrame, ticker: str) -> dict:
        err = g["RealizedPct"] - g["ForecastPct"]
        n = int(len(g))
        dir_acc = float(np.mean(np.sign(g["RealizedPct"]) == np.sign(g["ForecastPct"]))) if n else float("nan")
        succ = int(round(dir_acc * n)) if n else 0
        lo, hi = _wilson_interval(succ, n)
        corr = float(g[["RealizedPct", "ForecastPct"]].corr().iloc[0, 1]) if n > 2 else float("nan")
        return {
            "Ticker": ticker, "N_Independent": float(n),
            "MAE": float(np.mean(np.abs(err))) if n else float("nan"),
            "Directional_Accuracy": dir_acc,
            "Dir_CI_Lower": lo, "Dir_CI_Upper": hi,
            "Significant": float((lo > 0.5) or (hi < 0.5)) if n else float("nan"),
            "Corr": corr,
            "Avg_Forecast": float(np.mean(g["ForecastPct"])) if n else float("nan"),
            "Avg_Realized": float(np.mean(g["RealizedPct"])) if n else float("nan"),
        }

    for tk, g in res.groupby("Ticker"):
        out.append(_block(g, tk))
    out.append(_block(res, "ALL"))  # pooled across tickers
    summary = pd.DataFrame(out).sort_values("Ticker").reset_index(drop=True)

    SUMMARY_CSV.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_CSV, index=False)
    allrow = summary[summary["Ticker"] == "ALL"].iloc[0]
    payload = {
        "model": "DeepLearning_WF",
        "computed": pd.Timestamp.today().date().isoformat(),
        "n_independent_pooled": int(allrow["N_Independent"]),
        "pooled_directional_accuracy": float(allrow["Directional_Accuracy"]),
        "pooled_dir_ci": [float(allrow["Dir_CI_Lower"]), float(allrow["Dir_CI_Upper"])],
        "pooled_significant": bool(allrow["Significant"]),
        "per_ticker": summary[summary["Ticker"] != "ALL"].to_dict(orient="records"),
    }
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2))
    print(f" Wrote walk-forward summary -> {SUMMARY_CSV} / {SUMMARY_JSON}")
    print(f"   Pooled: N={payload['n_independent_pooled']} indep, "
          f"Dir={payload['pooled_directional_accuracy']:.1%} "
          f"CI[{payload['pooled_dir_ci'][0]:.0%},{payload['pooled_dir_ci'][1]:.0%}] "
          f"significant={payload['pooled_significant']}")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panel", type=Path, default=PANEL_PATH_DEFAULT)
    ap.add_argument("--start-date", default=None)
    ap.add_argument("--end-date", default=None)
    ap.add_argument("--cycles", type=int, default=0, help="0 = all available; else keep the most recent N steps")
    ap.add_argument("--step-days", type=int, default=HORIZON, help="Trading-day spacing (HORIZON = non-overlapping)")
    ap.add_argument("--tickers", default=",".join(MAG7_DEFAULT))
    ap.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    ap.add_argument("--first-epochs", type=int, default=6)
    ap.add_argument("--warm-epochs", type=int, default=2)
    ap.add_argument("--from-scratch-each", action="store_true")
    ap.add_argument("--seq-len", type=int, default=60)
    args = ap.parse_args()

    device = args.device
    if device == "cuda" and not torch.cuda.is_available():
        print(" CUDA requested but unavailable; using CPU.")
        device = "cpu"

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    res = run_walkforward(args.panel, args.start_date, args.end_date, args.cycles, args.step_days,
                          tickers, device, args.first_epochs, args.warm_epochs,
                          args.from_scratch_each, args.seq_len)
    if res.empty:
        print(" No walk-forward forecasts produced.")
        return
    score_walkforward(res)


if __name__ == "__main__":
    main()
