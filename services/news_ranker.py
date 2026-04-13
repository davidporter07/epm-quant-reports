from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import math
import re


CATALYST_KEYWORDS = {
    "earnings": 2.5,
    "guidance": 2.5,
    "acquisition": 2.0,
    "merger": 2.0,
    "lawsuit": 1.8,
    "investigation": 1.8,
    "approval": 2.2,
    "downgrade": 1.7,
    "upgrade": 1.7,
    "forecast": 1.5,
    "outlook": 1.5,
    "dividend": 1.2,
    "buyback": 1.4,
    "layoffs": 1.4,
    "flows": 1.8,
    "inflows": 1.8,
    "outflows": 1.8,
    "rebalance": 1.5,
}

def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None

def _hours_old(value: str | None) -> float | None:
    dt = _parse_dt(value)
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max((now - dt).total_seconds() / 3600.0, 0.0)

def _keyword_score(text: str) -> float:
    text_l = text.lower()
    score = 0.0
    for kw, weight in CATALYST_KEYWORDS.items():
        if kw in text_l:
            score += weight
    return score

def _mention_score(text: str, ticker: str, name: str | None) -> float:
    score = 0.0
    text_l = text.lower()
    if ticker.lower() in text_l:
        score += 1.5
    if name:
        for token in re.split(r"[^a-zA-Z0-9]+", name.lower()):
            if len(token) >= 4 and token in text_l:
                score += 0.3
    return min(score, 2.0)

def rank_news(items: list[dict[str, Any]], ticker: str, name: str | None = None) -> list[dict[str, Any]]:
    ranked = []
    seen_titles = set()

    for item in items:
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        full_text = f"{title} {summary}".strip()

        if not title:
            continue

        title_key = title.lower()
        duplicate_penalty = 2.0 if title_key in seen_titles else 0.0
        seen_titles.add(title_key)

        age_hours = _hours_old(item.get("date"))
        if age_hours is None:
            recency_score = 0.5
        else:
            recency_score = max(0.0, 4.0 - math.log1p(age_hours))

        score = (
            recency_score
            + _keyword_score(full_text)
            + _mention_score(full_text, ticker=ticker, name=name)
            + (0.5 if len(summary) > 120 else 0.0)
            - duplicate_penalty
        )

        ranked.append({
            **item,
            "score": round(score, 2),
            "age_hours": None if age_hours is None else round(age_hours, 1),
        })

    ranked.sort(key=lambda x: x.get("score", 0), reverse=True)
    return ranked