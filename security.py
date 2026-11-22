"""Session tokens, access-key check, quotas and login throttling (F-01, F-02).

Sessions are stateless HMAC-signed tokens stored in an HttpOnly cookie. The
session id (``sid``) is the owner identity used for thread ownership.
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

import config


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    key = config.get_session_secret().encode()
    return _b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())


def new_session_id() -> str:
    return secrets.token_urlsafe(18)


def issue_session_token(sid: str | None = None, ttl: int | None = None) -> str:
    payload = _b64(
        json.dumps(
            {"sid": sid or new_session_id(), "exp": int(time.time()) + (ttl or config.SESSION_TTL_SECONDS)},
            separators=(",", ":"),
        ).encode()
    )
    return f"{payload}.{_sign(payload)}"


def verify_session_token(token: str | None) -> str | None:
    """Return the session id for a valid, unexpired token, else None."""
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

    sid = data.get("sid")
    return sid if isinstance(sid, str) and sid else None


def auth_required() -> bool:
    return bool(config.APP_ACCESS_KEY)


def access_key_matches(candidate: str) -> bool:
    expected = config.APP_ACCESS_KEY
    if not expected:
        return False
    return hmac.compare_digest(
        hashlib.sha256(candidate.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    )


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


plan_limiter = SlidingWindowLimiter(config.MAX_PLANS_PER_SESSION_PER_HOUR, 3600)
daily_limiter = SlidingWindowLimiter(config.MAX_PLANS_PER_DAY, 86400)
login_failures = SlidingWindowLimiter(5, 900)


def acquire_plan_quota(sid: str) -> int:
    """Charge one plan to the session and the global daily cap.

    Returns 0 when allowed, otherwise the number of seconds to wait.
    """
    wait = plan_limiter.try_acquire(sid)
    if wait:
        return wait

    wait = daily_limiter.try_acquire("global")
    if wait:
        # Refund is not tracked; the session slot simply expires with its window.
        return wait
    return 0
