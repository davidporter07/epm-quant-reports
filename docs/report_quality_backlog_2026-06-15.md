# Report Quality Backlog — Week of 2026-06-08 → 06-15 (EPM vs. Sevens)

Source: weekly side-by-side grade of EPM daily reports vs. Sevens Report (6/8–6/15).
EPM data layer (cross-asset tables, Treasury curve, MAG7 signals, fund metrics) was
accurate and reconciled with Sevens all week. **All defects below are in the generated
prose / editorial logic, not the data.**

Weekly grade: EPM ~C / C−; Sevens ~A−.

---

## DONE (2026-06-15)

- **Degenerate-repetition guard.** `_scrub_degenerate_repetition()` in
  `generate_market_commentary.py`, wired into `sanitize_commentary()`. Collapses
  verbatim-duplicate sentences across all prose fields, trims a leading mid-clause
  fragment, AND drops interior sentences that open with a lowercase connector
  (`vs`/`and`/`but`/…) — fully removing the dangling "vs 0.5% prior…" residue while
  preserving legit lowercase-brand sentences (xAI, iPhone). Fixes the 6/15
  `economics_commentary` loop (same 3-sentence block ×40). Commit `fc2e1fa` +
  follow-up. Tests in `tests/test_commentary_guardrails.py`.
- **PPI series correction (item 5a).** `data_arbiter._FRED_ECON_SERIES`: `PPI_YoY`
  switched `PPIACO` (All Commodities, energy-dominated → 13.08% in the oil spike) →
  `PPIFID` (Final Demand, NSA → 6.46%, the headline markets quote; matches Sevens 6.5%).
  Verified live against FRED. This is the source the report used on 6/15.

---

## TODO (deferred — gated behind PR H / D2 HOLD; do after a confirmed clean run)

### 1. Catalyst anchoring + selection  (HIGH — recurring) — PARTIALLY DONE
- ✅ **Bug B root cause + fix.** The 6/15 GDPNow miss was NOT a selection-logic bug
  (logic already prefers high-importance future events, date-sorted). Root cause: the
  **June FOMC date was wrong** in the hardcoded fallback (`06-10` vs the real Warsh
  meeting `06-17`), and `fomcCalendars.json` 404s — so the 6/17 decision never entered
  the forward calendar. Fixed the date + added `_catalyst_priority` so a same-date FOMC
  outranks Retail Sales. Verified live: scenario now selects "FOMC Meeting / Rate
  Decision | 2026-06-17 | Wednesday". Tests added.
- ⏳ **Bug A — synthesis-prose weekday.** Scenario TITLE day is now correct
  (`_event_day_from_dates`), but the Take/Synthesis PROSE can still mislabel a catalyst's
  weekday ("Friday's CPI" 6/8). There's a retry validator (`_check_event_dating`); a
  deterministic weekday corrector keyed to the calendar would close it. Not done.
- ⏳ **Bug C — Juneteenth/holiday blindness.** Still no market-holiday awareness in the
  calendar. Not done.
- ⏳ **Residual:** `fomcCalendars.json` 404 — find the correct Fed JSON endpoint so the
  hardcoded list isn't the sole source; also a stray `2026-07-13` "FOMC press release"
  entry appears from FRED — verify it's real.

### 2. Model vs. narrative reconciliation  — DONE (deterministic guard tested; prompt at next run)
- ✅ **Stance-stability guard.** `_stance_notch_distance` + `_check_stance_reversal_unexplained`
  wired into the Call-2 retry loop: a ≥2-notch near-term reversal vs `prior_day_label`
  (Bearish<Cautious<Neutral<Bullish) that the rationale never acknowledges forces a retry.
  Catches the 6/8 BEARISH→6/15 BULLISH whipsaw class. Tests added.
- ✅ **MAG7 reconciliation (prompt).** `SYSTEM_PROMPT_OUTLOOK` now instructs: when
  `mag7_consensus_forecasts` conflicts with `market_outlook_label` (defensive MAG7 under a
  Bullish label), name and reconcile the tension. Effect confirmed at next live run.

### 3. Next-day catalyst recap  — DONE (prompt; confirm at next run)
- ✅ Threaded `prior_scenario_event` (the catalyst the prior session teased) from the
  saved commentary into the Call-1 narrative payload, and added a PREVIEW→RECAP LINKAGE
  rule to `economics_commentary`: if the previewed catalyst now appears in
  `recent_macro_prints`, LEAD the recap with its actual vs prior + the market's read.
- The general recap instruction (CPI/PCE/GDP/claims/payrolls from `recent_macro_prints`)
  already existed; this closes the specific preview→recap gap. Effect confirmed at next run.
- NOTE: the 6/11 broken stub ("…decline is.") was a generation truncation, not a recap
  gap — not addressed here; a truncated-final-sentence guard is a possible follow-up.

### 4. Prescriptive-tone rewrite → optioned / non-advice  — DONE (verify at next live run)
- ✅ Daily takeaway de-imperatived: "Lean into X; trim Y" → "Relative 1M momentum —
  leaders X; laggards Y" (descriptive model read, not a buy/sell directive).
- ✅ Spotlight prompt reframed: Paragraph 4 is now "HOW TO EXPRESS IT (options, not
  advice)" requiring ≥2 verified_funds, a counter/caveat, and banning imperatives;
  added a NON-ADVICE FRAMING rule.
- ✅ Deterministic belt-and-suspenders: `_scrub_spotlight_text` now softens the exact
  observed imperatives ("Investors should express this view by leaning into …" →
  "One way to express this view is via …"). Tests added.
- NOTE: the prompt-side effect (richer optioned prose, ≥2 vehicles) only manifests in a
  live LLM run — confirm on the next generation. The deterministic softener + takeaway
  changes are active immediately.

### 5. Economics data accuracy  (PARTIALLY DONE — see DONE section)
- ✅ FRED PPI series corrected (PPIACO → PPIFID); ✅ dangling-fragment trim shipped.
- ⏳ **YCharts-side PPI (residual).** When the YCharts scrape populates econ,
  `run_arbitration` uses YCharts ONLY (FRED isn't fetched). Verify the YCharts metric
  `us_producer_price_index_yoy` (scrape_ycharts.py) is Final Demand, not All Commodities,
  so the corrected headline holds regardless of which source wins. Needs a live scrape to
  check; the 6/15 value came from FRED (yc_econ was not populated that day).
- ⏳ Minor: `_arbitrate_economics` labels every entry `source: "ycharts"` even when the
  value came from FRED — cosmetic mislabel, fix when convenient.

---

## EPM strengths to preserve (do NOT regress)
Cross-asset data density; full Treasury curve; MAG7 model signals; fund-aware portfolio
metrics (Sharpe/alpha/beta/MaxDD); numeric (non-LLM) support/resistance; consistent
scannable structure; appropriately-hedged geopolitical sourcing (e.g., the 6/15
"Islamabad MoU … remains the key unconfirmed catalyst" was accurate and correctly caveated).
