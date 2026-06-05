# Branch Hygiene

The repository treats branch cleanliness as a task-start requirement, not a
cleanup step at the end.

## Install Once

```powershell
python .\scripts\check_branch_hygiene.py --install-hooks
```

This sets `core.hooksPath=.githooks` for the clone. The pre-commit hook blocks:

- direct commits to `main` or `master`;
- branches behind or diverged from `origin/main` or their upstream;
- generated/local artifacts such as `data/`, `logs/`, and PC recovery notes;
- `models/` changes outside a `model-refresh/*`, `models/refresh/*`, or
  `artifact-refresh/*` branch;
- staged bundles larger than 20 files unless they are explicitly reviewed.

## Start Every Task

```powershell
git fetch origin --prune
python .\scripts\check_branch_hygiene.py --base origin/main
```

If the check fails, stop before editing:

1. Commit coherent work or create a named, scoped stash.
2. Reconcile the branch with its upstream.
3. Rebase the task branch onto `origin/main`.
4. Create a new task branch from `origin/main` when the existing branch has
   unrelated history.

Never switch branches with a dirty worktree. Never use an unnamed stash for
task work.

## Before Every Commit

Stage explicit files, never the whole worktree by habit:

```powershell
git add <explicit paths>
git diff --cached --name-status
python .\scripts\check_branch_hygiene.py --pre-commit --base origin/main
```

Then run `gitnexus_detect_changes({scope: "staged"})`. Split a `CRITICAL`
mixed-scope bundle into coherent commits. A genuinely high-risk execution-path
change may remain `HIGH` after splitting; document it and run all direct
dependent tests rather than hiding the warning.

After committing, refresh GitNexus and verify no uncommitted scope remains:

```powershell
npx gitnexus analyze
python .\scripts\check_branch_hygiene.py --base origin/main
```
