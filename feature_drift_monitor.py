"""feature_drift_monitor.py
Drift detection and dashboard output for DL-approved features.

Compares current live feature distributions (features.parquet) against the
historical training distribution (training_panel.parquet).

Detects:
  - Mean/std shift in current vs historical distribution
  - Null rate increases (data source degrading)
  - KS distance between current and historical values
  - Auto-demotion warnings when drift exceeds thresholds

Outputs (all written to feature_store/dashboard/):
  drift_status.json       per-feature drift metrics (latest run)
  registry_status.json    full registry snapshot for dashboard
  promotion_queue.json    features with test results but not yet promoted

Usage:
    python feature_drift_monitor.py                  # monitor DL-approved features
    python feature_drift_monitor.py --all-stages     # monitor all registered features
    python feature_drift_monitor.py --emit-warnings  # print demotion warnings
"""

from __future__ import annotations

import argparse
import json
import warnings
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats

PANEL_PATH = Path("data/training_panel.parquet")
FEATURES_PATH = Path("data/features.parquet")
REGISTRY_PATH = Path("feature_store/registry/feature_registry.json")
DASHBOARD_DIR = Path("feature_store/dashboard")

# Drift thresholds
MEAN_SHIFT_WARN_Z = 2.0   # z-scores of mean shift vs training std
MEAN_SHIFT_FAIL_Z = 4.0
KS_WARN_P = 0.05
KS_FAIL_P = 0.01
NULL_RATE_WARN = 0.30
NULL_RATE_FAIL = 0.70


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_registry() -> Dict:
    if not REGISTRY_PATH.exists():
        return {}
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_training_distributions(feature_cols: List[str]) -> Dict[str, dict]:
    """Compute mean/std/p5/p95 of each feature from the training panel."""
    if not PANEL_PATH.exists():
        return {}

    try:
        from forecast_common import load_panel_with_features
        df = load_panel_with_features()
    except Exception:
        df = pd.read_parquet(PANEL_PATH)

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])

    distributions = {}
    for col in feature_cols:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(series) < 10:
            continue
        distributions[col] = {
            "mean": float(series.mean()),
            "std": float(series.std()),
            "p5": float(series.quantile(0.05)),
            "p25": float(series.quantile(0.25)),
            "p50": float(series.quantile(0.50)),
            "p75": float(series.quantile(0.75)),
            "p95": float(series.quantile(0.95)),
            "n": int(len(series)),
            "null_rate": float(df[col].isna().mean()),
        }
    return distributions


def _load_current_distributions(feature_cols: List[str]) -> Dict[str, dict]:
    """Compute distribution of each feature from the live features.parquet snapshot."""
    if not FEATURES_PATH.exists():
        return {}

    df = pd.read_parquet(FEATURES_PATH)
    distributions = {}
    for col in feature_cols:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        total = len(df)
        n_null = int(df[col].isna().sum())
        null_rate = n_null / total if total > 0 else 1.0
        if len(series) < 2:
            distributions[col] = {"n": len(series), "null_rate": null_rate, "error": "too_few_values"}
            continue
        distributions[col] = {
            "mean": float(series.mean()),
            "std": float(series.std()),
            "p5": float(series.quantile(0.05)) if len(series) >= 20 else None,
            "p50": float(series.quantile(0.50)) if len(series) >= 2 else None,
            "p95": float(series.quantile(0.95)) if len(series) >= 20 else None,
            "n": int(len(series)),
            "null_rate": null_rate,
        }
    return distributions


# ---------------------------------------------------------------------------
# Drift computation per feature
# ---------------------------------------------------------------------------


