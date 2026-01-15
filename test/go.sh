#!/usr/bin/env bash
set -euo pipefail

pushd host-mcp-gateway >/dev/null
go test ./...
popd >/dev/null
