# Handoff: Direction C Redesign
Updated: 2026-04-23

## Status: DEPLOYED — Bucket-A complete + topbar redesign live on server; service restart pending

The backend has been stable (Analyst Council pipeline). The front end has been fully migrated
to Direction C (light-first, navy masthead, cool off-white canvas, amber-underline nav, teal eyebrows)
and deployed. Topbar redesign + mobile bottom nav shipped in commit `717793a1`. File sync to server
complete; service restart (`sudo systemctl restart epm.service`) still pending manually on the server.

---

## Architecture summary

- **Shell**: shared chrome injected at runtime by `static/js/chrome.js` into `<div id="epmChrome">` on every page. No Jinja. Each page sets `<body data-page="..." data-ds="v3">` and keeps its own `<head>` + theme/density bootstrap. chrome.js re-emits the legacy DOM contract (`.topbar`, `.brand-block`, `.main-nav`, `.topbar-nav`, `#settingsDrawer`, `#settingsOverlay`, `#openSettingsBtn`, `#closeSettingsBtn`, all `[data-pref-*]` chips) verbatim so `site.js` keeps working.
- **CSS layering**: `styles.css` (legacy) → `design-v2.css` (terminal-clarity override, heavy `!important`) → `design-system.css` (Direction C, scoped to `body[data-ds="v3"]`). New rules that must beat design-v2.css use `!important`.
- **Tokens**: Direction C palette on `:root`, dark-mode remap on `[data-theme="dark"]`, density overrides on `body[data-density="dense"]`. Spacing scale `--s-1..--s-6`. Type `--t-display/h2/h3/body/small/eyebrow`.
- **Primitives**: `.ds-card (.is-panel, .is-kpi, .is-table)`, `.ds-eyebrow`, `.ds-title (.is-display, .is-h3)`, `.ds-subtitle`, `.ds-chip (.up/.down/.neutral)`, `.ds-btn (.is-primary, .is-ghost)`, `.ds-num`, `.ds-kpi`, `.ds-research` (editorial serif scope), `.ds-section-header`, `.ds-section-divider`, `.ds-grid-3 / .ds-grid-2`, `.ds-table`.

---

## What's done (Phases 0–9, per-page migrations)

- All six top-level pages (`index.html`, `markets.html`, `forecasting.html`, `portfolios.html`, `search.html`, `deep-report.html`) migrated to `data-ds="v3"`, using chrome.js shell, eyebrow/title/subtitle pattern and the ds-card system.
- Markets dense mode lives (Markets-only overrides, KPI pill shrink, plot-target heights, subtitle hide).
- Analyst Council pipeline UX: 7-persona list + pipeline dots + ETA; "Run Analyst Council" copy throughout `search.html` and `deep_analysis.js`; `deep-report.html` pill reads "Analyst Council".
- Topbar cosmetic fixes from last session:
  - Desktop `.brand-copy` (wordmark h1) hidden — logo image carries the brand. Fixed by `!important` on the base rule that beats `design-v2.css @media(≥1100px) .brand-copy{display:flex!important}`.
  - Legacy active-nav background box removed (underline-only active state at ≥900px).
- Editorial typography (serif) scoped to `.ds-research` — used on homepage hero subhead and forecasting commentary blocks.

---

## Bucket-A first pass — ALL COMPLETE (deployed 2026-04-23)

Per PDF page 20 source-of-truth + Claude Design gap audit cross-check. Scope was narrowed by
user to 5 items + topbar redesign. Backend / APIs / polling / auth untouched.

### (1) Top-bar icon visibility — COMPLETE
- `#openSettingsBtn` and `#dsDensityBtn`: `design-v2.css`'s `background: var(--panel-2) !important` on `.settings-gear-btn` was making the gear a white-ish square floating on the navy bar. Overrode with higher-specificity `body[data-ds="v3"] .topbar .settings-gear-btn { background: transparent !important; border: 1px solid rgba(255,255,255,.22); color: rgba(255,255,255,.85); }` + killed the legacy `::before` gradient overlay + sized inline SVG child to 16×16.
- Density button got matching treatment (white-on-navy translucent border, amber border when dense).
- Settings-gear glyph issue confirmed resolved by user — no further action needed.

