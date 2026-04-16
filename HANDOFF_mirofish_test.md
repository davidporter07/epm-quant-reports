# Handoff: Deep Analysis Feature
Updated: 2026-04-16 (session 4)

## Status: LIVE — Auth fixed, zombie auto-cleanup, report prompt hardened, agent viewer wired

---

## What Works
- Fund Search page → Deep Analysis Lab section → Run Deep Swarm Analysis
- FIFO job queue, progress polling every 10s, localStorage job persistence across page nav
- Redesigned progress UI: animated agent network SVG, current stage card, horizontal pipeline tracker
- Report page: Copy Link + Download PDF + Run New Analysis buttons
- "Run New Analysis" button on done panel clears old job, scrolls to lab, resets run button state
- "Run New Analysis" button on report page navigates back to Fund Search anchored to lab section
- SVG animations force-run even when OS has prefers-reduced-motion enabled
- **Agent Activity section** on report page: expandable per-agent cards showing bio + all simulation posts
- 401 on deep analysis start now opens auth drawer with friendly message instead of raw HTTP error

---

## Session Fixes Applied (2026-04-16, session 4)

### Auth Cookie Fix (root cause of all 401 errors)
- **Root cause**: Security hardening (2026-04-13) removed `storeToken` from frontend JS with a comment
  "tokens are now set as HttpOnly cookies by the server" — but `set_cookie()` was never implemented
  in `app.py`. The JWT was returned in the login JSON body, discarded by the frontend, and no cookie
  was ever written. Every auth-gated route returned 401 for all users always.
- **Fix**: `api_login` and `api_register` now call `_set_auth_cookie(response, token, remember_me)`,
  which sets `epm_token` as `HttpOnly`, `Secure`, `SameSite=lax` with correct `max_age`
- Added `/api/auth/logout` route — calls `delete_cookie("epm_token")`; previously missing entirely
- `api_change_username` now refreshes the cookie with the re-issued token
- `SECURE_COOKIES` env var (default `true`): set `SECURE_COOKIES=false` for local HTTP dev
- **Impact**: All auth-gated features were broken (deep analysis, user prefs, forecasting page).
  Users appeared signed in due to optimistic `localStorage.epm_username` state but all API calls failed.

### Zombie Sim Auto-Cleanup
- **Root cause**: MiroFish never cleans up `run_parallel_simulation.py` child processes.
  Accumulated zombies compete for Ollama GPU causing IPC stalls and poll timeouts.
  Previously required manual `pgrep + kill` each session.
- **Fix**: Added `_kill_zombie_sims()` to `deep_analysis_worker.py` — runs `pgrep -f
  run_parallel_simulation.py` + `kill -9` on any found PIDs, waits 1s for GPU release.
  Called automatically just before `simulation_create` in every pipeline run.

### LLM Post-Processing Prompt Hardened
- Added explicit rule to strip MiroFish internal tool names: `interview_agents`, `quick_search`,
  `insight_forge`, `panorama_search` — these were leaking verbatim into report text
- Banned blockquote formatting (`>`) entirely — fabricated quotes were persisting as blockquotes
  attributed to unnamed "spokespersons" and "firms"
- Added deduplication rule: each statistic appears exactly once across the report
- Total rules: 8 numbered mandatory rules (up from 4 loose bullet points)

### Copy Link Bug Fixed
- `copyReportLink()` was defined inside the IIFE — invisible to `onclick="copyReportLink()"`
  global scope. Button did nothing.
- Fixed by making it `window.copyReportLink = function() {...}`
- Added `execCommand('copy')` fallback for browsers that block the clipboard API

### Agent Activity Viewer Wired Correctly
- Was triggered on a blind 800ms setTimeout — failed silently if auth returned 401 (which it always did)
- Now called directly from `renderReport()` after report content is visible
- Shows "Loading agent data…" immediately, surfaces HTTP error codes if fetch fails
- Old redundant second script block removed

