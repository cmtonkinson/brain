## Host MCP Gateway Daemon Spec

### Purpose
Provide a host-side gateway that runs MCP servers which require macOS APIs and exposes them to the containerized brain-agent through a single, secure network endpoint. This avoids bespoke bridges per MCP server and standardizes host/container communication.

### Goals
- Run host-only MCP servers (e.g., EventKit) on macOS.
- Expose a single gateway endpoint reachable from the container via `host.docker.internal`.
- Support multiple MCP servers behind one gateway.
- Enforce security controls (token auth, allowlist, local binding).
- Provide deterministic startup, shutdown, and restart behavior.
- Produce clear logs and health status for observability and debugging.
- Integrate with the existing observability stack (logs + metrics + tracing).

### Non-Goals
- Running MCP servers inside the container.
- Providing a full MCP client implementation inside the container.
- Replacing UTCP/Code-Mode in the agent.

### Top-Level Layout
Create a new top-level directory for the gateway:
- `host-mcp-gateway/`
  - `SPEC.md` (this document)
  - `README.md` (optional, short user-facing setup guide)
  - `config/` (sample configs)
  - `scripts/` (optional tooling for install/run)

### Architecture
1. The gateway runs on the macOS host.
2. The gateway spawns and manages MCP server processes using stdio.
3. The gateway exposes a single network interface (HTTP or TCP) to the container.
4. The container (brain-agent) connects to the gateway endpoint and requests MCP tool execution.
5. The gateway routes requests to the correct MCP server, collects responses, and returns them to the container.

### Interface and Transport
#### Gateway Endpoint
- Bind to `127.0.0.1` by default.
- Optional bind to `0.0.0.0` only if required for container access (recommended: use `host.docker.internal` on macOS and local bind).
- Port is configurable (default: `7411`).
- Health endpoint: `GET /health` returns version, uptime, and configured servers.
- List endpoint: `GET /servers` returns server registry and status.

#### Request Routing
Each MCP server is identified by a unique `server_id`. The gateway must:
- Map `server_id` to a command plus args for the MCP process.
- Forward MCP JSON-RPC requests to the target server over stdio.
- Relay MCP JSON-RPC responses back to the caller unmodified.

#### MCP Message Flow
The gateway is a pass-through for MCP JSON-RPC, with minimal wrapping:
- Client sends a request to the gateway specifying:
  - `server_id`
  - `payload` (raw MCP JSON-RPC request)
- Gateway forwards `payload` to the MCP server stdio.
- Gateway reads the MCP response and returns it to the client.
- The gateway does not interpret MCP tool content; it only routes and transports.

### Configuration
The gateway reads a local config file on the host:
- Default path: `~/.config/brain/host-mcp-gateway.json`
- Provide a sample config in `host-mcp-gateway/config/host-mcp-gateway.sample.json`

Required fields:
- `bind_host` (string)
- `bind_port` (int)
- `auth_token` (string)
- `allowed_clients` (array of CIDR or explicit IPs)
- `servers` (array)

Server entries:
- `server_id` (string, unique)
- `command` (string)
- `args` (array of strings)
- `working_dir` (string, optional)
- `env` (object map, optional)
- `autostart` (bool)
- `restart_policy` (string: `always`, `on-failure`, `never`)
- `startup_timeout_ms` (int, optional)

### Security Model
Mandatory:
- Token auth for all requests.
- Client IP allowlist; default allow only localhost.

Recommended:
- Gateway binds to loopback.
- Only container via `host.docker.internal` or explicit bridge access.
- Reject requests without valid `Authorization: Bearer <token>`.
- Log authentication failures with client IP and request path.

### Process Lifecycle
Gateway manages MCP server processes:
- On startup:
  - Load config.
  - Start all `autostart` servers.
  - Mark each server status: `starting`, `ready`, or `error`.
- At request time:
  - If server is not running and `autostart` is false, return a clear error.
  - If server is running, route requests normally.
- On crash:
  - Apply restart policy.
  - Record crash count and last exit code.
- On shutdown:
  - Gracefully terminate child processes, then force kill after timeout.

### Health and Status
`GET /health` returns:
- `status`: `ok` or `degraded`
- `version`
- `uptime_seconds`
- `servers`: list with status, pid, last_exit_code, restart_count

`GET /servers` returns:
- Full server registry
- `autostart`, `restart_policy`, and current state

### Observability (Required)
The gateway must ship logs, metrics, and traces into the existing observability stack.

Logging:
- Emit structured JSON logs to stdout/stderr.
- Include fields: timestamp, level, server_id, request_id, event, message.
- Log process start/stop, errors, auth failures, routing errors.

Metrics:
- Export via OTLP using `OTEL_EXPORTER_OTLP_ENDPOINT`.
- Provide at least:
  - Requests per server (counter)
  - Latency per server (histogram)
  - Process restarts per server (counter)
  - Auth failures (counter)

Tracing:
- Export via OTLP using `OTEL_EXPORTER_OTLP_ENDPOINT`.
- Create a span per gateway request, include `server_id` and `request_id` attributes.
- Include child spans for MCP process invocation and response read.

### Error Handling
Gateway returns errors in a consistent JSON shape:
- `error_code`
- `message`
- `server_id`
- `request_id` (if provided)

Never return partial MCP responses. If the MCP server dies mid-request:
- Return a gateway error indicating the server crashed.
- If restart policy allows, restart the server.

### Integration with Brain
In the container:
- UTCP/Code-Mode config should point MCP servers to the gateway endpoint instead of spawning locally.
- The agent never runs host MCP servers directly.

In the host:
- Install and run `mcp-eventkit` (and any other host MCP server).
- Configure the gateway to launch them.
- Keep all configs in `~/.config/brain/` to match repo conventions.

### Compatibility Constraints
- macOS only for host MCP servers that use EventKit.
- Gateway must run on macOS host and be reachable from Docker.
- Agent remains containerized and unmodified except for UTCP config.

### Testing Expectations
Manual:
- Start gateway, hit `/health`, confirm server status.
- Execute a known MCP tool via gateway, confirm response.
- Kill a MCP server process and verify restart policy.

Automated (if added later):
- Config validation tests.
- Request routing tests with a fake MCP server.
- Auth and allowlist tests.

### Rollout Plan
1. Implement gateway with minimal features: config, spawn, route, auth.
2. Add EventKit MCP server to gateway config.
3. Update UTCP config in `~/.config/brain/` to use gateway.
4. Validate end-to-end from container to EventKit.
