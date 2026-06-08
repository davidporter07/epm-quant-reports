"""
local_council.py — Deterministic multi-persona analyst council.

Three-round deliberation:
  Round 1 (R1): 7 independent stances — each persona reads only KEY_FACTS + seed section.
  Round 2 (R2): 7 debate responses — each reads all R1 takes, MUST name a dissenting analyst.
  Round 3 (R3): 7 brief final positions — 60-80 words each after reviewing all R2 takes.
  Synthesis   : 1 senior-editor report covering the full debate arc.

Pipeline:
  run_council(ticker, seed_text, key_facts) ->
      7x R1  ->  7x R2  ->  7x R3  ->  synthesis
      -> {takes, takes_by_round, enhanced_markdown, raw_markdown}

Runtime on deepseek-r1:8b: ~45-75 min (22 Ollama calls; model swap on first call ~60s).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL   = os.environ.get("LOCAL_OLLAMA_URL",    "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("COUNCIL_OLLAMA_MODEL", "deepseek-r1:8b")


# ---------------------------------------------------------------------------
# Persona definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Persona:
    name: str
    title: str
    section_header: str
    system_prompt: str
    focus_fields: List[str] = field(default_factory=list)
    # "neutral" forms its own view from evidence; "bull"/"bear" open by arguing
    # their side but vote honestly and may concede in later rounds.
    kind: str = "neutral"


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
        name="growth_analyst",
        title="Growth Analyst",
        section_header="GROWTH INVESTOR PERSPECTIVE",
        system_prompt=(
            "You are a growth analyst. You weigh revenue growth, earnings growth, "
            "forward P/E, PEG, margins, and ROE to judge whether the growth rate "
            "justifies the valuation. Reach your own conclusion objectively — say so "
            "if the growth supports the multiple AND if it does not; you have no "
            "predisposition toward optimism or skepticism. If a recent earnings release "
            "is present (eps_release_surprise_pct), weight it heavily — it supersedes "
            "historical averages. Every claim must cite a specific number from KEY_FACTS "
            "or the seed."
        ),
        focus_fields=[
            "revenue_growth_pct", "earnings_growth_pct", "forward_pe",
            "peg_ratio", "ev_to_ebitda", "profit_margin_pct",
            "operating_margin_pct", "roe_pct", "analyst_target_price",
            "analyst_target_upside_pct", "analyst_recommendation_score",
            "eps_release_surprise_pct", "reported_eps", "analyst_targets_may_be_stale",
        ],
    ),
    Persona(
        name="valuation_analyst",
        title="Valuation Analyst",
        section_header="VALUE INVESTOR PERSPECTIVE",
        system_prompt=(
            "You are a valuation analyst. You weigh trailing P/E, EV/EBITDA, "
            "price-to-book, debt-to-equity, dividend yield, and margin of safety to "
            "judge whether the current price is justified by the underlying business. "
            "Assess this objectively in BOTH directions — flag overvaluation and "
            "undervaluation alike, and do not assume an elevated multiple is unwarranted "
            "if the fundamentals support it. Every claim must cite a specific number "
            "from KEY_FACTS or the seed."
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
        name="operations_analyst",
        title="Operations & Supply Chain Analyst",
        section_header="SUPPLY CHAIN",
        system_prompt=(
            "You are an operations and supply chain analyst. You assess the company's "
            "manufacturing footprint, component sourcing, logistics, and geopolitical "
            "exposure — weighing BOTH operational resilience and competitive advantages "
            "AND risks or vulnerabilities, not only the downside. Your perspective is "
            "structural, not quantitative. Name specific countries, corridors, or "
            "suppliers when relevant. If legal_regulatory_note or mna_note are present "
            "in KEY_FACTS, factor those structural events into your view in whichever "
            "direction the evidence points."
        ),
        focus_fields=["legal_regulatory_note", "mna_note"],
    ),
    Persona(
        name="bull_analyst",
        title="Bull Analyst",
        section_header="BULLISH ANALYST PERSPECTIVE",
        kind="bull",
        system_prompt=(
            "You are the bull analyst. In Round 1, build the strongest evidence-based "
            "case for why the stock RISES — cite the most optimistic EPM model, the "
            "Kronos bullish target, upside catalysts, and the price levels where it "
            "breaks out. Make the upside impossible to ignore. You are an honest analyst, "
            "not a permabull: if later rounds show the downside decisively outweighs the "
            "upside, you may concede. Cite specific numbers from KEY_FACTS; never invent."
        ),
        focus_fields=[
            "epm_most_optimistic_model", "epm_most_optimistic_pct",
            "kronos_bullish_target", "kronos_bullish_implied_pct",
            "analyst_target_upside_pct", "eps_release_surprise_pct",
            "revenue_growth_pct", "earnings_growth_pct", "pct_from_52w_low",
            "mgmt_change_note", "analyst_action_note", "mna_note",
        ],
    ),
    Persona(
        name="bear_analyst",
        title="Bear Analyst",
        section_header="BEARISH ANALYST PERSPECTIVE",
        kind="bear",
        system_prompt=(
            "You are the bear analyst. In Round 1, build the strongest evidence-based "
            "case for why the stock FALLS — cite the most pessimistic EPM model, the "
            "Kronos bearish target, downside catalysts, and the price levels where support "
            "fails. Make the downside impossible to ignore. You are an honest analyst, not "
            "a permabear: if later rounds show the upside decisively outweighs the downside, "
            "you may concede. Cite specific numbers from KEY_FACTS; never invent."
        ),
        focus_fields=[
            "atr_percentile", "volatility_regime", "rsi_14",
            "epm_most_pessimistic_model", "epm_most_pessimistic_pct",
            "kronos_bearish_target", "kronos_bearish_implied_pct",
            "pct_from_52w_high",
            "mgmt_change_note", "legal_regulatory_note", "analyst_action_note", "mna_note",
        ],
    ),
    Persona(
        name="earnings_catalyst",
        title="Earnings Catalyst Analyst",
        section_header="EARNINGS CATALYST PERSPECTIVE",
        system_prompt=(
            "You are the earnings catalyst analyst. You focus on the next "
            "earnings date, EPS surprise history, beat rate, and the PEAD "
            "(post-earnings announcement drift) signal. If eps_release_surprise_pct "
            "is present in KEY_FACTS, it is the CONFIRMED most-recent-quarter actual — "
            "treat it as your primary evidence and note whether it is extraordinary (>30%). "
            "The pead_signal field reflects this. Every claim must cite a specific "
            "number from KEY_FACTS or the seed."
        ),
        focus_fields=[
            "next_earnings_date", "days_to_earnings",
            "eps_beat_rate_str", "eps_beat_rate_pct",
            "avg_eps_surprise_pct", "pead_signal",
            "eps_release_surprise_pct", "reported_eps", "estimated_eps",
            "earnings_release_detected", "pead_extraordinary_note",
        ],
    ),
]


# Swapped in for the earnings_catalyst persona when the subject is a fund/ETF
# (earnings have no meaning for a basket). See run_council().
FUND_STRUCTURE_PERSONA = Persona(
    name="fund_structure",
    title="Fund Structure Analyst",
    section_header="FUND COMPOSITION & MANDATE",
    system_prompt=(
        "You are a fund structure analyst. You reason over the fund's top-holding "
        "concentration, sector tilt, stated mandate/objective, expense drag, and — "
        "for actively-managed funds — the manager's tenure and track record. NOT "
        "single-company earnings. Judge whether the holdings match the stated "
        "mandate, whether concentration creates single-name risk, whether the "
        "expense ratio is justified versus comparable funds, and (if manager_summary "
        "is present) whether management tenure/background supports confidence in the "
        "strategy. Every claim must cite a specific number or fact from KEY_FACTS or "
        "the FUND COMPOSITION & MANDATE seed section."
    ),
    focus_fields=[
        "is_fund", "fund_type", "fund_category", "fund_family",
        "expense_ratio_pct", "top10_concentration_pct", "top_holdings",
        "fund_objective", "fund_managers", "manager_summary", "manager_tenure_years",
        "fund_strategy", "fund_developments", "fund_flows",
    ],
)


# ---------------------------------------------------------------------------
# Exemplar constants — swap these in one place to upgrade output quality.
# Both use a fictitious NVDA scenario so they are unambiguously not the
# live ticker being analysed.
# ---------------------------------------------------------------------------

_BANNED_PHRASES_RULE = (
    "BANNED PHRASES — never use: 'suggests', 'could lead to', 'may indicate', "
    "'potentially', 'likely', 'appears to', 'tends to', 'it seems', 'might'. "
    "State every claim decisively. If genuine uncertainty exists, name the "
    "specific condition: e.g. 'Below MA50 = bearish; above = base case' — "
    "NOT 'the MA50 may provide support'."
)

_FIELD_GLOSSARY = (
    "PLAIN-ENGLISH FIELD NAMES — when citing any KEY_FACTS field, use the human-readable label, "
    "never the raw variable name:\n"
    "  rsi_14              → RSI (14-day)\n"
    "  atr_percentile      → ATR percentile\n"
    "  hv_20_annualized_pct → 20-day annualized volatility\n"
    "  volatility_regime   → volatility regime\n"
    "  mom_5d_pct          → 5-day momentum\n"
    "  rel_perf_1m_stock_pct → 1-month stock return\n"
    "  rel_perf_1m_etf_pct → 1-month sector ETF return\n"
    "  rel_perf_1m_diff_pct → 1-month return vs. sector ETF\n"
    "  rel_perf_3m_diff_pct → 3-month return vs. sector ETF\n"
    "  rel_perf_6m_diff_pct → 6-month return vs. sector ETF\n"
    "  forward_pe          → forward P/E ratio\n"
    "  trailing_pe         → trailing P/E ratio\n"
    "  peg_ratio           → PEG ratio\n"
    "  price_to_book       → price-to-book ratio\n"
    "  ev_to_ebitda        → EV/EBITDA\n"
    "  analyst_target_upside_pct → analyst consensus target upside\n"
    "  eps_beat_rate_str   → EPS beat record\n"
    "  eps_beat_rate_pct   → EPS beat rate\n"
    "  pead_signal         → post-earnings drift signal\n"
    "  days_to_earnings    → days to next earnings\n"
    "  next_earnings_date  → next earnings date\n"
    "  debt_to_equity      → debt-to-equity ratio\n"
    "  roe_pct             → return on equity\n"
    "  profit_margin_pct   → net profit margin\n"
    "  operating_margin_pct → operating margin\n"
    "  kronos_base_implied_pct → Kronos base case implied return\n"
    "  kronos_bear_target  → Kronos bear case price target\n"
    "  kronos_base_target  → Kronos base case price target\n"
    "  kronos_bull_target  → Kronos bull case price target\n"
    "  spy_20d_pct         → S&P 500 20-day return\n"
    "  vix_regime          → VIX risk regime\n"
    "  epm_most_pessimistic_model → most pessimistic EPM model\n"
    "  epm_ensemble_implied_pct → EPM ensemble implied return\n"
    "  eps_release_surprise_pct → most recent quarter EPS surprise % (confirmed post-release)\n"
    "  reported_eps             → most recent quarter reported EPS\n"
    "  estimated_eps            → most recent quarter EPS estimate\n"
    "  earnings_release_detected → whether a same-day earnings release was captured\n"
    "  analyst_targets_may_be_stale → analyst price targets predate the most recent earnings release\n"
    "  pead_extraordinary_note  → explanation when EPS surprise is extraordinary (>30%)\n"
    "Example: write '3-month return vs. sector ETF at -5.19%' NOT 'rel_perf_3m_diff_pct at -5.19'.\n"
)

_R1_EXEMPLAR = """\
── EXEMPLAR (style reference only — do NOT copy content; use KEY_FACTS for {ticker}, not these examples) ──

