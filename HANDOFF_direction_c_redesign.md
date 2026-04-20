# Handoff: Direction C Redesign
Updated: 2026-04-20

## Status: LOCAL — Direction C shell live on all pages; Bucket-A first-pass COMPLETE (pending deploy + settings-gear glyph decision)

The backend has been stable (Analyst Council pipeline). The front end has been rebuilding
against Direction C (light-first, navy masthead, cool off-white canvas, amber-underline nav,
teal eyebrows). The cutover is in local working state, not deployed.

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

## In-flight: Bucket-A first pass (started 2026-04-20)

Per PDF page 20 source-of-truth + Claude Design gap audit cross-check. Scope was narrowed by
user to 5 items — all others are parked. Backend / APIs / polling / auth untouched.

### (1) Top-bar icon visibility — COMPLETE
- `#openSettingsBtn` and `#dsDensityBtn`: `design-v2.css`'s `background: var(--panel-2) !important` on `.settings-gear-btn` was making the gear a white-ish square floating on the navy bar. Overrode with higher-specificity `body[data-ds="v3"] .topbar .settings-gear-btn { background: transparent !important; border: 1px solid rgba(255,255,255,.22); color: rgba(255,255,255,.85); }` + killed the legacy `::before` gradient overlay + sized inline SVG child to 16×16.
- Density button got matching treatment (white-on-navy translucent border, amber border when dense).
- **TODO**: chrome.js still renders an empty `<button id="openSettingsBtn">`. The design-system.css now has the right frame, but the gear glyph itself needs to ship inside the button. Either (a) add an inline SVG gear to chrome.js, or (b) revive the legacy `.settings-gear-wrap > .settings-bar` markup. Pending decision — pause until icon is chosen.

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

## Files touched this session

- `static/css/design-system.css` — icon visibility rules (settings-gear + ds-density-btn), density-scope hide rule, skeleton-shimmer primitive + Markets scope, podium-medal Direction C restyle for text rank badges.
- `static/js/forecasting.js` — medal emoji → `#1/#2/#3` rank badges.
- `static/portfolios.html` — eyebrows on Leaders/Laggards/Holdings.
- `static/forecasting.html` — eyebrows on Consensus Forecasts / Model Leaderboard.

Pending edits:
- `static/js/chrome.js` — pending: inline SVG gear inside `#openSettingsBtn` (awaiting user's call).

---

## Deploy status

**LOCAL ONLY.** Nothing pushed since the last deploy cycle. Live site at `epm-market-intelligence.com` still shows the pre–Direction-C styling until this pass ships.

Deploy target (confirmed via `post_run.py:30-35`):
- Server: `dporter02@192.168.1.145`, path `/opt/epm-market-intelligence/`
- `sync_to_server()` covers `static/`, `charts/`, `commentary/`, `data/`, `services/`, plus a listed set of top-level `.py` files. Does NOT cover `models/`, `generate_pdf_report.py`, or `local_council.py` — those need manual `scp` when they change.
- After any server-side code push: `sudo systemctl restart epm.service` (passwordless sudo is configured).
- Local test workflow: set `SECURE_COOKIES=false`, stop `epm.service` locally (or use uvicorn directly), verify, then restore `SECURE_COOKIES=true` before any push.

---

## Next step on resume

Bucket-A first pass is done. Still blocked on user:
- Verdict on the settings-gear glyph (inline SVG vs. legacy bars).
- Approval to deploy Bucket-A (1)–(5) to production. Deploy = `sync_to_server()` from `post_run.py` + `sudo systemctl restart epm.service`. Remember SECURE_COOKIES=true before push.
- Bucket B decisions (launch cards, brand mark, nav expansion).

Suggested local verification before deploy:
- Markets page under light + dark, animations on + off → skeleton should shimmer cleanly over `--ds-canvas` without the old v2 stripe.
- Forecasting podium → `#1/#2/#3` colored amber/muted/bronze, mono font, no emoji fallback on any OS.
- Portfolios & Forecasting → eyebrows appear above section titles with the teal `--ds-teal` color and uppercase letter-spacing.