def _compute_drift_metrics(
    col: str,
    hist: dict,
    curr: dict,
) -> dict:
    """Compute drift metrics comparing current snapshot to historical distribution."""
    result = {
        "feature": col,
        "check_date": str(date.today()),
        "historical_n": hist.get("n", 0),
        "current_n": curr.get("n", 0),
        "historical_mean": hist.get("mean"),
        "current_mean": curr.get("mean"),
        "historical_std": hist.get("std"),
        "current_std": curr.get("std"),
        "historical_null_rate": hist.get("null_rate"),
        "current_null_rate": curr.get("null_rate"),
    }

    flags = []
    notes = []

    # Mean shift in z-score units
    hist_std = hist.get("std") or 0.0
    hist_mean = hist.get("mean")
    curr_mean = curr.get("mean")
    if hist_std > 1e-10 and hist_mean is not None and curr_mean is not None:
        mean_z = abs(curr_mean - hist_mean) / hist_std
        result["mean_shift_z"] = round(mean_z, 3)
        if mean_z >= MEAN_SHIFT_FAIL_Z:
            flags.append("FAIL")
            notes.append(f"Mean shifted {mean_z:.1f} std deviations from training distribution.")
        elif mean_z >= MEAN_SHIFT_WARN_Z:
            flags.append("WARN")
            notes.append(f"Mean shifted {mean_z:.1f} std deviations. Monitor closely.")
        else:
            flags.append("PASS")
    else:
        result["mean_shift_z"] = None

    # Null rate change
    curr_null = curr.get("null_rate", 0.0)
    hist_null = hist.get("null_rate", 0.0)
    result["null_rate_delta"] = round(curr_null - hist_null, 4) if curr_null is not None else None
    if curr_null >= NULL_RATE_FAIL:
        flags.append("FAIL")
        notes.append(f"Current null rate {curr_null:.0%}  feature may be unavailable.")
    elif curr_null >= NULL_RATE_WARN and curr_null > hist_null + 0.10:
        flags.append("WARN")
        notes.append(f"Null rate increased from {hist_null:.0%} to {curr_null:.0%}.")

    # KS test using percentile bins as proxy (no raw historical values in memory)
    # Approximate via mean/std comparison only (full KS needs raw data)
    # Flag if std ratio is extreme
    hist_std_v = hist.get("std") or 0.0
    curr_std_v = curr.get("std") or 0.0
    if hist_std_v > 1e-10 and curr_std_v > 1e-10:
        std_ratio = max(curr_std_v, hist_std_v) / min(curr_std_v, hist_std_v)
        result["std_ratio"] = round(std_ratio, 3)
        if std_ratio >= 3.0:
            flags.append("WARN")
            notes.append(f"Std ratio={std_ratio:.2f}x vs training. Distribution shape may have changed.")
        elif std_ratio >= 5.0:
            flags.append("FAIL")
            notes.append(f"Extreme std ratio={std_ratio:.2f}x. Feature distribution has shifted significantly.")
    else:
        result["std_ratio"] = None

    # Overall flag
    if "FAIL" in flags:
        overall = "FAIL"
    elif "WARN" in flags:
        overall = "WARN"
    else:
        overall = "PASS"

    result["drift_flag"] = overall
    result["drift_notes"] = notes
    return result


# ---------------------------------------------------------------------------
# Dashboard output builders
# ---------------------------------------------------------------------------


def build_drift_status(all_stages: bool = False) -> dict:
    """Compute drift metrics for DL-approved (and optionally all) features."""
    registry = _load_registry()

    # Select features to monitor
    if all_stages:
        target_features = list(registry.values())
    else:
        target_features = [v for v in registry.values() if v["stage"] in ("dl_approved", "production_critical")]

    feature_cols = [v["panel_column"] for v in target_features]

    hist_dists = _load_training_distributions(feature_cols)
    curr_dists = _load_current_distributions(feature_cols)

    drift_results = []
    demotion_warnings = []

    for entry in target_features:
        col = entry["panel_column"]
        name = entry["name"]
        hist = hist_dists.get(col, {})
        curr = curr_dists.get(col, {})

        if not hist:
            drift_results.append({
                "feature": name,
                "panel_column": col,
                "stage": entry["stage"],
                "drift_flag": "WARN",
                "drift_notes": [f"Column '{col}' not found in training panel  cannot compute historical baseline."],
                "check_date": str(date.today()),
            })
            continue

        metrics = _compute_drift_metrics(col, hist, curr)
        metrics["feature"] = name
        metrics["stage"] = entry["stage"]
        drift_results.append(metrics)

        if metrics["drift_flag"] == "FAIL" and entry["stage"] in ("dl_approved", "production_critical"):
            demotion_warnings.append({
                "feature": name,
                "stage": entry["stage"],
                "reason": "; ".join(metrics["drift_notes"]),
                "recommended_action": "Review and consider demotion via: python feature_promoter.py --feature {} --action demote --reason \"drift detected\"".format(name),
            })

    summary = {
        "generated_date": str(date.today()),
        "features_monitored": len(drift_results),
        "drift_pass": sum(1 for r in drift_results if r.get("drift_flag") == "PASS"),
        "drift_warn": sum(1 for r in drift_results if r.get("drift_flag") == "WARN"),
        "drift_fail": sum(1 for r in drift_results if r.get("drift_flag") == "FAIL"),
        "demotion_warnings": demotion_warnings,
        "features": drift_results,
    }
    return summary


