"""validators.py — central home for scattered validation rules (PR G).

Each function documents the file:line it was extracted from so the rule's
provenance is auditable. stdlib-only, no app imports — safely importable from
the web app, the laptop pipeline, and tests alike.

Conventions:
- Field validators return an error message (str) or None. The CALLER decides
  the exception type (AuthError, HTTPException, ...) so no behavior moves when
  a rule is extracted here.
- read_json_artifact never raises (mirrors services/data_freshness._load_json
  and services/send_ledger.load_ledger).
- env_flag implements decision D1 (2026-06-11): one canonical truthy/falsey
  set for every boolean flag, replacing four divergent parsing idioms.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional, Tuple

# ---------------------------------------------------------------------------
# Tickers
# ---------------------------------------------------------------------------

def normalize_ticker(raw: Any, *, strip_market_prefix: bool = False) -> str:
    """Canonical web-surface ticker normalization.

    Extracted from app.py:_normalize_symbol (strip/upper/de-space) and the
    base line of services/market_board_service.MarketBoardService._normalize_symbol
    (which additionally strips the YCharts "M:" prefix — replace happens BEFORE
    upper-casing, matching the original, so a lowercase "m:" is NOT stripped).

    Share-class suffix handling (BRK-B → BRK.B etc.) intentionally stays at the
    call sites — market_board and openbb_provider apply DIFFERENT suffix rules.
    """
    value = str(raw or "")
    if strip_market_prefix:
        value = value.replace("M:", "")
    return value.strip().upper().replace(" ", "")


# Extracted from app.py:2795. Used by the deep-analysis endpoints. NOTE: this
# deliberately rejects dotted tickers (BRK.B) — existing product behavior,
# preserved verbatim (PR G decision D4: broadening is a future product call).
DEEP_TICKER_RE = re.compile(r"^[A-Z]{1,10}$")


def is_valid_deep_ticker(symbol: str) -> bool:
    """True when symbol matches the deep-analysis ticker gate (already-normalized input)."""
    return bool(DEEP_TICKER_RE.match(symbol))


# ---------------------------------------------------------------------------
# Auth field rules — messages must stay byte-identical to the original
# AuthError messages; tests/test_validators.py locks them.
# ---------------------------------------------------------------------------

USERNAME_MIN = 2   # services/auth_service.py:185 (register) and :545 (change_username)
USERNAME_MAX = 40  # services/auth_service.py:187 and :547
PASSWORD_MIN = 10  # services/auth_service.py:189 (register) and :449 (reset_password)


def validate_username(username: str) -> Optional[str]:
    """Rule from auth_service.register_user / change_username (was duplicated)."""
    if not username or len(username) < USERNAME_MIN:
        return "Username must be at least 2 characters."
    if len(username) > USERNAME_MAX:
        return "Username too long (max 40 characters)."
    return None


def validate_password(password: str) -> Optional[str]:
    """Rule from auth_service.register_user / reset_password (was duplicated)."""
    if not password or len(password) < PASSWORD_MIN:
        return "Password must be at least 10 characters."
    return None


def validate_email_format(email: str) -> Optional[str]:
    """Rule from auth_service.register_user:191 — deliberately the same naive
    check (full RFC validation is not a goal; the double-opt-in confirm link is
    the real verification)."""
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return "A valid email address is required."
    return None


# ---------------------------------------------------------------------------
# Environment flags — decision D1 (2026-06-11)
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSEY = frozenset({"0", "false", "no", "off"})


def env_flag(name: str, *, default: bool = False) -> bool:
    """Canonical boolean env-flag parsing. Replaces four divergent idioms:
    app.py RATE_LIMIT_ENFORCE (`not in ("","0","false")`), send_email
    SEND_REQUIRE_PDF (`== "1"`), data_freshness DATA_FRESHNESS_ENFORCE
    (`== "1"`), watchdog_service WATCHDOG_ENABLED (`== "0"` inverted).

    Semantics:
    - unset, empty, or whitespace-only → default (an empty assignment means
      "unset", so it can never silently disable a default-on flag like
      WATCHDOG_ENABLED; for every default-off flag it still reads as False)
    - value in {1,true,yes,on}  (case-insensitive) → True
    - value in {0,false,no,off} (case-insensitive) → False
    - unrecognized garbage → default (garbage never silently flips a flag)
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if not value:
        return default
    if value in _TRUTHY:
        return True
    if value in _FALSEY:
        return False
    return default


# ---------------------------------------------------------------------------
# Artifact reads
# ---------------------------------------------------------------------------

def read_json_artifact(path: Path | str) -> Tuple[Optional[dict], str]:
    """Never-raise defensive JSON artifact read for health checks and similar.

    Returns (doc, "ok") only for a parseable JSON OBJECT; otherwise
    (None, "missing") or (None, "malformed"). Non-dict JSON (list/str/number)
    is "malformed": every artifact this repo reads is an object, and callers
    immediately .get() on the result.
    """
    p = Path(path)
    try:
        if not p.exists():
            return None, "missing"
        with p.open(encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception:
        return None, "malformed"
    if not isinstance(doc, dict):
        return None, "malformed"
    return doc, "ok"