### (2) Density toggle scoped to Markets — COMPLETE
- `body[data-ds="v3"]:not([data-page="markets"]) #dsDensityBtn { display: none !important; }` added to design-system.css. Fund Search / Home / Forecasting / Portfolios / Deep Report no longer show the toggle.

### (3) Markets loading/unavailable states — COMPLETE
- Added `@keyframes ds-skeleton-shimmer` + Markets-scoped `.placeholder-item` override in `design-system.css` (section 14.5). Uses Direction C tokens (`--ds-canvas`, `--ds-line`, `--ds-muted`) for a light-canvas shimmer; killed the inherited v2 `::after` overlay so only the v3 gradient is visible.
- Dark-mode variant remaps to `--ds-paper` with white overlay.
- Animation gated on `[data-animations="on"]` to respect user motion prefs.
- Also added a reusable `.ds-skeleton` primitive (block-level) for future v3 loading states — not yet used in HTML.

### (4) Forecasting trophy/medal cleanup — COMPLETE
- `static/js/forecasting.js:466` `MEDALS` changed from `['🥇','🥈','🥉']` to `['#1','#2','#3']`.
- Added Direction-C podium override in `design-system.css`: `.podium-medal` is now mono-font (`--font-mono`), 15px, tabular numerals. Rank coloring: gold → `--ds-amber`, silver → `--ds-muted`, bronze → `#8a5f1a` (dark-mode bronze → `#c79a55`).

### (5) Eyebrow/title/subtitle sweep — COMPLETE
- `portfolios.html`: added `<div class="ds-eyebrow">` to Portfolio Leaders ("Today's Strength"), Portfolio Laggards ("Today's Weakness"), Portfolio Holdings ("Full Universe"). Section header now has `margin-top:var(--s-1)` to separate from eyebrow (matches the existing Model Portfolios pattern at the top of the same page).
- `forecasting.html`: added eyebrows "MAG7" above Consensus Forecasts and "Ranking" above Model Leaderboard. Same header margin treatment.
- Markets, Home, Search unchanged — already consistent. Deep Report intentionally skipped (uses `.report-pill` styling).

---

## Parked (Bucket B — requires explicit user approval before touching)

- Homepage launch-card replacement (Claude Design wanted them removed; PDF keeps them as simple nav tiles — currently kept).
- Brand mark: PNG logo + hidden h1 vs. amber "E" badge + text wordmark from `EPM_Design/directions/c-executive/system.jsx`. Currently shipping the PNG.
- Model Portfolios portfolio-first restructure.
- Fund Search IA changes / results table step before detail view.
- Deep Analysis Lab demotion on Fund Search page (user explicitly said keep it prominent).
- New nav routes (Research, Watchlists) — Direction C navigation shows 7 items; we ship 5.
- Density mode scope expansion to Fund Search (PDF says Markets + Watchlists only; current scope is Markets only this pass).

---

## Files touched (all sessions)

**Bucket-A (2026-04-20):**
- `static/css/design-system.css` — icon visibility rules (settings-gear + ds-density-btn), density-scope hide rule, skeleton-shimmer primitive + Markets scope, podium-medal Direction C restyle for text rank badges.
- `static/js/forecasting.js` — medal emoji → `#1/#2/#3` rank badges.
- `static/portfolios.html` — eyebrows on Leaders/Laggards/Holdings.
- `static/forecasting.html` — eyebrows on Consensus Forecasts / Model Leaderboard.

**Topbar redesign (2026-04-23, commit `717793a1`):**
- `static/js/chrome.js` — full topbar rewrite: `<nav class="main-nav">` moved before `brand-block` so `margin-right: auto` right-anchors brand; `#menuToggleBtn` pre-created in brand-block to prevent site.js duplication; added `BOTTOM_NAV_ICONS` + `_buildBottomNav()` + `<nav class="ds-bottom-nav">` for mobile.
- `static/css/design-system.css` — Section 2 (MASTHEAD/NAV) replaced: nav left with `margin-right: auto`, brand-block right-anchored, CSS `order` for search(1)/logo(2)/name(3) within brand-block, left-expanding search (`max-width` transition), suggestion dropdown right-anchored (`right:0; left:auto`), mobile bottom nav styles + `env(safe-area-inset-bottom)`.
- `static/search.html` — resolved 10 merge conflict markers (stale `git stash pop`), all resolved to "Updated upstream" (Direction-C) side.
- `static/index.html`, `markets.html`, `forecasting.html`, `portfolios.html`, `deep-report.html` — version-string bumps to `v=20260423a` for `design-system.css` and `chrome.js`.

