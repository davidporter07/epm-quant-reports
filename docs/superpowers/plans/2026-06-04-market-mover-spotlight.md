# Market-Mover Spotlight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the daily Topic Spotlight's single slot mover-aware — detect the dominant single-name market mover (hybrid: `get_market_movers()` feed + news/premarket supplement), pick mover-vs-theme-vs-sector with one prevalence score, write whichever wins, and surface a compact mover line in the email's Pre-Market Look.

**Architecture:** New focused module `market_movers.py` holds detection + prevalence selection + teaser building (pure; the movers feed, quote, and LLM scan are injected so tests never hit the network). `generate_topic_spotlight` in `generate_market_commentary.py` builds the three candidates, selects one, and feeds the winner into its existing crawl→verify→write flow. The winning teaser is persisted on the commentary dict and rendered by `send_email.py`. Exactly one story — the mover competes for the existing slot.

**Tech Stack:** Python 3.12, pytest, existing `OpenBBProvider` (`providers/openbb_provider.py`), existing Ollama helpers in `generate_market_commentary.py`.

---

## File structure

- **Create** `market_movers.py` — detection, prevalence selection, teaser (pure helpers).
- **Create** `tests/test_market_movers.py` — unit tests for the module.
- **Modify** `generate_market_commentary.py` — `generate_topic_spotlight` candidate selection; new `SYSTEM_PROMPT_MOVER_SCAN` + default injected fns; persist `spotlight_teaser` in `main`.
- **Modify** `send_email.py` — render the teaser in `_build_premarket_block`.
- **Modify** `tests/test_commentary_guardrails.py` — assert the email teaser renders.

**Candidate dict schema** (shared across all functions):

```python
{
  "kind": "mover" | "theme" | "sector",
  "topic": str,                 # writer headline, e.g. "Broadcom (AVGO) -13% on soft AI guidance"
  "topic_keywords": list[str],  # headline matching + writer grounding
  "why_now": str,
  "category": str,              # "single_name_mover" | scan category | "sector_catalyst"
  "candidate_funds": list[str], # tie-in tickers seeded into fund verification
  "headline_share": float,      # 0..1 share of today's corpus mentioning this
  "magnitude": float,           # FRACTION (0.13 == 13%); 0.0 for theme
  "in_portfolio": bool,
  # mover-only (None otherwise) — used only by build_spotlight_teaser:
  "mover_ticker": str | None,
  "mover_pct": float | None,    # signed fraction, -0.13
  "mover_when": str | None,     # "session" | "premarket"
  "mover_catalyst": str | None,
}
```

---

### Task 1: Module scaffold + constants + `_headline_share`

**Files:**
- Create: `market_movers.py`
- Test: `tests/test_market_movers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_market_movers.py
import market_movers as mm


def _corpus(*texts):
    return [{"text": t, "source": "s", "url": ""} for t in texts]


def test_headline_share_counts_matching_fraction():
    corpus = _corpus(
        "Broadcom plunges 13% on soft guidance",
        "AVGO drags chip sector lower",
        "Gold eases as dollar firms",
        "Treasury yields tick higher",
    )
    # 2 of 4 headlines mention the name/ticker
    assert mm._headline_share(["broadcom", "avgo"], corpus) == 0.5
    assert mm._headline_share(["nonexistent"], corpus) == 0.0
    assert mm._headline_share([], corpus) == 0.0
    assert mm._headline_share(["avgo"], []) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_movers.py::test_headline_share_counts_matching_fraction -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'market_movers'`

- [ ] **Step 3: Write minimal implementation**

