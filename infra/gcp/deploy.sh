#!/usr/bin/env bash
set -euo pipefail

# Deploy the current OFF-mode API/Postgres/Redis stack on an already-created VM.
# Usage from the repository root:
#   infra/gcp/deploy.sh
#
# This script does not call gcloud, Zerodha, OpenAI, or any cloud API. It assumes
# Docker Compose is already installed on the VM and infra/gcp/env.prod exists.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/env.prod}"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.prod.yml"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

get_env_value() {
  local key="$1"
  local value
  value="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n 1 | cut -d '=' -f 2- || true)"
  printf '%s' "${value}"
}

[ -f "${ENV_FILE}" ] || fail "Missing ${ENV_FILE}. Copy env.prod.example to env.prod on the VM and fill placeholders."
[ -f "${COMPOSE_FILE}" ] || fail "Missing ${COMPOSE_FILE}."

TRADING_MODE_VALUE="$(get_env_value TRADING_MODE)"
LIVE_ARMED_VALUE="$(get_env_value LIVE_ARMED)"

[ "${TRADING_MODE_VALUE}" = "OFF" ] || fail "Refusing deployment unless TRADING_MODE=OFF."
[ "${LIVE_ARMED_VALUE}" = "false" ] || fail "Refusing deployment unless LIVE_ARMED=false."

cd "${REPO_ROOT}"

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build api
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d postgres redis
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" run --rm \
  -e TRADING_MODE=OFF \
  -e LIVE_ARMED=false \
  api alembic -c backend/alembic.ini upgrade head
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d api

bash "${SCRIPT_DIR}/verify_deployment.sh"
