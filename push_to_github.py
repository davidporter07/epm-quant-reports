# push_to_github.py
import subprocess
import sys
from datetime import datetime
from pathlib import Path

def run(args, cwd, check=False):
    """Run a command and return (code, combined_output)."""
    res = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    out = (res.stdout or "") + (res.stderr or "")
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{out}")
    return res.returncode, out

def has_changes(repo_dir: Path) -> bool:
    code, out = run(["git", "status", "--porcelain"], cwd=repo_dir)
    return bool(out.strip())

def main():
    print(" Committing and pushing report to GitHub...")

    here = Path(__file__).resolve().parent
    repo_dir = here / "epm-quant-reports"
    if not repo_dir.exists():
        # Allow running from inside the site repo directly
        repo_dir = here

    # Sanity: ensure we're in a git repo
    code, out = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_dir)
    if code != 0 or "true" not in out.lower():
        print(" Not inside a git repository:", repo_dir)
        sys.exit(1)

    stashed = False

    # If there are local changes (generated report), stash them so pull/rebase can run
    if has_changes(repo_dir):
        print(" Stashing local generated changes...")
        code, out = run(["git", "stash", "push", "-u", "-m", "generated report"], cwd=repo_dir)
        if code != 0:
            print(" Failed to stash changes:\n", out)
            sys.exit(1)
        stashed = True

    # Always sync latest remote changes first
    print(" Pulling latest changes (rebase)...")
    code, out = run(["git", "pull", "--rebase", "origin", "main"], cwd=repo_dir)
    if code != 0:
        print(" git pull --rebase failed:\n", out)
        # Try to abort any in-progress rebase to leave repo in a clean state
        run(["git", "rebase", "--abort"], cwd=repo_dir)
        sys.exit(1)

    # Restore stashed generated changes
    if stashed:
        print(" Restoring stashed changes...")
        code, out = run(["git", "stash", "pop"], cwd=repo_dir)
        if code != 0:
            # If stash pop conflicts, prefer OUR generated files
            print(" Stash pop had conflicts; resolving by preferring local generated outputs...")
            run(["git", "checkout", "--ours", "--", "index.html"], cwd=repo_dir)
            run(["git", "checkout", "--ours", "--", "report.html"], cwd=repo_dir)
            # These may or may not exist depending on run
            run(["git", "checkout", "--ours", "--", "report.pdf"], cwd=repo_dir)
            run(["git", "checkout", "--ours", "--", "charts"], cwd=repo_dir)
            run(["git", "add", "-A"], cwd=repo_dir)

    # If nothing changed after restore, we're done
    if not has_changes(repo_dir):
        print(" No site changes to commit.")
        sys.exit(0)

    # Stage + commit
    run(["git", "add", "-A"], cwd=repo_dir, check=True)

    msg_date = datetime.now().strftime("%Y-%m-%d")
    commit_msg = f" Daily quant report: {msg_date}"

    # Commit may fail if nothing to commit (race condition); handle gracefully
    code, out = run(["git", "commit", "-m", commit_msg], cwd=repo_dir)
    if code != 0:
        if "nothing to commit" in out.lower():
            print(" Nothing to commit after staging.")
        else:
            print(" git commit failed:\n", out)
            sys.exit(1)

    # Push (and rebase+retry once if remote advanced again)
    print(" Pushing to GitHub...")
    code, out = run(["git", "push", "origin", "main"], cwd=repo_dir)
    if code == 0:
        print(" Pushed to GitHub")
        sys.exit(0)

    # Retry once if rejected
    if "fetch first" in out.lower() or "non-fast-forward" in out.lower() or "rejected" in out.lower():
        print(" Push rejected; rebasing and retrying once...")
        code2, out2 = run(["git", "pull", "--rebase", "origin", "main"], cwd=repo_dir)
        if code2 != 0:
            print(" Retry pull --rebase failed:\n", out2)
            run(["git", "rebase", "--abort"], cwd=repo_dir)
            sys.exit(1)

        code3, out3 = run(["git", "push", "origin", "main"], cwd=repo_dir)
        if code3 == 0:
            print(" Pushed to GitHub")
            sys.exit(0)

        print(" Push failed after retry:\n", out3)
        sys.exit(1)

    print(" Git push failed:\n", out)
    sys.exit(1)

if __name__ == "__main__":
    main()



