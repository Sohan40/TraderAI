#!/usr/bin/env bash
set -euo pipefail

# Verify the OFF-mode deployment without printing secrets.
# Usage:
#   infra/gcp/verify_deployment.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/env.prod}"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

pass() {
  printf 'PASS: %s\n' "$1"
}

get_env_value() {
  local key="$1"
  local value
  value="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n 1 | cut -d '=' -f 2- || true)"
  printf '%s' "${value}"
}

[ -f "${ENV_FILE}" ] || fail "Missing ${ENV_FILE}."

APP_PORT="$(get_env_value APP_PORT)"
APP_PORT="${APP_PORT:-8000}"
BASE_URL="${BASE_URL:-http://127.0.0.1:${APP_PORT}}"

[ "$(get_env_value TRADING_MODE)" = "OFF" ] || fail "Configured TRADING_MODE is not OFF."
[ "$(get_env_value LIVE_ARMED)" = "false" ] || fail "Configured LIVE_ARMED is not false."

command -v curl >/dev/null 2>&1 || fail "curl is required for deployment verification."

health_response="$(curl --fail --silent --show-error "${BASE_URL}/healthz")" || fail "/healthz request failed."
printf '%s' "${health_response}" | grep -q '"status":"healthy"' || fail "/healthz did not report healthy."
pass "/healthz is healthy"

ready_response="$(curl --fail --silent --show-error "${BASE_URL}/readyz")" || fail "/readyz request failed."
printf '%s' "${ready_response}" | grep -q '"status":"ready"' || fail "/readyz did not report ready."
printf '%s' "${ready_response}" | grep -q '"database":"ok"' || fail "Database dependency is not ready."
printf '%s' "${ready_response}" | grep -q '"redis":"ok"' || fail "Redis dependency is not ready."
pass "/readyz confirms Postgres and Redis are ready"

root_response="$(curl --fail --silent --show-error "${BASE_URL}/")" || fail "Root status request failed."
printf '%s' "${root_response}" | grep -q '"trading_mode":"OFF"' || fail "Application did not report trading_mode OFF."
pass "application reports trading_mode OFF"

pass "deployment verification completed with trading disabled"
