"""Admin console: access control, user and trip management, logs, audit."""

import json

import pytest
from fastapi.testclient import TestClient

import accounts
import app as app_module
import backend
import config
import observability
from tests.conftest import signed_in_client

ADMIN_ENDPOINTS = [
    ("get", "/api/admin/overview"),
    ("get", "/api/admin/users"),
    ("get", "/api/admin/trips"),
    ("get", "/api/admin/logs/requests"),
    ("get", "/api/admin/logs/sql"),
    ("get", "/api/admin/logs/audit"),
    ("get", "/api/admin/system"),
    ("post", "/api/admin/system/purge"),
]


@pytest.fixture
def admin(wired):
    client = signed_in_client(wired.users, "boss@example.com", "Boss")
    wired.users.set_role(client.user["id"], "admin")
    return client


@pytest.fixture
def member(wired):
    return signed_in_client(wired.users, "member@example.com", "Member")


# ---------------------------------------------------------------- access control
@pytest.mark.parametrize(("method", "path"), ADMIN_ENDPOINTS)
def test_anonymous_gets_401(wired, method, path):
    client = TestClient(app_module.app)
    response = getattr(client, method)(path, headers={"Origin": "http://testserver"})
    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path"), ADMIN_ENDPOINTS)
def test_normal_user_gets_403(wired, member, method, path):
    response = getattr(member, method)(path, headers={"Origin": "http://testserver"})
    assert response.status_code == 403
    assert "access" in response.json()["error"].lower()


def test_session_reports_role(wired, admin, member):
    assert admin.get("/api/session").json()["user"]["role"] == "admin"
    assert member.get("/api/session").json()["user"]["role"] == "user"


def test_unverified_admin_role_is_not_honoured(wired):
    user = wired.users.create_user("new@example.com", "New", None, None, False)
    wired.users.set_role(user["id"], "admin")
    client = TestClient(app_module.app)
    import security

    client.cookies.set("tm_session", security.issue_session_token(user["id"]))
    assert client.get("/api/admin/overview").status_code == 403


def test_demoted_admin_loses_access_immediately(wired, admin):
    assert admin.get("/api/admin/overview").status_code == 200
    wired.users.set_role(admin.user["id"], "user")
    assert admin.get("/api/admin/overview").status_code == 403