```python
# market_movers.py
"""market_movers.py - single-name market-mover detection + spotlight candidate selection.

Feeds the daily Topic Spotlight's single slot. Detection is hybrid: real session gainers/losers
from OpenBBProvider.get_market_movers() plus a news-detected premarket mover verified via
get_quote(). A unified prevalence score (news headline share + move magnitude + portfolio boost)
chooses ONE winner across {news theme, single-name mover, sector fallback}. Pure/testable: the
movers feed, quote, and LLM scan are injected so tests never touch the network.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

# Minimum absolute daily move (FRACTION) for a name to qualify as a "mover".
MOVER_MIN_PCT = 0.04          # 4%
# Floor the winning candidate's prevalence score must clear to take the spotlight slot.
SPOTLIGHT_FLOOR = 0.15
# Portfolio-relevance bump applied to a candidate that touches our funds/holdings.
PORTFOLIO_BOOST = 0.10

# Sector label (lowercased) -> representative ETF for tie-ins.
_SECTOR_ETF = {
    "technology": "XLK", "information technology": "XLK", "semiconductor": "SMH",
    "semiconductors": "SMH", "financials": "XLF", "financial": "XLF", "energy": "XLE",
    "health care": "XLV", "healthcare": "XLV", "industrials": "XLI", "industrial": "XLI",
    "consumer discretionary": "XLY", "consumer staples": "XLP", "utilities": "XLU",
    "materials": "XLB", "real estate": "XLRE", "communication services": "XLC",
    "communication": "XLC",
}


def _headline_share(needles: list[str], corpus: list[dict]) -> float:
    """Fraction of corpus headlines whose text mentions any needle (case-insensitive,
    word-boundary). 0.0 for an empty corpus or no needles."""
    needles = [n.lower().strip() for n in (needles or []) if n and n.strip()]
    if not needles or not corpus:
        return 0.0
    pats = [re.compile(r"\b" + re.escape(n) + r"\b", re.IGNORECASE) for n in needles]
    hits = 0
    for h in corpus:
        text = str(h.get("text") or "")
        if any(p.search(text) for p in pats):
            hits += 1
    return hits / len(corpus)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_market_movers.py::test_headline_share_counts_matching_fraction -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add market_movers.py tests/test_market_movers.py
git commit -m "feat(movers): market_movers module scaffold + _headline_share"
```

---

### Task 2: `_portfolio_tickers` + `_resolve_tie_in_tickers`

**Files:**
- Modify: `market_movers.py`
- Test: `tests/test_market_movers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_portfolio_tickers_from_payload():
    payload = {"tactical_positioning": {
        "top_funds": [{"ticker": "xntk"}, {"ticker": "VSMIX"}],
        "bottom_funds": [{"ticker": "LVHI"}],
    }}
    assert mm._portfolio_tickers(payload) == {"XNTK", "VSMIX", "LVHI"}
    assert mm._portfolio_tickers({}) == set()


def test_resolve_tie_in_tickers_orders_sector_then_peers_then_holdings():
    ties = mm._resolve_tie_in_tickers(
        "AVGO", sector="Technology", peers=["NVDA", "AMD"], portfolio={"XNTK", "AVGO"}
    )
    assert ties[0] == "XLK"          # sector ETF first
    assert "NVDA" in ties and "AMD" in ties
    assert "XNTK" in ties            # holding that relates
    assert "AVGO" not in ties        # never list the mover itself
    assert len(ties) == len(set(ties))  # deduped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_movers.py -k "portfolio_tickers or resolve_tie_in" -v`
Expected: FAIL — `AttributeError: module 'market_movers' has no attribute '_portfolio_tickers'`

- [ ] **Step 3: Write minimal implementation**

```python
def _portfolio_tickers(payload: dict) -> set[str]:
    """Tickers we consider 'in the book' for the portfolio relevance boost: the tactical
    leaders/laggards already computed upstream."""
    out: set[str] = set()
    tp = (payload or {}).get("tactical_positioning") or {}
    for key in ("top_funds", "bottom_funds"):
        for f in (tp.get(key) or []):
            t = str((f or {}).get("ticker") or "").upper().strip()
            if t:
                out.add(t)
    return out


def _resolve_tie_in_tickers(ticker: str, sector: str, peers: list[str],
                            portfolio: set[str]) -> list[str]:
    """Related vehicles for a single-name mover: sector ETF, then peers, then any holding
    that relates. Never includes the mover itself. Deduped, order-preserving."""
    ticker = str(ticker or "").upper().strip()
    out: list[str] = []
    etf = _SECTOR_ETF.get(str(sector or "").lower().strip())
    if etf:
        out.append(etf)
    for p in (peers or []):
        out.append(str(p).upper().strip())
    for h in sorted(portfolio or set()):
        out.append(str(h).upper().strip())
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t and t != ticker and t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_market_movers.py -k "portfolio_tickers or resolve_tie_in" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add market_movers.py tests/test_market_movers.py
git commit -m "feat(movers): portfolio ticker set + tie-in resolution"
```

---

### Task 3: `_session_candidates` (normalize the movers feed)

