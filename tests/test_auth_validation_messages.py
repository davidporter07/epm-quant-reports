"""PR G commit 3: AuthError messages must be byte-identical after the field
rules moved to services/validators.py.

These messages are part of the API contract (surfaced verbatim in HTTP detail
by api_register / api_reset_password / change-username) — locking them proves
the dedup was behavior-preserving.
"""
import pytest

try:
    import services.auth_service as auth
except Exception as exc:  # pragma: no cover - env dependent
    auth = None
    _skip = str(exc)

pytestmark = pytest.mark.skipif(auth is None, reason="auth deps unavailable")


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    db = tmp_path / "users.db"
    monkeypatch.setattr(auth, "DB_PATH", db)
    auth.init_db()
    return db


def _msg(excinfo):
    return str(excinfo.value)


# --- register_user -----------------------------------------------------------

def test_register_short_username_message(temp_db):
    with pytest.raises(auth.AuthError) as e:
        auth.register_user("a", "password12345", "a@x.com")
    assert _msg(e) == "Username must be at least 2 characters."


def test_register_long_username_message(temp_db):
    with pytest.raises(auth.AuthError) as e:
        auth.register_user("a" * 41, "password12345", "a@x.com")
    assert _msg(e) == "Username too long (max 40 characters)."


def test_register_short_password_message(temp_db):
    with pytest.raises(auth.AuthError) as e:
        auth.register_user("alice", "short", "a@x.com")
    assert _msg(e) == "Password must be at least 10 characters."


def test_register_bad_email_message(temp_db):
    with pytest.raises(auth.AuthError) as e:
        auth.register_user("alice", "password12345", "not-an-email")
    assert _msg(e) == "A valid email address is required."


def test_register_error_order_username_before_password(temp_db):
    """Multiple invalid fields → username error wins (original check order)."""
    with pytest.raises(auth.AuthError) as e:
        auth.register_user("a", "short", "bad")
    assert _msg(e) == "Username must be at least 2 characters."


def test_register_valid_still_succeeds(temp_db):
    user = auth.register_user("alice", "password12345", "alice@x.com")
    assert user["username"] == "alice"
    assert user["email"] == "alice@x.com"


# --- reset_password ----------------------------------------------------------

def test_reset_password_short_message(temp_db):
    user = auth.register_user("bob", "password12345", "bob@x.com")
    with pytest.raises(auth.AuthError) as e:
        auth.reset_password(user["id"], "short")
    assert _msg(e) == "Password must be at least 10 characters."


def test_reset_password_valid_still_succeeds(temp_db):
    user = auth.register_user("carol", "password12345", "carol@x.com")
    auth.reset_password(user["id"], "newpassword99")
    assert auth.verify_login("carol", "newpassword99")["id"] == user["id"]


# --- change_username ----------------------------------------------------------

def test_change_username_short_message(temp_db):
    user = auth.register_user("dave", "password12345", "dave@x.com")
    with pytest.raises(auth.AuthError) as e:
        auth.change_username(user["id"], "x", "password12345")
    assert _msg(e) == "Username must be at least 2 characters."


def test_change_username_long_message(temp_db):
    user = auth.register_user("erin", "password12345", "erin@x.com")
    with pytest.raises(auth.AuthError) as e:
        auth.change_username(user["id"], "x" * 41, "password12345")
    assert _msg(e) == "Username too long (max 40 characters)."


def test_change_username_valid_still_succeeds(temp_db):
    user = auth.register_user("frank", "password12345", "frank@x.com")
    updated = auth.change_username(user["id"], "franklin", "password12345")
    assert updated["username"] == "franklin"
