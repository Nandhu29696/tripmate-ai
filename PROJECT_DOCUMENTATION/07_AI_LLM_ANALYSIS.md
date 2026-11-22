# 07 - AI / LLM Analysis

> **Status:** this document is the **baseline audit** of the code before remediation. Most findings referenced here are now fixed; see [13_REMEDIATION_REPORT.md](13_REMEDIATION_REPORT.md) for the current status and evidence.

## Model

Groq `ChatGroq`, model from `GROQ_MODEL` (default `openai/gpt-oss-120b`),
`max_tokens=768`. Instantiated twice: `backend.py:62` and `mcp_client.py:71`
(F-24). No temperature/timeout/retry settings are specified (F-17).

## Agents and prompts

| Node | LLM? | Tools | Output |
|---|---|---|---|
| supervisor | 2 calls (guardrail JSON, routing JSON) | - | `guardrail_*`, `selected_agents`, `trip_constraints`, reasoning |
| flight_agent | 1 | AviationStack list tools | `flight_results` (<=700 tok) |
| hotel_agent | 0 | Tavily search | `hotel_results` (raw, <=700 tok, no LLM summary) |
| weather_agent | 1 (extract destination) | weather current + forecast | `weather_results` |
| budget_agent | 1 | - | `budget_results` |
| itinerary_agent | 1 | - | `itinerary` draft (<=1200 tok) |
| human_approval | 0 | - | interrupt |
| final_agent | 1 | - | `final_response` (<=1200 tok) |

Typical full run: about 8 LLM calls and 5-6 MCP calls, all sequential.
Prompts interpolate user text and tool output directly (no delimiters, no
injection defences). Structured output uses "return strict JSON" plus
first-`{`/last-`}` extraction (`backend.py:127-135`) rather than native
structured output.

## MCP

`MultiServerMCPClient` with Tavily (streamable HTTP, API key in URL),
AviationStack (stdio, `uvx aviationstack-mcp`, unpinned) and the custom
weather server (stdio). Each wrapper loads the tool list for one server, then
calls the tool; with stdio servers this likely starts a new subprocess per
operation (potential; magnitude not measured). Child processes inherit the
entire parent environment (F-04).

## RAG, vector DB, memory

None. "Memory" is LangGraph per-thread checkpoint state. There is no
cross-thread user memory.

## Token usage

`llm_utils.py`: input capped at 5,200 tokens (head+tail kept), output 768.
Each context slice is truncated to 300-1200 tokens. `llm_calls` is returned
but undercounted (weather's extraction call is not counted; failed paths
are not counted). No usage/cost logging.

## Lifecycle

Request -> guardrail -> routing -> tool calls -> specialist LLM calls ->
draft -> checkpoint+interrupt -> human decision -> final LLM call -> response.

## AI risks

Prompt injection through tool output or user text; guardrail fails open;
768-token output cap vs. a multi-day multi-section plan (F-16); flight and
weather "live data" are weaker than the UI implies (F-20, F-21); 429s from
Groq surface as 500s (F-17).
