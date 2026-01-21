#!/usr/bin/env bash
set -euo pipefail

echo "Running unit tests..."

run_pytest() {
  set +e
  poetry run pytest "$@"
  status=$?
  set -e
  if [[ $status -ne 0 && $status -ne 5 ]]; then
    exit $status
  fi
}

if [[ "${BRAIN_RUN_COVERAGE:-}" == "1" ]]; then
  run_pytest --cov=src --cov-report=term-missing --cov-report=xml test/unit
else
  run_pytest test/unit
fi
