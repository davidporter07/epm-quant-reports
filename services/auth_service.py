"""
Auth service — SQLite user store with bcrypt hashing and JWT session tokens.

Design notes:
- Passwords are stored as bcrypt hashes only. There is no way to reverse them.
- JWTs are signed with a secret key (auto-generated and persisted in data/jwt_secret.key).
- User preferences (featured_tickers, tape_tickers) are stored as JSON in the same DB.
- Password reset tokens are stored as SHA-256 hashes — the plain token is only ever
  in memory or in the reset email link, never persisted.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt
import jwt
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "users.db"
SECRET_FILE = DATA_DIR / "jwt_secret.key"

load_dotenv(BASE_DIR / ".env", override=False)

_TOKEN_ALGORITHM = "HS256"
_TOKEN_EXPIRE_HOURS_SHORT = 72     # 3-day sessions (sessionStorage, clears on browser close)
_TOKEN_EXPIRE_HOURS_LONG  = 720    # 30-day sessions (localStorage, "Remember Me")
_RESET_TOKEN_EXPIRE_MINUTES = 15   # Password reset links expire in 15 minutes


# ---------------------------------------------------------------------------
# JWT secret — loaded from JWT_SECRET env var; falls back to file for existing
# deployments. Set JWT_SECRET in .env to avoid any file-based secret.
# ---------------------------------------------------------------------------

def _load_or_create_secret() -> str:
    env_secret = os.environ.get("JWT_SECRET", "").strip()
    if env_secret:
        return env_secret
    # Legacy: read from or create the key file
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    secret = secrets.token_hex(48)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SECRET_FILE.write_text(secret, encoding="utf-8")
    return secret


_JWT_SECRET: str = _load_or_create_secret()


# ---------------------------------------------------------------------------
# Database bootstrap + migration
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables and run migrations. Safe to call multiple times."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                pw_hash  TEXT    NOT NULL,
                email    TEXT    UNIQUE COLLATE NOCASE,
                created  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id          INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                featured_tickers TEXT NOT NULL DEFAULT '[]',
                tape_tickers     TEXT NOT NULL DEFAULT '[]',
                updated          TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT    NOT NULL UNIQUE,
                expires_at TEXT    NOT NULL,
                used       INTEGER NOT NULL DEFAULT 0,
                created    TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        # Migration: add email column to existing DBs that were created without it.
        # SQLite doesn't allow ADD COLUMN with UNIQUE, so we add without constraint
        # and enforce uniqueness via a separate partial unique index.
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        if "email" not in existing_cols:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT COLLATE NOCASE")
            conn.commit()
        # Create unique index on email if it doesn't exist yet (covers both new and migrated DBs)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
            ON users(email) WHERE email IS NOT NULL
        """)
        conn.commit()

        # Migration: add profile customisation columns to user_prefs
        existing_prefs_cols = {row[1] for row in conn.execute("PRAGMA table_info(user_prefs)")}
        if "profile_color" not in existing_prefs_cols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN profile_color TEXT NOT NULL DEFAULT '#2563eb'")
            conn.commit()
        if "profile_avatar" not in existing_prefs_cols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN profile_avatar TEXT NOT NULL DEFAULT ''")
            conn.commit()

        # Migration: add token_version for server-side session invalidation on password change
        if "token_version" not in existing_cols:
            conn.execute("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
            conn.commit()

        # Migration: daily-recap email subscription. email_opt_in = user asked to
        # receive the daily email; email_confirmed = they clicked the double-opt-in
        # link. A user only receives mail when BOTH are 1 (see get_confirmed_subscribers).
        if "email_opt_in" not in existing_prefs_cols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN email_opt_in INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        if "email_confirmed" not in existing_prefs_cols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN email_confirmed INTEGER NOT NULL DEFAULT 0")
            conn.commit()


# ---------------------------------------------------------------------------
# Shared error type
# ---------------------------------------------------------------------------

class AuthError(Exception):
    """Raised for auth-related failures with a user-visible message."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_password(plain: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

def register_user(username: str, password: str, email: str, email_opt_in: bool = False) -> dict[str, Any]:
    """Create a new user. Returns the user dict. Raises AuthError on failure.

    email_opt_in records the signup-form "email me the daily recap" checkbox. It
    only sets the opt-in flag; the user must still confirm via the double-opt-in
    link before any mail is sent (email_confirmed stays 0 here).
    """
    username = username.strip()
    email = email.strip().lower()

    if not username or len(username) < 2:
        raise AuthError("Username must be at least 2 characters.")
    if len(username) > 40:
        raise AuthError("Username too long (max 40 characters).")
    if not password or len(password) < 10:
        raise AuthError("Password must be at least 10 characters.")
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise AuthError("A valid email address is required.")

    pw_hash = _hash_password(password)
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, pw_hash, email) VALUES (?, ?, ?)",
                (username, pw_hash, email),
            )
            user_id = cur.lastrowid
            conn.execute(
                "INSERT INTO user_prefs (user_id, email_opt_in) VALUES (?, ?)",
                (user_id, 1 if email_opt_in else 0),
            )
            conn.commit()
    except sqlite3.IntegrityError as exc:
        msg = str(exc).lower()
        if "email" in msg:
            raise AuthError("An account with that email already exists.")
        raise AuthError("Username already taken.")
    return {"id": user_id, "username": username, "email": email, "token_version": 0}


def get_token_version(user_id: int) -> int:
    """Return the current token_version for a user (used to invalidate old JWTs)."""
    with _get_conn() as conn:
        row = conn.execute("SELECT token_version FROM users WHERE id = ?", (user_id,)).fetchone()
    return int(row["token_version"]) if row else 0


def verify_login(username: str, password: str) -> dict[str, Any]:
    """Verify credentials. Returns user dict on success. Raises AuthError on failure."""
    username = username.strip()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, pw_hash, token_version FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
    if row is None or not _verify_password(password, row["pw_hash"]):
        raise AuthError("Invalid username or password.", status_code=401)
    return {"id": row["id"], "username": row["username"], "token_version": int(row["token_version"])}


def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Look up a user by email address. Returns None if not found."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, email FROM users WHERE email = ? COLLATE NOCASE",
            (email.strip().lower(),),
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "username": row["username"], "email": row["email"]}


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Look up a user by id. Returns None if not found."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, email FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "username": row["username"], "email": row["email"]}


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_token(user: dict[str, Any], remember_me: bool = False) -> str:
    """
    Create a signed JWT for the given user.

    remember_me=False  → 3-day expiry  (caller stores in sessionStorage)
    remember_me=True   → 30-day expiry (caller stores in localStorage)
    """
    hours = _TOKEN_EXPIRE_HOURS_LONG if remember_me else _TOKEN_EXPIRE_HOURS_SHORT
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "tv": user.get("token_version", 0),
        "remember": remember_me,
        "iat": datetime.now(tz=timezone.utc),
        "exp": datetime.now(tz=timezone.utc) + timedelta(hours=hours),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_TOKEN_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Returns the payload. Raises AuthError if invalid."""
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_TOKEN_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AuthError("Session expired. Please log in again.", status_code=401)
    except jwt.InvalidTokenError:
        raise AuthError("Invalid session token.", status_code=401)


# ---------------------------------------------------------------------------
# Email subscription tokens (stateless — signed with the same JWT secret).
# Used for double-opt-in confirmation and one-click unsubscribe links. No DB
# table needed: the token IS the proof. `purpose` namespaces the two link types
# so a confirm token can't be replayed as an unsubscribe and vice-versa.
# ---------------------------------------------------------------------------

EMAIL_PURPOSE_CONFIRM = "email_confirm"
EMAIL_PURPOSE_UNSUB = "email_unsub"


def make_email_token(user_id: int, purpose: str, ttl_hours: int | None = None) -> str:
    """Mint a signed token for an email link. ttl_hours=None → no expiry
    (unsubscribe links must keep working indefinitely)."""
    payload: dict[str, Any] = {"sub": str(user_id), "purpose": purpose}
    if ttl_hours is not None:
        payload["exp"] = datetime.now(tz=timezone.utc) + timedelta(hours=ttl_hours)
    return jwt.encode(payload, _JWT_SECRET, algorithm=_TOKEN_ALGORITHM)


def verify_email_token(token: str, purpose: str) -> int:
    """Validate an email token for the expected purpose. Returns user_id.
    Raises AuthError if invalid, expired, or the purpose doesn't match."""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_TOKEN_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AuthError("This link has expired. Please request a new one.", status_code=400)
    except jwt.InvalidTokenError:
        raise AuthError("This link is invalid or malformed.", status_code=400)
    if payload.get("purpose") != purpose:
        raise AuthError("This link is invalid.", status_code=400)
    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise AuthError("This link is invalid.", status_code=400)


# ---------------------------------------------------------------------------
# Email subscription state
# ---------------------------------------------------------------------------

def _ensure_prefs_row(user_id: int) -> None:
    with _get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO user_prefs (user_id) VALUES (?)", (user_id,))
        conn.commit()


def set_email_opt_in(user_id: int, opted_in: bool) -> None:
    """Turn the daily-recap subscription on/off. Turning it off does NOT clear
    email_confirmed, so re-subscribing a previously confirmed address skips the
    double-opt-in step."""
    _ensure_prefs_row(user_id)
    with _get_conn() as conn:
        conn.execute(
            "UPDATE user_prefs SET email_opt_in = ? WHERE user_id = ?",
            (1 if opted_in else 0, user_id),
        )
        conn.commit()


def set_email_confirmed(user_id: int, confirmed: bool = True) -> None:
    _ensure_prefs_row(user_id)
    with _get_conn() as conn:
        conn.execute(
            "UPDATE user_prefs SET email_confirmed = ? WHERE user_id = ?",
            (1 if confirmed else 0, user_id),
        )
        conn.commit()


def get_email_subscription(user_id: int) -> dict[str, bool]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT email_opt_in, email_confirmed FROM user_prefs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return {"email_opt_in": False, "email_confirmed": False}
    return {
        "email_opt_in": bool(row["email_opt_in"]),
        "email_confirmed": bool(row["email_confirmed"]),
    }


def get_confirmed_subscribers() -> list[dict[str, Any]]:
    """All users who opted in AND confirmed AND have an email. This is the
    daily-recap recipient list, served to the laptop via the internal endpoint."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT u.id AS user_id, u.username, u.email "
            "FROM users u JOIN user_prefs p ON p.user_id = u.id "
            "WHERE p.email_opt_in = 1 AND p.email_confirmed = 1 "
            "AND u.email IS NOT NULL AND u.email != ''"
        ).fetchall()
    return [
        {"user_id": r["user_id"], "username": r["username"], "email": r["email"]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Password reset tokens
# ---------------------------------------------------------------------------

def create_reset_token(user_id: int) -> str:
    """
    Generate a one-time password reset token for the given user.
    Returns the plain token (96 hex chars). Only the SHA-256 hash is stored in the DB.
    Expires in 1 hour.
    """
    plain = secrets.token_hex(48)
    token_hash = hashlib.sha256(plain.encode()).hexdigest()
    expires_at = (datetime.now(tz=timezone.utc) + timedelta(minutes=_RESET_TOKEN_EXPIRE_MINUTES)).isoformat()

    with _get_conn() as conn:
        # Invalidate any previous unused tokens for this user
        conn.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE user_id = ? AND used = 0",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user_id, token_hash, expires_at),
        )
        conn.commit()
    return plain


def consume_reset_token(plain_token: str) -> int:
    """
    Validate a reset token and mark it as used.
    Returns the user_id if valid. Raises AuthError if invalid, expired, or already used.
    """
    token_hash = hashlib.sha256(plain_token.encode()).hexdigest()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, user_id, expires_at, used FROM password_reset_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()

        if row is None or row["used"]:
            raise AuthError("Reset link is invalid or has already been used.", status_code=400)

        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(tz=timezone.utc) > expires_at:
            raise AuthError("Reset link has expired. Please request a new one.", status_code=400)

        conn.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE id = ?",
            (row["id"],),
        )
        conn.commit()
    return row["user_id"]


def reset_password(user_id: int, new_password: str) -> None:
    """Update the password hash for a user and invalidate all existing sessions."""
    if not new_password or len(new_password) < 10:
        raise AuthError("Password must be at least 10 characters.")
    pw_hash = _hash_password(new_password)
    with _get_conn() as conn:
        conn.execute(
            "UPDATE users SET pw_hash = ?, token_version = token_version + 1 WHERE id = ?",
            (pw_hash, user_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------

def get_user_prefs(user_id: int) -> dict[str, Any]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT featured_tickers, tape_tickers, profile_color, profile_avatar, "
            "email_opt_in, email_confirmed FROM user_prefs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return {
            "featured_tickers": [], "tape_tickers": [], "profile_color": "#2563eb",
            "profile_avatar": "", "email_opt_in": False, "email_confirmed": False,
        }
    return {
        "featured_tickers": json.loads(row["featured_tickers"] or "[]"),
        "tape_tickers": json.loads(row["tape_tickers"] or "[]"),
        "profile_color": row["profile_color"] or "#2563eb",
        "profile_avatar": row["profile_avatar"] or "",
        "email_opt_in": bool(row["email_opt_in"]),
        "email_confirmed": bool(row["email_confirmed"]),
    }


def set_user_prefs(
    user_id: int,
    featured_tickers: list[str] | None = None,
    tape_tickers: list[str] | None = None,
    profile_color: str | None = None,
    profile_avatar: str | None = None,
) -> dict[str, Any]:
    """Update stored prefs. Pass None to leave a field unchanged."""
    current = get_user_prefs(user_id)
    new_featured = featured_tickers if featured_tickers is not None else current["featured_tickers"]
    new_tape = tape_tickers if tape_tickers is not None else current["tape_tickers"]
    new_color = profile_color if profile_color is not None else current["profile_color"]
    new_avatar = profile_avatar if profile_avatar is not None else current["profile_avatar"]

    new_featured = [str(t).strip().upper() for t in new_featured if str(t).strip()][:20]
    new_tape = [str(t).strip().upper() for t in new_tape if str(t).strip()][:50]
    # Sanitise color: must be a hex color or one of the known palette values
    import re as _re
    if not _re.match(r'^#[0-9a-fA-F]{6}$', new_color or ''):
        new_color = "#2563eb"
    # Sanitise avatar: allow empty string, one ASCII letter/digit, or one emoji
    # (emoji are typically 1-2 Unicode code points). Reject HTML-unsafe characters.
    _av = (new_avatar or "").strip()
    import html as _html
    _av_escaped = _html.escape(_av, quote=True)
    # Only accept if escaping didn't change it (i.e. no <, >, &, ", ')
    new_avatar = _av[:4] if _av == _av_escaped else ""

    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO user_prefs (user_id, featured_tickers, tape_tickers, profile_color, profile_avatar, updated)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                featured_tickers = excluded.featured_tickers,
                tape_tickers     = excluded.tape_tickers,
                profile_color    = excluded.profile_color,
                profile_avatar   = excluded.profile_avatar,
                updated          = excluded.updated
        """, (user_id, json.dumps(new_featured), json.dumps(new_tape), new_color, new_avatar))
        conn.commit()
    return {
        "featured_tickers": new_featured,
        "tape_tickers": new_tape,
        "profile_color": new_color,
        "profile_avatar": new_avatar,
    }