**Files:**
- Modify: `market_movers.py`
- Test: `tests/test_market_movers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_session_candidates_normalizes_feed_rows():
    movers = {
        "gainers": [{"ticker": "NVDA", "name": "NVIDIA", "day_change_pct": 0.06, "sector": "Technology"}],
        "losers":  [{"ticker": "AVGO", "name": "Broadcom", "day_change_pct": -0.13, "sector": "Technology"}],
    }
    corpus = _corpus("Broadcom plunges 13% on guidance", "AVGO drags chips", "NVIDIA steady")
    cands = mm._session_candidates(movers, corpus, payload={"tactical_positioning": {}})
    avgo = next(c for c in cands if c["mover_ticker"] == "AVGO")
    assert avgo["kind"] == "mover"
    assert avgo["mover_pct"] == -0.13 and avgo["mover_when"] == "session"
    assert abs(avgo["magnitude"] - 0.13) < 1e-9
    assert avgo["headline_share"] > 0          # AVGO/Broadcom appear in the corpus
    assert "XLK" in avgo["candidate_funds"]     # tie-in sector ETF
    # a sub-threshold move (|pct| < MOVER_MIN_PCT) is dropped
    small = {"gainers": [{"ticker": "KO", "name": "Coca-Cola", "day_change_pct": 0.01}], "losers": []}
    assert mm._session_candidates(small, corpus, {}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_movers.py::test_session_candidates_normalizes_feed_rows -v`
Expected: FAIL — `AttributeError: ... '_session_candidates'`

- [ ] **Step 3: Write minimal implementation**

```python
def _mover_candidate(ticker: str, company: str, pct: float, when: str, sector: str,
                     catalyst: str, corpus: list[dict], payload: dict) -> dict:
    """Build a normalized 'mover' candidate dict from a resolved name + verified move."""
    ticker = str(ticker).upper().strip()
    company = str(company or ticker).strip()
    needles = [ticker, company] + [w for w in re.split(r"\s+", company) if len(w) > 3]
    share = _headline_share(needles, corpus)
    portfolio = _portfolio_tickers(payload)
    ties = _resolve_tie_in_tickers(ticker, sector, peers=[], portfolio=portfolio)
    sign = "fell" if pct < 0 else "rose"
    return {
        "kind": "mover",
        "topic": f"{company} ({ticker}) {pct * 100:+.1f}%"
                 + (f" on {catalyst}" if catalyst else ""),
        "topic_keywords": [n.lower() for n in needles],
        "why_now": f"{company} {sign} {abs(pct) * 100:.1f}% ({when}), "
                   f"one of the day's biggest single-name moves"
                   + (f" — {catalyst}" if catalyst else "") + ".",
        "category": "single_name_mover",
        "candidate_funds": ties,
        "headline_share": share,
        "magnitude": abs(float(pct)),
        "in_portfolio": ticker in portfolio,
        "mover_ticker": ticker,
        "mover_pct": float(pct),
        "mover_when": when,
        "mover_catalyst": catalyst or "",
    }


def _session_candidates(movers: dict, corpus: list[dict], payload: dict) -> list[dict]:
    """Normalize the get_market_movers() feed into mover candidates, dropping sub-threshold moves."""
    out: list[dict] = []
    for bucket in ("gainers", "losers"):
        for row in (movers or {}).get(bucket, []) or []:
            ticker = str((row or {}).get("ticker") or "").upper().strip()
            pct = (row or {}).get("day_change_pct")
            try:
                pct = float(pct)
            except (TypeError, ValueError):
                continue
            if not ticker or abs(pct) < MOVER_MIN_PCT:
                continue
            out.append(_mover_candidate(
                ticker, row.get("name") or ticker, pct, "session",
                str(row.get("sector") or ""), "", corpus, payload,
            ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_market_movers.py::test_session_candidates_normalizes_feed_rows -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add market_movers.py tests/test_market_movers.py
git commit -m "feat(movers): normalize get_market_movers feed into candidates"
```

---

### Task 4: `_premarket_candidate` (news-detected name, quote-verified)

**Files:**
- Modify: `market_movers.py`
- Test: `tests/test_market_movers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_premarket_candidate_verifies_pct_via_quote():
    scan = {"ticker": "AVGO", "company": "Broadcom", "pct": -0.10,
            "catalyst": "soft AI guidance", "sector": "Technology"}
    corpus = _corpus("Broadcom plunges 13% premarket", "AVGO guidance disappoints")
    # quote returns the authoritative move; it overrides the LLM's estimate
    cand = mm._premarket_candidate(scan, quote_fn=lambda t: {"day_change_pct": -0.13}, corpus=corpus, payload={})
    assert cand["mover_ticker"] == "AVGO" and cand["mover_when"] == "premarket"
    assert cand["mover_pct"] == -0.13                 # quote wins over the -0.10 estimate
    assert "soft AI guidance" in cand["topic"]


def test_premarket_candidate_corroboration_gate_when_quote_missing():
    scan = {"ticker": "ZZZZ", "company": "Zeta", "pct": -0.09, "catalyst": "lawsuit", "sector": ""}
    # quote fails AND only one headline mentions it -> drop (no trustworthy magnitude)
    assert mm._premarket_candidate(scan, quote_fn=lambda t: {}, corpus=_corpus("Zeta sued"), payload={}) is None
    # quote fails but >=2 headlines corroborate -> keep, using the LLM estimate
    corpus = _corpus("Zeta ZZZZ tumbles on lawsuit", "Zeta shares slide after suit")
    cand = mm._premarket_candidate(scan, quote_fn=lambda t: {}, corpus=corpus, payload={})
    assert cand is not None and abs(cand["mover_pct"] + 0.09) < 1e-9


def test_premarket_candidate_none_when_no_ticker():
    assert mm._premarket_candidate(None, quote_fn=lambda t: {}, corpus=[], payload={}) is None
    assert mm._premarket_candidate({"ticker": ""}, quote_fn=lambda t: {}, corpus=[], payload={}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_movers.py -k premarket_candidate -v`
