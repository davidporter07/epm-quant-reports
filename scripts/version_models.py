"""version_models.py — MANUAL, opt-in model versioning.

The daily pipeline (monitor.py) NO LONGER touches git. It only snapshots the
active checkpoint into models/history/<date>/ locally. If you want a git-tracked
record of model evolution, run this script by hand on a CLEAN checkout — never
from inside the scheduled report run.

It is deliberately conservative:
  - Aborts if the working tree has unrelated staged/unstaged changes.
  - Only stages the three model artefacts.
  - Commits locally. Does NOT push. You push manually after review.

Usage
-----
    python scripts/version_models.py
    python scripts/version_models.py --push   # commit AND push (after you review)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_FILES = [
    "models/dl_tcn.pt",
    "models/dl_scaler.json",
    "models/dl_feature_importance.csv",
]


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(ROOT), text=True,
                          capture_output=True, check=check)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="git push after committing")
    args = ap.parse_args()

    # Refuse to run if there are changes outside the model files — we don't want
    # to accidentally sweep unrelated work into a model commit.
    status = _git("status", "--porcelain").stdout.strip().splitlines()
    dirty = [ln for ln in status if ln[3:].strip() not in MODEL_FILES]
    if dirty:
        print("[ABORT] Working tree has changes outside the model files:")
        for ln in dirty:
            print("   ", ln)
        print("Commit/stash those first, then re-run on a clean tree.")
        return 1

    present = [m for m in MODEL_FILES if (ROOT / m).exists()]
    if not present:
        print("[SKIP] No model files present to version.")
        return 0

    _git("add", *present)
    res = _git("commit", "-m", f"Version DL model checkpoint: {date.today().isoformat()}",
               check=False)
    if res.returncode != 0:
        if "nothing to commit" in (res.stdout + res.stderr).lower():
            print("[SKIP] Model files unchanged — nothing to commit.")
            return 0
        print(f"[ERROR] commit failed: {res.stderr.strip()}")
        return 1
    print("[OK] Model checkpoint committed locally.")

    if args.push:
        push = _git("push", "origin", "HEAD", check=False)
        if push.returncode != 0:
            print(f"[ERROR] push failed (commit is safe locally): {push.stderr.strip()}")
            return 1
        print("[OK] Pushed.")
    else:
        print("Review with `git show`, then `git push` manually when ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
