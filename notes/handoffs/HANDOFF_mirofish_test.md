# Handoff: Deep Analysis Feature
Updated: 2026-04-20 (session 7)

## Status: LIVE — MiroFish replaced with Local Analyst Council

---

## What Works
- Fund Search page → Deep Analysis Lab → Run Analyst Council
- FIFO job queue with deduplication — submitting same ticker while active returns existing job
- Progress polling every 10s, localStorage job persistence across page nav
- Progress UI: current stage card, horizontal pipeline tracker (4 stages)
- **Queue visibility**: when waiting behind another job, shows "Waiting in Queue — Position X — est. ~Y min"
- **Auto-retry**: first failure requeues with retry_count=1; second failure marks failed
- Report page: Copy Link + Download PDF + Run New Analysis buttons
- Agent viewer: By Agent tab (7 persona cards, expandable) + Transcript tab (deliberation timeline)
- Transcript tab is the DEFAULT view
- Report rendered from `enhanced_markdown` (synthesized 6-section report); falls back to raw council transcript

---

## Session 7 Changes (2026-04-20): MiroFish → Local Analyst Council

### Root Cause for Replacement
AAPL job `deep_AAPL_67ea19e2` confirmed MiroFish was structurally broken:
- `has_seed: True`, `has_key_facts: True`, `has_raw_md: False`
- MiroFish hung 60+ minutes, produced no raw markdown, job auto-failed
- Root causes: NER lottery picks unpredictable "dominant agent" each run; 25-40 min base runtime;
  numbers hallucinated because they aren't injected into the simulation; one entity (e.g. "Federal Reserve")
  dominates 7/8 posts in a 72-round sim

### New Architecture: `local_council.py` (NEW)
Seven deterministic financial persona agents, each making one Ollama call grounded in KEY_FACTS:

| Persona | `name` key | Focus |
|---------|------------|-------|
| Technical Analyst | `technical_analyst` | Price action, chart patterns, ATR regime |
| Growth Investor | `growth_investor` | Revenue growth, margin expansion, forward multiples |
| Value Investor | `value_investor` | P/E, P/B, FCF yield, dividend, intrinsic value |
| Macro Strategist | `macro_strategist` | VIX, SPY correlation, macro risks |
| Supply Chain Risk Analyst | `supply_chain_risk` | Concentration, geopolitical exposure |
| Bearish Analyst | `bearish_analyst` | Downside case, risks, valuation ceiling |
| Earnings Catalyst Analyst | `earnings_catalyst` | Upcoming catalysts, guidance, PEAD signal |

Synthesis step: all 7 takes + KEY_FACTS → 6-section institutional report via one qwen2.5:14b call.

**6 report sections:**
1. `## Quantitative Snapshot` — KEY_FACTS table (exact values, no hallucination)
2. `## Quantitative Signals` — EPM ensemble signals, Kronos forecasts, PEAD
3. `## Kronos Scenario Breakdown` — base/bull/bear/crash scenarios with probabilities
4. `## Council Perspectives & Tensions` — council disagreements and consensus
5. `## Market Participant Reactions` — institutional vs retail behavior prediction
6. `## Critical Risks Beyond the Models` — tail risks not captured by quant models

### Pipeline: `deep_analysis_worker.py` (REWRITTEN)
All MiroFish code removed (`_mf_post`, `_mf_get`, `_poll`, `_kill_zombie_sims`,
`_postprocess_with_llm`, CJK validators, zombie kill on timeout).

New lean pipeline:
```
Step 0: build_seed_doc(ticker)     → seed_text + key_facts    (5%)
Step 1: run_council(...)           → 7 persona calls           (15-85%)
                                   → 1 synthesis call          (85-95%)
Step 2: persist result             → completed                 (100%)
```

New STAGES:
```python
STAGES = {
    "queued":             ("Queued",                     0),
    "seed_doc":           ("Building analysis document", 5),
    "council_personas":   ("Council deliberating",      15),
    "council_synthesis":  ("Synthesizing report",       85),
    "completed":          ("Complete",                 100),
    "failed":             ("Failed",                    -1),
}
```

Queue wait estimate: 35 min → 7 min per job (7 personas × ~45s + synthesis ~60s = ~6 min).

### Frontend: `static/js/deep_analysis.js` (edited)
Replaced 8 MiroFish STAGE_LABELS with 4 council stages:
```js
const STAGE_LABELS = [
  { key: 'seed_doc',          label: 'Data',      full: 'Building Analysis Document' },
  { key: 'council_personas',  label: 'Council',   full: 'Analyst Council Deliberating' },
  { key: 'council_synthesis', label: 'Synthesis', full: 'Synthesizing Report' },
  { key: 'completed',         label: 'Done',      full: 'Complete' },
];
```

### Agents Endpoint: `app.py` (edited)
`/api/deep/{job_id}/agents` now reads from `result.takes` (council submissions) instead of MiroFish SQLite.
Response shape is back-compatible with deep-report.html By Agent + Transcript tabs.

