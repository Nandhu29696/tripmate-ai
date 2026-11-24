#!/usr/bin/env bash
# Usage:
#   bash deploy/deploy.sh            build, back up the database, deploy, health-check
#   bash deploy/deploy.sh rollback   redeploy the previously deployed image
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
KEEP_BACKUPS="${KEEP_BACKUPS:-7}"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo "Docker Engine and Docker Compose are required." >&2
    exit 1
fi

if [[ ! -f .env.production ]]; then
    install -m 600 .env.production.example .env.production
    echo "Created .env.production. Fill in the required values, then run this script again."
    exit 1
fi

env_value() { grep -E "^$1=" .env.production | head -n1 | cut -d= -f2- || true; }

if grep -Eq '^GROQ_API_KEY=(|replace_with_a_real_groq_api_key)$' .env.production; then
    echo "Set GROQ_API_KEY in .env.production before deploying." >&2
    exit 1
fi

if grep -q 'replace_with_url_encoded_password' .env.production; then
    echo "Set the PostgreSQL password in DATABASE_URL in .env.production." >&2
    exit 1
fi

SESSION_SECRET_VALUE="$(env_value SESSION_SECRET)"
if [[ -z "$SESSION_SECRET_VALUE" || "$SESSION_SECRET_VALUE" == replace_with_* ]]; then
    echo "Set SESSION_SECRET in .env.production (generate one with: openssl rand -hex 32)." >&2
    exit 1
fi

PUBLIC_URL_VALUE="$(env_value PUBLIC_BASE_URL)"
if [[ ! "$PUBLIC_URL_VALUE" =~ ^https://[^/]+$ ]]; then
    echo "Set PUBLIC_BASE_URL in .env.production to the site's https URL, e.g. https://tripmate-ai.jagoindia.in (no trailing slash)." >&2
    echo "It is used for the Google redirect URI and for links in emails, so it must not come from request headers." >&2
    exit 1
fi

if [[ -z "$(env_value GOOGLE_CLIENT_ID)" || -z "$(env_value GOOGLE_CLIENT_SECRET)" ]]; then
    echo "WARNING: GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are empty: 'Continue with Google' will be hidden." >&2
fi

if [[ -z "$(env_value SMTP_HOST)" ]]; then
    echo "WARNING: SMTP_HOST is empty: confirmation and password-reset emails are only written to the log," >&2
    echo "         so email/password sign-up cannot work for real users." >&2
fi

health_url="http://127.0.0.1:8014/ready"
wait_healthy() {
    for _ in {1..30}; do
        if curl --fail --silent "$health_url" >/dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}

if [[ "${1:-}" == "rollback" ]]; then
    if [[ ! -f .previous_version ]]; then
        echo "No previous version recorded; nothing to roll back to." >&2
        exit 1
    fi
    TRIPMATE_VERSION="$(cat .previous_version)"
    export TRIPMATE_VERSION
    if ! docker image inspect "tripmate-ai:${TRIPMATE_VERSION}" >/dev/null 2>&1; then
        echo "Image tripmate-ai:${TRIPMATE_VERSION} no longer exists locally." >&2
        exit 1
    fi
    COMPOSE=(docker compose --env-file .env.production -f docker-compose.prod.yml)
    "${COMPOSE[@]}" up -d --no-build
    if wait_healthy; then
        cp .previous_version .deployed_version
        echo "Rolled back to ${TRIPMATE_VERSION}."
        exit 0
    fi
    echo "Rollback did not become healthy. Recent logs:" >&2
    "${COMPOSE[@]}" logs --tail=100 app >&2
    exit 1
fi

TRIPMATE_VERSION="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
export TRIPMATE_VERSION

COMPOSE=(docker compose --env-file .env.production -f docker-compose.prod.yml)
"${COMPOSE[@]}" config --quiet

# Database backup before touching anything (non-fatal if pg_dump is missing).
if command -v pg_dump >/dev/null 2>&1; then
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    backup_file="$BACKUP_DIR/tripmate-$(date +%Y%m%d-%H%M%S).sql.gz"
    if pg_dump "$(env_value DATABASE_URL)" 2>/dev/null | gzip > "$backup_file"; then
        echo "Database backup written to $backup_file"
        ls -1t "$BACKUP_DIR"/tripmate-*.sql.gz 2>/dev/null | tail -n +"$((KEEP_BACKUPS + 1))" | xargs -r rm -f --
    else
        rm -f "$backup_file"
        echo "WARNING: database backup failed; continuing." >&2
    fi
else
    echo "WARNING: pg_dump not found; skipping database backup." >&2
fi

[[ -f .deployed_version ]] && cp .deployed_version .previous_version

"${COMPOSE[@]}" up -d --build
docker tag "tripmate-ai:${TRIPMATE_VERSION}" tripmate-ai:latest
"${COMPOSE[@]}" ps

if wait_healthy; then
    echo "$TRIPMATE_VERSION" > .deployed_version
    echo "TripMate ${TRIPMATE_VERSION} is healthy at ${health_url}"
    exit 0
fi

echo "TripMate did not become healthy. Recent logs:" >&2
"${COMPOSE[@]}" logs --tail=100 app >&2
echo "Run 'bash deploy/deploy.sh rollback' to return to the previous version." >&2
exit 1
