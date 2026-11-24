# 13 - Remediation Report

Work done on branch `tripmate-hardening` (nothing committed, nothing deployed).
Documents 01-12 describe the **baseline audit**; this report records what was
changed and how each change was verified.

## Verification summary

| Check | Result |
|---|---|
| Automated tests (`pytest`, no network/DB) | 59 pass; `ruff check .` clean; `node --check static/script.js` OK |
| Real PostgreSQL (embedded server in a scratch dir): `init_backend()`, pool, checkpointer, registry DDL | Works; found and fixed a real multi-statement DDL bug (tests with fakes could not catch it) |
| Live end-to-end with real Groq + real MCP + real Postgres | Draft, reject, revised draft, approve, double-approve rejected, intruder blocked, off-topic blocked, delete removes all checkpoint rows |
| Pool recovery after the server killed its connections | Recovered (registry, readiness and checkpointer reads all succeeded) |
| Real HTTP server (uvicorn + lifespan) | Headers, static assets, session cookie, auth, validation, cross-origin block all as designed |
| Real browser (Playwright/Chromium) against the live server | 25/25 checks: login, XSS payload neutralised, revision loop, PDF export under CSP, reload restore, 0 CSP violations, 0 console errors |
| Live MCP | All three servers start; Tavily accepts header auth; pinned AviationStack runs via uvx; second weather call 0.4 s vs 4.1 s first (session reuse) |

**Not verified:** Docker image build and `docker compose up` (Docker daemon was
not running; compose config and `deploy.sh` syntax were checked only),
`nginx -t` and the Nginx fragments on a real server, Certbot/TLS, the VPS, and
behaviour under multiple workers. CI has not run on GitHub.

## Findings status

| ID | Status | What changed | Evidence |
|---|---|---|---|
| F-01 | Fixed | `APP_ACCESS_KEY` login, HMAC-signed HttpOnly SameSite=Strict session cookie, per-session hourly quota, global daily cap, login throttling (`security.py`, `app.py`) | `tests/test_api.py`, live curl: 401 without cookie, 429 after quota/brute force |
| F-02 | Fixed | Server-issued `trip_<uuid>` ids; `tripmate_threads` ownership table; every trip call checks the owner; same 404 for "missing" and "not yours" | tests + live intruder check |
| F-03 | Fixed | DOMPurify around `marked`; libs self-hosted and pinned; strict CSP; no inline handlers | Browser test: `<script>`, `<iframe>`, `onerror`, `javascript:` all stripped, nothing executed |
| F-04 | Fixed | Allowlisted environment for MCP subprocesses plus only the key each needs | `test_subprocess_env_does_not_leak_other_secrets` |
| F-05 | Fixed | `aviationstack-mcp@1.8.1` pinned (`AVIATIONSTACK_MCP_VERSION`); installed into the Docker image so there is no runtime download | live run via pinned uvx; Docker part unverified |
| F-06 | Fixed | Tavily key sent as `Authorization: Bearer`, not in the URL | live Tavily session + search succeeded |
| F-07 | Fixed | Generic errors with a request id; details only in logs | `test_internal_errors_do_not_leak_details` |
| F-08 | Mitigated | Guardrail+supervisor in one call, untrusted text fenced in tagged blocks, tag break-out stripped, deterministic injection pre-check, constraints sanitised, **fail-closed** on unparseable output (`GUARDRAIL_FAIL_OPEN` opt-in) | tests; live off-topic block. Prompt injection cannot be fully eliminated with an LLM guardrail |
| F-09 | Fixed | Pydantic limits: message 4000, feedback 2000, strict thread-id pattern | tests + live curl |
| F-10 | Fixed | CSP, X-Frame-Options, nosniff, Referrer/Permissions-Policy, HSTS over HTTPS; SRI is moot (libs self-hosted) | `test_security_headers...`, live headers |
| F-11 | Fixed | `DELETE /api/travel/{id}` (also deletes checkpoints), retention purge (`RETENTION_DAYS`, default 30, every 6 h) | live: 0 checkpoint rows after delete; purge test |
| F-12 | Fixed | Routes are plain `def` (thread pool), so the event loop is never blocked | `test_health_responds_while_a_plan_is_running` |
| F-13 | Fixed | `psycopg_pool.ConnectionPool` with `check_connection` | live outage test |
| F-14 | Fixed | One MCP event-loop thread, one long-lived session per server, retry once on a dead session; `nest_asyncio` removed | live: 4.1 s first call, 0.4 s next |
| F-15 | Fixed | Flight, hotel and weather run in parallel and join before budget | routing tests; live run |
| F-16 | Fixed | Per-stage output budgets, `reasoning_effort=low` for gpt-oss, hard word limits and "no tables" style rules, visible note if still truncated | Live runs: before, 4 of 5 calls ended `finish=length` and the plan was cut mid-table; after, every call ends `finish=stop` |
| F-17 | Fixed | LLM timeout and retries; MCP call timeouts; Groq 429 maps to 429 + `Retry-After`, timeouts/connection errors to 503 | tests with real `groq` exception classes |
| F-18 | Fixed | Fresh id per trip; `GET /api/travel/threads` and `GET /api/travel/{id}`; UI restores the pending draft after reload and lists past trips | browser + live tests |
| F-19 | Fixed | Resume checks ownership and that an interrupt is pending; per-thread lock; 404/409 instead of 500 | tests + live double-approve |
| F-20 | Fixed (limits below) | Offline airport resolution (`airportsdata`), then AviationStack `list_routes`, else today's departure board filtered to the destination; honest "unavailable" text; 6 h cache; plan-restriction remembered | live run (this plan lacks `list_routes`; fallback used). Fares are still not available from the API |
| F-21 | Fixed | Weather uses the supervisor's destination city; daily min/max/condition/rain-chance summary for up to 5 days | live forecast output; unit test |
| F-22 | Fixed | Reject loops back to the itinerary agent up to `MAX_REVISIONS` (2), then finalises with the feedback | live + browser |
| F-23 | Fixed | Each node returns its own LLM-call count via a decorator; additive reducer | tests |
| F-24 | Fixed | `config.py` (env, logging, single cached `ChatGroq`) | code |
| F-25 | Fixed | Removed `langchain`, `langchain-community`, `langchain-tavily`, `tavily-python`, `pycountry`, `nest_asyncio`; kept `airportsdata`/`psycopg_pool` (now used); `requirements.lock` pins every transitive package | clean import and tests |
| F-27 | Fixed | 59 tests, `ruff.toml`, `pytest.ini`, GitHub Actions workflow | local run; CI not yet run on GitHub; coverage not measured |
| F-28 | Fixed (scoped) | Logging with request ids, access log, per-LLM-call latency/tokens/finish reason, `/ready` DB probe | live. No metrics/tracing backend (not added) |
| F-29 | Partly fixed | Versioned image tags, pre-deploy `pg_dump` backups with retention, `deploy.sh rollback`, `/ready`-based health wait. **Host networking retained deliberately** (a bridge needs a host PostgreSQL change) | `bash -n`, `docker compose config` only |
| F-30 | Fixed | No import-time side effects; startup/shutdown in the FastAPI lifespan | tests import freely; live startup/shutdown |
| F-32 | Fixed | One supervisor call instead of two | tests |

