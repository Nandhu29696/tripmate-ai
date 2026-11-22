# 08 - Security and Performance Review (Findings Register)

> **Status:** this document is the **baseline audit** of the code before remediation. Most findings referenced here are now fixed; see [13_REMEDIATION_REPORT.md](13_REMEDIATION_REPORT.md) for the current status and evidence.

Status: **V** = verified from code/commands; **P** = potential (plausible, not
reproduced - the app was not run). Complexity: S/M/L. No Critical findings:
the most serious items (F-01, F-02) would be Critical if the service stores
other people's sensitive data or has a spend cap that matters; today they are
High because the data is trip text and Nginx rate-limits per IP.

| ID | Finding | Sev | St | Module | Evidence | Impact | Recommended fix | Cx |
|---|---|---|---|---|---|---|---|---|
| F-01 | No authentication or authorization | High | V | app.py | no auth code; `deploy/README.md` admits it; `tripmate-location.conf` | Anyone can trigger ~8 LLM + tool calls per plan: cost/quota abuse, Groq TPM exhaustion | API key or session login, per-user quota, global spend cap | M |
| F-02 | `thread_id` is client-supplied and unowned | High | V | app.py:41,44; backend.py:789,826 | any id accepted | Anyone knowing a thread id can read/resume/alter that run | Server-issued signed thread tokens bound to a session; verify ownership | M |
| F-03 | LLM Markdown rendered via `innerHTML`, unsanitised | High | V (sink) / P (exploit) | static/script.js:82 | `element.innerHTML = marked.parse(...)` | Injected tool/web content could execute script in users' browsers | Sanitise with DOMPurify, pin/self-host libs, add CSP | S |
| F-04 | MCP subprocesses inherit full environment | High | V | mcp_client.py:58 | `os.environ.copy()` | Third-party `uvx` package receives `GROQ_API_KEY`, `DATABASE_URL`, other keys | Pass an allowlist (only the key each server needs) | S |
| F-05 | `aviationstack-mcp` run unpinned via `uvx` at runtime | Medium | V | mcp_client.py:92-97 | no version | Supply-chain risk, non-reproducible, first-call download latency/failure | Pin version, preinstall in image, verify hashes | S |
| F-06 | Tavily key embedded in URL query | Medium | V | mcp_client.py:86-89 | `?tavilyApiKey=` | Key can leak via logs/proxies/tracebacks | Use auth header if supported by the endpoint; scrub logs | S |
| F-07 | Raw exception text returned to clients | Medium | V | app.py:93,131 | `"error": str(exc)` | Leaks internals (DB/host/library messages) | Generic message + correlation id; log details server-side | S |
| F-08 | Prompt injection; guardrail is an LLM and fails open | Medium | P | backend.py:156-190,209-236 | direct interpolation; `allowed=True` on error | Guardrail bypass, instruction hijack via tool output | Delimit untrusted text, native structured output, fail closed on parse errors, output checks | M |
| F-09 | No input length limits; full text persisted | Medium | V | app.py:39-47; backend.py:796 | unbounded `str` fields | Storage bloat, cost; only Nginx 256k cap | `max_length` on fields; truncate before storing | S |
| F-10 | No security headers; CDN scripts w/o SRI, `marked` unpinned | Low | V | deploy/nginx/*.conf; index.html:182-183 | none present | Clickjacking/MIME/supply-chain exposure | Add CSP, HSTS, X-Frame-Options, X-Content-Type-Options; SRI or self-host | S |
| F-11 | Indefinite retention of prompts/plans; no delete path | Medium | V | backend.py:719-728 | append-only checkpoints | Privacy/compliance exposure, DB growth | Retention job, user delete endpoint, document data handling | M |
| F-12 | Blocking sync `graph.invoke` inside `async def` routes | High | V | app.py:59-76,98-114 | no threadpool/await | One 30-60 s plan freezes the event loop, including `/health` (3 s check x3 -> container marked unhealthy) | Use `def` routes (threadpool) or `ainvoke` with async checkpointer | M |
| F-13 | Single shared DB connection, no reconnect/pool | High | V | backend.py:720-725 | module-level `psycopg.connect` | Postgres restart/idle drop breaks all requests until app restart; `psycopg_pool` is pinned but unused | `ConnectionPool` with checks; reconnect handling | M |
| F-14 | New asyncio loop and likely new MCP session/process per tool call | Medium | V (pattern) / P (cost) | backend.py:328-329,407-413; mcp_client.py:165,245 | `asyncio.run` per call; `get_tools` then `ainvoke` | Added latency; stdio subprocess spawns; nest_asyncio fragility | Persistent MCP sessions; make nodes async | L |
| F-15 | Independent agents run sequentially | Medium | V | backend.py:698-709 | linear edges | Latency = sum of all calls | Fan-out flight/hotel/weather in parallel, join before budget | M |
| F-16 | 768-token output cap and 1200-token truncation vs. long multi-section plans | Medium | V | llm_utils.py:8; backend.py:525,634 | caps | Truncated/thin itineraries; truncation marker can appear in user text | Raise caps per node, per-day generation, remove marker from final answer | S |
| F-17 | No LLM/MCP timeouts, retries or 429 mapping | Medium | V | backend.py:62; mcp_client.py:71-119 | defaults | Hangs; Groq 429 appears as 500 | Set `timeout`, `max_retries`, backoff; map 429 -> 503 + Retry-After | S |
| F-18 | Thread reuse and lost approval state after reload | Medium | V (code) | script.js:1,35,215; backend.py:792-815 | stored id re-sent; no state endpoint | New prompt reuses an old thread (messages accumulate); pending draft unrecoverable | Fresh id per trip, `GET /api/travel/{id}` to restore state | M |
| F-19 | Approve endpoint does not verify pending state; not idempotent | Medium | P | app.py:98-133; backend.py:820-840 | no check | Unknown/finished thread or double submit -> 500 or odd re-run | Check `get_state().next/tasks` before resuming; return 404/409 | S |
| F-20 | Flight agent never queries routes/fares | Medium | V | backend.py:328-338 | lists global airports/airlines, truncated to 500 tok | Data is an arbitrary slice; results mostly model memory yet presented as flight info | Use route/flight tool with origin/destination, or label as non-live | M |
| F-21 | Weather forecast = first 5 entries (~15 h), no dates; destination re-extracted | Medium | V | custom_weather_mcp_server.py:131; mcp_client.py:304-330 | `[:5]`; separate LLM call ignoring `trip_constraints` | Irrelevant forecast; country names may fail city lookup | Use constraints destination, geocode, daily summary for trip window | M |
| F-22 | Revision is single-pass (no loop back to itinerary) | Low | V | backend.py:711-713 | `human_approval -> final_agent` | Weak HITL: user cannot iterate | Conditional edge back to itinerary until approved (cap iterations) | M |
| F-23 | `llm_calls` undercounted | Low | V | backend.py:437-444 | weather node returns no count | Misleading metrics | Count every call centrally in `_llm_text` wrapper | S |
| F-24 | Duplicated config and LLM setup | Low | V | backend.py:5-7,53-66; mcp_client.py:20-35,71-75 | two `load_dotenv`, certifi, two `ChatGroq` | Drift risk | Single `config.py`/`llm.py` | S |
| F-25 | Unused dependencies; no lockfile for transitives | Low | V | requirements.txt | `langchain-community`, `langchain-tavily`, `tavily-python`, `airportsdata`, `pycountry`, `psycopg_pool` not imported | Larger image, attack surface, non-reproducible builds | Remove unused; use `pip-compile`/`uv lock` | S |
| F-26 | Cosmetic: "Local workspace" label in prod; `/favicon.ico` returns `{}` | Low | V | index.html:23; app.py:149 | static | Confusing UX | Configurable label; serve the SVG/204 | S |
| F-27 | No tests, linting or CI/CD | Medium | V | repo (no `tests/`, no `.github/`) ; README "Tests are not included" | none | Regressions undetected; manual deploys | pytest for routing/serialisation, mocked LLM/MCP; GitHub Actions lint+test+build | M |
| F-28 | Print-only logging; static `/health`; no metrics/tracing | Medium | V | app.py:86-87,136-146 | `print`, no DB/LLM probe | Hard to diagnose; false "healthy" | Structured logging with request id, readiness probe checking DB, token/latency metrics | M |
| F-29 | Deployment hardening gaps: `:latest` tag, host networking, no backup/rollback automation | Low | V | docker-compose.prod.yml:11,15; deploy.sh | as listed | Slow rollback; larger blast radius | Version tags, DB backup step, bridge network + published loopback port | M |
| F-30 | Import-time side effects (DB connect, key checks) | Low | V | backend.py:53-57,719-728 | module-level code | Untestable, slow failure modes | FastAPI lifespan startup; lazy init | S |
| F-31 | Repo hygiene: 7 MB `demo.excalidraw` tracked; public host details in deploy docs; untracked `Project Details.xlsx` | Low | V | repo root; deploy/README.md:19 | - | Bloat, minor info disclosure | Move assets out/LFS; trim infra detail; decide on xlsx | S |
| F-32 | Two sequential supervisor LLM calls (guardrail then routing) | Low | V | backend.py:178,239 | two invokes | Extra latency/cost | Merge into one structured call | S |

## Positive controls (verified)

Non-root container, `cap_drop: ALL`, `no-new-privileges`, `noexec` tmpfs,
loopback-only bind, Nginx body cap and API rate limit, docs routes hidden,
secrets git-ignored and absent from history, `.dockerignore` excludes env
files, pinned dependency versions match the installed venv.
