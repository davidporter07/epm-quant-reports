# Handoff: Deep Analysis Seed Doc Enrichment
Created: 2026-04-17
Updated: 2026-04-18

## Status: PARTIALLY COMPLETE — seed doc enrichment done, MiroFish agent quality work ongoing

---

## What Was Built (Session 2026-04-17)

All five seed doc enrichment tasks from the original spec are complete and deployed. Changes are
single-file in `deep_analysis.py` except where noted.

### Task 1 ✅ `_get_fundamentals()` + Growth/Value section rewrite
- Pulls P/E, forward P/E, PEG, EV/EBITDA, margins, ROE, D/E, market cap, analyst target/consensus
- Uses `trailingAnnualDividendYield` (not `dividendYield` — that field returns a pre-multiplied value
  that causes 100x inflation if you call `_pct()` on it)
- Growth and Value sections now show real numbers before the interpretive text

### Task 2 ✅ `_get_volatility_regime()`
- ATR(14) percentile vs trailing 252-day distribution + HV-20 annualized
- Regime labels: COMPRESSION / LOW / NORMAL / ELEVATED / EXTREME
- Bug fixed: threshold changed from `>= 252` to `>= 28` — `tr_series` has N-1 entries vs OHLCV,
  so the 252-candle check always failed

### Task 3 ✅ `_get_relative_performance()`
- Stock vs sector ETF (SECTOR_ETFS map) over 1m / 3m / 6m
- Momentum label: SECTOR LEADER / INLINE WITH SECTOR / SECTOR LAGGARD
- Jegadeesh & Titman citation included in seed doc output

### Task 4 ✅ `_get_earnings_surprise_history()`
- 8-quarter EPS beat history, beat rate, avg surprise, PEAD signal text
- Note: `surprisePct` column not always populated by yfinance — beat/miss shown even when surprise % is None

### Task 5 ✅ `_get_overnight_stats()`
- 20-day overnight (close→open) vs intraday (open→close) return decomposition
- Institutional accumulation / retail distribution interpretation included

---

## What Was Also Built (MiroFish Agent Quality, Session 2026-04-17/18)

### Problem identified
MiroFish's ontology extractor uses NER on the seed doc to decide which entities become agents.
It picks up real-world named entities (Apple Inc., Federal Reserve, Financial Media, Kronos) rather
than the section headers we intend as agent personas. The dominant agent each run is whichever
well-known proper noun appears most prominently.

History of dominant agents across runs:
- Run 1 (before patch): Apple Inc. (5/8 posts) — from first line + repeated in section bodies
- Run 2 (after co_info name removal): Financial Media (7/9 posts) — from Market Commentator body
- Run 3 (after SIMULATION PARTICIPANTS block): KRONOS OHLCV FOUNDATION MODEL (3 posts) — from section header
- Run 4 (after Kronos header renamed, agent names uppercased): Federal Reserve (7/8 posts) — from Macro section header
- Run 5 (current): Federal Reserve still dominant

### Fixes applied
1. Removed `co_info['name']` from all section bodies — replaced with `{ticker}` to prevent company
   as dominant entity
2. Added `SIMULATION PARTICIPANTS` block near top of seed doc listing 7 agent names in all-caps
3. Renamed `── KRONOS OHLCV FOUNDATION MODEL ──` to `── PRICE SCENARIO FORECASTS ──`
4. Replaced "financial media" with "market commentator" in Market Commentator section body
5. Added explicit agent persona list to `simulation_requirement` in `deep_analysis_worker.py`
6. Uppercased agent names in SIMULATION PARTICIPANTS block (TECHNICAL ANALYST etc.)

### LLM post-processing improvements (deep_analysis_worker.py)
- `seed_excerpt` increased from 5000 → 10000 chars so all new signal sections reach the LLM
- Added `## Quantitative Signals` section to the report template — explicitly instructs the LLM
  to reference ATR percentile, relative sector performance, overnight/intraday split, EPS beat rate,
  PEAD signal
- Validation required headers updated to include `## Quantitative Signals`
- Analysis Objective in seed doc got a 5th question: asking agents to reconcile PEAD drift signal
  vs Kronos base case

---

## Remaining Work (Next Session)

### Fix A — HIGH PRIORITY: Rename Federal Reserve out of section header
The `── MACRO / FEDERAL RESERVE PERSPECTIVE ──` header is the current entity trap.
"Federal Reserve" is one of the strongest named entities any NER model knows — it wins every run.

