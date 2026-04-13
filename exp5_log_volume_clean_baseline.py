"""
Experiment 5: log_volume vs clean 10-feat baseline  full from-scratch on broad panel.

Compares:
  Arm A: 10-feat (current production, no RSI_14, no log_volume)
  Arm B: 11-feat (10-feat + log_volume)

Both trained from scratch on 50-ticker broad panel (2020-2026), enough epochs to converge.
Results saved to data/experiment/log_volume_clean_baseline_comparison.json
"""

import json, os, shutil, numpy as np, pandas as pd
from scipy import stats

EPOCHS = 30
PATIENCE = 5
BATCH = 256
BROAD_PANEL = "data/research_panel.parquet"
EXP_DIR = "models/experiment"
RESULTS_PATH = "data/experiment/log_volume_clean_baseline_comparison.json"

BASE_FEATURES = [
    "Ret_1D", "Ret_5D", "Ret_21D", "Ret_63D", "Ret_252D",
    "Vol_21D", "Vol_63D", "Gap_MA20", "Gap_MA50", "Gap_MA200",
]

os.makedirs(EXP_DIR, exist_ok=True)
os.makedirs("data/experiment", exist_ok=True)

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# --- Build broad panel with log_volume ---
print("Loading broad panel...")
df = pd.read_parquet(BROAD_PANEL)
df["log_volume"] = np.log(df["Volume"].clip(lower=1))
broad_with_lv = "data/experiment/research_panel_with_log_volume.parquet"
df.to_parquet(broad_with_lv, index=False)
print(f"  Panel: {df.shape}, tickers: {df['Ticker'].nunique()}, log_volume added")

import subprocess, sys as _sys
PYTHON = _sys.executable

def train_arm(label, extra_features, panel, model_out, scaler_out):
    """Train from scratch, return best val nll."""
    # Write a temporary gate override via env
    feat_list = BASE_FEATURES + extra_features
    # Pass feature list via a temp JSON so deep_learning_model.py picks it up
    tmp_gate = f"data/experiment/_tmp_gate_{label}.json"
    with open(tmp_gate, "w") as f:
        json.dump({"feature_cols": feat_list, "last_updated": "exp5", "total_features": len(feat_list),
                   "stages_included": ["dl_approved"]}, f)

    # Temporarily swap approved features file
    gate_path = "feature_store/approved/dl_approved_features.json"
    gate_backup = f"feature_store/approved/dl_approved_features_exp5_backup.json"
    shutil.copy2(gate_path, gate_backup)
    shutil.copy2(tmp_gate, gate_path)

    try:
        result = subprocess.run([
            PYTHON, "deep_learning_model.py", "train",
            "--panel", panel,
            "--model", model_out,
            "--scaler", scaler_out,
            "--epochs", str(EPOCHS),
            "--patience", str(PATIENCE),
            "--batch-size", str(BATCH),
            "--from-scratch",
        ], capture_output=True, text=True, env=os.environ.copy())
        if result.returncode != 0:
            print(f"  [ERROR] {label} training failed:\n{result.stderr[-2000:]}")
            return None, result.stdout + result.stderr
    finally:
        shutil.copy2(gate_backup, gate_path)
        os.remove(gate_backup)
        os.remove(tmp_gate)

    return result.returncode, result.stdout + result.stderr

def extract_val_nll(log_text):
    """Pull best val nll from training log."""
    best = None
    for line in log_text.splitlines():
        if "val nll=" in line:
            try:
                val = float(line.split("val nll=")[-1].split()[0])
                if best is None or val > best:
                    best = val
            except Exception:
                pass
    return best

def backtest_arm(model_path, scaler_path, panel, label):
    """Run DL backtest on panel, return IC stats per ticker."""
    gate_path = "feature_store/approved/dl_approved_features.json"
    # Read feature_cols from checkpoint to set gate
    import torch
    ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
    feat_cols = ckpt["feature_cols"]
    gate_backup = f"feature_store/approved/dl_approved_features_bt_backup.json"
    shutil.copy2(gate_path, gate_backup)
    gate_data = {"feature_cols": feat_cols, "last_updated": "exp5", "total_features": len(feat_cols),
                 "stages_included": ["dl_approved"]}
    with open(gate_path, "w") as f:
        json.dump(gate_data, f)
    try:
        result = subprocess.run([
            PYTHON, "deep_learning_model.py", "backtest",
            "--panel", panel,
            "--model", model_path,
            "--scaler", scaler_path,
        ], capture_output=True, text=True, env=os.environ.copy())
    finally:
        shutil.copy2(gate_backup, gate_path)
        os.remove(gate_backup)

    # Parse per-ticker IC from output
    tickers, ics, corrs = [], [], []
    for line in (result.stdout + result.stderr).splitlines():
        if "IC=" in line and "Corr=" in line:
            try:
                parts = line.split()
                ticker = parts[0].rstrip(":")
                ic = float([p for p in parts if p.startswith("IC=")][0].split("=")[1].rstrip(","))
                corr = float([p for p in parts if p.startswith("Corr=")][0].split("=")[1].rstrip(","))
                tickers.append(ticker)
                ics.append(ic)
                corrs.append(corr)
            except Exception:
                pass
    return tickers, ics, corrs, result.stdout + result.stderr

