"""
compare_llm_models.py

Side-by-side quality comparison of qwen2.5:7b vs qwen3.5:4b using the real
SYSTEM_PROMPT_NARRATIVE from generate_market_commentary.py and real 2026-05-15
market data from latest_commentary.json.

Usage:
    python compare_llm_models.py
    python compare_llm_models.py --models qwen2.5:7b,qwen3.5:4b,phi4-mini:latest
    python compare_llm_models.py --save         # also write results to data/llm_comparison.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OLLAMA_HOST = "http://100.101.63.65:11434"
OLLAMA_TIMEOUT = 300

DATA_DIR = Path("data")
COMMENTARY_PATH = DATA_DIR / "latest_commentary.json"

# ---------------------------------------------------------------------------
# Prompts — imported verbatim from generate_market_commentary.py
# ---------------------------------------------------------------------------

WRITING_RULES = """You are a senior market strategist writing for EPM Financial's daily Market Intelligence Report.
Rules: tight analytical prose; no filler; present tense; active voice.
NEVER use: "geopolitical tensions", "geopolitical risks", "global uncertainties", "amid uncertainty", "amid concerns", "it is worth noting", "in conclusion", "overall,", "moving forward".
All market directions MUST match the sign of pct_change values provided.
Do NOT describe a yield or price as "unchanged" if a non-zero pct_change is provided — state the actual direction (rose/fell) and magnitude instead.
Do not invent figures or events not in the payload.
Do NOT attribute geopolitical actions, policy proposals, or peace initiatives to specific companies or financial institutions — if a headline mentions a bank alongside a geopolitical event, the bank is a commentator or stakeholder, not the actor proposing the policy.
Do NOT escalate the severity of geopolitical events beyond the exact language in the payload — if headlines say "tensions" or "conflict", do not write "war"; if they say "negotiations", do not write "deal reached".
NARRATIVE COHERENCE: All sections must describe the same geopolitical reality. If one section cites escalating risk ("expanded strikes", "rising tensions"), no other section may simultaneously frame the same situation as de-escalating ("easing tensions", "peace deal hopes", "ceasefire optimism"). Pick the dominant tone from the headlines payload and apply it consistently across every section.
Do NOT cite foreign central banks (BoE, ECB, BoJ, PBoC, RBA, BoC, SNB) or foreign sovereign yields (Gilts, Bunds, JGBs) as drivers of US asset moves unless a US-asset headline in the payload explicitly names that institution.
Return ONLY valid JSON  no markdown fences, no explanation."""

SYSTEM_PROMPT_NARRATIVE = WRITING_RULES + """

Return JSON with EXACTLY these 6 keys:

NUMBER FIDELITY (non-negotiable):
- Every percent and price you cite MUST equal the value in the payload to within 0.01.
- S&P 500: use market_levels["S&P 500"]["pct_change"] for the percent; ["level"] for the price.
- Apply the same rule for Nasdaq 100, DXY, 10-Yr Yield, Gold, WTI Crude against market_levels / bonds / commodities_top6 / currencies_top5.
- Direction words (rose/fell/gained/slid) MUST agree with the SIGN of pct_change. A pct_change of -0.04% is "essentially flat" or "barely changed" — NOT "lower" or "fell".
- SIGN PRESERVATION (most-violated rule): If pct_change is negative, the cited percent must be negative AND the verb must be "fell"/"slid"/"declined". If pct_change is positive, the cited percent must be positive AND the verb must be "rose"/"gained"/"climbed". Magnitude alone is wrong — sign and verb must both match.
- MAGNITUDE FIDELITY: Always cite the percent figure from pct_change, never the raw dollar delta.
- If a number is missing from the payload, OMIT it entirely. Do NOT estimate, round, or invent.

pre_market_bullets: Array of 5 strings:
  [0] "Markets closed [higher/lower]  S&P 500 [pct]%, Nasdaq 100 [pct]%; [specific catalyst from news]."
  [1] International/macro driver — cite one specific market-moving event.
  [2] Economic calendar: cite the single most important upcoming event (name, importance, date).
  [3] Fed/rates: cite 10-yr yield level and direction with a specific driver.
  [4] Top commodity or currency move with named driver.

