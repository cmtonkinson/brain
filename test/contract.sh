#!/usr/bin/env bash
set -euo pipefail

echo "Running contract tests..."

run_pytest() {
  set +e
  poetry run pytest "$@"
  status=$?
  set -e
  if [[ $status -ne 0 && $status -ne 5 ]]; then
    exit $status
  fi
}

run_pytest test/contract
