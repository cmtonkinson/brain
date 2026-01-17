#!/usr/bin/env bash
set -euo pipefail

pushd host-mcp-gateway >/dev/null
gofmt_output=$(gofmt -l .)
if [[ -n "$gofmt_output" ]]; then
  echo "gofmt required for:"
  echo "$gofmt_output"
  exit 1
fi
go vet ./...
go run github.com/golangci/golangci-lint/cmd/golangci-lint@v1.64.5 run ./...
go test ./...
popd >/dev/null
