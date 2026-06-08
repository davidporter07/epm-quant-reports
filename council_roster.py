"""
council_roster.py — Selectable & customizable analyst-council roster.

The Council Builder UI lets a user assemble a council from a library of ~19
analysts before running a deep analysis: pick members, tweak each one's
personality via trait dropdowns, or write a fully custom personality. This
module is the single source of truth for that library and for turning a
user-submitted roster spec into engine-ready `Persona` objects.

Design notes:
  - The engine (`local_council.run_council`) is decoupled — it just takes a
    `personas` list. This module imports FROM local_council, never the reverse.
  - The 8 default personas remain canonical in `local_council.PERSONAS`; here
    they are enriched with display labels only (system_prompt/focus_fields/kind
    are untouched), so the default roster reproduces today's council exactly.
  - Directional advocacy lives ONLY in `Persona.kind` (bull/bear). Trait
    dropdowns never impose a bull/bear lean on neutral analysts — that would
    re-introduce the herding the 4-round redesign removed.

Roster spec shape (what the API/UI submit):
    [{"id": "valuation_analyst",
      "traits": {"conviction": "Cautious", "school": "Value"},
      "custom_text": "Graham-style, demands a margin of safety…"}, ...]
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from local_council import PERSONAS, FUND_STRUCTURE_PERSONA, Persona

# ---------------------------------------------------------------------------
# Display metadata for the 8 default personas (engine fields stay in local_council)
# ---------------------------------------------------------------------------

_DEFAULT_DISPLAY: Dict[str, Dict[str, str]] = {
    "technical_analyst": {
        "blurb": "Reads price action, momentum, and volatility — ignores the story, trusts the tape.",
        "style_label": "Technical / price action", "econ_label": "Agnostic", "lens_label": "Charts & momentum",
    },
    "growth_analyst": {
        "blurb": "Judges whether the growth rate earns the multiple — revenue, earnings, margins, ROE.",
        "style_label": "Growth at a reasonable price", "econ_label": "Pro-innovation", "lens_label": "Growth quality",
    },
    "valuation_analyst": {
        "blurb": "Hunts for margin of safety; flags over- and under-valuation alike on P/E, EV/EBITDA, P/B.",
        "style_label": "Valuation discipline", "econ_label": "Mean-reversion", "lens_label": "Fundamental value",
    },
    "macro_strategist": {
        "blurb": "Frames the stock inside the rate regime, VIX, and index trend — top-down overlay.",
        "style_label": "Top-down macro", "econ_label": "Rates & liquidity driven", "lens_label": "Macro regime",
    },
    "operations_analyst": {
        "blurb": "Weighs manufacturing footprint, sourcing, and geopolitics — resilience AND risk.",
        "style_label": "Operational / structural", "econ_label": "Supply-chain realist", "lens_label": "Operations & supply chain",
    },
    "bull_analyst": {
        "blurb": "Opens by building the strongest evidence-based case for upside — then votes honestly.",
        "style_label": "Upside advocate", "econ_label": "Constructive", "lens_label": "Bull case",
    },
    "bear_analyst": {
        "blurb": "Opens by building the strongest evidence-based case for downside — then votes honestly.",
        "style_label": "Downside advocate", "econ_label": "Skeptical", "lens_label": "Bear case",
    },
    "earnings_catalyst": {
        "blurb": "Tracks the next print, beat rate, and post-earnings drift — catalyst timing.",
        "style_label": "Event / earnings driven", "econ_label": "Catalyst-focused", "lens_label": "Earnings catalysts",
    },
}


def _enrich_default(p: Persona) -> Persona:
    meta = _DEFAULT_DISPLAY.get(p.name, {})
    return dataclasses.replace(
        p,
        blurb=meta.get("blurb", ""),
        style_label=meta.get("style_label", ""),
        econ_label=meta.get("econ_label", ""),
        lens_label=meta.get("lens_label", ""),
    )


# ---------------------------------------------------------------------------
# Additional library personas (~11) — chosen from KEY_FACTS fields that exist
# ---------------------------------------------------------------------------

_EXTRA_PERSONAS: List[Persona] = [
    Persona(
        name="quant_analyst",
        title="Quantitative Analyst",
        section_header="QUANTITATIVE PERSPECTIVE",
        system_prompt=(
            "You are a quantitative analyst. You reason over the EPM model ensemble, the Kronos "
            "scenario targets, factor signals, and analyst-recommendation scores — statistics over "
            "narrative. Treat the ensemble spread as a distribution, not a point estimate. Reach "
            "your own conclusion objectively in either direction. Every claim must cite a specific "
            "number from KEY_FACTS or the seed."
        ),
        focus_fields=[
            "epm_ensemble_implied_pct", "epm_most_optimistic_pct", "epm_most_pessimistic_pct",
            "kronos_base_implied_pct", "kronos_bullish_implied_pct", "kronos_bearish_implied_pct",
            "analyst_recommendation_score", "peg_ratio", "beta",
        ],
        blurb="Trusts the model ensemble and Kronos distribution over the narrative.",
        style_label="Systematic / quant", econ_label="Data-driven", lens_label="Models & factors",
    ),
    Persona(
        name="momentum_trader",
        title="Momentum Trader",
        section_header="MOMENTUM PERSPECTIVE",
        system_prompt=(
            "You are a momentum / trend-following trader. You buy strength and avoid weakness — "
            "relative performance versus the sector, multi-horizon momentum, and trend structure "
            "(MA50/MA200). A strong trend is evidence in itself; a broken one is a warning. Reach "
            "your own conclusion objectively. Every claim must cite a specific number from KEY_FACTS."
        ),
        focus_fields=[
            "mom_5d_pct", "mom_20d_pct", "rel_perf_1m_diff_pct", "rel_perf_3m_diff_pct",
            "rel_perf_6m_diff_pct", "sector_momentum_label", "ma50", "ma200",
        ],
        blurb="Buys strength, avoids weakness — trades the trend, not the story.",
        style_label="Momentum / trend", econ_label="Trend-persistence", lens_label="Relative strength",
    ),
    Persona(
        name="contrarian_analyst",
        title="Contrarian Analyst",
        section_header="CONTRARIAN PERSPECTIVE",
        system_prompt=(
            "You are a contrarian, mean-reversion analyst. You are skeptical of crowded trades and "
            "stretched conditions — extreme RSI, distance from 52-week extremes, elevated volatility "
            "percentile. You look for where consensus has overshot in EITHER direction (over-loved "
            "or over-hated). You do not fade trends reflexively — you fade EXHAUSTION. Every claim "
            "must cite a specific number from KEY_FACTS."
        ),
        focus_fields=[
            "rsi_14", "pct_from_52w_high", "pct_from_52w_low", "atr_percentile",
            "mom_20d_pct", "analyst_target_upside_pct",
        ],
        blurb="Fades exhaustion and crowded trades — looks for over-loved and over-hated alike.",
        style_label="Contrarian / mean-reversion", econ_label="Reversion to mean", lens_label="Crowd positioning",
    ),
    Persona(
        name="sentiment_analyst",
        title="Sentiment & Flows Analyst",
        section_header="SENTIMENT & FLOWS PERSPECTIVE",
        system_prompt=(
            "You are a sentiment and flows analyst. You read market mood and positioning — the VIX "
            "regime, analyst recommendation drift and rating actions, and post-earnings drift signal "
            "— to judge whether sentiment is a tailwind or a headwind. Sentiment can confirm OR fade "
            "the fundamentals; say which. Every claim must cite a specific number from KEY_FACTS."
        ),
        focus_fields=[
            "vix", "vix_regime", "analyst_recommendation_score", "analyst_action_note",
            "pead_signal", "eps_release_surprise_pct",
        ],
        blurb="Reads the mood — VIX, rating drift, and post-earnings flows.",
        style_label="Sentiment / positioning", econ_label="Behavioral", lens_label="Market sentiment",
    ),
    Persona(
        name="risk_manager",
        title="Risk Manager",
        section_header="RISK MANAGEMENT PERSPECTIVE",
        system_prompt=(
            "You are a risk manager. You think in drawdowns, volatility, and leverage — ATR, annualized "
            "volatility, volatility regime, beta, and debt-to-equity — and how big a position the risk "
            "justifies. You are not bearish by default; you size to the risk. A great setup with "
            "uncontainable tail risk is still a small position. Every claim must cite a specific number "
            "from KEY_FACTS."
        ),
        focus_fields=[
            "atr_14", "atr_percentile", "hv_20_annualized_pct", "volatility_regime",
            "beta", "debt_to_equity", "max_drawdown_pct",
        ],
        blurb="Thinks in drawdowns and position size — not bearish, just risk-aware.",
        style_label="Risk / portfolio construction", econ_label="Capital preservation", lens_label="Risk & sizing",
    ),
    Persona(
        name="sector_specialist",
        title="Sector & Moat Specialist",
        section_header="SECTOR & COMPETITIVE PERSPECTIVE",
        system_prompt=(
            "You are a sector specialist focused on competitive moat and industry dynamics. You weigh "
            "profitability versus peers (operating margin, ROE), growth versus the sector, and relative "
            "performance against the sector ETF to judge competitive position. A wide moat justifies a "
            "premium; an eroding one does not. Reach your own conclusion objectively. Every claim must "
            "cite a specific number from KEY_FACTS."
        ),
        focus_fields=[
            "operating_margin_pct", "profit_margin_pct", "roe_pct", "revenue_growth_pct",
            "rel_perf_1m_etf_pct", "sector_momentum_label",
        ],
        blurb="Judges the competitive moat — margins and growth versus the sector.",
        style_label="Fundamental / industry", econ_label="Competitive-advantage", lens_label="Moat & sector",
    ),
    Persona(
        name="income_analyst",
        title="Dividend & Income Analyst",
        section_header="INCOME PERSPECTIVE",
        system_prompt=(
            "You are a dividend / income analyst. You weigh dividend yield, balance-sheet quality "
            "(debt-to-equity), and the durability of cash flow (profit margin, ROE) to judge whether "
            "the payout is safe and the total return attractive. A high yield on a stretched balance "
            "sheet is a warning, not a gift. Every claim must cite a specific number from KEY_FACTS."
        ),
        focus_fields=[
            "dividend_yield_pct", "debt_to_equity", "profit_margin_pct", "roe_pct",
            "trailing_pe", "market_cap_usd",
        ],
        blurb="Weighs yield against balance-sheet quality and cash-flow durability.",
        style_label="Income / quality", econ_label="Cash-flow focused", lens_label="Dividends & balance sheet",
    ),
    Persona(
        name="governance_analyst",
        title="Governance & Litigation Analyst",
        section_header="GOVERNANCE PERSPECTIVE",
        system_prompt=(
            "You are a governance and litigation analyst. You assess management quality and transitions, "
            "legal and regulatory exposure, and M&A activity as structural risks or catalysts. Your "
            "view is qualitative and event-driven, in whichever direction the evidence points — clean "
            "governance and accretive M&A are positives, not just litigation a negative. If "
            "legal_regulatory_note, mgmt_change_note, or mna_note are present, build your view on them."
        ),
        focus_fields=["legal_regulatory_note", "mgmt_change_note", "mna_note"],
        blurb="Weighs management, litigation, and M&A — structural risk and catalyst.",
        style_label="Governance / event-driven", econ_label="Institutional-quality", lens_label="Governance & legal",
    ),
    Persona(
        name="behavioral_analyst",
        title="Behavioral Analyst",
        section_header="BEHAVIORAL PERSPECTIVE",
        system_prompt=(
            "You are a behavioral analyst. You look for where cognitive biases and the prevailing "
            "narrative have pushed price away from fundamentals — anchoring on 52-week levels, "
            "recency from the last earnings surprise, herding signaled by the VIX regime and "
            "post-earnings drift. You name the bias and which way it cuts. Every claim must cite a "
            "specific number from KEY_FACTS."
        ),
        focus_fields=[
            "pead_signal", "eps_release_surprise_pct", "mom_5d_pct", "vix_regime",
            "pct_from_52w_high", "pct_from_52w_low",
        ],
        blurb="Spots where narrative and bias have pushed price off fundamentals.",
        style_label="Behavioral finance", econ_label="Bias-aware", lens_label="Cognitive biases",
    ),
    Persona(
        name="deep_value_bull",
        title="Deep-Value Bull",
        section_header="BULLISH ANALYST PERSPECTIVE",
        kind="bull",
        system_prompt=(
            "You are the deep-value bull. In Round 1, build the strongest evidence-based case for "
            "upside FROM UNDERVALUATION and turnaround potential — a low price relative to the 52-week "
            "range, a compressed multiple, asset/dividend support, and the optimistic EPM/Kronos "
            "targets. Make the re-rating case impossible to ignore. You are an honest analyst, not a "
            "permabull: if the downside decisively outweighs the upside, you may concede. Cite specific "
            "numbers from KEY_FACTS; never invent."
        ),
        focus_fields=[
            "pct_from_52w_low", "trailing_pe", "forward_pe", "price_to_book", "dividend_yield_pct",
            "epm_most_optimistic_pct", "kronos_bullish_target", "kronos_bullish_implied_pct",
        ],
        blurb="Argues upside from undervaluation and turnaround — the re-rating case.",
        style_label="Deep-value advocate", econ_label="Contrarian-bullish", lens_label="Bull case (value)",
    ),
    Persona(
        name="macro_bear",
        title="Macro & Tail-Risk Bear",
        section_header="BEARISH ANALYST PERSPECTIVE",
        kind="bear",
        system_prompt=(
            "You are the macro and tail-risk bear. In Round 1, build the strongest evidence-based case "
            "for downside FROM MACRO AND TAIL RISK — an elevated VIX regime, weak index momentum, high "
            "volatility percentile, leverage, and the pessimistic EPM/Kronos targets. Make the "
            "downside scenario impossible to ignore. You are an honest analyst, not a permabear: if the "
            "upside decisively outweighs the downside, you may concede. Cite specific numbers from "
            "KEY_FACTS; never invent."
        ),
        focus_fields=[
            "vix", "vix_regime", "spy_20d_pct", "atr_percentile", "debt_to_equity",
            "epm_most_pessimistic_pct", "kronos_bearish_target", "kronos_bearish_implied_pct",
        ],
        blurb="Argues downside from macro headwinds and tail risk.",
        style_label="Macro-bear advocate", econ_label="Defensive / cautious", lens_label="Bear case (macro)",
    ),
]


# Full selectable library: 8 enriched defaults + 11 extras = 19 members.
LIBRARY: List[Persona] = [_enrich_default(p) for p in PERSONAS] + _EXTRA_PERSONAS
_BY_ID: Dict[str, Persona] = {p.name: p for p in LIBRARY}

# Default roster = the canonical 8 (reproduces today's council exactly).
DEFAULT_ROSTER: List[str] = [p.name for p in PERSONAS]

MAX_COUNCIL = 8
MIN_COUNCIL = 3
_CUSTOM_TEXT_MAX = 600

# ---------------------------------------------------------------------------
# Trait axes — quick personality tweaks. NONE impose a bull/bear lean.
# ---------------------------------------------------------------------------

TRAIT_AXES: Dict[str, Dict[str, Any]] = {
    "conviction": {"label": "Conviction", "options": ["Cautious", "Balanced", "High-conviction"]},
    "horizon":    {"label": "Time horizon", "options": ["Short-term", "Swing", "Long-term"]},
    "school":     {"label": "School of thought", "options": ["Value", "Growth", "Momentum", "Quant", "Macro", "Contrarian"]},
    "risk":       {"label": "Risk posture", "options": ["Risk-averse", "Moderate", "Risk-seeking"]},
}

_TRAIT_SENTENCE = {
    "conviction": "a {} conviction level",
    "horizon": "a {} time horizon",
    "school": "a {} school-of-thought lens",
    "risk": "a {} risk posture",
}


# ---------------------------------------------------------------------------
# Custom-personality sanitisation
# ---------------------------------------------------------------------------

_INJECTION_RE = re.compile(
    r"(?i)\b(ignore (?:all |the )?(?:previous|above|prior) (?:instructions?|prompts?)|"
    r"system\s*:|disregard (?:all|the|your)|you are now|new instructions?)\b"
)


def _sanitize_custom_text(text: str) -> str:
    """Bound and neutralise a user-supplied personality string.

    Not a hard security boundary (the endpoint is auth-gated), but it caps
    length, strips code fences / control chars, and removes the most common
    prompt-injection phrasings so the text reads as a personality description.
    """
    if not text:
        return ""
    t = str(text)
    t = t.replace("```", " ").replace("`", "'")
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", t)   # control chars
    t = _INJECTION_RE.sub("[removed]", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:_CUSTOM_TEXT_MAX]


def _overlay(traits: Optional[Dict[str, str]], custom_text: str) -> str:
    """Compose a PERSONALITY OVERLAY appended to a persona's system_prompt."""
    parts: List[str] = []
    trait_bits = []
    for axis, sentence in _TRAIT_SENTENCE.items():
        val = (traits or {}).get(axis)
        if val and val in TRAIT_AXES[axis]["options"]:
            trait_bits.append(sentence.format(val))
    if trait_bits:
        parts.append(
            "PERSONALITY OVERLAY: Approach this analysis with " + ", ".join(trait_bits)
            + ". This shapes your temperament and emphasis, NOT your conclusion — your stance must "
            "still follow the evidence."
        )
    clean = _sanitize_custom_text(custom_text)
    if clean:
        parts.append(
            "PERSONALITY (user-defined): " + clean
            + " Stay grounded in KEY_FACTS; this describes your style, not a license to invent."
        )
    return ("\n\n" + "\n\n".join(parts)) if parts else ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def default_roster_spec() -> List[Dict[str, Any]]:
    """The default 8-member roster as a spec (no traits, no custom text)."""
    return [{"id": pid, "traits": {}, "custom_text": ""} for pid in DEFAULT_ROSTER]