equities_commentary: 3-4 sentence paragraph on US equity market. Cite S&P and Nasdaq levels and % changes exactly.
fixed_income_commentary: 2-3 sentence paragraph on bond market and 10-yr yield.
commodities_commentary: 2-3 sentence paragraph on commodities using exact figures.
currencies_commentary: 2-3 sentence paragraph on DXY and major pairs using exact figures.
economics_commentary: 2-3 sentence paragraph on economic data context."""

SYSTEM_PROMPT_OUTLOOK = WRITING_RULES + """

Return JSON with EXACTLY these keys:
market_outlook_label: exactly one of "Bullish" | "Cautious" | "Neutral" | "Bearish"
market_outlook_rationale: exactly 2 sentences explaining the label.
tactical_outperforming: comma-separated list of 2-3 sectors/themes currently outperforming.
tactical_underperforming: comma-separated list of 2-3 sectors/themes currently underperforming."""


# ---------------------------------------------------------------------------
# Build test payload from saved commentary data
# ---------------------------------------------------------------------------

def build_test_payload() -> tuple[dict, dict]:
    """Return (narrative_payload, outlook_payload) from saved latest_commentary.json."""
    data = json.loads(COMMENTARY_PATH.read_text(encoding="utf-8"))

    snap = data.get("market_snapshot", {})
    bonds = data.get("bonds_table", {})
    gm = dict(list(data.get("global_markets", {}).items())[:5])
    cmdty = dict(list(data.get("commodities_table", {}).items())[:6])
    fx = dict(list(data.get("currencies_table", {}).items())[:5])

    cal = json.loads((DATA_DIR / "economic_calendar.json").read_text(encoding="utf-8"))
    econ = cal.get("events", [])[:5]

    # Representative headlines from the 2026-05-15 session (from pre_market_bullets context)
    headlines = [
        "S&P 500 falls 0.75% as gold slumps to one-week low on inflation worries",
        "Gold prices fall on fears of sustained high rates; weekly decline likely",
        "WTI crude slides 0.75% to $99.84 on softer Asian demand signals",
        "U.S.-China trade talks scheduled for next week; markets cautiously optimistic",
        "10-year Treasury yield rises 2bp to 4.47% after stronger-than-expected jobless claims",
        "Nvidia shares fall despite record Q1 earnings as AI spending guidance disappoints",
        "Empire State Manufacturing survey due; consensus sees modest contraction",
        "DXY rises 0.66% to 99.28 as dollar demand picks up on rate differentials",
        "Reports of expanded strikes near Iranian facilities; diplomatic talks stall",
        "Euro Stoxx 50 edges lower as ECB officials signal caution on rate cuts",
    ]

    narrative_payload = {
        "date": data.get("report_date", "2026-05-15"),
        "market_levels": snap,
        "bonds": bonds,
        "global_markets_top5": gm,
        "commodities_top6": cmdty,
        "currencies_top5": fx,
        "upcoming_economic_events": econ,
        "recent_headlines": headlines,
        "recent_earnings_actuals": [],
    }

    outlook_payload = {
        "date": data.get("report_date", "2026-05-15"),
        "market_levels": snap,
        "bonds": bonds,
        "recent_headlines": headlines,
        "narrative_summary": "S&P 500 fell 0.75%; gold slumped 3.23% on rate fears; 10-yr yield rose to 4.47%; WTI -0.75%.",
    }

    return narrative_payload, outlook_payload


# ---------------------------------------------------------------------------
# Ollama call
# ---------------------------------------------------------------------------

def call_model(model: str, system: str, user_payload: dict) -> tuple[dict | None, float, str]:
    """Call model; return (parsed_dict_or_None, elapsed_seconds, raw_content)."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, default=str)},
        ],
        "stream": False,
        "format": "json",
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": 2048,
            "num_ctx": 8192,
        },
    }
    t0 = time.time()
    try:
        resp = requests.post(f"{OLLAMA_HOST}/api/chat", json=body, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        elapsed = time.time() - t0
        raw = resp.json()["message"]["content"]
        parsed = json.loads(raw)
        return parsed, elapsed, raw
    except Exception as exc:
        elapsed = time.time() - t0
        return None, elapsed, f"ERROR: {exc}"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

FORBIDDEN_PHRASES = [
    "geopolitical tensions", "geopolitical risks", "global uncertainties",
    "amid uncertainty", "amid concerns", "it is worth noting",
    "in conclusion", "overall,", "moving forward",
]

def score_narrative(result: dict | None, payload: dict) -> dict:
    """Quick automated quality checks on narrative output."""
    if result is None:
        return {"valid_json": False}

    scores: dict = {"valid_json": True}

    # Forbidden phrase check
    all_text = " ".join(str(v) for v in result.values() if isinstance(v, str)).lower()
    forbidden_hits = [p for p in FORBIDDEN_PHRASES if p in all_text]
    scores["forbidden_phrases"] = forbidden_hits
    scores["forbidden_count"] = len(forbidden_hits)

    # Key presence
    expected_keys = ["pre_market_bullets", "equities_commentary", "fixed_income_commentary",
                     "commodities_commentary", "currencies_commentary", "economics_commentary"]
    scores["missing_keys"] = [k for k in expected_keys if k not in result]

    # Bullet count
    bullets = result.get("pre_market_bullets", [])
    scores["bullet_count"] = len(bullets) if isinstance(bullets, list) else 0

    # Number fidelity — check S&P 500 pct_change sign
    sp_pct = payload.get("market_levels", {}).get("S&P 500", {}).get("pct_change", None)
    eq = result.get("equities_commentary", "")
    if sp_pct is not None and isinstance(eq, str):
        if sp_pct < 0:
            scores["sp_sign_correct"] = "fell" in eq.lower() or "declined" in eq.lower() or "lower" in eq.lower() or "slide" in eq.lower() or "slid" in eq.lower()
        else:
            scores["sp_sign_correct"] = "rose" in eq.lower() or "gained" in eq.lower() or "climbed" in eq.lower() or "higher" in eq.lower()

    return scores


def score_outlook(result: dict | None) -> dict:
    if result is None:
        return {"valid_json": False}
    valid_labels = {"Bullish", "Cautious", "Neutral", "Bearish"}
    label = result.get("market_outlook_label", "")
    return {
        "valid_json": True,
        "valid_label": label in valid_labels,
        "label": label,
        "has_rationale": bool(result.get("market_outlook_rationale")),
        "has_tactical": bool(result.get("tactical_outperforming") and result.get("tactical_underperforming")),
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _wrap(text: str, width: int = 90) -> list[str]:
    import textwrap
    return textwrap.wrap(text, width=width)


def print_comparison(models: list[str], results: dict, scores: dict, elapsed: dict) -> None:
    SEP = "=" * 100

    print(f"\n{SEP}")
    print("LLM MODEL COMPARISON  —  2026-05-15 market data  —  no tuning")
    print(f"Models tested: {', '.join(models)}")
    print(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEP)

    # --- Timing & scores table ---
    print(f"\n{'Field':<30}", end="")
    for m in models:
        short = m.split(":")[0][:18]
        print(f"{short:>22}", end="")
    print()
    print("-" * (30 + 22 * len(models)))

    def row(label, fn):
        print(f"{label:<30}", end="")
        for m in models:
            val = fn(m)
            print(f"{str(val):>22}", end="")
        print()

    row("Elapsed — narrative (s)", lambda m: f"{elapsed[m]['narrative']:.1f}s")
    row("Elapsed — outlook (s)",   lambda m: f"{elapsed[m]['outlook']:.1f}s")
    row("Valid JSON (narrative)",   lambda m: scores[m]['narrative'].get('valid_json'))
    row("Valid JSON (outlook)",     lambda m: scores[m]['outlook'].get('valid_json'))
    row("Missing keys",            lambda m: scores[m]['narrative'].get('missing_keys', []))
    row("Bullet count",            lambda m: scores[m]['narrative'].get('bullet_count', '?'))
    row("Forbidden phrases",       lambda m: scores[m]['narrative'].get('forbidden_count', '?'))
    row("S&P sign correct",        lambda m: scores[m]['narrative'].get('sp_sign_correct', '?'))
    row("Outlook label",           lambda m: scores[m]['outlook'].get('label', '?'))
    row("Valid label",             lambda m: scores[m]['outlook'].get('valid_label', '?'))
    row("Has tactical sectors",    lambda m: scores[m]['outlook'].get('has_tactical', '?'))

    # --- Per-field side-by-side ---
    fields_narrative = [
        ("pre_market_bullets", "PRE-MARKET BULLETS"),
        ("equities_commentary", "EQUITIES COMMENTARY"),
        ("fixed_income_commentary", "FIXED INCOME COMMENTARY"),
        ("commodities_commentary", "COMMODITIES COMMENTARY"),
        ("currencies_commentary", "CURRENCIES COMMENTARY"),
        ("economics_commentary", "ECONOMICS COMMENTARY"),
    ]
    fields_outlook = [
        ("market_outlook_label", "OUTLOOK LABEL"),
        ("market_outlook_rationale", "OUTLOOK RATIONALE"),
        ("tactical_outperforming", "TACTICAL OUTPERFORMING"),
        ("tactical_underperforming", "TACTICAL UNDERPERFORMING"),
    ]

    for key, label in fields_narrative + fields_outlook:
        print(f"\n{'—' * 100}")
        print(f"  {label}")
        print(f"{'—' * 100}")
        call = "narrative" if (key, label) in fields_narrative else "outlook"
        for m in models:
            r = results[m].get(call)
            val = r.get(key, "[MISSING]") if r else "[NO RESULT]"
            print(f"\n  [{m}]")
            if isinstance(val, list):
                for i, item in enumerate(val):
                    print(f"    [{i}] {item}")
            elif isinstance(val, dict):
                print(f"    {json.dumps(val, indent=6)}")
            else:
                for line in _wrap(str(val)):
                    print(f"    {line}")

    # --- Forbidden phrase detail ---
    print(f"\n{'—' * 100}")
    print("  FORBIDDEN PHRASE VIOLATIONS")
    print(f"{'—' * 100}")
    for m in models:
        hits = scores[m]['narrative'].get('forbidden_phrases', [])
        print(f"\n  [{m}]: {hits if hits else 'NONE'}")

    print(f"\n{SEP}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="qwen2.5:7b,qwen3.5:4b",
                    help="Comma-separated Ollama model tags to compare")
    ap.add_argument("--save", action="store_true", help="Save results to data/llm_comparison.json")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    narrative_payload, outlook_payload = build_test_payload()

    results: dict = {}
    scores: dict = {}
    elapsed: dict = {}
    raw_outputs: dict = {}

    for model in models:
        print(f"\n>>> Testing model: {model}")
        results[model] = {}
        elapsed[model] = {}
        raw_outputs[model] = {}

        print(f"  Call 1/2 — narrative sections...")
        parsed, t, raw = call_model(model, SYSTEM_PROMPT_NARRATIVE, narrative_payload)
        results[model]["narrative"] = parsed
        elapsed[model]["narrative"] = t
        raw_outputs[model]["narrative"] = raw
        print(f"  Done in {t:.1f}s — {'OK' if parsed else 'PARSE ERROR'}")

        print(f"  Call 2/2 — outlook...")
        parsed2, t2, raw2 = call_model(model, SYSTEM_PROMPT_OUTLOOK, outlook_payload)
        results[model]["outlook"] = parsed2
        elapsed[model]["outlook"] = t2
        raw_outputs[model]["outlook"] = raw2
        print(f"  Done in {t2:.1f}s — {'OK' if parsed2 else 'PARSE ERROR'}")

        scores[model] = {
            "narrative": score_narrative(results[model]["narrative"], narrative_payload),
            "outlook": score_outlook(results[model]["outlook"]),
        }

    print_comparison(models, results, scores, elapsed)

    if args.save:
        out = {
            "run_at": datetime.now().isoformat(),
            "models": models,
            "results": results,
            "scores": scores,
            "elapsed": elapsed,
        }
        path = DATA_DIR / "llm_comparison.json"
        path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        print(f"Results saved -> {path}")


if __name__ == "__main__":
    main()