Expected: FAIL — `AttributeError: ... '_premarket_candidate'`

- [ ] **Step 3: Write minimal implementation**

```python
def _quote_pct(quote_fn: Callable[[str], dict], ticker: str) -> Optional[float]:
    """Resolve a verified daily move (fraction) from get_quote(), tolerating key/scale variants."""
    try:
        q = quote_fn(ticker) or {}
    except Exception:
        return None
    for key in ("day_change_pct", "percent_change", "change_percent", "change_pct", "pct_change"):
        v = q.get(key)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        return v / 100.0 if abs(v) > 1 else v   # normalize percent -> fraction
    return None


def _premarket_candidate(scan: Optional[dict], quote_fn: Callable[[str], dict],
                         corpus: list[dict], payload: dict) -> Optional[dict]:
    """Build a premarket mover candidate from an LLM-detected single name, grounding the % via
    quote_fn; if the quote is unavailable, keep the LLM estimate only when >=2 headlines mention
    the name (corroboration gate)."""
    scan = scan or {}
    ticker = str(scan.get("ticker") or "").upper().strip()
    if not ticker:
        return None
    company = str(scan.get("company") or ticker).strip()
    catalyst = str(scan.get("catalyst") or "").strip()
    sector = str(scan.get("sector") or "").strip()

    pct = _quote_pct(quote_fn, ticker)
    if pct is None:
        try:
            est = float(scan.get("pct"))
        except (TypeError, ValueError):
            return None
        needles = [ticker, company]
        corroboration = sum(
            1 for h in corpus
            if any(re.search(r"\b" + re.escape(n) + r"\b", str(h.get("text") or ""), re.IGNORECASE)
                   for n in needles if n)
        )
        if corroboration < 2:
            return None
        pct = est
    if abs(pct) < MOVER_MIN_PCT:
        return None
    return _mover_candidate(ticker, company, pct, "premarket", sector, catalyst, corpus, payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_market_movers.py -k premarket_candidate -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add market_movers.py tests/test_market_movers.py
git commit -m "feat(movers): quote-verified premarket candidate with corroboration gate"
```

---

### Task 5: `detect_market_mover` (merge + pick strongest)

**Files:**
- Modify: `market_movers.py`
- Test: `tests/test_market_movers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_detect_market_mover_prefers_higher_prelim_score():
    movers = {"gainers": [], "losers": [
        {"ticker": "AVGO", "name": "Broadcom", "day_change_pct": -0.13, "sector": "Technology"},
        {"ticker": "XYZ",  "name": "Xyz Corp", "day_change_pct": -0.05, "sector": "Energy"},
    ]}
    corpus = _corpus("Broadcom plunges 13% premarket", "AVGO drags chip sector", "Xyz dips")
    got = mm.detect_market_mover(
        corpus, enrich_co_news=[], payload={},
        movers_fn=lambda: movers,
        quote_fn=lambda t: {},
        scan_fn=lambda: None,
    )
    assert got["mover_ticker"] == "AVGO"     # bigger move + more headlines wins


def test_detect_market_mover_none_when_nothing_qualifies():
    got = mm.detect_market_mover(
        _corpus("quiet day"), enrich_co_news=[], payload={},
        movers_fn=lambda: {"gainers": [], "losers": []},
        quote_fn=lambda t: {}, scan_fn=lambda: None,
    )
    assert got is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_movers.py -k detect_market_mover -v`
Expected: FAIL — `AttributeError: ... 'detect_market_mover'`

- [ ] **Step 3: Write minimal implementation**

