#!/usr/bin/env bash
set -euo pipefail

RUN_INTEGRATION=false
RUN_COVERAGE=false
RUN_ALL=false

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]
Options:
  --integration        run the integration tests (starts Postgres/Qdrant)
  --coverage           enable coverage reporting for unit tests
  -a, --all            equivalent to --integration --coverage
  -h, --help           display this help and exit
EOF
}

while (( "$#" )); do
  case "$1" in
    --integration) RUN_INTEGRATION=true ;;
    --coverage) RUN_COVERAGE=true ;;
    -a|--all) RUN_ALL=true ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if $RUN_ALL; then
  RUN_INTEGRATION=true
  RUN_COVERAGE=true
fi

run_step() {
  local label="$1"
  shift
  echo ""
  echo "==> ${label}"
  if ! "$@"; then
    local status=$?
    echo "Step \"${label}\" failed with exit code ${status}."
    exit "${status}"
  fi
}

run_step "Linting and type checks" ./test/lint.sh
run_step "Attention router gate" ./test/check_attention_router_gate.sh

unit_args=()
if $RUN_COVERAGE; then
  unit_args+=(--coverage)
fi
run_step "Unit tests" ./test/unit.sh "${unit_args[@]}"

run_step "Contract tests" ./test/contract.sh

if $RUN_INTEGRATION; then
  run_step "Integration tests" ./test/integration.sh --integration
else
  echo ""
  echo "==> Integration tests (skipped; pass --integration or -a to enable)"
fi

run_step "Smoke tests" ./test/smoke.sh
run_step "Go checks" ./test/go.sh
