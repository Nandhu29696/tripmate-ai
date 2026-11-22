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
