"""pm_research.py — Portfolio-manager discovery agent for actively-managed funds.

For an actively-managed fund/ETF, surface who runs it and for how long:
  1. Resolve PM name(s) via SearxNG (yfinance almost never carries them) and a
     small Ollama extraction step.
  2. For each PM, search tenure / prior firm / background and have Ollama write a
     short Manager Profile.
The result feeds a `── MANAGEMENT & MANDATE ──` seed section and a
`manager_tenure_years` key fact in deep_analysis.build_seed_doc.

Hard contract: this module NEVER raises into the caller and is meant to run
time-boxed in a worker thread. If SearxNG is absent (the live state until the
container is stood up) or anything fails, research_fund_management returns {}
and no section is rendered. Index funds are skipped — they have no
discretionary manager.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

# Phrases that mark a fund as passive/index-tracking (skip PM discovery).
_PASSIVE_MARKERS = (
    "index", "indexed", "s&p 500", "s&p500", "track", "tracks", "tracking",
    "replicat", "passive", "ftse", "msci", "nasdaq-100", "nasdaq 100",
    "russell", "benchmark",
)

OllamaCall = Callable[[str, int], str]


def _default_ollama(prompt: str, timeout: int = 120) -> str:
    # Reuse the council's Ollama path (model/host config + <think> stripping).
    from local_council import _call_ollama
    return _call_ollama(prompt, timeout=timeout, mode="factual")


def looks_actively_managed(
    name: str = "",
    category: str = "",
    objective: str = "",
    issue_type: str = "",
    expense_ratio_pct: Optional[float] = None,
) -> bool:
    """Heuristic: True if the fund is plausibly actively managed.

    Conservative — we'd rather skip a borderline index ETF than burn LLM/web
    calls. Passive if any index marker appears in name/category/objective, or
    if the expense ratio is index-cheap (< 0.12%). Mutual funds lean active.
    """
    blob = " ".join(str(x or "") for x in (name, category, objective)).lower()
    if any(m in blob for m in _PASSIVE_MARKERS):
        return False
    if expense_ratio_pct is not None and expense_ratio_pct < 0.12:
        return False
    return True


def _format_snippets(results: List[Dict[str, Any]], limit: int = 8) -> str:
    lines = []
    for r in results[:limit]:
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()
        if title or content:
            lines.append(f"- {title}: {content}")
    return "\n".join(lines)


def _parse_json_list(raw: str) -> List[str]:
    """Pull a JSON array of strings out of an LLM response, tolerating prose."""
    if not raw:
        return []
    m = re.search(r"\[.*\]", raw, flags=re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    out: List[str] = []
    for item in data if isinstance(data, list) else []:
        s = str(item).strip()
        # filter obvious non-names
        if s and 2 <= len(s) <= 60 and not s.lower().startswith(("n/a", "none", "unknown")):
            out.append(s)
    return out


def _extract_manager_names(snippets: str, fund_name: str, ollama_call: OllamaCall) -> List[str]:
    if not snippets:
        return []
    prompt = (
        "You are extracting facts from web search snippets. Below are snippets about "
        f"the fund \"{fund_name}\".\n\n{snippets}\n\n"
        "List ONLY the names of the people who are portfolio managers of THIS fund. "
        "Return a JSON array of full-name strings, e.g. [\"Jane Smith\", \"John Doe\"]. "
        "If no portfolio manager is clearly named, return []. Do not invent names."
    )
    try:
        raw = ollama_call(prompt, 90)
    except Exception:
        return []
    # de-dup, preserve order
    seen, names = set(), []
    for nm in _parse_json_list(raw):
        key = nm.lower()
        if key not in seen:
            seen.add(key)
            names.append(nm)
    return names


_TENURE_RE = re.compile(r"(\b\d{1,2}(?:\.\d)?)\s*(?:\+|plus)?\s*years?\b", re.IGNORECASE)


def _summarize_manager(
    pm_name: str, fund_name: str, snippets: str, ollama_call: OllamaCall
) -> Dict[str, Any]:
    profile: Dict[str, Any] = {"name": pm_name, "summary": None, "tenure_years": None}
    if not snippets:
        return profile
    prompt = (
        f"From these web snippets about {pm_name}, portfolio manager of \"{fund_name}\":\n\n"
        f"{snippets}\n\n"
        "Write 1-2 factual sentences covering: how long they have managed this fund "
        "(tenure), their prior firm(s)/background, and any noted track record. Use ONLY "
        "facts present in the snippets — if a detail is absent, omit it. Do not speculate. "
        "Start your reply with the tenure if known, e.g. 'Manager since 2015 (~10 years).'"
    )
    try:
        summary = ollama_call(prompt, 90).strip()
    except Exception:
        summary = ""
    if summary:
        profile["summary"] = summary
        m = _TENURE_RE.search(summary)
        if m:
            try:
                profile["tenure_years"] = float(m.group(1))
            except Exception:
                pass
    return profile


def _compose_summary(managers: List[Dict[str, Any]]) -> str:
    parts = []
    for m in managers:
        nm = m.get("name")
        s = m.get("summary")
        if nm and s:
            parts.append(f"{nm}: {s}")
        elif nm:
            parts.append(nm)
    return " | ".join(parts)


def research_fund_management(
    ticker: str,
    fund_name: str,
    *,
    searx: Any = None,
    ollama_call: Optional[OllamaCall] = None,
    max_managers: int = 2,
) -> Dict[str, Any]:
    """Discover PM name(s) + tenure/background for an actively-managed fund.

    Returns {} if SearxNG is unavailable or nothing is found. Otherwise:
      {managers: [{name, summary, tenure_years}], manager_summary: str,
       manager_tenure_years: float|None, source_urls: [str]}
    Never raises.
    """
    try:
        if searx is None:
            from providers.searxng_provider import SearxNGProvider
            searx = SearxNGProvider()
        if not searx.available():
            return {}
        ollama_call = ollama_call or _default_ollama
        fund_name = (fund_name or ticker).strip()

        results = searx.search(f'{fund_name} portfolio manager', max_results=8)
        if not results:
            return {}
        names = _extract_manager_names(_format_snippets(results), fund_name, ollama_call)
        source_urls: List[str] = [r["url"] for r in results[:3] if r.get("url")]
        if not names:
            return {}

        managers: List[Dict[str, Any]] = []
        for nm in names[:max_managers]:
            r2 = searx.search(f'{nm} {fund_name} manager since tenure background', max_results=6)
            for r in r2[:2]:
                if r.get("url") and r["url"] not in source_urls:
                    source_urls.append(r["url"])
            managers.append(_summarize_manager(nm, fund_name, _format_snippets(r2), ollama_call))

        tenures = [m["tenure_years"] for m in managers if m.get("tenure_years") is not None]
        return {
            "managers":             managers,
            "manager_summary":      _compose_summary(managers),
            "manager_tenure_years": min(tenures) if tenures else None,
            "source_urls":          source_urls[:5],
        }
    except Exception:
        return {}