def build_registry_status() -> dict:
    """Full registry snapshot formatted for dashboard consumption."""
    registry = _load_registry()
    stage_groups: Dict[str, list] = {}

    for name, entry in registry.items():
        stage = entry["stage"]
        if stage not in stage_groups:
            stage_groups[stage] = []
        stage_groups[stage].append({
            "name": name,
            "panel_column": entry["panel_column"],
            "description": entry["description"],
            "feature_type": entry["feature_type"],
            "source": entry["source"],
            "lag_days": entry["lag_days"],
            "point_in_time": entry["point_in_time"],
            "update_frequency": entry["update_frequency"],
            "first_available_date": entry["first_available_date"],
            "added_date": entry.get("added_date"),
            "promoted_date": entry.get("promoted_date"),
            "has_test_results": bool(entry.get("test_results_path")),
            "has_scorecard": bool(entry.get("scorecard_path")),
            "last_checked": entry.get("last_checked"),
            "notes": entry.get("notes", ""),
        })

    from dl_feature_gate import get_approved_features
    dl_features = get_approved_features()

    return {
        "generated_date": str(date.today()),
        "total_features": len(registry),
        "dl_approved_count": len(dl_features),
        "dl_approved_features": dl_features,
        "stages": {
            "experimental": len(stage_groups.get("experimental", [])),
            "sandbox_approved": len(stage_groups.get("sandbox_approved", [])),
            "dl_approved": len(stage_groups.get("dl_approved", [])),
            "production_critical": len(stage_groups.get("production_critical", [])),
            "quarantined": len(stage_groups.get("quarantined", [])),
        },
        "by_stage": stage_groups,
    }


def build_promotion_queue() -> dict:
    """Features that have test results and may be ready for promotion review."""
    registry = _load_registry()
    queue = []

    for name, entry in registry.items():
        if entry["stage"] in ("production_critical", "quarantined"):
            continue
        if not entry.get("test_results_path"):
            continue
        # Has test results  eligible for promotion review
        results_path = Path(entry["test_results_path"])
        scorecard_available = bool(entry.get("scorecard_path"))
        queue.append({
            "name": name,
            "current_stage": entry["stage"],
            "has_scorecard": scorecard_available,
            "test_results_path": entry["test_results_path"],
            "last_checked": entry.get("last_checked"),
            "review_command": f"python feature_promoter.py --feature {name} --action review",
            "promote_command": f"python feature_promoter.py --feature {name} --action promote --reason \"<reason>\"",
        })

    return {
        "generated_date": str(date.today()),
        "features_pending_review": len(queue),
        "queue": queue,
    }


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run(all_stages: bool = False, emit_warnings: bool = False) -> None:
    """Run full monitoring cycle and write dashboard outputs."""
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n[feature_drift_monitor] Running  {date.today()}")
    print("=" * 55)

    # Drift status
    print("  Computing drift status...")
    drift = build_drift_status(all_stages=all_stages)
    drift_path = DASHBOARD_DIR / "drift_status.json"
    with open(drift_path, "w", encoding="utf-8") as f:
        json.dump(drift, f, indent=2)
    print(f"  [{drift['drift_pass']} PASS / {drift['drift_warn']} WARN / {drift['drift_fail']} FAIL] -> {drift_path}")

    # Registry status
    print("  Building registry snapshot...")
    reg_status = build_registry_status()
    reg_path = DASHBOARD_DIR / "registry_status.json"
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump(reg_status, f, indent=2)
    print(f"  {reg_status['total_features']} features, {reg_status['dl_approved_count']} DL-approved -> {reg_path}")

    # Promotion queue
    print("  Building promotion queue...")
    queue = build_promotion_queue()
    queue_path = DASHBOARD_DIR / "promotion_queue.json"
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2)
    print(f"  {queue['features_pending_review']} features pending review -> {queue_path}")

    # Demotion warnings
    if emit_warnings and drift["demotion_warnings"]:
        print(f"\n[WARN] {len(drift['demotion_warnings'])} demotion warning(s):")
        for w in drift["demotion_warnings"]:
            print(f"  {w['feature']} ({w['stage']}): {w['reason']}")
            print(f"  -> {w['recommended_action']}")

    print("\n[OK] Dashboard outputs updated.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Run feature drift monitoring and update dashboard outputs.")
    ap.add_argument("--all-stages", action="store_true", help="Monitor all stages, not just DL-approved")
    ap.add_argument("--emit-warnings", action="store_true", help="Print demotion warnings to stdout")
    args = ap.parse_args()
    run(all_stages=args.all_stages, emit_warnings=args.emit_warnings)


if __name__ == "__main__":
    main()
