#!/usr/bin/env bash
# Chạy test của analysis trong Docker (máy dev không cần Python).
#   bash services/analysis/tests/run.sh [đối số pytest]
set -euo pipefail
cd "$(dirname "$0")/../../.."
ROOT="$(pwd -W 2>/dev/null || pwd)"
ARGS=(--rm -v "$ROOT:/work" -v kpdl-pipcache:/root/.cache/pip -w /work
      -e PYTHONPATH=/work/services/analysis:/work/backend -e PYTHONDONTWRITEBYTECODE=1)
MSYS_NO_PATHCONV=1 docker run "${ARGS[@]}" python:3.11-slim bash -c \
  'pip install -q -r services/analysis/requirements.txt -r services/analysis/requirements-dev.txt 2>&1 | grep -v WARNING; pytest services/analysis/tests -q -p no:cacheprovider "$@"' _ "$@"

