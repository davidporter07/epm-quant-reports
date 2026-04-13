"""dl_feature_gate.py
Single source of truth for which features enter the deep learning model.

The DL model MUST call get_approved_features() instead of using a hardcoded
list. This ensures only features that have passed the promotion pipeline are
used for training.

Design rules:
  - This module has NO training logic  it only reads the approved list.
  - If the registry is unavailable, falls back to FALLBACK_FEATURES so the
    pipeline never hard-crashes (but logs a clear warning).
  - The fallback list MUST match the original FEATURE_COLS_DEFAULT exactly 
    it represents the pre-pipeline baseline.

Usage:
    from dl_feature_gate import get_approved_features

    feature_cols = get_approved_features()          # call once, pass to train_model()
    feature_cols = get_approved_features(verbose=True)  # log what was loaded

CLI:
    python dl_feature_gate.py           # print current approved list
    python dl_feature_gate.py --check   # verify features exist in panel
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

# Managed by feature_registry.py  rebuilt whenever a feature is promoted/demoted
APPROVED_PATH = Path("feature_store/approved/dl_approved_features.json")

# ---------------------------------------------------------------------------
# Fallback: original hardcoded feature set that was in production before the
# promotion pipeline was established. These have been implicitly "approved"
# by being in production. Do NOT add new features here  use the registry.
# ---------------------------------------------------------------------------
FALLBACK_FEATURES: List[str] = [
    "Ret_1D",
    "Ret_5D",
    "Ret_21D",
    "Ret_63D",
    "Ret_252D",
    "Vol_21D",
    "Vol_63D",
    "Gap_MA20",
    "Gap_MA50",
    "Gap_MA200",
]


def get_approved_features(verbose: bool = False) -> List[str]:
    """Return the current DL-approved feature list.

    Reads from feature_store/approved/dl_approved_features.json.
    This file is rebuilt by feature_registry.py whenever a feature is
    promoted to or demoted from 'dl_approved' or 'production_critical'.

    Falls back to FALLBACK_FEATURES if the registry has not been initialized
    (e.g., first run) so the model never hard-crashes.

    Args:
        verbose: If True, print what was loaded and the last-updated date.

    Returns:
        List of panel column names approved for DL training. Preserves the
        order from the approved list (promotion order matters for warm-start
        compatibility).
    """
    if APPROVED_PATH.exists():
        try:
            with open(APPROVED_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            cols = data.get("feature_cols", [])
            if cols:
                if verbose:
                    print(
                        f"[DL Gate] {len(cols)} approved features "
                        f"(updated {data.get('last_updated', 'unknown')})"
                    )
                return list(cols)
        except Exception as exc:
            print(f"[DL Gate] WARNING: could not read approved list ({exc}). Using fallback.")

    if verbose:
        print(
            f"[DL Gate] No approved features file found at {APPROVED_PATH}. "
            f"Using {len(FALLBACK_FEATURES)} fallback features (pre-pipeline baseline).\n"
            f"[DL Gate] Initialize the registry: python feature_registry.py --rebuild"
        )
    return list(FALLBACK_FEATURES)


def get_feature_count() -> int:
    """Return the number of currently approved DL features."""
    return len(get_approved_features())


def check_features_in_panel(panel_path: Path | None = None) -> None:
    """Verify that all approved features exist in the training panel.

    Useful for catching column name drift before a training run.

    Args:
        panel_path: Path to training_panel.parquet. Defaults to the standard location.
    """
    import pandas as pd  # lazy import  only needed for this check

    panel_path = panel_path or Path("data/training_panel.parquet")
    if not panel_path.exists():
        print(f"[DL Gate] Panel not found: {panel_path}")
        return

    panel = pd.read_parquet(panel_path, columns=None)
    panel_cols = set(panel.columns)
    approved = get_approved_features()

    missing = [c for c in approved if c not in panel_cols]
    present = [c for c in approved if c in panel_cols]

    print(f"\nDL Feature Gate  panel check ({panel_path})")
    print(f"  Approved features : {len(approved)}")
    print(f"  Found in panel    : {len(present)}")
    print(f"  Missing from panel: {len(missing)}")

    if missing:
        print("\n[WARN] Features not found in panel (will cause NaN sequences):")
        for m in missing:
            print(f"  - {m}")
    else:
        print("\n[OK] All approved features present in panel.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Show or verify the current DL-approved feature list."
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Verify features exist in data/training_panel.parquet",
    )
    ap.add_argument(
        "--panel",
        type=str,
        default=None,
        help="Path to training panel (default: data/training_panel.parquet)",
    )
    args = ap.parse_args()

    if args.check:
        check_features_in_panel(
            panel_path=Path(args.panel) if args.panel else None
        )
        return

    cols = get_approved_features(verbose=True)
    print(f"\nApproved DL features ({len(cols)}):")
    for i, c in enumerate(cols, 1):
        print(f"  {i:2d}. {c}")


if __name__ == "__main__":
    main()