### Agent Activity — What MiroFish Actually Produces
- **Finding**: 72-round simulation for AAPL produced only 5 total posts (1 per agent)
- Agents do NOT deliberate — each makes one isolated statement then goes silent
- Raw Reddit posts are a sparse side-effect of the simulation; the actual analysis comes from
  MiroFish's internal IPC interview layer (not accessible via API)
- Agent posts are in Chinese — MiroFish has no language constraint; qwen2.5 defaults to Chinese
- **Recommendation**: Relabel section "Agent Perspective Snapshots" (not "activity/conversations")
  and add note that these are domain-perspective statements, not a conversation log
- Next improvement: add `simulation_requirement` to force English-language posts
- Elle Fanning / ASML still appeared as agents (sim ran before news contamination fix)

---

## Session Fixes Applied (2026-04-16, session 3)

### App.py Deep Routes Restored
- `deep_analysis_start`, `deep_analysis_status`, `/deep-report` routes were silently removed from
  app.py by a `sync_to_server()` overwrite during a prior session
- **Root cause**: `deep_analysis.py` and `deep_analysis_worker.py` were only on the server, not in
  the local repo — when sync pushed local app.py it overwrote the server version without these routes
- **Fix**: pulled both files from server to local repo, restored all deep analysis routes to app.py,
  added worker start/stop to FastAPI startup/shutdown events
- **Going forward**: `deep_analysis.py`, `deep_analysis_worker.py`, `static/deep-report.html` are
  now local files and will sync correctly via `post_run.sync_to_server()`

### Agent Activity Viewer
- New endpoint: `GET /api/deep/{job_id}/agents` — reads `reddit_profiles.json` and `reddit_simulation.db`
  from MiroFish sim directory, returns agent names, bios, and all posts
- MiroFish sim data path: `/opt/mirofish/backend/uploads/simulations/{sim_id}/`
  - `reddit_profiles.json` — agent name/bio/persona
  - `reddit_simulation.db` — SQLite, `post` table, `user_id` + `content` columns
  - Configurable via `MIROFISH_SIMS_DIR` env var (default: above path)
- UI: collapsible `<details>` cards per agent in "Simulation Agent Activity" section below report
- MiroFish `/<sim_id>/agent-stats` and `/<sim_id>/posts` REST endpoints are **broken** (Flask 308
  redirect strips the sim_id) — data must be read from SQLite directly

### News Entity Contamination Fix
- Agent names were being extracted from news headlines (Elle Fanning, ASML, Amazon) instead of
  analytical section headers (Technical Analysis Perspective, Federal Reserve, etc.)
- **Fix**: changed news section header label to include
  "background context — do not create agents from these headlines"
- This is a soft LLM instruction — agents should now be seeded from section headers

### Report Quality Fixes
- **Supply chain text**: removed "Current US-China tariff escalation" (factually incorrect assertion);
  replaced with structural risk framing: "US-China trade policy, tariff regimes, and export controls
  create structural cost and margin risk"
- **VIX bug**: `yf.download("^VIX", auto_adjust=True)` returned 1748 instead of ~17; fixed by
  switching to `yf.Ticker("^VIX").history()` with a 5–150 sanity check
- **LLM post-processing prompt**: added explicit rules — no "interviews with stakeholders" language,
  no fabricated external quotes ("said a spokesperson"), use ONLY seed doc numbers (ignore MiroFish
  numbers which are often wrong), don't assert specific current geopolitical events
- **EPM Enhanced badge**: now only shown when `enhanced_markdown !== markdown_content`; previously
  showed even when LLM post-processing failed silently and returned raw MiroFish content

### Timeout Fix
- `report_poll` timeout increased: 100×15s (25 min) → 160×15s (40 min)
- Root cause: MiroFish IPC interview stalls for ~3 min per section when system is under load;
  previous timeout was too tight and caused the worker to stop polling before report completed

### Auth / 401 Fix
- `_runDeepAnalysis` in `deep_analysis.js`: 401 response now shows "Sign in required" message and
  calls `openAuthDrawer()` instead of displaying raw "HTTP 401" error

### CSP Fix (session 2, same session context)
- Added `https://static.cloudflareinsights.com` to `script-src` in `add_security_headers` middleware
- Stops Cloudflare beacon from being blocked and logging console CSP errors

