#!/usr/bin/env bash
# Chạy test của ingestion trong Docker (máy dev không cần Python).
#   bash services/ingestion/tests/run.sh [đối số pytest]
#   INTEGRATION=1 bash ...   -> thêm test cần Postgres (warehouse-db phải đang chạy)
set -euo pipefail
cd "$(dirname "$0")/../../.."
ROOT="$(pwd -W 2>/dev/null || pwd)"
ARGS=(--rm -v "$ROOT:/work" -v kpdl-pipcache:/root/.cache/pip -w /work
      -e PYTHONPATH=/work/services/ingestion:/work/backend -e PYTHONDONTWRITEBYTECODE=1)
if [ "${INTEGRATION:-0}" = "1" ]; then
  set -a; . ./.env; set +a
  ARGS+=(--network cyber-radar-vn_cyber-net
         -e "TEST_WAREHOUSE_DSN=postgresql://ingestion_user:${INGESTION_DB_PASSWORD}@warehouse-db:5432/${WAREHOUSE_DB}")
fi
MSYS_NO_PATHCONV=1 docker run "${ARGS[@]}" python:3.11-slim bash -c \
  'pip install -q -r services/ingestion/requirements-dev.txt 2>&1 | grep -v WARNING; pytest services/ingestion/tests -q -p no:cacheprovider "$@"' _ "$@"
