"""dl_experiment_eval.py
Evaluates the two trained experiment variants and produces a clean comparison.

Must be run AFTER both training variants complete.

Usage:
    python dl_experiment_eval.py

Output:
    data/experiment/rsi14_removal_comparison.json
    (also prints a formatted table to stdout)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent))

PANEL_PATH     = Path("data/training_panel.parquet")
EXPERIMENT_DIR = Path("models/experiment")
OUT_PATH       = Path("data/experiment/rsi14_removal_comparison.json")

VARIANTS = {
    "11feat":        "11-feature baseline (full)",
    "10feat_no_rsi": "10-feature (RSI_14 removed)",
}

# Last 252 trading days as test set (matches production backtest default)
TEST_DAYS = 252


def _load_panel() -> pd.DataFrame:
    from deep_learning_model import _ensure_panel_schema, read_panel
    return _ensure_panel_schema(read_panel(PANEL_PATH))


def _get_test_panel(panel: pd.DataFrame, test_days: int) -> pd.DataFrame:
    dates = pd.to_datetime(panel["Date"]).drop_duplicates().sort_values()
    if len(dates) < test_days + 10:
        test_days = max(5, int(len(dates) * 0.2))
    cutoff = dates.iloc[-test_days]
    return panel[panel["Date"] >= cutoff].copy(), cutoff


def evaluate_variant(variant_key: str, panel_test: pd.DataFrame) -> Dict:
    from deep_learning_model import (
        load_model_and_scaler,
        PanelSequenceDataset,
    )

    model_path  = EXPERIMENT_DIR / f"dl_{variant_key}.pt"
    scaler_path = EXPERIMENT_DIR / f"dl_{variant_key}_scaler.json"

    if not model_path.exists():
        return {"error": f"Model not found: {model_path}"}
    if not scaler_path.exists():
        return {"error": f"Scaler not found: {scaler_path}"}

    model, scaler, feature_cols, seq_len = load_model_and_scaler(
        model_path, scaler_path, "cpu"
    )
    model.eval()

    ds = PanelSequenceDataset(panel_test, scaler, feature_cols, seq_len)
    loader = DataLoader(ds, batch_size=1024, shuffle=False)

    preds, actuals, tickers_out, dates_out = [], [], [], []

    with torch.no_grad():
        for xb, yb, tkrs, dates_ns in loader:
            xb = xb.to("cpu")
            mu, _ = model(xb)
            preds.append(mu.cpu().numpy().ravel())
            actuals.append(yb.numpy().ravel())
            tickers_out.extend(tkrs if isinstance(tkrs, list) else list(tkrs))
            dates_out.extend(dates_ns.tolist() if hasattr(dates_ns, 'tolist') else list(dates_ns))

    p = np.concatenate(preds)
    y = np.concatenate(actuals)

    mae      = float(np.mean(np.abs(y - p)))
    rmse     = float(np.sqrt(np.mean((y - p) ** 2)))
    dir_acc  = float(np.mean(np.sign(y) == np.sign(p)))
    corr     = float(np.corrcoef(p, y)[0, 1]) if len(p) > 2 else float("nan")

    # IC (Spearman rank correlation)
    from scipy.stats import spearmanr
    ic_val, ic_pval = spearmanr(p, y)

    # Per-ticker breakdown
    results_df = pd.DataFrame({
        "Predicted": p,
        "Actual":    y,
        "Ticker":    tickers_out[:len(p)],
    })
    per_ticker = {}
    for tkr, grp in results_df.groupby("Ticker"):
        if len(grp) < 5:
            continue
        per_ticker[tkr] = {
            "mae":      round(float(np.mean(np.abs(grp["Actual"] - grp["Predicted"]))), 6),
            "dir_acc":  round(float(np.mean(np.sign(grp["Actual"]) == np.sign(grp["Predicted"]))), 4),
            "corr":     round(float(np.corrcoef(grp["Predicted"], grp["Actual"])[0, 1])
                              if len(grp) > 2 else float("nan"), 4),
            "n":        len(grp),
        }

    return {
        "variant":              variant_key,
        "label":                VARIANTS[variant_key],
        "n_features":           len(feature_cols),
        "feature_cols":         feature_cols,
        "n_samples":            int(len(p)),
        "mae":                  round(mae, 6),
        "rmse":                 round(rmse, 6),
        "directional_accuracy": round(dir_acc, 4),
        "correlation":          round(corr, 4),
        "ic_spearman":          round(float(ic_val), 4),
        "ic_pvalue":            round(float(ic_pval), 4),
        "per_ticker":           per_ticker,
    }


def print_comparison(results: List[Dict]) -> None:
    print("\n" + "="*72)
    print("DL EXPERIMENT: RSI_14 REMOVAL COMPARISON")
    print("="*72)

    # Header
    base = results[0]
    test_n = base.get("n_samples", "?")
    print(f"Test set: last {TEST_DAYS} trading days | N samples: {test_n}\n")

    metrics = [
        ("MAE",                   "mae"),
        ("RMSE",                  "rmse"),
        ("Directional Accuracy",  "directional_accuracy"),
        ("Pearson Correlation",   "correlation"),
        ("IC (Spearman)",         "ic_spearman"),
    ]

    print(f"{'Metric':<26} " + "  ".join(f"{r['label'][:30]:<30}" for r in results))
    print("-" * 90)
    for m_label, m_key in metrics:
        vals = [r.get(m_key, "?") for r in results]
        row  = f"{m_label:<26} "
        for i, (v, r) in enumerate(zip(vals, results)):
            cell = f"{v:.5f}" if isinstance(v, float) else str(v)
            row += f"  {cell:<30}"
        print(row)

    # Delta row (variant B vs variant A)
    if len(results) == 2:
        print()
        print(f"{'Delta (10feat - 11feat)':<26}", end="  ")
        print(" " * 32, end="")  # skip first variant column
        for m_label, m_key in metrics:
            a = results[0].get(m_key)
            b = results[1].get(m_key)
            if isinstance(a, float) and isinstance(b, float):
                delta = b - a
                direction = "better" if (m_key in ("directional_accuracy","correlation","ic_spearman") and delta > 0) \
                            else ("better" if (m_key in ("mae","rmse") and delta < 0) else "worse")
                print(f"\n  {m_label:<24}: {delta:+.5f}  ({direction})", end="")
        print()

    # Per-ticker breakdown
    print("\n--- Per-ticker Directional Accuracy ---")
    tickers = sorted(set(k for r in results for k in r.get("per_ticker", {}).keys()))
    print(f"{'Ticker':<10} " + "  ".join(f"{r['label'][:20]:<20}" for r in results))
    print("-" * 60)
    for tkr in tickers:
        row = f"{tkr:<10} "
        for r in results:
            da = r.get("per_ticker", {}).get(tkr, {}).get("dir_acc", "?")
            row += f"  {str(da):<20}"
        print(row)

    print("\n--- Per-ticker Pearson Correlation ---")
    print(f"{'Ticker':<10} " + "  ".join(f"{r['label'][:20]:<20}" for r in results))
    print("-" * 60)
    for tkr in tickers:
        row = f"{tkr:<10} "
        for r in results:
            c = r.get("per_ticker", {}).get(tkr, {}).get("corr", "?")
            row += f"  {str(c):<20}"
        print(row)

    print("="*72)


def main() -> None:
    panel = _load_panel()
    panel_test, cutoff = _get_test_panel(panel, TEST_DAYS)

    print(f"Test window: {cutoff.date()} -> {panel['Date'].max()}")
    print(f"Test rows  : {len(panel_test)}")

    results = []
    for vkey in VARIANTS:
        print(f"\nEvaluating: {VARIANTS[vkey]} ...")
        r = evaluate_variant(vkey, panel_test)
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            sys.exit(1)
        results.append(r)
        print(f"  MAE={r['mae']:.5f}  DirAcc={r['directional_accuracy']:.4f}  "
              f"Corr={r['correlation']:.4f}  IC={r['ic_spearman']:.4f}")

    print_comparison(results)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"test_cutoff": str(cutoff.date()), "results": results}, f, indent=2)
    print(f"\nResults saved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
