"""research_store.py — server-managed cache of web-discovered research.

Persists what the research enrichment layer (research_service.py) discovers about
a symbol so we don't re-search every deep analysis. One row per (symbol, topic):
e.g. ("PRWCX", "manager"), ("NVDA", "legal_regulatory").

A row is "fresh" when it is not past its TTL (`expires_at`) AND not flagged
`stale` (news-driven invalidation in research_service marks it stale when a
recent headline says the underlying fact changed).

Like users.db this is a SERVER-MANAGED store: it lives at the repo root and is
excluded from the laptop->server sync (post_run._SERVER_MANAGED) so the laptop
never clobbers the server's accumulated cache.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DB_PATH = Path(os.getenv("RESEARCH_DB_PATH", "research_cache.db"))
_LOCK = threading.Lock()
_INITIALIZED = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    global _INITIALIZED
    with _LOCK:
        if _INITIALIZED:
            return
        with _connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS research (
                    symbol           TEXT NOT NULL,
                    topic            TEXT NOT NULL,
                    content_json     TEXT NOT NULL,
                    source_urls_json TEXT NOT NULL DEFAULT '[]',
                    confidence       REAL NOT NULL DEFAULT 0,
                    fetched_at       TEXT NOT NULL,
                    expires_at       TEXT NOT NULL,
                    stale            INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (symbol, topic)
                )
                """
            )
            conn.commit()
        _INITIALIZED = True


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        content = json.loads(row["content_json"])
    except Exception:
        content = {}
    try:
        sources = json.loads(row["source_urls_json"])
    except Exception:
        sources = []
    return {
        "symbol":     row["symbol"],
        "topic":      row["topic"],
        "content":    content,
        "sources":    sources,
        "confidence": row["confidence"],
        "fetched_at": row["fetched_at"],
        "expires_at": row["expires_at"],
        "stale":      bool(row["stale"]),
    }


def get(symbol: str, topic: str) -> Optional[Dict[str, Any]]:
    """Return the cached row for (symbol, topic), or None if missing/expired/stale."""
    init_db()
    symbol = (symbol or "").upper()
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM research WHERE symbol=? AND topic=?", (symbol, topic)
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    if row["stale"]:
        return None
    exp = _parse(row["expires_at"])
    if exp is not None and exp < _utcnow():
        return None
    return _row_to_dict(row)


def put(
    symbol: str,
    topic: str,
    content: Any,
    sources: Optional[List[str]] = None,
    confidence: float = 0.0,
    ttl_days: float = 30.0,
) -> None:
    """Upsert a research result, clearing any prior stale flag."""
    init_db()
    symbol = (symbol or "").upper()
    now = _utcnow()
    expires = now + timedelta(days=float(ttl_days))
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO research
                    (symbol, topic, content_json, source_urls_json, confidence,
                     fetched_at, expires_at, stale)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(symbol, topic) DO UPDATE SET
                    content_json=excluded.content_json,
                    source_urls_json=excluded.source_urls_json,
                    confidence=excluded.confidence,
                    fetched_at=excluded.fetched_at,
                    expires_at=excluded.expires_at,
                    stale=0
                """,
                (
                    symbol, topic,
                    json.dumps(content, default=str),
                    json.dumps(list(sources or [])),
                    float(confidence),
                    _iso(now), _iso(expires),
                ),
            )
            conn.commit()
    except Exception:
        pass


def mark_stale(symbol: str, topics: Optional[List[str]] = None) -> int:
    """Flag cached rows stale so the next enrich() re-researches them.

    topics=None marks every topic for the symbol. Returns rows affected.
    """
    init_db()
    symbol = (symbol or "").upper()
    try:
        with _connect() as conn:
            if topics:
                qmarks = ",".join("?" for _ in topics)
                cur = conn.execute(
                    f"UPDATE research SET stale=1 WHERE symbol=? AND topic IN ({qmarks})",
                    (symbol, *topics),
                )
            else:
                cur = conn.execute("UPDATE research SET stale=1 WHERE symbol=?", (symbol,))
            conn.commit()
            return cur.rowcount
    except Exception:
        return 0


def get_fresh_for_symbol(symbol: str) -> Dict[str, Dict[str, Any]]:
    """All fresh (non-expired, non-stale) topics for a symbol, keyed by topic.

    For the read-only UI endpoint — never triggers research.
    """
    init_db()
    symbol = (symbol or "").upper()
    out: Dict[str, Dict[str, Any]] = {}
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research WHERE symbol=? AND stale=0", (symbol,)
            ).fetchall()
    except Exception:
        return out
    now = _utcnow()
    for row in rows:
        exp = _parse(row["expires_at"])
        if exp is not None and exp < now:
            continue
        out[row["topic"]] = _row_to_dict(row)
    return out
