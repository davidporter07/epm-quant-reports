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

## PR C — Config centralization (IMPLEMENTED 2026-06-10, pending deploy approval)

Implemented as planned below, in four staged commits:
1. `services/runtime_config.py` + 16 unit tests (no callers)
2. pipeline cluster migrated (generate_market_commentary,
   commentary/ollama_commentary, local_council, research_service)
3. app.py (stale LAN default eliminated), deep_analysis (KRONOS_URL env
   override added), searxng_provider, send_email
4. endpoint-literal lint test (`tests/test_endpoint_literals.py`) +
   `.env.example` docs; lint immediately caught and fixed two leftover
   literals (email_service docstring LAN IP, searxng docstring default)

Decisions taken: R1 hard-require `LOCAL_OLLAMA_URL` (verified present in
BOTH .envs before stage 2 — server returned grep count 1); D1 model-name
defaults centralized; D2 post_run.py excluded. Env var names unchanged.

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
- The module must `load_dotenv(override=False)` on import (same pattern as
  `email_service`): laptop pipeline processes (`run_daily.py`,
  `generate_market_commentary.py`) do NOT otherwise load `.env`, so a
  required `LOCAL_OLLAMA_URL` would falsely fail on the laptop without this.

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
  env lacks it. Laptop `.env` VERIFIED 2026-06-10 (has `LOCAL_OLLAMA_URL` +
  `EPM_SERVER_URL`). Server still unverified — run on the server:
  `sudo grep -c "^LOCAL_OLLAMA_URL=." /opt/epm-market-intelligence/.env`
  (want `1`) BEFORE merging the app.py migration.
  (Decision: hard-require vs warn+default `127.0.0.1`.)
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

## PR D — Data freshness hard gates (IMPLEMENTED 2026-06-10, pending deploy approval)

Prevents stale market-data inputs from silently producing reports. Root cause: the
YCharts scraper was frozen for 24+ days (5/08→6/01) with only a console warning.

### Design

New module `services/data_freshness.py` — pure functions, injectable params for
tests, never raises out of the check runner. Results persisted to
`data/data_freshness.json` (synced via `data/` SYNC_DIRS) so `/api/health`
surfaces pipeline-time verdicts; server never re-runs mtime checks.

**Critical checks** (block email when `DATA_FRESHNESS_ENFORCE=1`):

| Check | File | Rule |
|---|---|---|
| `ycharts_scrape` | `data/ycharts_live.json` | `scrape_date` ≤ `FRESH_YCHARTS_MAX_AGE_DAYS` (default 3) |
| `features_csv` | `data/features_from_ycharts.csv` | exists + mtime ≤ max age |
| `arbitrated` | `data/market_data_arbitrated.json` | `arbitrated_date == today` on market days |

**Optional checks** (warn only, never block):
`enrichment`, `economic_calendar`, `dl_forecasts`

### Wiring

- `send_email.py`: after the narrative gate — run checks, write report, print warns,
  block if `gate_message()` returns non-None (enforce=1 + critical fail only).
- `post_run.py`: warn-only summary before sync. Never blocks manual deploys.
- `app.py /api/health`: new `checks["data_freshness"]` section. File absent = not
  degraded. Degrades only when report shows critical fail + enforce=true + market open.

### Deployment sequence

1. `python -m pytest tests/ -q` → 350 passed.
2. Add to **laptop** `.env`: `DATA_FRESHNESS_ENFORCE=0` (and server `.env` for parity).
3. `python post_run.py` — services/data_freshness.py syncs, health shows
   `data_freshness: {present: false}` until the first pipeline run.
4. Observe tomorrow's 9am run: warn lines in send_email output,
   `data/data_freshness.json` produced + synced, health `present:true`.
5. After clean observed run: set `DATA_FRESHNESS_ENFORCE=1` in laptop `.env`.
   No redeploy needed for the pipeline gate.

### Rollback

- **Behavior**: set `DATA_FRESHNESS_ENFORCE=0` — instant, no code change.
- **Code**: `git revert a70365a ffb5bf3 ad41fe7` + `python post_run.py`.

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


---

## PR E — Send-path hardening (idempotent sends, partial-failure visibility)

**Commits:** 4643fc2->4008ead (6 commits on main, 2026-06-11)

### What changed
- send_raw/send_message return provider: "resend", "gmail", "gmail_fallback"
- NEW services/send_ledger.py: per-recipient ledger (logs/email_send_ledger.json, laptop-local PII) + counts-only summary (data/email_send_summary.json, auto-synced)
- send_email.py: ledger idempotency, EXIT_PARTIAL_SEND=6, fetch_daily_recipients() returns (list, fetch_ok), _check_pdf() at runtime
- run_daily.py: exit-6 branch deploys + alerts
- app.py: check 9 email_send; degrades on partial/internal/fetch failures