def library_payload() -> Dict[str, Any]:
    """Serialisable library + axes for the Council Builder UI."""
    return {
        "members": [
            {
                "id": p.name, "title": p.title, "kind": p.kind, "blurb": p.blurb,
                "style_label": p.style_label, "econ_label": p.econ_label, "lens_label": p.lens_label,
            }
            for p in LIBRARY
        ],
        "trait_axes": TRAIT_AXES,
        "default_roster": DEFAULT_ROSTER,
        "max_council": MAX_COUNCIL,
        "min_council": MIN_COUNCIL,
        "custom_text_max": _CUSTOM_TEXT_MAX,
    }


def validate_roster(spec: Any) -> Tuple[bool, str]:
    """Validate a roster spec. Returns (ok, error_message)."""
    if not isinstance(spec, list):
        return False, "Roster must be a list of members."
    if not (MIN_COUNCIL <= len(spec) <= MAX_COUNCIL):
        return False, f"Council must have between {MIN_COUNCIL} and {MAX_COUNCIL} members."
    seen: set = set()
    kinds = {"bull": 0, "bear": 0, "neutral": 0}
    for entry in spec:
        if not isinstance(entry, dict):
            return False, "Each member must be an object."
        pid = entry.get("id")
        base = _BY_ID.get(pid)
        if base is None:
            return False, f"Unknown council member: {pid!r}."
        if pid in seen:
            return False, f"Duplicate member: {pid!r}."
        seen.add(pid)
        kinds[base.kind] = kinds.get(base.kind, 0) + 1
        traits = entry.get("traits") or {}
        if not isinstance(traits, dict):
            return False, "Member traits must be an object."
        for axis, val in traits.items():
            if axis not in TRAIT_AXES:
                return False, f"Unknown trait axis: {axis!r}."
            if val and val not in TRAIT_AXES[axis]["options"]:
                return False, f"Invalid {axis} value: {val!r}."
        ct = entry.get("custom_text") or ""
        if not isinstance(ct, str):
            return False, "custom_text must be a string."
        if len(ct) > _CUSTOM_TEXT_MAX * 2:
            return False, "Custom personality is too long."
    if kinds["bull"] < 1:
        return False, "Council needs at least one bullish analyst."
    if kinds["bear"] < 1:
        return False, "Council needs at least one bearish analyst."
    return True, ""


