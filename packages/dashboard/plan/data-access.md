# Dashboard Data Access Plan
This document defines the data access strategy for the dashboard: how it
connects to Brain-owned substrates, what each pane reads, and how data sources
present a uniform interface that abstracts the underlying refresh mechanism.

------------------------------------------------------------------------
## Purpose
The dashboard needs to read operational data from several substrates and
services that Brain owns. This document governs:

- where the dashboard sits relative to Brain's architecture
- the read-only invariant
- connection strategy per substrate
- per-pane data source mapping
- the interface contract between data sources and panes
- the open question of push vs poll refresh
- failure semantics
- configuration
- testing expectations

------------------------------------------------------------------------
## Architectural Position
The dashboard is an _external_ operator tool. It is not part of Brain's L0/L1/L2
architecture.

It is not an _Actor_. It is not a _Service_. It is not a _Resource_.

It is analogous to `psql` or Grafana: an out-of-band utility that reads
substrates for observability purposes. It does not participate in Brain's
runtime, does not use the Brain Core SDK, and does not send _Envelopes_.

### Schema Ownership Rules Do Not Apply
Brain's schema ownership model (each _Service_ owns its schema exclusively;
cross-schema access is prohibited) governs Brain's _runtime architecture_. The
dashboard is not subject to those rules.

The dashboard reading from multiple service-owned Postgres schemas is _not_ a
cross-schema access exception. It is an external tool reading a database, the
same way a reporting query or an admin console would.

### No Burden on Brain Internals
The dashboard must be responsible for its own data acquisition. Brain's internal
services, resources, and adapters must not be modified, decorated, or extended to
serve dashboard needs.

Mechanisms that would require changes to Brain service code are undesirable:
- ORM-level hooks or event listeners inside Brain services
- LISTEN/NOTIFY channels that Brain services must populate
- Brain-side pub/sub that exists solely for dashboard consumption

DB-level triggers (Postgres-side, not application-side) remain a possibility but
the decision is deferred.

------------------------------------------------------------------------
## Read-Only Invariant
The dashboard must _never_ write to any Brain-owned state.

This applies to:
- Postgres (all schemas)
- Redis
- the filesystem (Brain-owned logs, heartbeat files, vault)
- any Brain HTTP endpoint that mutates state

All dashboard connections to Brain substrates must be read-only by construction,
not merely by convention.

Enforcement:
- Postgres connections should use a read-only connection mode or a restricted
  database role when practical
- Redis connections should use read-only commands only
- HTTP calls must target health/alive endpoints only, never mutation endpoints
- filesystem access must be read-only opens

------------------------------------------------------------------------
## Connection Strategy
### Postgres
The dashboard connects to Postgres directly using the same connection parameters
Brain Core uses.

Source of connection parameters:
- `resources.yaml` under `substrate.postgres`
- environment variables following the `BRAIN_RESOURCES__SUBSTRATE__POSTGRES__*`
  convention

The dashboard must not maintain its own separate Postgres configuration surface.
It reads the same config Brain reads and derives its connection from that.

Connection behavior:
- use a lightweight connection pool appropriate for a single-process read-only
  client
- set `default_transaction_read_only` or equivalent to enforce the read-only
  invariant at the connection level
- set `search_path` per query or per cursor to target the appropriate
  service-owned schema
- use explicit timeouts on all queries

The dashboard does not use Brain's SQLAlchemy engine, ORM models, or session
infrastructure. It connects independently, using its own lightweight database
access layer.

### Redis
The dashboard connects to Redis using the same connection parameters Brain Core
uses.

Source of connection parameters:
- `resources.yaml` under `substrate.redis`
- environment variables following the `BRAIN_RESOURCES__SUBSTRATE__REDIS__*`
  convention

Connection behavior:
- read-only commands only (`PING`, `GET`, `LRANGE`, `KEYS`, etc.)
- no writes, no queue mutations, no pub/sub subscriptions that would alter
  Brain-side state
- explicit timeouts on all commands

### HTTP
The dashboard makes HTTP calls to health/alive endpoints only.

These are read-only probes used by the header health checks. The dashboard must
not call Brain Core SDK endpoints, capability invocation endpoints, or any
endpoint with side effects.

