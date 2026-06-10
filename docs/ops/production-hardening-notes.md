# Production Hardening — Running Engineering Notes

Living document for the PR A/B/C hardening series. Update after every PR in
this series ships. Newest material at the bottom of each section.

---

## PR A — Deploy integrity guards (SHIPPED, deployed 2026-06-09)

What it does:
- `post_run.sync_to_server()` refuses to deploy from a dirty git tree
  (`_git_dirty_code_paths`); bypass via `allow_dirty=True` or
  `EPM_ALLOW_DIRTY_DEPLOY=1`.
- Warns (does not fail) on unlisted root `.py` files so new modules can't
  silently miss the deploy list. Repo invariant test
  (`test_root_py_inventory_classified`) forces every tracked root `.py` into
  `SYNC_PY_FILES` or `_NOT_DEPLOYED_PY`.
- Restarts `epm.service` after sync and probes `/api/health` before declaring
  the deploy good.

Post-review fixes landed in commit `10e6667`.

## PR B — Watchdog + health truthfulness (SHIPPED, commit `a8a7413`, deployed 2026-06-09)

What it does:
- `services/watchdog_service.py`: daemon thread on the server, polls
  `data/latest_commentary.json` every `WATCHDOG_INTERVAL_SEC` (600s). If the
  report is missing/stale past `WATCHDOG_STALE_CUTOFF` (10:30 CST) on a market
  day, sends ONE alert email to `ALERT_EMAIL` (same-day dedup; a failed send
  is retried next tick). `WATCHDOG_ENABLED=0` suppresses the thread on laptops.
- `/api/health` extended with truthful checks: `last_run` (from
  `data/run_daily_status.json`, pushed by the laptop after every terminal
  pipeline stage), db writability (`BEGIN IMMEDIATE`), Ollama model presence
  (chat + council), watchdog liveness. Adds `reasons[]`; preserves legacy keys.
- `run_daily.py` records terminal status (`_record_status`) and pushes it to
  the server (`post_run.push_status_file`) so server health reflects the
  laptop pipeline.

## Post-deploy health probe fix (SHIPPED, commits `49152be` + `7262899`, deployed 2026-06-10)

Symptom: `post_run.py` reported "/api/health unreachable" after deploy even
though the server was healthy, poisoning `run_daily_status.json` with
`last_run_failed:post_run`.

Root cause: Cloudflare WAF blocks the `Python-urllib/3.12` User-Agent with
HTTP 403 (error code 1010). `HTTPError` is a subclass of `URLError`, so the
probe swallowed the 403 as "unreachable" with zero diagnostics.

Fix:
- `_probe_health_origin()` — SSH to the server and `curl -fsS
  http://127.0.0.1:8000/api/health` on loopback. This is the DEPLOY-CRITICAL
  check (12×5s retry window); immune to Cloudflare/WAF/UA issues.
- `_probe_health()` (public HTTPS via urllib) demoted to secondary,
  warn-only, 3 attempts; now catches `HTTPError` before `URLError` and
  surfaces the status code + body snippet.
- Expected output on every deploy: `[SYNC][WARN] Public health probe failed:
  HTTP 403 — error code: 1010` — this is Cloudflare blocking urllib's UA and
  is NOT a failure. The deploy verdict comes from `origin status=ok`.

## Mail routing policy (SHIPPED, commit `1169a3d`, deployed 2026-06-10)

Trigger: an internal status email went out through the Resend domain sender.
Policy decided 2026-06-10:

- **Resend is reserved for outward-facing product mail**: the daily report
  and subscriber transactional mail (password reset, opt-in confirmation).
- **Internal ops alerts go via Gmail only**: `run_daily._send_alert` and the
  server watchdog now call `email_service.send_message(..., provider="gmail")`.
  If `GMAIL_APP_PASSWORD` is missing they skip with a log line — they never
  fall back to Resend.
- **Daily report gains a Gmail fallback**: if the Resend SMTP send fails,
  `send_raw` re-sends via Gmail with the `From` header rewritten, so the
  report still goes out. Both-fail raises a combined `EmailError`.

New surface in `services/email_service.py`: `_gmail_config()`,
`gmail_configured()`, `provider=` parameter on `send_raw`/`send_message`
(default behavior unchanged). Tests: `tests/test_mail_routing.py` (11 tests).

**Env requirement: `GMAIL_APP_PASSWORD` must be present in BOTH the laptop
environment and `/opt/epm-market-intelligence/.env`** (optional `GMAIL_USER`
overrides the account; defaults to the legacy personal address). Without it,
server watchdog alerts skip silently (logged in journalctl).