```python
def _prelim_score(c: dict) -> float:
    """Rank movers among themselves: news share + magnitude (capped)."""
    return c.get("headline_share", 0.0) + min(c.get("magnitude", 0.0), 0.30)


def detect_market_mover(
    corpus: list[dict],
    enrich_co_news: list[dict],
    payload: dict,
    *,
    movers_fn: Callable[[], dict],
    quote_fn: Callable[[str], dict],
    scan_fn: Callable[[], Optional[dict]],
) -> Optional[dict]:
    """Return the single strongest mover candidate (session feed + premarket news), or None.

    movers_fn() -> {"gainers": [...], "losers": [...]} (OpenBBProvider.get_market_movers)
    quote_fn(ticker) -> dict        (OpenBBProvider.get_quote, for premarket grounding)
    scan_fn() -> {"ticker","company","pct","catalyst","sector"} | None  (LLM premarket detector)
    """
    candidates: list[dict] = []
    try:
        candidates.extend(_session_candidates(movers_fn() or {}, corpus, payload))
    except Exception:
        pass
    try:
        pre = _premarket_candidate(scan_fn(), quote_fn, corpus, payload)
        if pre:
            candidates.append(pre)
    except Exception:
        pass
    if not candidates:
        return None
    # Dedupe by ticker, keeping the higher-scoring entry (premarket vs session for same name).
    best_by_ticker: dict[str, dict] = {}
    for c in candidates:
        t = c["mover_ticker"]
        if t not in best_by_ticker or _prelim_score(c) > _prelim_score(best_by_ticker[t]):
            best_by_ticker[t] = c
    return max(best_by_ticker.values(), key=_prelim_score)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_market_movers.py -k detect_market_mover -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add market_movers.py tests/test_market_movers.py
git commit -m "feat(movers): detect_market_mover merges session + premarket candidates"
```

---

### Task 6: `theme_candidate` + `select_spotlight_candidate` (the unified gate)

**Files:**
- Modify: `market_movers.py`
- Test: `tests/test_market_movers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_select_spotlight_candidate_prevalence_gate():
    corpus = _corpus(*(["AI capex theme"] * 3 + ["Broadcom plunges 13%"] * 2 + ["misc"] * 5))
    theme = mm.theme_candidate(
        topic="AI capex", topic_keywords=["ai capex"], why_now="w", category="theme",
        candidate_funds=["SMH"], matching=[1, 1, 1], corpus=corpus, payload={},
    )  # headline_share = 3/10 = 0.30
    mover = mm._mover_candidate("AVGO", "Broadcom", -0.13, "premarket", "Technology", "guidance",
                                corpus, payload={})  # share 0.20 + mag 0.13 = 0.33
    win = mm.select_spotlight_candidate([mover, theme])
    assert win["kind"] == "mover"                     # 0.33 > 0.30

    # A mid-size mover with thin news loses to a dominant theme.
    weak = mm._mover_candidate("XYZ", "Xyz", -0.05, "session", "Energy", "", corpus, payload={})
    assert mm.select_spotlight_candidate([weak, theme])["kind"] == "theme"


def test_select_spotlight_candidate_floor_returns_none():
    corpus = _corpus("nothing relevant here", "still nothing")
    weak = mm._mover_candidate("XYZ", "Xyz", -0.04, "session", "", "", corpus, payload={})
    assert mm.select_spotlight_candidate([weak]) is None     # score < SPOTLIGHT_FLOOR


def test_select_spotlight_candidate_portfolio_boost_breaks_tie():
    corpus = _corpus("AVGO moves", "NVDA moves", "filler", "filler")
    held = mm._mover_candidate("AVGO", "Broadcom", -0.05, "session", "Technology", "",
                               corpus, payload={"tactical_positioning": {"top_funds": [{"ticker": "AVGO"}]}})
    notheld = mm._mover_candidate("NVDA", "NVIDIA", -0.05, "session", "Technology", "", corpus, payload={})
    assert mm.select_spotlight_candidate([notheld, held])["mover_ticker"] == "AVGO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_movers.py -k "select_spotlight or theme_candidate" -v`
Expected: FAIL — `AttributeError: ... 'theme_candidate'`

- [ ] **Step 3: Write minimal implementation**

