# Handoff: Direction C Redesign
Updated: 2026-05-04 (session 3)

## Status: LIVE — deep report fully redesigned; persona-anchor fix deployed

epm.service active, Kronos healthy, Ollama running qwen2.5:14b.

---

## What was done this session (2026-05-04 session 3)

### 1. Chief analyst investment memo — COMPLETE
Rewrote `_chief_analyst_prompt` in `local_council.py` (lines ~578–638) from a 6-section debate-recap
structure into a proper 7-section investment memo:

`## Investment Thesis` → `## Where This Stands Today` → `## The Bull Case` → `## The Bear Case`
→ `## What Tilts the Decision` → `## Catalysts to Watch (Next 60–90 Days)` → `## What Would Change This View`

Tone instructions added: write as senior analyst to PM, narrative paragraphs, take a position.
Output goes to `enhanced_markdown` (same field, no downstream schema changes).

**Also fixed**: synthesis `num_ctx` raised `8192 → 16384`; timeout raised `420s → 600s` to give
qwen2.5:14b enough room to generate the full memo. Previously the synthesis was timing out and
the fallback filled "Investment Analysis" with raw per-agent R3 stances.

### 2. Deep report frontend restructure — COMPLETE
`static/deep-report.html` restructured:

- **Hero section**: `enhanced_markdown` rendered with prominent typography, section title
  "Investment Analysis", recommendation chip (UNDERWEIGHT/OVERWEIGHT/NEUTRAL) pulled from memo.
- **Council Deliberation header**: styled `.council-section-divider` with golden title and grey
  subtitle "How the analyst council reached this view." — previously was unstyled plain text at
  the page left edge because it lived outside `.report-page`.
- **Bug fixed**: `councilDivider` and `agentActivity` divs moved inside `.report-page` (were
  outside it, rendering without container styling). Duplicate divs at end of file removed.
- **By Agent tab**: rebuilt as verdict cards — one card per agent with stance pill, rationale,
  shifted badge + "Changed view:" text. No full posts. Default tab changed to "By Agent".
- **CSS** (`static/css/styles.css`): `.investment-memo`, `.council-section-divider`,
  `.verdict-card`, `.recommendation-chip`, `.stance-pill`, `.shifted-badge` all added.

### 3. Per-agent verdict in `/api/deep/{job_id}/agents` — COMPLETE
`app.py`: Each entry in `agents[]` now includes a `verdict` dict with `stance`, `rationale`,
`shifted` (bool), `shift_reason` — parsed from R3 FINAL STANCE/RATIONALE/POSITION SHIFTED/WHY
fields. Existing `posts` array retained for backward compat.

### 4. Persona-anchor fix (R3 pile-on conformance) — DEPLOYED, pending service restart
`local_council.py:_final_position_prompt` — added `domain_anchor` block inserted between
`YOUR ROUND 2:` and `OTHER ANALYSTS' ROUND 2 RESPONSES:`. Three variants:
- **TA**: anchor to price-action/momentum/volatility only
- **Personas with focus_fields** (GI, VI, EC, BA, MS): anchor to own domain fields; RSI/ATR
  explicitly not valid shift triggers; POSITION SHIFTED: yes requires naming the specific
  domain field+value that changed their mind
- **SC**: anchor to structural/geopolitical domain

Key rule: "Majority consensus pressure is NOT a valid reason to shift." Prevents EC/GI from
flipping bearish when 5 other analysts pile on with bearish takes.

**Service restart needed** after sync (SSH was timing out from local machine — user must run):
```
ssh -i ~/.ssh/epm_server epm@epm-market-intelligence.com "sudo systemctl restart epm.service"
```

---

## What was fixed in session 2 (2026-04-29)

### 1. Browser static-file caching — RESOLVED
Root cause confirmed: `deep_analysis.js` was the only static asset without a `?v=` cache-buster.
`site.js` and `design-system.css` also had stale version strings (fixes applied to the files
after the version strings were set, so browsers served old code indefinitely).

**Fixes applied:**
- `search.html:42` — added `?v=20260429a` to `deep_analysis.js` script tag
- All 6 HTML pages (`index`, `markets`, `portfolios`, `deep-report`, `forecasting`, `search`) —
  bumped `site.js?v=20260420c` → `?v=20260429b`
- Same 6 pages — bumped `design-system.css?v=20260424a` → `?v=20260429b`

After a single hard-reload, browsers now fetch the corrected JS/CSS that was already on the server.

### 2. "Run New Analysis" run-loop — RESOLVED (by fix #1)
The loop (Run New Analysis → Run Analyst Council → instant Done → repeat) was caused by the
stale `deep_analysis.js` calling `_runDeepAnalysis(ticker)` without `forceFresh=true`. The
current source at `static/js/deep_analysis.js:189` already passes `true` — fixing the cache-bust
was all that was needed.

### 3. Ticker tape not at top / search dropdown behind card — RESOLVED (by fix #1)
Both the ticker tape fix (`eb249324`) and the search card z-index fix (`be65dff6`) were in the
deployed JS/CSS but browsers served cached stale copies. Fixed by version bump above.