BAD — never write like this:
STANCE: bearish
CLAIM: The stock appears overvalued and could decline.
EVIDENCE: Valuation metrics suggest the stock may be expensive relative to peers.
MECHANISM: High multiples tend to compress, which could lead to selling pressure.
WHAT WOULD CHANGE MY MIND: If the fundamentals improve.

GOOD BEAR example — write with this precision:
STANCE: bearish
CLAIM: The bullish case is confusing business quality with stock attractiveness at current multiples.
EVIDENCE: The market is already pricing in durable growth. A weak upgrade cycle leaves little room for estimate upside. Analyst downgrades have cited expensive relative valuation with no expected strong upgrade cycle within the next year.
MECHANISM: When expectations are high, stable fundamentals are not enough. The multiple contracts if investors realise growth is merely average. If upgrade demand disappoints, the stock derates even if the business remains high quality.
WHAT WOULD CHANGE MY MIND: Accelerating device demand and Services growth at the same time would make the premium multiple easier to defend.

GOOD BULL example — write with this precision:
STANCE: bullish
CLAIM: The council is overweighting valuation risk and underweighting operating leverage from the installed base.
EVIDENCE: Services revenue is growing faster than total company revenue. Services margins are structurally higher than product margins. A stronger device cycle increases the installed base, which feeds higher-margin recurring revenue.
MECHANISM: The device sale creates the customer relationship. Services extract recurring profit from that relationship. That combination can justify a premium multiple even when hardware unit growth slows.
WHAT WOULD CHANGE MY MIND: Two consecutive quarters of weaker hardware demand and slowing Services growth would break this thesis.
── END EXEMPLAR ──\
"""

_R2_EXEMPLAR = """\
── EXEMPLAR (style reference only — do NOT copy content; cite KEY_FACTS for {ticker}, not these examples) ──

