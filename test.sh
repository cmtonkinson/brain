#!/usr/bin/env bash
set -euo pipefail

./test/lint.sh
./test/check_attention_router_gate.sh
./test/unit.sh
./test/contract.sh
./test/integration.sh
./test/smoke.sh
./test/go.sh
