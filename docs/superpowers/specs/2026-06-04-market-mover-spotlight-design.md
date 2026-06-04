# Market-Mover Spotlight — Design Spec

**Date:** 2026-06-04
**Status:** Approved (design), pending implementation plan
**Author:** David Porter + Claude (primary backend dev)

## Problem

The daily report misses the single-name **market movers** that drive the tape — e.g. on
2026-06-04 the Sevens report led with **AVGO −13% premarket** (soft AI guidance) and a **GOOGL
+$5B equity raise**, both absent from our email and report. Our existing **Topic Spotlight**
(`generate_topic_spotlight` in `generate_market_commentary.py`) detects a dominant *news theme*
or, on quiet days, the *largest sector move* (`_pick_fallback_theme`), but it has no concept of a
single-stock mover. The result reads as data-dense but blind to "what actually moved today."

## Goal

Make the existing **single** spotlight slot mover-aware: on days a single name dominates the wire,
the spotlight becomes that mover's story (with related ETFs/funds/peers); on other days it behaves
exactly as today (news theme → sector fallback → evergreen). **Never two stories** — the mover
competes for the one existing slot. Additionally surface a **compact mover line in the email's
Pre-Market Look**, since the email was the original gap.

## Decisions (locked via discussion 2026-06-04)

1. **Mover detection = hybrid (movers feed + news/premarket supplement).** Primary candidates come
   from the existing `OpenBBProvider.get_market_movers()` feed (real session gainers/losers with
   verified `day_change_pct`); supplement with news-detected **premarket** movers (e.g. AVGO −13% on
   earnings) verified via `OpenBBProvider.get_quote()`. The session feed grounds magnitude reliably;
   the news/quote path catches pre-bell earnings reactions the session feed misses.
   *(Updated 2026-06-04 after discovering `providers/openbb_provider.py` already exposes
   `get_market_movers()` / `get_quote()` — a market-wide feed I'd initially assumed didn't exist.)*
2. **Selection = unified prevalence score.** Score every candidate (news theme · single-name mover ·
   sector fallback) on one axis — share of today's headlines + a magnitude boost — and pick the
   single highest. The mover only wins when the wire is genuinely about it.
3. **Output surface = compact email line + full story web/PDF.** A one-line mover callout in the
   email Pre-Market Look (`⚡ Mover: AVGO −13% premarket on soft AI guidance — watch SMH, XLK`); the
   full deep-dive stays on the website/PDF exactly like today's spotlight.
4. **Universe = any major mover, portfolio = boost.** Cover any name dominating the wire regardless
   of holdings (like Sevens); if the mover touches our funds/holdings/watchlist, add a small
   prevalence-score boost and surface the holding connection. Always attach related ETFs/peers.

## Architecture (Approach B — extract a focused module, reuse the existing writer)

Rationale: `generate_market_commentary.py` is already ~6,200 lines. New detection/selection logic
goes in a small, independently testable module rather than growing that file. The existing
deep-dive **writer** and tie-in verification are reused unchanged — they just write whichever
candidate wins.

### New module: `market_movers.py`

Pure, network-light, unit-testable functions (movers feed + quote + LLM scan injected/mocked in tests):

- `detect_market_mover(headline_corpus, enrich_co_news, payload, *, movers_fn, quote_fn, scan_fn) -> dict | None`
  - **Session candidates** from `movers_fn()` → `OpenBBProvider.get_market_movers()` returns
    `{gainers:[...], losers:[...]}`, each row `{ticker, name, day_change_pct (fraction), last_price,
    volume, ...}` — magnitude already verified.
  - **Premarket candidates** from the news path: the LLM topic-scan (`scan_fn`) returns the dominant
    single name **and ticker** (and `enrich_co_news` carries tickers for tracked names); verify the
    move via `quote_fn(ticker)` → `OpenBBProvider.get_quote()` (premarket/last % vs prev close). Only
    quote a % when the quote resolves or **≥2 headlines corroborate** it; else describe qualitatively.
  - Compute each candidate's **headline_share** against the corpus, merge, and return the strongest as
    `{ticker, company, pct, when ("session"|"premarket"), catalyst, headline_share, tie_in_tickers,
    in_portfolio: bool}` or `None`.
- `_resolve_tie_in_tickers(ticker, payload) -> list[str]`: sector ETF (from the existing
  `_SECTOR_KW`/sector map) + 1–2 peers + any of our funds/holdings/watchlist that hold it.