Not requested, so left as is: F-26 (static "Local workspace" label was
replaced incidentally by "Your workspace"; the favicon stub now returns 204)
and F-31 (7 MB `demo.excalidraw`, public host details in the deploy docs).

## Issues found while verifying (not in the original audit)

1. Multi-statement DDL fails under `prepare_threshold=0` - fixed (statements run one by one).
2. `list_routes` and rate limits return `{"ok": false}` payloads instead of raising, so the old pattern would have passed an error message to the LLM as data - now converted to `ToolError`.
3. MCP results were raw content-block lists - now flattened to text.
4. The first plan budgets still truncated real plans; prompts needed format rules, not just bigger limits.
5. My earlier guess that `list_airports` might not exist in the pinned release was wrong (tool names are set by decorator `name=`); the original names are correct.

## Behaviour changes to be aware of

- `thread_id` is no longer accepted from clients; `POST /api/travel` always starts a new trip.
- A rejection now returns another draft (`requires_approval: true`) instead of the final plan.
- Unparseable guardrail output now blocks the request instead of allowing it.
- Responses and log lines carry a `request_id`; production needs `SESSION_SECRET`.
- The Nginx rate limit now applies 5/min only to the two plan endpoints (60/min elsewhere), because page reloads call several light endpoints.

## Residual risks

- Quotas and login throttling are per process (single worker only).
- With `APP_ACCESS_KEY` empty, an attacker who discards cookies is limited only by the daily cap and Nginx.
- LLM guardrails remain probabilistic; the model can still be steered by search results.
- Free-tier AviationStack limits make flight data best-effort (rate limit hit during testing).
- Base image CVEs reported by the IDE for `python:3.12-slim` are not addressed here; rebuild regularly.
- Hotel results are still raw Tavily JSON truncated to 700 tokens (possible follow-up).


