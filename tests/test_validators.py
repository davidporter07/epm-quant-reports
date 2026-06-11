"""PR G commit 1: table-driven tests for services/validators.py.

These lock CURRENT behavior verbatim before any caller migrates (C2-C4),
including the D1 env_flag edge-case changes explicitly approved 2026-06-11.
"""
import json

import pytest

from services import validators as v


# ---------------------------------------------------------------------------
# normalize_ticker
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("aapl", "AAPL"),
    ("  msft  ", "MSFT"),
    ("brk.b", "BRK.B"),
    ("BRK B", "BRKB"),          # spaces removed (app.py:752 behavior)
    ("", ""),
    (None, ""),
    (123, "123"),
])
def test_normalize_ticker_base(raw, expected):
    assert v.normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("M:PRWCX", "PRWCX"),        # YCharts mutual-fund prefix stripped
    ("m:prwcx", "M:PRWCX"),      # lowercase prefix NOT stripped (replace runs before upper — original behavior)
    ("M:VFIAX ", "VFIAX"),
    ("AAPL", "AAPL"),
    (None, ""),
])
def test_normalize_ticker_market_prefix(raw, expected):
    assert v.normalize_ticker(raw, strip_market_prefix=True) == expected


def test_normalize_ticker_matches_legacy_app_behavior():
    """The helper must be byte-equivalent to the original app.py:752 expression."""
    for raw in ("aapl", " spy ", "BRK B", "", "m:x", "M:X", "qqq "):
        legacy = str(raw or "").strip().upper().replace(" ", "")
        assert v.normalize_ticker(raw) == legacy


# ---------------------------------------------------------------------------
# deep ticker gate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("symbol,ok", [
    ("AAPL", True),
    ("A", True),
    ("ABCDEFGHIJ", True),        # 10 chars — boundary
    ("ABCDEFGHIJK", False),      # 11 chars
    ("BRK.B", False),            # dotted tickers rejected — preserved behavior (D4)
    ("aapl", False),             # input must be pre-normalized
    ("", False),
    ("AAPL ", False),
])
def test_is_valid_deep_ticker(symbol, ok):
    assert v.is_valid_deep_ticker(symbol) is ok


def test_deep_ticker_re_pattern_unchanged():
    """Regex must stay exactly app.py:2795's pattern (regression pin)."""
    assert v.DEEP_TICKER_RE.pattern == r"^[A-Z]{1,10}$"


# ---------------------------------------------------------------------------
# auth field rules — error messages must stay byte-identical to AuthError text
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("username,error", [
    ("ab", None),
    ("a" * 40, None),
    ("a", "Username must be at least 2 characters."),
    ("", "Username must be at least 2 characters."),
    ("a" * 41, "Username too long (max 40 characters)."),
])
def test_validate_username(username, error):
    assert v.validate_username(username) == error


@pytest.mark.parametrize("password,error", [
    ("a" * 10, None),
    ("a" * 9, "Password must be at least 10 characters."),
    ("", "Password must be at least 10 characters."),
])
def test_validate_password(password, error):
    assert v.validate_password(password) == error


@pytest.mark.parametrize("email,error", [
    ("a@b.com", None),
    ("user@sub.domain.org", None),
    ("", "A valid email address is required."),
    ("nodomain", "A valid email address is required."),
    ("a@b", "A valid email address is required."),        # no dot in domain
    ("a.b@c", "A valid email address is required."),      # dot only before @
])
def test_validate_email_format(email, error):
    assert v.validate_email_format(email) == error


# ---------------------------------------------------------------------------
# env_flag — D1 truth table, including the approved edge-case CHANGES
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    (" 1 ", True),
    ("0", False), ("false", False), ("no", False), ("off", False), ("OFF", False),
])
def test_env_flag_truth_table_default_off(value, expected, monkeypatch):
    monkeypatch.setenv("PRG_TEST_FLAG", value)
    assert v.env_flag("PRG_TEST_FLAG", default=False) is expected


def test_env_flag_unset_returns_default(monkeypatch):
    monkeypatch.delenv("PRG_TEST_FLAG", raising=False)
    assert v.env_flag("PRG_TEST_FLAG", default=False) is False
    assert v.env_flag("PRG_TEST_FLAG", default=True) is True


