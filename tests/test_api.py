"""HTTP-level tests. The lifespan (real database) is not started: the backend
is wired to in-memory components by the ``wired`` fixture."""

import uuid

import groq
import httpx
import pytest
from fastapi.testclient import TestClient

import backend
import config
import security
from app import app
from tests.conftest import signed_in_client

PROMPT = "Plan a 7-day Japan trip from Dhaka in October."


def new_client() -> TestClient:
    """A client signed in as a fresh verified user."""
    return signed_in_client(backend.get_user_store(), email=f"{uuid.uuid4().hex[:10]}@example.com")


@pytest.fixture
def client(wired):
    return new_client()


# ---- pages, headers, operations ---------------------------------------------
def test_security_headers_and_no_inline_or_cdn_scripts(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]
    assert "onclick" not in response.text
    assert "cdn.jsdelivr" not in response.text and "cdnjs" not in response.text


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.json()["ready"] is True




# ---- authentication and sessions --------------------------------------------
def test_api_requires_a_session(wired):
    anonymous = TestClient(app)
    response = anonymous.post("/api/travel", json={"message": PROMPT})
    assert response.status_code == 401
    assert response.json()["success"] is False




def test_cross_origin_post_is_blocked(client):
    response = client.post(
        "/api/travel", json={"message": PROMPT}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


# ---- trip flow and ownership -------------------------------------------------
def test_full_flow_over_http(client):
    draft = client.post("/api/travel", json={"message": PROMPT}).json()
    assert draft["success"] and draft["requires_approval"]
    tid = draft["thread_id"]

    assert [t["thread_id"] for t in client.get("/api/travel/threads").json()["trips"]] == [tid]
    assert client.get(f"/api/travel/{tid}").json()["itinerary"] == "DRAFT ITINERARY"

    final = client.post("/api/travel/approve", json={"thread_id": tid, "approved": True}).json()
    assert final["status"] == "completed" and final["answer"] == "FINAL PLAN"

    again = client.post("/api/travel/approve", json={"thread_id": tid, "approved": True})
    assert again.status_code == 409

    assert client.delete(f"/api/travel/{tid}").json() == {"success": True}
    assert client.get(f"/api/travel/{tid}").status_code == 404


def test_other_session_cannot_touch_my_trip(client):
    tid = client.post("/api/travel", json={"message": PROMPT}).json()["thread_id"]
    intruder = new_client()

    assert intruder.get(f"/api/travel/{tid}").status_code == 404
    assert intruder.delete(f"/api/travel/{tid}").status_code == 404
    resumed = intruder.post("/api/travel/approve", json={"thread_id": tid, "approved": True})
    assert resumed.status_code == 404
    assert intruder.get("/api/travel/threads").json()["trips"] == []
    assert client.get(f"/api/travel/{tid}").json()["requires_approval"] is True


def test_forged_session_cookie_is_rejected(client):
    forged = TestClient(app, cookies={"tm_session": "e30.AAAA"})
    assert forged.post("/api/travel", json={"message": PROMPT}).status_code == 401


# ---- validation (F-09) -------------------------------------------------------
def test_input_validation(client):
    assert client.post("/api/travel", json={"message": "   "}).status_code == 400
    assert client.post("/api/travel", json={"message": "x" * (config.MAX_MESSAGE_CHARS + 1)}).status_code == 400
    assert client.post("/api/travel", json={}).status_code == 400

    tid = "trip_" + "a" * 32
    assert client.post("/api/travel/approve", json={"thread_id": "../etc", "approved": True}).status_code == 400
    assert client.post("/api/travel/approve", json={"thread_id": tid, "approved": False}).status_code == 400
    too_long = {"thread_id": tid, "approved": False, "feedback": "x" * (config.MAX_FEEDBACK_CHARS + 1)}
    assert client.post("/api/travel/approve", json=too_long).status_code == 400
    assert client.get("/api/travel/not-a-trip").status_code == 404


# ---- quotas and safe errors (F-01, F-07, F-17) --------------------------------
def test_plan_quota_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(security, "plan_limiter", security.SlidingWindowLimiter(1, 3600))
    assert client.post("/api/travel", json={"message": PROMPT}).status_code == 200
    limited = client.post("/api/travel", json={"message": PROMPT})
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0


def test_daily_cap_applies_across_sessions(wired, monkeypatch):
    monkeypatch.setattr(security, "daily_limiter", security.SlidingWindowLimiter(1, 86400))
    assert new_client().post("/api/travel", json={"message": PROMPT}).status_code == 200
    assert new_client().post("/api/travel", json={"message": PROMPT}).status_code == 429


def test_internal_errors_do_not_leak_details(client, wired):
    wired.llm.fail_with = RuntimeError("password=hunter2 host=db.internal")
    response = client.post("/api/travel", json={"message": PROMPT})
    assert response.status_code == 500
    body = response.text
    assert "hunter2" not in body and "db.internal" not in body
    assert "reference" in response.json()["error"]


def test_provider_rate_limit_maps_to_429(client, wired):
    request = httpx.Request("POST", "https://api.groq.com/x")
    wired.llm.fail_with = groq.RateLimitError(
        "slow down", response=httpx.Response(429, headers={"retry-after": "7"}, request=request), body=None
    )
    response = client.post("/api/travel", json={"message": PROMPT})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "7"


def test_provider_timeout_maps_to_503(client, wired):
    wired.llm.fail_with = groq.APITimeoutError(request=httpx.Request("POST", "https://api.groq.com/x"))
    assert client.post("/api/travel", json={"message": PROMPT}).status_code == 503


# ---- the server stays responsive during a long plan (F-12) ----------------------
def test_health_responds_while_a_plan_is_running(client, wired):
    import threading
    import time

    original = wired.llm.invoke

    def slow_invoke(messages, max_tokens=None):
        time.sleep(0.6)
        return original(messages, max_tokens=max_tokens)

    wired.llm.invoke = slow_invoke
    done = {}

    def plan():
        done["response"] = client.post("/api/travel", json={"message": PROMPT})

    worker = threading.Thread(target=plan)
    started = time.perf_counter()
    worker.start()
    time.sleep(0.3)  # the plan is now in progress (~4 slow LLM calls, > 2 s in total)

    health_started = time.perf_counter()
    health = TestClient(app).get("/health")
    health_latency = time.perf_counter() - health_started
    worker.join()

    assert health.status_code == 200
    assert not worker.is_alive() and done["response"].status_code == 200
    assert time.perf_counter() - started > 1.5, "the plan should have been long-running"
    assert health_latency < 0.5, f"/health blocked for {health_latency:.2f}s while a plan ran"
