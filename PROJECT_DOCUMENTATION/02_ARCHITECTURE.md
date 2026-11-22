# 02 - Architecture

> **Status:** this document is the **baseline audit** of the code before remediation. Most findings referenced here are now fixed; see [13_REMEDIATION_REPORT.md](13_REMEDIATION_REPORT.md) for the current status and evidence.

## System context

```mermaid
flowchart LR
  B[Browser SPA] -->|HTTPS| N[Nginx: TLS, rate limit]
  N -->|127.0.0.1:8014| F[FastAPI app.py]
  F --> G[LangGraph travel_graph]
  G --> Q[Groq LLM API]
  G --> M[mcp_client.py]
  M -->|streamable HTTP| T[Tavily MCP]
  M -->|stdio: uvx| A[AviationStack MCP]
  M -->|stdio: python| W[Weather MCP] --> O[OpenWeather REST]
  G <--> P[(PostgreSQL checkpoints)]
```

## Graph

```mermaid
flowchart TD
  S([START]) --> SUP[supervisor: guardrail + routing]
  SUP -->|blocked| GB[guardrail_blocked] --> E([END])
  SUP --> FL[flight] --> HO[hotel] --> WE[weather] --> BU[budget] --> IT[itinerary]
  SUP -.skips unselected.-> IT
  IT --> HA{{human_approval: interrupt}} --> FA[final_agent] --> E
```

Agents execute strictly in `AGENT_ORDER` (`backend.py:109`); the supervisor
only decides which are skipped. `itinerary_agent` is always appended.

## Request sequence (draft then approval)

```mermaid
sequenceDiagram
  participant U as Browser
  participant API as FastAPI
  participant G as LangGraph
  participant L as Groq
  participant M as MCP servers
  participant DB as PostgreSQL
  U->>API: POST /api/travel {message, thread_id?}
  API->>G: invoke(initial state, thread_id)
  G->>L: guardrail, supervisor
  G->>M: flight/hotel/weather tools
  G->>L: flight, budget, itinerary
  G->>DB: checkpoint after every step
  G-->>API: __interrupt__ (draft)
  API-->>U: requires_approval=true + draft
  U->>API: POST /api/travel/approve {thread_id, approved, feedback}
  API->>G: invoke(Command(resume))
  G->>DB: load checkpoint
  G->>L: final_agent
  G-->>API: final_response
  API-->>U: final plan
```

## Layers

- **Frontend:** static page; state in three JS globals and one
  `localStorage` key. No framework, no build step.
- **API:** two POST endpoints plus health. Pydantic validation only.
- **Orchestration:** one compiled graph with a Postgres checkpointer.
- **Tools:** MCP servers, each loaded independently so one failure degrades
  only the agent that needs it.
- **Cross-cutting:** token budgeting (`llm_utils.py`), `print` logging,
  fail-open guardrail/supervisor, per-agent degradation messages.

## Notable design traits

1. Sync agent functions bridge to async MCP via `asyncio.run` +
   `nest_asyncio` (`app.py:15-17`).
2. Routes are `async def` but call synchronous `graph.invoke` (see F-12).
3. One module-level psycopg connection is shared by the whole process (F-13).
4. Not present: RAG, vector DB, long-term memory, background jobs, file
   storage, auth, caching.
