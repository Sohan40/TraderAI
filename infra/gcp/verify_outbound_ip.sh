#!/usr/bin/env bash
set -euo pipefail

# Print the VM outbound public IP for manual comparison with the reserved static
# IP recorded outside this repository. Do not commit the actual IP.

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

command -v curl >/dev/null 2>&1 || fail "curl is required."

detected_ip="$(curl --fail --silent --show-error https://api.ipify.org)"

printf 'Detected outbound public IP: %s\n' "${detected_ip}"
printf 'Manually compare this with the reserved static IP recorded outside Git.\n'
printf 'Never enable future live-order functionality until static-IP verification is complete.\n'
