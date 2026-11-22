# 06 - Business Workflows

> **Status:** this document is the **baseline audit** of the code before remediation. Most findings referenced here are now fixed; see [13_REMEDIATION_REPORT.md](13_REMEDIATION_REPORT.md) for the current status and evidence.

## Journey A: Happy path (draft -> approve -> final)

1. User describes a trip (UI 01) and submits.
2. Backend creates `thread_id` (`user_<uuid4 hex>`) if none supplied.
3. **Supervisor**: LLM guardrail (allowed?) then LLM routing (agents +
   constraints). Both fall back safely (allow / run all agents).
4. Selected specialists run in fixed order:
   - flight: AviationStack `list_airports` + `list_airlines`, then LLM summary
   - hotel: Tavily search "Best hotels for <query>"
   - weather: LLM destination extraction, then current weather + forecast
   - budget: LLM feasibility analysis using prior results
5. **Itinerary** agent produces a draft; graph pauses at `human_approval`.
6. UI shows draft + approval panel. User approves.
7. **Final** agent polishes and formats 7 sections; response returned.

## Journey B: Revision

Same as A, but the user rejects with feedback. `final_agent` receives the
feedback and regenerates once. There is no second review loop (F-22).

## Journey C: Blocked request

Guardrail returns `allowed:false` -> `guardrail_blocked` node -> END. UI shows
the "Outside travel scope" badge and the reason as the answer; stepper step 2
is marked blocked.

## Backend processing and DB operations

Every step writes a checkpoint (see 05). Resume reads the latest checkpoint.
Nothing else is persisted; there is no business database.

## Error scenarios

| Scenario | Current behaviour |
|---|---|
| Empty message | 400 with message |
| Reject without feedback | 400 (server) and client-side check |
| Guardrail/supervisor JSON parse failure | Fail open; all agents run |
| MCP server/key missing or tool error | Agent substitutes "non-live advice" text; flight returns "unavailable: <exc>" |
| Groq error (e.g. 429 TPM) | Uncaught in budget/itinerary/final -> 500 with raw message |
| Unknown or finished `thread_id` on approve | Library-dependent error -> 500 (not verified) |
| Database down at startup | Import fails; app does not start |
| Database drops later | Shared connection fails until restart (F-13) |
| Page reload during review | Draft UI lost; thread pending but not recoverable (F-18) |
| Nginx rate limit | 429 after ~3 quick calls, then 1 per 12 s per IP |

## Incomplete or divergent behaviour

- Flight agent does not query routes or fares (F-20).
- Forecast covers ~15 hours and ignores travel dates (F-21).
- README says `/api/travel` can "create or resume"; code always starts a run.