### Filesystem
The dashboard reads log files and heartbeat files from the host filesystem.

All file opens must be read-only. The dashboard must not write to, rotate,
truncate, or delete any file it reads.

Filesystem access is already covered by the logging plan and header plan.

### Docker
The dashboard reads container state and logs via the Docker API.

All Docker interactions must be read-only: container inspect, container logs,
container list. The dashboard must not start, stop, restart, or remove
containers.

Docker access is already covered by the logging plan and header plan.

------------------------------------------------------------------------
## Per-Pane Data Source Mapping
Each pane has a defined set of data sources. The mapping below identifies the
substrate, schema (where applicable), and nature of each access.

### Header
- Postgres: connectivity ping only (no schema, no application queries)
- Redis: `PING` only
- HTTP: health endpoints for core, signal, qdrant, gateway
- Docker: container inspect for core, agent, signal, qdrant
- Host process liveness: gateway
- Filesystem: heartbeat file for agent

Header data access is fully specified in the header plan.

### Trace Pane
- Postgres: reads from service-owned schemas that persist trace and envelope
  execution data
- Relevant schemas: those owned by services that record envelope lifecycle,
  trace metadata, and execution trees

The trace pane reads normalized execution history to build the trace tree and
detail views specified in the trace pane plan.

### Turn Pane
- Postgres: reads from the Memory Authority Service schema
  (`service_memory_authority`)
- Reads dialogue turn records, session records, and associated metadata

The turn pane reads dialogue history to show recent conversation turns and
context assembly results.

### Policy Pane
- Postgres: reads from the Policy Service schema (`service_policy_service`)
- Reads policy decisions, approval proposals, and approval state

The policy pane reads policy state to show pending approvals and recent decisions
as specified in the policy pane plan.

### Log Pane
- Filesystem: log files by component
- Docker: container logs as fallback

Log pane data access is fully specified in the logging plan.

### Host Pane
- Host system metrics via psutil-style calls
- No Brain data access

Host pane data access is fully specified in the host pane plan.

------------------------------------------------------------------------
## Interface Contract
Each pane consumes data through a _data source_ abstraction. The data source
presents a clean interface to the pane and hides the underlying acquisition
mechanism.

### Principle
A pane must not know or care whether its data arrived via:
- a periodic SQL poll
- a Postgres LISTEN/NOTIFY push
- a trigger-driven callback
- a Redis subscription
- a filesystem watch

The pane asks its data source for the current state. The data source is
responsible for keeping that state current, by whatever mechanism it uses
internally.

### Suggested Abstraction
Each data source should present an interface equivalent to:

```text
DataSource
- get_current() -> T | None
- get_snapshot() -> Snapshot[T]
- is_stale() -> bool
- last_refreshed_at() -> datetime | None
```

Where `Snapshot[T]` is equivalent to:

```text
Snapshot[T]
- data: T | None
- refreshed_at: datetime | None
- error: str | None
- stale: bool
```

Rules:
- `get_current()` returns the most recently acquired data, or `None` if no data
  has been acquired
- `get_snapshot()` returns the data plus metadata about freshness and errors
- `is_stale()` returns `True` when the data has not been refreshed within the
  expected cadence
- `last_refreshed_at()` returns the timestamp of the most recent successful
  refresh
- the pane never triggers a refresh directly; the data source manages its own
  refresh lifecycle

### One Source Per Pane Domain
Each pane should depend on one primary data source for its domain data.

Examples:
- the trace pane depends on a trace data source
- the policy pane depends on a policy data source
- the turn pane depends on a turn data source

A pane should not scatter multiple independent substrate readers across its
rendering code.

------------------------------------------------------------------------
## Refresh Strategy
### The Open Question
The notification mechanism for data refresh is intentionally deferred.

Two families of approach exist:

_Pull-driven (polling):_
- the data source periodically queries the substrate on a configured cadence
- simple, requires no Brain-side changes, works today

_Push-driven (event):_
- the data source receives notifications when data changes
- possible mechanisms include Postgres LISTEN/NOTIFY, DB-level triggers,
  filesystem watches, or Redis pub/sub
- more responsive, but requires deciding on a notification surface

### Current Default
The initial implementation should use polling.

Polling is the simplest mechanism that satisfies all requirements without
requiring any changes to Brain internals.

