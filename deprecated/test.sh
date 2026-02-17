#!/usr/bin/env bash
set -euo pipefail

RUN_INTEGRATION=false
RUN_COVERAGE=false
RUN_ALL=false
QUIET=false

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]
Options:
  --integration        run the integration tests (starts Postgres/Qdrant)
  --coverage           enable coverage reporting for unit tests
  -a, --all            equivalent to --integration --coverage
  -q, --quiet          suppress output unless a step fails
  -h, --help           display this help and exit
EOF
}

while (( "$#" )); do
  case "$1" in
    --integration) RUN_INTEGRATION=true ;;
    --coverage) RUN_COVERAGE=true ;;
    -a|--all) RUN_ALL=true ;;
    -q|--quiet) QUIET=true ;;
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
  if $QUIET; then
    local output_file
    output_file="$(mktemp)"
    if "$@" >"${output_file}" 2>&1; then
      rm -f "${output_file}"
      return 0
    fi
    local status=$?
    echo "==> ${label}"
    cat "${output_file}"
    rm -f "${output_file}"
    echo "Step \"${label}\" failed with exit code ${status}."
    exit "${status}"
  else
    echo ""
    echo "==> ${label}"
    if ! "$@"; then
      local status=$?
      echo "Step \"${label}\" failed with exit code ${status}."
      exit "${status}"
    fi
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
  if ! $QUIET; then
    echo ""
    echo "==> Integration tests (skipped; pass --integration or -a to enable)"
  fi
fi

run_step "Smoke tests" ./test/smoke.sh
run_step "Go checks" ./test/go.sh
