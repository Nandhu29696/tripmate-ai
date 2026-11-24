"""Central configuration, logging and the shared LLM client.

Everything that used to be duplicated between backend.py and mcp_client.py
(dotenv loading, certifi, Groq key checks, ChatGroq construction) lives here.
Nothing in this module connects to a network or database at import time.
"""

from __future__ import annotations

import contextvars
import logging
import os
import secrets
import uuid
from functools import lru_cache
from pathlib import Path

import certifi
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Logging with a per-request correlation id (F-28)
# ---------------------------------------------------------------------------
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging() -> None:
    """Idempotent logging setup used by the web app."""
    root = logging.getLogger()
    if getattr(root, "_tripmate_configured", False):
        return

    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
        )
    )
    root.handlers[:] = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    root._tripmate_configured = True  # type: ignore[attr-defined]


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Settings (read lazily so importing never fails)
# ---------------------------------------------------------------------------
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

LLM_TIMEOUT_SECONDS = _int("LLM_TIMEOUT_SECONDS", 60)
LLM_MAX_RETRIES = _int("LLM_MAX_RETRIES", 2)
MCP_CALL_TIMEOUT_SECONDS = _int("MCP_CALL_TIMEOUT_SECONDS", 45)

# Output budgets per stage (F-16). Live testing showed 1100/1400 truncated real
# 4-day plans; raise them further for longer trips (mind your provider's TPM).
LLM_OUTPUT_TOKENS = _int("LLM_OUTPUT_TOKENS", 1000)
LLM_OUTPUT_TOKENS_ITINERARY = _int("LLM_OUTPUT_TOKENS_ITINERARY", 2000)
LLM_OUTPUT_TOKENS_FINAL = _int("LLM_OUTPUT_TOKENS_FINAL", 2600)
LLM_MAX_INPUT_TOKENS = _int("LLM_MAX_INPUT_TOKENS", 5200)

# Reasoning models (e.g. gpt-oss) spend hidden "reasoning" tokens that count
# against max_tokens, which truncated answers in testing. A low effort keeps
# the budget for the visible answer. Set LLM_REASONING_EFFORT="" to disable.
LLM_REASONING_EFFORT = os.getenv(
    "LLM_REASONING_EFFORT", "low" if "gpt-oss" in GROQ_MODEL else ""
).strip()

MAX_REVISIONS = _int("MAX_REVISIONS", 2)

# Guardrail behaviour when the model cannot be parsed (F-08).
GUARDRAIL_FAIL_OPEN = _bool("GUARDRAIL_FAIL_OPEN", False)

# Request limits (F-09)
MAX_MESSAGE_CHARS = _int("MAX_MESSAGE_CHARS", 4000)
MAX_FEEDBACK_CHARS = _int("MAX_FEEDBACK_CHARS", 2000)

# Accounts, sessions and quotas (F-01, F-02)
SESSION_TTL_SECONDS = _int("SESSION_TTL_SECONDS", 12 * 3600)
# Per signed-in user. MAX_PLANS_PER_SESSION_PER_HOUR is the old name, still honoured.
MAX_PLANS_PER_USER_PER_HOUR = _int(
    "MAX_PLANS_PER_USER_PER_HOUR", _int("MAX_PLANS_PER_SESSION_PER_HOUR", 5)
)
MAX_PLANS_PER_DAY = _int("MAX_PLANS_PER_DAY", 300)

# Email + password accounts
MIN_PASSWORD_LENGTH = _int("MIN_PASSWORD_LENGTH", 10)
REGISTER_PER_IP_PER_HOUR = _int("REGISTER_PER_IP_PER_HOUR", 5)
FORGOT_PER_EMAIL_PER_HOUR = _int("FORGOT_PER_EMAIL_PER_HOUR", 3)
VERIFY_TOKEN_TTL_SECONDS = _int("VERIFY_TOKEN_TTL_SECONDS", 24 * 3600)
RESET_TOKEN_TTL_SECONDS = _int("RESET_TOKEN_TTL_SECONDS", 3600)

# Google sign-in (OAuth 2.0 / OpenID Connect). Leave empty to hide the button.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

# Public site URL, used for the Google redirect URI and links in emails, e.g.
# https://tripmate-ai.jagoindia.in . Falls back to the request's own URL.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

# Outgoing mail (verification and password reset). Without SMTP_HOST the
# message is written to the log instead, which is only suitable for development.
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "").strip() or SMTP_USER or "no-reply@localhost"
SMTP_STARTTLS = _bool("SMTP_STARTTLS", True)

# Data retention (F-11)
RETENTION_DAYS = _int("RETENTION_DAYS", 30)

AVIATIONSTACK_MCP_VERSION = os.getenv("AVIATIONSTACK_MCP_VERSION", "1.8.1")


def get_session_secret() -> str:
    """HMAC key for session cookies.

    Production must set SESSION_SECRET. For local development an ephemeral
    key is generated (sessions then end whenever the process restarts).
    """
    secret = os.getenv("SESSION_SECRET", "")
    if secret:
        return secret
    return _ephemeral_secret()


@lru_cache(maxsize=1)
def _ephemeral_secret() -> str:
    logging.getLogger(__name__).warning(
        "SESSION_SECRET is not set; using an ephemeral key. "
        "Set SESSION_SECRET in production."
    )
    return secrets.token_hex(32)


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. Add a PostgreSQL connection URL to .env."
        )
    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"
    return database_url


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is missing. Add {name}=your_key to the project .env file."
        )
    return value


@lru_cache(maxsize=1)
def get_llm():
    """Single shared ChatGroq client with timeout and retries (F-17)."""
    from langchain_groq import ChatGroq

    extra = {"reasoning_effort": LLM_REASONING_EFFORT} if LLM_REASONING_EFFORT else {}
    return ChatGroq(
        model=GROQ_MODEL,
        api_key=require_env("GROQ_API_KEY"),
        max_tokens=LLM_OUTPUT_TOKENS,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
        **extra,
    )
