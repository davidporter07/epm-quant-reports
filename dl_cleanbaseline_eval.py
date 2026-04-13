"""dl_cleanbaseline_eval.py
Experiment 4: Combined clean-baseline warm-start comparison.

Compares:
  A) 10-feat warm-start (no RSI_14)  clean calibration baseline
  B) 11-feat warm-start (no RSI_14 + log_volume)  tests log_volume in clean setting

This is the definitive test: does log_volume add value when RSI_14's bullish bias
is already removed?

Must be run AFTER both training variants complete:
    python dl_warmstart_train.py --variant 10feat_no_rsi_ws
    python dl_warmstart_train.py --variant 11feat_clean_logvol_ws

Output:
    data/experiment/combined_cleanbaseline_comparison.json
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

PANEL_PATH     = Path("data/experiment/training_panel_with_log_volume.parquet")
EXPERIMENT_DIR = Path("models/experiment")
OUT_PATH       = Path("data/experiment/combined_cleanbaseline_comparison.json")

VARIANTS = {
    "10feat_no_rsi_ws":       "10-feat WS (no RSI_14  clean baseline)",
    "11feat_clean_logvol_ws": "11-feat WS (no RSI_14 + log_volume)",
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
        "pred_std":             round(pred_std, 6),
        "pct_neg_predictions":  round(pct_neg, 4),
        "per_ticker":           per_ticker,
    }


def print_comparison(results: List[Dict]) -> None:
    a, b = results[0], results[1]
    print("\n" + "="*80)
    print("DL EXPERIMENT 4: COMBINED CLEAN-BASELINE WARM-START")
    print("10-feat (no RSI_14)  vs  11-feat (no RSI_14 + log_volume)")
    print("="*80)
    print(f"Test set: last {TEST_DAYS} trading days | N samples: {a.get('n_samples','?')}")
    print(f"Protocol: partial warm-start from production checkpoint, 5 epochs, LR*0.2\n")

    metrics = [
        ("MAE",                   "mae",                  False),
        ("RMSE",                  "rmse",                 False),
        ("Pearson Correlation",   "correlation",          True),
        ("IC (Spearman)",         "ic_spearman",          True),
        ("IC p-value",            "ic_pvalue",            False),
        ("Pred StdDev",           "pred_std",             None),
        ("Pct Neg Predictions",   "pct_neg_predictions",  None),
        ("Directional Accuracy",  "directional_accuracy", None),
    ]

    print(f"{'Metric':<26}  {'10-feat WS (no RSI)':<28}  {'11-feat WS (+logvol)':<28}  Delta")
    print("-" * 96)
    for m_label, m_key, higher_better in metrics:
        v1 = a.get(m_key, "?")
        v2 = b.get(m_key, "?")
        if isinstance(v1, float) and isinstance(v2, float):
            delta = v2 - v1
            sign = "+" if delta >= 0 else ""
            if higher_better is True:
                better = "(better)" if delta > 0 else ("(worse)" if delta < 0 else "")
            elif higher_better is False:
                better = "(better)" if delta < 0 else ("(worse)" if delta > 0 else "")
            else:
                better = ""
            print(f"  {m_label:<24}  {v1:<28.5f}  {v2:<28.5f}  {sign}{delta:+.5f} {better}")
        else:
            print(f"  {m_label:<24}  {str(v1):<28}  {str(v2):<28}")

    print("\n--- Per-ticker Pearson Correlation ---")
    tickers = sorted(set(list(a.get("per_ticker",{}).keys()) + list(b.get("per_ticker",{}).keys())))
    print(f"  {'Ticker':<10}  {'10-feat WS':<18}  {'11-feat+logvol WS':<18}  Delta")
    print("  " + "-"*62)
    for tkr in tickers:
        c1 = a.get("per_ticker", {}).get(tkr, {}).get("corr", float("nan"))
        c2 = b.get("per_ticker", {}).get(tkr, {}).get("corr", float("nan"))
        if not (np.isnan(c1) or np.isnan(c2)):
            delta = c2 - c1
            sign = "+" if delta >= 0 else ""
            better = "" if delta > 0 else ""
            print(f"  {tkr:<10}  {c1:<18.4f}  {c2:<18.4f}  {sign}{delta:+.4f} {better}")

    print("\n--- Per-ticker IC (Spearman) ---")
    print(f"  {'Ticker':<10}  {'10-feat WS':<18}  {'11-feat+logvol WS':<18}  Delta")
    print("  " + "-"*62)
    for tkr in tickers:
        ic1 = a.get("per_ticker", {}).get(tkr, {}).get("ic", float("nan"))
        ic2 = b.get("per_ticker", {}).get(tkr, {}).get("ic", float("nan"))
        if not (np.isnan(ic1) or np.isnan(ic2)):
            delta = ic2 - ic1
            sign = "+" if delta >= 0 else ""
            print(f"  {tkr:<10}  {ic1:<18.4f}  {ic2:<18.4f}  {sign}{delta:+.4f}")

    print("="*80)


def main() -> None:
    panel = _load_panel()
    panel_test, cutoff = _get_test_panel(panel, TEST_DAYS)
    print(f"Test window: {cutoff.date()} -> {pd.to_datetime(panel['Date']).max().date()}")
    print(f"Test rows  : {len(panel_test)}")

    results = []
    for vkey in VARIANTS:
        print(f"\nEvaluating: {VARIANTS[vkey]} ...")
        r = evaluate_variant(vkey, panel_test)
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            sys.exit(1)
        results.append(r)
        print(f"  MAE={r['mae']:.5f}  Corr={r['correlation']:.4f}  "
              f"IC={r['ic_spearman']:.4f}  p={r['ic_pvalue']:.3f}  "
              f"PredStd={r['pred_std']:.5f}  PctNeg={r['pct_neg_predictions']:.3f}")

    print_comparison(results)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "test_cutoff": str(cutoff.date()),
            "test_rows":   len(panel_test),
            "protocol":    "warm-start from production checkpoint, 5 epochs, LR*0.2, clean baseline (no RSI_14)",
            "results":     results,
        }, f, indent=2)
    print(f"\nResults saved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
