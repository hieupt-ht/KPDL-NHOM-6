#!/usr/bin/env bash
# Docker only; no local Python, Node or .env needed.
set -euo pipefail
cd "$(dirname "$0")/../../.."
PROJECT="${KPDL_TEST_PROJECT:-kpdl-api-tests-$$}"
[[ "$PROJECT" =~ ^kpdl-api-tests-[a-z0-9][a-z0-9-]*$ ]] || { echo "Use a kpdl-api-tests-* project name" >&2; exit 2; }
MODE="${1:-all}"
[[ "$MODE" == unit || "$MODE" == integration || "$MODE" == all ]] || { echo "Usage: $0 [unit|integration|all]" >&2; exit 2; }
COMPOSE=(docker compose --file services/api/tests/compose.yml --project-name "$PROJECT")
cleanup() { status=$?; trap - EXIT; "${COMPOSE[@]}" down --volumes --remove-orphans || true; exit "$status"; }
trap cleanup EXIT
IMAGES=(tests)
[[ "$MODE" != all ]] || IMAGES=(analysis clustering prediction api tests)
for service in "${IMAGES[@]}"; do "${COMPOSE[@]}" build "$service"; done
if [[ "$MODE" == all ]]; then
  "${COMPOSE[@]}" up --no-build --abort-on-container-exit --exit-code-from tests
else
  MARKER='not integration and not stack'
  if [[ "$MODE" == integration ]]; then
    "${COMPOSE[@]}" up --detach --wait mart-db warehouse-db
    MARKER='not stack'
  fi
  "${COMPOSE[@]}" run --rm --no-deps tests python -m pytest -c pytest.ini tests -q -p no:cacheprovider -m "$MARKER"
fi