# --- Arm A: 10-feat from scratch ---
print("\n--- ARM A: 10-feat (clean baseline) ---")
model_a = f"{EXP_DIR}/dl_10feat_broad_scratch.pt"
scaler_a = f"{EXP_DIR}/dl_10feat_broad_scratch_scaler.json"
rc_a, log_a = train_arm("armA", [], BROAD_PANEL, model_a, scaler_a)
nll_a = extract_val_nll(log_a)
print(f"  Best val nll: {nll_a}")
print(log_a[-1500:])

# --- Arm B: 10-feat + log_volume from scratch ---
print("\n--- ARM B: 10-feat + log_volume ---")
model_b = f"{EXP_DIR}/dl_11feat_logvol_broad_scratch.pt"
scaler_b = f"{EXP_DIR}/dl_11feat_logvol_broad_scratch_scaler.json"
rc_b, log_b = train_arm("armB", ["log_volume"], broad_with_lv, model_b, scaler_b)
nll_b = extract_val_nll(log_b)
print(f"  Best val nll: {nll_b}")
print(log_b[-1500:])

# --- Backtest both arms ---
print("\n--- BACKTEST: Arm A ---")
tA, icA, corrA, btlogA = backtest_arm(model_a, scaler_a, BROAD_PANEL, "10feat")
print(btlogA[-1000:])

print("\n--- BACKTEST: Arm B ---")
tB, icB, corrB, btlogB = backtest_arm(model_b, scaler_b, broad_with_lv, "11feat_logvol")
print(btlogB[-1000:])

# --- Aggregate results ---
def summarize(ics, corrs):
    if not ics:
        return {}
    arr_ic = np.array(ics)
    arr_corr = np.array(corrs)
    t, p = stats.ttest_1samp(arr_ic, 0)
    return {
        "mean_IC": round(float(arr_ic.mean()), 4),
        "std_IC": round(float(arr_ic.std()), 4),
        "mean_Corr": round(float(arr_corr.mean()), 4),
        "IC_p_value": round(float(p), 4),
        "n_tickers": len(ics),
        "per_ticker": {t: {"IC": round(ic, 4), "Corr": round(c, 4)} for t, ic, c in zip(tA or tB, ics, corrs)},
    }

results = {
    "experiment": "Exp5: log_volume on clean 10-feat baseline  from scratch, broad 50-ticker panel",
    "date": "2026-04-02",
    "epochs": EPOCHS,
    "patience": PATIENCE,
    "panel": BROAD_PANEL,
    "arm_A_10feat": {**summarize(icA, corrA), "best_val_nll": nll_a},
    "arm_B_11feat_logvol": {**summarize(icB, corrB), "best_val_nll": nll_b},
    "delta_mean_IC": round((np.mean(icB) - np.mean(icA)) if icA and icB else 0, 4),
    "delta_mean_Corr": round((np.mean(corrB) - np.mean(corrA)) if corrA and corrB else 0, 4),
}

with open(RESULTS_PATH, "w") as f:
    json.dump(results, f, indent=2)

print("\n=== EXPERIMENT 5 SUMMARY ===")
print(f"Arm A (10-feat)     IC={results['arm_A_10feat'].get('mean_IC','?')}  Corr={results['arm_A_10feat'].get('mean_Corr','?')}  p={results['arm_A_10feat'].get('IC_p_value','?')}")
print(f"Arm B (+log_volume) IC={results['arm_B_11feat_logvol'].get('mean_IC','?')}  Corr={results['arm_B_11feat_logvol'].get('mean_Corr','?')}  p={results['arm_B_11feat_logvol'].get('IC_p_value','?')}")
print(f"Delta IC: {results['delta_mean_IC']}  Delta Corr: {results['delta_mean_Corr']}")
print(f"Results saved -> {RESULTS_PATH}")