### Exit codes
- 0: Full success; legacy email_sent.log marked
- 1: Hard failure (all sends failed, PDF blocked, commentary stale)
- 6: Partial send (some failed or fetch failed); site still deploys

### Retry after partial
    python send_email.py --send-only
Sends only to recipients not yet ok in ledger. Exits 0 + marks legacy log on full success.

### Artifacts
- logs/email_send_ledger.json -- laptop-local, never synced, contains addresses
- data/email_send_summary.json -- counts/booleans only, syncs to server, NO addresses

### Health: checks.email_send
- present:false = no run yet, not degraded
- failed>0 -> email_send:partial_failure (today + market open)
- internal_ok:false -> email_send:internal_failed
- fetch_ok:false -> email_send:subscriber_fetch_failed
- fallback_used, pdf_ok = info-only

### Rollback
    git revert <commits>  # minimally commit 4+5
    python post_run.py
Legacy email_sent.log written on full success so reverted code still works.
Edge: mid-day rollback after partial (no legacy line) -- manually append a timestamp
line to email_sent.log before any re-run to prevent duplicate sends.

### Env flags
- SEND_REQUIRE_PDF=0 (default warn-only); set 1 to block on missing/stale PDF

---

## PR F — Pre-scale hardening (SHIPPED, deployed + VALIDATED 2026-06-11)

Six staged commits (5806c8e → b5388db) closing the scale/resilience gaps identified
in audit, plus probe-diagnostic commit 5e5c849. No prompts, model behavior,
report/PDF, UI, auth business logic, or data-freshness rules were touched.

### Validation result (2026-06-11)

- `/api/health`: `status: ok`, `reasons: []`; `deploy.present: true` showing the
  live commit; `rate_limit.enforce: false`.
- Server `users.db` `PRAGMA journal_mode` → `wal`.
- Proxy/real-IP keying CONFIRMED: journalctl shows the real client IP
  (IPv6), not 127.0.0.1.
- The original suggest-tickers warn probe was REPLACED by the auth_login probe
  (see verification step 5 below). data_cheap's 120-per-sliding-60s threshold is
  unreachable by a sequential curl loop through Cloudflare TLS (~0.4–0.8s/req),
  so that probe could never fire — confirmed not a code bug by regression test
  (`test_suggest_tickers_burst_emits_would_429_in_warn_mode`).
- Corrected auth_login probe (17 junk POSTs) PRODUCED the expected
  `[rate_limit][WARN] would-429 bucket=auth_login` lines with the real client IP.
- **`RATE_LIMIT_ENFORCE` remains 0 by design.** Do not flip to 1 until the
  warn-only observation window has been reviewed (operator decision; flip
  procedure below).

### What it does

**C1 — users.db WAL + busy_timeout (enforced immediately)**
`services/auth_service._get_conn()` now mirrors `research_store._connect()`:
`timeout=10.0`, `journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`.
Eliminates `OperationalError("database is locked")` on concurrent auth writes
(default was busy_timeout=0, DELETE journaling).

`post_run._SERVER_MANAGED` gains `users.db-wal/-shm` and
`research_cache.db-wal/-shm` so a laptop dev run after WAL migration cannot push
foreign WAL sidecars next to the server's live DB (corruption vector, would have
been silent).