Each data source should poll its substrate on a configured cadence and update its
internal snapshot.

### The Requirement
The data source interface _must_ support either mechanism without requiring pane
changes.

If the underlying mechanism later changes from polling to push-driven:
- the data source implementation changes
- the pane code does not change
- the interface contract remains the same

This is the primary architectural requirement of the data source abstraction.

### Cadence
Polling cadence should be per-data-source and configuration-driven.

Suggested defaults:
- header health: fast (already specified in header plan)
- trace: moderate
- turn: moderate
- policy: moderate to fast (pending approvals benefit from responsiveness)
- log: already specified in logging plan
- host: moderate

Exact cadence values belong in configuration, not in this plan.

------------------------------------------------------------------------
## Query Strategy
### Schema Targeting
Each data source that reads Postgres must target the correct service-owned
schema.

The dashboard must not assume a default `search_path`. Each query should
explicitly reference the target schema or the data source should set
`search_path` on its connection/cursor before executing queries.

### Query Scope
Dashboard queries should be scoped and bounded.

Rules:
- always include a `LIMIT` clause or equivalent bound
- prefer queries that fetch only the most recent or currently relevant rows
- avoid full table scans
- avoid queries that would be expensive on large tables
- prefer indexed access paths

### No ORM
The dashboard does not use Brain's SQLAlchemy models or ORM infrastructure.

Queries should be explicit SQL, executed through a lightweight database access
layer. This keeps the dashboard decoupled from Brain's internal model
definitions and migration state.

The dashboard must tolerate schema evolution gracefully. If a column is renamed
or a table is restructured, the dashboard query layer is the only thing that
needs to change.

------------------------------------------------------------------------
## Failure Semantics
Data source failures must not crash the dashboard.

Rules:
- a failed data source refresh must not prevent other data sources from
  refreshing
- a failed refresh must preserve the most recently successful snapshot
- the snapshot must reflect the failure state (error populated, stale flag set)
- panes must render gracefully when their data source is in a failed or stale
  state
- connection failures must not leak connections or exhaust the pool
- query timeouts must be explicit and enforced

### Degradation Behavior
When a data source fails:
- the pane should continue rendering the last known good data
- the pane should visually indicate staleness or error state
- the data source should continue attempting to refresh on its normal cadence
- recovery should be automatic when the substrate becomes available again

------------------------------------------------------------------------
## Configuration
Dashboard data access configuration should define:
- polling cadence per data source
- query timeouts
- connection pool sizing
- staleness thresholds

Substrate connection parameters are _not_ configured separately. The dashboard
reads Brain's existing `resources.yaml` and environment variables.

Illustrative shape:

```yaml
dashboard:
  data_sources:
    defaults:
      poll_seconds: 2.0
      query_timeout_seconds: 5.0
      staleness_threshold_seconds: 10.0
    trace:
      poll_seconds: 2.0
    turn:
      poll_seconds: 2.0
    policy:
      poll_seconds: 1.0
  postgres:
    pool_size: 3
    read_only: true
```

------------------------------------------------------------------------
## Testing Expectations
Data access tests should cover:
- data source interface contract: `get_current`, `get_snapshot`, `is_stale`,
  `last_refreshed_at`
- snapshot freshness tracking after successful refresh
- snapshot staleness detection after missed refresh
- snapshot error preservation after failed refresh
- snapshot data preservation after failed refresh (last known good)
- read-only enforcement on Postgres connections
- schema targeting per data source
- query timeout enforcement
- connection failure handling without crash
- one data source failure not affecting others
- polling cadence respect

------------------------------------------------------------------------
## Contributor Notes
- Keep the dashboard external to Brain's architecture in all data access code.
- Keep all substrate access read-only by construction.
- Keep the data source interface agnostic to push vs poll.
- Keep pane code free of substrate-specific logic.
- Keep queries explicit, bounded, and schema-targeted.
- Do not import or depend on Brain's SQLAlchemy models, ORM sessions, or
  internal service code.
- Do not add notification hooks, event listeners, or pub/sub channels inside
  Brain service code for dashboard purposes.
- Prefer simplicity. Polling works. Push can come later without rearchitecting.


------------------------------------------------------------------------
_End of Dashboard Data Access Plan_
