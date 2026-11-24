# TripMate AI - Multi-Agent Travel Planner (LangGraph + MCP)

A multi-agent travel-planning assistant built with LangGraph and MCP. A **Supervisor** applies an input **guardrail** and picks the specialist agents, the research agents run **in parallel**, and a **human approves or revises** the draft itinerary (up to two revision rounds) before the final plan is produced.

Key ideas:
- Multi-agent coordination with LangGraph; live data through MCP servers (Tavily, AviationStack, OpenWeather)
- Supervisor + guardrail in one structured LLM call, fail-closed on unparseable output
- Human-in-the-loop approval with a revision loop and restorable drafts
- Live progress while a plan is built (streamed), and source-linked hotel suggestions
- User accounts (email + password, and Google sign-in), per-user trips and quotas, retention and delete

## Contents
- `app.py`: FastAPI app, routes, security headers, lifespan
- `backend.py`: LangGraph workflow, agents, trip service (start/resume/restore/delete/purge)
- `mcp_client.py`: persistent MCP sessions on a private event loop
- `custom_weather_mcp_server.py`: OpenWeather MCP server (current weather + daily forecast)
- `config.py`: settings, logging, shared LLM client
- `llm_utils.py`: token budgeting, prompt fencing, per-node LLM call counting
- `security.py`: signed session/OAuth-state tokens, quotas, throttling
- `accounts.py`: password hashing (scrypt), user store, one-time email tokens
- `auth_routes.py`: register, confirm email, sign in, forgot/reset password, Google, delete account
- `oauth_google.py`: Google OAuth 2.0 / OpenID Connect (PKCE, state, nonce)
- `mailer.py`: SMTP email (logs the message when SMTP is not configured)
- `web_common.py`: shared helpers (session cookie, current user, error responses)
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

Open http://127.0.0.1:8000 and create an account. Without `SMTP_HOST` the confirmation and reset links are written to the app log (look for `DEV MAIL`), so copy the link from the terminal. Tables are created automatically at startup.

Flight data uses the version-pinned `aviationstack-mcp` server, started through `uvx` (installed by the `uv` dependency; the first run downloads Python 3.13 for it). In Docker it is pre-installed in the image.

## Tests and lint

```powershell
python -m pytest -q      # 124 tests, no network or database
ruff check .
```

CI (`.github/workflows/ci.yml`) runs lint, a script syntax check, the tests and a Docker build.

## API

All `/api/travel*` endpoints need a signed-in user and only ever touch that user's own trips (other trips return 404).

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/session` | Who is signed in, and which sign-in methods are available |
| POST | `/api/auth/register` | `{email, password, name?}`; sends a confirmation link; same reply whether or not the email exists |
| GET | `/auth/verify?token=` | Confirms the email, signs in, redirects to `/?verified=1` |
| POST | `/api/auth/login` | `{email, password}`; generic error; throttled per IP and per account |
| POST | `/api/auth/forgot` | `{email}`; always the same reply; emails a one-hour reset link if the account exists |
| POST | `/api/auth/reset` | `{token, password}`; signs out every other session |
| GET | `/auth/google/login` | Starts Google sign-in (PKCE + state + nonce) |
| GET | `/auth/google/callback` | Google redirects here; creates or links the account |
| POST | `/api/account/delete` | `{confirm: true}`; deletes the user, every trip and its checkpoints |
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

Required: `GROQ_API_KEY`, `DATABASE_URL`. Production also needs `SESSION_SECRET` and `PUBLIC_BASE_URL` (the site's https URL; `deploy.sh` refuses to run without them), plus `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` for Google sign-in and `SMTP_*` for email. Optional tuning (defaults): `MAX_PLANS_PER_USER_PER_HOUR=5`, `MAX_PLANS_PER_DAY=300`, `MIN_PASSWORD_LENGTH=10`, `REGISTER_PER_IP_PER_HOUR=5`, `FORGOT_PER_EMAIL_PER_HOUR=3`, `SESSION_TTL_SECONDS=43200`, `RETENTION_DAYS=30`, `MAX_REVISIONS=2`, `GUARDRAIL_FAIL_OPEN=false`, `LLM_TIMEOUT_SECONDS=60`, `LLM_MAX_RETRIES=2`, `LLM_OUTPUT_TOKENS=1000`, `LLM_OUTPUT_TOKENS_ITINERARY=2000`, `LLM_OUTPUT_TOKENS_FINAL=2600`, `LLM_MAX_INPUT_TOKENS=5200`, `MAX_MESSAGE_CHARS=4000`, `DB_POOL_MAX=10`. See `.env.example` and `.env.production.example`.

Quotas are counted in process memory (single worker). Run one worker, or move the counters to a shared store before scaling out.

## Accounts and Google sign-in

Everyone signs in before using the model, so every plan is tied to a person and counted against their own quota. Two methods share one `users` table:

- **Email + password.** Registration sends a one-time confirmation link (24 h); sign-in is refused until it is used. Passwords are hashed with scrypt, must be 10+ characters, and failed sign-ins are throttled per IP and per account. "Forgot password" emails a one-hour single-use link and signs out every other session. Responses never reveal whether an email is registered.
- **Google.** OAuth 2.0 / OpenID Connect with PKCE, `state` and `nonce`; the ID token's signature, issuer, audience and expiry are checked by `google-auth`, and `email_verified` must be true. A Google sign-in whose email matches an existing confirmed account links to it; if the existing account was never confirmed, its password is removed first, so someone who pre-registered a victim's address cannot keep access.

Trips, quotas and history belong to the user, so they follow the person across devices. "Delete account" removes the user, all trips and their checkpoints.

### One-time Google setup (about 15 minutes)

1. Create a project at https://console.cloud.google.com.
2. **APIs & Services -> OAuth consent screen:** user type **External**; app name, support email, developer contact; add your domain (for example `tripmate-ai.jagoindia.in`) as an authorized domain; add privacy-policy and terms URLs; scopes `openid`, `email`, `profile` only (non-sensitive, no Google verification review). While the app is in **Testing**, only listed test users can sign in; switch to **In production** for everyone.
3. **Credentials -> Create OAuth client ID -> Web application**, with these authorized redirect URIs (exact match, including scheme and path):
   - `http://127.0.0.1:8000/auth/google/callback` (local)
   - `https://tripmate-ai.jagoindia.in/auth/google/callback` (production)
4. Put the values in `.env` / `.env.production` (never in git): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and in production `PUBLIC_BASE_URL=https://tripmate-ai.jagoindia.in`.
5. Email: set `SMTP_HOST`, `SMTP_PORT` (587 STARTTLS or 465 TLS), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` with any transactional provider. Without `SMTP_HOST` the links are only written to the log, which is fine for development and unusable in production.

If the Google variables are empty the "Continue with Google" button is hidden and email sign-in still works.

## Production deployment

See [deploy/README.md](./deploy/README.md): Docker (host network, loopback only), Nginx with TLS and rate limits, versioned images, pre-deploy database backup and one-command rollback.

## Operating notes
- The UI uses the `/stream` endpoints. The run is not tied to the connection: if the tab is closed the plan still finishes and appears under "Your trips".
- Logs go to stdout with a request id per line (`docker compose logs -f app`); each LLM call logs latency, tokens and finish reason.
- Saved trips (prompts and plans) are purged after `RETENTION_DAYS`; users can delete a trip any time.
- Prompts and generated plans are sent to Groq, and search text to Tavily; inform users accordingly.

## License
See `LICENSE`.