**C2 — `_client_ip()` proxy-aware keying (enforced immediately — bug fix)**
All existing rate limits keyed on `request.client.host` which is `127.0.0.1`
behind Cloudflare → nginx → uvicorn, making "per-IP" limits effectively global
(one abuser exhausted everyone's forgot-password budget). New helper:
CF-Connecting-IP → XFF first hop → client.host fallback. Existing four limit
sites migrated.

**C3 — New rate-limit buckets behind `RATE_LIMIT_ENFORCE=0` (warn-only first)**
Middleware + bucket table for: `auth_login` (15/300s), `auth_register` (5/3600s),
`email_links` (30/600s), `data_cheap` (120/60s), `data_expensive` (30/60s).
Inline `deep_enqueue`: 6/3600s per user + 12/3600s per IP.
Never limited: `/api/health`, OPTIONS, `/api/internal/`, `/static/`.
Existing proven limits are always enforced regardless of the flag.

**C4 — Cache-bust lint + fix 2 violations (enforced immediately)**
`login.html:8` and `reset-password.html:8` referenced `fonts.css` with no `?v=`
— static files are served `max-age=604800,immutable` so browsers cached stale
fonts indefinitely (proven incident class from deep_analysis.js). Fixed:
`?v=20260611a`. New `tests/test_static_versioning.py` (3 assertions, pure
filesystem) guards against recurrence.

**C5 — Deploy stamp + health check 10 (info-only)**
`post_run._write_deploy_stamp()` writes `data/deploy_stamp.json {commit, ts}`
after the dirty-guard passes; the file rides the existing `data/` scp.
`/api/health` check 10 exposes `deploy.commit/ts/age_hours` and
`rate_limit.enforce` (info-only, never touches overall_ok). Addresses the
wrong-branch incident class (6/05: no way to confirm which commit was actually
live on the server).

### Rate-limit bucket table

| Bucket | Endpoints | Limit | Window |
|---|---|---|---|
| `auth_login` | POST /api/auth/login | 15 | 300s |
| `auth_register` | POST /api/auth/register | 5 | 3600s |
| `email_links` | /email/confirm, /unsubscribe | 30 | 600s |
| `data_cheap` | ticker-tape, quotes, home, markets, portfolios, forecasts, commentary, enrichment, suggest-tickers | 120 | 60s |
| `data_expensive` | snapshot, chart, fund-page, forecast-chart-data | 30 | 60s |
| `deep_enqueue` | POST /api/deep/{ticker} (post-auth) | 6/user + 12/IP | 3600s |

### Verification after deploy

```bash
# 1. Suite green
python -m pytest tests/ -q

# 2. Health: deploy.present:true, rate_limit.enforce:false, status:ok
curl -fsS https://epm-market-intelligence.com/api/health | python -m json.tool

# 3. users.db WAL confirmed on server
ssh -i ~/.ssh/epm_server dporter02@100.101.63.65 \
  "sqlite3 /opt/epm-market-intelligence/data/users.db 'PRAGMA journal_mode;'"
# Expected: wal

# 4. deploy.commit matches local HEAD
git rev-parse --short=12 HEAD
# Should match health deploy.commit

# 5. Proxy-header verification (REQUIRED before flipping RATE_LIMIT_ENFORCE=1)
# DO NOT probe with /api/suggest-tickers: data_cheap is 120 req per SLIDING
# 60s window, and a sequential curl loop through Cloudflare TLS (~0.4-0.8s
# per request) cannot sustain >2 req/s — the threshold is never crossed and
# no warn log appears (observed 2026-06-11; limiter was working correctly).
#
# Use the auth_login bucket instead (15/300s — trivially reachable, no
# yfinance cost; junk credentials just return 401):
#   for i in $(seq 1 17); do
#     curl -s -o /dev/null -X POST \
#       https://epm-market-intelligence.com/api/auth/login \
#       -H 'Content-Type: application/json' \
#       -d '{"username":"rl-probe","password":"x","remember_me":false}'
#   done
# Then on server:
#   journalctl -u epm.service --since '10 min ago' | grep rate_limit
# Expect: [rate_limit][WARN] would-429 bucket=auth_login path=/api/auth/login ip=<laptop public IP>
# The logged ip= must be the laptop's public IP, NOT 127.0.0.1.
# If 127.0.0.1: add proxy_set_header X-Forwarded-For to nginx FIRST.
```

### Flag flip procedure (after clean observation window)

```bash
# On server — no code change or redeploy needed:
echo "RATE_LIMIT_ENFORCE=1" >> /opt/epm-market-intelligence/.env
sudo systemctl restart epm.service
curl -fsS http://127.0.0.1:8000/api/health | python -m json.tool
# Expect: rate_limit.enforce:true
```

### Rollback

**Rate limits misfiring:** unset `RATE_LIMIT_ENFORCE` + restart — instant.

**Code rollback:** `git revert <commit(s)>` + `python post_run.py`

**WAL special case:** code revert is immediately safe (old SQLite code reads WAL
DBs fine). Full revert to DELETE journaling if needed:
```bash
sudo systemctl stop epm.service
sqlite3 /opt/epm-market-intelligence/data/users.db 'PRAGMA journal_mode=DELETE;'
sudo systemctl start epm.service
```
Keep the `_SERVER_MANAGED` sidecar entries even if WAL is reverted (harmless, protective).

### Follow-ups (deferred, not blocking)

- nginx `limit_req` as a second enforcement layer (does not depend on proxy headers)
- Deep-analysis queue-depth cap (warn logs will surface abuse patterns first)
- `OperationalError` → 503 mapping for `users.db` (busy_timeout covers it for now)
- Multi-worker caveat: if `--workers` is ever added to uvicorn, in-memory rate
  limits become per-worker silently — add Redis at that point

### Env flags

- `RATE_LIMIT_ENFORCE=0` (default warn-only); set 1 after proxy verification +
  clean observation window. Existing limits (forgot-password, reset, chat) always enforced.

---

## PR G — Validator centralization (IMPLEMENTED 2026-06-11, pending deploy approval)

Five staged commits (2eedfc7 → HEAD) creating `services/validators.py` as the
single home for scattered validation rules. Behavior-preserving by construction
(extract rules verbatim → delegate call sites → lock with tests) except the
explicitly approved D1 env-flag edge cases below.

### What it does

**C1 — `services/validators.py` (2eedfc7).** stdlib-only module, zero callers
at introduction. Contents (provenance documented per function):
`normalize_ticker()`, `DEEP_TICKER_RE`/`is_valid_deep_ticker()`,
`validate_username/password/email_format()` (return error-or-None; callers
raise), `env_flag()`, `read_json_artifact()`. 64 table-driven tests.

**C2 — ticker delegation (d74d922).** `app.py:_normalize_symbol` (9 internal
call sites, CRITICAL fan-out per GitNexus — change is body delegation only) and
`MarketBoardService._normalize_symbol` delegate to `normalize_ticker`; the
share-class dash→dot rule (BRK-B → BRK.B) proved identical in both and moved
into the canonical helper. `_DEEP_TICKER_RE` aliases `validators.DEEP_TICKER_RE`.
Byte-equivalence to both legacy functions proven by table tests.
openbb_provider keeps its own distinct suffix logic (not a duplicate).

**C3 — auth rule dedup (038b446).** username 2–40 (was in register_user AND
change_username) and password ≥10 (was in register_user AND reset_password)
now live once in validators. AuthError messages byte-identical, original check
order preserved; locked by tests/test_auth_validation_messages.py (11 tests).

**C4 — env_flag + health artifact reads (d1841ef).** Four flag sites share
`env_flag` (see D1). The 5 inline `json.load` blocks in `/api/health` use
`read_json_artifact`; per-check semantics exact (commentary malformed still
degrades; the other four map malformed → `{present:false, error:"check_failed"}`
without degrading) — locked by 4 new malformed-artifact shape tests.

**C5 — leak-count ratchet + docs.** `tests/test_error_detail_inventory.py`
freezes app.py's `detail=str(exc)` count at 13 (5 AuthError pass-throughs +
8 deferred D2 leak sites) — adding a site fails CI.

