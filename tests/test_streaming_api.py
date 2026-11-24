"""NDJSON streaming endpoints."""

import json
import time
import uuid

import groq
import httpx
import pytest
from fastapi.testclient import TestClient

import app as app_module
import backend
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


def read_stream(response) -> list[dict]:
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["x-accel-buffering"] == "no"
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_stream_emits_progress_then_result(client):
    response = client.post("/api/travel/stream", json={"message": PROMPT})
    assert response.status_code == 200
    events = read_stream(response)

    first = {"type": "progress", "node": "supervisor", "label": "Checking your request", "state": "start"}
    assert events[0] == first
    assert events[-1]["type"] == "result"
    assert events[-1]["success"] is True
    assert events[-1]["requires_approval"]
    assert events[-1]["itinerary"] == "DRAFT ITINERARY"
    assert {e["type"] for e in events[:-1]} == {"progress"}

    tid = events[-1]["thread_id"]
    follow_up = client.post("/api/travel/approve/stream", json={"thread_id": tid, "approved": True})
    final = read_stream(follow_up)
    assert final[-1]["status"] == "completed"
    assert final[-1]["answer"] == "FINAL PLAN"
    assert any(e.get("node") == "final_agent" for e in final)


def test_stream_pre_checks_keep_real_http_statuses(client, monkeypatch):
    assert TestClient(app).post("/api/travel/stream", json={"message": PROMPT}).status_code == 401
    assert client.post("/api/travel/stream", json={"message": "  "}).status_code == 400

    tid = read_stream(client.post("/api/travel/stream", json={"message": PROMPT}))[-1]["thread_id"]
    intruder = new_client()
    other = intruder.post("/api/travel/approve/stream", json={"thread_id": tid, "approved": True})
    assert other.status_code == 404
    no_feedback = client.post("/api/travel/approve/stream", json={"thread_id": tid, "approved": False})
    assert no_feedback.status_code == 400

    client.post("/api/travel/approve", json={"thread_id": tid, "approved": True})
    again = client.post("/api/travel/approve/stream", json={"thread_id": tid, "approved": True})
    assert again.status_code == 409

    monkeypatch.setattr(security, "plan_limiter", security.SlidingWindowLimiter(1, 3600))
    assert client.post("/api/travel/stream", json={"message": PROMPT}).status_code == 200
    limited = client.post("/api/travel/stream", json={"message": PROMPT})
    assert limited.status_code == 429
    assert "retry-after" in limited.headers


def test_stream_reports_failures_as_a_safe_error_event(client, wired):
    request = httpx.Request("POST", "https://api.groq.com/x")
    wired.llm.fail_with = groq.RateLimitError(
        "slow down", response=httpx.Response(429, headers={"retry-after": "7"}, request=request), body=None
    )
    events = read_stream(client.post("/api/travel/stream", json={"message": PROMPT}))
    assert events[-1]["type"] == "error"
    assert events[-1]["status"] == 429
    assert events[-1]["retry_after"] == "7"

    wired.llm.fail_with = RuntimeError("password=hunter2")
    leaked = client.post("/api/travel/stream", json={"message": PROMPT})
    assert "hunter2" not in leaked.text
    assert read_stream(leaked)[-1]["status"] == 500


def test_run_finishes_even_if_the_client_never_reads_the_stream(wired):
    """A closed tab must not abort the plan: it is saved and restorable."""
    finished = []

    def work(emit):
        emit({"type": "progress", "node": "supervisor", "label": "x", "state": "start"})
        time.sleep(0.2)
        finished.append(True)
        return {"thread_id": "t"}

    response = app_module._ndjson_stream(work, "start_trip")  # never iterated
    assert response.media_type == "application/x-ndjson"
    deadline = time.time() + 3
    while not finished and time.time() < deadline:
        time.sleep(0.05)
    assert finished == [True]