```python
def theme_candidate(topic: str, topic_keywords: list[str], why_now: str, category: str,
                    candidate_funds: list[str], matching: list, corpus: list[dict],
                    payload: dict) -> Optional[dict]:
    """Wrap the existing news-theme scan result as a normalized candidate. headline_share is the
    fraction of the corpus matching the theme (derived from the already-computed `matching` list)."""
    topic = str(topic or "").strip()
    if not topic:
        return None
    share = (len(matching) / len(corpus)) if corpus else 0.0
    funds = [str(t).upper().strip() for t in (candidate_funds or []) if t]
    portfolio = _portfolio_tickers(payload)
    return {
        "kind": "sector" if category == "sector_catalyst" else "theme",
        "topic": topic,
        "topic_keywords": [str(k).lower().strip() for k in (topic_keywords or []) if k],
        "why_now": str(why_now or ""),
        "category": str(category or ""),
        "candidate_funds": funds,
        "headline_share": share,
        "magnitude": 0.0,
        "in_portfolio": any(f in portfolio for f in funds),
        "mover_ticker": None, "mover_pct": None, "mover_when": None, "mover_catalyst": None,
    }


def _prevalence_score(c: dict) -> float:
    mag = c.get("magnitude", 0.0)
    kind = c.get("kind")
    if kind == "mover":
        mboost = min(abs(mag), 0.30)
    elif kind == "sector":
        mboost = min(abs(mag) * 0.5, 0.10)
    else:
        mboost = 0.0
    pboost = PORTFOLIO_BOOST if c.get("in_portfolio") else 0.0
    return c.get("headline_share", 0.0) + mboost + pboost


def select_spotlight_candidate(candidates: list[dict]) -> Optional[dict]:
    """Pick the single highest-prevalence candidate, or None if the top score is below the floor
    (caller then keeps today's sector/evergreen fallback)."""
    cands = [c for c in (candidates or []) if c]
    if not cands:
        return None
    winner = max(cands, key=_prevalence_score)
    return winner if _prevalence_score(winner) >= SPOTLIGHT_FLOOR else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_market_movers.py -k "select_spotlight or theme_candidate" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add market_movers.py tests/test_market_movers.py
git commit -m "feat(movers): theme candidate wrapper + unified prevalence selection gate"
```

---

### Task 7: `build_spotlight_teaser`

**Files:**
- Modify: `market_movers.py`
- Test: `tests/test_market_movers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_spotlight_teaser_mover():
    win = {"kind": "mover", "mover_ticker": "AVGO", "mover_pct": -0.13, "mover_when": "premarket",
           "mover_catalyst": "soft AI guidance", "candidate_funds": ["SMH", "XLK", "NVDA"], "topic": "x"}
    t = mm.build_spotlight_teaser(win)
    assert "AVGO" in t and "-13.0%" in t and "premarket" in t
    assert "soft AI guidance" in t and "SMH" in t and "XLK" in t   # first two tie-ins


def test_build_spotlight_teaser_theme_and_empty():
    assert mm.build_spotlight_teaser({"kind": "theme", "topic": "AI capex cycle"}).endswith("AI capex cycle")
    assert mm.build_spotlight_teaser(None) == ""
    assert mm.build_spotlight_teaser({"kind": "mover", "mover_ticker": "", "topic": ""}) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_movers.py -k build_spotlight_teaser -v`
Expected: FAIL — `AttributeError: ... 'build_spotlight_teaser'`

- [ ] **Step 3: Write minimal implementation**

```python
def build_spotlight_teaser(winner: Optional[dict]) -> str:
    """Compact one-line teaser for the email Pre-Market Look. Mover -> 'Mover: AVGO -13.0% ...';
    theme/sector -> 'Today's Spotlight: <topic>'. Returns '' when there is nothing to show."""
    if not winner:
        return ""
    if winner.get("kind") == "mover":
        tkr = str(winner.get("mover_ticker") or "").strip()
        if not tkr:
            return ""
        parts = [f"Mover: {tkr}"]
        pct = winner.get("mover_pct")
        if isinstance(pct, (int, float)):
            parts.append(f"{pct * 100:+.1f}%")
        when = str(winner.get("mover_when") or "").strip()
        if when:
            parts.append(when)
        line = " ".join(parts)
        catalyst = str(winner.get("mover_catalyst") or "").strip()
        if catalyst:
            line += f" on {catalyst}"
        ties = [t for t in (winner.get("candidate_funds") or []) if t][:2]
        if ties:
            line += " - watch " + ", ".join(ties)
        return line
    topic = str(winner.get("topic") or "").strip()
    return f"Today's Spotlight: {topic}" if topic else ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_market_movers.py -k build_spotlight_teaser -v`
Expected: PASS. Then run the whole module suite: `python -m pytest tests/test_market_movers.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add market_movers.py tests/test_market_movers.py
git commit -m "feat(movers): compact spotlight teaser builder"
```

---

### Task 8: Wire into `generate_topic_spotlight` + persist teaser

**Files:**
- Modify: `generate_market_commentary.py` (`generate_topic_spotlight` ~line 5559; `main` spotlight persist ~line 6180; add `SYSTEM_PROMPT_MOVER_SCAN` near the other prompts)

- [ ] **Step 1: Add the premarket-mover scan prompt.** Near the other `SYSTEM_PROMPT_*` definitions (search for `SYSTEM_PROMPT_TOPIC_SCAN =`), add:

