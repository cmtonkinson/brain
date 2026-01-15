#!/usr/bin/env bash
set -euo pipefail

if [[ "${BRAIN_RUN_INTEGRATION:-}" != "1" ]]; then
  echo "Skipping integration tests (set BRAIN_RUN_INTEGRATION=1 to run)."
  exit 0
fi

poetry run pytest test/integration
