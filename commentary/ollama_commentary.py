import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

OLLAMA_HOST = os.getenv("LOCAL_OLLAMA_URL", "http://100.101.63.65:11434")
OLLAMA_MODEL = os.getenv("MAG7_OLLAMA_MODEL") or os.getenv("LOCAL_OLLAMA_MODEL", "qwen3.5:9b")
OLLAMA_TIMEOUT = int(os.getenv("LOCAL_OLLAMA_TIMEOUT", "180"))

DEBUG_DIR = Path("commentary_debug")
DEBUG_DIR.mkdir(exist_ok=True)

SYSTEM_PROMPT = """
You are a commentary layer for a quantitative investment report.

Rules:
- Use ONLY the JSON data provided by the user.
- Do NOT invent numbers, events, or explanations not supported by the JSON.
- Do NOT recalculate forecasts.
- Do NOT provide buy/sell recommendations.
- Do NOT speak as if you are the forecasting model.
- Your job is interpretation only.
- Be concise, professional, and plain-English.
- Return valid JSON only.
- Do not use markdown.
- Do not wrap the response in code fences.
- All strings must use standard JSON double quotes.

Writing style:
- Avoid generic phrases such as "the report indicates", "the highlights suggest", "market regime", "risk-on", and "risk-off" unless the JSON explicitly supports them.
- Sound like a market strategist summarizing the tape, not a model explaining itself.
- Use direct language tied to breadth, agreement, and where leadership is concentrated.
- Prefer concrete wording such as "leadership is narrow", "signals are mixed", "upside is concentrated", or "breadth is split" when supported by the JSON.
- portfolio_overview must summarize the full MAG7 set, not just restate the three highlights.
- market_reflection must interpret what the highlights imply about the broader group and should not repeat the overview.
- Do not mention "the report" or "the three highlights".

Length limits:
- portfolio_overview: maximum 2 short sentences
- top_bullets: exactly 3 bullets, each 1 short sentence
- market_reflection: 1 to 2 short sentences
- Use the field names faithfully:
  - ytd_return_pct means year-to-date return, not 1-year return
  - model_agreement is a label such as high, moderate, low, flat, or insufficient
- Do not convert qualitative labels into numeric scores
- The payload includes a top_highlights array chosen deterministically on the laptop.
- top_bullets must cover those exact 3 highlight tickers in the same order.
- Each top bullet must explicitly say whether the name is bullish or bearish and briefly explain why using highlight_reason.
- top_bullets should be short highlight sentences only, not mini data dumps.
- Do not list price, YTD return, beta, or Sharpe in the top bullets.
""".strip()

REPAIR_PROMPT = """
You repair malformed JSON.

You will receive text that was meant to be JSON but is invalid.
Your job is to convert it into valid JSON that matches the required structure.

Rules:
- Return valid JSON only.
- Do not use markdown.
- Do not use code fences.
- Preserve the meaning of the text.
- If needed, shorten wording slightly to make the JSON valid.
- Do not add new facts.
""".strip()

OLLAMA_KEEP_ALIVE = os.getenv("LOCAL_OLLAMA_KEEP_ALIVE", "45m")

COMMENTARY_SCHEMA = {
    "type": "object",
    "properties": {
        "portfolio_overview": {"type": "string"},
        "top_bullets": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {"type": "string"}
        },
        "market_reflection": {"type": "string"},
        "ticker_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "commentary": {"type": "string"}
                },
                "required": ["ticker", "commentary"]
            }
        }
    },
    "required": ["portfolio_overview", "top_bullets", "market_reflection"]
}

def warmup_model() -> bool:
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "keep_alive": OLLAMA_KEEP_ALIVE,
        }
        response = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=30)
        response.raise_for_status()
        return True
    except Exception:
        return False

def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if value == "":
            return None
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _agreement_label(forecasts: List[Optional[float]]) -> str:
    valid = [x for x in forecasts if isinstance(x, (int, float))]
    if len(valid) < 2:
        return "insufficient"
    positives = sum(1 for x in valid if x > 0)
    negatives = sum(1 for x in valid if x < 0)
    zeros = sum(1 for x in valid if x == 0)
    if positives == len(valid) or negatives == len(valid):
        return "high"
    if max(positives, negatives) >= len(valid) - 1:
        return "moderate"
    if zeros == len(valid):
        return "flat"
    return "low"