# ---------------------------------------------------------------------------
# Username change
# ---------------------------------------------------------------------------

def change_username(user_id: int, new_username: str, password: str) -> dict[str, Any]:
    """
    Change the username for a user after verifying their current password.
    Returns the updated user dict. Raises AuthError on failure.
    A new JWT must be issued by the caller since username is embedded in the token.
    """
    new_username = new_username.strip()
    if not new_username or len(new_username) < 2:
        raise AuthError("Username must be at least 2 characters.")
    if len(new_username) > 40:
        raise AuthError("Username too long (max 40 characters).")

    with _get_conn() as conn:
        row = conn.execute("SELECT pw_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or not _verify_password(password, row["pw_hash"]):
        raise AuthError("Incorrect password.", status_code=401)

    try:
        with _get_conn() as conn:
            conn.execute(
                "UPDATE users SET username = ?, token_version = token_version + 1 WHERE id = ?",
                (new_username, user_id),
            )
            conn.commit()
            row = conn.execute("SELECT token_version FROM users WHERE id = ?", (user_id,)).fetchone()
    except sqlite3.IntegrityError:
        raise AuthError("That username is already taken.")
    return {"id": user_id, "username": new_username, "token_version": int(row["token_version"]) if row else 0}


# Initialize DB on import
init_db()
