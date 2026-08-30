#!/usr/bin/env bash
# TFC-Plane production deployment helper.
#
# Usage:
#   ./deploy.sh            # pull images and start the production stack
#
# Requirements:
#   - Docker + Docker Compose v2 on the host
#   - .env file next to this script (copy from .env.production.example)
#
# This script never deletes volumes/containers and never runs `down -v`.
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }

bold "==> TFC-Plane production deployment"

# 1. Docker present?
if ! command -v docker >/dev/null 2>&1; then
  fail "Docker is not installed. Install Docker first: https://docs.docker.com/engine/install/"
fi
bold "Docker found: $(docker --version)"

# 2. Docker Compose available?
if docker compose version >/dev/null 2>&1; then
  bold "Compose found: $(docker compose version --short)"
else
  fail "Docker Compose v2 is not available (try: docker compose version)."
fi

# 3. Environment file present?
if [ ! -f "$ENV_FILE" ]; then
  if [ -f ".env.production.example" ]; then
    fail "$ENV_FILE not found. Create it first:
       cp .env.production.example $ENV_FILE   # then edit the values (passwords, domain, TFC_IMAGE_PREFIX)"
  else
    fail "$ENV_FILE not found and no .env.production.example template exists."
  fi
fi
bold "Environment file found: $ENV_FILE"

# 4. Pull the prebuilt images (no source build on this machine).
bold "==> Pulling images (this may take a few minutes on first run)..."
docker compose -f "$COMPOSE_FILE" pull

# 5. Start the stack (migrator runs once, then api/worker/beat/web/... come up).
bold "==> Starting TFC-Plane..."
docker compose -f "$COMPOSE_FILE" up -d

# 6. Status + useful pointers.
bold "==> Container status:"
docker compose -f "$COMPOSE_FILE" ps

cat <<EOF

${BOLD:-}TFC-Plane is starting.${RESET:-}
- Web UI:      http://localhost:${LISTEN_HTTP_PORT:-80}/          (first migration may take ~1 min)
- Admin:       http://localhost:${LISTEN_HTTP_PORT:-80}/god-mode/
- Spaces:      http://localhost:${LISTEN_HTTP_PORT:-80}/spaces/
- Live socket: http://localhost:${LISTEN_HTTP_PORT:-80}/live/

Useful commands:
  docker compose -f ${COMPOSE_FILE} ps           # status
  docker compose -f ${COMPOSE_FILE} logs -f api  # follow API logs
  docker compose -f ${COMPOSE_FILE} logs -f migrator  # first-run migrations
EOF