### 4. Economic calendar clustering — RESOLVED
- `services/market_board_service._load_economic_calendar` rewrote from `[:200]` head-slice to
  a proper 4-week date-window filter + importance floor (drops "low" events).
  File: `services/market_board_service.py:258`
- May events now reach the browser; foreign holidays / minor auctions are filtered out.

### 5. FOMC missing from economic calendar — RESOLVED
FRED's `/releases/dates` API misses the current FOMC meeting because the press release
publication date can fall before the query's `realtime_start`.

**Fix:** `generate_market_commentary.fetch_economic_calendar` now injects FOMC dates from
a hardcoded 2026 list (after the FRED/NASDAQ/Finnhub fetches), adding any meeting whose
announcement date is in [today, today+28] and not already present (±2-day tolerance).

Hardcoded list lives at `generate_market_commentary.py` just before the JSON save block.
**Update annually in November** when the Fed publishes next year's meeting schedule.

2026 dates encoded:
`2026-01-28`, `2026-03-18`, `2026-04-29`, `2026-06-10`,
`2026-07-29`, `2026-09-16`, `2026-10-28`, `2026-12-09`

Note: Fed JSON endpoint (`/monetarypolicy/json/fomcCalendars.json`) returned 404 — they don't
publish it there. The hardcoded fallback is the correct approach.

### 6. Market Movers showing micro-caps — RESOLVED
`_load_broad_market_movers` (OpenBB/yfinance screener) returned all-market results,
surfacing micro-cap stocks with 30-40% moves. Replaced with the curated
`DEFAULT_MARKET_MOVERS_UNIVERSE` ranking approach (already loaded, live quotes).
File: `services/market_board_service.py:311` — removed the broad-screener branch entirely.

### 7. NVDA earnings context
NVDA next earnings: 2026-05-20. AMD: 2026-05-05. No earnings release today, so the
earnings-triggered cache invalidation correctly did NOT fire — expected behavior.

---

## Current server state

| Component | Status |
|-----------|--------|
| epm.service | **needs restart** — `local_council.py` synced but SSH timing out from local |
| Kronos | healthy |
| Ollama | running, qwen2.5:14b loaded |
| Browser caching | resolved — all version strings bumped |
| Economic calendar | FOMC injected, importance-filtered, date-windowed |
| Market movers | curated large-cap universe |
| Deep report | fully redesigned — memo hero, verdict cards, Council Deliberation styled |

---

## Remaining / parked

### Needs verification on next analysis run
- Persona-anchor fix: trigger a fresh analysis on a ticker with strong bullish earnings signal
  (e.g. recent beat >5%) and confirm EC/GI hold their domain-grounded stances in R3 even when
  4-5 other analysts are bearish. Check server logs for `Chief analyst done in` timing.

### Low-priority cleanup
- Add `earnings_calendar.json` to `_SERVER_MANAGED` in `post_run.py` (one-liner, removes
  a benign sync warning)

### Bucket B (requires explicit user approval before starting)
- Homepage launch-card replacement
- Brand mark: PNG logo vs. amber "E" badge + wordmark
- Model Portfolios portfolio-first restructure
- Fund Search IA changes / results table before detail view
- New nav routes (Research, Watchlists)

---

## Architecture summary (unchanged)

- **Shell**: shared chrome injected at runtime by `static/js/chrome.js` into `<div id="epmChrome">`.
- **CSS layering**: `styles.css` → `design-v2.css` → `design-system.css` (scoped to `body[data-ds="v3"]`).
- **Tokens**: Direction C palette on `:root`, dark-mode on `[data-theme="dark"]`, density on `[data-density="dense"]`.
- **Primitives**: `.ds-card`, `.ds-eyebrow`, `.ds-title`, `.ds-btn`, `.ds-chip`, `.ds-kpi`, `.ds-research`, etc.

---

## Key files changed — session 3 (2026-05-04)

- `local_council.py` — `_chief_analyst_prompt` rewritten (7-section memo); `num_ctx` synthesis `8192→16384`; chief analyst timeout `420s→600s`; `_final_position_prompt` domain anchor added
- `app.py` — `/api/deep/{job_id}/agents` adds `verdict` dict per agent (additive, backward compat)
- `static/deep-report.html` — hero section, Council Deliberation header moved inside `.report-page`, By Agent rebuilt as verdict cards, default tab = By Agent
- `static/css/styles.css` — `.investment-memo`, `.council-section-divider`, `.verdict-card`, `.recommendation-chip`, `.stance-pill`, `.shifted-badge` added

## Key files changed — session 2 (2026-04-29)

- `static/search.html` — `deep_analysis.js?v=20260429a`
- `static/{index,markets,portfolios,deep-report,forecasting,search}.html` — `site.js?v=20260429b`, `design-system.css?v=20260429b`
- `services/market_board_service.py` — `_load_economic_calendar` date filter, movers fix
- `generate_market_commentary.py` — FOMC injection block