STANCE: neutral (updated from bullish in Round 1)
CLAIM: The correct debate is not hardware versus Services. It is whether hardware can keep feeding Services at the pace bulls assume.
EVIDENCE: Services monetisation depends on installed base engagement. Hardware demand determines how many users enter and refresh the ecosystem. Valuation determines how much growth is already priced in.
MECHANISM: If hardware stagnates, Services can delay the earnings problem but not eliminate it. A declining active device count eventually caps Services attach rates regardless of per-user monetisation gains.
DISAGREEMENT: I disagree with the Growth Analyst's argument that Services growth makes valuation risk secondary. Services are not independent from hardware. A simple "Services are big, buy the dip" argument ignores that Services revenue per user must rise fast enough to fully offset slower device volume — and the data does not yet confirm that rate.
WHAT WOULD CHANGE MY MIND: Evidence that Services revenue per user is rising fast enough to offset a slower device cycle, or proof that active device count is still expanding despite weaker gross shipments.
── END EXEMPLAR ──\
"""

_SYNTHESIS_QUALITY_STANDARD = """\
EDITOR QUALITY STANDARD:
Reject: generic phrases like "momentum remains strong", claims without a mechanism, one-sided arguments that ignore valuation or timing, conclusions that do not name what evidence would change the view.
Require: clear stance, specific evidence, named mechanism, direct identification of the crux disagreement, and what the strongest hidden risk is if the consensus is wrong.
Synthesis task: identify the real crux of disagreement — do not average the opinions. Decide which argument has the strongest evidence and which hidden risk would matter most if the consensus turns out to be wrong.\
"""


# ---------------------------------------------------------------------------
# Ollama and helpers
# ---------------------------------------------------------------------------

def _call_ollama(prompt: str, timeout: int = 600, mode: str = "factual") -> str:
    if mode == "synthesis":
        options = {"temperature": 0.55, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.05, "num_ctx": 8192}
    else:
        options = {"temperature": 0.2, "top_p": 0.85, "top_k": 20, "repeat_penalty": 1.05, "num_ctx": 8192}
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": options},
        timeout=timeout,
    )
    r.raise_for_status()
    return _strip_reasoning(r.json().get("response", "").strip())


def _strip_reasoning(text: str) -> str:
    """Strip DeepSeek-R1 <think>...</think> blocks before storing analyst takes."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_section(seed_text: str, header_fragment: str) -> str:
    """Return lines from a `── <HEADER> ──` marker up to the next `──` marker."""
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
    clean = {k: v for k, v in (key_facts or {}).items() if v is not None}
    return json.dumps(clean, indent=2, default=str)


def _kf_json_filtered(key_facts: Dict[str, Any], focus_fields: List[str]) -> str:
    """Persona-relevant KEY_FACTS slice for R1/R2. Reduces noise and context load."""
    always = {"current_price", "ticker", "sector", "next_earnings_date",
              "eps_release_surprise_pct", "earnings_release_detected"}
    keep = set(focus_fields or []) | always
    clean = {k: v for k, v in (key_facts or {}).items() if v is not None and k in keep}
    return json.dumps(clean, indent=2, default=str)


# ---------------------------------------------------------------------------
# Round 1 — independent stance
# ---------------------------------------------------------------------------

