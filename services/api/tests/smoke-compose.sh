#!/usr/bin/env bash
# Boot the application Compose file on an isolated CI host with fake config.
# Verifies container wiring and real dashboard SSO, without real Cloudflare data.
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
  -e 's/^NEXT_PUBLIC_DATA_MODE=demo$/NEXT_PUBLIC_DATA_MODE=api/' \
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
docker build --file services/api/tests/Dockerfile --tag "$PROJECT-checks" .
docker run --rm --network "${PROJECT}_cyber-net" \
  --env TEST_FRONTEND_URL=http://localhost:3000 \
  --env TEST_KEYCLOAK_DEMO_PASSWORD=change-viewer-demo-password \
  --env TEST_KEYCLOAK_ADMIN_PASSWORD=change-admin-demo-password \
  "$PROJECT-checks" python -m pytest -c pytest.ini tests/test_frontend_sso.py -q -p no:cacheprovider
echo "Application Compose passed: 9 services, NextAuth/Keycloak sessions, role guards, exact job tracking and logout."
