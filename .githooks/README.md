# Git hooks (`.githooks/`)

Version-controlled git hooks for this repo. Tracked here (not in `.git/hooks/`,
which is local-only and never travels with the repo) so they can't silently
disappear or drift.

## Activation (one-time, per clone/machine)

Git config is **not** part of the repo, so each working copy must be pointed at
this directory once:

```bash
git config core.hooksPath .githooks
```

Verify with `git config --get core.hooksPath` (should print `.githooks`).
When set, git runs hooks from here and **ignores `.git/hooks/`**.

## Hooks

### `post-commit` — GitNexus auto-reindex

Rebuilds the GitNexus code index after every commit so it never goes stale
(see CLAUDE.md "Keeping the Index Fresh"). Runs detached, so your commit returns
immediately; the reindex finishes in the background.

**Visibility:** all output is logged to `.gitnexus/reindex.log` (gitignored).
If the index ever stops updating, check that file first — the last block shows
`exit rc=N` (0 = success). This logging is deliberate: the previous hook threw
its errors away (`2>/dev/null`), which is how it stayed broken unnoticed.

Embeddings are preserved automatically (the hook adds `--embeddings` only when
`.gitnexus/meta.json` shows a non-zero count).

Runs with `--skip-agents-md` so it does **not** touch `AGENTS.md` / `CLAUDE.md` on
every commit (the gitnexus section there carries a volatile symbol/relationship
count that otherwise dirtied both files each run — and `--no-stats` does *not*
suppress it in this version, only `--skip-agents-md` does). The graph index still
updates fully. Drop `--skip-agents-md` if you want that section kept live.
