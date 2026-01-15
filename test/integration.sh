#!/usr/bin/env bash
set -euo pipefail

if [[ "${BRAIN_RUN_INTEGRATION:-}" != "1" ]]; then
  echo "Skipping integration tests (set BRAIN_RUN_INTEGRATION=1 to run)."
  exit 0
fi

run_pytest() {
  set +e
  poetry run pytest "$@"
  status=$?
  set -e
  if [[ $status -ne 0 && $status -ne 5 ]]; then
    exit $status
  fi
}

run_pytest test/integration