**In `deep_analysis.py`:**
```python
# Change:
lines.append("── MACRO / FEDERAL RESERVE PERSPECTIVE ─────────────────────────────────────────")

# To:
lines.append("── MACRO STRATEGIST PERSPECTIVE ─────────────────────────────────────────────────")
```

Also scrub "Federal Reserve" from the section body text — replace with "the central bank" or
"monetary policymakers". The hardcoded line currently reads:
```
"Interest Rate Environment: Federal Reserve maintaining elevated rates..."
```
Change to:
```
"Interest Rate Environment: The central bank is maintaining elevated rates..."
```

### Fix B — MEDIUM PRIORITY: Inject ground-truth numbers into LLM prompt preamble
The raw swarm agents (qwen2.5 running inside MiroFish) hallucinate numbers — seen P/E 23x instead
of 34.2x, ROE 15% instead of 152%, dividend yield 2% instead of 0.39%. These bleed into the
LLM post-processing even though we tell it to use Source A.

Fix: add a compact key-facts block at the top of the LLM prompt with the 6-8 most critical numbers
extracted from seed_text so the model has them as explicit ground truth, not buried in 10k chars:

```python
# Extract and inject key numbers as a grounding block before the full seed excerpt
# e.g.: "KEY FACTS (use these exact numbers, do not substitute):
#   Current price: $270.23 | Trailing P/E: 34.2x | Forward P/E: 29.0x | ROE: 152.0%
#   Revenue growth: +15.7% | Earnings growth: +18.3% | Dividend yield: 0.39%
#   ATR(14): $6.32 (90.3th pct) | HV-20: 21.9% | Beat rate: 4/4 quarters"
```

This requires parsing these values out of the seed_text string (or passing them as a separate
structured dict from `build_seed_doc`). The cleanest approach: have `build_seed_doc` return
both the text and a `key_facts: Dict` so the worker can inject them without string parsing.

### Fix C — LOW PRIORITY: Suppress remaining named entity traps
Even after Fix A, these named entities in the seed doc may still become agents:
- "SPY" (mentioned in Macro section) — minor, usually 0 posts
- "ARIMAX" (mentioned in EPM section and Analysis Objective) — has appeared as agent before
- "XLK" (in relative performance section) — low risk but worth watching

Mitigation: refer to them as "the sector ETF" / "the most pessimistic model" rather than by name
in the Analysis Objective and section bodies.

---

## Current State of Enhanced Report Quality

The LLM post-processing layer (`_postprocess_with_llm` in `deep_analysis_worker.py`) is now
doing most of the analytical heavy lifting correctly:

✅ All 7 personas appear: Technical Analyst, Growth Investor, Value Investor, Macro Strategist,
   Supply Chain Risk Analyst, Bearish Analyst, Earnings Catalyst Analyst
✅ PEAD signal referenced in Earnings Catalyst section
✅ Volatility regime (ATR percentile) referenced by Technical Analyst
✅ EPS beat history and upcoming earnings date used in Earnings Catalyst reasoning
✅ Real fundamental numbers flowing through (P/E, growth rates, margins)
⚠️  Some numbers still occasionally hallucinated — Fix B addresses this
⚠️  Raw swarm agent composition still wrong — Fix A will help but may not fully resolve

The raw swarm is best understood as a "disagreement engine" whose qualitative tensions the LLM
post-processor organizes. The swarm's specific numbers are unreliable; the LLM is told to use
Source A (seed doc) numbers only.

---

## Key Files

- `D:\fund_monitor\deep_analysis.py` — seed doc builder (all enrichment + agent fixes)
- `D:\fund_monitor\deep_analysis_worker.py` — pipeline runner + LLM post-processing prompt
- `D:\fund_monitor\notes\handoffs\HANDOFF_mirofish_test.md` — full MiroFish architecture reference

## Server Access

```bash
ssh -i ~/.ssh/epm_server dporter02@192.168.1.145
sudo systemctl restart epm.service
sudo journalctl -u epm.service -f   # live logs
```

## Deployment

```bash
# From D:/fund_monitor:
scp -i ~/.ssh/epm_server deep_analysis.py deep_analysis_worker.py dporter02@192.168.1.145:/opt/epm-market-intelligence/
# Then restart service on server
```
