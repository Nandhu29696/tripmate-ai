# TripMate AI - Project Documentation

Documents 01-12 come from a read-only audit of the repository as found
(branch `tripmate-ai-publish`). Documents 04 and 05 were rewritten after the
fixes, and **13 records the remediation** (branch `tripmate-hardening`). Secrets
in `.env` were never read; only variable names were listed.

| # | Document | Contents |
|---|----------|----------|
| 01 | [Project overview](01_PROJECT_OVERVIEW.md) | Purpose, stack, folder map, entry points, configuration, integrations |
| 02 | [Architecture](02_ARCHITECTURE.md) | System, graph and sequence diagrams, component communication |
| 03 | [Frontend](03_FRONTEND.md) | **React app**: structure, routes, auth behaviour, trip lifecycle, a11y (rewritten) |
| 04 | [Backend and API](04_BACKEND_API.md) | Endpoint table, request tracing, modules |
| 05 | [Database](05_DATABASE.md) | Checkpoint schema, ER diagram, data lifecycle |
| 06 | [Business workflows](06_BUSINESS_WORKFLOWS.md) | User journeys, processing steps, error scenarios |
| 07 | [AI / LLM analysis](07_AI_LLM_ANALYSIS.md) | Model, prompts, agents, MCP, token budget, lifecycle |
| 08 | [Security and performance review](08_SECURITY_PERFORMANCE_REVIEW.md) | Findings register F-01..F-30 with severity, evidence, fix |
| 09 | [Deployment and infrastructure](09_DEPLOYMENT.md) | Docker, Nginx, TLS, CI/CD, logging, monitoring |
| 10 | [Developer setup](10_DEVELOPER_SETUP.md) | Local run instructions and conventions |
| 11 | [Validation report](11_VALIDATION_REPORT.md) | What was verified, how, and what was not |
| 12 | [Roadmap](12_ROADMAP.md) | Prioritised development plan (baseline) |
| 13 | [Remediation report](13_REMEDIATION_REPORT.md) | **Current status**: what was fixed, evidence, residual risks |

Conventions: **Verified** = confirmed by reading the cited code or by a
read-only command. **Potential** = plausible from the code but not reproduced
(the application was deliberately not run).
