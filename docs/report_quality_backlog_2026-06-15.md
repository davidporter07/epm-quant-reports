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

### 2. Model vs. narrative reconciliation  (HIGH)
- On 6/12 and 6/15 the MAG7 quant signal was max-defensive (6 bearish/1 bullish) while
  the headline stance/Tactical Read was RISK-ON / BULLISH — shipped unreconciled.
- When MAG7/Tactical disagree with the headline stance, force one synthesized sentence
  that names and resolves the tension instead of printing both verbatim.
- **Stance-stability guard:** EPM ran BEARISH (6/8, at the low) → BULLISH (6/15, at the
  high). Flag/justify any ≥2-notch near-term-stance reversal within N sessions.

### 3. Next-day catalyst recap  (MEDIUM)
- The report previewed CPI/PPI all week but never analyzed the actual prints the next
  morning (6/11 shipped the broken stub "The S&P 500's 1.62% decline is.").
- After a scenario event is previewed, the following report MUST recap the released
  figure (2–3 grounded sentences) — feed actuals via `load_recent_macro_prints()`.

### 4. Prescriptive-tone rewrite → optioned / non-advice  (MEDIUM)  [scope: spotlight + daily tactical takeaway]
- Spotlight says "Investors should express this view by leaning into ARKK" — reads as
  *buy this*, single vehicle, no alternative. Daily takeaway "Lean into X; trim Y" has
  the same directive tone and barely changes day to day (XNTK/IXJ/FLQM all week).
- Rewrite both to: "One way to express this is…", **≥2 vehicles**, and a counter-option
  or caveat. **Keep concrete facts** (e.g., "Ark bought >$500M in SpaceX" — good, retain).
- De-template the takeaway so five straight days don't read identically.

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
