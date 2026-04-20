"""
local_council.py — Deterministic multi-persona analyst council.

Replaces MiroFish's NER-driven swarm with seven named analysts plus a synthesis
editor. Each persona makes one Ollama call grounded in KEY_FACTS; the synthesis
call produces the final six-section report.

Pipeline:
  run_council(ticker, seed_text, key_facts) ->
      7x _run_persona  ->  1x synthesis  ->  {takes, enhanced_markdown, raw_markdown}

Runtime on qwen2.5:14b: ~5-8 minutes total (vs MiroFish 25-40 min).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL   = os.environ.get("LOCAL_OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("LOCAL_OLLAMA_MODEL", "qwen2.5:14b")


# ---------------------------------------------------------------------------
# Persona definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Persona:
    name: str              # machine id
    title: str             # display name used in the report
    section_header: str    # substring used to locate the persona's seed section
    system_prompt: str     # persona framing
    focus_fields: List[str] = field(default_factory=list)


PERSONAS: List[Persona] = [
    Persona(
        name="technical_analyst",
        title="Technical Analyst",
        section_header="TECHNICAL ANALYSIS PERSPECTIVE",
        system_prompt=(
            "You are a technical analyst. You read price action, momentum, "
            "volatility regime, relative performance, and overnight/intraday "
            "flow. You do NOT discuss fundamentals or macro policy — leave "
            "those to other analysts. Every claim must cite a specific "
            "number from KEY_FACTS or the seed section."
        ),
        focus_fields=[
            "current_price", "52w_high", "52w_low", "pct_from_52w_high",
            "pct_from_52w_low", "ma50", "ma200", "rsi_14", "mom_5d_pct",
            "mom_20d_pct", "vol_ratio_vs_20d", "atr_14", "atr_percentile",
            "hv_20_annualized_pct", "volatility_regime",
            "overnight_avg_pct_20d", "intraday_avg_pct_20d",
            "sector_momentum_label",
        ],
    ),
    Persona(
        name="growth_investor",
        title="Growth Investor",
        section_header="GROWTH INVESTOR PERSPECTIVE",
        system_prompt=(
            "You are a growth investor. You weigh revenue growth, earnings "
            "growth, forward P/E, PEG, margins, ROE, and whether compounding "
            "justifies the multiple. You value durable growth over cheapness. "
            "Every claim must cite a specific number from KEY_FACTS or the seed."
        ),
        focus_fields=[
            "revenue_growth_pct", "earnings_growth_pct", "forward_pe",
            "peg_ratio", "ev_to_ebitda", "profit_margin_pct",
            "operating_margin_pct", "roe_pct", "analyst_target_price",
            "analyst_target_upside_pct", "analyst_recommendation_score",
        ],
    ),
    Persona(
        name="value_investor",
        title="Value Investor",
        section_header="VALUE INVESTOR PERSPECTIVE",
        system_prompt=(
            "You are a value investor. You care about trailing P/E, EV/EBITDA, "
            "price-to-book, debt-to-equity, dividend yield, and margin of "
            "safety. You are skeptical of story stocks and elevated multiples. "
            "Every claim must cite a specific number from KEY_FACTS or the seed."
        ),
        focus_fields=[
            "trailing_pe", "forward_pe", "peg_ratio", "ev_to_ebitda",
            "price_to_book", "debt_to_equity", "dividend_yield_pct",
            "market_cap_usd", "roe_pct",
        ],
    ),
    Persona(
        name="macro_strategist",
        title="Macro Strategist",
        section_header="MACRO",
        system_prompt=(
            "You are a macro strategist. You frame individual stocks inside "
            "the rate regime, VIX, index trend, and liquidity conditions. You "
            "do NOT drill into stock-specific fundamentals — you draw the "
            "top-down overlay. Every claim must cite a specific number from "
            "KEY_FACTS or the seed section."
        ),
        focus_fields=["vix", "vix_regime", "spy_5d_pct", "spy_20d_pct"],
    ),
    Persona(
        name="supply_chain_risk",
        title="Supply Chain Risk Analyst",
        section_header="SUPPLY CHAIN",
        system_prompt=(
            "You are a supply chain and geopolitical risk analyst. You track "
            "manufacturing concentration, tariff exposure, component sourcing, "
            "shipping lane disruption, and sanction risk. Your perspective is "
            "structural, not quantitative. Name specific countries, corridors, "
            "or suppliers when relevant."
        ),
    ),
    Persona(
        name="bearish_analyst",
        title="Bearish Analyst",
        section_header="BEARISH ANALYST PERSPECTIVE",
        system_prompt=(
            "You are the bearish analyst. Argue the downside case forcefully "
            "— reasons the stock FALLS, not rises. Challenge consensus. Cite "
            "the most pessimistic EPM model and the Kronos bearish target if "
            "available. Name specific price levels where support fails. Do NOT "
            "hedge."
        ),
        focus_fields=[
            "atr_percentile", "volatility_regime", "rsi_14",
            "epm_most_pessimistic_model", "epm_most_pessimistic_pct",
            "kronos_bearish_target", "kronos_bearish_implied_pct",
            "pct_from_52w_high",
        ],
    ),
    Persona(
        name="earnings_catalyst",
        title="Earnings Catalyst Analyst",
        section_header="EARNINGS CATALYST PERSPECTIVE",
        system_prompt=(
            "You are the earnings catalyst analyst. You focus on the next "
            "earnings date, EPS surprise history, beat rate, and the PEAD "
            "(post-earnings announcement drift) signal. Explain what the "
            "historical pattern implies for the upcoming print. Every claim "
            "must cite a specific number from KEY_FACTS or the seed."
        ),
        focus_fields=[
            "next_earnings_date", "days_to_earnings",
            "eps_beat_rate_str", "eps_beat_rate_pct",
            "avg_eps_surprise_pct", "pead_signal",
        ],
    ),
]


# ---------------------------------------------------------------------------
# Ollama and helpers
# ---------------------------------------------------------------------------

def _call_ollama(prompt: str, timeout: int = 240) -> str:
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("response", "").strip()


def _extract_section(seed_text: str, header_fragment: str) -> str:
    """Return lines from a `── <HEADER> ──` marker up to (but not including)
    the next `──` marker. Empty string if no match."""
    lines = seed_text.splitlines()
    start: Optional[int] = None
    for i, ln in enumerate(lines):
        if ln.startswith("──") and header_fragment in ln:
            start = i
            break
    if start is None:
        return ""
    out = [lines[start]]
    for ln in lines[start + 1:]:
        if ln.startswith("──"):
            break
        out.append(ln)
    return "\n".join(out).strip()


def _kf_json(key_facts: Dict[str, Any]) -> str:
    """JSON-serialize key_facts stripping null values."""
    clean = {k: v for k, v in (key_facts or {}).items() if v is not None}
    return json.dumps(clean, indent=2, default=str)


# ---------------------------------------------------------------------------
# Persona prompt construction
# ---------------------------------------------------------------------------

def _persona_prompt(
    persona: Persona,
    ticker: str,
    key_facts: Dict[str, Any],
    section_text: str,
) -> str:
    focus_list = ", ".join(persona.focus_fields) if persona.focus_fields else "(qualitative — no specific fields required)"
    return (
        "IMPORTANT: Respond in English only. Write prose only — no bullet "
        "lists, no markdown headers, no code fences.\n\n"
        f"PERSONA: {persona.title}\n"
        f"{persona.system_prompt}\n\n"
        f"TICKER: {ticker}\n\n"
        "KEY_FACTS — authoritative numeric ground truth. Field names with "
        "`_pct` are already in percent form (34.2 means 34.2%). Use these "
        "EXACT values verbatim wherever you cite a number. Do NOT round, "
        "re-derive, or invent numbers that are not present here:\n"
        f"```json\n{_kf_json(key_facts)}\n```\n\n"
        f"YOUR FOCUS FIELDS (emphasize these): {focus_list}\n\n"
        "YOUR SECTION FROM THE SEED DOCUMENT (narrative context; if a number "
        "here conflicts with KEY_FACTS, KEY_FACTS wins):\n"
        f"```\n{section_text or '(section not available for this persona)'}\n```\n\n"
        f"Write a 180-240 word analysis of {ticker} from your perspective, in "
        "three labeled paragraphs:\n\n"
        "SCENARIO STANCE: Which of bearish / base / bullish is most credible "
        "from your domain and why. Cite 2-3 specific numbers from KEY_FACTS.\n\n"
        "MARKET BEHAVIOR PREDICTION: If your scenario plays out over the next "
        "10 days, name the specific price level or condition that confirms it.\n\n"
        "HIDDEN RISK: One structural risk your domain sees that the quantitative "
        "models do not capture. Name the trigger and the transmission mechanism.\n\n"
        "Rules: no hedging phrases like 'it could go either way' or 'time will "
        "tell'. No generic disclaimers. No quotes or blockquotes. Plain prose, "
        "180-240 words total across the three paragraphs.\n"
    )


def _run_persona(
    persona: Persona,
    ticker: str,
    key_facts: Dict[str, Any],
    seed_text: str,
) -> Dict[str, str]:
    section = _extract_section(seed_text, persona.section_header)
    prompt = _persona_prompt(persona, ticker, key_facts, section)
    t0 = time.time()
    try:
        take = _call_ollama(prompt, timeout=240)
    except Exception as exc:
        logger.warning("Persona %s failed: %s", persona.name, exc)
        take = f"[{persona.title} unavailable — Ollama call failed: {exc}]"
    logger.info("Persona %s done in %.1fs (%d chars)", persona.name, time.time() - t0, len(take))
    return {"name": persona.name, "title": persona.title, "take": take}


# ---------------------------------------------------------------------------
# Synthesis step
# ---------------------------------------------------------------------------

def _synthesis_prompt(
    ticker: str,
    key_facts: Dict[str, Any],
    takes: List[Dict[str, str]],
) -> str:
    takes_block = "\n\n".join(
        f"### {t['title']}\n{t['take']}" for t in takes
    )
    return (
        "IMPORTANT: Your entire response must be written in English only.\n\n"
        "You are the senior editor of an equity research council. Seven "
        "specialist analysts have already submitted their perspectives on "
        f"{ticker}. Produce the final institutional-grade report by "
        "organizing their work into six sections.\n\n"
        "KEY_FACTS — AUTHORITATIVE NUMERIC GROUND TRUTH. Use these EXACT "
        "values anywhere you cite a number. Field names encode units: `_pct` "
        "fields are already in percent form. Do not re-derive, round further, "
        "or invent numbers not present in this JSON:\n"
        f"```json\n{_kf_json(key_facts)}\n```\n\n"
        "ANALYST COUNCIL SUBMISSIONS:\n"
        f"{takes_block}\n\n"
        "Write exactly these six sections in order. Start immediately with "
        "## Quantitative Snapshot. No preamble, no title line.\n\n"
        "## Quantitative Snapshot\n"
        "Two to three paragraphs covering: current price from `current_price` "
        "and where it sits vs `52w_high`, `52w_low`, `ma50`, `ma200`; the "
        "`rsi_14` reading; `mom_20d_pct`; the EPM ensemble spread — name "
        "`epm_most_optimistic_model` and `epm_most_pessimistic_model` with "
        "their exact percentages and explain what `epm_spread_pct` implies "
        "about directional conviction; `vol_ratio_vs_20d`.\n\n"
        "## Quantitative Signals\n"
        "Three paragraphs. (1) Volatility regime: exact `volatility_regime` "
        "label, `atr_14` and `atr_percentile`, `hv_20_annualized_pct`, and "
        "what that regime historically implies for near-term directional "
        "risk. (2) Relative performance: 1m/3m/6m vs sector ETF using the "
        "`rel_perf_*` fields and `sector_momentum_label`; apply Jegadeesh & "
        "Titman momentum framing over 3-12 months. (3) Return attribution "
        "and earnings setup: `overnight_avg_pct_20d` vs `intraday_avg_pct_20d` "
        "and what the split implies about institutional vs retail flow; then "
        "`eps_beat_rate_str`, `avg_eps_surprise_pct`, `pead_signal`, "
        "`next_earnings_date`, `days_to_earnings`.\n\n"
        "## Kronos Scenario Breakdown\n"
        "One paragraph per Kronos scenario that IS PRESENT in KEY_FACTS. "
        "Use `kronos_bearish_target`, `kronos_base_target`, "
        "`kronos_bullish_target` with their `_implied_pct` companions. If a "
        "scenario is absent from KEY_FACTS, omit it entirely — do NOT "
        "fabricate a target. For each present scenario: exact price target "
        "and percent move, what conditions produce that path, how retail vs "
        "institutions would position, which EPM models align.\n\n"
        "## Council Perspectives & Tensions\n"
        "Four paragraphs that synthesize the seven council submissions. "
        "Focus explicitly on where the analysts DISAGREE — tension is more "
        "informative than consensus. Name the analysts by role (e.g. 'the "
        "Value Investor argues...', 'the Technical Analyst counters...'). Do "
        "not paraphrase line by line; surface the actual argumentative cruxes. "
        "If two analysts agree on a point, acknowledge it in one sentence and "
        "move on.\n\n"
        "## Market Participant Reactions\n"
        "Three paragraphs. (1) If price trends toward the bearish Kronos "
        "target, what retail momentum traders do, what value institutions do, "
        "what narrative takes hold — with specific price levels. (2) Same "
        "for the bullish scenario — where short covering adds fuel. (3) What "
        "behavioral dynamic would produce a whipsaw and what signals the "
        "dominant scenario has been decided.\n\n"
        "## Critical Risks Beyond the Models\n"
        "Exactly three numbered risks that quantitative models do not "
        f"capture for {ticker}. For each: the specific risk, its trigger "
        "mechanism, which Kronos scenario it would most accelerate, and the "
        f"early-warning signal. Specific to {ticker}'s business — not generic "
        "market risks.\n\n"
        "Rules: KEY_FACTS numbers override any conflicting number elsewhere. "
        "No blockquotes. No mention of MiroFish, swarm, ontology, or "
        "panorama_search. English only. Start with ## Quantitative Snapshot.\n"
    )


# ---------------------------------------------------------------------------
# Council entry point
# ---------------------------------------------------------------------------

def run_council(
    ticker: str,
    seed_text: str,
    key_facts: Dict[str, Any],
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Any]:
    """Run the 7-persona council + synthesis editor.

    Args:
        progress_cb: optional callback invoked as progress_cb(percent, label)
            where percent is 0-100 scaled within the council portion.

    Returns:
        {
          "takes":             [{"name": str, "title": str, "take": str}, ...],
          "enhanced_markdown": str,  # final 6-section editor report
          "raw_markdown":      str,  # transcript of the 7 persona takes
        }
    """
    takes: List[Dict[str, str]] = []
    n = len(PERSONAS)
    for idx, persona in enumerate(PERSONAS):
        if progress_cb:
            progress_cb(int(100 * idx / (n + 1)), f"council: {persona.title}")
        takes.append(_run_persona(persona, ticker, key_facts, seed_text))

    if progress_cb:
        progress_cb(int(100 * n / (n + 1)), "council: synthesis")

    synth_prompt = _synthesis_prompt(ticker, key_facts, takes)
    t0 = time.time()
    try:
        enhanced = _call_ollama(synth_prompt, timeout=360)
    except Exception as exc:
        logger.error("Council synthesis failed: %s", exc)
        enhanced = ""
    logger.info("Synthesis done in %.1fs (%d chars)", time.time() - t0, len(enhanced))

    if progress_cb:
        progress_cb(100, "council: complete")

    raw = "\n\n".join(f"## {t['title']}\n\n{t['take']}" for t in takes)
    return {
        "takes": takes,
        "enhanced_markdown": enhanced,
        "raw_markdown": raw,
    }


if __name__ == "__main__":
    import sys
    from deep_analysis import build_seed_doc

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    tick = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"Building seed doc for {tick}...")
    seed, kf = build_seed_doc(tick, pred_len=10)
    print(f"  seed: {len(seed)} chars, key_facts: {len(kf)} fields")
    result = run_council(tick, seed, kf, progress_cb=lambda p, s: print(f"  [{p:3d}%] {s}"))
    print("\n" + "=" * 80)
    print("ENHANCED REPORT:")
    print("=" * 80)
    print(result["enhanced_markdown"])
    print("\n" + "=" * 80)
    print(f"takes: {len(result['takes'])} | "
          f"enhanced: {len(result['enhanced_markdown'])} chars | "
          f"raw: {len(result['raw_markdown'])} chars")
