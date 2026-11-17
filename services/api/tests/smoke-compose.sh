#!/usr/bin/env bash
# Boot the application Compose file on an isolated CI host with fake config.
# This verifies container/build wiring, not real Cloudflare data or dashboard SSO.
set -euo pipefail
cd "$(dirname "$0")/../../.."
PROJECT="kpdl-compose-smoke-${GITHUB_RUN_ID:-$$}"
[[ "$PROJECT" =~ ^kpdl-compose-smoke-[0-9]+$ ]] || exit 2
ENV_FILE="$(mktemp "${TMPDIR:-/tmp}/kpdl-compose-smoke.XXXXXX")"
COMPOSE=(docker compose --env-file "$ENV_FILE" --project-name "$PROJECT")
cleanup() {
  status=$?
  trap - EXIT
  if [[ "$status" != 0 ]]; then "${COMPOSE[@]}" logs --tail 80 || true; fi
  "${COMPOSE[@]}" down --volumes --remove-orphans || true
  rm -f -- "$ENV_FILE"
  exit "$status"
}
trap cleanup EXIT
cp .env.example "$ENV_FILE"
sed -i \
  -e 's/^AUTH_ENABLED=false$/AUTH_ENABLED=true/' \
  -e 's/^SCHEDULER_ENABLED=true$/SCHEDULER_ENABLED=false/' \
  -e 's/^WAREHOUSE_DB=warehouse$/WAREHOUSE_DB=test_warehouse/' \
  -e 's/^MART_DB=mart$/MART_DB=test_mart/' "$ENV_FILE"
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" down
"${COMPOSE[@]}" up --detach --build --wait --wait-timeout 300
count="$("${COMPOSE[@]}" ps --status running --services | wc -l)"
[[ "$count" -eq 9 ]] || { echo "Expected 9 running application services, got $count" >&2; exit 1; }
curl --fail --silent --show-error --retry 5 --retry-connrefused --retry-delay 2 http://localhost:3000/ >/dev/null
curl --fail --silent --show-error http://localhost:8000/ready >/dev/null
curl --fail --silent --show-error http://localhost:8080/realms/cyber-radar/.well-known/openid-configuration >/dev/null
code="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' http://localhost:8000/api/me)"
[[ "$code" == 401 ]] || { echo "Expected authenticated API to reject a missing token, got $code" >&2; exit 1; }
echo "Application Compose smoke passed: 9 services, frontend HTTP, Mart readiness, Keycloak and protected API."
