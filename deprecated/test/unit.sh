#!/usr/bin/env bash
set -euo pipefail

echo "Running unit tests..."

RUN_COVERAGE=false
while (( "$#" )); do
  case "$1" in
    --coverage) RUN_COVERAGE=true; shift ;;
    -h|--help)
      echo "Usage: $0 [--coverage]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ "${BRAIN_RUN_COVERAGE:-}" == "1" ]]; then
  RUN_COVERAGE=true
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

if $RUN_COVERAGE; then
  run_pytest --cov=src --cov-report=term-missing --cov-report=xml test/unit
else
  run_pytest test/unit
fi