def _save_debug_text(filename: str, text: str) -> str:
    path = DEBUG_DIR / filename
    path.write_text(text, encoding="utf-8")
    return str(path)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines).strip()
    return text


def _extract_json_object(text: str) -> str:
    text = _strip_code_fences(text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def _parse_json_text(text: str) -> Dict[str, Any]:
    cleaned = _extract_json_object(text)
    return json.loads(cleaned)

def _post_chat(messages: List[Dict[str, str]], fmt: Any, num_predict: int = 300) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "format": fmt,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": 0,
            "num_predict": num_predict,
        },
    }
    response = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=OLLAMA_TIMEOUT)
    response.raise_for_status()
    raw = response.json()
    _save_debug_text("last_commentary_raw.txt", raw.get("message", {}).get("content", ""))
    return raw["message"]["content"].strip()


def build_commentary_payload(report_date: str, market_summary: Dict[str, Any], ticker_rows: List[Dict[str, Any]], top_highlights: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    cleaned_tickers = []
    top_highlights = top_highlights or []
    for row in ticker_rows:
        linear = _safe_float(row.get("linear_forecast_21d_pct"))
        ff3 = _safe_float(row.get("ff3_forecast_21d_pct"))
        inst = _safe_float(row.get("institutional_forecast_21d_pct"))
        qc = _safe_float(row.get("quantconnect_forecast_21d_pct"))
        ml = _safe_float(row.get("ml_forecast_21d_pct"))
        cleaned_tickers.append(
            {
                "ticker": _clean_text(row.get("ticker")),
                "name": _clean_text(row.get("name")),
                "price": _safe_float(row.get("price")),
                "ytd_return_pct": _safe_float(row.get("ytd_return_pct")),
                "beta_3y": _safe_float(row.get("beta_3y")),
                "sharpe_3y": _safe_float(row.get("sharpe_3y")),
                "ma200_signal": _clean_text(row.get("ma200_signal")),
                "linear_forecast_21d_pct": linear,
                "ff3_forecast_21d_pct": ff3,
                "institutional_forecast_21d_pct": inst,
                "quantconnect_forecast_21d_pct": qc,
                "ml_forecast_21d_pct": ml,
                "model_agreement": _agreement_label([linear, ff3, inst, qc, ml]),
            }
        )
    return {
        "as_of": report_date,
        "market_summary": {
            "report_title": _clean_text(market_summary.get("report_title")),
            "market_regime": _clean_text(market_summary.get("market_regime")),
            "top_strengths": market_summary.get("top_strengths", []),
            "top_risks": market_summary.get("top_risks", []),
            "notes": _clean_text(market_summary.get("notes")),
        },
        "top_highlights": [
            {
                "ticker": _clean_text(row.get("ticker")),
                "name": _clean_text(row.get("name")),
                "highlight_bias": _clean_text(row.get("highlight_bias")),
                "highlight_reason": _clean_text(row.get("highlight_reason")),
                "consensus_forecast_pct": _safe_float(row.get("consensus_forecast_pct")),
                "confidence_label": _clean_text(row.get("confidence_label")),
                "model_agreement": _clean_text(row.get("model_agreement")),
            }
            for row in top_highlights
        ],
        "tickers": cleaned_tickers,
    }



def _sanitize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("text", "summary", "overview", "reflection", "commentary"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return " ".join(candidate.strip().split())
        return ""
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            cleaned = _sanitize_text(item)
            if cleaned:
                parts.append(cleaned)
        return " ".join(parts).strip()
    return " ".join(str(value).strip().split())


def _format_highlight_bullets(top_highlights: List[Dict[str, Any]]) -> List[str]:
    bullets: List[str] = []
    for row in (top_highlights or [])[:3]:
        bias = "Bullish" if str(row.get("highlight_bias", "")).strip().lower() == "bullish" else "Bearish"
        ticker = _sanitize_text(row.get("ticker"))
        reason = _sanitize_text(row.get("highlight_reason"))
        if not ticker:
            continue
        if reason and not reason.endswith("."):
            reason += "."
        bullets.append(f"{bias} — {ticker}: {reason}".strip())
    return bullets[:3]


def _build_fallback_overview(summary_payload: Dict[str, Any]) -> str:
    tickers = summary_payload.get("tickers", []) or []
    valid_consensus: List[float] = []
    bullish = 0
    bearish = 0
    agreement_counts: Dict[str, int] = {}
    for row in tickers:
        value = _safe_float(row.get("consensus_forecast_pct"))
        if value is not None:
            valid_consensus.append(value)
            if value > 0:
                bullish += 1
            elif value < 0:
                bearish += 1
        label = _sanitize_text(row.get("model_agreement")).lower()
        if label:
            agreement_counts[label] = agreement_counts.get(label, 0) + 1
    parts: List[str] = []
    if valid_consensus:
        avg_consensus = sum(valid_consensus) / len(valid_consensus)
        tone = "positive" if avg_consensus >= 0 else "negative"
        parts.append(f"MAG7 consensus forecasts are {tone} on balance at {avg_consensus:.2f}%.")
    if tickers:
        dominant = max(agreement_counts, key=agreement_counts.get) if agreement_counts else "mixed"
        parts.append(f"Breadth is {bullish} bullish versus {bearish} bearish names, with {dominant} model agreement most common.")
    return " ".join(parts[:2]).strip()


def _build_fallback_reflection(summary_payload: Dict[str, Any]) -> str:
    highlights = summary_payload.get("top_highlights", []) or []
    if not highlights:
        return "The current forecast mix points to a selective rather than uniform MAG7 backdrop, with leadership concentrated in the stronger names and caution still visible elsewhere."
    bullish = sum(1 for row in highlights if _sanitize_text(row.get("highlight_bias")).lower() == "bullish")
    bearish = sum(1 for row in highlights if _sanitize_text(row.get("highlight_bias")).lower() == "bearish")
    if bullish >= 2 and bearish >= 1:
        return "The current highlight set points to selective leadership rather than a broad risk-on tape. Strength is concentrated in a few names, while at least one major platform name still argues for caution."
    if bullish == len(highlights):
        return "The current highlight set points to a broadly constructive MAG7 tone, with strength visible across several of the most closely watched names."
    return "The current highlight set points to a cautious MAG7 tone, with upside concentrated in fewer names and risk still present across the group."


def _top_highlight_tickers(summary_payload: Dict[str, Any]) -> List[str]:
    return [
        _sanitize_text(row.get("ticker"))
        for row in (summary_payload.get("top_highlights", []) or [])[:3]
        if _sanitize_text(row.get("ticker"))
    ]


def _overview_grounded_enough(text: str, summary_payload: Dict[str, Any]) -> bool:
    cleaned = _sanitize_text(text)
    if not cleaned:
        return False
    lower = cleaned.lower()
    banned_prefixes = (
        "the report indicates",
        "the report shows",
        "the report suggests",
        "the report points to",
        "the current report",
    )
    banned_fragments = (
        "the highlights suggest",
        "the three highlights",
        "market regime",
    )
    if lower.startswith(banned_prefixes):
        return False
    if any(fragment in lower for fragment in banned_fragments):
        return False
    signal_terms = (
        "bullish", "bearish", "breadth", "agreement", "consensus", "leadership", "mixed", "concentrated",
        "split", "narrow", "tone", "stronger", "weaker"
    )
    return any(term in lower for term in signal_terms)


def _reflection_grounded_enough(text: str, summary_payload: Dict[str, Any]) -> bool:
    cleaned = _sanitize_text(text)
    if not cleaned:
        return False
    lower = cleaned.lower()
    if lower.startswith(("the report indicates", "the report shows", "the report suggests", "the highlights suggest", "the three highlights")):
        return False
    if "what this suggests" in lower:
        return False
    if "market regime" in lower:
        return False
    highlight_tickers = [t.lower() for t in _top_highlight_tickers(summary_payload)]
    if any(t and t in lower for t in highlight_tickers):
        return True
    return any(term in lower for term in ("leadership", "breadth", "concentrated", "selective", "mixed", "tone", "split"))


def _build_grounded_overview(summary_payload: Dict[str, Any]) -> str:
    tickers = summary_payload.get("tickers", []) or []
    valid_consensus: List[float] = []
    bullish = 0
    bearish = 0
    agreement_counts: Dict[str, int] = {}
    for row in tickers:
        value = _safe_float(row.get("consensus_forecast_pct"))
        if value is not None:
            valid_consensus.append(value)
            if value > 0:
                bullish += 1
            elif value < 0:
                bearish += 1
        label = _sanitize_text(row.get("model_agreement")).lower()
        if label:
            agreement_counts[label] = agreement_counts.get(label, 0) + 1

    parts: List[str] = []
    if valid_consensus:
        avg_consensus = sum(valid_consensus) / len(valid_consensus)
        if bullish > bearish:
            parts.append(f"MAG7 signals lean constructive overall, but breadth is not uniform, with {bullish} bullish names versus {bearish} bearish.")
        elif bearish > bullish:
            parts.append(f"MAG7 signals skew defensive overall, with {bearish} bearish names versus {bullish} bullish.")
        else:
            parts.append(f"MAG7 signals are mixed overall, with breadth split at {bullish} bullish and {bearish} bearish names.")

        if avg_consensus >= 0:
            parts.append(f"Consensus is still positive on balance at {avg_consensus:.2f}%, which suggests upside is concentrated rather than broad.")
        else:
            parts.append(f"Consensus is negative on balance at {avg_consensus:.2f}%, which keeps the group on a cautious footing.")
    elif tickers:
        dominant = max(agreement_counts, key=agreement_counts.get) if agreement_counts else "mixed"
        parts.append(f"MAG7 signals are mixed, with {dominant} model agreement the most common reading across the group.")
    return " ".join(parts[:2]).strip()


def _build_grounded_reflection(summary_payload: Dict[str, Any]) -> str:
    highlights = summary_payload.get("top_highlights", []) or []
    if not highlights:
        return "Leadership appears selective rather than broad, with conviction concentrated in a smaller set of names while the rest of the group remains less aligned."

    highlight_tickers = [
        _sanitize_text(row.get("ticker"))
        for row in highlights[:3]
        if _sanitize_text(row.get("ticker"))
    ]
    bullish_rows = [row for row in highlights[:3] if _sanitize_text(row.get("highlight_bias")).lower() == "bullish"]
    bearish_rows = [row for row in highlights[:3] if _sanitize_text(row.get("highlight_bias")).lower() == "bearish"]

    if bullish_rows and bearish_rows:
        leaders = ", ".join(_sanitize_text(r.get("ticker")) for r in bullish_rows if _sanitize_text(r.get("ticker")))
        laggards = ", ".join(_sanitize_text(r.get("ticker")) for r in bearish_rows if _sanitize_text(r.get("ticker")))
        return f"Leadership is narrow, with strength concentrated in {leaders} while {laggards} still screen weaker. That points to selective opportunity rather than broad-based tech leadership."

    if bullish_rows:
        leaders = ", ".join(_sanitize_text(r.get("ticker")) for r in bullish_rows if _sanitize_text(r.get("ticker")))
        return f"Leadership is concentrated in {leaders}, which keeps the near-term tone constructive even if conviction is not yet broad across the whole group."

    if bearish_rows:
        laggards = ", ".join(_sanitize_text(r.get("ticker")) for r in bearish_rows if _sanitize_text(r.get("ticker")))
        return f"Weakness is concentrated in {laggards}, which keeps the broader MAG7 tone cautious until leadership broadens out again."

    return "Leadership appears selective rather than broad, with conviction concentrated in a smaller set of names while the rest of the group remains less aligned."


def _sanitize_commentary_payload(summary_payload: Dict[str, Any], parsed: Dict[str, Any]) -> Dict[str, Any]:
    data = parsed if isinstance(parsed, dict) else {}
    overview = _sanitize_text(data.get("portfolio_overview"))
    reflection = _sanitize_text(data.get("market_reflection"))
    bullets = []
    for item in data.get("top_bullets", []) if isinstance(data.get("top_bullets"), list) else []:
        cleaned = _sanitize_text(item)
        if cleaned:
            bullets.append(cleaned)
    deduped_bullets: List[str] = []
    seen = set()
    for bullet in bullets:
        key = bullet.lower()
        if key in seen:
            continue
        deduped_bullets.append(bullet)
        seen.add(key)

    expected_bullets = _format_highlight_bullets(summary_payload.get("top_highlights", []) or [])
    if len(deduped_bullets) != 3 and len(expected_bullets) == 3:
        deduped_bullets = expected_bullets

    if not overview or not _overview_grounded_enough(overview, summary_payload):
        overview = _build_grounded_overview(summary_payload) or _build_fallback_overview(summary_payload)
    if not reflection or not _reflection_grounded_enough(reflection, summary_payload):
        reflection = _build_grounded_reflection(summary_payload) or _build_fallback_reflection(summary_payload)

    cleaned_notes = []
    if isinstance(data.get("ticker_notes"), list):
        for item in data.get("ticker_notes", []):
            if not isinstance(item, dict):
                continue
            ticker = _sanitize_text(item.get("ticker"))
            commentary = _sanitize_text(item.get("commentary"))
            if ticker and commentary:
                cleaned_notes.append({"ticker": ticker, "commentary": commentary})

    return {
        "portfolio_overview": overview,
        "top_bullets": deduped_bullets[:3],
        "market_reflection": reflection,
        "ticker_notes": cleaned_notes,
    }


def _payload_is_valid(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    overview = _sanitize_text(payload.get("portfolio_overview"))
    reflection = _sanitize_text(payload.get("market_reflection"))
    bullets = payload.get("top_bullets", [])
    if not isinstance(bullets, list):
        return False
    clean_bullets = [_sanitize_text(x) for x in bullets if _sanitize_text(x)]
    if not overview or not reflection or len(clean_bullets) != 3:
        return False
    return True


def generate_commentary(summary_payload: Dict[str, Any]) -> Dict[str, Any]:
    user_prompt = (
        "Generate report commentary from the following JSON.\n"
        "Use only the provided data.\n"
        "Return valid JSON only.\n"
        "Write like a market strategist, not like a model or a report template.\n"
        "portfolio_overview must summarize the full MAG7 setup using breadth, consensus, and agreement where relevant.\n"
        "Do not say 'the report indicates' or 'the highlights suggest'.\n"
        "Do not use vague phrases like market regime unless the JSON directly supports them.\n"
        "The top_bullets must be concise highlight sentences in the exact order of top_highlights.\n"
        "Each top bullet must start with Bullish or Bearish, followed by an em dash and the ticker.\n"
        "Do not turn the bullets into mini tables or metric dumps.\n"
        "market_reflection must explain what the highlighted leaders and laggards imply about the broader MAG7 tone without repeating the overview.\n\n"
        f"{json.dumps(summary_payload, indent=2)}"
    )

    last_error = None
    raw_content = ""

    try:
        for _ in range(2):
            try:
                raw_content = _post_chat(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    fmt=COMMENTARY_SCHEMA,
                    num_predict=512,
                )
                _save_debug_text("last_commentary_candidate.txt", raw_content)
                parsed = _parse_json_text(raw_content)
                sanitized = _sanitize_commentary_payload(summary_payload, parsed)
                if _payload_is_valid(sanitized):
                    return {"ok": True, "data": sanitized, "error": None}
                last_error = "schema_pass_invalid_payload"
            except Exception as e:
                last_error = f"schema_pass_failed: {type(e).__name__}: {e}"
                if raw_content:
                    _save_debug_text("raw_invalid_commentary.txt", raw_content)

        try:
            raw_content = _post_chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                fmt="json",
                num_predict=512,
            )
            _save_debug_text("last_commentary_json_mode.txt", raw_content)
            parsed = _parse_json_text(raw_content)
            sanitized = _sanitize_commentary_payload(summary_payload, parsed)
            if _payload_is_valid(sanitized):
                return {"ok": True, "data": sanitized, "error": None}
            last_error = "json_mode_invalid_payload"
        except Exception as e:
            last_error = f"json_mode_failed: {type(e).__name__}: {e}"
            if raw_content:
                _save_debug_text("raw_invalid_commentary_json_mode.txt", raw_content)

        repair_user_prompt = (
            "Fix the following malformed JSON-like text so it becomes valid JSON matching the required structure.\n\n"
            f"{raw_content}"
        )
        repaired_content = _post_chat(
            messages=[
                {"role": "system", "content": REPAIR_PROMPT},
                {"role": "user", "content": repair_user_prompt},
            ],
            fmt=COMMENTARY_SCHEMA,
            num_predict=512,
        )
        _save_debug_text("repaired_commentary.txt", repaired_content)
        parsed = _parse_json_text(repaired_content)
        sanitized = _sanitize_commentary_payload(summary_payload, parsed)
        if _payload_is_valid(sanitized):
            return {"ok": True, "data": sanitized, "error": None}
        return {"ok": False, "data": None, "error": "repair_invalid_payload"}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        if last_error:
            err = f"{last_error} | final_error: {err}"
        return {"ok": False, "data": None, "error": err}
