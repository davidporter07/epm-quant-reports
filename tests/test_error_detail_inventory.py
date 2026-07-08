"""PR G commit 5 (ratchet) / PR H commit C2 (D2 cleanup): freeze the
`detail=str(exc)` site count in app.py.

As of PR H (2026-07-07) the 8 blanket `except Exception` data-endpoint sites
that leaked internal exception text (yfinance errors, file paths) are gone —
they raise via _api_error(), which journals the real exception server-side
and returns a controlled public message.

The 5 remaining sites are all AuthError pass-throughs: AuthError messages are
authored in services/auth_service.py / services/validators.py and are
user-facing BY DESIGN ("Password must be at least 10 characters.", etc.), so
str(exc) there is a controlled message, not a leak.

This lint ratchets the count: ADDING a new `detail=str(exc)` site fails CI.
Removals must also update EXPECTED_COUNT (two-sided assert) so they are
acknowledged deliberately.
"""
import re
from pathlib import Path

APP_PY = Path(__file__).resolve().parent.parent / "app.py"

# 5 as of PR H C2 (2026-07-07): AuthError pass-throughs only (controlled
# messages — decode_token dep, api_login, api_register, reset-password,
# change_username). The 8 D2 leak sites now go through _api_error().
EXPECTED_COUNT = 5


def test_detail_str_exc_count_is_frozen():
    src = APP_PY.read_text(encoding="utf-8")
    sites = re.findall(r"detail=str\(exc\)", src)
    assert len(sites) == EXPECTED_COUNT, (
        f"app.py has {len(sites)} `detail=str(exc)` sites, expected {EXPECTED_COUNT}.\n"
        "If you ADDED one: don't — raw exception text leaks internals to API "
        "clients; use _api_error() (journal + controlled public message) or a "
        "fixed HTTPException detail instead.\n"
        "If you REMOVED one: update EXPECTED_COUNT here."
    )


def test_remaining_sites_are_all_autherror_passthroughs():
    """The surviving detail=str(exc) sites must each sit inside an
    `except AuthError as exc:` block — never a blanket `except Exception`."""
    src = APP_PY.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(src):
        if "detail=str(exc)" not in line:
            continue
        window = "\n".join(src[max(0, i - 4):i])
        assert "except AuthError as exc:" in window, (
            f"app.py line {i + 1}: detail=str(exc) outside an AuthError handler:\n{window}"
        )