def test_configured_admin_email_is_promoted_at_sign_in(wired, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAILS", frozenset({"owner@example.com"}))
    verified = wired.users.create_user("owner@example.com", "Owner", accounts.hash_password("correct horse battery"), None, True)
    stranger = wired.users.create_user("other@example.com", "Other", accounts.hash_password("correct horse battery"), None, True)
    unverified = wired.users.create_user("owner2@example.com", "Owner2", accounts.hash_password("correct horse battery"), None, False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", frozenset({"owner@example.com", "owner2@example.com"}))

    client = TestClient(app_module.app)
    assert client.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery"}).status_code == 200
    assert client.get("/api/session").json()["user"]["role"] == "admin"
    assert wired.users.get(verified["id"])["role"] == "admin"

    other = TestClient(app_module.app)
    other.post("/api/auth/login", json={"email": "other@example.com", "password": "correct horse battery"})
    assert other.get("/api/session").json()["user"]["role"] == "user"
    assert wired.users.get(stranger["id"]).get("role", "user") == "user"

    # A listed address that was never verified cannot sign in, so it is never promoted.
    third = TestClient(app_module.app)
    assert third.post("/api/auth/login", json={"email": "owner2@example.com", "password": "correct horse battery"}).status_code == 403
    assert wired.users.get(unverified["id"]).get("role", "user") == "user"


# ---------------------------------------------------------------- overview and system
def test_overview_counts(wired, admin, member):
    wired.registry.create("trip_" + "a" * 32, member.user["id"], "Paris")
    wired.registry.set_status("trip_" + "a" * 32, "completed")
    data = admin.get("/api/admin/overview").json()
    assert data["users"]["total"] == 2 and data["users"]["admins"] == 1
    assert data["trips"]["by_status"] == {"completed": 1} and data["trips"]["total"] == 1
    assert data["requests"]["total"] >= 0 and "series" in data["requests"]
    assert data["ready"]["ready"] is True


def test_system_info_has_no_secrets(wired, admin, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_super_secret_value")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "google-secret-value")
    body = admin.get("/api/admin/system").text
    assert "gsk_super_secret_value" not in body and "google-secret-value" not in body
    assert "test-secret" not in body  # session secret
    data = json.loads(body)
    assert data["settings"]["model"] == config.GROQ_MODEL


# ---------------------------------------------------------------- users
def test_list_and_search_users(wired, admin, member):
    wired.registry.create("trip_" + "b" * 32, member.user["id"], "Rome")
    data = admin.get("/api/admin/users").json()
    assert data["total"] == 2
    row = next(u for u in data["users"] if u["email"] == "member@example.com")
    assert row["trips"] == 1 and row["role"] == "user"
    assert "password_hash" not in json.dumps(data)

    found = admin.get("/api/admin/users", params={"q": "MEMB"}).json()
    assert [u["email"] for u in found["users"]] == ["member@example.com"]


def test_promote_and_demote(wired, admin, member):
    uid = member.user["id"]
    assert admin.patch(f"/api/admin/users/{uid}", json={"role": "admin"}).json()["user"]["role"] == "admin"
    assert member.get("/api/admin/overview").status_code == 200  # takes effect immediately
    assert admin.patch(f"/api/admin/users/{uid}", json={"role": "user"}).json()["user"]["role"] == "user"
    assert member.get("/api/admin/overview").status_code == 403


def test_cannot_promote_unverified_user(wired, admin):
    user = wired.users.create_user("pending@example.com", "P", None, None, False)
    response = admin.patch(f"/api/admin/users/{user['id']}", json={"role": "admin"})
    assert response.status_code == 400 and "verified" in response.json()["error"]


def test_self_protection(wired, admin):
    uid = admin.user["id"]
    assert admin.patch(f"/api/admin/users/{uid}", json={"role": "user"}).status_code == 400
    assert admin.patch(f"/api/admin/users/{uid}", json={"is_active": False}).status_code == 400
    assert admin.delete(f"/api/admin/users/{uid}").status_code == 400
    assert admin.get("/api/admin/overview").status_code == 200


def test_one_admin_can_demote_another_but_the_guard_protects_the_last(wired, admin, member):
    wired.users.set_role(member.user["id"], "admin")
    assert wired.users.user_counts()["admins"] == 2
    assert admin.patch(f"/api/admin/users/{member.user['id']}", json={"role": "user"}).status_code == 200
    assert wired.users.user_counts()["admins"] == 1

    # The guard itself: a sole administrator is never removable.
    import admin_routes

    assert admin_routes._guard_last_admin(wired.users.get(admin.user["id"])) is not None
    assert admin_routes._guard_last_admin(wired.users.get(member.user["id"])) is None


def test_disable_ends_sessions_and_enable_restores_access(wired, admin, member):
    uid = member.user["id"]
    assert member.get("/api/session").json()["authenticated"] is True
    assert admin.patch(f"/api/admin/users/{uid}", json={"is_active": False}).status_code == 200
    assert member.get("/api/session").json()["authenticated"] is False
    assert member.get("/api/travel/threads").status_code == 401

    login = TestClient(app_module.app).post(
        "/api/auth/login", json={"email": "member@example.com", "password": "whatever-123"}
    )
    assert login.status_code == 401

    assert admin.patch(f"/api/admin/users/{uid}", json={"is_active": True}).status_code == 200
    import security

    member.cookies.set("tm_session", security.issue_session_token(uid))
    assert member.get("/api/session").json()["authenticated"] is True


def test_revoke_sessions(wired, admin, member):
    uid = member.user["id"]
    assert admin.post(f"/api/admin/users/{uid}/revoke-sessions").status_code == 200
    assert member.get("/api/session").json()["authenticated"] is False


def test_verify_email_manually(wired, admin):
    user = wired.users.create_user("stuck@example.com", "S", None, None, False)
    admin.patch(f"/api/admin/users/{user['id']}", json={"verify_email": True})
    assert wired.users.get(user["id"])["email_verified"] is True


def test_delete_user_removes_their_trips(wired, admin, member):
    tid = "trip_" + "c" * 32
    wired.registry.create(tid, member.user["id"], "Oslo")
    from langgraph.checkpoint.base import empty_checkpoint  # noqa: F401 - checkpointer exists

    response = admin.delete(f"/api/admin/users/{member.user['id']}")
    assert response.status_code == 200 and response.json()["trips_deleted"] == 1
    assert wired.users.get(member.user["id"]) is None
    assert wired.registry.get(tid) is None


def test_bad_ids_are_rejected(wired, admin):
    assert admin.patch("/api/admin/users/not-an-id", json={"role": "admin"}).status_code == 404
    assert admin.delete("/api/admin/users/usr_" + "0" * 32).status_code == 404
    assert admin.patch("/api/admin/users/usr_" + "0" * 32, json={"role": "root"}).status_code == 400


# ---------------------------------------------------------------- trips
def test_trips_list_filter_and_delete(wired, admin, member):
    a, b = "trip_" + "d" * 32, "trip_" + "e" * 32
    wired.registry.create(a, member.user["id"], "Lima")
    wired.registry.create(b, admin.user["id"], "Cusco")
    wired.registry.set_status(b, "completed")

    data = admin.get("/api/admin/trips").json()
    assert data["total"] == 2
    assert {t["owner_email"] for t in data["trips"]} == {"member@example.com", "boss@example.com"}

    done = admin.get("/api/admin/trips", params={"status": "completed"}).json()
    assert [t["thread_id"] for t in done["trips"]] == [b]
    assert admin.get("/api/admin/trips", params={"status": "bogus"}).status_code == 400

    assert admin.delete(f"/api/admin/trips/{a}").status_code == 200
    assert wired.registry.get(a) is None
    assert admin.delete(f"/api/admin/trips/{a}").status_code == 404
    assert admin.delete("/api/admin/trips/nope").status_code == 404


# ---------------------------------------------------------------- logs
def test_request_log_records_path_without_query_string(wired, admin):
    admin.get("/api/admin/users", params={"q": "secret-token-123"})
    admin.get("/health")
    logs = admin.get("/api/admin/logs/requests").json()["logs"]
    paths = [row["path"] for row in logs]
    assert "/api/admin/users" in paths
    assert "/health" not in paths
    assert "secret-token-123" not in json.dumps(logs)
    row = next(r for r in logs if r["path"] == "/api/admin/users")
    assert row["method"] == "GET" and row["status"] == 200 and row["user_id"] == admin.user["id"]
    assert row["duration_ms"] >= 0 and row["request_id"]


def test_request_log_filters(wired, admin, member):
    member.get("/api/admin/overview")  # 403
    anonymous = TestClient(app_module.app)
    anonymous.get("/api/travel/threads")  # 401
    errors = admin.get("/api/admin/logs/requests", params={"status": "4xx"}).json()["logs"]
    assert {r["status"] for r in errors} == {401, 403}
    only_403 = admin.get("/api/admin/logs/requests", params={"status": "403"}).json()["logs"]
    assert [r["path"] for r in only_403] == ["/api/admin/overview"]
    by_user = admin.get("/api/admin/logs/requests", params={"user_id": member.user["id"]}).json()["logs"]
    assert by_user and all(r["user_id"] == member.user["id"] for r in by_user)
    assert admin.get("/api/admin/logs/requests", params={"status": "abc"}).status_code == 400
    assert admin.get("/api/admin/logs/requests", params={"limit": 5000}).status_code == 400


def test_sql_log_normalises_flags_slow_and_hides_logging_tables(monkeypatch):
    log = observability.SqlLog(size=5)
    monkeypatch.setattr(config, "SLOW_QUERY_MS", 100)
    log.add("SELECT  *\n  FROM users\n WHERE id = %s", 3.2, rows=1)
    log.add("UPDATE users SET name = %s", 450.0)
    log.add("INSERT INTO api_request_logs VALUES (1)", 1.0)  # not recorded
    log.add("SELECT bad", 2.0, error="UndefinedTable")

    everything = log.query()
    assert [r["sql"] for r in everything] == ["SELECT bad", "UPDATE users SET name = %s", "SELECT * FROM users WHERE id = %s"]
    assert [r["sql"] for r in log.query(slow_only=True)] == ["UPDATE users SET name = %s"]
    assert [r["sql"] for r in log.query(errors_only=True)] == ["SELECT bad"]
    assert len(log.query("from USERS")) == 1
    summary = log.summary()
    assert summary["count"] == 3 and summary["slow"] == 1 and summary["errors"] == 1 and summary["max_ms"] == 450.0

    for i in range(10):
        log.add(f"SELECT {i}", 1.0)
    assert len(log.query(limit=100)) == 5  # bounded ring


def test_sql_log_endpoint(wired, admin):
    observability.sql_log.add("SELECT 1", 1.0)
    data = admin.get("/api/admin/logs/sql", params={"q": "select 1"}).json()
    assert data["summary"]["count"] >= 1 and data["logs"][0]["sql"] == "SELECT 1"
    assert "params" not in json.dumps(data["logs"][0])


def test_admin_actions_are_audited(wired, admin, member):
    admin.patch(f"/api/admin/users/{member.user['id']}", json={"is_active": False})
    admin.post("/api/admin/system/purge")
    rows = admin.get("/api/admin/logs/audit").json()["logs"]
    actions = [r["action"] for r in rows]
    assert actions[:2] == ["system.purge", "user.update"]
    update = rows[1]
    assert update["actor_email"] == "boss@example.com" and update["target"] == "member@example.com"
    assert update["detail"] == "disabled"


def test_no_audit_entry_when_nothing_changes(wired, admin, member):
    admin.patch(f"/api/admin/users/{member.user['id']}", json={"role": "user"})
    assert admin.get("/api/admin/logs/audit").json()["logs"] == []


# ---------------------------------------------------------------- day-wise draft format
def test_draft_prompt_requests_day_wise_layout(wired):
    backend.start_trip("usr_x", "Plan 3 days in Tokyo")
    draft_call = next(c for c in wired.llm.calls if "expert travel planner" in c["system"])
    for expected in ("## Trip at a glance", "## Weather outlook", "## Day 1 -", "**Weather:**", "**Est. cost:**",
                     "## Budget summary", "## Before you go"):
        assert expected in draft_call["user"]


def test_final_prompt_requests_flights_hotels_and_days(wired):
    started = backend.start_trip("usr_x", "Plan 3 days in Tokyo")
    backend.resume_trip("usr_x", started["thread_id"], True)
    final_call = next(c for c in wired.llm.calls if "booking assistant" in c["system"])
    for expected in ("## Flights", "## Hotels", "## Day 1 -", "**Weather:**", "## Weather outlook"):
        assert expected in final_call["user"]


def test_streamed_request_duration_covers_the_whole_stream(wired, admin, monkeypatch):
    import time as time_module

    def slow_trip(owner_id, message, on_event=None):
        time_module.sleep(0.25)
        return {"thread_id": "trip_" + "f" * 32, "status": "completed"}

    monkeypatch.setattr(backend, "start_trip", slow_trip)
    response = admin.post("/api/travel/stream", json={"message": "Plan Paris"})
    assert response.status_code == 200 and '"type": "result"' in response.text

    row = next(r for r in admin.get("/api/admin/logs/requests").json()["logs"] if r["path"] == "/api/travel/stream")
    assert row["status"] == 200
    assert row["duration_ms"] >= 240  # headers go out at once; the work happens while the body is sent


# ---------------------------------------------------------------- token accounting
def test_trip_tokens_are_added_up_per_call(wired):
    started = backend.start_trip("usr_x", "Plan 3 days in Tokyo")
    row = wired.registry.get(started["thread_id"])
    # the fake model reports 100 in / 50 out per call
    assert row["llm_calls"] == started["llm_calls"] > 0
    assert row["input_tokens"] == 100 * row["llm_calls"]
    assert row["output_tokens"] == 50 * row["llm_calls"]

    before = row["llm_calls"]
    backend.resume_trip("usr_x", started["thread_id"], True)
    after = wired.registry.get(started["thread_id"])
    assert after["llm_calls"] > before  # the final-plan call is added to the same trip


def test_missing_provider_counts_are_estimated(wired):
    import llm_utils

    usage = llm_utils.new_usage()
    token = llm_utils.usage_var.set(usage)
    try:
        wired.llm.usage_override = None
        original = wired.llm.invoke

        def no_usage(messages, max_tokens=None):
            response = original(messages, max_tokens)
            response.usage_metadata = {}
            return response

        wired.llm.invoke = no_usage
        llm_utils.invoke_with_token_budget(wired.llm, "You are a flight planner.", "hello world", 100)
    finally:
        llm_utils.usage_var.reset(token)
    assert usage["llm_calls"] == 1 and usage["input_tokens"] > 0 and usage["output_tokens"] > 0


def test_request_log_and_admin_views_show_tokens(wired, admin, member):
    response = member.post("/api/travel/stream", json={"message": "Plan 3 days in Tokyo"})
    assert response.status_code == 200 and '"type": "result"' in response.text

    logs = admin.get("/api/admin/logs/requests").json()["logs"]
    row = next(r for r in logs if r["path"] == "/api/travel/stream")
    assert row["llm_calls"] >= 4
    assert row["input_tokens"] == 100 * row["llm_calls"] and row["output_tokens"] == 50 * row["llm_calls"]

    trips = admin.get("/api/admin/trips").json()["trips"]
    assert trips[0]["llm_calls"] == row["llm_calls"] and trips[0]["input_tokens"] == row["input_tokens"]

    users = {u["email"]: u for u in admin.get("/api/admin/users").json()["users"]}
    assert users["member@example.com"]["tokens"] == row["input_tokens"] + row["output_tokens"]

    stats = admin.get("/api/admin/overview").json()["requests"]
    assert stats["llm_calls"] == row["llm_calls"] and stats["input_tokens"] == row["input_tokens"]


def test_requests_without_ai_calls_show_zero_tokens(wired, admin):
    admin.get("/api/admin/users")
    row = admin.get("/api/admin/logs/requests").json()["logs"][0]
    assert row["llm_calls"] == 0 and row["input_tokens"] == 0 and row["output_tokens"] == 0


# ---------------------------------------------------------------- India as the default starting point
def _supervisor_with(origin: str, origin_city: str):
    def supervisor(_prompt):
        data = json.loads(backend_default_supervisor(_prompt))
        data["trip_constraints"]["origin"] = origin
        data["trip_constraints"]["origin_city"] = origin_city
        return json.dumps(data)

    return supervisor


def backend_default_supervisor(prompt):
    from tests.conftest import FakeLLM

    return FakeLLM.default_supervisor(prompt)


def test_trip_without_a_starting_point_starts_from_india(wired):
    wired.llm.supervisor = _supervisor_with("", "")
    result = backend.start_trip("usr_x", "Plan 3 days in Tokyo")
    assert result["trip_constraints"]["origin"] == "India"
    assert result["trip_constraints"]["origin_city"] == "Delhi"
    assert "assumed" in result["supervisor_reasoning"] and "Delhi" in result["supervisor_reasoning"]


def test_a_stated_starting_point_is_kept(wired):
    wired.llm.supervisor = _supervisor_with("Bangladesh", "Dhaka")
    result = backend.start_trip("usr_x", "Plan 3 days in Tokyo from Dhaka")
    assert result["trip_constraints"]["origin_city"] == "Dhaka"
    assert "assumed" not in result["supervisor_reasoning"]


def test_from_india_without_a_city_uses_the_default_city(wired):
    wired.llm.supervisor = _supervisor_with("India", "")
    result = backend.start_trip("usr_x", "Plan 3 days in Tokyo from India")
    assert result["trip_constraints"]["origin_city"] == "Delhi"
    assert "assumed" not in result["supervisor_reasoning"]


def test_prompts_use_rupees_and_ask_for_a_total_budget(wired):
    backend.start_trip("usr_x", "Plan 3 days in Tokyo")
    draft = next(c for c in wired.llm.calls if "expert travel planner" in c["system"])["user"]
    assert "INR" in draft and "₹" in draft
    assert "TOTAL estimated cost of the WHOLE trip" in draft and "**Per person:**" in draft
    assert "total estimated cost of the whole trip" in draft  # also in "Trip at a glance"
