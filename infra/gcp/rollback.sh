#!/usr/bin/env bash
set -euo pipefail

# Safe rollback helper.
#
# Usage from the repository root:
#   infra/gcp/rollback.sh <git-revision-or-image-tag-note>
#
# This script intentionally does not delete Docker volumes, database data, cloud
# resources, static IPs, or backups. If using Git revisions, checkout the known
# good revision before running this script, then let Compose rebuild/restart the
# OFF-mode services. If using prebuilt image tags later, update the Compose file
# manually and review the diff before running this script.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/env.prod}"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.prod.yml"
ROLLBACK_TARGET="${1:-}"

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

[ -n "${ROLLBACK_TARGET}" ] || fail "Provide a known-good Git revision or image tag note."
[ -f "${ENV_FILE}" ] || fail "Missing ${ENV_FILE}."
[ "$(get_env_value TRADING_MODE)" = "OFF" ] || fail "Refusing rollback unless TRADING_MODE=OFF."
[ "$(get_env_value LIVE_ARMED)" = "false" ] || fail "Refusing rollback unless LIVE_ARMED=false."

printf 'Rolling back/restarting using reviewed target: %s\n' "${ROLLBACK_TARGET}"
printf 'Database and Redis volumes will be preserved.\n'

cd "${REPO_ROOT}"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build api
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --no-deps api

"${SCRIPT_DIR}/verify_deployment.sh"