## Current production status (2026-06-10)

- `/api/health`: `status: ok`, `reasons: []` — commentary fresh (2026-06-10),
  data files present, deep worker alive, Ollama reachable with both models,
  `last_run` stage `ok`, both DBs writable, watchdog alive.
- Guarded code paths clean; full test suite green (302 tests).
- Deploys from `main` only (branch guard, exit 3) with origin-health gate.

### Verification commands

```bash
# public health (curl UA is not blocked; urllib's is)
curl -fsS https://epm-market-intelligence.com/api/health

# origin health (what the deploy gate uses)
ssh -i ~/.ssh/epm_server dporter02@100.101.63.65 \
  "curl -fsS http://127.0.0.1:8000/api/health"

# service logs
ssh -i ~/.ssh/epm_server dporter02@100.101.63.65 \
  "journalctl -u epm.service -n 50 --no-pager"

# full suite + deploy
python -m pytest tests/ -q
python post_run.py          # origin probe is the deploy verdict
```

---

## PR C — Config centralization (PLANNED, not started)

### Problem

Service endpoints have divergent hardcoded defaults scattered across modules,
which has caused production/laptop differences before (e.g. the 6/01 Ollama
loopback incident degraded the pipeline to deterministic fallback).

### Endpoint inventory (2026-06-10)

| File:line | Constant | Env var | Hardcoded default | Note |
|---|---|---|---|---|
| `app.py:2394` | `_CHAT_OLLAMA_HOST` | `LOCAL_OLLAMA_URL` | `http://192.168.1.145:11434` | **stale LAN IP, pre-Tailscale** |
| `commentary/ollama_commentary.py:8` | `OLLAMA_HOST` | `LOCAL_OLLAMA_URL` | `http://100.101.63.65:11434` | Tailscale IP |
| `generate_market_commentary.py:61` | `OLLAMA_HOST` | `LOCAL_OLLAMA_URL` | `http://100.101.63.65:11434` | Tailscale IP |
| `local_council.py:36` | `OLLAMA_URL` | `LOCAL_OLLAMA_URL` | `http://localhost:11434` | third different default |
| `research_service.py:32` | `_OLLAMA_URL` | `LOCAL_OLLAMA_URL` | `http://localhost:11434` | |
| `deep_analysis.py:28` | `KRONOS_URL` | — (none!) | `http://127.0.0.1:8100` | no env override at all |
| `providers/searxng_provider.py:26` | `base_url` | `SEARXNG_URL` | `http://127.0.0.1:8080` | |
| `send_email.py:45-47` | `EPM_SERVER_URL` / `INTERNAL_RECIPIENTS_URL` | same | `https://epm-market-intelligence.com` | env-driven, default OK |
| `app.py:2395`, `app.py:1497`, `generate_market_commentary.py:62`, `commentary/ollama_commentary.py:9`, `local_council.py:37`, `research_service.py:33` | model names | `CHAT_OLLAMA_MODEL` / `COUNCIL_OLLAMA_MODEL` / `COMMENTARY_OLLAMA_MODEL` / `RESEARCH_OLLAMA_MODEL` | `qwen3.5:4b` / `deepseek-r1:8b` / `qwen3.5:9b` | defaults duplicated per file |
| dev scripts: `compare_llm_models.py:26`, `_test_*.py` | various | — | Tailscale IP | laptop-only, exempt |
| `post_run.py:32` | `SERVER_HOST` | — | `100.101.63.65` | deploy tooling — proposed NON-GOAL |

### Proposed design

New module **`services/runtime_config.py`** (lives in `services/` so it is
auto-synced via `SYNC_DIRS` and importable by both the server app and laptop
pipeline). One accessor per service; import-safe; no side effects beyond a
one-time resolution log.

- `ollama_url()` — **REQUIRED**: read `LOCAL_OLLAMA_URL`; if unset, raise
  `ConfigError` with a message naming the env var and both known-good values
  (server: `http://127.0.0.1:11434`, laptop: `http://100.101.63.65:11434`).
  Rationale: a wrong silent default degrades the pipeline invisibly (seen
  6/01); both machines already have `.env` files, so requiring it costs
  nothing. This also kills the stale `192.168.1.145` default in app.py.
- `kronos_url()` — allowed default `http://127.0.0.1:8100` (`KRONOS_URL` env
  gains an override it never had). Server-local sidecar; default is correct.
- `searxng_url()` — allowed default `http://127.0.0.1:8080` (`SEARXNG_URL`).
  Server-local container with graceful no-op when down.
