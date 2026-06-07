"""Fail fast when a Git task branch is dirty, stale, or mixed with local artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
LIVE_WORKTREE = Path(r"D:\fund_monitor")
RESEARCH_WORKTREE = Path(r"D:\fund_monitor_research")
GROWTH24_RESEARCH_BRANCH = "growth24/research-salvage"
GROWTH24_BRANCH_PREFIX = "growth24/"
PROTECTED_BRANCHES = {"main", "master"}
MODEL_BRANCH_PREFIXES = ("model-refresh/", "models/refresh/", "artifact-refresh/")
GROWTH24_SCOPED_PREFIXES = (
    ".githooks/",
    "notes/growth24_",
    "scripts/growth24_",
    "tests/test_growth24_",
)
GROWTH24_SCOPED_NAMES = {
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/branch_hygiene.md",
    "scripts/check_branch_hygiene.py",
    "tests/test_branch_hygiene.py",
}
LOCAL_ARTIFACT_PREFIXES = (
    "data/",
    "logs/",
    "memory/",
    ".claude/",
    "notes/pc_health_",
    "notes/session_recovery_",
)
LOCAL_ARTIFACT_NAMES = {
    ".env",
    "email_log.txt",
    "email_sent.log",
    "push_log.txt",
    "report.html",
    "report.pdf",
}


class GitError(RuntimeError):
    pass


@dataclass
class HygieneState:
    root: str
    branch: str | None
    base: str
    base_exists: bool
    base_behind: int | None
    base_ahead: int | None
    upstream: str | None
    upstream_behind: int | None
    upstream_ahead: int | None
    dirty_paths: list[str] = field(default_factory=list)
    staged_paths: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    stash_count: int = 0
    hooks_path: str | None = None


@dataclass
class HygieneResult:
    state: HygieneState
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


GitRunner = Callable[[list[str], bool], str]


def _run_git(args: list[str], allow_failure: bool = False) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode and not allow_failure:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise GitError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip() if result.returncode == 0 else ""


def _normalize_path(path: str) -> str:
    return path.strip().replace("\\", "/")


def _same_worktree(root: str, expected: Path) -> bool:
    normalized_root = _normalize_path(root).rstrip("/").casefold()
    normalized_expected = _normalize_path(str(expected)).rstrip("/").casefold()
    return normalized_root == normalized_expected


def parse_status_paths(output: str) -> list[str]:
    paths: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        path = _normalize_path(line[3:] if len(line) > 3 else line)
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            paths.append(path)
    return paths


def is_local_artifact(path: str) -> bool:
    normalized = _normalize_path(path)
    return normalized in LOCAL_ARTIFACT_NAMES or normalized.startswith(LOCAL_ARTIFACT_PREFIXES)


def is_model_artifact(path: str) -> bool:
    return _normalize_path(path).startswith("models/")


def model_branch_allowed(branch: str | None) -> bool:
    return bool(branch and branch.startswith(MODEL_BRANCH_PREFIXES))


def is_growth24_scoped_path(path: str) -> bool:
    normalized = _normalize_path(path)
    if normalized in GROWTH24_SCOPED_NAMES:
        return True
    if normalized.startswith("dl_growth24_") and normalized.endswith(".py"):
        return True
    return normalized.startswith(GROWTH24_SCOPED_PREFIXES)


def _rev_counts(left: str, right: str, run_git: GitRunner) -> tuple[int | None, int | None]:
    output = run_git(["rev-list", "--left-right", "--count", f"{left}...{right}"], True)
    if not output:
        return None, None
    parts = output.replace("\t", " ").split()
    if len(parts) != 2:
        return None, None
    return int(parts[0]), int(parts[1])


def _git_path_exists(name: str, run_git: GitRunner) -> bool:
    path = run_git(["rev-parse", "--git-path", name], True)
    if not path:
        return False
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate.exists()


def _operation_names(
    run_git: GitRunner,
    path_exists: Callable[[str], bool] | None = None,
) -> list[str]:
    refs = {
        "merge": "MERGE_HEAD",
        "cherry-pick": "CHERRY_PICK_HEAD",
        "revert": "REVERT_HEAD",
    }
    operations = [
        name
        for name, ref in refs.items()
        if run_git(["rev-parse", "--verify", "--quiet", ref], True)
    ]
    exists = path_exists or (lambda name: _git_path_exists(name, run_git))
    if exists("rebase-merge") or exists("rebase-apply"):
        operations.append("rebase")
    return operations


def collect_state(base: str, run_git: GitRunner = _run_git) -> HygieneState:
    branch = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], True) or None
    base_exists = bool(run_git(["rev-parse", "--verify", "--quiet", base], True))
    base_behind, base_ahead = _rev_counts(base, "HEAD", run_git) if base_exists else (None, None)
    upstream = run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        True,
    ) or None
    upstream_behind, upstream_ahead = (
        _rev_counts(upstream, "HEAD", run_git) if upstream else (None, None)
    )
    dirty_paths = parse_status_paths(
        run_git(["status", "--porcelain=v1", "--untracked-files=all"], False)
    )
    staged_paths = [
        _normalize_path(path)
        for path in run_git(
            ["diff", "--cached", "--name-only", "--diff-filter=ACMRDTUXB"],
            False,
        ).splitlines()
        if path.strip()
    ]
    stash_output = run_git(["stash", "list", "--format=%gd"], True)
    hooks_path = run_git(["config", "--get", "core.hooksPath"], True) or None
    return HygieneState(
        root=str(ROOT),
        branch=branch,
        base=base,
        base_exists=base_exists,
        base_behind=base_behind,
        base_ahead=base_ahead,
        upstream=upstream,
        upstream_behind=upstream_behind,
        upstream_ahead=upstream_ahead,
        dirty_paths=dirty_paths,
        staged_paths=staged_paths,
        operations=_operation_names(run_git),
        stash_count=len(stash_output.splitlines()) if stash_output else 0,
        hooks_path=hooks_path,
    )


def evaluate_state(
    state: HygieneState,
    *,
    pre_commit: bool,
    allow_dirty: bool,
    allow_diverged: bool,
    allow_protected: bool,
    allow_large_commit: bool,
    max_staged_files: int,
) -> HygieneResult:
    errors: list[str] = []
    warnings: list[str] = []
    live_worktree = _same_worktree(state.root, LIVE_WORKTREE)
    research_worktree = _same_worktree(state.root, RESEARCH_WORKTREE)
    growth24_branch = bool(state.branch and state.branch.startswith(GROWTH24_BRANCH_PREFIX))

    if not state.branch:
        errors.append("HEAD is detached; create or switch to a task branch before working.")
    if live_worktree and state.branch and state.branch != "main":
        errors.append(
            r"Live worktree D:\fund_monitor must stay on main; do not checkout or switch branches there."
        )
    if research_worktree and state.branch and state.branch != GROWTH24_RESEARCH_BRANCH:
        errors.append(
            "Research worktree must stay on "
            f"{GROWTH24_RESEARCH_BRANCH!r}; use another worktree for other branches."
        )
    if growth24_branch and not research_worktree:
        errors.append(r"Growth24 branches may only be worked on from D:\fund_monitor_research.")
    if state.operations:
        errors.append(f"Git operation in progress: {', '.join(state.operations)}.")
    if not state.base_exists:
        errors.append(f"Base ref {state.base!r} does not exist; fetch before working.")
    elif state.base_behind and not allow_diverged:
        errors.append(
            f"Branch is {state.base_behind} commit(s) behind {state.base}; rebase before working."
        )
    if state.upstream and state.upstream_behind and not allow_diverged:
        errors.append(
            f"Branch is {state.upstream_behind} commit(s) behind/diverged from "
            f"{state.upstream}; reconcile it before working."
        )
    if not state.upstream:
        warnings.append("Branch has no upstream yet; push it after the first coherent commit.")
    if state.stash_count:
        warnings.append(f"{state.stash_count} stash entry/entries exist; keep them named and scoped.")
    if state.hooks_path != ".githooks":
        warnings.append(
            "Repository hooks are not installed; run "
            "`python scripts/check_branch_hygiene.py --install-hooks`."
        )

    if pre_commit:
        if live_worktree:
            errors.append(r"Commits are disabled in live worktree D:\fund_monitor.")
        if state.branch in PROTECTED_BRANCHES and not allow_protected:
            errors.append(f"Direct commits to protected branch {state.branch!r} are blocked.")
        if not state.staged_paths:
            errors.append("No staged files found.")
        local_paths = [path for path in state.staged_paths if is_local_artifact(path)]
        if local_paths:
            errors.append("Local/generated artifacts are staged: " + ", ".join(local_paths))
        model_paths = [path for path in state.staged_paths if is_model_artifact(path)]
        if model_paths and not model_branch_allowed(state.branch):
            errors.append(
                "Model artifacts may only be committed from model-refresh/*, "
                "models/refresh/*, or artifact-refresh/* branches: "
                + ", ".join(model_paths)
            )
        if growth24_branch:
            out_of_scope_paths = [
                path for path in state.staged_paths if not is_growth24_scoped_path(path)
            ]
            if out_of_scope_paths:
                errors.append(
                    "Growth24 commits may only contain scoped research or hygiene files: "
                    + ", ".join(out_of_scope_paths)
                )
        if len(state.staged_paths) > max_staged_files and not allow_large_commit:
            errors.append(
                f"{len(state.staged_paths)} files are staged; split the commit or explicitly "
                "run the checker with --allow-large-commit after review."
            )
    elif state.dirty_paths and not allow_dirty:
        errors.append(
            "Worktree is dirty; commit or create a named, scoped stash before switching "
            "branches or starting new work."
        )

    return HygieneResult(state=state, errors=errors, warnings=warnings)


def install_hooks(run_git: GitRunner = _run_git) -> None:
    run_git(["config", "core.hooksPath", ".githooks"], False)


def _print_human(result: HygieneResult) -> None:
    state = result.state
    status = "PASS" if result.ok else "FAIL"
    print(f"Branch hygiene: {status}")
    print(f"Worktree: {state.root}")
    print(f"Branch: {state.branch or 'detached'}")
    print(
        f"Base: {state.base} "
        f"(behind={state.base_behind if state.base_behind is not None else 'n/a'}, "
        f"ahead={state.base_ahead if state.base_ahead is not None else 'n/a'})"
    )
    print(
        f"Upstream: {state.upstream or 'none'} "
        f"(behind={state.upstream_behind if state.upstream_behind is not None else 'n/a'}, "
        f"ahead={state.upstream_ahead if state.upstream_ahead is not None else 'n/a'})"
    )
    print(f"Dirty paths: {len(state.dirty_paths)}")
    print(f"Staged paths: {len(state.staged_paths)}")
    for error in result.errors:
        print(f"ERROR: {error}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit task-branch Git hygiene.")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--pre-commit", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--allow-diverged", action="store_true")
    parser.add_argument("--allow-protected", action="store_true")
    parser.add_argument("--allow-large-commit", action="store_true")
    parser.add_argument("--max-staged-files", type=int, default=20)
    parser.add_argument("--install-hooks", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.install_hooks:
        install_hooks()

    try:
        state = collect_state(args.base)
    except GitError as exc:
        print(f"Branch hygiene: FAIL\nERROR: {exc}")
        return 2

    result = evaluate_state(
        state,
        pre_commit=bool(args.pre_commit),
        allow_dirty=bool(args.allow_dirty),
        allow_diverged=bool(args.allow_diverged),
        allow_protected=bool(args.allow_protected),
        allow_large_commit=bool(args.allow_large_commit),
        max_staged_files=int(args.max_staged_files),
    )
    if args.json:
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "state": asdict(result.state),
                    "errors": result.errors,
                    "warnings": result.warnings,
                },
                indent=2,
            )
        )
    else:
        _print_human(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