def build_personas(spec: List[Dict[str, Any]], is_fund: bool = False) -> List[Persona]:
    """Resolve a roster spec into engine-ready Persona objects.

    Applies trait/custom-text overlays and, on funds/ETFs, swaps the
    earnings_catalyst persona for the fund-structure analyst (matching the
    default-path behaviour in run_council).
    """
    personas: List[Persona] = []
    for entry in spec:
        base = _BY_ID.get(entry.get("id"))
        if base is None:
            continue
        if is_fund and base.name == "earnings_catalyst":
            base = FUND_STRUCTURE_PERSONA
        overlay = _overlay(entry.get("traits"), entry.get("custom_text") or "")
        if overlay:
            base = dataclasses.replace(base, system_prompt=base.system_prompt + overlay)
        personas.append(base)
    return personas


def roster_signature(spec: Optional[List[Dict[str, Any]]]) -> str:
    """Stable short hash of a roster spec for cache matching.

    Returns 'default' for the canonical default roster (no traits/custom text)
    so default runs share the daily cache; any customisation yields a unique
    signature that will not be served to or clobbered by a default request.
    """
    if not spec:
        return "default"
    norm = []
    for e in spec:
        norm.append({
            "id": e.get("id"),
            "traits": {k: v for k, v in sorted((e.get("traits") or {}).items()) if v},
            "custom_text": _sanitize_custom_text(e.get("custom_text") or ""),
        })
    norm.sort(key=lambda x: x["id"] or "")
    ids_only = all(not e["traits"] and not e["custom_text"] for e in norm)
    if ids_only and sorted(e["id"] for e in norm) == sorted(DEFAULT_ROSTER):
        return "default"
    blob = json.dumps(norm, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