```python
SYSTEM_PROMPT_MOVER_SCAN = (
    "You identify the single biggest SINGLE-STOCK premarket move in today's financial headlines. "
    "Return STRICT JSON: {\"ticker\": str, \"company\": str, \"pct\": float (signed FRACTION, e.g. "
    "-0.13 for -13%), \"catalyst\": short phrase, \"sector\": str} for the one company whose shares "
    "are moving the most premarket on a clear catalyst (earnings, guidance, M&A, capital raise). "
    "If no single stock clearly dominates, return {\"ticker\": \"\"}. Never invent a ticker; use the "
    "real US-listed symbol (Broadcom -> AVGO). pct is your best estimate; it will be price-verified."
)
```

- [ ] **Step 2: Insert candidate selection** in `generate_topic_spotlight`, immediately BEFORE the `# Fund grounding: crawl topic articles` block (after `matching`/`distinct_src` are finalized, ~line 5559). Add:

```python
    # ── Single-name mover competes for the slot via unified prevalence score ──
    import market_movers
    from providers.openbb_provider import OpenBBProvider

    def _default_movers_fn():
        try:
            return OpenBBProvider().get_market_movers(limit=10)
        except Exception as _e:
            print(f"  [SPOTLIGHT] movers feed unavailable ({_e}).")
            return {"gainers": [], "losers": []}

    def _default_quote_fn(_t):
        try:
            return OpenBBProvider().get_quote(_t)
        except Exception:
            return {}

    def _default_mover_scan():
        try:
            res = _call_ollama_raw(SYSTEM_PROMPT_MOVER_SCAN,
                                   {"headlines": [h["text"][:300] for h in headline_corpus[:40]]})
            return res if isinstance(res, dict) and res.get("ticker") else None
        except Exception:
            return None

    _theme_cand = market_movers.theme_candidate(
        topic, topic_keywords, why_now, category, scan_funds, matching, headline_corpus, payload)
    _mover_cand = market_movers.detect_market_mover(
        headline_corpus, enrich_co_news, payload,
        movers_fn=_default_movers_fn, quote_fn=_default_quote_fn, scan_fn=_default_mover_scan)
    _selected = market_movers.select_spotlight_candidate(
        [c for c in (_mover_cand, _theme_cand) if c]) or _theme_cand

    if _selected and _selected.get("kind") == "mover":
        print(f"  [SPOTLIGHT] Mover wins slot: {_selected['mover_ticker']} "
              f"{_selected['mover_pct'] * 100:+.1f}% (share {_selected['headline_share']:.2f}).")
        topic          = _selected["topic"]
        topic_keywords = _selected["topic_keywords"]
        why_now        = _selected["why_now"]
        category       = _selected["category"]
        scan_funds     = list(_selected["candidate_funds"])
        matching       = [h for h in headline_corpus if _topic_matches_text(topic_keywords, h["text"])]
```

- [ ] **Step 3: Attach the teaser to the result.** Change the result assembly (~line 5699) from:

```python
    result = {"title": title, "body": body, "funds": clean_funds, "category": category, "topic": topic}
```
to:
```python
    result = {"title": title, "body": body, "funds": clean_funds, "category": category, "topic": topic}
    result["teaser"] = market_movers.build_spotlight_teaser(_selected)
```

- [ ] **Step 4: Persist `spotlight_teaser`** in `main`, where the spotlight is stored on `existing`. Find both `existing["topic_spotlight"] = _spotlight` assignments (LLM + deterministic paths, ~line 6180/6198) and immediately after each add:

```python
            existing["spotlight_teaser"] = (_spotlight or {}).get("teaser", "")
```
And where the spotlight is popped/absent (the `else: existing.pop("topic_spotlight", None)` branches), add alongside:
```python
            existing.pop("spotlight_teaser", None)
```

- [ ] **Step 5: Verify import + a smoke run.**

Run: `python -c "import generate_market_commentary; import market_movers; print('import OK')"`
Expected: `import OK`
Run: `python -m pytest tests/test_market_movers.py tests/test_commentary_guardrails.py -p no:faulthandler -q`
Expected: all PASS (existing suite unaffected).

- [ ] **Step 6: Commit**

```bash
git add generate_market_commentary.py
git commit -m "feat(movers): wire mover candidate into spotlight selection + persist teaser"
```

---

### Task 9: Render the teaser in the email Pre-Market Look

**Files:**
- Modify: `send_email.py` (`_build_premarket_block`, ~line 290)
- Test: `tests/test_commentary_guardrails.py`

- [ ] **Step 1: Write the failing test** (append near the other email tests):

