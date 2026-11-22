# 01 - Project Overview

**TripMate AI** (v2.0.0) is a multi-agent travel planner. A Supervisor agent
applies an input guardrail and chooses specialist agents (flight, hotel,
weather, budget, itinerary). A human approves or revises the draft itinerary
(human-in-the-loop) before the final plan is produced.

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 (backend), vanilla JavaScript (frontend) |
| Web | FastAPI 0.136.3, Uvicorn 0.48.0, Jinja2, Pydantic |
| Orchestration | LangGraph 1.2.2 (StateGraph, `interrupt`, `Command`), LangChain 1.3.2 |
| LLM | Groq via `langchain-groq`; default `openai/gpt-oss-120b` |
| Tools | MCP: `langchain-mcp-adapters` 0.3.0, `mcp` 1.28.1 |
| State store | PostgreSQL via `langgraph-checkpoint-postgres` 3.1.0, psycopg 3.3.4 |
| Token budget | `tiktoken` (`o200k_base`) |
| Frontend libs (CDN) | `marked`, `html2pdf.js` 0.10.1 |
| Infra | Docker, Compose, host Nginx + Certbot TLS, Hostinger VPS |

## Folder map

| Path | Role |
|---|---|
| `app.py` | FastAPI app, routes, Pydantic request models. Entry point. |
| `backend.py` | LangGraph state, agents, routing, Postgres checkpointer, API helper functions |
| `mcp_client.py` | `MultiServerMCPClient` configuration, per-tool wrappers, `extract_destination` |
| `custom_weather_mcp_server.py` | FastMCP stdio server wrapping OpenWeather (2 tools) |
| `llm_utils.py` | Token truncation and bounded LLM invocation |
| `templates/index.html`, `static/*` | Single-page UI |
| `Dockerfile`, `compose.yaml`, `docker-compose.prod.yml` | Container build, local DB, production app |
| `deploy/` | `deploy.sh`, Nginx rate-limit zone and proxy locations, runbook |
| `.env.example`, `.env.production.example` | Configuration templates |
| `demo.excalidraw`, `TripMate_AI_User_Manual.docx` | Non-code assets (not analysed in depth) |

## Entry points

- Local: `python app.py` -> uvicorn `127.0.0.1:8000`, `reload=True`.
- Production: `uvicorn app:app --host 127.0.0.1 --port 8014 --proxy-headers`
  (Compose command override).
- Importing `backend.py` has side effects: it requires `GROQ_API_KEY` and
  `DATABASE_URL`, opens the Postgres connection, runs `checkpointer.setup()`
  and compiles the graph.

## Configuration (names only)

Required: `GROQ_API_KEY`, `DATABASE_URL`. Optional: `GROQ_MODEL`,
`TAVILY_API_KEY`, `AVIATION_STACK_API_KEY` (alias `AVIATIONSTACK_API_KEY`),
`OPENWEATHER_API_KEY`. Local-only: `POSTGRES_DB/USER/PASSWORD`.
`.env` and `.env.production` are git-ignored; `git log --all` shows neither
was ever committed.

## Integrations

Groq (LLM); Tavily MCP (remote streamable HTTP); AviationStack MCP (stdio via
`uvx`); custom weather MCP (stdio Python subprocess -> OpenWeather REST).

## Authentication

None. No users, sessions, API keys or roles exist.
