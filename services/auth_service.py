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
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt
import jwt

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "users.db"
SECRET_FILE = DATA_DIR / "jwt_secret.key"

_TOKEN_ALGORITHM = "HS256"
_TOKEN_EXPIRE_HOURS_SHORT = 72     # 3-day sessions (sessionStorage, clears on browser close)
_TOKEN_EXPIRE_HOURS_LONG  = 720    # 30-day sessions (localStorage, "Remember Me")
_RESET_TOKEN_EXPIRE_HOURS = 1      # Password reset links expire in 1 hour


# ---------------------------------------------------------------------------
# JWT secret — auto-generated on first run, persisted across restarts
# ---------------------------------------------------------------------------

def _load_or_create_secret() -> str:
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    secret = secrets.token_hex(48)
    SECRET_FILE.write_text(secret, encoding="utf-8")
    return secret


_JWT_SECRET: str = _load_or_create_secret()


# ---------------------------------------------------------------------------
# Database bootstrap + migration
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
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

def register_user(username: str, password: str, email: str) -> dict[str, Any]:
    """Create a new user. Returns the user dict. Raises AuthError on failure."""
    username = username.strip()
    email = email.strip().lower()

    if not username or len(username) < 2:
        raise AuthError("Username must be at least 2 characters.")
    if len(username) > 40:
        raise AuthError("Username too long (max 40 characters).")
    if not password or len(password) < 6:
        raise AuthError("Password must be at least 6 characters.")
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
            conn.execute("INSERT INTO user_prefs (user_id) VALUES (?)", (user_id,))
            conn.commit()
    except sqlite3.IntegrityError as exc:
        msg = str(exc).lower()
        if "email" in msg:
            raise AuthError("An account with that email already exists.")
        raise AuthError("Username already taken.")
    return {"id": user_id, "username": username, "email": email}


def verify_login(username: str, password: str) -> dict[str, Any]:
    """Verify credentials. Returns user dict on success. Raises AuthError on failure."""
    username = username.strip()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, pw_hash FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
    if row is None or not _verify_password(password, row["pw_hash"]):
        raise AuthError("Invalid username or password.", status_code=401)
    return {"id": row["id"], "username": row["username"]}


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
    expires_at = (datetime.now(tz=timezone.utc) + timedelta(hours=_RESET_TOKEN_EXPIRE_HOURS)).isoformat()

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
    """Update the password hash for a user. Raises AuthError if password too short."""
    if not new_password or len(new_password) < 6:
        raise AuthError("Password must be at least 6 characters.")
    pw_hash = _hash_password(new_password)
    with _get_conn() as conn:
        conn.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (pw_hash, user_id))
        conn.commit()


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------

def get_user_prefs(user_id: int) -> dict[str, Any]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT featured_tickers, tape_tickers, profile_color, profile_avatar FROM user_prefs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return {"featured_tickers": [], "tape_tickers": [], "profile_color": "#2563eb", "profile_avatar": ""}
    return {
        "featured_tickers": json.loads(row["featured_tickers"] or "[]"),
        "tape_tickers": json.loads(row["tape_tickers"] or "[]"),
        "profile_color": row["profile_color"] or "#2563eb",
        "profile_avatar": row["profile_avatar"] or "",
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
    # Sanitise avatar: allow empty, a single letter/symbol, or up to 2 chars (emoji)
    new_avatar = (new_avatar or "")[:4]

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
            conn.execute("UPDATE users SET username = ? WHERE id = ?", (new_username, user_id))
            conn.commit()
    except sqlite3.IntegrityError:
        raise AuthError("That username is already taken.")
    return {"id": user_id, "username": new_username}


# Initialize DB on import
init_db()
