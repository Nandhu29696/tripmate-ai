"""User accounts: password hashing, the user store and one-time email tokens.

Two sign-in methods share one ``users`` table: email + password and Google
(identified by the stable ``google_sub``). A user id is the owner id used by
the trip registry, so trips follow the person across devices.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

import config

# ---------------------------------------------------------------------------
# Passwords: scrypt from the standard library (memory-hard, no extra dependency)
# ---------------------------------------------------------------------------
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_PASSWORD_MAX = 128
_COMMON_PASSWORDS = {
    "password", "password1", "password123", "1234567890", "12345678910", "qwertyuiop",
    "qwerty12345", "iloveyou123", "letmein1234", "welcome1234", "admin12345", "abc1234567",
}
# Sessions issued within this many seconds of account creation stay valid even if
# clocks differ slightly.
_CLOCK_MARGIN_SECONDS = 5
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def validate_email(email: str) -> str | None:
    """Return an error message, or None when the address looks valid."""
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return "Please enter a valid email address."
    return None


def validate_password(password: str, email: str = "") -> str | None:
    """Return an error message, or None when the password is acceptable."""
    if len(password) < config.MIN_PASSWORD_LENGTH:
        return f"Use at least {config.MIN_PASSWORD_LENGTH} characters for your password."
    if len(password) > _PASSWORD_MAX:
        return f"Use at most {_PASSWORD_MAX} characters for your password."
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS or (email and lowered == email.lower()):
        return "That password is too easy to guess. Please choose another."
    if len(set(password)) < 4:
        return "That password is too repetitive. Please choose another."
    return None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. Always does the same work, even with no stored hash."""
    if not stored:
        _DUMMY_VERIFY()
        return False
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(candidate, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def _DUMMY_VERIFY() -> None:  # noqa: N802 - burns the same CPU as a real check
    hashlib.scrypt(b"dummy", salt=b"0" * 16, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)


# ---------------------------------------------------------------------------
# One-time email tokens (only a hash is stored)
# ---------------------------------------------------------------------------
def new_token() -> tuple[str, str]:
    """Return (token_for_the_link, hash_to_store)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# User store
# ---------------------------------------------------------------------------
class DuplicateEmailError(ValueError):
    """An account with this email already exists."""


class UserStore(Protocol):
    def create_user(self, email: str, name: str = "", password_hash: str | None = None,
                    google_sub: str | None = None, email_verified: bool = False) -> dict[str, Any]: ...
    def get(self, user_id: str) -> dict[str, Any] | None: ...
    def get_by_email(self, email: str) -> dict[str, Any] | None: ...
    def get_by_google_sub(self, sub: str) -> dict[str, Any] | None: ...
    def get_password_hash(self, user_id: str) -> str | None: ...
    def mark_verified(self, user_id: str) -> None: ...
    def set_password(self, user_id: str, password_hash: str | None, revoke_sessions: bool = True) -> None: ...
    def link_google(self, user_id: str, sub: str, name: str = "") -> None: ...
    def touch_login(self, user_id: str) -> None: ...
    def add_token(self, user_id: str, purpose: str, token_hash: str, ttl_seconds: int) -> None: ...
    def consume_token(self, token_hash: str, purpose: str) -> str | None: ...
    def delete_user(self, user_id: str) -> None: ...
    def list_users(self, query: str = "", limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]: ...
    def set_role(self, user_id: str, role: str) -> None: ...
    def set_active(self, user_id: str, active: bool) -> None: ...
    def revoke_sessions(self, user_id: str) -> None: ...
    def user_counts(self) -> dict[str, int]: ...


ROLES = ("user", "admin")


_USER_DDL = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id                   TEXT PRIMARY KEY,
        email                TEXT NOT NULL UNIQUE,
        email_verified       BOOLEAN NOT NULL DEFAULT FALSE,
        password_hash        TEXT,
        google_sub           TEXT UNIQUE,
        name                 TEXT NOT NULL DEFAULT '',
        is_active            BOOLEAN NOT NULL DEFAULT TRUE,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_login           TIMESTAMPTZ,
        sessions_valid_after TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL,
        purpose    TEXT NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        used_at    TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS auth_tokens_user_idx ON auth_tokens (user_id, purpose)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'",
)

_USER_COLUMNS = (
    "id, email, email_verified, (password_hash IS NOT NULL) AS has_password, "
    "(google_sub IS NOT NULL) AS has_google, name, role, is_active, created_at, last_login, "
    "extract(epoch FROM sessions_valid_after) AS sessions_valid_after"
)


def _public(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    out["sessions_valid_after"] = float(out["sessions_valid_after"])
    for key in ("created_at", "last_login"):
        if hasattr(out.get(key), "isoformat"):
            out[key] = out[key].isoformat()
    return out


class PostgresUserStore:
    def __init__(self, pool) -> None:
        self._pool = pool

    def ensure_schema(self) -> None:
        with self._pool.connection() as conn:
            for statement in _USER_DDL:  # one statement per call (extended protocol)
                conn.execute(statement)

    def _one(self, where: str, params: tuple) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            row = conn.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE {where}", params).fetchone()
        return _public(row)

    def create_user(self, email, name="", password_hash=None, google_sub=None, email_verified=False):
        import psycopg.errors

        user_id = f"usr_{uuid.uuid4().hex}"
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    "INSERT INTO users (id, email, name, password_hash, google_sub, email_verified, "
                    "sessions_valid_after) VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s))",
                    (user_id, email, name[:80], password_hash, google_sub, email_verified,
                     time.time() - _CLOCK_MARGIN_SECONDS),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateEmailError(email) from exc
        return self.get(user_id)  # type: ignore[return-value]

    def get(self, user_id):
        return self._one("id = %s", (user_id,))

    def get_by_email(self, email):
        return self._one("email = %s", (email,))

    def get_by_google_sub(self, sub):
        return self._one("google_sub = %s", (sub,))

    def get_password_hash(self, user_id):
        with self._pool.connection() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
        return row["password_hash"] if row else None

    def _exec(self, sql: str, params: tuple) -> None:
        with self._pool.connection() as conn:
            conn.execute(sql, params)

    def mark_verified(self, user_id):
        self._exec("UPDATE users SET email_verified = TRUE WHERE id = %s", (user_id,))

    def set_password(self, user_id, password_hash, revoke_sessions=True):
        if revoke_sessions:
            # App clock (not the DB's now()): session tokens carry the app's issue time.
            self._exec(
                "UPDATE users SET password_hash = %s, sessions_valid_after = to_timestamp(%s) WHERE id = %s",
                (password_hash, time.time(), user_id),
            )
        else:
            self._exec("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))

    def link_google(self, user_id, sub, name=""):
        self._exec(
            "UPDATE users SET google_sub = %s, email_verified = TRUE, "
            "name = CASE WHEN name = '' THEN %s ELSE name END WHERE id = %s",
            (sub, name[:80], user_id),
        )

    def touch_login(self, user_id):
        self._exec("UPDATE users SET last_login = now() WHERE id = %s", (user_id,))

    def add_token(self, user_id, purpose, token_hash, ttl_seconds):
        self._exec(
            "INSERT INTO auth_tokens (token_hash, user_id, purpose, expires_at) "
            "VALUES (%s, %s, %s, now() + make_interval(secs => %s))",
            (token_hash, user_id, purpose, ttl_seconds),
        )

    def consume_token(self, token_hash, purpose):
        with self._pool.connection() as conn:
            row = conn.execute(
                "UPDATE auth_tokens SET used_at = now() WHERE token_hash = %s AND purpose = %s "
                "AND used_at IS NULL AND expires_at > now() RETURNING user_id",
                (token_hash, purpose),
            ).fetchone()
        return row["user_id"] if row else None

    def delete_user(self, user_id):
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM auth_tokens WHERE user_id = %s", (user_id,))
            conn.execute("DELETE FROM users WHERE id = %s", (user_id,))

    def list_users(self, query="", limit=50, offset=0):
        like = f"%{query.strip().lower()}%"
        with self._pool.connection() as conn:
            total = conn.execute(
                "SELECT count(*) AS n FROM users WHERE lower(email) LIKE %s OR lower(name) LIKE %s", (like, like)
            ).fetchone()["n"]
            rows = conn.execute(
                f"SELECT {_USER_COLUMNS} FROM users WHERE lower(email) LIKE %s OR lower(name) LIKE %s "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (like, like, limit, offset),
            ).fetchall()
        return [_public(r) for r in rows], total

    def set_role(self, user_id, role):
        self._exec("UPDATE users SET role = %s WHERE id = %s", (role, user_id))

    def set_active(self, user_id, active):
        # Disabling also ends every session that exists right now.
        self._exec(
            "UPDATE users SET is_active = %s, sessions_valid_after = to_timestamp(%s) WHERE id = %s",
            (active, time.time(), user_id),
        )

    def revoke_sessions(self, user_id):
        self._exec("UPDATE users SET sessions_valid_after = to_timestamp(%s) WHERE id = %s", (time.time(), user_id))

    def user_counts(self):
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) AS total, count(*) FILTER (WHERE email_verified) AS verified, "
                "count(*) FILTER (WHERE role = 'admin') AS admins, "
                "count(*) FILTER (WHERE NOT is_active) AS disabled, "
                "count(*) FILTER (WHERE created_at > now() - interval '7 days') AS new_7d, "
                "count(*) FILTER (WHERE google_sub IS NOT NULL) AS google "
                "FROM users"
            ).fetchone()
        return {k: int(v) for k, v in row.items()}

    def purge_expired_tokens(self) -> None:
        self._exec("DELETE FROM auth_tokens WHERE expires_at < now() - interval '7 days'", ())


class InMemoryUserStore:
    """Test double with the same behaviour as the Postgres store."""

    def __init__(self) -> None:
        self._users: dict[str, dict[str, Any]] = {}
        self._tokens: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _view(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row["id"], "email": row["email"], "email_verified": row["email_verified"],
            "has_password": row["password_hash"] is not None, "has_google": row["google_sub"] is not None,
            "name": row["name"], "role": row.get("role", "user"), "is_active": row["is_active"],
            "created_at": row["created_at"].isoformat(), "last_login": row["last_login"],
            "sessions_valid_after": row["sessions_valid_after"],
        }

    def create_user(self, email, name="", password_hash=None, google_sub=None, email_verified=False):
        with self._lock:
            if any(u["email"] == email for u in self._users.values()):
                raise DuplicateEmailError(email)
            user_id = f"usr_{uuid.uuid4().hex}"
            self._users[user_id] = {
                "id": user_id, "email": email, "name": name[:80], "password_hash": password_hash,
                "google_sub": google_sub, "email_verified": email_verified, "is_active": True,
                "created_at": datetime.now(UTC), "last_login": None,
                "sessions_valid_after": time.time() - _CLOCK_MARGIN_SECONDS,
            }
            return self._view(self._users[user_id])  # type: ignore[return-value]

    def get(self, user_id):
        return self._view(self._users.get(user_id))

    def get_by_email(self, email):
        return self._view(next((u for u in self._users.values() if u["email"] == email), None))

    def get_by_google_sub(self, sub):
        return self._view(next((u for u in self._users.values() if u["google_sub"] == sub), None))

    def mark_verified(self, user_id):
        self._users[user_id]["email_verified"] = True

    def set_password(self, user_id, password_hash, revoke_sessions=True):
        self._users[user_id]["password_hash"] = password_hash
        if revoke_sessions:
            self._users[user_id]["sessions_valid_after"] = time.time()

    def link_google(self, user_id, sub, name=""):
        user = self._users[user_id]
        user["google_sub"], user["email_verified"] = sub, True
        if not user["name"]:
            user["name"] = name[:80]

    def touch_login(self, user_id):
        self._users[user_id]["last_login"] = datetime.now(UTC).isoformat()

    def add_token(self, user_id, purpose, token_hash, ttl_seconds):
        self._tokens[token_hash] = {
            "user_id": user_id, "purpose": purpose, "expires": time.time() + ttl_seconds, "used": False,
        }

    def consume_token(self, token_hash, purpose):
        with self._lock:
            row = self._tokens.get(token_hash)
            if not row or row["purpose"] != purpose or row["used"] or row["expires"] <= time.time():
                return None
            row["used"] = True
            return row["user_id"]

    def delete_user(self, user_id):
        self._users.pop(user_id, None)
        for key in [k for k, v in self._tokens.items() if v["user_id"] == user_id]:
            del self._tokens[key]

    def get_password_hash(self, user_id):
        row = self._users.get(user_id)
        return row["password_hash"] if row else None

    def list_users(self, query="", limit=50, offset=0):
        needle = query.strip().lower()
        rows = [u for u in self._users.values() if needle in u["email"].lower() or needle in u["name"].lower()]
        rows.sort(key=lambda u: u["created_at"], reverse=True)
        return [self._view(r) for r in rows[offset: offset + limit]], len(rows)

    def set_role(self, user_id, role):
        self._users[user_id]["role"] = role

    def set_active(self, user_id, active):
        self._users[user_id]["is_active"] = active
        self._users[user_id]["sessions_valid_after"] = time.time()

    def revoke_sessions(self, user_id):
        self._users[user_id]["sessions_valid_after"] = time.time()

    def user_counts(self):
        users = list(self._users.values())
        week = datetime.now(UTC).timestamp() - 7 * 86400
        return {
            "total": len(users),
            "verified": sum(1 for u in users if u["email_verified"]),
            "admins": sum(1 for u in users if u.get("role") == "admin"),
            "disabled": sum(1 for u in users if not u["is_active"]),
            "new_7d": sum(1 for u in users if u["created_at"].timestamp() > week),
            "google": sum(1 for u in users if u["google_sub"]),
        }

    # test helpers --------------------------------------------------------

    def expire_tokens(self) -> None:
        for row in self._tokens.values():
            row["expires"] = 0