```python
def test_email_premarket_renders_spotlight_teaser():
    se = pytest.importorskip("send_email")
    html, txt = se._build_premarket_block({
        "spotlight_teaser": "Mover: AVGO -13.0% premarket on soft AI guidance - watch SMH, XLK",
        "futures_table": {"S&P 500 Futures": {"level": 7555.0, "pct_change": 0.16}},
    })
    assert "AVGO -13.0%" in html and "Mover:" in html
    assert any("AVGO -13.0%" in line for line in txt)
    # absent teaser is a clean no-op
    html2, _ = se._build_premarket_block({"futures_table": {}})
    assert "Mover:" not in html2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_commentary_guardrails.py::test_email_premarket_renders_spotlight_teaser -p no:faulthandler -v`
Expected: FAIL — teaser not rendered.

- [ ] **Step 3: Implement.** In `_build_premarket_block(c)`, build a teaser sub-block and prepend it to `inner`. After the line `inner = ''` (just before `if fut_rows:`), insert:

```python
    teaser = _clean(c.get('spotlight_teaser', ''))
    if teaser:
        inner += (
            '<div style="margin:0 0 10px 0;padding:6px 10px;background:#fff7ed;'
            'border-left:3px solid #ea580c;border-radius:4px;font-size:12px;color:#7c2d12;">'
            f'<b>{html_lib.escape(teaser)}</b></div>'
        )
```
And in the plain-text assembly, where `txt_lines = ['PRE-MARKET LOOK', '']` is built, change it to include the teaser:

```python
    txt_lines = ['PRE-MARKET LOOK', '']
    if teaser:
        txt_lines += [teaser, '']
```

Note: the `has_content` early-return (`if not has_content: return '', []`) must still fire when ONLY a teaser exists. Update that guard:

```python
    has_content = fut_rows or earn_parts or fed_parts or econ_parts or teaser
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_commentary_guardrails.py::test_email_premarket_renders_spotlight_teaser -p no:faulthandler -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add send_email.py tests/test_commentary_guardrails.py
git commit -m "feat(movers): render spotlight mover teaser in email Pre-Market Look"
```

---

### Task 10: Full suite + deploy

**Files:** none (verification + deploy)

- [ ] **Step 1: Run the full relevant suite**

Run: `python -m pytest tests/test_market_movers.py tests/test_commentary_guardrails.py -p no:faulthandler -q`
Expected: all PASS.

- [ ] **Step 2: Sanity-check the selection on today's data (no LLM, mocked feed)**

```bash
python -c "
import json, market_movers as mm
c = json.load(open('data/latest_commentary.json', encoding='utf-8'))
corpus = [{'text': h, 'source': 's', 'url': ''} for h in str(c.get('_source_headlines','')).split('  ') if h]
movers = {'gainers': [], 'losers': [{'ticker':'AVGO','name':'Broadcom','day_change_pct':-0.13,'sector':'Technology'}]}
m = mm.detect_market_mover(corpus, [], c, movers_fn=lambda: movers, quote_fn=lambda t: {}, scan_fn=lambda: None)
print('mover:', m and (m['mover_ticker'], round(m['mover_pct'],3), round(m['headline_share'],3)))
print('teaser:', mm.build_spotlight_teaser(m))
"
```
Expected: prints an AVGO mover and a `Mover: AVGO -13.0% ...` teaser (confirms wiring end-to-end on real headlines).

- [ ] **Step 3: Deploy** `market_movers.py` + the two modified files to the server (pipeline runs on the laptop; server keeps parity), then refresh the index.

```bash
cd static && scp -i ~/.ssh/epm_server -o StrictHostKeyChecking=no -O ../market_movers.py ../generate_market_commentary.py ../send_email.py dporter02@100.101.63.65:/opt/epm-market-intelligence/ ; cd ..
npx gitnexus analyze
```

- [ ] **Step 4: Final commit (if any uncommitted)**

```bash
git add -A && git commit -m "chore(movers): market-mover spotlight complete" || echo "nothing to commit"
```

---

## Self-review

- **Spec coverage:** hybrid detection (Tasks 3–5), unified prevalence gate w/ portfolio boost + floor (Task 6), tie-in tickers (Task 2), email teaser (Tasks 7,9), persist-to-website via existing generation sanitize (Task 8 persists `spotlight_teaser` alongside `topic_spotlight`; the deep-dive already flows through `sanitize_commentary`), one-story guarantee (mover replaces the slot, never adds — Task 8). ✔
- **Placeholder scan:** none — every step has concrete code/commands. ✔
- **Type consistency:** the candidate dict schema is identical across `_mover_candidate`, `theme_candidate`, `select_spotlight_candidate`, `build_spotlight_teaser`; `detect_market_mover` signature matches its call site in Task 8; `day_change_pct` is a fraction throughout. ✔
- **Out of scope (unchanged):** general gainers/losers UI, Fed-speaker sourcing, gold spot/futures divergence.
