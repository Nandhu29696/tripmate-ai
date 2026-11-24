"""Signed tokens, quotas and throttling (F-01, F-02).

Sessions and the short-lived OAuth state cookie are stateless HMAC-signed
tokens. A session token names a user id and carries its issue time, so the
server can revoke older sessions (password reset) and deactivated users.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any

import config


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    key = config.get_session_secret().encode()
    return _b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())


# ---------------------------------------------------------------------------
# Generic signed tokens
# ---------------------------------------------------------------------------
def issue_signed(data: dict[str, Any], ttl: int) -> str:
    body = {**data, "exp": int(time.time()) + ttl}
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def read_signed(token: str | None) -> dict[str, Any] | None:
    """Return the payload of a valid, unexpired token, else None."""
    if not token or "." not in token:
        return None

    payload, _, signature = token.partition(".")
    if not hmac.compare_digest(signature, _sign(payload)):
        return None

    try:
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict) or data.get("exp", 0) < time.time():
        return None
    return data


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def new_session_id() -> str:
    return secrets.token_urlsafe(18)


def issue_session_token(user_id: str, ttl: int | None = None) -> str:
    return issue_signed({"sid": user_id, "iat": time.time()}, ttl or config.SESSION_TTL_SECONDS)


def read_session_token(token: str | None) -> dict[str, Any] | None:
    data = read_signed(token)
    if not data or not isinstance(data.get("sid"), str) or not data["sid"]:
        return None
    return data


def verify_session_token(token: str | None) -> str | None:
    """Return the user id for a valid token (signature and expiry only)."""
    data = read_session_token(token)
    return data["sid"] if data else None


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
class SlidingWindowLimiter:
    """Thread-safe in-memory sliding-window counter.

    State is per process, which matches the single-worker deployment. Use a
    shared store (e.g. Redis) before running several workers.
    """

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float]:
        events = self._events[key]
        while events and events[0] <= now - self.window:
            events.popleft()
        if not events:
            self._events.pop(key, None)
            return self._events[key]
        return events

    def retry_after(self, key: str) -> int:
        """Seconds until a new event is allowed; 0 means allowed now."""
        now = time.time()
        with self._lock:
            events = self._trim(key, now)
            if len(events) < self.limit:
                return 0
            return max(1, int(events[0] + self.window - now) + 1)

    def record(self, key: str) -> None:
        with self._lock:
            self._events[key].append(time.time())

    def try_acquire(self, key: str) -> int:
        """Record an event if allowed. Returns 0, or seconds to wait."""
        now = time.time()
        with self._lock:
            events = self._trim(key, now)
            if len(events) >= self.limit:
                return max(1, int(events[0] + self.window - now) + 1)
            events.append(now)
            return 0


plan_limiter = SlidingWindowLimiter(config.MAX_PLANS_PER_USER_PER_HOUR, 3600)
daily_limiter = SlidingWindowLimiter(config.MAX_PLANS_PER_DAY, 86400)
# Failed password attempts, counted separately per IP and per account email.
login_failures_ip = SlidingWindowLimiter(10, 900)
login_failures_email = SlidingWindowLimiter(5, 900)
register_limiter = SlidingWindowLimiter(config.REGISTER_PER_IP_PER_HOUR, 3600)
forgot_limiter = SlidingWindowLimiter(config.FORGOT_PER_EMAIL_PER_HOUR, 3600)
forgot_ip_limiter = SlidingWindowLimiter(10, 3600)
resend_limiter = SlidingWindowLimiter(3, 3600)


def acquire_plan_quota(user_id: str) -> int:
    """Charge one plan to the user and the global daily cap.

    Returns 0 when allowed, otherwise the number of seconds to wait.
    """
    wait = plan_limiter.try_acquire(user_id)
    if wait:
        return wait

    wait = daily_limiter.try_acquire("global")
    if wait:
        return wait
    return 0
