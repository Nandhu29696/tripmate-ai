# 09 - Deployment and Infrastructure

> **Status:** this document is the **baseline audit** of the code before remediation. Most findings referenced here are now fixed; see [13_REMEDIATION_REPORT.md](13_REMEDIATION_REPORT.md) for the current status and evidence.

## Topology

Browser -> Nginx (TLS via Certbot) -> `127.0.0.1:8014` -> container
`tripmate-ai` (host network) -> PostgreSQL `127.0.0.1:5432` and outbound
Groq/MCP providers. Host: Hostinger Linux VPS; hostname
`tripmate-ai.jagoindia.in`; PM2 is **not** used (Docker `restart:
unless-stopped` supervises the process).

## Docker

- `Dockerfile`: `python:3.12-slim`, non-root uid 10001, pinned requirements,
  `COPY . .` (safe: `.dockerignore` excludes `.env*`, `.git`, `.venv`,
  `deploy`), healthcheck against `/health`, `uvicorn` on 8014.
- `docker-compose.prod.yml`: `network_mode: host`, `init: true`,
  `cap_drop: ALL`, `no-new-privileges`, `/tmp` tmpfs `noexec`, named volume
  for the `uvx` cache, 20 s grace, `--proxy-headers` with
  `--forwarded-allow-ips=127.0.0.1`. Image tag is `:latest` (F-29).
- `compose.yaml`: local Postgres 17 only, bound to `127.0.0.1:5433`.

## Nginx / SSL

`tripmate-rate-limit.conf`: zone `5r/m` per IP (10 MB). `tripmate-location.conf`:
256k body cap, 404 for `/docs|/redoc|/openapi.json`, `/api/` limited
(burst 2, 429) with 300 s timeouts, catch-all proxy. TLS is issued by Certbot
(`--nginx --redirect`, renewal dry-run documented). Not present: security
headers/HSTS/CSP (F-10).

## Environment

`.env.production` (mode 600, created from the example by `deploy.sh`);
`deploy.sh` refuses placeholder values for the Groq key and DB password.
Database role/DB must be created manually.

## CI/CD

None. Deployment is manual: `git pull` then `bash deploy/deploy.sh`
(validates compose, builds, `up -d`, polls `/health` for 60 s, prints logs on
failure). No tests, image registry, rollback or DB backup step (F-27, F-29).

## Logging and monitoring

Container stdout/stderr only (`docker compose logs`), `print`-based, no
request ids, no metrics, no alerting. `/health` is static and does not probe
Postgres or Groq (F-28). Because routes block the event loop (F-12), a long
plan can make the healthcheck time out.

## Operational notes

Postgres is the only stateful component; back it up before upgrades. The
`uvx` cache volume is disposable. Port 8014 must stay closed externally.
