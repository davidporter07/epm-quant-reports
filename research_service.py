"""research_service.py — generalized web-discovery enrichment for deep analysis.

Generalizes the Plan-2 PM-discovery agent into a registry of topic researchers
that share one search backend (SearxNG), one cache (services/research_store.py),
and one set of guardrails. Each topic is a small spec with its own query +
grounded LLM extraction, a TTL, and a set of change-keywords that drive
news-based cache invalidation.

`enrich()` is the single entry point used by deep_analysis.build_seed_doc. For a
given symbol it: (1) invalidates cached topics whose facts recent news says
changed, (2) serves fresh cache hits, (3) runs misses concurrently against
SearxNG + a fast Ollama model, and (4) stores results back.

Hard contract (inherited from pm_research/searxng_provider): never raises into the
caller, degrades to {} when SearxNG is down, and only ever asserts facts that
appear in the search snippets (extract-only-from-snippets prompts).
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

import pm_research
from services import research_store
from services import runtime_config as _rc

_OLLAMA_URL = _rc.ollama_url()
_RESEARCH_MODEL = _rc.research_model()
# Concurrency is modest on purpose: the server GPU (A2000, ~5.75GB) can only
# hold one small model at a time, so a burst of cold requests thrashes VRAM.
_MAX_WORKERS = 2
_OLLAMA_TIMEOUT = int(os.getenv("RESEARCH_OLLAMA_TIMEOUT_S", "90"))
# Cold-load budget for the one-shot pre-warm (model -> VRAM under contention).
_PREWARM_TIMEOUT = int(os.getenv("RESEARCH_OLLAMA_PREWARM_S", "180"))
# Keep the model resident across the topic calls in one enrich().
_KEEP_ALIVE = os.getenv("RESEARCH_OLLAMA_KEEP_ALIVE", "10m")

# Sentinel an extractor returns when the snippets contained nothing usable.
_NONE_TOKENS = {"none", "n/a", "no", "nothing", "unknown", ""}


# --------------------------------------------------------------------------- #
# Ollama (fast extraction model — NOT the slow council model)
# --------------------------------------------------------------------------- #
def _research_ollama(prompt: str, timeout: Optional[int] = None) -> str:
    # qwen3.x is a reasoning model — without think:false it generates a long
    # hidden <think> trace before answering, which is slow (esp. with partial
    # CPU offload) and blew the timeout. Extraction needs no reasoning trace.
    r = requests.post(
        f"{_OLLAMA_URL}/api/generate",
        json={
            "model": _RESEARCH_MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "keep_alive": _KEEP_ALIVE,
            "options": {"temperature": 0.1, "top_p": 0.85, "num_ctx": 8192},
        },
        timeout=timeout or _OLLAMA_TIMEOUT,
    )
    r.raise_for_status()
    txt = r.json().get("response", "").strip()
    return re.sub(r"<think>.*?</think>", "", txt, flags=re.DOTALL).strip()


def _prewarm(ollama_call: "OllamaCall") -> None:
    """Load the research model into VRAM before the topic burst so concurrent
    extraction calls hit a warm model instead of all racing a cold load."""
    try:
        ollama_call("Reply with the single word: OK", _PREWARM_TIMEOUT)
    except Exception:
        pass


OllamaCall = Callable[[str, int], str]


# --------------------------------------------------------------------------- #
# Topic spec
# --------------------------------------------------------------------------- #
# A runner returns one of:
#   None                       -> not applicable / backend down (do NOT cache)
#   {"found": False}           -> searched, nothing usable (cache empty for ttl)
#   {"found": True, ...fields} -> store + render
# plus optional "sources" (list[str]) and "confidence" (float) keys.
RunnerResult = Optional[Dict[str, Any]]
Runner = Callable[[Dict[str, Any], Any, OllamaCall], RunnerResult]
Gate = Callable[[Dict[str, Any]], bool]


@dataclass(frozen=True)
class ResearchTopic:
    name: str
    applies_to: str           # "fund" | "stock"
    ttl_days: float
    change_keywords: Tuple[str, ...]
    runner: Runner
    gate: Optional[Gate] = None   # extra applicability check on ctx


# --------------------------------------------------------------------------- #
# Generic single-shot researcher (query -> snippets -> grounded summary)
# --------------------------------------------------------------------------- #
def _simple_research(
    query: str,
    instruction: str,
    searx: Any,
    ollama: OllamaCall,
    *,
    max_results: int = 7,
    confidence: float = 0.6,
) -> RunnerResult:
    results = searx.search(query, max_results=max_results)
    if not results:
        return None
    snippets = pm_research._format_snippets(results)
    if not snippets:
        return {"found": False, "sources": [r["url"] for r in results[:3] if r.get("url")]}
    prompt = (
        f"{instruction}\n\nSEARCH SNIPPETS:\n{snippets}\n\n"
        "Use ONLY facts present in the snippets — do not speculate or add outside "
        "knowledge. If the snippets contain nothing relevant, reply with exactly NONE."
    )
    try:
        answer = ollama(prompt, 60).strip()
    except Exception:
        return None
    sources = [r["url"] for r in results[:3] if r.get("url")]
    if not answer or answer.strip().lower().rstrip(".") in _NONE_TOKENS:
        return {"found": False, "sources": sources}
    return {"found": True, "summary": answer, "sources": sources, "confidence": confidence}


def _simple_runner(query_fn: Callable[[Dict[str, Any]], str], instruction: str) -> Runner:
    def _run(ctx: Dict[str, Any], searx: Any, ollama: OllamaCall) -> RunnerResult:
        return _simple_research(query_fn(ctx), instruction, searx, ollama)
    return _run


def _subject(ctx: Dict[str, Any]) -> str:
    """Best human label for the symbol in a query."""
    return (ctx.get("name") or ctx.get("symbol") or "").strip()


# --------------------------------------------------------------------------- #
# Manager topic — wraps the Plan-2 PM-discovery agent
# --------------------------------------------------------------------------- #
def _run_manager(ctx: Dict[str, Any], searx: Any, ollama: OllamaCall) -> RunnerResult:
    info = pm_research.research_fund_management(
        ctx.get("symbol", ""), _subject(ctx), searx=searx, ollama_call=ollama)
    if not info:
        # could be "no manager found" — record empty so we don't re-search each run
        return {"found": False}
    return {
        "found": True,
        "summary": info.get("manager_summary"),
        "managers": [m.get("name") for m in info.get("managers", []) if m.get("name")],
        "tenure_years": info.get("manager_tenure_years"),
        "sources": info.get("source_urls", []),
        "confidence": 0.7,
    }


def _gate_active_fund(ctx: Dict[str, Any]) -> bool:
    return pm_research.looks_actively_managed(
        name=ctx.get("name", ""), category=ctx.get("category", ""),
        objective=ctx.get("objective", ""), issue_type=ctx.get("issue_type", ""),
        expense_ratio_pct=ctx.get("expense_ratio_pct"),
    )


# --------------------------------------------------------------------------- #
# Topic registry
# --------------------------------------------------------------------------- #
TOPICS: List[ResearchTopic] = [
    # ---- Funds ----------------------------------------------------------- #
    ResearchTopic(
        name="manager", applies_to="fund", ttl_days=60,
        change_keywords=("portfolio manager", "manager", "steps down", "resign",
                         "retire", "appointed", "named", "new manager", "departs"),
        runner=_run_manager, gate=_gate_active_fund,
    ),
    ResearchTopic(
        name="strategy", applies_to="fund", ttl_days=90,
        change_keywords=("strategy", "mandate", "reposition", "overhaul", "approach"),
        runner=_simple_runner(
            lambda c: f"{_subject(c)} fund investment strategy objective approach",
            "Summarize this fund's investment strategy / mandate in 1-2 factual "
            "sentences, and note any recent strategy change if mentioned."),
    ),
    ResearchTopic(
        name="developments", applies_to="fund", ttl_days=5,
        change_keywords=("fee", "expense", "close", "closing", "liquidat", "merger",
                         "reorganiz", "manager", "lawsuit", "investigation"),
        runner=_simple_runner(
            lambda c: f"{_subject(c)} fund news manager fee change closing",
            "List any MATERIAL recent developments for this fund (manager change, "
            "fee/expense change, closure or liquidation, reorganization, notable "
            "litigation). 1-3 short factual sentences."),
    ),
    ResearchTopic(
        name="flows", applies_to="fund", ttl_days=7,
        change_keywords=("inflow", "outflow", "redemption", "assets", "withdrawal"),
        runner=_simple_runner(
            lambda c: f"{_subject(c)} fund inflows outflows net assets trend",
            "Summarize the fund's recent asset flows (net inflows/outflows or AUM "
            "trend) in 1 factual sentence."),
    ),
    # ---- Stocks (Phase B) ----------------------------------------------- #
    ResearchTopic(
        name="management_changes", applies_to="stock", ttl_days=30,
        change_keywords=("ceo", "cfo", "executive", "resign", "steps down",
                         "appointed", "named", "departs", "successor"),
        runner=_simple_runner(
            lambda c: f"{_subject(c)} CEO CFO executive leadership change",
            "Note any recent senior-management changes (CEO/CFO/key executives) "
            "in 1-2 factual sentences."),
    ),
    ResearchTopic(
        name="legal_regulatory", applies_to="stock", ttl_days=7,
        change_keywords=("lawsuit", "sue", "investigation", "probe", "sec ",
                         "doj", "fine", "settlement", "regulator", "antitrust", "recall"),
        runner=_simple_runner(
            lambda c: f"{_subject(c)} lawsuit investigation regulatory fine settlement",
            "Note any material legal or regulatory actions (lawsuits, investigations, "
            "fines, settlements, recalls) in 1-2 factual sentences."),
    ),
    ResearchTopic(
        name="analyst_actions", applies_to="stock", ttl_days=5,
        change_keywords=("upgrade", "downgrade", "price target", "initiated",
                         "rating", "outperform", "underperform"),
        runner=_simple_runner(
            lambda c: f"{_subject(c)} analyst upgrade downgrade price target rating",
            "Note any recent analyst rating actions (upgrades, downgrades, price-target "
            "changes, new coverage) in 1-2 factual sentences."),
    ),
    ResearchTopic(
        name="mna", applies_to="stock", ttl_days=5,
        change_keywords=("acquire", "acquisition", "merger", "buyout", "takeover",
                         "deal", "stake", "divest"),
        runner=_simple_runner(
            lambda c: f"{_subject(c)} merger acquisition deal takeover divestiture",
            "Note any recent M&A activity (acquisitions, mergers, buyouts, divestitures, "
            "stake changes) in 1-2 factual sentences."),
    ),
]

_TOPICS_BY_NAME = {t.name: t for t in TOPICS}


# --------------------------------------------------------------------------- #
# News-driven invalidation
# --------------------------------------------------------------------------- #
def _symbol_news(symbol: str):
    """Recent (Headline, Summary, PublishedAt) rows for a symbol; [] on any error."""
    try:
        from news_store import load_news_store
        df = load_news_store()
        if df is None or df.empty:
            return []
        sub = df[df["Ticker"].astype(str).str.upper() == symbol.upper()]
        return list(sub[["Headline", "Summary", "PublishedAt"]].itertuples(index=False, name=None))
    except Exception:
        return []


def invalidate_from_news(symbol: str, topics: Optional[List[ResearchTopic]] = None) -> List[str]:
    """Mark cached topics stale when recent news mentions a relevant change.

    A topic is invalidated if a headline/summary published AFTER its cached
    fetched_at contains one of the topic's change_keywords. Returns the names
    of topics marked stale.
    """
    topics = topics or TOPICS
    rows = _symbol_news(symbol)
    if not rows:
        return []
    invalidated: List[str] = []
    for topic in topics:
        cached = research_store.get(symbol, topic.name)
        if cached is None:
            continue
        fetched = research_store._parse(cached.get("fetched_at"))
        for headline, summary, published in rows:
            text = f"{headline or ''} {summary or ''}".lower()
            if not any(k in text for k in topic.change_keywords):
                continue
            pub = None
            try:
                if published is not None:
                    pub = published.to_pydatetime() if hasattr(published, "to_pydatetime") else published
                    if pub.tzinfo is None:
                        pub = pub.replace(tzinfo=timezone.utc)
            except Exception:
                pub = None
            # Invalidate when the news is newer than the cache (or undated → be safe).
            if fetched is None or pub is None or pub > fetched:
                research_store.mark_stale(symbol, [topic.name])
                invalidated.append(topic.name)
                break
    return invalidated


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def _applicable(asset_kind: str, ctx: Dict[str, Any]) -> List[ResearchTopic]:
    out = []
    for t in TOPICS:
        if t.applies_to != asset_kind:
            continue
        if t.gate is not None and not t.gate(ctx):
            continue
        out.append(t)
    return out


def enrich(
    symbol: str,
    *,
    name: str = "",
    asset_kind: str = "stock",
    fund_profile: Optional[Dict[str, Any]] = None,
    searx: Any = None,
    ollama_call: Optional[OllamaCall] = None,
) -> Dict[str, Dict[str, Any]]:
    """Discover + cache research for a symbol. Returns {topic: {...}} for topics
    with usable (found) content. Never raises; returns {} if SearxNG is down."""
    try:
        symbol = (symbol or "").upper()
        fund_profile = fund_profile or {}
        ctx: Dict[str, Any] = {
            "symbol": symbol,
            "name": name or fund_profile.get("name") or symbol,
            "asset_kind": asset_kind,
            "category": fund_profile.get("category", ""),
            "objective": fund_profile.get("objective", ""),
            "issue_type": fund_profile.get("issue_type", ""),
            "expense_ratio_pct": fund_profile.get("expense_ratio_pct"),
        }
        topics = _applicable(asset_kind, ctx)
        if not topics:
            return {}

        if searx is None:
            from providers.searxng_provider import SearxNGProvider
            searx = SearxNGProvider()
        if not searx.available():
            return {}
        ollama_call = ollama_call or _research_ollama

        # 1. news-driven invalidation for this symbol's cached topics
        invalidate_from_news(symbol, topics)

        # 2. split into cache hits vs misses
        results: Dict[str, Dict[str, Any]] = {}
        misses: List[ResearchTopic] = []
        for topic in topics:
            cached = research_store.get(symbol, topic.name)
            if cached is not None:
                if cached["content"].get("found"):
                    results[topic.name] = _shape(cached["content"], cached["sources"], cached["fetched_at"])
                continue
            misses.append(topic)

        # 3. run misses concurrently (pre-warm the model first so the burst
        #    doesn't all race a cold VRAM load and time out)
        if misses:
            _prewarm(ollama_call)
            with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(misses))) as ex:
                futs = {ex.submit(_safe_run, t, ctx, searx, ollama_call): t for t in misses}
                for fut in as_completed(futs):
                    topic = futs[fut]
                    res = fut.result()
                    if res is None:
                        continue  # not applicable / backend hiccup — don't cache
                    content = {k: v for k, v in res.items() if k not in ("sources", "confidence")}
                    sources = res.get("sources", [])
                    conf = res.get("confidence", 0.0)
                    research_store.put(symbol, topic.name, content, sources, conf, topic.ttl_days)
                    if content.get("found"):
                        results[topic.name] = _shape(content, sources, _now_iso())
        return results
    except Exception:
        return {}


def _safe_run(topic: ResearchTopic, ctx: Dict[str, Any], searx: Any, ollama: OllamaCall) -> RunnerResult:
    try:
        return topic.runner(ctx, searx, ollama)
    except Exception:
        return None


def _shape(content: Dict[str, Any], sources: List[str], fetched_at: str) -> Dict[str, Any]:
    out = dict(content)
    out["sources"] = sources
    out["fetched_at"] = fetched_at
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
