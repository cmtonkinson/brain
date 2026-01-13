# Host MCP Gateway

A host-side gateway that runs MCP servers requiring macOS APIs and exposes them to the containerized Brain agent through a single HTTP endpoint.

## Prerequisites

- macOS host
- Go 1.22+ (for building)
- MCP servers installed on the host (e.g., `mcp-eventkit`)
- `OTEL_EXPORTER_OTLP_ENDPOINT` set to your collector

## Build

```bash
go build -o host-mcp-gateway ./...
```

## Run

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=<endpoint> \
  ./host-mcp-gateway -config ~/.config/brain/host-mcp-gateway.json
```

## Install

```bash
go install ./...
```

This installs the binary to your Go `GOBIN` (or `GOPATH/bin`).

## Configuration

Copy the sample config and edit values as needed:

```bash
cp host-mcp-gateway/config/host-mcp-gateway.sample.json ~/.config/brain/host-mcp-gateway.json
```

Generate a token for `auth_token` (shared secret):

```bash
openssl rand -hex 32
```

or:

```bash
python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
```

Key fields:
- `bind_host`, `bind_port`
- `auth_token`
- `allowed_clients`
- `servers` (commands + args for each MCP server)

## Endpoints

- `GET /health`
- `GET /servers`
- `POST /rpc`

All requests require `Authorization: Bearer <token>`.

## Notes

- The gateway exits if `OTEL_EXPORTER_OTLP_ENDPOINT` is not set.
- This binary must run on the macOS host (not inside Docker).

## EventKit MCP Troubleshooting (Permissions + Install)

If the EventKit server shows `notDetermined` even after granting permissions, it usually means the **server binary never requested access** or you installed a **stale app bundle**.

Recommended path:

1) Patch the EventKit server to request permissions on startup (in your fork).
   - In `src/index.ts`, call `requestCalendarAccess()` and `requestAccess()` when not granted.

2) Rebuild the binary:

```bash
cd /path/to/mcp-server-eventkit
bun build --compile --outfile build/mcp-eventkit src/index.ts
```

3) Ensure the app bundle uses the rebuilt binary (fast path):

```bash
sudo cp /path/to/mcp-server-eventkit/build/mcp-eventkit \
  "/Applications/MCP EventKit.app/Contents/MacOS/mcp-eventkit"
```

4) Run the app-bundle binary once to trigger the prompts:

```bash
/Applications/MCP\ EventKit.app/Contents/MacOS/mcp-eventkit
```

You should see permissions move from `notDetermined` to `authorized`.

If you prefer rebuilding the installer:

```bash
APP_SIGN_IDENTITY="-" PKG_SIGN_IDENTITY="-" installer/build-pkg.sh 1.1.0
sudo installer -pkg dist/MCP-EventKit-Server-1.1.0.pkg -target /
```

Note: When you skip signing, the pkg build can still succeed but may print a missing `*-signed.pkg` warning if the script tries to move a signed package. The unsigned pkg is still usable locally.

Finally, point the gateway config to the **app-bundle binary**:

```
/Applications/MCP EventKit.app/Contents/MacOS/mcp-eventkit
```

## LaunchAgent (Auto-Start)

Use a LaunchAgent to keep the gateway running while you are logged in. A sample plist is provided at `host-mcp-gateway/launchd/brain.host-mcp-gateway.plist.sample`.

Steps:

1) Copy and edit the sample:

```bash
cp host-mcp-gateway/launchd/brain.host-mcp-gateway.plist.sample \\
  ~/Library/LaunchAgents/brain.host-mcp-gateway.plist
```

2) Replace `CHANGEME` paths with your username and ensure the binary path is correct.

3) Load the LaunchAgent:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/brain.host-mcp-gateway.plist
```

To unload:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/brain.host-mcp-gateway.plist
```
