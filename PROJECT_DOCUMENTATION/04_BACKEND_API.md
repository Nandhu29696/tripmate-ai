# 04 - Backend and API (updated after remediation)

> The original audit described the pre-remediation code; this file reflects
> the current code. See [13_REMEDIATION_REPORT.md](13_REMEDIATION_REPORT.md).

## Endpoints

| Method | Endpoint | Purpose | Auth | Request | Response |
|---|---|---|---|---|---|
| GET | `/` | UI | None | - | HTML (CSP and security headers) |
| GET | `/api/session` | Who is signed in; which sign-in methods exist | None | - | `{authenticated, user?, providers:{google,password}}` |
| POST | `/api/auth/register` | Create an email+password account; emails a confirmation link; identical reply for new and existing emails | None | `{email, password, name?}` | `{success, message}`; 400 weak input; 429 per-IP limit |
| GET | `/auth/verify` | Confirm email (single-use link), sign in | Token | `?token=` | 303 to `/?verified=1` or `/?auth_error=invalid_link` |
| POST | `/api/auth/login` | Email + password sign-in | None | `{email, password}` | 200 + cookie; 401 generic; 403 `email_not_verified`; 429 throttled |
| POST | `/api/auth/forgot` | Emails a one-hour reset link if the account exists | None | `{email}` | same reply always |
| POST | `/api/auth/reset` | Set a new password; revokes all other sessions | Token | `{token, password}` | 200 + cookie; 400 |
| GET | `/auth/google/login` | Start Google sign-in (state, nonce, PKCE) | None | - | 303 to accounts.google.com |
| GET | `/auth/google/callback` | Finish Google sign-in; create or link the user | state cookie | `?code=&state=` | 303 to `/` or `/?auth_error=...` |
| POST | `/api/account/delete` | Delete the user, all trips and checkpoints | Session | `{confirm:true}` | `{success, trips_deleted}` |
| DELETE | `/api/session` | Sign out | None | - | `{success}` |
| POST | `/api/travel` | New trip; pauses at human review | Signed-in user | `{message (<=4000 chars)}` | trip payload (below); 429 on quota |
| POST | `/api/travel/approve` | Approve, or reject with feedback (revised draft, max 2 rounds) | Session + owner | `{thread_id, approved, feedback? (<=2000)}` | trip payload; 404 not yours, 409 not awaiting review |
| GET | `/api/travel/threads` | List own trips | Session | - | `{trips:[{thread_id,title,status,created_at,updated_at}]}` |
| GET | `/api/travel/{thread_id}` | Restore a trip | Session + owner | - | trip payload |
| DELETE | `/api/travel/{thread_id}` | Delete trip and checkpoints | Session + owner | - | `{success}` |
| GET | `/health` | Liveness | None | - | `{status, message, features}` |
| GET | `/ready` | Readiness (DB probe); blocked at Nginx | None | - | `{ready, database}` or 503 |

**Trip payload:** `success, thread_id, status (awaiting_approval|completed|blocked), user_query, answer, requires_approval, approval_request, flight_results, hotel_results, weather_results, budget_results, itinerary, selected_agents, trip_constraints, supervisor_reasoning, guardrail_allowed, guardrail_reason, approved, human_feedback, revision_count, max_revisions, llm_calls`.

**Errors:** `{success:false, error, request_id}` with 400 (validation), 401, 403 (cross-origin), 404, 409, 429 (+`Retry-After`), 503, 500 (generic + reference id).

Authentication: a signed, HttpOnly, SameSite=Lax session cookie names the user id and its issue time. Every request loads the user, so deactivated users and sessions issued before a password reset are rejected immediately. Quotas are per user.

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
- `config.py`, `llm_utils.py`, `security.py`, `store.py`, `accounts.py`, `auth_routes.py`, `oauth_google.py`, `mailer.py`, `web_common.py` as described in the README.

## Graph

`START -> supervisor -> {flight, hotel, weather in parallel | skip} -> research_join -> budget? -> itinerary -> human_approval -> (approved or revisions exhausted: final | else itinerary) -> END`; a blocked request goes `supervisor -> guardrail_blocked -> END`.

## Trace: new trip

`script.js sendMessage` -> `POST /api/travel` -> `current_session` (verify cookie) -> `acquire_plan_quota` -> `backend.start_trip` (registry row, `graph.invoke` in a worker thread) -> supervisor (1 LLM call) -> parallel agents (MCP sessions reused) -> budget -> itinerary -> `interrupt` -> checkpoints in Postgres -> `_serialize_result` -> JSON.

## Admin API (v2.2)

All routes need a signed-in administrator (401 if signed out, 403 otherwise) and every change is audited.

| Route | Purpose |
|---|---|
| `GET /api/admin/overview` | user/trip counts, 24 h request stats (+ hourly series), SQL summary, readiness |
| `GET /api/admin/users?q&limit&offset` | list/search users with trip counts |
| `PATCH /api/admin/users/{id}` | `role`, `is_active`, `verify_email`; cannot target self; admin needs verified email |
| `POST /api/admin/users/{id}/revoke-sessions` | sign the user out everywhere |
| `DELETE /api/admin/users/{id}` | delete user and trips |
| `GET /api/admin/trips?status&owner` / `DELETE /api/admin/trips/{id}` | trip metadata, delete |
| `GET /api/admin/logs/requests` | filters: status (`4xx` or exact), method, path, user_id, min_ms |
| `GET /api/admin/logs/sql` | filters: q, slow, errors |
| `GET /api/admin/logs/audit` | admin actions |
| `GET /api/admin/system`, `POST /api/admin/system/purge` | read-only non-secret settings; run retention now |

Token fields: request-log rows, trip rows and the overview's `requests` block carry `input_tokens`, `output_tokens`, `llm_calls`; user rows carry `tokens`.

`GET /api/session` now returns `user.role`. Middleware records every request (except `/health`, `/ready`, `/assets`) in `observability`; streamed responses are timed until the last chunk.
