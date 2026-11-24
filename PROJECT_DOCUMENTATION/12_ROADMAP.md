# 12 - Recommended Roadmap

> **Status:** this document is the **baseline audit** of the code before remediation. Most findings referenced here are now fixed; see [13_REMEDIATION_REPORT.md](13_REMEDIATION_REPORT.md) for the current status and evidence.

**Phase 0 - quick safety wins (S, ~1-2 days):** F-03 sanitise + CSP/headers
(F-10), F-04 env allowlist, F-07 generic errors, F-09 input limits,
F-05 pin MCP package, F-06 Tavily header, F-17 timeouts/retries/429 mapping.

**Phase 1 - stability (M):** F-12 non-blocking routes, F-13 connection pool,
F-30 lifespan init, F-19 resume validation, F-28 readiness probe + structured
logging.

**Phase 2 - access control (M):** F-01 auth + quotas, F-02 thread ownership,
F-11 retention/delete, F-18 restore pending drafts and per-trip thread ids.

**Phase 3 - quality of results (M):** F-20 real flight tool, F-21 dated
forecast and geocoding, F-16 token caps, F-22 revision loop, F-08 prompt-injection
hardening and fail-closed guardrail, F-32 merged supervisor call.

**Phase 4 - performance and engineering (M-L):** F-15 parallel agents,
F-14 persistent MCP sessions/async nodes, F-27 tests + CI, F-29 versioned
images/backups, F-24/F-25 cleanup and lockfile, F-23 metrics, F-26/F-31 polish.

## Future enhancements (recommended after v2.2)

| ID | Enhancement | Area | Priority | Detail |
|---|---|---|---|---|
| FUT-001 | Two-factor sign-in (TOTP) | Security | High | Optional authenticator-app codes for everyone, mandatory for administrators; recovery codes. |
| FUT-002 | Usage and cost tracking per user | Admin | High | Record LLM calls and tokens per trip and user, show them in the admin console, allow per-user quota overrides and abuse alerts. |
| FUT-003 | Fallback model and result caching for AI rate limits | Reliability | High | A live run was refused with HTTP 429 by the AI provider after several plans in a minute. Add a second model/provider fallback, short-lived caches for weather/flight/hotel lookups and automatic retry with the Retry-After delay. |
| FUT-004 | Structured itinerary output | Quality | High | Ask the model for JSON (schema-validated) instead of markdown that the browser parses, so days, weather and costs are guaranteed fields; enables maps, totals and calendar export. |
| FUT-005 | Background job queue and shared state | Scalability | High | Run plans in a queue (for example Redis + a worker) so they survive restarts and scale to several app instances; move rate limiters and the SQL log ring out of process memory. |
| FUT-006 | Real export and sharing | User experience | Medium | Server-side PDF, .ics calendar file, share-by-link (read-only, expiring) and email-me-my-plan. |
| FUT-007 | Data provenance and freshness labels | Trust | Medium | Show where each flight, hotel and weather fact came from and when it was fetched (extends ENH-002). |
| FUT-008 | Persistent SQL and trace logging | Observability | Medium | Keep slow-query history in the database, export logs, ship them to a log service and add OpenTelemetry traces across API, graph nodes, MCP calls and SQL. |
| FUT-009 | Database migrations tool | Engineering | Medium | Replace CREATE TABLE IF NOT EXISTS / ALTER ... IF NOT EXISTS with versioned migrations (for example Alembic) and a restore drill for backups. |
| FUT-010 | More admin roles | Admin | Medium | Read-only support role, admin invitations, and an approval step before deleting accounts. |
| FUT-011 | Transactional email provider and templates | Operations | Medium | HTML templates, bounce/complaint handling and delivery status in the admin console. |
| FUT-012 | Cross-browser and accessibility testing in CI | Quality | Medium | Run the Playwright journey on Chromium, Firefox and WebKit in CI, add automated accessibility checks and a manual screen-reader pass. |
| FUT-013 | Privacy tools | Compliance | Medium | Download my data, configurable retention per tenant, and an admin-visible record of data-deletion requests. |
| FUT-014 | Saved traveller profile and booking links | User experience | Low | Remember home airport, budget style and currency; deep links to book the suggested flights and hotels. |
| FUT-015 | Languages, currencies and units | User experience | Low | Localised interface, currency conversion and metric/imperial units. |
| FUT-016 | Installable app (PWA) with offline trips | User experience | Low | Cache saved trips so the plan can be read on a plane without a connection. |

Suggested order: FUT-003 (rate-limit resilience), FUT-004 (structured itinerary), FUT-002 and FUT-001 (cost visibility and 2FA), then FUT-005 before running more than one app instance.
