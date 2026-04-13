"""dl_warmstart_eval.py
Evaluates warm-start variants and produces a clean comparison.

Must be run AFTER both warm-start training variants complete.

Shows warm-start results alongside from-scratch reference numbers for context.

Usage:
    python dl_warmstart_eval.py

Output:
    data/experiment/warmstart_comparison.json
    (also prints a formatted table to stdout)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent))

# Use enriched panel for ALL evaluation  11-feat model ignores log_volume col,
# 12-feat model uses it.  Same test window = fair comparison.
PANEL_PATH     = Path("data/experiment/training_panel_with_log_volume.parquet")
EXPERIMENT_DIR = Path("models/experiment")
OUT_PATH       = Path("data/experiment/warmstart_comparison.json")

# Prior from-scratch results for reference column
FROMSCRATCH_PATH = Path("data/experiment/log_volume_addition_comparison.json")

WARM_VARIANTS = {
    "11feat_ws":            "11-feat WS (production baseline)",
    "12feat_log_volume_ws": "12-feat WS (+log_volume)",
}

TEST_DAYS = 252


def _load_panel() -> pd.DataFrame:
    from deep_learning_model import _ensure_panel_schema, read_panel
    return _ensure_panel_schema(read_panel(PANEL_PATH))


def _get_test_panel(panel: pd.DataFrame, test_days: int):
    dates = pd.to_datetime(panel["Date"]).drop_duplicates().sort_values()
    if len(dates) < test_days + 10:
        test_days = max(5, int(len(dates) * 0.2))
    cutoff = dates.iloc[-test_days]
    return panel[panel["Date"] >= cutoff].copy(), cutoff


def evaluate_variant(variant_key: str, panel_test: pd.DataFrame) -> Dict:
    from deep_learning_model import load_model_and_scaler, PanelSequenceDataset
    from scipy.stats import spearmanr

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

    ds     = PanelSequenceDataset(panel_test, scaler, feature_cols, seq_len)
    loader = DataLoader(ds, batch_size=1024, shuffle=False)

    preds, actuals, tickers_out = [], [], []

    with torch.no_grad():
        for xb, yb, tkrs, _ in loader:
            mu, _ = model(xb.to("cpu"))
            preds.append(mu.cpu().numpy().ravel())
            actuals.append(yb.numpy().ravel())
            tickers_out.extend(tkrs if isinstance(tkrs, list) else list(tkrs))

    p = np.concatenate(preds)
    y = np.concatenate(actuals)

    mae      = float(np.mean(np.abs(y - p)))
    rmse     = float(np.sqrt(np.mean((y - p) ** 2)))
    dir_acc  = float(np.mean(np.sign(y) == np.sign(p)))
    corr     = float(np.corrcoef(p, y)[0, 1]) if len(p) > 2 else float("nan")
    ic_val, ic_pval = spearmanr(p, y)
    pred_std = float(np.std(p))
    pct_neg  = float(np.mean(p < 0))

    results_df = pd.DataFrame({
        "Predicted": p, "Actual": y,
        "Ticker":    tickers_out[:len(p)],
    })
    per_ticker = {}
    for tkr, grp in results_df.groupby("Ticker"):
        if len(grp) < 5:
            continue
        c = float(np.corrcoef(grp["Predicted"], grp["Actual"])[0, 1]) if len(grp) > 2 else float("nan")
        ic_t, _ = spearmanr(grp["Predicted"], grp["Actual"])
        per_ticker[tkr] = {
            "n":       len(grp),
            "mae":     round(float(np.mean(np.abs(grp["Actual"] - grp["Predicted"]))), 6),
            "dir_acc": round(float(np.mean(np.sign(grp["Actual"]) == np.sign(grp["Predicted"]))), 4),
            "corr":    round(c, 4),
            "ic":      round(float(ic_t), 4),
        }

    return {
        "variant":              variant_key,
        "label":                WARM_VARIANTS[variant_key],
        "n_features":           len(feature_cols),
        "n_samples":            int(len(p)),
        "mae":                  round(mae, 6),
        "rmse":                 round(rmse, 6),
        "directional_accuracy": round(dir_acc, 4),
        "correlation":          round(corr, 4),
        "ic_spearman":          round(float(ic_val), 4),
        "ic_pvalue":            round(float(ic_pval), 4),
        "pred_std":             round(pred_std, 6),
        "pct_neg_predictions":  round(pct_neg, 4),
        "per_ticker":           per_ticker,
    }


def load_fromscratch_ref() -> List[Dict]:
    """Load prior from-scratch results for reference comparison.

    Handles both list-under-"results" format and flat-dict format (older files).
    """
    if not FROMSCRATCH_PATH.exists():
        return []
    with open(FROMSCRATCH_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "results" in data and isinstance(data["results"], list):
        return data["results"]
    # Flat dict format: keys are variant names, values are result dicts
    if isinstance(data, dict) and any(isinstance(v, dict) for v in data.values()):
        return [{"variant": k, **v} for k, v in data.items() if isinstance(v, dict)]
    return []


def print_comparison(ws_results: List[Dict], ref_results: List[Dict]) -> None:
    print("\n" + "="*80)
    print("DL WARM-START EXPERIMENT: 11-feat baseline vs 12-feat (+log_volume)")
    print("="*80)

    n = ws_results[0].get("n_samples", "?")
    print(f"Test set: last {TEST_DAYS} trading days | N samples: {n}")
    print(f"Training: warm-start from production checkpoint (5 epochs, LR*0.2)\n")

    metrics = [
        ("MAE",                   "mae",                  "lower=better"),
        ("RMSE",                  "rmse",                 "lower=better"),
        ("Pearson Correlation",   "correlation",          "higher=better"),
        ("IC (Spearman)",         "ic_spearman",          "higher=better"),
        ("IC p-value",            "ic_pvalue",            "lower=better"),
        ("Pred StdDev",           "pred_std",             "higher=more spread"),
        ("Pct Neg Predictions",   "pct_neg_predictions",  "~0.42 = calibrated"),
        ("Directional Accuracy",  "directional_accuracy", "secondary"),
    ]

    # Column headers
    col1 = ws_results[0]["label"][:28]
    col2 = ws_results[1]["label"][:28]
    print(f"{'Metric':<26}  {'Direction':<22}  {col1:<28}  {col2:<28}  {'Delta':>10}")
    print("-" * 100)

    for m_label, m_key, direction in metrics:
        v1 = ws_results[0].get(m_key, "?")
        v2 = ws_results[1].get(m_key, "?")
        if isinstance(v1, float) and isinstance(v2, float):
            delta = v2 - v1
            if m_key in ("correlation", "ic_spearman", "directional_accuracy"):
                sign = "+" if delta > 0 else ""
                better = "(better)" if delta > 0 else "(worse)"
            elif m_key in ("mae", "rmse", "ic_pvalue"):
                sign = "+" if delta > 0 else ""
                better = "(worse)" if delta > 0 else "(better)"
            else:
                sign = "+" if delta > 0 else ""
                better = ""
            print(f"  {m_label:<24}  {direction:<22}  {v1:<28.5f}  {v2:<28.5f}  {sign}{delta:+.5f} {better}")
        else:
            print(f"  {m_label:<24}  {direction:<22}  {str(v1):<28}  {str(v2):<28}")

    # --- From-scratch reference ---
    if ref_results:
        print(f"\n{'--- From-scratch reference (same metric order)'}")
        ref_map = {r["variant"]: r for r in ref_results}
        r11 = ref_map.get("11feat", {})
        r12 = ref_map.get("12feat_log_volume", {})
        if r11 and r12:
            print(f"  {'Metric':<24}  {'11feat (scratch)':<28}  {'12feat+logvol (scratch)':<28}")
            print("  " + "-"*82)
            for m_label, m_key, _ in metrics:
                v1 = r11.get(m_key, "?")
                v2 = r12.get(m_key, "?")
                f1 = f"{v1:.5f}" if isinstance(v1, float) else str(v1)
                f2 = f"{v2:.5f}" if isinstance(v2, float) else str(v2)
                print(f"  {m_label:<24}  {f1:<28}  {f2:<28}")

    # --- Per-ticker ---
    print("\n--- Per-ticker Pearson Correlation (warm-start) ---")
    tickers = sorted(set(k for r in ws_results for k in r.get("per_ticker", {}).keys()))
    print(f"  {'Ticker':<10}  {ws_results[0]['label'][:20]:<22}  {ws_results[1]['label'][:20]:<22}  {'Delta':>8}")
    print("  " + "-"*66)
    for tkr in tickers:
        c1 = ws_results[0].get("per_ticker", {}).get(tkr, {}).get("corr", float("nan"))
        c2 = ws_results[1].get("per_ticker", {}).get(tkr, {}).get("corr", float("nan"))
        if isinstance(c1, float) and isinstance(c2, float) and not (np.isnan(c1) or np.isnan(c2)):
            delta = c2 - c1
            sign = "+" if delta >= 0 else ""
            print(f"  {tkr:<10}  {c1:<22.4f}  {c2:<22.4f}  {sign}{delta:+.4f}")
        else:
            print(f"  {tkr:<10}  {str(c1):<22}  {str(c2):<22}")

    print("\n--- Per-ticker IC (Spearman, warm-start) ---")
    print(f"  {'Ticker':<10}  {ws_results[0]['label'][:20]:<22}  {ws_results[1]['label'][:20]:<22}  {'Delta':>8}")
    print("  " + "-"*66)
    for tkr in tickers:
        ic1 = ws_results[0].get("per_ticker", {}).get(tkr, {}).get("ic", float("nan"))
        ic2 = ws_results[1].get("per_ticker", {}).get(tkr, {}).get("ic", float("nan"))
        if isinstance(ic1, float) and isinstance(ic2, float) and not (np.isnan(ic1) or np.isnan(ic2)):
            delta = ic2 - ic1
            sign = "+" if delta >= 0 else ""
            print(f"  {tkr:<10}  {ic1:<22.4f}  {ic2:<22.4f}  {sign}{delta:+.4f}")
        else:
            print(f"  {tkr:<10}  {str(ic1):<22}  {str(ic2):<22}")

    print("="*80)


def main() -> None:
    panel = _load_panel()
    panel_test, cutoff = _get_test_panel(panel, TEST_DAYS)
    print(f"Test window: {cutoff.date()} -> {pd.to_datetime(panel['Date']).max().date()}")
    print(f"Test rows  : {len(panel_test)}")

    ws_results = []
    for vkey in WARM_VARIANTS:
        print(f"\nEvaluating: {WARM_VARIANTS[vkey]} ...")
        r = evaluate_variant(vkey, panel_test)
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            sys.exit(1)
        ws_results.append(r)
        print(f"  MAE={r['mae']:.5f}  Corr={r['correlation']:.4f}  "
              f"IC={r['ic_spearman']:.4f}  PredStd={r['pred_std']:.5f}  "
              f"PctNeg={r['pct_neg_predictions']:.3f}")

    ref_results = load_fromscratch_ref()

    print_comparison(ws_results, ref_results)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "test_cutoff": str(cutoff.date()),
            "test_rows":   len(panel_test),
            "protocol":    "warm-start from production checkpoint, 5 epochs, LR*0.2",
            "results":     ws_results,
            "fromscratch_reference": ref_results,
        }, f, indent=2)
    print(f"\nResults saved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
