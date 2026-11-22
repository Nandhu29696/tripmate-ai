# 04 - Backend and API (updated after remediation)

> The original audit described the pre-remediation code; this file reflects
> the current code. See [13_REMEDIATION_REPORT.md](13_REMEDIATION_REPORT.md).

## Endpoints

| Method | Endpoint | Purpose | Auth | Request | Response |
|---|---|---|---|---|---|
| GET | `/` | UI | None | - | HTML (CSP and security headers) |
| GET | `/api/session` | Auth status; issues an anonymous session in open mode | None | - | `{authenticated, auth_required}` |
| POST | `/api/session` | Sign in (throttled: 5 failures / 15 min / IP) | None | `{access_key}` | 200 + `tm_session` cookie, or 401/429 |
| DELETE | `/api/session` | Sign out | None | - | `{success}` |
| POST | `/api/travel` | New trip; pauses at human review | Session | `{message (<=4000 chars)}` | trip payload (below); 429 on quota |
| POST | `/api/travel/approve` | Approve, or reject with feedback (revised draft, max 2 rounds) | Session + owner | `{thread_id, approved, feedback? (<=2000)}` | trip payload; 404 not yours, 409 not awaiting review |
| GET | `/api/travel/threads` | List own trips | Session | - | `{trips:[{thread_id,title,status,created_at,updated_at}]}` |
| GET | `/api/travel/{thread_id}` | Restore a trip | Session + owner | - | trip payload |
| DELETE | `/api/travel/{thread_id}` | Delete trip and checkpoints | Session + owner | - | `{success}` |
| GET | `/health` | Liveness | None | - | `{status, message, features}` |
| GET | `/ready` | Readiness (DB probe); blocked at Nginx | None | - | `{ready, database}` or 503 |

**Trip payload:** `success, thread_id, status (awaiting_approval|completed|blocked), user_query, answer, requires_approval, approval_request, flight_results, hotel_results, weather_results, budget_results, itinerary, selected_agents, trip_constraints, supervisor_reasoning, guardrail_allowed, guardrail_reason, approved, human_feedback, revision_count, max_revisions, llm_calls`.

**Errors:** `{success:false, error, request_id}` with 400 (validation), 401, 403 (cross-origin), 404, 409, 429 (+`Retry-After`), 503, 500 (generic + reference id).

## Modules

- `app.py`: lifespan (init backend, retention loop), middleware (request id,
  Origin check, security headers, access log), session/auth, routes, error mapping.
- `backend.py`: `TravelState`, agents, routing, `build_graph()`, runtime wiring
  (`init_backend`, `shutdown_backend`, `check_ready`) and the trip service
  (`start_trip`, `resume_trip`, `get_trip`, `list_trips`, `delete_trip`,
  `purge_expired`).
- `mcp_client.py`: `MCPRuntime` (persistent sessions on one loop thread),
  `ToolError`, wrappers `tavily_search`, `aviation_call`, `weather_current`,
  `weather_forecast`.
- `config.py`, `llm_utils.py`, `security.py`, `store.py` as described in the README.

## Graph

`START -> supervisor -> {flight, hotel, weather in parallel | skip} -> research_join -> budget? -> itinerary -> human_approval -> (approved or revisions exhausted: final | else itinerary) -> END`; a blocked request goes `supervisor -> guardrail_blocked -> END`.

## Trace: new trip

`script.js sendMessage` -> `POST /api/travel` -> `current_session` (verify cookie) -> `acquire_plan_quota` -> `backend.start_trip` (registry row, `graph.invoke` in a worker thread) -> supervisor (1 LLM call) -> parallel agents (MCP sessions reused) -> budget -> itinerary -> `interrupt` -> checkpoints in Postgres -> `_serialize_result` -> JSON.