def _persona_prompt(
    persona: Persona,
    ticker: str,
    key_facts: Dict[str, Any],
    section_text: str,
) -> str:
    focus_list = ", ".join(persona.focus_fields) if persona.focus_fields else "(qualitative — no specific fields required)"
    exemplar = _R1_EXEMPLAR.format(ticker=ticker)
    return (
        "IMPORTANT: Respond in English only. Prose only — no bullet lists, no markdown headers, no code fences.\n\n"
        f"PERSONA: {persona.title}\n"
        f"{persona.system_prompt}\n\n"
        f"TICKER: {ticker}\n\n"
        "KEY_FACTS — authoritative numeric ground truth. Field names with `_pct` are already in percent "
        "form (34.2 means 34.2%). CITATION RULE: when you cite any number, quote its KEY_FACTS field "
        "name in parentheses, e.g. '91.39% (eps_release_surprise_pct)'. If you cannot name the source "
        "field, do not state the number:\n"
        f"```json\n{_kf_json_filtered(key_facts, persona.focus_fields)}\n```\n\n"
        f"YOUR FOCUS FIELDS (emphasize these): {focus_list}\n\n"
        "YOUR SECTION FROM THE SEED DOCUMENT (narrative context; if a number here conflicts with "
        "KEY_FACTS, KEY_FACTS wins):\n"
        f"```\n{section_text or '(section not available for this persona)'}\n```\n\n"
        f"Write a 140-170 word analysis of {ticker} from your perspective. "
        "Use EXACTLY these five labeled fields, in order:\n\n"
        "STANCE: bearish | base | bullish (one word)\n"
        "CLAIM: one decisive sentence stating your directional thesis\n"
        "EVIDENCE: 2-3 specific KEY_FACTS field names and their exact values (e.g. 'rsi_14 at 94.0')\n"
        "MECHANISM: 2-3 sentences — the exact transmission chain that produces your predicted outcome\n"
        "WHAT WOULD CHANGE MY MIND: one specific data signal (price level, field value, or named event) "
        "that would invalidate your thesis\n\n"
        f"{_BANNED_PHRASES_RULE}\n\n"
        f"{_FIELD_GLOSSARY}\n\n"
        "Rules: no hedging, no generic disclaimers, no blockquotes, no quotes. Plain prose per field. "
        "This is Round 1 — state only your own perspective, do not reference other analysts.\n\n"
        f"{exemplar}\n"
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
        take = _call_ollama(prompt, timeout=600)
    except Exception as exc:
        logger.warning("Persona %s R1 failed: %s", persona.name, exc)
        take = f"[{persona.title} unavailable — {exc}]"
    logger.info("Persona %s R1 done in %.1fs (%d chars)", persona.name, time.time() - t0, len(take))
    return {"name": persona.name, "title": persona.title, "take": take}


# ---------------------------------------------------------------------------
# Round 2 — debate with required named disagreement
# ---------------------------------------------------------------------------

def _debate_prompt(
    persona: Persona,
    ticker: str,
    key_facts: Dict[str, Any],
    my_r1_take: str,
    others_r1: List[Dict[str, str]],
) -> str:
    others_block = "\n\n".join(
        f"### {t['title']}\n{t['take']}" for t in others_r1
    )
    exemplar = _R2_EXEMPLAR.format(ticker=ticker)

    # Domain constraint — prevents non-TA agents from echo-chambering RSI/ATR
    is_ta = persona.name == "technical_analyst"
    if persona.kind in ("bull", "bear"):
        side = "bullish" if persona.kind == "bull" else "bearish"
        domain_constraint = (
            f"DOMAIN CONSTRAINT: As the {persona.title}, marshal the strongest {side} "
            f"evidence from anywhere in KEY_FACTS — you are not confined to one domain. "
            f"You may acknowledge where the opposing case has genuine merit; honest "
            f"assessment strengthens your credibility, it does not weaken it."
        )
    elif is_ta:
        domain_constraint = (
            f"DOMAIN CONSTRAINT: As {persona.title}, your EVIDENCE must cite price-action, "
            f"momentum, or volatility data. Do not stray into fundamental valuation territory."
        )
    elif persona.focus_fields:
        domain_constraint = (
            f"DOMAIN CONSTRAINT: As {persona.title}, your EVIDENCE must draw from YOUR OWN "
            f"analytical domain — do NOT echo RSI, ATR percentile, or volatility regime as "
            f"primary evidence; those belong to the Technical Analyst. "
            f"Cite data specific to your lens: {', '.join(persona.focus_fields)}."
        )
    else:
        domain_constraint = (
            f"DOMAIN CONSTRAINT: As {persona.title}, your EVIDENCE must be qualitative and "
            f"domain-specific (geopolitical risk, supply chain factors, etc.). "
            f"Do NOT echo RSI or ATR — those belong to the Technical Analyst."
        )

    return (
        "IMPORTANT: Respond in English only. Prose only — no bullet lists, no markdown headers, no code fences.\n\n"
        f"PERSONA: {persona.title}\n"
        f"{persona.system_prompt}\n\n"
        f"TICKER: {ticker}\n\n"
        "KEY_FACTS — authoritative numeric ground truth. Field names with `_pct` are in percent form. "
        "CITATION RULE: when you cite any number, quote its KEY_FACTS field name in parentheses, "
        "e.g. '91.39% (eps_release_surprise_pct)'. If you cannot name the source field, do not state "
        "the number:\n"
        f"```json\n{_kf_json_filtered(key_facts, persona.focus_fields)}\n```\n\n"
        "YOUR ROUND 1 TAKE (defend or update this):\n"
        f"```\n{my_r1_take}\n```\n\n"
        "OTHER ANALYSTS' ROUND 1 TAKES — read these, find at least one you disagree with:\n\n"
        f"{others_block}\n\n"
        f"Write a 160-200 word Round 2 response for {ticker}. "
        "Use EXACTLY these six labeled fields, in order:\n\n"
        "STANCE: bearish | base | bullish  — add '(maintained)' or '(updated from Round 1)'\n"
        "CLAIM: one decisive sentence — your thesis after reviewing the other analysts\n"
        "EVIDENCE: 2-3 specific KEY_FACTS field names and exact values that support your claim\n"
        "MECHANISM: 2-3 sentences — the transmission chain from current conditions to your predicted outcome\n"
        "DISAGREEMENT: name exactly one analyst by role (e.g. 'The Technical Analyst') from the "
        "OTHER ANALYSTS' ROUND 1 TAKES section — you CANNOT disagree with yourself or your own "
        "Round 1 take. Identify the specific claim that analyst made + explain precisely why their "
        "data or logic is wrong, citing at least one KEY_FACTS field\n"
        "WHAT WOULD CHANGE MY MIND: one specific data signal that would force you to revise your stance\n\n"
        f"{domain_constraint}\n\n"
        f"{_BANNED_PHRASES_RULE}\n\n"
        f"{_FIELD_GLOSSARY}\n\n"
        "Rules: DISAGREEMENT is mandatory — name a real analyst from the Round 1 takes above. "
        "Attack a specific claim, not their general stance. No hedging. No generic disclaimers.\n\n"
        f"{exemplar}\n"
    )


def _run_debate(
    persona: Persona,
    ticker: str,
    key_facts: Dict[str, Any],
    my_r1_take: str,
    others_r1: List[Dict[str, str]],
) -> Dict[str, str]:
    prompt = _debate_prompt(persona, ticker, key_facts, my_r1_take, others_r1)
    t0 = time.time()
    try:
        take = _call_ollama(prompt, timeout=720)
    except Exception as exc:
        logger.warning("Persona %s R2 failed: %s", persona.name, exc)
        take = f"[{persona.title} R2 unavailable — {exc}]"
    logger.info("Persona %s R2 done in %.1fs (%d chars)", persona.name, time.time() - t0, len(take))
    return {"name": persona.name, "title": persona.title, "take": take}


# ---------------------------------------------------------------------------
# Round 3 — brief final positions
# ---------------------------------------------------------------------------

def _final_position_prompt(
    persona: Persona,
    ticker: str,
    key_facts: Dict[str, Any],
    my_r1_take: str,
    my_r2_take: str,
    all_r2: List[Dict[str, str]],
) -> str:
    others_r2_block = "\n\n".join(
        f"### {t['title']}\n{t['take']}"
        for t in all_r2 if t["name"] != persona.name
    )

    # Domain anchor — mirrors R2 domain_constraint; prevents pile-on conformance in R3.
    # A persona must hold its domain-grounded view unless a counter-argument cited
    # new evidence from *its own* focus fields. Majority consensus is not a valid shift trigger.
    is_ta = persona.name == "technical_analyst"
    if persona.kind in ("bull", "bear"):
        side = "bull" if persona.kind == "bull" else "bear"
        domain_anchor = (
            f"FINAL-STANCE RULE: As the {persona.title}, you opened by arguing the {side} "
            f"case so it was fully heard. Now vote honestly — state the stance the TOTAL "
            f"weight of evidence supports after three rounds. You MAY concede to the other "
            f"side if its case proved decisively stronger; conceding when the evidence demands "
            f"it is rigor, not weakness. Do not cling to your opening advocacy against the "
            f"evidence.\n"
            f"SHIFTING RULE: Write 'POSITION SHIFTED: yes' if you moved from your Round 1-2 "
            f"stance, and in your WHY name the specific evidence that moved you. Majority "
            f"head-count alone is NOT a reason to shift — only evidence is."
        )
    elif is_ta:
        domain_anchor = (
            f"DOMAIN ANCHOR: As {persona.title}, your final stance must rest on price action, "
            f"momentum, and volatility signals. Do not be swayed by fundamental or macro "
            f"arguments from other analysts — those are outside your domain.\n"
            f"SHIFTING RULE: Write 'POSITION SHIFTED: yes' ONLY if a Round 2 argument "
            f"directly contradicted your specific technical signals with price-action data "
            f"you had not considered. Majority consensus is NOT grounds for shifting."
        )
    elif persona.focus_fields:
        focus_list = ", ".join(persona.focus_fields)
        domain_anchor = (
            f"DOMAIN ANCHOR: As {persona.title}, your final stance must be grounded in your "
            f"own analytical domain — {focus_list}. Do NOT capitulate to RSI, ATR, or "
            f"volatility-regime arguments; those belong to the Technical Analyst.\n"
            f"SHIFTING RULE: Write 'POSITION SHIFTED: yes' ONLY if a Round 2 argument cited "
            f"new evidence from YOUR domain fields above that directly refutes your specific "
            f"R1-R2 position. Majority consensus pressure is NOT a valid reason to shift — "
            f"you are an independent expert who holds a domain-grounded view. If you shift, "
            f"your WHY must name the specific field and value that changed your mind."
        )
    else:
        domain_anchor = (
            f"DOMAIN ANCHOR: As {persona.title}, your final stance must be grounded in your "
            f"qualitative domain expertise (geopolitical risk, supply chain, structural factors).\n"
            f"SHIFTING RULE: Write 'POSITION SHIFTED: yes' ONLY if a Round 2 argument "
            f"introduced concrete structural evidence that directly refutes your specific claims. "
            f"Majority consensus alone is NOT grounds for shifting."
        )

    return (
        "IMPORTANT: Respond in English only. Prose only — no bullet lists, no markdown headers.\n\n"
        f"PERSONA: {persona.title}\n"
        f"{persona.system_prompt}\n\n"
        f"TICKER: {ticker}\n\n"
        "KEY_FACTS — authoritative numeric ground truth. CITATION RULE: when you cite any number, "
        "quote its KEY_FACTS field name in parentheses, e.g. '91.39% (eps_release_surprise_pct)'. "
        "If you cannot name the source field, do not state the number:\n"
        f"```json\n{_kf_json(key_facts)}\n```\n\n"
        f"YOUR ROUND 1:\n{my_r1_take}\n\n"
        f"YOUR ROUND 2:\n{my_r2_take}\n\n"
        f"{domain_anchor}\n\n"
        f"OTHER ANALYSTS' ROUND 2 RESPONSES:\n\n{others_r2_block}\n\n"
        "Write your final 60-80 word position statement. "
        "Use EXACTLY these four fields:\n\n"
        "FINAL STANCE: [write exactly one word — bear, base, or bull — nothing else]\n"
        "RATIONALE: one sentence — the single strongest reason for your final stance\n"
        "POSITION SHIFTED: [write exactly one word — yes or no]\n"
        "WHY: one sentence — what specifically changed your mind (if shifted) or what reinforced you (if not)\n\n"
        f"{_BANNED_PHRASES_RULE}\n\n"
        f"{_FIELD_GLOSSARY}\n\n"
        "No hedging. 60-80 words total across all four fields.\n"
    )


def _run_final_position(
    persona: Persona,
    ticker: str,
    key_facts: Dict[str, Any],
    my_r1_take: str,
    my_r2_take: str,
    all_r2: List[Dict[str, str]],
) -> Dict[str, str]:
    prompt = _final_position_prompt(persona, ticker, key_facts, my_r1_take, my_r2_take, all_r2)
    t0 = time.time()
    try:
        take = _call_ollama(prompt, timeout=600)
    except Exception as exc:
        logger.warning("Persona %s R3 failed: %s", persona.name, exc)
        take = f"[{persona.title} R3 unavailable — {exc}]"
    logger.info("Persona %s R3 done in %.1fs (%d chars)", persona.name, time.time() - t0, len(take))
    return {"name": persona.name, "title": persona.title, "take": take}


# ---------------------------------------------------------------------------
# Two-pass synthesis
# Pass 1: Distill debate → structured JSON
# Pass 2: Chief Analyst writes narrative research note from JSON + KEY_FACTS
# ---------------------------------------------------------------------------

def _distill_prompt(
    ticker: str,
    key_facts: Dict[str, Any],
    takes_by_round: Dict[int, List[Dict[str, str]]],
) -> str:
    def _fmt(takes: List[Dict[str, str]]) -> str:
        return "\n\n".join(f"[{t['title']}] {t['take']}" for t in takes)

    r1 = _fmt(takes_by_round.get(1, []))
    r2 = _fmt(takes_by_round.get(2, []))
    r3 = _fmt(takes_by_round.get(3, []))
    n_analysts = len(takes_by_round.get(3) or takes_by_round.get(1) or [])

    return (
        "IMPORTANT: Respond ONLY with valid JSON. No preamble, no markdown fences, no commentary.\n\n"
        "KEY_FACTS — authoritative numeric ground truth. When extracting evidence strings, use "
        "EXACT values from this block:\n"
        f"```json\n{_kf_json(key_facts)}\n```\n\n"
        f"You have just reviewed a three-round analyst council deliberation on {ticker}. "
        "Extract the following into a single JSON object with these exact keys:\n\n"
        '{\n'
        '  "consensus_stance": "bearish" | "base" | "bullish",\n'
        '  "vote_distribution": {"bearish": N, "base": N, "bullish": N},\n'
        f'  "_vote_instructions": "Count one vote per analyst from their FINAL STANCE in Round 3 only. bear=bearish, bull=bullish, base=base. Sum must equal the number of analysts ({n_analysts}). Do not use Round 1 or Round 2 stances.",\n'
        '  "crux_disagreement": "one sentence — the specific claim the council never resolved",\n'
        '  "strongest_bull": {"analyst": "EXACT role title from the deliberation (e.g. \'Bull Analyst\', \'Growth Analyst\')", "claim": "exact claim", "evidence": "cited data fields and values"},\n'
        '  "strongest_bear": {"analyst": "EXACT role title from the deliberation (e.g. \'Bear Analyst\', \'Valuation Analyst\')", "claim": "exact claim", "evidence": "cited data fields and values"},\n'
        '  "position_shifts": [{"analyst": "EXACT role title", "from_stance": "...", "to_stance": "...", "reason": "..."}],\n'
        '  "open_question": "one sentence — the specific data that would break the consensus",\n'
        '  "key_risks": ["risk 1", "risk 2", "risk 3"]\n'
        '}\n\n'
        f"ROUND 1 — INDEPENDENT STANCES:\n{r1}\n\n"
        f"ROUND 2 — DEBATE:\n{r2}\n\n"
        f"ROUND 3 — FINAL POSITIONS:\n{r3}\n\n"
        "Output ONLY the JSON object. No other text."
    )


_REC_BY_STANCE = {"bearish": "UNDERWEIGHT", "base": "NEUTRAL", "bullish": "OVERWEIGHT"}

# Tolerate markdown/punctuation between the label and the verdict — advocate
# personas sometimes emit "**FINAL STANCE:** bull", and a plain \s* would not
# cross the asterisks, silently dropping that analyst's vote from the tally.
_FINAL_STANCE_RE = re.compile(
    r'final\s+stance[\s*_:]*(bear(?:ish)?|base|bull(?:ish)?)', re.IGNORECASE
)


def _count_final_votes(r3_takes: List[Dict[str, Any]]) -> Dict[str, int]:
    """Tally R3 FINAL STANCE verdicts into {bearish, base, bullish} counts."""
    votes: Dict[str, int] = {"bearish": 0, "base": 0, "bullish": 0}
    for t in r3_takes:
        m = _FINAL_STANCE_RE.search(t.get("take", ""))
        if m:
            s = m.group(1).lower()
            key = "bearish" if s.startswith("bear") else "bullish" if s.startswith("bull") else "base"
            votes[key] += 1
    return votes


def _chief_analyst_prompt(
    ticker: str,
    key_facts: Dict[str, Any],
    distilled: Dict[str, Any],
) -> str:
    # The Round-3 vote (Python-computed in run_council) fixes the headline call so
    # the memo can never recommend a direction the council did not reach.
    _cs = str((distilled or {}).get("consensus_stance") or "").strip().lower()
    _vd = (distilled or {}).get("vote_distribution") or {}
    _n_bear = int(_vd.get("bearish", 0) or 0)
    _n_base = int(_vd.get("base", 0) or 0)
    _n_bull = int(_vd.get("bullish", 0) or 0)
    required_rec = _REC_BY_STANCE.get(_cs, "NEUTRAL")
    return (
        "IMPORTANT: Your entire response must be written in English only.\n\n"
        f"You are a senior research analyst at a top-tier institutional equity research firm. "
        f"Your council has just completed a three-round deliberation on {ticker}. "
        "Write the investment memo that will be delivered to the portfolio manager. "
        "This is NOT a recap of who argued what — it is your authoritative analysis of the stock, "
        "informed by the deliberation but written in your own voice.\n\n"
        "TONE: Write as a senior analyst to a sophisticated PM. Conversational professional. "
        "Narrative paragraphs throughout — no bullet lists except in sections 6 and 7. "
        "Take a clear position. A memo that hedges in every direction is a failed memo. "
        "If the evidence is mixed, say which side weighs more and why.\n\n"
        "KEY_FACTS — AUTHORITATIVE NUMERIC GROUND TRUTH. Use EXACT values anywhere you cite a number. "
        "CITATION RULE: every number you state must be followed by its KEY_FACTS field name in "
        "parentheses — e.g. '68.48% (eps_release_surprise_pct)'. If you cannot name the source field, "
        "do not state the number.\n"
        f"```json\n{_kf_json(key_facts)}\n```\n\n"
        "RESEARCH TEAM FINDINGS (distilled from the council deliberation):\n"
        f"```json\n{json.dumps(distilled, indent=2)}\n```\n\n"
        f"{_BANNED_PHRASES_RULE}\n\n"
        f"{_SYNTHESIS_QUALITY_STANDARD}\n\n"
        "Write exactly these seven sections in order. Start immediately with ## Investment Thesis. "
        "No preamble. No sign-off.\n\n"
        "## Investment Thesis\n"
        f"The council's Round-3 vote was {_n_bear} bearish / {_n_base} base / {_n_bull} bullish "
        f"(computed consensus: {_cs or 'mixed'}). Your headline call is FIXED by this vote — "
        "bearish→UNDERWEIGHT, base→NEUTRAL, bullish→OVERWEIGHT — so for this council the required "
        f"call is {required_rec}. "
        f"Write one paragraph (4-6 sentences) stating {ticker} as {required_rec} with a conviction "
        "level (high / moderate / cautious) and a time horizon (3–6 months / 6–12 months / 12+ months), "
        "and name the single most important reason. "
        "You MUST NOT recommend a direction that contradicts the vote above, and you must NEVER claim "
        "your view 'aligns with the consensus' unless your recommendation actually matches it. The Bull "
        "and Bear sections may explore both sides, but the headline call stays fixed by the vote.\n\n"
        "## Where This Stands Today\n"
        f"One to two paragraphs. Set the scene: where {ticker} is trading now, what the valuation "
        "picture looks like relative to its own history and peers, and what has happened recently "
        "(earnings release, guidance, significant price move) that makes this analysis timely. "
        "Tie every number to a KEY_FACTS field. This is context, not opinion — save the argument for "
        "the bull and bear sections.\n\n"
        "## The Bull Case\n"
        "Two to three paragraphs of narrative. Weave together the strongest pro-ownership argument. "
        "Draw on the council's RESEARCH TEAM FINDINGS (cite the analyst by their EXACT role title — "
        "never invent a human name). Cite KEY_FACTS evidence and explain the causal mechanism that "
        "produces upside. End this section with one sentence: what must be true for this case to play out.\n\n"
        "## The Bear Case\n"
        "Two to three paragraphs of narrative. Present the strongest argument against owning the stock. "
        "Cite the analyst by their EXACT role title. Cite KEY_FACTS evidence, explain the downside "
        "mechanism. End with: what structural risk specific to this business model do the quantitative "
        f"models underweight? (BANNED generic categories: 'Competition', 'Economic Slowdown', "
        "'Interest Rates', 'Market Correction', 'Geopolitical'. Name something concrete to {ticker}.)\n\n"
        "## What Tilts the Decision\n"
        "One to two paragraphs. This is the synthesis — which side wins on the current evidence and why. "
        "Acknowledge the strongest counter-argument and explain why it does not override your view. "
        "This section is what separates a memo from a debate transcript. You must land on a side.\n\n"
        "## Catalysts to Watch (Next 60–90 Days)\n"
        "Three to five specific, named events or data releases. For each, one line: what it is, "
        "which scenario (bull / bear / base) it accelerates if it breaks the stated direction, "
        "and the approximate magnitude (e.g. +3-5% / -8-12%). "
        "ONLY cite dates in KEY_FACTS (next_earnings_date, days_to_earnings). "
        "For other catalysts, name the quarter or fiscal period only — do NOT invent calendar dates.\n\n"
        "## What Would Change This View\n"
        "Two numbered items. One that forces an upgrade; one that forces a downgrade. "
        "Each must be a concrete, measurable condition — a price level, a KEY_FACTS field crossing a "
        "threshold, or a fundamental data point. No vague conditions. "
        "Close with one sentence on position sizing given the current volatility regime "
        "(volatility_regime).\n\n"
        f"{_FIELD_GLOSSARY}\n\n"
        "Rules: KEY_FACTS numbers override any conflicting number. No blockquotes. "
        "No mention of the internal council deliberation format, swarm mechanics, or ontology processing. "
        "English only. NEVER invent analyst names, product version numbers, event dates, or any "
        "specifics not present in KEY_FACTS or RESEARCH TEAM FINDINGS. "
        "Start with ## Investment Thesis.\n"
    )


# Grounding citations are required during generation (so the model only states numbers
# it can source) but read as debug noise in the delivered memo. The model emits them in
# two styles: pure "(current_price)" and labelled "(debt_to_equity: 79.55)". Strip the
# field labels for display (keeping any value), and decode leaked unicode escapes.
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
# Generic source tag the model sometimes appends: "(KEY_FACTS)" -> remove.
_CITE_KEYFACTS_RE = re.compile(r"\s*\(KEY_FACTS\)")
# Pure grounding token: "(current_price)" / "(vix)" -> remove (with leading space).
_CITE_FIELD_RE = re.compile(r"\s*\((?:[a-z0-9]+(?:_[a-z0-9]+)+|vix)\)")
# Labelled citation, key may be snake_case OR human words:
# "(debt_to_equity: 79.55)" / "(volatility regime: ELEVATED…)" -> keep the value.
_CITE_KV_RE = re.compile(r"\(([a-z][a-z0-9_]*(?: [a-z0-9_]+)*):\s*([^()]*?)\)")
# Month-name date used for the earnings catalyst, e.g. "May 30, 2026".
_PROSE_DATE = r"[A-Z][a-z]+ \d{1,2},? \d{4}"


def _clean_memo(text: str) -> str:
    if not text:
        return text
    text = _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text)
    text = _CITE_KEYFACTS_RE.sub("", text)
    text = _CITE_FIELD_RE.sub("", text)                          # pure tokens (incl. inner of nested)
    text = _CITE_KV_RE.sub(lambda m: f"({m.group(2).strip()})" if m.group(2).strip() else "", text)
    text = _CITE_FIELD_RE.sub("", text)                          # any leftover pure tokens
    return text