- `select_spotlight_candidate(candidates: list[dict]) -> dict | None`
  - Each candidate is normalized to `{kind: "theme"|"mover"|"sector", topic, topic_keywords,
    candidate_funds, why_now, headline_share, magnitude, in_portfolio, ...}`.
  - `score = headline_share + magnitude_boost(kind, magnitude) + portfolio_boost(in_portfolio)`.
  - Returns the highest-scoring candidate, or `None` if the top score is below `SPOTLIGHT_FLOOR`
    (then caller falls back to today's behavior).

### Changes to `generate_market_commentary.py`

- `generate_topic_spotlight(...)`:
  1. Build the news-theme candidate via the existing `SYSTEM_PROMPT_TOPIC_SCAN` (unchanged).
  2. Build the mover candidate via `market_movers.detect_market_mover(...)`.
  3. Build the sector-fallback candidate via the existing `_pick_fallback_theme(...)`.
  4. `winner = market_movers.select_spotlight_candidate([...present candidates...])`.
  5. If `winner is None` → keep today's fallback ladder (sector → evergreen → skip).
  6. Pass `winner` to the **existing deep-dive writer** (unchanged prompt/flow). For a mover:
     `topic = "Broadcom (AVGO) −13% on soft AI guidance"`, `candidate_funds = tie_in_tickers`,
     with the existing no-fabricated-%/AUM tie-in verification.
- On the winning spotlight, also persist a compact **`spotlight_teaser`** string on the commentary
  dict (specialized to `⚡ Mover: <TICKER> <pct> <when> on <catalyst> — watch <tie-ins>` when the
  winner is a mover; a short topic teaser otherwise).
- `spotlight_teaser` is written alongside `topic_spotlight` and flows through the existing
  generation-time `sanitize_commentary` persist step (so no fabricated corporate actions / unsourced
  superlatives reach any surface).

### Changes to `send_email.py`

- In `_build_premarket_block(c)`, render `c.get("spotlight_teaser")` as one compact line at the top
  of the Pre-Market Look block (HTML + plain-text). No-op when absent, so quiet days are unchanged.

## Data flow

```
news corpus (world_news, enrich_news, enrich_co_news), payload, sector_performance
        │
        ├── theme candidate   (SYSTEM_PROMPT_TOPIC_SCAN, existing)
        ├── mover candidate    (market_movers.detect_market_mover → yfinance price-verify)
        └── sector candidate   (_pick_fallback_theme, existing)
        │
   select_spotlight_candidate(...)  ── unified prevalence score → ONE winner (or None→fallback ladder)
        │
        ├── existing deep-dive writer → topic_spotlight  → website + PDF
        └── spotlight_teaser          → email Pre-Market Look (compact line)
```

## Grounding & safety

- The mover **%** is always price-verified or corroboration-gated (≥2 headlines) — never a bare
  LLM number.
- All prose passes the existing `sanitize_commentary` guards at generation persist time and at
  render time (no fabricated corporate actions, no unsourced superlatives, the
  `_spotlight_contradicts_market` direction check still applies).
- **Exactly one story.** The mover is a *candidate for the existing slot*, never an added section.

## Testing (deterministic units; LLM scan + yfinance mocked)

1. `detect_market_mover`: session candidates from a mocked `movers_fn`, premarket candidate from a
   mocked `scan_fn` + `quote_fn`, headline-share ranking, and the value-grounding ladder (feed % →
   quote % → ≥2-headline corroboration → no-number).
2. `select_spotlight_candidate`: given crafted candidates, asserts the expected winner — mover beats
   theme when its headline share dominates; theme beats a mid-size mover; portfolio boost breaks a
   near-tie; sub-floor top score returns `None`.
3. `_resolve_tie_in_tickers`: sector ETF + peers + holding connection for a mover.
4. Email teaser: `_build_premarket_block` renders the `⚡ Mover:` line when present and is a clean
   no-op when absent.

## Out of scope (this spec)

- A general market-wide gainers/losers price feed (universe stays news-driven + verify).
- Fed-speaker sourcing gap (Barkin/Daly) and the gold spot-vs-futures divergence — tracked
  separately.
- Rendering the full deep-dive inside the email (rejected to keep the email lean).

## Affected files

- **new** `market_movers.py`
- **edit** `generate_market_commentary.py` (`generate_topic_spotlight`, persist `spotlight_teaser`)
- **edit** `send_email.py` (`_build_premarket_block`)
- **new** `tests/test_market_movers.py` (+ a teaser assertion in the email guardrail tests)