**Uncommitted local changes (2026-04-23, not yet deployed):**
- `generate_market_commentary.py` — 18 line delta
- `quant_cup/backtest_engine.py` + `quant_cup/tournament.py` — 42 line delta
- `models/linear_panel.pkl`, `models/linear_panel_meta.json`, `models/ml_panel.pkl`, `models/ml_panel_meta.json` — updated checkpoints

---

## Deploy status

**SYNCED — service restart pending.**
- `sync_to_server()` ran successfully — all static files (including topbar redesign) are on the server.
- `sudo systemctl restart epm.service` must be run manually on the server (non-interactive SSH can't sudo). SSH in and run it to go live.
- Uncommitted changes (`generate_market_commentary.py`, `quant_cup/`, `models/`) not yet synced — need commit + another sync run.

Deploy target (confirmed via `post_run.py:30-35`):
- Server: `dporter02@192.168.1.145`, path `/opt/epm-market-intelligence/`
- `sync_to_server()` covers `static/`, `charts/`, `commentary/`, `data/`, `services/`, plus a listed set of top-level `.py` files. Does NOT cover `models/`, `generate_pdf_report.py`, or `local_council.py` — those need manual `scp` when they change.
- After any server-side code push: `sudo systemctl restart epm.service` (passwordless sudo is configured).
- Local test workflow: set `SECURE_COOKIES=false`, stop `epm.service` locally (or use uvicorn directly), verify, then restore `SECURE_COOKIES=true` before any push.

---

---

## Analyst Council — Session 2026-04-28 work (deployed)

Full multi-round debate pipeline is live. Summary of what shipped this session:

- **3-round council**: R1 independent stances → R2 named debate → R3 final positions → synthesis
- **Discord-style transcript UI**: avatar circles, round dividers, stance badges, grouped messages
- **Reply/quote previews**: R2 messages show a clickable quoted snippet of the R1 CLAIM they're challenging; R3 does the same for R2. Click scrolls to the original message.
- **Debate Map tab**: 3-column SVG flow chart — R1 stances (left), bezier arcs showing who challenged whom in R2 (middle, color = challenger's avatar), R3 final stances (right). Shifted positions get a gold "↕ shifted" badge; unchallenged analysts get a muted grey "unchallenged" label.
- **Field glossary**: `_FIELD_GLOSSARY` constant injected into all prompts — maps raw variable names (`rsi_14`, `rel_perf_3m_diff_pct`) to plain English.
- **Python vote counting**: `vote_distribution` and `consensus_stance` computed from R3 FINAL STANCE regex, overriding unreliable LLM counts. Chief Analyst prompt now requires acknowledgment of consensus and explicit justification for any contrarian verdict.
- **Copy Link fix**: `navigator.clipboard` with `_legacyCopy` textarea fallback.

Files modified: `local_council.py` (major), `static/deep-report.html` (major), `app.py` (minor).

---

## Deep Analysis Caching + Earnings-Triggered Invalidation — PLANNED

### Problem
The full council run costs ~20-25 min of GPU. Running it again for the same ticker on the same day with identical data is pure waste. Multiple users requesting the same ticker should share one result.

### Chosen design: shared daily cache + earnings-triggered on-demand re-run

**Cache key:** `ticker:YYYY-MM-DD`
**Scope:** shared across all users — report is non-personalized (ticker, not user)
**Flow:**
```
User requests AAPL deep analysis
    ↓
Cache hit for AAPL:today?
  ├── YES → serve cached job_id instantly
  │         + run lightweight earnings headline check (see below)
  │         + if new earnings data detected → show banner:
  │           "Earnings results just released — run a fresh analysis?"
  └── NO  → queue new 25-min run; all users waiting for same ticker
            share the single in-progress job (no duplicate spawns)
```

**In-progress dedup:** if a run is already queued/running for `AAPL:today`, a second user's request returns the same `job_id` and polls it — no second run spawned.

### Earnings-triggered invalidation (not generic news)

**Only invalidate on confirmed new earnings data, not any headline.** The check must be:
1. **Time-gated** — only run the earnings check on the exact `next_earnings_date` stored in `key_facts`, and only after the company's announced release window (pre-market ≈ 07:00 ET, mid-day ≈ 12:00 ET, after-close ≈ 16:30 ET). Do NOT poll before the release window. Do NOT poll on non-earnings days.
2. **Triggered by request** — the check fires when a user requests a report on earnings day after the release window, not on a background cron. This avoids constant server load.
3. **Confirmation signal** — the check looks for a confirmed EPS result (actual vs. estimate), not just any mention of the company name. A headline alone is not enough — need actual/estimate data to confirm the release dropped.

### Earnings release time data — needs research

The current `key_facts` has `next_earnings_date` but NOT the time-of-day of the release (pre/mid/after-close). This is required to gate the check correctly. Reliable sources to investigate:
- **Earnings Whispers** (earningswhispers.com) — known for accurate release time data, widely used
- **Alpha Vantage** `/EARNINGS_CALENDAR` endpoint — includes `reportTime` field (BMO = before market open, AMC = after market close); no mid-day field
- **Yahoo Finance** `yfinance` library — `ticker.calendar` returns earnings date + time where available
- **Nasdaq earnings calendar** — has pre/after-close flags for most large-caps

Recommendation: `yfinance.Ticker.calendar` for initial implementation (already a dependency), fall back to Alpha Vantage if time field missing. Research needed on coverage for mid-cap and international ADRs — the pipeline currently covers S&P 500 + extended universe, so focus on those first.

### Mid-day earnings handling (hardest case)

If earnings drop mid-day (after the daily pipeline has already run at ~08:00 ET):
1. The earnings check fires when a user requests the report after the release window
2. Server runs a **targeted on-demand data refresh** for just that ticker:
   - Re-run `fetch_enrichment.py --ticker AAPL` (fast, ~10-15s) to get fresh price + EPS actuals
   - Re-fetch headlines from `news_store` for that ticker (fast)
   - Rebuild `key_facts` and `seed_doc` with the new data
3. Queue a fresh council run (~25 min) and invalidate the old cached job
4. All users who request the ticker during the run share the in-progress job

Pre-market and after-close releases are easier — the next-morning pipeline naturally picks them up before most users would request a fresh report that day.

### Implementation scope (not yet started)

Files to touch:
- `app.py` — cache lookup at `/api/deep/run` endpoint; in-progress dedup; earnings-check trigger
- `deep_analysis.py` or new `earnings_check.py` — lightweight EPS-result detector; on-demand data refresh for single ticker
- `data_arbiter.py` — add `earnings_release_time` field to output (BMO/AMC/intraday) using yfinance calendar
- `static/search.html` or `static/deep-report.html` — "Earnings just released" banner UI
- New `deep_analysis_cache.json` (or Redis key if available) — stores `{ "AAPL:2026-04-28": { job_id, fetched_at, invalidated: false } }`

**Do not build until the existing council quality is stable** — validate R2/R3 debate quality on 3-5 more tickers first.

---

## Next step on resume

1. **Complete service restart**: SSH to `dporter02@192.168.1.145` and run `sudo systemctl restart epm.service` — topbar redesign is staged but not live yet.
2. **Commit + sync pending changes**: `generate_market_commentary.py`, `quant_cup/backtest_engine.py`, `quant_cup/tournament.py`, and model checkpoints are uncommitted. Commit then re-run `sync_to_server()` + restart.
3. **Research earnings release time sources**: check `yfinance.Ticker.calendar` coverage for S&P 500 universe — does it include release time (BMO/AMC) reliably? Check Alpha Vantage `/EARNINGS_CALENDAR` as fallback. Document findings before building the invalidation trigger.
4. **Validate council quality** on 3-5 more tickers (NVDA, TSLA, MSFT recommended) before building caching layer.
5. **Bucket B decisions** (requires user approval before touching):
   - Homepage launch-card replacement
   - Brand mark (PNG logo vs. amber "E" badge + wordmark)
   - Model Portfolios portfolio-first restructure
   - Fund Search IA changes
   - New nav routes (Research, Watchlists)