def _fix_earnings_date(text: str, key_facts: Dict[str, Any]) -> str:
    """Force the earnings date in the memo to match the validated KEY_FACTS value.

    next_earnings_date is guaranteed >= today by _get_earnings_info, so this corrects
    the LLM occasionally hallucinating the month (e.g. writing 'May 30' when the data
    and days-count point to 'July 30') and never lets a past date be cited as a future
    catalyst. Only touches dates in explicit earnings contexts; other dates are left alone.
    """
    if not text:
        return text
    iso = str((key_facts or {}).get("next_earnings_date") or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso)
    if not m:
        return text
    import datetime as _dt
    try:
        d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        return text
    human = f"{d.strftime('%B')} {d.day}, {d.year}"
    text = re.sub(r"(?i)(earnings date is\s+)" + _PROSE_DATE, r"\1" + human, text)
    text = re.sub(r"(?i)(Earnings Release\s*\(\s*)" + _PROSE_DATE + r"(\s*\))", r"\1" + human + r"\2", text)
    return text


# ---------------------------------------------------------------------------
# Council entry point
# ---------------------------------------------------------------------------

def run_council(
    ticker: str,
    seed_text: str,
    key_facts: Dict[str, Any],
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Any]:
    """Run the 7-persona council through 3 deliberation rounds + synthesis.

    progress_cb(percent, label) is called before each Ollama call so the
    cancel signal in deep_analysis_worker is checked between every call.
    percent is 0-100 scaled across the entire council portion.

    Returns:
        {
          "takes":          R1 takes list (backwards-compat),
          "takes_by_round": {1: [...], 2: [...], 3: [...]},
          "enhanced_markdown": synthesized 6-section report,
          "raw_markdown":   full R1+R2+R3 transcript, role-grouped,
        }
    """
    # For funds/ETFs, swap the earnings_catalyst persona (earnings are
    # meaningless for a basket) for the fund-structure analyst.
    personas = list(PERSONAS)
    if key_facts.get("is_fund"):
        personas = [
            FUND_STRUCTURE_PERSONA if p.name == "earnings_catalyst" else p
            for p in personas
        ]
    n = len(personas)

    def _cb(pct: int, label: str) -> None:
        if progress_cb:
            progress_cb(pct, label)

    # Round 1 — independent stances (progress 0 → 35%)
    takes_r1: List[Dict[str, str]] = []
    for idx, persona in enumerate(personas):
        _cb(int(idx / n * 35), f"R1: {persona.title}")
        takes_r1.append(_run_persona(persona, ticker, key_facts, seed_text))

    # Round 2 — named-disagreement debate (progress 35 → 65%)
    takes_r2: List[Dict[str, str]] = []
    for idx, persona in enumerate(personas):
        _cb(35 + int(idx / n * 30), f"R2: {persona.title}")
        my_r1  = next(t for t in takes_r1 if t["name"] == persona.name)
        others = [t for t in takes_r1  if t["name"] != persona.name]
        takes_r2.append(_run_debate(persona, ticker, key_facts, my_r1["take"], others))

    # Round 3 — brief final positions (progress 65 → 80%)
    takes_r3: List[Dict[str, str]] = []
    for idx, persona in enumerate(personas):
        _cb(65 + int(idx / n * 15), f"R3: {persona.title}")
        my_r1 = next(t for t in takes_r1 if t["name"] == persona.name)
        my_r2 = next(t for t in takes_r2 if t["name"] == persona.name)
        takes_r3.append(_run_final_position(persona, ticker, key_facts, my_r1["take"], my_r2["take"], takes_r2))

    takes_by_round = {1: takes_r1, 2: takes_r2, 3: takes_r3}

    # Pass 1 — Distill debate to structured JSON (progress 80 → 88%)
    _cb(80, "distill")
    distill_p = _distill_prompt(ticker, key_facts, takes_by_round)
    t0 = time.time()
    try:
        distilled_raw = _call_ollama(distill_p, timeout=480)
    except Exception as exc:
        print(f"[council] Distill Ollama call failed for {ticker}: {exc}", flush=True)
        logger.error("Distill pass failed: %s", exc)
        distilled_raw = "{}"
    try:
        import re as _re
        # Strip markdown fences (qwen often wraps JSON in ```json ... ```)
        _stripped = _re.sub(r'^```[a-z]*\s*', '', distilled_raw.strip())
        _stripped = _re.sub(r'\s*```$', '', _stripped.strip())
        _m = _re.search(r'\{[\s\S]*\}', _stripped)
        distilled: Dict[str, Any] = json.loads(_m.group()) if _m else {}
        if not distilled:
            print(f"[council] Distill JSON empty for {ticker}. Raw[:300]: {distilled_raw[:300]}", flush=True)
        else:
            print(f"[council] Distill OK for {ticker}: consensus={distilled.get('consensus_stance')} votes={distilled.get('vote_distribution')}", flush=True)
    except Exception as exc:
        print(f"[council] Distill JSON parse failed for {ticker}: {exc}. Raw[:300]: {distilled_raw[:300]}", flush=True)
        logger.error("Distill JSON parse failed for %s: %s", ticker, exc)
        distilled = {}
    logger.info("Distill done in %.1fs", time.time() - t0)

    # Override LLM vote count with Python-computed values from R3 FINAL STANCE fields
    r3_takes = takes_by_round.get(3, [])
    if r3_takes:
        _votes = _count_final_votes(r3_takes)
        _consensus = max(_votes, key=_votes.get)
        if distilled is None:
            distilled = {}
        distilled["vote_distribution"] = _votes
        distilled["consensus_stance"] = _consensus
        print(f"[council] Python vote count for {ticker}: {_votes} → consensus={_consensus}", flush=True)

    # Pass 2 — Chief Analyst research note (progress 88 → 100%)
    _cb(88, "chief_analyst")
    chief_p = _chief_analyst_prompt(ticker, key_facts, distilled)
    t0 = time.time()
    try:
        enhanced = _call_ollama(chief_p, timeout=600, mode="synthesis")
    except Exception as exc:
        logger.error("Chief analyst pass failed: %s", exc)
        enhanced = ""
    logger.info("Chief analyst done in %.1fs (%d chars)", time.time() - t0, len(enhanced))

    if not enhanced:
        enhanced = "\n\n".join(
            f"## {t['title']}\n\n{t['take']}" for t in takes_r3
        )
        logger.warning("Chief analyst pass empty for %s; falling back to R3 takes", ticker)

    enhanced = _fix_earnings_date(_clean_memo(enhanced), key_facts)

    _cb(100, "complete")

    raw = "\n\n".join(
        f"## {p.title}\n\n"
        f"**Round 1**\n\n{next(t for t in takes_r1 if t['name'] == p.name)['take']}\n\n"
        f"**Round 2**\n\n{next(t for t in takes_r2 if t['name'] == p.name)['take']}\n\n"
        f"**Round 3**\n\n{next(t for t in takes_r3 if t['name'] == p.name)['take']}"
        for p in personas
    )

    return {
        "takes":          takes_r1,  # backwards-compat for any caller reading only R1
        "takes_by_round": takes_by_round,
        "enhanced_markdown": enhanced,
        "raw_markdown":   raw,
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
    print(f"R1: {len(result['takes_by_round'][1])} takes | "
          f"R2: {len(result['takes_by_round'][2])} takes | "
          f"R3: {len(result['takes_by_round'][3])} takes | "
          f"enhanced: {len(result['enhanced_markdown'])} chars")
