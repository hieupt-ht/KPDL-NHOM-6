#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
docker build --target tests --file training/Dockerfile --tag kpdl-ml-tests .
docker run --rm --network none kpdl-ml-tests
