# Dashboard Header Plan
This document defines the intended design for the dashboard header health line.

------------------------------------------------------------------------
## Purpose
The header exists to provide a compact, continuously refreshed health summary
for a fixed set of operator-relevant components.

The header is not a general-purpose metrics surface.
It is a fast situational-awareness line.

------------------------------------------------------------------------
## Component Order
The header must always render components in this exact order:

1. `core`
2. `agent`
3. `postgres`
4. `redis`
5. `signal`
6. `qdrant`
7. `gateway`

------------------------------------------------------------------------
## Status Mapping
The header uses exactly three rendered states:

- green `OK`
- red `NO`
- gray `??`

Meaning:
- `OK`: the component responded positively to its canonical health signal
- `NO`: the component responded negatively to its canonical health signal
- `??`: the dashboard could not determine health, including absent, missing,
  disabled, unreachable, or probe failure conditions

`absent` and `unknown` are intentionally collapsed into `??`.

------------------------------------------------------------------------
## Architectural Split
Header health behavior is split into three layers:

1. fetch
2. normalize
3. render

### Fetch
Fetchers gather raw health signals from substrates.

Examples:
- container inspect state
- health endpoint response
- ping response
- heartbeat file freshness

Fetchers must not return pre-rendered strings.

### Normalize
Normalization converts raw probe results into one canonical dashboard health
model per component.

Examples of normalized states:
- `ok`
- `no`
- `unknown`

Normalization is where component-specific policy lives.

### Render
Rendering converts canonical health models into the fixed display format used by
the header.

The header widget must not contain substrate-specific health logic.

------------------------------------------------------------------------
## Canonical Health Model
The header should render from a canonical model equivalent to:

```text
ComponentHealth
- name: str
- state: "ok" | "no" | "unknown"
- detail: str
- checked_at: datetime
```

Rules:
- `name` must be one of the fixed header component ids
- `detail` is for logs, hover/debug, or future drill-down; it is not required in
  the compact header render
- the header itself renders only `name` and status token

------------------------------------------------------------------------
## Data Sources
The header should consume a dedicated health aggregation layer, not raw data
sources directly.

Suggested structure:

```text
data_sources/*
  raw probes

health.py or health/*
  canonical probe coordination + normalization

widgets/health_header.py
  compact rendering only
```

The header widget should depend on a single snapshot builder, not on multiple
substrate readers.

------------------------------------------------------------------------
## Component Checks
The exact checks below are the intended canonical health signals.

### `core`
Primary check:
- HTTP health call to Brain Core published health endpoint

Exact behavior:
- if the health endpoint responds and indicates ready/healthy, normalize to
  `OK`
- if the health endpoint responds and indicates not-ready/unhealthy, normalize
  to `NO`
- if the endpoint cannot be reached, times out, or the target is not present,
  normalize to `??`

Secondary fallback:
- Docker container inspect for `brain-core`

Fallback behavior:
- if HTTP health is unavailable but Docker shows container present and healthy,
  normalize to `OK`
- if Docker shows container present and unhealthy/exited, normalize to `NO`
- if Docker cannot determine state, normalize to `??`

Reasoning:
- prefer app-level health over container liveness
- container state is fallback only

### `agent`
Primary check:
- heartbeat file freshness

Exact behavior:
- if the heartbeat file exists and its age is within the configured freshness
  threshold, normalize to `OK`
- if the heartbeat file exists but is stale, normalize to `NO`
- if the heartbeat file is missing or unreadable, normalize to `??`

Secondary fallback:
- Docker container inspect for `brain-agent`

Fallback behavior:
- if heartbeat cannot be evaluated and Docker shows container present and
  healthy/running, normalize to `OK`
- if Docker shows container present and unhealthy/exited, normalize to `NO`
- if Docker cannot determine state, normalize to `??`

Reasoning:
- the agent is long-lived and has a heartbeat; that is a better signal than
  process existence alone

### `postgres`
Primary and only canonical check:
- direct Postgres connectivity ping

Exact behavior:
- attempt to establish a connection and execute a connection-level health signal
  only
- if the database responds successfully, normalize to `OK`
- if the database responds negatively or the connection is explicitly rejected,
  normalize to `NO`
- if the database cannot be reached or probed, normalize to `??`

Constraint:
- do not use arbitrary application queries as the header health signal

Reasoning:
- the header should reflect substrate availability, not application data
  semantics

### `redis`
Primary and only canonical check:
- Redis `PING`