## Follow-up round: deploy verification, hotel results, live progress

**Deploy path (verified with Docker, not just reviewed)**

| Check | Result |
|---|---|
| `docker build` of the production image | Builds; the pinned `aviationstack-mcp` binary is on PATH and starts |
| Container as in production (uid 10001, `--cap-drop ALL`, `no-new-privileges`, `noexec` tmpfs) against Postgres 17 | `/health`, `/ready` ok; effective capabilities `0`; CSP header present |
| tiktoken with `--network none` | Works (encoding baked into the image) |
| `nginx -t` on the real fragments, then live through Nginx | Passes; `/ready`, `/docs`, `/openapi.json` return 404; light zone passes 12 rapid requests |
| GitHub Actions run | **Not run** (needs a push; nothing was pushed) |

Bugs found only by running the real stack (both fixed):

1. **Strict rate limit never applied.** `location ^~ /api/` beats a regex location, so the 5/min limit on plan endpoints was bypassed (6 rapid POSTs all reached the app). The strict limit is now a regex location and `/api/` is a plain prefix. Re-tested: 401 x4 then 429.
2. **CSRF check rejected real browsers behind Nginx on a non-default port.** `proxy_set_header Host $host` drops the port, so the app saw `Host: 127.0.0.1` against `Origin: http://127.0.0.1:18080` and returned 403 on every POST. Now `$http_host`. Re-tested: browser-style Origin 200, foreign Origin still 403. Production on 443 was not affected, but any port change or extra proxy would have been.

**Hotel results (F-new: quality).** Tavily JSON (scores, images, empty fields) is now reduced to up to 5 bullets of title + snippet + source URL (http/https only); the search query is built from the supervisor's constraints (city, budget, style, preferences) instead of the whole user message; the final prompt requires source links and forbids inventing hotels. In a live run the final plan's hotel section carried a real source link and labelled anything without a source as a general recommendation.

**Live progress.** New `POST /api/travel/stream` and `POST /api/travel/approve/stream` (NDJSON). The graph runs in a background thread and events are relayed through a queue, so closing the tab does not abort a plan; the result is saved and restorable. Pre-stream checks (auth, validation, quota, ownership, "no draft waiting") still return real HTTP statuses; failures after the stream opens arrive as a safe `error` event. The UI shows a checklist with spinner/tick per stage (research agents visibly run together; revisions say "Revising your itinerary"). `proxy_buffering off` and `X-Accel-Buffering: no` keep Nginx from holding the stream.

Verification: 73 automated tests; a live run through Nginx showed events spread over 10.7 s; a real browser run against the full stack (UI to Nginx to app to Groq, MCP and Postgres) passed 22/22 checks, including 8 distinct progress snapshots, parallel stages, revision label, source links in the final plan, PDF export, reload restore and delete from the UI.

Residual: the model still sometimes formats the hotel section as a table despite the style rule (harmless now that output is no longer truncated); one hotel in the sampled plan had no source and was labelled as a general recommendation, as instructed.


## Follow-up round: user accounts, email/password and Google sign-in

Replaces the shared access key and anonymous sessions. Design and setup steps are in the project README ("Accounts and Google sign-in").

**What was built:** email + password registration with emailed confirmation, sign-in, forgot and reset; Google OAuth 2.0 / OpenID Connect (PKCE, state, nonce, ID-token verification with `google-auth`, `email_verified` required); per-user trips and quotas; session revocation on password reset; account deletion; SMTP mailer; throttles per IP and per account; Nginx limits for the password endpoints and `/auth/`; `PUBLIC_BASE_URL` required in production so links and the redirect URI never come from a forged Host header.

**Security decisions worth knowing:**
- Registration and forgot-password answer identically whether or not the email exists, and do the same work (the password is always hashed).
- Pre-hijack defence: if someone registered a victim's email with their own password and the victim later signs in with Google, the unconfirmed account's password is removed before linking.
- A Google email already linked to a different Google identity is never merged.
- Reset tokens and confirmation tokens are hashed at rest, single-use, expiring, and purpose-bound.
- Rejected (invalid) sign-up input is not counted against the sign-up throttle; only valid attempts, which cost an email and a database write, are.

**Verification**