### D1 — canonical env-flag parsing (operator-facing change)

truthy = {1, true, yes, on}; falsey = {0, false, no, off}; case-insensitive;
unset/empty/garbage → flag default. **Documented 0/1 values behave identically
everywhere — zero production impact.** Edge changes (each test-locked):

| Flag value | Old behavior | New behavior |
|---|---|---|
| `SEND_REQUIRE_PDF=true` (or yes/on) | silently OFF (`== "1"`) | ON |
| `DATA_FRESHNESS_ENFORCE=true` | silently OFF | ON |
| `RATE_LIMIT_ENFORCE=no` / `off` | ON (`not in ("","0","false")`) | OFF |
| `WATCHDOG_ENABLED=false` / `no` / `off` | running (`== "0"` only) | disabled |

### Deferred decisions (named, not silently changed)

- **D2:** the 8 blanket `except Exception → detail=str(exc)` data endpoints
  leak internal text; fix needs a frontend audit first. Count is ratcheted.
- **D3:** profile_color / profile_avatar are stored unvalidated.
- **D4:** `DEEP_TICKER_RE` rejects dotted tickers (BRK.B cannot be
  deep-analyzed) — product decision, preserved verbatim.
- No new /api/health check: validators are pure code with no runtime artifact;
  every existing health check reads a real artifact.

### Verification after deploy

```bash
python -m pytest tests/ -q          # full suite
python post_run.py                  # manual approval only
curl -fsS https://epm-market-intelligence.com/api/health | python -m json.tool
# Expect: status ok, deploy.commit == new HEAD, rate_limit.enforce:false,
# all check shapes unchanged.
# Spot checks: 1-char-username register -> same 400 message; junk login -> 401;
# /api/suggest-tickers?q=aa -> 200; unauthenticated POST /api/deep/AAPL -> 401.
```

### Rollback

Pure code — no flags, no data migrations, no artifacts, no .env changes:
`git revert <commit(s)>` + `python post_run.py`. C1 has no callers (revert
trivially safe); C2–C4 are delegations whose reverts restore the inlined logic
verbatim. D1 deltas are env-edge-cases only; prod .env files use 0/1, so no
operator action on revert either.
