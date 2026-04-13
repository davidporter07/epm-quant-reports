"""feature_registry.py
Central registry for the EPM feature promotion pipeline.

Every predictor that enters the deep learning model must be registered here
and pass the full promotion workflow before it can be used for DL training.

Lifecycle stages (in order):
    experimental -> sandbox_approved -> dl_approved -> production_critical
    (any stage) -> quarantined

Usage:
    python feature_registry.py               # print summary
    python feature_registry.py --verbose     # full feature list

    from feature_registry import FeatureRegistry
    reg = FeatureRegistry()
    reg.list_all(verbose=True)
    reg.promote("log_volume", reason="passed IC walk-forward at 0.06 mean IC")
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REGISTRY_PATH = Path("feature_store/registry/feature_registry.json")
APPROVED_PATH = Path("feature_store/approved/dl_approved_features.json")
CHANGELOG_PATH = Path("feature_store/approved/feature_changelog.csv")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STAGES = [
    "experimental",
    "sandbox_approved",
    "dl_approved",
    "production_critical",
    "quarantined",
]

# Features in these stages are eligible to enter DL training
DL_ELIGIBLE_STAGES: frozenset = frozenset({"dl_approved", "production_critical"})

# Ordered index for promotion (quarantined excluded from ordering)
_STAGE_ORDER = {s: i for i, s in enumerate(STAGES[:-1])}


# ---------------------------------------------------------------------------
# Low-level I/O
# ---------------------------------------------------------------------------


def _load_registry() -> Dict:
    if not REGISTRY_PATH.exists():
        return {}
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_registry(registry: Dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, default=str)


def _append_changelog(entry: dict) -> None:
    CHANGELOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not CHANGELOG_PATH.exists()
    fieldnames = ["date", "feature", "from_stage", "to_stage", "reason", "operator"]
    with open(CHANGELOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        writer.writerow(entry)


def _rebuild_approved_list(registry: Dict) -> None:
    """Rebuild dl_approved_features.json from current registry state."""
    approved_cols = [
        v["panel_column"]
        for v in registry.values()
        if v["stage"] in DL_ELIGIBLE_STAGES
    ]
    APPROVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(APPROVED_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "feature_cols": approved_cols,
                "last_updated": str(date.today()),
                "total_features": len(approved_cols),
                "stages_included": sorted(DL_ELIGIBLE_STAGES),
            },
            f,
            indent=2,
        )
    print(f"[OK] DL approved features updated: {len(approved_cols)} features -> {APPROVED_PATH}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class FeatureRegistry:
    """Interface to the feature promotion registry."""

    def add(
        self,
        name: str,
        *,
        description: str,
        source: str,
        feature_type: str,
        panel_column: str,
        first_available_date: str,
        update_frequency: str = "daily",
        lag_days: int = 1,
        point_in_time: bool = True,
        target_use: str = "21-day forward return prediction",
        stage: str = "experimental",
        notes: str = "",
        operator: str = "system",
    ) -> None:
        """Register a new feature candidate.

        Args:
            name: Unique feature name (matches key in registry).
            description: Human-readable description.
            source: Data source identifier (e.g. 'yfinance_ohlcv', 'ycharts_scraper').
            feature_type: Category (e.g. 'price_momentum', 'sentiment', 'fundamental_valuation').
            panel_column: Exact column name in training_panel.parquet.
            first_available_date: Earliest date this feature is reliably available (YYYY-MM-DD).
            update_frequency: How often the feature updates ('daily', 'weekly', 'quarterly').
            lag_days: Minimum lag between feature date and its availability for prediction.
            point_in_time: True if no future data is used in computation.
            target_use: What this feature is intended to predict.
            stage: Starting lifecycle stage (default: 'experimental').
            notes: Any caveats, risks, or implementation notes.
            operator: Who is registering (for audit trail).
        """
        registry = _load_registry()
        if name in registry:
            raise ValueError(
                f"Feature '{name}' already exists. Use update_notes() or promote()/demote()."
            )
        if stage not in STAGES:
            raise ValueError(f"Invalid stage '{stage}'. Must be one of {STAGES}")

        today = str(date.today())
        registry[name] = {
            "name": name,
            "version": "1.0",
            "stage": stage,
            "description": description,
            "source": source,
            "feature_type": feature_type,
            "panel_column": panel_column,
            "first_available_date": first_available_date,
            "update_frequency": update_frequency,
            "lag_days": lag_days,
            "point_in_time": point_in_time,
            "target_use": target_use,
            "notes": notes,
            "added_date": today,
            "promoted_date": today if stage != "experimental" else None,
            "promoted_by": operator if stage != "experimental" else None,
            "test_results_path": None,
            "scorecard_path": None,
            "last_checked": today,
        }
        _save_registry(registry)
        _append_changelog({
            "date": today,
            "feature": name,
            "from_stage": "new",
            "to_stage": stage,
            "reason": "Initial registration",
            "operator": operator,
        })
        print(f"[OK] Feature '{name}' registered at stage '{stage}'")

        if stage in DL_ELIGIBLE_STAGES:
            _rebuild_approved_list(registry)

    def promote(
        self, name: str, *, reason: str, operator: str = "system"
    ) -> None:
        """Advance a feature to the next lifecycle stage.

        A feature must have test results before being promoted to dl_approved.
        Use feature_tester.py to generate test results first.
        """
        registry = _load_registry()
        if name not in registry:
            raise KeyError(f"Feature '{name}' not found in registry.")

        current = registry[name]["stage"]
        if current == "quarantined":
            raise ValueError(
                f"'{name}' is quarantined. Use restore() before promoting."
            )
        if current == "production_critical":
            raise ValueError(
                f"'{name}' is already at production_critical (highest stage)."
            )
        if current not in _STAGE_ORDER:
            raise ValueError(f"Unknown current stage '{current}'.")

        # Require test results before entering DL training
        next_stage = STAGES[_STAGE_ORDER[current] + 1]
        if next_stage in DL_ELIGIBLE_STAGES:
            if not registry[name].get("test_results_path"):
                raise ValueError(
                    f"Feature '{name}' has no test results. "
                    f"Run: python feature_tester.py --feature {name}\n"
                    f"Then: python feature_promoter.py --feature {name} --action promote"
                )

        from_stage = current
        today = str(date.today())
        registry[name]["stage"] = next_stage
        registry[name]["promoted_date"] = today
        registry[name]["promoted_by"] = operator
        registry[name]["last_checked"] = today
        _save_registry(registry)

        _append_changelog({
            "date": today,
            "feature": name,
            "from_stage": from_stage,
            "to_stage": next_stage,
            "reason": reason,
            "operator": operator,
        })

        if next_stage in DL_ELIGIBLE_STAGES or from_stage in DL_ELIGIBLE_STAGES:
            _rebuild_approved_list(registry)

        print(f"[OK] '{name}' promoted: {from_stage} -> {next_stage}")

    def demote(
        self,
        name: str,
        *,
        reason: str,
        to_stage: str = "quarantined",
        operator: str = "system",
    ) -> None:
        """Demote a feature (default: quarantine).

        Use this when a feature shows drift, data quality issues, or performance
        degradation in production.
        """
        registry = _load_registry()
        if name not in registry:
            raise KeyError(f"Feature '{name}' not found in registry.")
        if to_stage not in STAGES:
            raise ValueError(f"Invalid target stage '{to_stage}'.")

        from_stage = registry[name]["stage"]
        today = str(date.today())
        registry[name]["stage"] = to_stage
        registry[name]["last_checked"] = today
        _save_registry(registry)

        _append_changelog({
            "date": today,
            "feature": name,
            "from_stage": from_stage,
            "to_stage": to_stage,
            "reason": reason,
            "operator": operator,
        })

        if from_stage in DL_ELIGIBLE_STAGES:
            _rebuild_approved_list(registry)

        print(f"[WARN] '{name}' demoted: {from_stage} -> {to_stage}")
        print(f"       Reason: {reason}")

    def restore(
        self, name: str, *, to_stage: str, reason: str, operator: str = "system"
    ) -> None:
        """Restore a quarantined feature to a specified stage."""
        registry = _load_registry()
        if name not in registry:
            raise KeyError(f"Feature '{name}' not found.")
        if registry[name]["stage"] != "quarantined":
            print(f"[INFO] '{name}' is not quarantined (stage: {registry[name]['stage']})")
            return
        if to_stage not in STAGES or to_stage == "quarantined":
            raise ValueError(f"Invalid restore stage '{to_stage}'.")

        today = str(date.today())
        registry[name]["stage"] = to_stage
        registry[name]["last_checked"] = today
        _save_registry(registry)

        _append_changelog({
            "date": today,
            "feature": name,
            "from_stage": "quarantined",
            "to_stage": to_stage,
            "reason": reason,
            "operator": operator,
        })

        if to_stage in DL_ELIGIBLE_STAGES:
            _rebuild_approved_list(registry)

        print(f"[OK] '{name}' restored to '{to_stage}'")

    def set_test_results(
        self,
        name: str,
        results_path: str,
        scorecard_path: Optional[str] = None,
    ) -> None:
        """Record the path to test results for a feature after running feature_tester.py."""
        registry = _load_registry()
        if name not in registry:
            raise KeyError(f"Feature '{name}' not found.")
        registry[name]["test_results_path"] = results_path
        if scorecard_path:
            registry[name]["scorecard_path"] = scorecard_path
        registry[name]["last_checked"] = str(date.today())
        _save_registry(registry)
        print(f"[OK] Test results path set for '{name}'")

    def update_notes(self, name: str, notes: str) -> None:
        """Update the notes field for a feature (non-structural change)."""
        registry = _load_registry()
        if name not in registry:
            raise KeyError(f"Feature '{name}' not found.")
        registry[name]["notes"] = notes
        _save_registry(registry)

    def get_dl_features(self) -> List[str]:
        """Return panel column names approved for DL training."""
        if APPROVED_PATH.exists():
            with open(APPROVED_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("feature_cols", [])
        # Build directly from registry
        registry = _load_registry()
        return [
            v["panel_column"]
            for v in registry.values()
            if v["stage"] in DL_ELIGIBLE_STAGES
        ]

    def get_by_stage(self, stage: str) -> List[dict]:
        """Return all feature entries at a given stage."""
        if stage not in STAGES:
            raise ValueError(f"Unknown stage '{stage}'")
        registry = _load_registry()
        return [v for v in registry.values() if v["stage"] == stage]

    def get(self, name: str) -> dict:
        """Return the registry entry for a single feature."""
        registry = _load_registry()
        if name not in registry:
            raise KeyError(f"Feature '{name}' not found.")
        return dict(registry[name])

    def list_all(self, verbose: bool = False) -> None:
        """Print registry summary."""
        registry = _load_registry()
        stage_counts: Dict[str, int] = {}
        for v in registry.values():
            s = v["stage"]
            stage_counts[s] = stage_counts.get(s, 0) + 1

        print(f"\nFeature Registry  ({len(registry)} features total)")
        print("=" * 55)
        for stage in STAGES:
            count = stage_counts.get(stage, 0)
            marker = " [DL eligible]" if stage in DL_ELIGIBLE_STAGES else ""
            print(f"  {stage:<25s}: {count:3d} features{marker}")

        if verbose:
            print()
            for stage in STAGES:
                entries = [v for v in registry.values() if v["stage"] == stage]
                if not entries:
                    continue
                print(f"\n--- {stage.upper()} ---")
                for v in sorted(entries, key=lambda x: x["name"]):
                    pit = "PIT" if v.get("point_in_time") else "non-PIT"
                    tested = "[tested]" if v.get("test_results_path") else ""
                    print(
                        f"  {v['name']:<22s}  col:{v['panel_column']:<22s}"
                        f"  lag:{v['lag_days']:>2d}d  {pit}  {tested}"
                    )
                    print(f"    {v['description'][:70]}")

    def rebuild_approved_list(self) -> None:
        """Force-rebuild dl_approved_features.json from current registry state."""
        registry = _load_registry()
        _rebuild_approved_list(registry)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="EPM Feature Registry  inspect and manage the feature lifecycle."
    )
    ap.add_argument("--verbose", "-v", action="store_true", help="Show full feature list")
    ap.add_argument("--stage", help="Filter to a specific stage")
    ap.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild the dl_approved_features.json from current registry",
    )
    return ap


def main() -> None:
    args = _build_parser().parse_args()
    reg = FeatureRegistry()

    if args.rebuild:
        reg.rebuild_approved_list()
        return

    if args.stage:
        entries = reg.get_by_stage(args.stage)
        print(f"\n{len(entries)} features at stage '{args.stage}':")
        for e in entries:
            print(f"  {e['name']:<25s}  {e['panel_column']:<25s}  {e['description'][:50]}")
        return

    reg.list_all(verbose=args.verbose)

    # Show current DL feature list
    dl_cols = reg.get_dl_features()
    print(f"\nDL-approved features ({len(dl_cols)}):")
    for c in dl_cols:
        print(f"  - {c}")


if __name__ == "__main__":
    main()
