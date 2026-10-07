#!/usr/bin/env bash
# Non-destructive gates. Requires an existing Python 3.11 venv and npm ci.
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin="${RELEASE_PYTHON:-$PWD/.venv/bin/python}"
# Unit tests exercise mocked ingestion as well as local-only guards. An inherited
# local-only flag must not suppress those branches; never read real credentials.
LOCAL_DATA_ONLY=0 ENV_FILE_PATH=/dev/null OPENCELLID_KEYS= OPENCELLID_TOKEN= \
  ALLOW_MODEL_TRAINING=0 PREDICTION_DEVICE=cpu "$python_bin" -m pytest -q
(
  cd services/visualization
  npm run test -- --run
  npm run typecheck
  npm run lint
  npm run build
)
# Config-only placeholder; runtime still requires real, validated artifacts.
ARTIFACT_DIR="${ARTIFACT_DIR:-$PWD/.cache/release-artifacts}" \
  docker compose --env-file /dev/null config --quiet
git diff --check