Exact behavior:
- if `PING` succeeds, normalize to `OK`
- if Redis responds negatively or with an explicit error state, normalize to
  `NO`
- if Redis cannot be reached or the probe fails, normalize to `??`

### `signal`
Primary check:
- HTTP health/alive endpoint exposed by the Signal runtime, if available

Exact behavior:
- if the Signal runtime responds positively to a health/alive probe, normalize
  to `OK`
- if it responds negatively, normalize to `NO`
- if no health endpoint is available or the probe cannot be completed,
  normalize to `??`

Secondary fallback:
- Docker container inspect for `signal-api`

Fallback behavior:
- if runtime probing is unavailable and the container is healthy/running,
  normalize to `OK`
- if the container is unhealthy/exited, normalize to `NO`
- otherwise normalize to `??`

Reasoning:
- prefer adapter/runtime reachability over bare container state

### `qdrant`
Primary check:
- Qdrant health/readiness endpoint or client health call

Exact behavior:
- if Qdrant responds positively, normalize to `OK`
- if Qdrant responds negatively, normalize to `NO`
- if Qdrant cannot be reached or the probe cannot be completed, normalize to
  `??`

Secondary fallback:
- Docker container inspect for `qdrant`

Fallback behavior:
- use healthy/running -> `OK`
- unhealthy/exited -> `NO`
- indeterminate -> `??`

### `gateway`
Primary check:
- Host MCP Gateway health/alive endpoint

Exact behavior:
- if the gateway health endpoint responds positively, normalize to `OK`
- if it responds negatively, normalize to `NO`
- if it is not configured, not running, or cannot be reached, normalize to `??`

Secondary fallback:
- process or container liveness only if a proper health endpoint is unavailable

Fallback behavior:
- if the backing process/container is clearly alive, normalize to `OK`
- if it is clearly dead, normalize to `NO`
- otherwise normalize to `??`

Reasoning:
- gateway is a host-adjacent component; the dashboard should rely on the most
  explicit alive/health signal available

------------------------------------------------------------------------
## Probe Rules
### Prefer Explicit Health Signals
When available, prefer:
- health endpoints
- alive endpoints
- ping operations
- heartbeat freshness

Do not prefer:
- arbitrary application queries
- domain-level operations
- actions with side effects

### Read-Only Only
All header checks must be read-only.

No header probe may:
- mutate state
- enqueue work
- invoke capabilities
- alter runtime configuration

### Timeouts
Each probe must have an explicit timeout.

Timeout expiry normalizes to `??`, not `NO`, unless the target explicitly
responds unhealthy.

### Refresh Cadence
Header health should refresh independently of pane content refresh.

Suggested behavior:
- one shared header refresh cadence
- faster than heavy pane polling
- slow enough to avoid unnecessary substrate churn

------------------------------------------------------------------------
## Normalization Rules
The normalizer should apply these rules consistently:

- positive health/alive/ping response -> `ok`
- explicit unhealthy or failing health response -> `no`
- timeout, missing target, disabled target, probe exception, unreadable signal,
  or unsupported probe path -> `unknown`

Rendered mapping:
- `ok` -> `OK`
- `no` -> `NO`
- `unknown` -> `??`

------------------------------------------------------------------------
## Rendering Rules
The header render format is:

```text
core OK  agent OK  postgres OK  redis ??  signal NO  qdrant OK  gateway ??
```

Rules:
- keep the fixed component order
- no pipe separators
- component names are lowercase canonical ids
- status token is two characters exactly
- color only the token, not the component name

------------------------------------------------------------------------
## Failure Semantics
Header failures must remain local to the dashboard.

Rules:
- a probe failure must not crash the app
- one component probe failure must not suppress other component statuses
- normalization must always produce one status for every configured header item

------------------------------------------------------------------------
## Testing Expectations
Header tests should cover:
- canonical component ordering
- `OK` mapping for successful probes
- `NO` mapping for explicit unhealthy probes
- `??` mapping for timeouts, missing targets, and probe exceptions
- fallback behavior for `core`, `agent`, `signal`, `qdrant`, and `gateway`
- rendering format with no separators
- colorization of only the status token

------------------------------------------------------------------------
## Contributor Notes
- Keep fetch, normalize, and render strictly separate.
- Keep the header widget dumb.
- Keep component-specific health policy in the normalization layer.
- Prefer health/alive/ping/heartbeat checks over arbitrary queries.
- Do not couple header status to domain-level application state.


------------------------------------------------------------------------
_End of Dashboard Header Plan_
