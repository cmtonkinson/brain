#!/usr/bin/env bash
# Docblock:
# - File: test/check_attention_router_gate.sh
# - Purpose: Guard against direct Signal notifications that bypass the attention router.
# - Usage: ./test/check_attention_router_gate.sh

set -euo pipefail

echo "Running attention router gate check..."

if ! command -v rg >/dev/null 2>&1; then
  echo "Attention router gate check requires ripgrep (rg) on PATH."
  echo "Install ripgrep or add it to PATH so this gate can run."
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

allowed_send_message_files=(
  "src/attention/router.py"
  "src/services/signal.py"
)

allowed_send_endpoint_files=(
  "src/services/signal.py"
)

fail=0

send_message_matches="$(rg -n --files-with-matches "send_message\\(" src || true)"
for file in $send_message_matches; do
  allowed=0
  for allowed_file in "${allowed_send_message_files[@]}"; do
    if [[ "$file" == "$allowed_file" ]]; then
      allowed=1
      break
    fi
  done
  if [[ "$allowed" -eq 0 ]]; then
    echo "Attention router gate violation: send_message usage in $file"
    fail=1
  fi
done

send_endpoint_matches="$(rg -n --files-with-matches "/v2/send" src || true)"
for file in $send_endpoint_matches; do
  allowed=0
  for allowed_file in "${allowed_send_endpoint_files[@]}"; do
    if [[ "$file" == "$allowed_file" ]]; then
      allowed=1
      break
    fi
  done
  if [[ "$allowed" -eq 0 ]]; then
    echo "Attention router gate violation: direct Signal endpoint usage in $file"
    fail=1
  fi
done

if [[ "$fail" -ne 0 ]]; then
  echo "Failed attention router gate check."
  exit 1
fi

echo "Attention router gate check passed: no direct notification call sites found."