def test_env_flag_empty_returns_default(monkeypatch):
    """Empty assignment means "unset": False for default-off flags (all of
    today's enforce flags), and it can never silently disable a default-on
    flag like WATCHDOG_ENABLED."""
    monkeypatch.setenv("PRG_TEST_FLAG", "")
    assert v.env_flag("PRG_TEST_FLAG", default=False) is False
    assert v.env_flag("PRG_TEST_FLAG", default=True) is True


def test_env_flag_garbage_returns_default(monkeypatch):
    monkeypatch.setenv("PRG_TEST_FLAG", "banana")
    assert v.env_flag("PRG_TEST_FLAG", default=False) is False
    assert v.env_flag("PRG_TEST_FLAG", default=True) is True


# --- D1 approved behavior CHANGES (each was an operator footgun) -------------

def test_d1_change_send_require_pdf_true_now_enables(monkeypatch):
    """SEND_REQUIRE_PDF=true: OLD parsing (== "1") silently ignored it (False);
    NEW canonical parsing enables it (True). Approved 2026-06-11."""
    monkeypatch.setenv("SEND_REQUIRE_PDF", "true")
    assert v.env_flag("SEND_REQUIRE_PDF", default=False) is True


def test_d1_change_rate_limit_enforce_off_now_disables(monkeypatch):
    """RATE_LIMIT_ENFORCE=off: OLD parsing (not in ("","0","false")) treated it
    as ENABLED (True); NEW canonical parsing disables it (False). Approved
    2026-06-11."""
    monkeypatch.setenv("RATE_LIMIT_ENFORCE", "off")
    assert v.env_flag("RATE_LIMIT_ENFORCE", default=False) is False


def test_d1_change_rate_limit_enforce_no_now_disables(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENFORCE", "no")
    assert v.env_flag("RATE_LIMIT_ENFORCE", default=False) is False


def test_d1_change_data_freshness_enforce_true_now_enables(monkeypatch):
    monkeypatch.setenv("DATA_FRESHNESS_ENFORCE", "true")
    assert v.env_flag("DATA_FRESHNESS_ENFORCE", default=False) is True


def test_d1_change_watchdog_false_now_disables(monkeypatch):
    """WATCHDOG_ENABLED=false: OLD parsing (== "0") kept it running; NEW
    canonical parsing disables it — "false" now means what it says."""
    monkeypatch.setenv("WATCHDOG_ENABLED", "false")
    assert v.env_flag("WATCHDOG_ENABLED", default=True) is False


def test_documented_values_unchanged(monkeypatch):
    """The only values .env.example documents (0/1) behave exactly as before
    for every flag — zero production impact."""
    for flag, default in (
        ("RATE_LIMIT_ENFORCE", False),
        ("SEND_REQUIRE_PDF", False),
        ("DATA_FRESHNESS_ENFORCE", False),
        ("WATCHDOG_ENABLED", True),
    ):
        monkeypatch.setenv(flag, "1")
        assert v.env_flag(flag, default=default) is True
        monkeypatch.setenv(flag, "0")
        assert v.env_flag(flag, default=default) is False


# ---------------------------------------------------------------------------
# read_json_artifact
# ---------------------------------------------------------------------------

def test_read_json_artifact_ok(tmp_path):
    p = tmp_path / "artifact.json"
    p.write_text(json.dumps({"date": "2026-06-11", "ok": True}), encoding="utf-8")
    doc, status = v.read_json_artifact(p)
    assert status == "ok"
    assert doc == {"date": "2026-06-11", "ok": True}


def test_read_json_artifact_missing(tmp_path):
    doc, status = v.read_json_artifact(tmp_path / "nope.json")
    assert (doc, status) == (None, "missing")


def test_read_json_artifact_malformed(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("NOT JSON {", encoding="utf-8")
    doc, status = v.read_json_artifact(p)
    assert (doc, status) == (None, "malformed")


@pytest.mark.parametrize("payload", ["[1, 2, 3]", '"a string"', "42", "null"])
def test_read_json_artifact_non_dict_is_malformed(tmp_path, payload):
    p = tmp_path / "nondict.json"
    p.write_text(payload, encoding="utf-8")
    doc, status = v.read_json_artifact(p)
    assert (doc, status) == (None, "malformed")


def test_read_json_artifact_never_raises_on_weird_path():
    doc, status = v.read_json_artifact("\0invalid\0path")
    assert doc is None
    assert status in ("missing", "malformed")