| Check | Result |
|---|---|
| Automated tests | 124 pass (about 50 new: hashing, policy, tokens, enumeration, throttles, revocation, every Google failure mode, deletion, SMTP) |
| Real PostgreSQL | New tables created; no orphan trips, checkpoints or tokens after account deletion |
| Real browser, full stack, real LLM | 36 of 37 checks passed. The 37th was my test counting every user's trips; a direct query confirmed zero orphans. Covered: sign-up, weak password, unconfirmed sign-in, confirmation link, used link, real plan, sign-out/in, second device sees the same trip, forgot/reset, other device signed out by the reset, old password rejected, deletion, no CSP violations or console errors |
| Real Nginx in front of the app | New locations work: auth zone allowed 5 then returned 429, `/auth/` reaches the app with the port preserved in the redirect URI, plan zone and light zone unchanged |
| Google redirect | Verified to carry state, nonce, S256 challenge, client id and callback URI, and never the client secret |

**Not verified:** the real Google consent screen and callback (no Google credentials were available; the exchange and ID-token verification are tested with Google mocked), delivery through a real SMTP server (tested with a fake SMTP client), and Google "In production" publishing.

**Bugs found while verifying (fixed):** the planner section flashed for signed-out visitors before the session check completed (now hidden by default); a used or expired confirmation link was silently ignored for a signed-in user (now shows a notice); invalid sign-up attempts consumed the sign-up throttle.

**Behaviour changes:** `APP_ACCESS_KEY`, `POST /api/session` and anonymous sessions are removed; `MAX_PLANS_PER_SESSION_PER_HOUR` is now `MAX_PLANS_PER_USER_PER_HOUR` (old name still read); the session cookie is `SameSite=Lax` (needed for the Google and email-link redirects; state-changing requests are POST/DELETE with an Origin check); `deploy.sh` now requires `PUBLIC_BASE_URL` and warns when Google or SMTP settings are empty.

**Residual risks:** the session is a stateless token, so signing out clears the cookie but a stolen cookie stays valid until it expires (12 h) or the password is reset; sign-up throttles are per process; open sign-up means anyone can create an account, so the per-user and daily caps are the cost controls (a CAPTCHA such as Cloudflare Turnstile is the next step if abuse appears).

## Follow-up round: React frontend with authentication

Replaced the vanilla-JS page with a React 19 + TypeScript + Vite single-page app (see `03_FRONTEND.md`). The backend API is unchanged except that FastAPI now serves the built app (`spa.py`) and the Docker build compiles it in a Node stage.

**Verification**

| Check | Result |
|---|---|
| Frontend type-check (strict) and production build | Clean; ~145 KB gzipped, no inline scripts |
| Frontend tests (Vitest + Testing Library) | 75 pass: stream reader (split chunks, errors, 401, interruption), URL bootstrap, hostile Markdown, route guards, every auth form state, planning, review workflow, reload handling, account deletion |
| Backend tests | 146 pass (23 new for serving the app: client routes, asset caching, JSON 404s for API paths, path traversal, missing build) |
| Real browser, full stack, real LLM (Playwright) | 51 of 51 checks: guards, deep-link return, sign-up with strength meter, confirmation email, live parallel progress, revision and approval, reload restore, print layout, dark theme persistence, second device on a phone viewport with drawer, password reset revoking the other device, Google redirect protections, account deletion with no orphaned rows, no CSP violations or console errors |
| Docker build with the Node stage | Builds (`npm ci` + type-check + `vite build` inside the image) |

**Bugs the tests and real browser found, all fixed:**

1. *Deep-link return never worked.* After sign-in, the guard bounced to `/` before the login page could send the user back. Found by an integration test.
2. *Reloading a trip page showed a stale draft.* The router keeps navigation state across reloads, so an approved trip reopened as the old draft with a review panel. Now the handed-over trip is only a first paint and is always revalidated; a late response never overwrites a result the user already triggered. Found by the real browser.
3. *Short passwords got no feedback.* The strength meter was hidden for anything under the minimum; it now says "Too short".
4. *Phone layout scrolled sideways* on pages with long unbroken text (a URL in a title, code blocks): 1158 px wide on a 390 px screen. Found by a probe with worst-case content.
5. *Closed mobile drawer was keyboard-reachable.* It was only moved off-screen; now `visibility: hidden` while closed.

**Behaviour and operations notes**
- `/static/*` and the Jinja templates are gone; `/assets/*` (hashed, immutable cache) and `index.html` (no-cache) replace them. Nginx needs no change.
- Without a build, the API serves a clear placeholder page (HTTP 503) instead of failing.
- On Windows, a project path containing `&` breaks npm's `cmd.exe` scripts; Docker and CI are unaffected.
- Not verified: behaviour on real mobile hardware and in Safari/Firefox (Chromium only), and screen-reader testing (semantics were checked by test, not by assistive technology).