- `epm_server_url()` / `internal_recipients_url()` — allowed default
  (public domain), moved from send_email.py.
- Model accessors: `chat_model()` (`qwen3.5:4b`), `council_model()`
  (`deepseek-r1:8b`), `commentary_model()` (`qwen3.5:9b`),
  `research_model()` (falls back to chat model) — allowed defaults, single
  source of truth instead of per-file duplicates.
- `log_resolved()` — one-line startup summary of resolved endpoints (called
  from app.py startup and pipeline entry), so prod/laptop divergence is
  visible in logs instead of discovered during incidents.

Required vs allowed defaults: **required** = anything where the correct value
differs between laptop and server (`LOCAL_OLLAMA_URL`). **Allowed default** =
server-local sidecars and the public domain, where one value is right
everywhere.

### Files likely touched

`services/runtime_config.py` (new), `app.py`, `commentary/ollama_commentary.py`,
`generate_market_commentary.py`, `local_council.py`, `research_service.py`,
`deep_analysis.py`, `providers/searxng_provider.py`, `send_email.py`,
`.env.example`, `tests/test_runtime_config.py` (new).

### Non-goals

- Prompts, model pipeline behavior, PDF/report styling, council behavior,
  auth core, cache busting, UI — untouched (caller edits are default-source
  swaps only; same env var names keep both `.env` files valid unchanged).
- `post_run.py` deploy constants (laptop-only tooling, recently hardened —
  churn risk exceeds benefit).
- Dev scripts (`_test_*.py`, `compare_llm_models.py`) — exempt, listed in the
  lint allowlist.

### Tests

1. `runtime_config` unit tests: env override wins; `ollama_url()` raises a
   clear `ConfigError` when unset; allowed defaults resolve.
2. Caller wiring tests: each migrated module resolves its endpoint through
   `runtime_config` (monkeypatch the accessor, assert propagation).
3. **Endpoint-literal lint test** (repo invariant, like
   `test_root_py_inventory_classified`): scan `git ls-files *.py` for
   `:11434|:8100|:8080|100.101.63.65|192.168.` outside the allowlist
   `{services/runtime_config.py, post_run.py, tests/, _test_*.py,
   compare_llm_models.py}`. Prevents new hardcoded endpoints from creeping in.

### Risks & decisions needed

- **R1**: making `LOCAL_OLLAMA_URL` required fails fast if either machine's
  env lacks it. Pre-deploy verification step: confirm it is present in the
  laptop env AND `/opt/epm-market-intelligence/.env` BEFORE merging the
  app.py migration. (Decision: hard-require vs warn+default `127.0.0.1`.)
- **R2**: `app.py` chat default changes from the stale LAN IP — if the server
  somehow relied on the old default (it shouldn't; env is set), chat breaks.
  Mitigated by R1 verification + origin health probe checks Ollama.
- **D1**: include model-name defaults in PR C scope? (Recommended: yes, same
  pattern, removes duplication; behavior unchanged.)
- **D2**: include `post_run.py` server host? (Recommended: no.)

### Implementation sequence (each step independently green + deployable)

1. Add `services/runtime_config.py` + unit tests (no callers yet). Commit.
2. Verify `LOCAL_OLLAMA_URL` present in both `.env`s (manual check).
3. Migrate the pipeline cluster (`generate_market_commentary`,
   `commentary/ollama_commentary`, `local_council`, `research_service`).
   Suite green. Commit.
4. Migrate `app.py` (chat host/model, council model) + `deep_analysis.py`
   (Kronos) + `searxng_provider` + `send_email.py`. Suite green. Commit.
5. Add the endpoint-literal lint test + `.env.example` docs. Commit.
6. Deploy via `python post_run.py`; verify `/api/health` `ollama.reachable`
   + both models true; watch the next 9am run end-to-end.

### Rollback plan

The module is additive and callers keep the SAME env var names, so both
`.env` files are valid before/after. Rollback = `git revert` the caller
migration commit(s) + `python post_run.py`. No env changes to undo.

---

## Open risks (running list)

- Server watchdog alerts require `GMAIL_APP_PASSWORD` on the server — if
  missing, alerts skip (logged). Verify in `/opt/epm-market-intelligence/.env`.
- Public urllib health probe permanently 403s (Cloudflare UA block) — warn
  only; do not "fix" by failing deploys on it. Consider a custom UA later.
- Research/pipeline share one working tree (laptop) — worktree split still
  open (see incident 2026-06-05, wrong-branch email).
- Gmail fallback for the daily report sends from the personal address —
  deliverability to external subscribers is worse than Resend; acceptable as
  an emergency path only.
