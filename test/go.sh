#!/usr/bin/env bash
set -euo pipefail

echo "Running Go checks..."

pushd host-mcp-gateway >/dev/null
gofmt_output="$(gofmt -l .)"
gofmt_status=$?
if [[ $gofmt_status -ne 0 ]]; then
  echo "gofmt failed with exit code ${gofmt_status}."
  exit "${gofmt_status}"
fi
if [[ -n "$gofmt_output" ]]; then
  echo "gofmt required for:"
  echo "$gofmt_output"
  exit 1
fi
go vet ./...
go run github.com/golangci/golangci-lint/cmd/golangci-lint@v1.64.5 run ./...
go test ./...
popd >/dev/null
