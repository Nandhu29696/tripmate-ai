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

In the DNS zone for `jagoindia.in`, point the `tripmate-ai` A record to this VPS's public IPv4 address. The hostname currently resolves to `187.127.166.46`; confirm that is the intended VPS address. Remove or correct any AAAA record unless IPv6 is configured on the VPS. Allow inbound TCP ports 80 and 443 in the Hostinger firewall and any VPS firewall.

Create a dedicated database role and database if they do not already exist:

```bash
sudo -u postgres createuser --pwprompt tripmate_user
sudo -u postgres createdb --owner=tripmate_user tripmate
```

The app's `DATABASE_URL` connects to `127.0.0.1:5432` from the host-network container. If PostgreSQL runs somewhere else, change the URL and host-network assumptions deliberately.

## 2. Get the project and configure secrets

Clone the published deployment branch to the VPS. Do not copy a developer's `.env`, commit credentials, or bake a secrets file into the image.

```bash
git clone --branch tripmate-ai-publish https://github.com/Nandhu29696/tripmate-ai.git tripmate-ai
cd tripmate-ai
```

From the project directory:

```bash
install -m 600 .env.production.example .env.production
nano .env.production
```

Set `GROQ_API_KEY`, keep `GROQ_MODEL` at a model available to that key, and set `DATABASE_URL` with the dedicated PostgreSQL role/password. URL-encode special characters in the database password. `sslmode=disable` is suitable only for PostgreSQL on the same host over loopback; use the database provider's TLS settings for a remote database.

Also set, in `.env.production`:

- `SESSION_SECRET` (**required**): signs session cookies. Generate it with `openssl rand -hex 32`. `deploy.sh` refuses to run without it.
- `APP_ACCESS_KEY` (**strongly recommended**): users must enter this key to use the app. If left empty the app is open to anyone and is protected only by the per-session and daily quotas (`deploy.sh` prints a warning).
- Optional provider keys (`TAVILY_API_KEY`, `AVIATION_STACK_API_KEY`, `OPENWEATHER_API_KEY`) and the tuning values listed in `.env.production.example`.

## 3. Deploy the container

```bash
bash deploy/deploy.sh
```

The script validates Compose configuration, builds the image, starts/restarts the app, and checks `http://127.0.0.1:8014/health`. Check the status and logs with:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f app
```

The first build downloads Python dependencies and installs the version-pinned AviationStack MCP server (and the Python 3.13 interpreter it needs) into the image, so nothing is downloaded at runtime. LangGraph creates its checkpoint tables, and the app creates its `tripmate_threads` ownership table, in the configured PostgreSQL database on startup. Conversation state stays in PostgreSQL; the container itself is stateless.

Each deploy tags the image with the git commit (`tripmate-ai:<commit>`), takes a gzip `pg_dump` into `backups/` (keeping the last 7; skipped with a warning if `pg_dump` is missing), then waits for `GET /ready` on `127.0.0.1:8014`. To return to the previous release run `bash deploy/deploy.sh rollback`.

## 4. Configure Nginx and HTTPS for the subdomain

The public hostname for this deployment is `tripmate-ai.jagoindia.in`. If Nginx already has a server block for this hostname, set its `server_name` to `tripmate-ai.jagoindia.in` and ensure it has a valid certificate for that name. If no server block exists yet, create a temporary HTTP-only block so Certbot can identify the hostname:

```nginx
server {
    listen 80;
    server_name tripmate-ai.jagoindia.in;
    location / { return 404; }
}
```

Save it as `/etc/nginx/conf.d/tripmate-ai.conf`, then issue and install a certificate using the Nginx Certbot plugin:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d tripmate-ai.jagoindia.in --redirect
```

Certbot requires DNS to point to this VPS and inbound port 80 to be reachable for validation. Install the Certbot Nginx plugin first if it is not already available. If TLS for this hostname is already managed elsewhere, do not create a duplicate server block; configure that existing TLS site instead.