### Zombie Sim Process Cleanup
- Old MiroFish simulation processes from April 14 were still running (PIDs 841732, 1042541)
- These competed with new simulations for Ollama GPU, causing IPC timeouts mid-report
- Killed manually; MiroFish does not auto-clean child processes after sim completion

---

## Architecture

### Job Queue
- Jobs: `data/jobs/{job_id}.json` — persist indefinitely
- One background thread, FIFO, one job at a time
- Jobs reset to `queued` on app restart if interrupted
- Report URL shareable: `/deep-report?job_id=xxx&ticker=XXX`
- localStorage: 1 job per ticker (overwritten on new run — by design)
- Job file stores `seed_text`, `simulation_id`, `graph_id`, `report_id` for recovery

### Pipeline Stages & Timings
| Stage | Time | Progress % |
|-------|------|-----------|
| seed_doc | ~8s | 5% |
| ontology | ~2 min (blocking POST, 180s timeout) | 8-15% |
| graph | ~1-6 min (36-iteration poll) | 16-25% |
| simulation_create | instant | 30% |
| simulation_prepare | ~12.5 min (130×10s poll) | 31-54% |
| simulation_running | instant start | 55% |
| report_generate | ~15-30 min (160×15s poll) | 60-95% |
| LLM post-processing | ~1-2 min (qwen2.5:14b Ollama call) | 96% |
| completed | — | 100% |

### API Endpoints
- `POST /api/deep/{ticker}` — auth required, enqueues job, returns `{job_id}`
- `GET /api/deep/{job_id}/status` — auth required, returns progress + result when done
- `GET /api/deep/{job_id}/agents` — auth required, returns agent profiles + posts from sim SQLite
- `GET /deep-report?job_id=xxx&ticker=XXX` — report display page

---

## MiroFish Key Facts
- `total_rounds` always = 72 (hardcoded, `rounds` param ignored)
- Agent count = qualifying graph nodes from seed doc named entities
- Minimum viable seed: ~1000 chars with named entities
- Named entities come from section headers in the seed doc
- News headlines section now labeled "background context" to prevent entity extraction from headlines
- Kronos sample_count=3 appears to be ignored; only 1 forecast returned
- Report generator drops quantitative data — mitigated by LLM post-processing layer
- MiroFish `/<sim_id>/agent-stats` REST endpoint broken (Flask routing bug, 308 redirect strips sim_id)
  — read SQLite files directly instead
- MiroFish does NOT auto-clean zombie simulation child processes after sim completes

---

## Server Setup
```bash
# MiroFish (port 5001)
cd /opt/mirofish/backend && source /opt/mirofish/venv/bin/activate && nohup python run.py >> /opt/mirofish/mirofish.log 2>&1 &

# Kronos (port 8100)
cd /opt/kronos && source venv/bin/activate && nohup python api.py > /opt/kronos/kronos.log 2>&1 &

# SSH
ssh -i ~/.ssh/epm_server dporter02@192.168.1.145

# Kill zombie MiroFish sim processes if they accumulate
pgrep -a python | grep run_parallel_simulation  # identify PIDs
kill <PID1> <PID2>
```

---

## Known Issues / Watch Points
- MiroFish not auto-started on boot — must be manually started after server reboots
- MiroFish main Flask process can crash without warning (crashed ~3am on 2026-04-16); no watchdog
- Ontology stage is the most likely timeout point (~2 min synchronous call)
- If MiroFish is down when worker runs, job fails with clean user error message
- Job files never cleaned up — will grow over time (no purge mechanism yet)
- `seed_text` stored in job JSON — adds ~3-5KB per job file
- Kronos reliable horizon: ~7-10 days for OHLCV-only model
- MiroFish report generator drops quant numbers — mitigated by post-processing, not fully solved
- Agent exclusion not yet implemented — no MiroFish API for removing individual graph nodes;
  next approach would be a pre-simulation agent review/approval step before simulation_create
- `deep_analysis.py` / `deep_analysis_worker.py` / `static/deep-report.html` must be kept in local
  repo to avoid sync overwrites removing server-only files
