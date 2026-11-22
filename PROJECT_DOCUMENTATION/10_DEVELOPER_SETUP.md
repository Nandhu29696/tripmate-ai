# 10 - Developer Setup (from the existing README, validated against the code)

> **Status:** this document is the **baseline audit** of the code before remediation. Most findings referenced here are now fixed; see [13_REMEDIATION_REPORT.md](13_REMEDIATION_REPORT.md) for the current status and evidence.

Prerequisites: Python 3.12, Docker Desktop (for local Postgres), a Groq API
key. Tavily, AviationStack and OpenWeather keys are optional and only needed
when the corresponding agent runs.

```powershell
Copy-Item .env.example .env            # then set GROQ_API_KEY (and optional keys)
docker compose up -d db                # Postgres on 127.0.0.1:5433
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py                          # http://127.0.0.1:8000
```

Notes
- The app fails at import if `GROQ_API_KEY` or `DATABASE_URL` is missing or
  Postgres is unreachable (F-30).
- `uvx` comes from the pinned `uv` package; the first AviationStack call
  downloads its MCP package.
- `docker compose down -v` deletes all saved checkpoints.
- Quick checks: `GET /health`; `python -c "import asyncio, mcp_client; asyncio.run(mcp_client.get_all_tools())"`
  tests each MCP server (calls external services).
- There is no test suite; add one before refactoring (F-27).

Where to change things
- New agent: add node + `AGENT_ORDER`/`KNOWN_AGENTS` + supervisor prompt +
  `AGENT_LABELS` in `script.js`.
- New MCP tool: add server in `mcp_client.py` `client` config + wrapper.
- Token limits: `llm_utils.py` constants.
