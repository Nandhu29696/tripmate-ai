# Hostinger VPS deployment

This deployment runs the existing FastAPI UI and API in one Docker container. It uses the VPS host's PostgreSQL and Nginx, following the host-network pattern used by the other VPS application.

```text
Browser -- HTTPS --> VPS Nginx -- HTTP over loopback --> TripMate container
                                                   127.0.0.1:8014
                                                            |
                                                            +--> PostgreSQL 127.0.0.1:5432
                                                            +--> Groq / optional MCP providers
```

Port `8014` is intentionally distinct from the example app's `8004` backend, `8005` frontend, and `8006` TLS listener. The app binds only to `127.0.0.1`; Docker Compose uses Linux host networking, so no public Docker port is published. This is intended for a Linux Hostinger VPS, not Docker Desktop.

## 1. Prepare the VPS

Install Docker Engine with the Compose plugin, PostgreSQL, Nginx, and `curl`. Keep PostgreSQL listening on loopback and ensure its local TCP authentication is enabled. Keep the existing Nginx TLS configuration and certificate; this deployment adds only a reverse-proxy location.

Create a dedicated database role and database if they do not already exist:

```bash
sudo -u postgres createuser --pwprompt tripmate_user
sudo -u postgres createdb --owner=tripmate_user tripmate
```

The app's `DATABASE_URL` connects to `127.0.0.1:5432` from the host-network container. If PostgreSQL runs somewhere else, change the URL and host-network assumptions deliberately.

## 2. Get the project and configure secrets

Clone or copy the project to the VPS. Do not copy a developer's `.env`, commit credentials, or bake a secrets file into the image.

From the project directory:

```bash
install -m 600 .env.production.example .env.production
nano .env.production
```

Set `GROQ_API_KEY`, keep `GROQ_MODEL` at a model available to that key, and set `DATABASE_URL` with the dedicated PostgreSQL role/password. URL-encode special characters in the database password. `sslmode=disable` is suitable only for PostgreSQL on the same host over loopback; use the database provider's TLS settings for a remote database. Optional MCP provider keys can remain blank until those features are needed.

## 3. Deploy the container

```bash
bash deploy/deploy.sh
```

The script validates Compose configuration, builds the image, starts/restarts the app, and checks `http://127.0.0.1:8014/health`. Check the status and logs with:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f app
```

The first build downloads Python dependencies. The first AviationStack MCP call may also download its `uvx` tool package. LangGraph creates its checkpoint tables in the configured PostgreSQL database on app startup. Conversation state stays in PostgreSQL; the Docker named volume is only for the `uvx` package cache.

## 4. Connect the existing Nginx TLS site

Install the rate-limit zone inside Nginx's `http {}` context (on many distributions, a file in `/etc/nginx/conf.d/` is included there):

```bash
sudo cp deploy/nginx/tripmate-rate-limit.conf /etc/nginx/conf.d/tripmate-rate-limit.conf
sudo cp deploy/nginx/tripmate-location.conf /etc/nginx/snippets/tripmate-location.conf
```

Inside the existing TLS `server {}` block for TripMate, add `include /etc/nginx/snippets/tripmate-location.conf;`. Replace any existing catch-all `location /` for this site rather than adding a duplicate. The included locations proxy the UI and API to `127.0.0.1:8014`, preserve forwarding headers, allow up to five API requests per minute per IP with a burst of two, and return 429 when rate-limited. They also hide the interactive OpenAPI docs.

Validate and reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

The sample location fragment does not create a TLS certificate or server block. Keep TLS termination and the external listener in the existing VPS Nginx configuration. Do not expose port `8014` through the VPS firewall.

## 5. Updating and operating

After pulling a code update, run `bash deploy/deploy.sh` again. Review logs and confirm `/health` after each deployment. Back up PostgreSQL before upgrades; the app's checkpoints are not stored in a Compose database volume.

Stop only the app container without touching PostgreSQL:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

The API currently has no user login or authorization. The included Nginx rate limit reduces accidental/API abuse but is not a substitute for authentication. Add an authentication layer before offering this app publicly. Prompts and generated responses can be stored in PostgreSQL checkpoints; configure appropriate database backups, access controls, retention, and key rotation.

## Troubleshooting

- **Container unhealthy / database connection error:** verify PostgreSQL is running, accepts TCP on `127.0.0.1:5432`, and the URL credentials/database are correct.
- **Nginx 502:** check `docker compose ... ps` and app logs; confirm the app is listening at `127.0.0.1:8014`.
- **Nginx 404 or duplicate location error:** include the proxy locations inside the correct TLS server block and replace, rather than duplicate, an existing `location /`.
- **Nginx 429:** the per-client API rate limit is active; adjust `rate` and `burst` in the Nginx snippets to fit real usage.
- **Groq errors:** verify the model ID is available to the configured key and account TPM limits allow the request.
- **Deployment on a non-Linux Docker host:** this Compose file relies on Linux host networking; use a bridge-network deployment design instead.
