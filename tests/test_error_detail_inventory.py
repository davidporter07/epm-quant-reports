"""PR G commit 5: freeze the `detail=str(exc)` site count in app.py.

8 of the current 13 sites are blanket `except Exception` handlers on data
endpoints that leak internal exception text (yfinance errors, file paths) to
API clients. Fixing them is DEFERRED (decision D2, 2026-06-11) because the
frontend may display detail text verbatim — a frontend audit must come first.

Until then this lint ratchets the count: ADDING a new `detail=str(exc)` site
fails CI. When D2 lands and sites are converted to controlled messages, lower
EXPECTED_COUNT accordingly (the assert is two-sided so removals are also
acknowledged deliberately).
"""
import re
from pathlib import Path

APP_PY = Path(__file__).resolve().parent.parent / "app.py"

# 13 as of PR G (2026-06-11): 5 AuthError pass-throughs (controlled messages,
# acceptable) + 8 blanket except-Exception data endpoints (the D2 leak sites).
EXPECTED_COUNT = 13


def test_detail_str_exc_count_is_frozen():
    src = APP_PY.read_text(encoding="utf-8")
    sites = re.findall(r"detail=str\(exc\)", src)
    assert len(sites) == EXPECTED_COUNT, (
        f"app.py has {len(sites)} `detail=str(exc)` sites, expected {EXPECTED_COUNT}.\n"
        "If you ADDED one: don't — raw exception text leaks internals to API "
        "clients; raise HTTPException with a controlled message instead.\n"
        "If you REMOVED one (D2 cleanup): great — update EXPECTED_COUNT here."
    )
