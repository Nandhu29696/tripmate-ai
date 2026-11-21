#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo "Docker Engine and Docker Compose are required." >&2
    exit 1
fi

if [[ ! -f .env.production ]]; then
    install -m 600 .env.production.example .env.production
    echo "Created .env.production. Add your Groq key and PostgreSQL URL, then run this script again."
    exit 1
fi

if grep -Eq '^GROQ_API_KEY=(|replace_with_a_real_groq_api_key)$' .env.production; then
    echo "Set GROQ_API_KEY in .env.production before deploying." >&2
    exit 1
fi

if grep -q 'replace_with_url_encoded_password' .env.production; then
    echo "Set the PostgreSQL password in DATABASE_URL in .env.production." >&2
    exit 1
fi

COMPOSE=(docker compose --env-file .env.production -f docker-compose.prod.yml)
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up -d --build
"${COMPOSE[@]}" ps

for _ in {1..30}; do
    if curl --fail --silent http://127.0.0.1:8014/health >/dev/null; then
        echo "TripMate is healthy at http://127.0.0.1:8014/health"
        exit 0
    fi
    sleep 2
done

echo "TripMate did not become healthy. Recent logs:" >&2
"${COMPOSE[@]}" logs --tail=100 app >&2
exit 1
