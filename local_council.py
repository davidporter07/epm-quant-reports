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

Runtime on qwen2.5:14b: ~20-25 min (22 Ollama calls).
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
    name: str
    title: str
    section_header: str
    system_prompt: str
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
DISAGREEMENT: I disagree with the Growth Investor's argument that Services growth makes valuation risk secondary. Services are not independent from hardware. A simple "Services are big, buy the dip" argument ignores that Services revenue per user must rise fast enough to fully offset slower device volume — and the data does not yet confirm that rate.
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

def _call_ollama(prompt: str, timeout: int = 240) -> str:
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("response", "").strip()


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
        "form (34.2 means 34.2%). Use these EXACT values verbatim. Do NOT round, re-derive, or invent "
        "numbers not present here:\n"
        f"```json\n{_kf_json(key_facts)}\n```\n\n"
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
        take = _call_ollama(prompt, timeout=240)
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
    return (
        "IMPORTANT: Respond in English only. Prose only — no bullet lists, no markdown headers, no code fences.\n\n"
        f"PERSONA: {persona.title}\n"
        f"{persona.system_prompt}\n\n"
        f"TICKER: {ticker}\n\n"
        "KEY_FACTS — authoritative numeric ground truth. Field names with `_pct` are in percent form. "
        "Use EXACT values. Do NOT invent numbers:\n"
        f"```json\n{_kf_json(key_facts)}\n```\n\n"
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
        "DISAGREEMENT: name exactly one analyst by role (e.g. 'The Technical Analyst') + "
        "identify the specific claim they made + explain precisely why their data or logic is wrong, "
        "citing at least one KEY_FACTS field\n"
        "WHAT WOULD CHANGE MY MIND: one specific data signal that would force you to revise your stance\n\n"
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
        take = _call_ollama(prompt, timeout=300)
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
    return (
        "IMPORTANT: Respond in English only. Prose only — no bullet lists, no markdown headers.\n\n"
        f"PERSONA: {persona.title}\n"
        f"{persona.system_prompt}\n\n"
        f"TICKER: {ticker}\n\n"
        f"YOUR ROUND 1:\n{my_r1_take}\n\n"
        f"YOUR ROUND 2:\n{my_r2_take}\n\n"
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
        take = _call_ollama(prompt, timeout=180)
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

    return (
        "IMPORTANT: Respond ONLY with valid JSON. No preamble, no markdown fences, no commentary.\n\n"
        f"You have just reviewed a three-round analyst council deliberation on {ticker}. "
        "Extract the following into a single JSON object with these exact keys:\n\n"
        '{\n'
        '  "consensus_stance": "bearish" | "base" | "bullish",\n'
        '  "vote_distribution": {"bearish": N, "base": N, "bullish": N},\n'
        '  "_vote_instructions": "Count one vote per analyst from their FINAL STANCE in Round 3 only. bear=bearish, bull=bullish, base=base. Sum must equal the number of analysts (7). Do not use Round 1 or Round 2 stances.",\n'
        '  "crux_disagreement": "one sentence — the specific claim the council never resolved",\n'
        '  "strongest_bull": {"analyst": "EXACT role title from the deliberation (e.g. \'Earnings Catalyst Analyst\', \'Growth Investor\')", "claim": "exact claim", "evidence": "cited data fields and values"},\n'
        '  "strongest_bear": {"analyst": "EXACT role title from the deliberation (e.g. \'Technical Analyst\', \'Value Investor\')", "claim": "exact claim", "evidence": "cited data fields and values"},\n'
        '  "position_shifts": [{"analyst": "EXACT role title", "from_stance": "...", "to_stance": "...", "reason": "..."}],\n'
        '  "open_question": "one sentence — the specific data that would break the consensus",\n'
        '  "key_risks": ["risk 1", "risk 2", "risk 3"]\n'
        '}\n\n'
        f"ROUND 1 — INDEPENDENT STANCES:\n{r1}\n\n"
        f"ROUND 2 — DEBATE:\n{r2}\n\n"
        f"ROUND 3 — FINAL POSITIONS:\n{r3}\n\n"
        "Output ONLY the JSON object. No other text."
    )


def _chief_analyst_prompt(
    ticker: str,
    key_facts: Dict[str, Any],
    distilled: Dict[str, Any],
) -> str:
    return (
        "IMPORTANT: Your entire response must be written in English only.\n\n"
        f"You are the Chief Analyst at a top-tier institutional equity research firm. "
        f"Your research team has completed a three-round deliberation on {ticker}. "
        "Write the final research note that a portfolio manager will use to make a position decision. "
        "This is NOT a summary of the debate — it is your own authoritative call informed by the deliberation.\n\n"
        "KEY_FACTS — AUTHORITATIVE NUMERIC GROUND TRUTH. Use these EXACT values anywhere you cite a number:\n"
        f"```json\n{_kf_json(key_facts)}\n```\n\n"
        "RESEARCH TEAM FINDINGS (distilled from the council deliberation):\n"
        f"```json\n{json.dumps(distilled, indent=2)}\n```\n\n"
        f"{_BANNED_PHRASES_RULE}\n\n"
        f"{_SYNTHESIS_QUALITY_STANDARD}\n\n"
        "Write exactly these six sections in order. Start immediately with ## Verdict. No preamble.\n\n"
        "## Verdict\n"
        f"One sentence: your rating (OVERWEIGHT / UNDERWEIGHT / NEUTRAL), 12-month price target range, "
        "and the single most important reason. Then one paragraph (3-4 sentences) investment thesis. "
        "You MUST acknowledge the council's `consensus_stance` and `vote_distribution` from RESEARCH TEAM FINDINGS. "
        "If your rating diverges from the consensus (e.g., OVERWEIGHT when consensus_stance is bearish with 5+ votes), "
        "you MUST explicitly name the specific insight the majority missed that justifies your contrarian call. "
        "If you cannot name a concrete, data-backed reason, align with the council consensus.\n\n"
        "## Bull Case\n"
        "The strongest argument for owning this stock. Attribute it to the analyst by their EXACT role title "
        "from RESEARCH TEAM FINDINGS (e.g. 'Earnings Catalyst Analyst', 'Growth Investor') — NEVER invent "
        "a human name. Cite the specific KEY_FACTS evidence, explain the mechanism that produces upside. "
        "End with: what must be TRUE for this case to play out.\n\n"
        "## Bear Case\n"
        "The strongest argument against this stock. Attribute it to the analyst by their EXACT role title "
        "from RESEARCH TEAM FINDINGS (e.g. 'Technical Analyst', 'Value Investor') — NEVER invent a human "
        "name. Cite the specific KEY_FACTS evidence, explain the mechanism that produces downside. "
        "End with: what must be TRUE for this case to play out.\n\n"
        "## Key Catalysts\n"
        "Three specific catalysts in order of time. For each: what it is, which scenario it "
        "accelerates (bull/bear/base), and by how much. "
        "ONLY cite dates present in KEY_FACTS (e.g. `next_earnings_date`, `days_to_earnings`). "
        "For any other catalyst, name the quarter or fiscal period only — do NOT invent specific "
        "calendar dates not in KEY_FACTS.\n\n"
        "## Primary Risks\n"
        f"Three risks specific to {ticker}'s business model that the quantitative models miss. "
        "For each: the risk, its trigger mechanism, and the earliest-warning signal to watch. "
        "BANNED generic risk categories — do not use any of these: 'Supply Chain Disruptions', "
        "'Competition', 'Economic Slowdown', 'Interest Rates', 'Market Correction', 'Geopolitical'. "
        "Each risk MUST cite a specific KEY_FACTS field as its early-warning signal "
        f"(e.g. eps_beat_rate_pct, pead_signal, rel_perf_1m_stock_pct). "
        f"Think about what is structurally unique to {ticker}'s revenue model, margin structure, "
        "or customer base that Wall Street consensus tends to underweight.\n\n"
        "## What Changes My View\n"
        "Two concrete, measurable conditions: one that forces an upgrade, one that forces a downgrade. "
        "Cite specific price levels, KEY_FACTS fields, or fundamental thresholds — not vague conditions. "
        "Close with one sentence on position sizing given the current `volatility_regime`.\n\n"
        f"{_FIELD_GLOSSARY}\n\n"
        "Rules: KEY_FACTS numbers override any conflicting number. No blockquotes. "
        "No mention of MiroFish, swarm, ontology, or panorama_search. English only. "
        "Do NOT re-summarize the debate — make your own call and defend it. "
        "NEVER invent analyst names, product version numbers, event dates, or any specifics not present "
        "in KEY_FACTS or RESEARCH TEAM FINDINGS. Start with ## Verdict.\n"
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
    n = len(PERSONAS)

    def _cb(pct: int, label: str) -> None:
        if progress_cb:
            progress_cb(pct, label)

    # Round 1 — independent stances (progress 0 → 35%)
    takes_r1: List[Dict[str, str]] = []
    for idx, persona in enumerate(PERSONAS):
        _cb(int(idx / n * 35), f"R1: {persona.title}")
        takes_r1.append(_run_persona(persona, ticker, key_facts, seed_text))

    # Round 2 — named-disagreement debate (progress 35 → 65%)
    takes_r2: List[Dict[str, str]] = []
    for idx, persona in enumerate(PERSONAS):
        _cb(35 + int(idx / n * 30), f"R2: {persona.title}")
        my_r1  = next(t for t in takes_r1 if t["name"] == persona.name)
        others = [t for t in takes_r1  if t["name"] != persona.name]
        takes_r2.append(_run_debate(persona, ticker, key_facts, my_r1["take"], others))

    # Round 3 — brief final positions (progress 65 → 80%)
    takes_r3: List[Dict[str, str]] = []
    for idx, persona in enumerate(PERSONAS):
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
        distilled_raw = _call_ollama(distill_p, timeout=180)
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
    import re as _re2
    r3_takes = takes_by_round.get(3, [])
    if r3_takes:
        _votes: Dict[str, int] = {"bearish": 0, "base": 0, "bullish": 0}
        for t in r3_takes:
            m = _re2.search(r'final\s+stance:\s*(bear(?:ish)?|base|bull(?:ish)?)', t["take"], _re2.IGNORECASE)
            if m:
                s = m.group(1).lower()
                key = "bearish" if s.startswith("bear") else "bullish" if s.startswith("bull") else "base"
                _votes[key] += 1
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
        enhanced = _call_ollama(chief_p, timeout=420)
    except Exception as exc:
        logger.error("Chief analyst pass failed: %s", exc)
        enhanced = ""
    logger.info("Chief analyst done in %.1fs (%d chars)", time.time() - t0, len(enhanced))

    if not enhanced:
        enhanced = "\n\n".join(
            f"## {t['title']}\n\n{t['take']}" for t in takes_r3
        )
        logger.warning("Chief analyst pass empty for %s; falling back to R3 takes", ticker)

    _cb(100, "complete")

    raw = "\n\n".join(
        f"## {p.title}\n\n"
        f"**Round 1**\n\n{next(t for t in takes_r1 if t['name'] == p.name)['take']}\n\n"
        f"**Round 2**\n\n{next(t for t in takes_r2 if t['name'] == p.name)['take']}\n\n"
        f"**Round 3**\n\n{next(t for t in takes_r3 if t['name'] == p.name)['take']}"
        for p in PERSONAS
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