Install the rate-limit zones inside Nginx's `http {}` context (on many distributions, a file in `/etc/nginx/conf.d/` is included there), and install the location fragment:

```bash
sudo cp deploy/nginx/tripmate-rate-limit.conf /etc/nginx/conf.d/tripmate-rate-limit.conf
sudo cp deploy/nginx/tripmate-location.conf /etc/nginx/snippets/tripmate-location.conf
```

Inside the HTTPS `server {}` block for `tripmate-ai.jagoindia.in`, add `include /etc/nginx/snippets/tripmate-location.conf;`. Replace any existing catch-all `location /` for this site rather than adding a duplicate. The included locations proxy the UI and API to `127.0.0.1:8014`, preserve forwarding headers, and apply two limits per IP: **5 requests/minute (burst 2)** on the expensive plan endpoints (`/api/travel`, `/api/travel/approve` and their `/stream` variants), and **60 requests/minute (burst 20)** on all other `/api/` routes so a page reload never trips the limit. They hide the interactive OpenAPI docs and the internal `/ready` endpoint. Three details matter and were each verified against a running Nginx: the strict limit is a regex location, so the generic `/api/` location must stay a plain prefix (a `^~` prefix would silently bypass the strict limit); `Host` is forwarded as `$http_host` so the app's CSRF origin check still matches when the site is served on a non-default port; and `proxy_buffering off` on the plan endpoints lets the progress stream reach the browser immediately. Security headers (CSP, HSTS over HTTPS, X-Frame-Options, ...) are set by the application itself.

Validate, reload Nginx, and verify the site and certificate:

```bash
sudo nginx -t
sudo systemctl reload nginx
curl --fail https://tripmate-ai.jagoindia.in/health
sudo certbot renew --dry-run
```

The location fragment does not create a TLS certificate or server block. Keep TLS termination at Nginx and do not expose port `8014` through the VPS firewall.

## 5. Updating and operating

After pulling a code update, run `bash deploy/deploy.sh` again (it backs up the database first). Review logs and confirm `/health` after each deployment. Roll back with `bash deploy/deploy.sh rollback`.

Stop only the app container without touching PostgreSQL:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

Access control: set `APP_ACCESS_KEY` so only people with the key can create trips; every trip is bound to the signed session that created it, and other sessions get 404. Quotas (`MAX_PLANS_PER_SESSION_PER_HOUR`, `MAX_PLANS_PER_DAY`) are counted in process memory, so run a single worker. Prompts and generated plans are stored in PostgreSQL checkpoints and are deleted automatically after `RETENTION_DAYS` (default 30) or when a user deletes a trip; configure database backups, access controls and key rotation to match your retention policy.

## Troubleshooting

- **Container unhealthy / database connection error:** verify PostgreSQL is running, accepts TCP on `127.0.0.1:5432`, and the URL credentials/database are correct.
- **Nginx 502:** check `docker compose ... ps` and app logs; confirm the app is listening at `127.0.0.1:8014`.
- **Nginx 404 or duplicate location error:** include the proxy locations inside the correct TLS server block and replace, rather than duplicate, an existing `location /`.
- **Certificate hostname mismatch:** confirm the A/AAAA records point to this VPS and renew/install a certificate that includes `tripmate-ai.jagoindia.in`.
- **Nginx 429:** a per-IP limit is active (5/min on plan endpoints, 60/min elsewhere); adjust `rate` and `burst` in the Nginx snippets. An application-level 429 carries a JSON body and `Retry-After` (plan quota or Groq rate limit).
- **Everyone is asked for an access key / sessions end on restart:** set `SESSION_SECRET` (without it an ephemeral key is generated on each start). Sessions last `SESSION_TTL_SECONDS` (12 h).
- **`/ready` returns 503:** the database is unreachable; check PostgreSQL and `DATABASE_URL`. `/health` stays green because it only reports that the process is alive.
- **Groq errors:** verify the model ID is available to the configured key and account TPM limits allow the request.
- **Deployment on a non-Linux Docker host:** this Compose file relies on Linux host networking; use a bridge-network deployment design instead.
