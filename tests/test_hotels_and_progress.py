"""Hotel result formatting and live progress events."""

import json

import pytest

import backend
import mcp_client

OWNER, OTHER = "owner-1", "owner-2"
PROMPT = "Plan a 7-day Japan trip from Dhaka in October."

TAVILY = json.dumps(
    {
        "query": "x",
        "follow_up_questions": None,
        "answer": None,
        "images": [],
        "results": [
            {
                "title": f"Hotel list {i}",
                "url": f"https://example.com/{i}",
                "score": 0.9,
                "content": "Great   area" + chr(10) + "near the station. " * 20,
            }
            for i in range(7)
        ]
        + [{"title": "Bad link", "url": "javascript:alert(1)", "content": "text"}],
    }
)


# ---- hotel results ---------------------------------------------------------------
def test_search_results_become_compact_attributed_bullets():
    text = backend._format_search_results(TAVILY)
    lines = text.splitlines()
    assert len(lines) == 5  # capped
    assert lines[0].startswith("- Hotel list 0: Great area near the station.")
    assert "(source: https://example.com/0)" in lines[0]
    assert "follow_up_questions" not in text
    assert "score" not in text
    assert all(len(line) < 450 for line in lines)


def test_search_results_edge_cases():
    only_bad = json.dumps({"results": [{"title": "Bad", "url": "javascript:alert(1)", "content": "text"}]})
    assert "javascript" not in backend._format_search_results(only_bad)
    assert backend._format_search_results(json.dumps({"results": []})) == "No live hotel results were found."
    assert backend._format_search_results("plain text, not json") == "plain text, not json"


def test_hotel_query_uses_supervisor_constraints():
    state = {
        "user_query": "long rambling request",
        "trip_constraints": {
            "destination_city": "Tokyo",
            "budget": "mid-range",
            "travel_style": "culture",
            "special_preferences": ["food", "quiet"],
        },
    }
    assert backend._hotel_query(state) == "Best hotels in Tokyo mid-range budget culture travel good for food, quiet"
    fallback = backend._hotel_query({"user_query": "Somewhere nice", "trip_constraints": {}})
    assert fallback == "Best hotels for Somewhere nice"


def test_formatted_hotels_reach_the_itinerary_prompt(wired, monkeypatch):
    monkeypatch.setattr(mcp_client, "tavily_search", lambda q: TAVILY)
    backend.start_trip(OWNER, PROMPT)
    itinerary_prompt = next(c["user"] for c in wired.llm.calls if "expert travel planner" in c["system"])
    assert "- Hotel list 0:" in itinerary_prompt
    assert "https://example.com/0" in itinerary_prompt
    assert "follow_up_questions" not in itinerary_prompt


def test_final_prompt_requires_sourced_hotels(wired):
    draft = backend.start_trip(OWNER, PROMPT)
    backend.resume_trip(OWNER, draft["thread_id"], True)
    final_prompt = next(c["user"] for c in wired.llm.calls if "booking assistant" in c["system"])
    assert "Never invent hotel names or links" in final_prompt


# ---- live progress events ----------------------------------------------------------
def test_progress_events_cover_every_visible_stage(wired):
    events = []
    result = backend.start_trip(OWNER, PROMPT, on_event=events.append)

    assert all(e["type"] == "progress" for e in events)
    started = [e["node"] for e in events if e["state"] == "start"]
    done = [e["node"] for e in events if e["state"] == "done"]
    assert started[0] == "supervisor"
    assert set(started) == set(done)
    assert set(started) == {
        "supervisor", "flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent",
    }
    # internal nodes never leak into the UI
    assert not {"research_join", "human_approval"} & set(started)
    # all three research agents start before the budget stage does
    research_starts = [started.index(n) for n in ("flight_agent", "hotel_agent", "weather_agent")]
    assert max(research_starts) < started.index("budget_agent")
    assert result["status"] == "awaiting_approval"
    assert result["itinerary"] == "DRAFT ITINERARY"


def test_streamed_run_matches_plain_run(wired):
    streamed = backend.start_trip(OWNER, PROMPT, on_event=lambda e: None)
    plain = backend.start_trip(OWNER, PROMPT)
    for key in ("status", "itinerary", "flight_results", "selected_agents", "llm_calls", "requires_approval"):
        assert streamed[key] == plain[key], key


def test_revision_and_final_stages_are_labelled(wired):
    draft = backend.start_trip(OWNER, PROMPT)
    revision = []
    backend.resume_trip(OWNER, draft["thread_id"], False, "cheaper please", on_event=revision.append)
    expected = {"type": "progress", "node": "itinerary_agent", "label": "Revising your itinerary", "state": "start"}
    assert expected in revision

    final = []
    result = backend.resume_trip(OWNER, draft["thread_id"], True, on_event=final.append)
    assert [e["label"] for e in final if e["state"] == "start"] == ["Writing your final plan"]
    assert result["status"] == "completed"


def test_blocked_request_streams_only_the_supervisor_stage(wired):
    wired.llm.supervisor = lambda _p: json.dumps({"allowed": False, "reason": "Not travel."})
    events = []
    result = backend.start_trip(OWNER, "poem please", on_event=events.append)
    assert {e["node"] for e in events} == {"supervisor"}
    assert result["status"] == "blocked"


def test_check_resumable_validates_before_streaming(wired):
    draft = backend.start_trip(OWNER, PROMPT)
    backend.check_resumable(OWNER, draft["thread_id"])
    with pytest.raises(backend.ThreadNotFoundError):
        backend.check_resumable(OTHER, draft["thread_id"])
    backend.resume_trip(OWNER, draft["thread_id"], True)
    with pytest.raises(backend.ThreadStateError):
        backend.check_resumable(OWNER, draft["thread_id"])
