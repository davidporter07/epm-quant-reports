# Report Quality Backlog — Week of 2026-06-08 → 06-15 (EPM vs. Sevens)

Source: weekly side-by-side grade of EPM daily reports vs. Sevens Report (6/8–6/15).
EPM data layer (cross-asset tables, Treasury curve, MAG7 signals, fund metrics) was
accurate and reconciled with Sevens all week. **All defects below are in the generated
prose / editorial logic, not the data.**

Weekly grade: EPM ~C / C−; Sevens ~A−.

---

## DONE (hotfix, 2026-06-15)

- **Degenerate-repetition guard.** `_scrub_degenerate_repetition()` in
  `generate_market_commentary.py`, wired into `sanitize_commentary()`. Collapses
  verbatim-duplicate sentences across all prose fields and trims a leading mid-clause
  fragment. Fixes the 6/15 `economics_commentary` loop (same 3-sentence block ×40,
  opened with dangling "vs 0.5% prior…"). Tests in `tests/test_commentary_guardrails.py`.

---

## TODO (deferred — gated behind PR H / D2 HOLD; do after a confirmed clean run)

### 1. Catalyst anchoring + selection  (HIGH — recurring)
- **Bug A — wrong day-of-week.** CPI was Wed 6/10, but EPM's Take/Synthesis called it
  "Friday's CPI" (6/8) and "Thursday's CPI" (6/9). Derive the catalyst's weekday from
  the economic calendar, not the LLM. Extend the existing DATE GUARD / `_correct_event_day_slip`.
- **Bug B — wrong catalyst picked.** 6/15 scenario "Primary event" = Atlanta Fed GDPNow
  (a nowcast) while the week had Retail Sales (high) and the **first Warsh-led FOMC**.
  Rule: scenario primary_event = highest-importance dated calendar item (FOMC/CPI/PPI/
  Retail Sales rank above nowcasts).
- **Bug C — holiday blindness.** Never flagged Juneteenth (markets closed Fri 6/19),
  even while citing a "June 19" signing. Add holiday-closure awareness to the calendar feed.

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

### 5. Economics data accuracy  (MEDIUM — surfaced by the hotfix)
- 6/15 printed PPI "13.1% YoY vs 9.4% prior"; the real May print was ~6.5% y/y. Verify
  the PPI series mapping in `data_arbiter` / `_MACRO_PRINT_SPEC` vs. the headline PPI.
- The hotfix collapses the loop but a single dangling "vs 0.5% prior…" sentence can
  still survive mid-paragraph. Optional: trim any mid-paragraph sentence opening with a
  bare connector ("vs"/"and"/"but") — implement carefully to avoid over-trimming.

---

## EPM strengths to preserve (do NOT regress)
Cross-asset data density; full Treasury curve; MAG7 model signals; fund-aware portfolio
metrics (Sharpe/alpha/beta/MaxDD); numeric (non-LLM) support/resistance; consistent
scannable structure; appropriately-hedged geopolitical sourcing (e.g., the 6/15
"Islamabad MoU … remains the key unconfirmed catalyst" was accurate and correctly caveated).
