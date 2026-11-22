# TripMate AI - Multi-Agent Travel Planner (LangGraph + MCP)

A multi-agent travel-planning assistant built with LangGraph and MCP. A **Supervisor** applies an input **guardrail** and picks the specialist agents, the research agents run **in parallel**, and a **human approves or revises** the draft itinerary (up to two revision rounds) before the final plan is produced.

Key ideas:
- Multi-agent coordination with LangGraph; live data through MCP servers (Tavily, AviationStack, OpenWeather)
- Supervisor + guardrail in one structured LLM call, fail-closed on unparseable output
- Human-in-the-loop approval with a revision loop and restorable drafts
- Live progress while a plan is built (streamed), and source-linked hotel suggestions
- Access key, signed sessions, per-owner trips, quotas, retention and delete

## Contents
- `app.py`: FastAPI app, routes, security headers, lifespan
- `backend.py`: LangGraph workflow, agents, trip service (start/resume/restore/delete/purge)
- `mcp_client.py`: persistent MCP sessions on a private event loop
- `custom_weather_mcp_server.py`: OpenWeather MCP server (current weather + daily forecast)
- `config.py`: settings, logging, shared LLM client
- `llm_utils.py`: token budgeting, prompt fencing, per-node LLM call counting
- `security.py`: session tokens, access key, quotas, login throttling
- `store.py`: thread ownership registry (`tripmate_threads` table)
- `templates/`, `static/`: UI (libraries are self-hosted in `static/vendor/`)
- `tests/`: pytest suite (no network or database needed)
- `deploy/`: production runbook, `deploy.sh`, Nginx fragments
- `PROJECT_DOCUMENTATION/`: architecture, API, security review and remediation report

## Prerequisites
- Python 3.12
- Docker Desktop with the Linux engine running (for the local PostgreSQL database)
- A Groq API key. Tavily, AviationStack and OpenWeather keys are optional and only needed for their live-data tools.

## Quick start (Windows PowerShell)

1. Create the environment file and add your Groq key

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

`.env` is ignored by Git and must not be committed. `GROQ_MODEL` defaults to `openai/gpt-oss-120b`; for `gpt-oss` models `LLM_REASONING_EFFORT` defaults to `low` so hidden reasoning tokens do not eat the answer budget.

2. Start the local database

```powershell
docker compose up -d db
```

PostgreSQL is exposed only on `127.0.0.1:5433`. `docker compose down -v` deletes all saved trips.

3. Install and run

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python app.py
```

Open http://127.0.0.1:8000. With `APP_ACCESS_KEY` empty (the default for local use) the app is open and each browser gets an anonymous session; set `APP_ACCESS_KEY` to require a key. Tables are created automatically at startup.

Flight data uses the version-pinned `aviationstack-mcp` server, started through `uvx` (installed by the `uv` dependency; the first run downloads Python 3.13 for it). In Docker it is pre-installed in the image.

## Tests and lint

```powershell
python -m pytest -q      # 73 tests, no network or database
ruff check .
```

CI (`.github/workflows/ci.yml`) runs lint, a script syntax check, the tests and a Docker build.

## API

All `/api/travel*` endpoints need a session cookie from `/api/session` and only ever touch the caller's own trips (other trips return 404).

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/session` | Auth status; in open mode issues an anonymous session |
| POST | `/api/session` | Sign in `{access_key}` (throttled) |
| DELETE | `/api/session` | Sign out |
| POST | `/api/travel` | New trip `{message}`; pauses for review (`requires_approval`) |
| POST | `/api/travel/stream` | Same, but streams live progress as NDJSON: `{type:"progress",node,label,state}` lines, then one `{type:"result",...}` or `{type:"error",status,error}` |
| POST | `/api/travel/approve` | `{thread_id, approved, feedback?}`; a rejection returns a revised draft (max `MAX_REVISIONS`) |
| POST | `/api/travel/approve/stream` | Streaming variant of approve (404/409/400 are returned as normal HTTP statuses before the stream opens) |
| GET | `/api/travel/threads` | List your trips |
| GET | `/api/travel/{thread_id}` | Restore a trip (draft awaiting review, or final plan) |
| DELETE | `/api/travel/{thread_id}` | Delete a trip and its checkpoints |
| GET | `/health` | Liveness (no dependencies) |
| GET | `/ready` | Readiness (checks the database) |

Errors are `{success:false, error, request_id}`; 401 not signed in, 404 not found/not yours, 409 wrong state (e.g. already approved), 429 quota or provider rate limit (with `Retry-After`), 503 provider unavailable, 500 generic with a reference id.

## Configuration

Required: `GROQ_API_KEY`, `DATABASE_URL`. Production also needs `SESSION_SECRET` (and should set `APP_ACCESS_KEY`). Optional tuning (defaults): `MAX_PLANS_PER_SESSION_PER_HOUR=5`, `MAX_PLANS_PER_DAY=300`, `RETENTION_DAYS=30`, `MAX_REVISIONS=2`, `GUARDRAIL_FAIL_OPEN=false`, `LLM_TIMEOUT_SECONDS=60`, `LLM_MAX_RETRIES=2`, `LLM_OUTPUT_TOKENS=1000`, `LLM_OUTPUT_TOKENS_ITINERARY=2000`, `LLM_OUTPUT_TOKENS_FINAL=2600`, `LLM_MAX_INPUT_TOKENS=5200`, `MAX_MESSAGE_CHARS=4000`, `DB_POOL_MAX=10`. See `.env.example` and `.env.production.example`.

Quotas are counted in process memory (single worker). Run one worker, or move the counters to a shared store before scaling out.

## Production deployment

See [deploy/README.md](./deploy/README.md): Docker (host network, loopback only), Nginx with TLS and rate limits, versioned images, pre-deploy database backup and one-command rollback.

## Operating notes
- The UI uses the `/stream` endpoints. The run is not tied to the connection: if the tab is closed the plan still finishes and appears under "Your trips".
- Logs go to stdout with a request id per line (`docker compose logs -f app`); each LLM call logs latency, tokens and finish reason.
- Saved trips (prompts and plans) are purged after `RETENTION_DAYS`; users can delete a trip any time.
- Prompts and generated plans are sent to Groq, and search text to Tavily; inform users accordingly.

## License
See `LICENSE`.
