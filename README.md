# Multi-Agent-System-using-LangGraph-MCP-Supervisor-Guardrails-HITL

A demo multi-agent system that uses LangGraph and MCP to implement a travel-planning assistant with a Supervisor, input Guardrails, and Human-In-The-Loop (HITL) approval flows. The project includes a FastAPI frontend, example MCP server, and client helpers to demonstrate how agents, supervisors, and guardrails can be composed into a safe, reviewable planning pipeline.

Key ideas:
- Multi-agent coordination using LangGraph and MCP
- Supervisor agent to manage complex workflows
- Input guardrails to validate user requests
- Human-in-the-loop approval for generated plans

Contents
- `app.py`: FastAPI web frontend and API endpoints
- `backend.py`: core agent orchestration / travel-planner logic
- `mcp_client.py`: client helpers to interact with the MCP server
- `custom_weather_mcp_server.py`: example MCP server for weather checks
- `templates/`, `static/`: frontend UI assets (HTML, JS, CSS)

Features
- Interactive web UI for sending travel planning prompts
- Endpoint for drafting travel plans and separate approval endpoint
- Example MCP server demonstrating domain adapters (weather, checkpoints)

Prerequisites
- Python 3.10+ (Python 3.11 or 3.12 recommended)
- Docker Desktop with the Linux container engine running (for the local PostgreSQL database)
- API keys: Groq is required; Tavily, AviationStack, and OpenWeather are needed only for their respective live-data tools

Quick start (Windows PowerShell)

1. Create the local environment file and add your Groq API key

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

The checked-out project may already have a `.env`; edit it rather than overwriting it. `.env` is ignored by Git and must not be committed.

Set `GROQ_API_KEY` to a key from the Groq Console. `GROQ_MODEL` defaults to `openai/gpt-oss-120b`; choose a model ID available to your API key if you change it. The model list for your key is available from `https://api.groq.com/openai/v1/models`.

LLM prompts are bounded to 5,200 input tokens and responses to 768 tokens to help stay within Groq's on-demand TPM limits. Oversized user or tool context is shortened, so include the most important trip requirements first. Groq applies TPM limits across recent requests; if repeated requests still exceed your plan, wait for the quota window to reset or use a model/tier with a higher limit.

2. Start the local PostgreSQL database

```powershell
docker compose up -d db
docker compose ps
```

The database is exposed only on `127.0.0.1:5433` (mapped to PostgreSQL's container port 5432 to avoid conflicts with an existing local database). Its local connection string and credentials are in `.env`; they are for local development only. The named Docker volume keeps checkpoint data across restarts.

3. Create and activate a virtual environment, then install dependencies

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal and activate again.

4. Run the FastAPI app

```powershell
python app.py
```

Open http://127.0.0.1:8000. The LangGraph PostgreSQL tables are initialized automatically at startup.

Flight search requires `AVIATION_STACK_API_KEY`; `uvx` is installed with the project dependencies. Hotel search requires `TAVILY_API_KEY`; weather tools require `OPENWEATHER_API_KEY`. These integrations are used only when the corresponding agent is selected.

To stop the database without removing its data:

```powershell
docker compose down
```

To remove the local database and all saved checkpoint data, run `docker compose down -v`.

## Hostinger VPS deployment

The production Docker and Nginx setup is documented in [deploy/README.md](./deploy/README.md). It uses the VPS host's PostgreSQL and TLS-terminating Nginx, with the container bound only to `127.0.0.1:8014`.

API Endpoints
- `POST /api/travel` — create or resume a travel planning thread. JSON: `{ "message": "<user prompt>", "thread_id": "optional-thread-id" }`
- `POST /api/travel/approve` — approve or request revisions for a draft. JSON: `{ "thread_id": "<id>", "approved": true|false, "feedback": "optional" }`
- `GET /health` — basic health check and features list

Configuration & environment
- `.env.example` documents the local settings; copy it to `.env` and add your own API keys. Never commit `.env` or put production credentials in the local Compose configuration.

Development notes
- The project keeps synchronous convenience wrappers in `backend.py` while running an async FastAPI server — `nest_asyncio` is applied in `app.py` to allow the sync helpers to call async MCP helpers.
- Tests are not included; to experiment, interact with the web UI or call the API endpoints directly.

Contributing
- Contributions are welcome. Please open issues or pull requests for bug fixes, documentation improvements, or new adapter examples.

License
- This repository follows the license in the `LICENSE` file.

Acknowledgements
- Built as a demonstration of LangGraph + MCP patterns with supervisor and guardrail concepts.

Contact
- For questions or suggestions, open an issue or contact the repository owner.
