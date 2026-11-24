"""Shared fixtures: no network, no database, no real LLM."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Must be set before `config` is imported anywhere.
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ["SESSION_SECRET"] = "test-secret-test-secret-test-secret"
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""
os.environ["SMTP_HOST"] = ""

# A stand-in for `npm run build`, so the backend tests do not need Node.
import tempfile  # noqa: E402

FAKE_DIST = Path(tempfile.mkdtemp(prefix="tripmate-dist-"))
(FAKE_DIST / "assets").mkdir()
(FAKE_DIST / "index.html").write_text(
    '<!doctype html><html><head><title>TripMate AI</title></head><body><div id="root"></div>'
    '<script type="module" src="/assets/app-abc123.js"></script></body></html>',
    encoding="utf8",
)
(FAKE_DIST / "assets" / "app-abc123.js").write_text("console.log('app');", encoding="utf8")
(FAKE_DIST / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf8")
os.environ["FRONTEND_DIST"] = str(FAKE_DIST)
os.environ["DATABASE_URL"] = "postgresql://unused:unused@127.0.0.1:1/unused"

import backend  # noqa: E402
import config  # noqa: E402
import mailer  # noqa: E402
import mcp_client  # noqa: E402
import security  # noqa: E402
from accounts import InMemoryUserStore  # noqa: E402
from store import InMemoryThreadRegistry  # noqa: E402

ALL_AGENTS = ["flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent"]


class FakeLLM:
    """Scripted stand-in for ChatGroq. Records every prompt it receives."""

    def __init__(self):
        self.calls = []
        self.supervisor = self.default_supervisor
        self.fail_with = None
        self.finish_reason = {}

    @staticmethod
    def default_supervisor(_prompt):
        return json.dumps(
            {
                "allowed": True,
                "reason": "",
                "selected_agents": ALL_AGENTS,
                "trip_constraints": {
                    "destination": "Japan",
                    "destination_city": "Tokyo",
                    "origin": "Bangladesh",
                    "origin_city": "Dhaka",
                    "duration": "7 days",
                    "dates": "October",
                    "budget": "mid-range",
                    "travel_style": "culture",
                    "special_preferences": ["food"],
                },
                "reasoning": "Full plan requested.",
            }
        )

    def invoke(self, messages, max_tokens=None):
        system, user = messages[0].content, messages[1].content
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if self.fail_with:
            raise self.fail_with
        if "supervisor and input guardrail" in system:
            text = self.supervisor(user)
        elif "flight planner" in system:
            text = "FLIGHT GUIDANCE"
        elif "budget analyst" in system:
            text = "BUDGET ANALYSIS"
        elif "expert travel planner" in system:
            text = "DRAFT ITINERARY"
        elif "booking assistant" in system:
            text = "FINAL PLAN"
        else:
            text = "Tokyo"
        finish = {"finish_reason": self.finish_reason.get(system.split('.')[0])} if self.finish_reason else {}
        return SimpleNamespace(content=text, usage_metadata={}, response_metadata=finish)


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(config, "get_llm", lambda: fake)
    return fake


@pytest.fixture
def mcp_calls(monkeypatch):
    """Fake MCP tools; returns the list of recorded calls."""
    calls = []

    def record(name, result):
        def fn(*args, **kwargs):
            calls.append((name, args, kwargs))
            if isinstance(result, Exception):
                raise result
            return result

        return fn

    monkeypatch.setattr(mcp_client, "tavily_search", record("tavily", "HOTEL DATA"))
    monkeypatch.setattr(mcp_client, "aviation_call", record("aviation", '{"data":[{"flight":"NH 846"}]}'))
    monkeypatch.setattr(mcp_client, "weather_current", record("weather_current", {"temp": 18}))
    monkeypatch.setattr(mcp_client, "weather_forecast", record("weather_forecast", {"daily_forecast": []}))
    return calls


@pytest.fixture
def wired(llm, mcp_calls):
    """Backend wired to an in-memory checkpointer and thread registry."""
    from langgraph.checkpoint.memory import InMemorySaver

    registry = InMemoryThreadRegistry()
    users = InMemoryUserStore()
    backend.init_backend_for_tests(InMemorySaver(), registry, users)
    yield SimpleNamespace(llm=llm, mcp=mcp_calls, registry=registry, users=users)
    backend._travel_graph = backend._checkpointer = backend._registry = backend._users = None


@pytest.fixture(autouse=True)
def fresh_limiters(monkeypatch):
    monkeypatch.setattr(security, "plan_limiter", security.SlidingWindowLimiter(5, 3600))
    monkeypatch.setattr(security, "daily_limiter", security.SlidingWindowLimiter(300, 86400))
    monkeypatch.setattr(security, "login_failures_ip", security.SlidingWindowLimiter(10, 900))
    monkeypatch.setattr(security, "login_failures_email", security.SlidingWindowLimiter(5, 900))
    monkeypatch.setattr(security, "register_limiter", security.SlidingWindowLimiter(5, 3600))
    monkeypatch.setattr(security, "forgot_limiter", security.SlidingWindowLimiter(3, 3600))
    monkeypatch.setattr(security, "forgot_ip_limiter", security.SlidingWindowLimiter(10, 3600))
    monkeypatch.setattr(security, "resend_limiter", security.SlidingWindowLimiter(3, 3600))


@pytest.fixture(autouse=True)
def fresh_flight_state(monkeypatch):
    monkeypatch.setattr(backend, "_routes_endpoint_available", True)
    backend._route_cache.clear()


@pytest.fixture
def mailbox(monkeypatch):
    """Capture outgoing email synchronously instead of sending it."""
    sent = []
    monkeypatch.setattr(mailer, "_sink", lambda to, subject, body: sent.append({"to": to, "subject": subject, "body": body}))
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, body: mailer._deliver(to, subject, body))
    return sent


def signed_in_client(users, email="user@example.com", name="Test User"):
    """A TestClient holding a valid session cookie for a verified user."""
    from fastapi.testclient import TestClient

    import app as app_module

    user = users.get_by_email(email) or users.create_user(email, name, None, None, True)
    client = TestClient(app_module.app)
    client.cookies.set("tm_session", security.issue_session_token(user["id"]))
    client.user = user
    return client
