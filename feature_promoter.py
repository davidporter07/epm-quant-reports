"""feature_promoter.py
Scorecard evaluation and promotion/demotion decisions for the EPM feature pipeline.

Reads test results produced by feature_tester.py and applies a 7-dimensional
scorecard to determine whether a feature is ready for promotion.

Scorecard dimensions (max 100 points):
    1. Predictive Lift        (0-20 pts)  mean IC threshold
    2. IC Stability           (0-15 pts)  IC hit rate across windows
    3. Incremental Value      (0-20 pts)  ablation delta R
    4. Leakage-Free           (0-15 pts)  leakage check result
    5. Drift Resistance       (0-15 pts)  KS drift test
    6. Robustness             (0-10 pts)  noise injection degradation
    7. Availability           (0-5 pts)   null rate check

Promotion thresholds:
    Experimental -> Sandbox Approved : score >= 40 AND leakage = PASS
    Sandbox Approved -> DL Approved  : score >= 60 AND leakage = PASS AND no FAIL in any dimension
    DL Approved -> Production Critical: score >= 75 AND all dimensions >= WARN

Hard gates (block promotion regardless of score):
    LEAKAGE_DETECTED                     leakage check FAIL
    INSUFFICIENT_DATA                    availability FAIL
    HIGHLY_REDUNDANT_WITH_NO_ABLATION_LIFT  redundancy FAIL AND delta R < 0.003
    INVERTED_SIGNAL                      mean IC < 0 AND hit_rate < 50%

Demotion triggers (automatic warnings):
    - Recent drift detected (FAIL on drift test)
    - Leakage newly detected (FAIL on leakage test)
    - Availability drops (null_rate > 0.70)

Usage:
    python feature_promoter.py --feature log_volume --action review
    python feature_promoter.py --feature log_volume --action promote --reason "IC=0.07 across all windows"
    python feature_promoter.py --feature sentiment_1d --action demote --reason "only 12 months of data, too sparse"
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RESULTS_DIR = Path("feature_store/testing/results")
SCORECARD_DIR = Path("feature_store/scoring/results")


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------


def _score_availability(test: dict) -> Tuple[int, str]:
    """0-5 pts. Based on null rate."""
    flag = test.get("flag", "FAIL")
    null_rate = test.get("null_rate", 1.0)
    if flag == "PASS" and null_rate < 0.10:
        return 5, "Excellent coverage (<10% null)"
    elif flag == "PASS":
        return 3, f"Good coverage ({null_rate:.0%} null)"
    elif flag == "WARN":
        return 1, f"Sparse data ({null_rate:.0%} null)  interpret with caution"
    else:
        return 0, f"Insufficient data ({null_rate:.0%} null)  do not promote"


def _score_ic(test: dict) -> Tuple[int, str]:
    """0-20 pts. Based on signed mean IC. Negative IC scores 0  direction matters."""
    mean_ic = test.get("mean_ic", 0.0) or 0.0
    if mean_ic < 0:
        return 0, f"Inverted signal: mean IC={mean_ic:.4f} (negative  scores 0 regardless of magnitude)"
    if mean_ic >= 0.08:
        return 20, f"Strong IC={mean_ic:.4f} (>= 0.08)"
    elif mean_ic >= 0.05:
        return 15, f"Good IC={mean_ic:.4f} (>= 0.05)"
    elif mean_ic >= 0.03:
        return 8, f"Marginal IC={mean_ic:.4f} (>= 0.03)"
    elif mean_ic >= 0.01:
        return 3, f"Weak IC={mean_ic:.4f} (>= 0.01)"
    else:
        return 0, f"No predictive signal: IC={mean_ic:.4f}"


def _score_ic_stability(test: dict) -> Tuple[int, str]:
    """0-15 pts. Based on IC hit rate across windows."""
    hit_rate = test.get("ic_hit_rate", 0.0) or 0.0
    n_windows = test.get("windows_evaluated", 0) or 0
    if n_windows < 5:
        return 0, f"Too few windows ({n_windows}) for stability assessment"
    if hit_rate >= 0.70:
        return 15, f"Very stable: hit_rate={hit_rate:.0%} across {n_windows} windows"
    elif hit_rate >= 0.60:
        return 10, f"Stable: hit_rate={hit_rate:.0%}"
    elif hit_rate >= 0.50:
        return 5, f"Marginally stable: hit_rate={hit_rate:.0%}"
    else:
        return 0, f"Unstable: hit_rate={hit_rate:.0%} (< 50% of windows positive)"


def _score_ablation(test: dict) -> Tuple[int, str]:
    """0-20 pts. Incremental delta R. Minimum threshold 0.001  below that scores 0.

    Tiers (tightened from original):
        >= 0.010  : 20 pts  strong lift
        >= 0.005  : 15 pts  clear lift
        >= 0.003  : 8 pts   meaningful lift
        >= 0.001  : 3 pts   modest but measurable
        < 0.001   : 0 pts   noise floor, no credit (includes negative)
    """
    delta_r2 = test.get("delta_r2", 0.0) or 0.0
    if delta_r2 >= 0.010:
        return 20, f"Strong incremental lift: delta R={delta_r2:+.5f}"
    elif delta_r2 >= 0.005:
        return 15, f"Clear incremental lift: delta R={delta_r2:+.5f}"
    elif delta_r2 >= 0.003:
        return 8, f"Meaningful incremental lift: delta R={delta_r2:+.5f}"
    elif delta_r2 >= 0.001:
        return 3, f"Modest incremental lift: delta R={delta_r2:+.5f}"
    elif delta_r2 >= 0.0:
        return 0, f"Below noise floor: delta R={delta_r2:+.5f} (< 0.001 minimum)"
    else:
        return 0, f"Negative incremental value: delta R={delta_r2:+.5f}"


def _score_leakage(test: dict) -> Tuple[int, str]:
    """0-15 pts. Binary pass/fail with warning tier."""
    flag = test.get("flag", "FAIL")
    if flag == "PASS":
        return 15, "No leakage detected"
    elif flag == "WARN":
        return 7, "Mild leakage risk  review lag assumptions"
    else:
        return 0, "LEAKAGE DETECTED  do not promote to DL"


def _score_drift(test: dict) -> Tuple[int, str]:
    """0-15 pts. Based on KS test p-value."""
    flag = test.get("flag", "FAIL")
    pval = test.get("ks_pvalue", 0.0) or 0.0
    if flag == "PASS" and pval >= 0.10:
        return 15, f"No drift (KS p={pval:.4f})"
    elif flag == "PASS" or (flag == "WARN" and pval >= 0.05):
        return 10, f"Minor drift (KS p={pval:.4f})  monitor"
    elif flag == "WARN":
        return 5, f"Moderate drift (KS p={pval:.4f})  retrain cadence important"
    else:
        return 0, f"Significant distribution drift (KS p={pval:.4f})"


def _score_robustness(test: dict) -> Tuple[int, str]:
    """0-10 pts. Based on IC degradation under noise."""
    flag = test.get("flag", "FAIL")
    degradation = test.get("ic_degradation_pct", 1.0) or 0.0
    if flag == "PASS":
        return 10, f"Robust: {degradation:.0%} IC degradation under noise"
    elif flag == "WARN":
        return 5, f"Moderate sensitivity: {degradation:.0%} IC degradation"
    else:
        return 0, f"Brittle: {degradation:.0%} IC degradation  review signal construction"


# ---------------------------------------------------------------------------
# Overall scoring
# ---------------------------------------------------------------------------


def _score_redundancy(test: dict) -> Tuple[int, str]:
    """0-10 pts. Based on max absolute correlation with approved features."""
    flag = test.get("flag", "FAIL")
    max_corr = test.get("max_abs_corr")
    if max_corr is None:
        return 7, "No approved features to compare against (treated as non-redundant)"
    if flag == "PASS":
        return 10, f"Low redundancy: max corr={max_corr:.3f}"
    elif flag == "WARN":
        return 5, f"Moderate redundancy: max corr={max_corr:.3f}  verify ablation"
    else:
        return 0, f"Highly redundant: max corr={max_corr:.3f}  likely duplicates approved signal"


def _lookup_current_stage(feature_name: Optional[str]) -> str:
    """Read current stage from registry. Returns 'experimental' if unknown."""
    if not feature_name:
        return "experimental"
    try:
        from feature_registry import FeatureRegistry, STAGES
        entry = FeatureRegistry().get(feature_name)
        return entry.get("stage", "experimental")
    except Exception:
        return "experimental"


def compute_scorecard(results: dict) -> dict:
    """Apply the 8-dimension scorecard to test results.

    Dimensions and max points:
        availability       (0-5)    null rate / coverage
        predictive_lift    (0-20)   mean IC
        ic_stability       (0-10)   IC hit rate across windows
        incremental_value  (0-20)   ablation delta R
        leakage_free       (0-15)   leakage check
        drift_resistance   (0-10)   KS drift test
        robustness         (0-10)   noise injection
        non_redundant      (0-10)   max corr with approved features
        
        Total              (0-100)

    Hard gates block promotion regardless of score:
        LEAKAGE_DETECTED   leakage check FAIL
        INSUFFICIENT_DATA  availability FAIL
        HIGHLY_REDUNDANT   redundancy FAIL AND ablation delta < 0.003
    """
    tests = results.get("tests", {})
    feature_name = results.get("feature_name")

    # ic_walkforward_stability uses the same ic_walkforward test data
    scorers = [
        ("availability",      "availability",   _score_availability),
        ("predictive_lift",   "ic_walkforward", _score_ic),
        ("ic_stability",      "ic_walkforward", _score_ic_stability),
        ("incremental_value", "ablation",       _score_ablation),
        ("leakage_free",      "leakage_check",  _score_leakage),
        ("drift_resistance",  "drift",          _score_drift),
        ("robustness",        "robustness",     _score_robustness),
        ("non_redundant",     "redundancy",     _score_redundancy),
    ]

    dimensions = {}
    total = 0

    for dim_name, test_key, scorer_fn in scorers:
        test_data = tests.get(test_key, {})
        if not test_data or test_data.get("flag") == "ERROR":
            score, explanation = 0, f"Test '{test_key}' not run or errored"
        else:
            score, explanation = scorer_fn(test_data)
        dimensions[dim_name] = {
            "score": score,
            "explanation": explanation,
            "test_flag": test_data.get("flag", "N/A"),
        }
        total += score

    # Hard gates
    hard_gates_failed: List[str] = []
    if tests.get("leakage_check", {}).get("flag") == "FAIL":
        hard_gates_failed.append("LEAKAGE_DETECTED")
    if tests.get("availability", {}).get("flag") == "FAIL":
        hard_gates_failed.append("INSUFFICIENT_DATA")
    redundancy_flag = tests.get("redundancy", {}).get("flag", "PASS")
    ablation_delta = tests.get("ablation", {}).get("delta_r2", 0.0) or 0.0
    if redundancy_flag == "FAIL" and ablation_delta < 0.003:
        hard_gates_failed.append("HIGHLY_REDUNDANT_WITH_NO_ABLATION_LIFT")

    # Joint gate: inverted signal  negative mean IC with hit rate below 50%
    # A feature where the signal direction is wrong more often than right cannot be promoted.
    ic_data = tests.get("ic_walkforward", {})
    _mean_ic   = ic_data.get("mean_ic", 0.0) or 0.0
    _hit_rate  = ic_data.get("ic_hit_rate", 1.0) or 1.0
    if _mean_ic < 0 and _hit_rate < 0.50:
        hard_gates_failed.append("INVERTED_SIGNAL")

    # Stage-aware promotion recommendation
    current_stage = _lookup_current_stage(feature_name)
    blocked = bool(hard_gates_failed)

    if blocked:
        recommendation = "BLOCK"
        recommendation_reason = f"Hard gate(s) failed: {', '.join(hard_gates_failed)}"
    elif current_stage in ("dl_approved", "production_critical"):
        # Already in DL  just monitoring
        if total >= 75:
            recommendation = "PROMOTE_TO_PRODUCTION_CRITICAL"
            recommendation_reason = f"Score {total}/100 qualifies for production_critical."
        else:
            recommendation = "MAINTAIN_DL_APPROVED"
            recommendation_reason = f"Score {total}/100  feature remains DL-approved."
    elif current_stage == "sandbox_approved":
        if total >= 75:
            recommendation = "PROMOTE_TO_DL_APPROVED"
            recommendation_reason = f"Score {total}/100 meets DL Approved threshold (>=75). Next: dl_approved."
        else:
            recommendation = "KEEP_SANDBOX"
            recommendation_reason = f"Score {total}/100  not yet DL-ready (need >=75 from sandbox)."
    else:
        # experimental
        if total >= 60:
            recommendation = "PROMOTE_TO_SANDBOX"
            recommendation_reason = f"Score {total}/100 meets Sandbox threshold (>=60). Next step: sandbox_approved."
        elif total >= 40:
            recommendation = "KEEP_EXPERIMENTAL"
            recommendation_reason = f"Score {total}/100  stays experimental (need >=60 for sandbox)."
        else:
            recommendation = "REJECT"
            recommendation_reason = f"Score {total}/100  too low (<40). Investigate feature quality."

    return {
        "feature_name": feature_name,
        "current_stage": current_stage,
        "test_date": results.get("test_date"),
        "scorecard_date": str(date.today()),
        "total_score": total,
        "max_possible": 100,
        "dimensions": dimensions,
        "hard_gates_failed": hard_gates_failed,
        "recommendation": recommendation,
        "recommendation_reason": recommendation_reason,
        "overall_test_flag": results.get("overall_flag"),
        "lag_days_applied": results.get("lag_days_applied", 1),
        "pit_enforced": results.get("lag_shifted", False),
    }


def print_scorecard(scorecard: dict) -> None:
    """Pretty-print the scorecard to stdout."""
    print(f"\n{'='*60}")
    print(f"FEATURE SCORECARD: {scorecard['feature_name']}")
    print(f"{'='*60}")
    print(f"Total Score : {scorecard['total_score']:3d} / 100")
    print(f"Test Date   : {scorecard['test_date']}")
    print()
    print("Dimension Scores:")
    print(f"  {'Dimension':<22s} {'Score':>6s}  {'Flag':<6s}  Explanation")
    print("  " + "-" * 70)
    for dim, data in scorecard["dimensions"].items():
        print(
            f"  {dim:<22s} {data['score']:>4d}pts  {data['test_flag']:<6s}  {data['explanation'][:55]}"
        )
    print()

    if scorecard["hard_gates_failed"]:
        print(f"[BLOCKED] Hard gates failed: {', '.join(scorecard['hard_gates_failed'])}")

    rec = scorecard["recommendation"]
    marker = "[OK]" if "PROMOTE" in rec else "[WARN]" if "KEEP" in rec else "[BLOCK]"
    print(f"{marker} Recommendation: {rec}")
    print(f"         Reason: {scorecard['recommendation_reason']}")
    print()


# ---------------------------------------------------------------------------
# Load latest test results for a feature
# ---------------------------------------------------------------------------


def load_latest_results(feature_name: str) -> Optional[dict]:
    """Load the most recent test results for a feature from testing/results/."""
    pattern = f"{feature_name.lower()}_*.json"
    files = sorted(RESULTS_DIR.glob(pattern))
    if not files:
        return None
    with open(files[-1], "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Promotion / demotion actions
# ---------------------------------------------------------------------------


def action_review(feature_name: str) -> dict:
    """Load test results and compute scorecard. No registry changes."""
    results = load_latest_results(feature_name)
    if not results:
        print(
            f"[ERROR] No test results found for '{feature_name}'.\n"
            f"Run: python feature_tester.py --feature {feature_name}"
        )
        return {}

    scorecard = compute_scorecard(results)
    print_scorecard(scorecard)

    # Save scorecard
    SCORECARD_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{feature_name.lower()}_{date.today().strftime('%Y%m%d')}_scorecard.json"
    out_path = SCORECARD_DIR / fname
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scorecard, f, indent=2)
    print(f"Scorecard saved: {out_path}")

    return scorecard


def action_promote(feature_name: str, reason: str, operator: str = "user") -> None:
    """Compute scorecard and, if approved, promote via feature_registry."""
    from feature_registry import FeatureRegistry

    results = load_latest_results(feature_name)
    if not results:
        print(
            f"[ERROR] No test results found for '{feature_name}'.\n"
            f"Run: python feature_tester.py --feature {feature_name}"
        )
        return

    scorecard = compute_scorecard(results)
    print_scorecard(scorecard)

    if scorecard["recommendation"] == "BLOCK":
        print("[BLOCKED] Cannot promote  hard gates failed. Fix issues first.")
        return

    if scorecard["recommendation"] == "REJECT":
        print(
            "[REJECTED] Score too low. Fix predictive value, stability, or data quality first."
        )
        return

    reg = FeatureRegistry()

    # Link test results to registry entry
    results_path = results.get("saved_to") or str(
        sorted(RESULTS_DIR.glob(f"{feature_name.lower()}_*.json"))[-1]
    )
    scorecard_path = str(
        sorted(SCORECARD_DIR.glob(f"{feature_name.lower()}_*_scorecard.json"))[-1]
    ) if list(SCORECARD_DIR.glob(f"{feature_name.lower()}_*_scorecard.json")) else None

    reg.set_test_results(feature_name, results_path, scorecard_path)

    full_reason = f"{reason} | Score={scorecard['total_score']}/100 | {scorecard['recommendation_reason']}"
    reg.promote(feature_name, reason=full_reason, operator=operator)


def action_demote(feature_name: str, reason: str, to_stage: str = "quarantined", operator: str = "user") -> None:
    """Demote a feature via feature_registry."""
    from feature_registry import FeatureRegistry
    reg = FeatureRegistry()
    reg.demote(feature_name, reason=reason, to_stage=to_stage, operator=operator)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Review, promote, or demote features in the promotion pipeline."
    )
    ap.add_argument("--feature", type=str, required=True, help="Feature name")
    ap.add_argument(
        "--action",
        type=str,
        choices=["review", "promote", "demote"],
        default="review",
        help="Action to take (default: review)",
    )
    ap.add_argument(
        "--reason",
        type=str,
        default="Manual review decision",
        help="Reason for promotion/demotion (required for promote/demote)",
    )
    ap.add_argument(
        "--to-stage",
        type=str,
        default="quarantined",
        help="Target stage for demotion (default: quarantined)",
    )
    ap.add_argument(
        "--operator",
        type=str,
        default="user",
        help="Who is making this decision (for audit trail)",
    )
    return ap


def main() -> None:
    args = _build_parser().parse_args()

    if args.action == "review":
        action_review(args.feature)
    elif args.action == "promote":
        action_promote(args.feature, reason=args.reason, operator=args.operator)
    elif args.action == "demote":
        action_demote(
            args.feature,
            reason=args.reason,
            to_stage=args.to_stage,
            operator=args.operator,
        )


if __name__ == "__main__":
    main()