### Branding: `static/deep-report.html` (edited)
`'Deep Swarm Analysis · Powered by Kronos + MiroFish + EPM Ensemble · '`
→ `'Deep Analysis · Powered by Kronos + Analyst Council + EPM Ensemble · '`

### yfinance 401 Fix: `deep_analysis.py` (edited)
Added 2-attempt retry with 4s backoff in `_get_fundamentals` for transient Yahoo Finance 401 errors.
yfinance 1.2.0 is installed at `/opt/epm-market-intelligence/.venv`. Confirmed working.

---

## Architecture

### Job Queue
- Jobs: `data/jobs/{job_id}.json` — persist indefinitely
- Schema fields: `job_id`, `ticker`, `status`, `stage`, `progress`, `retry_count`, `created_at`,
  `started_at`, `completed_at`, `updated_at`, `error`, `result`, `seed_text`, `key_facts`
- One background thread, FIFO, one job at a time
- Jobs reset to `queued` on app restart if interrupted (`_reset_interrupted_jobs`)
- Deduplication: submitting ticker with active job returns existing job_id
- Auto-retry: first failure → queued with retry_count=1; second → failed

### Pipeline Stages & Timings
| Stage | Time | Progress % |
|-------|------|-----------|
| seed_doc | ~8s | 5-12% |
| council_personas | ~5-6 min (7 × ~45s persona calls) | 15-85% |
| council_synthesis | ~60-90s (synthesis call) | 85-95% |
| completed | — | 100% |

**Total target: 5-8 min** (vs MiroFish 25-60+ min)

### Job Result Schema
```json
{
  "markdown_content":  "...",     // raw council transcript (per-persona takes)
  "enhanced_markdown": "...",     // synthesized 6-section report
  "title":   "AAPL Deep Analysis",
  "summary": "",
  "sections": [],
  "takes": [                      // structured per-persona submissions
    {"name": "technical_analyst", "title": "Technical Analyst", "body": "..."},
    ...
  ]
}
```

### API Endpoints
- `POST /api/deep/{ticker}` — auth required, enqueues/deduplicates, returns `{job_id}`
- `GET /api/deep/{job_id}/status` — includes `queue_position`, `queue_wait_min` when queued
- `GET /api/deep/{job_id}/agents` — returns 7 persona cards + chronological timeline from `takes`
- `GET /deep-report?job_id=xxx&ticker=XXX` — report display page

---

## Server Setup
```bash
# SSH
ssh -i ~/.ssh/epm_server dporter02@192.168.1.145

# Restart service after deploys
sudo systemctl restart epm.service
journalctl -u epm.service -n 20 --no-pager

# Kronos (port 8100) — must be running for seed_doc step
cd /opt/kronos && source venv/bin/activate && nohup python api.py > /opt/kronos/kronos.log 2>&1 &

# Ollama (port 11434) — must be running for council step
# Check: curl http://localhost:11434/api/tags

# GitNexus (npx broken on Node 24 — use direct node call)
node "C:\Users\david\AppData\Roaming\npm\node_modules\gitnexus\dist\cli\index.js" analyze
```

---

## Known Issues / Watch Points
- **yfinance fundamentals**: 401 Invalid Crumb errors are transient at the server IP. 2-attempt retry with 4s
  backoff added. If fundamentals are consistently null (PE, ROE etc.), consider `curl_cffi` browser
  impersonation: `pip install curl_cffi` then wrap `yf.Ticker(ticker, session=cf.Session(impersonate="chrome")).info`
- **Stale failed job**: `deep_AAPL_67ea19e2.json` in `failed` status on server. Non-blocking — `failed` jobs
  don't interfere with new analyses. Can delete: requires `epmapp` user access (service account).
- **Job files never cleaned up**: `data/jobs/` grows over time; no purge mechanism
- **Ollama not auto-started on boot**: if council calls fail with connection refused, check `ollama serve`
- **Kronos not auto-started on boot**: if seed_doc step fails, check Kronos at port 8100
- **synthesis fallback**: if enhanced_markdown is empty, falls back to raw council transcript so user
  sees something; logged as WARNING in service logs
- `deep_analysis.py` / `deep_analysis_worker.py` / `local_council.py` / `static/deep-report.html`
  / `static/js/deep_analysis.js` / `app.py` must stay in sync between local and server

---

## Next Test: End-to-End Validation
1. Visit Fund Search page → enter AAPL → click "Run Analyst Council"
2. Progress bar should advance: Data (12%) → Council (15-85%, slow linear) → Synthesis (85-95%) → Done
3. Total runtime: ~5-8 min
4. Open report — confirm all 6 sections present, KEY_FACTS numbers match, no MiroFish/swarm/ontology references
5. "By Agent" tab — should show exactly 7 persona cards, each with one post
6. Transcript tab — 7 sequential entries in council deliberation order

## MiroFish Notes (historical reference only — no longer used)
- MiroFish processes fully removed from pipeline. `mirofish` dir still on server at `/opt/mirofish/`
  but EPM no longer calls it.
- All previous sessions' MiroFish fixes (NER persona shaping, zombie kill, CJK filter, English directives)
  are obsolete — those problems are solved by design in the new deterministic council approach.
