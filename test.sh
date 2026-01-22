#!/usr/bin/env bash
set -euo pipefail

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
run_step "Unit tests" ./test/unit.sh
run_step "Contract tests" ./test/contract.sh
run_step "Integration tests" ./test/integration.sh
run_step "Smoke tests" ./test/smoke.sh
run_step "Go checks" ./test/go.sh
