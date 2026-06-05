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
# A single-name move at/above this magnitude IS the day's story — it takes the spotlight
# slot outright, regardless of how many headlines a diffuse macro theme accumulated.
# Without this, headline_share structurally favors themes and a name like AVGO -15% on
# earnings loses the slot (regression 2026-06-05: tech-selloff theme beat the AVGO mover).
BLOCKBUSTER_PCT = 0.10        # 10%

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


def _resolve_tie_in_tickers(ticker: str, sector: str, peers: list[str]) -> list[str]:
    """Related vehicles for a single-name mover: the sector ETF, then named peers. Never the mover
    itself. We deliberately do NOT list arbitrary portfolio holdings here — without fund-holdings
    data we can't assert a fund relates to this name, and 'watch <unrelated holding>' misleads.
    Portfolio relevance is captured by the in_portfolio score boost instead. Deduped, ordered."""
    ticker = str(ticker or "").upper().strip()
    out: list[str] = []
    etf = _SECTOR_ETF.get(str(sector or "").lower().strip())
    if etf:
        out.append(etf)
    for p in (peers or []):
        out.append(str(p).upper().strip())
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t and t != ticker and t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def _mover_candidate(ticker: str, company: str, pct: float, when: str, sector: str,
                     catalyst: str, corpus: list[dict], payload: dict) -> dict:
    """Build a normalized 'mover' candidate dict from a resolved name + verified move."""
    ticker = str(ticker).upper().strip()
    company = str(company or ticker).strip()
    needles = [ticker, company] + [w for w in re.split(r"\s+", company) if len(w) > 3]
    share = _headline_share(needles, corpus)
    portfolio = _portfolio_tickers(payload)
    ties = _resolve_tie_in_tickers(ticker, sector, peers=[])
    sign = "fell" if pct < 0 else "rose"
    return {
        "kind": "mover",
        "topic": f"{company} ({ticker}) {pct * 100:+.1f}%"
                 + (f" on {catalyst}" if catalyst else ""),
        "topic_keywords": [n.lower() for n in needles],
        "why_now": f"{company} {sign} {abs(pct) * 100:.1f}% ({when}), "
                   f"one of the day's biggest single-name moves"
                   + (f" - {catalyst}" if catalyst else "") + ".",
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

    enrich_co_news is accepted for future tracked-name detection; the current detector sources
    candidates from the movers feed and the premarket scan.
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
    # Empty-funds floor: a sector spotlight must never ship with zero tie-ins (regression
    # 2026-06-05: a "Technology Sector Sell-Off" spotlight rendered funds:[]). Derive the
    # representative sector ETF from the topic/keywords when nothing else resolved.
    if str(category or "") == "sector_catalyst" and not funds:
        hay = " ".join([topic] + [str(k) for k in (topic_keywords or [])]).lower()
        for _label, _etf in _SECTOR_ETF.items():
            if re.search(r"\b" + re.escape(_label) + r"\b", hay):
                funds = [_etf]
                break
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
    """Pick the spotlight winner, or None if nothing clears the bar.

    Blockbuster override first: a single-name mover at/above BLOCKBUSTER_PCT is the day's
    story and takes the slot outright (bypassing the prevalence floor), because
    headline_share otherwise structurally favors diffuse macro themes over a single big
    name. Among multiple blockbusters, the largest move wins. Absent a blockbuster, fall
    back to the unified prevalence score with its floor."""
    cands = [c for c in (candidates or []) if c]
    if not cands:
        return None
    blockbusters = [c for c in cands
                    if c.get("kind") == "mover" and abs(c.get("magnitude", 0.0) or 0.0) >= BLOCKBUSTER_PCT]
    if blockbusters:
        return max(blockbusters, key=lambda c: abs(c.get("magnitude", 0.0) or 0.0))
    winner = max(cands, key=_prevalence_score)
    return winner if _prevalence_score(winner) >= SPOTLIGHT_FLOOR else None


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
