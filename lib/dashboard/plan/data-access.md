# Dashboard Data Access Plan
This document defines the data access strategy for the dashboard: how it
connects to Brain-owned substrates, what each view reads, and how data sources
present a uniform interface that abstracts the underlying refresh mechanism and
feeds bounded internal histories.

------------------------------------------------------------------------
## Purpose
The dashboard needs to read operational data from several substrates and
services that Brain owns. This document governs:

- where the dashboard sits relative to Brain's architecture
- the read-only invariant
- connection strategy per substrate
- per-view data source mapping
- the interface contract between data sources and views
- the layering between raw acquisition, normalized records, derived data, and
  view models
- temporal buffering and retention semantics
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
## Data Flow Layers
Dashboard data flow is split into four explicit layers.

### 1. Raw Acquisition
Substrate-specific readers fetch raw state from:
- Postgres
- Valkey
- files
- Docker
- host-local probes
- health endpoints

Raw acquisition is transport- and substrate-specific.

### 2. Normalized Records
Raw payloads normalize into canonical dashboard records with:
- stable ids where available
- normalized timestamps
- correlation fields such as `turn_id`, `trace_id`, `envelope_id`,
  `component`, `provider`, `model`, and `capability`
- provenance describing where the record came from

Normalization is where source heterogeneity is hidden.

### 3. Derived and Aggregated Data
Derived layers build on normalized records to produce:
- bounded histories
- windowed rates
- summaries
- pressure states
- cross-record aggregations

Windowed metrics belong here, not in view code.

### 4. View Models
View models are presentation-ready shapes for one view.

They may:
- select the relevant subset of normalized or derived data
- arrange fields for display
- pre-compute labels or compact summaries

They must not:
- perform substrate reads
- define retention policy
- compute heavy aggregations ad hoc during render

------------------------------------------------------------------------
## Read-Only Invariant
The dashboard must _never_ write to any Brain-owned state.

This applies to:
- Postgres (all schemas)
- Valkey
- the filesystem (Brain-owned logs, heartbeat files, vault)
- any Brain HTTP endpoint that mutates state

All dashboard connections to Brain substrates must be read-only by construction,
not merely by convention.

Enforcement:
- Postgres connections should use a read-only connection mode or a restricted
  database role when practical
- Valkey connections should use read-only commands only
- HTTP calls must target health/alive endpoints only, never mutation endpoints
- filesystem access must be read-only opens

Read-only also applies to temporal behavior:
- freezing a viewport must never pause or alter Brain-side systems
- backfill and follow behavior must be dashboard-local only

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

### Valkey
The dashboard connects to Valkey using the same connection parameters Brain Core
uses.

Source of connection parameters:
- `resources.yaml` under `substrate.valkey`
- environment variables following the `BRAIN_RESOURCES__SUBSTRATE__VALKEY__*`
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
## Temporal Model
All changing data sources feed bounded internal histories.

The temporal model distinguishes:
- acquisition: ingestion of new raw data into internal buffers
- viewport: the slice or anchor the operator is currently viewing

Acquisition continues independently of viewport state.

Core terms:
- _buffer_: bounded retained history for a dashboard data source or domain
- _live edge_: most recent retained record, sample, or snapshot
- _temporal cursor_: the record, sample bucket, or snapshot timestamp anchoring
  the current viewport
- _live-follow_: cursor tracks the live edge
- _frozen_: cursor is detached from the live edge while acquisition continues

Rules:
- `freeze` freezes the viewport, not the buffer
- stepping moves the temporal cursor within retained history only
- `jump_live` and `follow_live` restore the live edge as the viewport anchor
- no view may redefine these terms with local semantics

------------------------------------------------------------------------
## Time Semantics and Retention
The dashboard recognizes three temporal data families.

### Event
An event is a discrete occurrence with its own timestamp and identity.

Examples:
- log events
- policy decisions
- envelope execution records

Event buffers retain the newest `N` events or a bounded recent duration.
Stepping moves by event or visible row.

### Sample
A sample is a measurement captured at intervals.

Examples:
- CPU percentage
- disk I/O rate
- model token rate buckets

Sample retention keeps bounded recent windows or fixed-count samples.
Stepping moves by retained sample or bucket interval.

### Snapshot
A snapshot is the state of an entity or compact state surface at a point in
time.

Examples:
- current turn summary
- current approval state
- trace tree for one trace at one acquisition point

Snapshot retention keeps bounded recent snapshots or entity versions.
Stepping moves by snapshot timestamp, entity selection, or retained version.

### Recent Semantics
`recent` must be explicit per view family:
- event-heavy views: a recent duration and/or recent event count
- sampled views: a recent time window and sample interval
- snapshot views: a bounded recent entity count or snapshot count

The docs and config must avoid ambiguous uses of `recent`.

### Eviction Expectations
Buffers are bounded. Retention is not infinite.

High-level expectations:
- event buffers should behave like ring buffers or equivalent bounded histories
- sample buffers should evict oldest retained samples first
- snapshot histories should evict oldest retained snapshots or versions first
- eviction must not corrupt ordering, provenance, or correlation metadata
- the dashboard may indicate when the operator has reached the oldest retained
  history boundary

------------------------------------------------------------------------
## Correlation Model
The dashboard supports three correlation axes, and the data layer must preserve
enough information for all three:

### Entity Correlation
Relating records that describe the same unit of work.

Examples:
- turn -> trace
- trace -> envelope
- policy decision -> capability

### Temporal Correlation
Relating records that occurred at the same time or in the same retained time
window.

Examples:
- what logs surrounded this envelope at `14:31:59`
- what other components were active during this rate spike

### Resource Correlation
Relating activity to a shared resource or budget.

Examples:
- which turn or trace contributed to a provider/model token surge
- which model activity is driving projected rate-limit breach

Views may emphasize different axes, but normalized records and derived models
must preserve the fields needed for all of them.

------------------------------------------------------------------------
## Per-View Data Source Mapping
Each view has a defined set of data sources. The mapping below identifies the
substrate, schema (where applicable), and nature of each access.

### Header
- Postgres: connectivity ping only (no schema, no application queries)
- Valkey: `PING` only
- HTTP: health endpoints for core, signal, qdrant, gateway
- Docker: container inspect for core, agent, signal, qdrant
- Host process liveness: gateway
- Filesystem: heartbeat file for agent

Header data access is fully specified in the header plan.

### Trace View
- Postgres: reads from service-owned schemas that persist trace and envelope
  execution data
- Relevant schemas: those owned by services that record envelope lifecycle,
  trace metadata, and execution trees

The trace view reads normalized execution history to build the trace tree and
detail views specified in the trace view plan.

### Turn View
- Postgres: reads from the Memory Authority Service schema
  (`service_memory_authority`)
- Reads dialogue turn records, session records, and associated metadata

The turn view reads dialogue history to show recent conversation turns and
context assembly results.

### Policy View
- Postgres: reads from the Policy Service schema (`service_policy_service`)
- Reads policy decisions, approval proposals, and approval state

The policy view reads policy state to show pending approvals and recent decisions
as specified in the policy view plan.

### Log View
- Filesystem: log files by component
- Docker: container logs as fallback

Log view data access is fully specified in the logging plan.

### Host View
- Host system metrics via psutil-style calls
- No Brain data access

Host view data access is fully specified in the host view plan.

### LLM View
- Postgres and/or logs: reads normalized LLM request activity where
  provider/model usage can be reconstructed
- Optional config surface: provider/model budget or allowance metadata when
  available

The `LLMView` reads normalized model-usage records and derives windowed rate
pressure as specified in the `LLMView` plan.

------------------------------------------------------------------------
## Interface Contract
Each view consumes data through a _data source_ abstraction. The data source
presents a clean interface to the view and hides the underlying acquisition
mechanism.

### Principle
A view must not know or care whether its data arrived via:
- a periodic SQL poll
- a Postgres LISTEN/NOTIFY push
- a trigger-driven callback
- a Valkey subscription
- a filesystem watch

The view asks its data source for the current state. The data source is
responsible for keeping that state current, by whatever mechanism it uses
internally.

### Suggested Abstraction
Each data source should present an interface equivalent to:

```text
DataSource
- get_current() -> T | None
- get_snapshot() -> Snapshot[T]
- get_history() -> History[T]
- get_viewport(cursor: TemporalCursor | None) -> Viewport[T]
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
- provenance: list[ProvenanceRecord]
```

Where `History[T]`, `Viewport[T]`, and `TemporalCursor` are equivalent to:

```text
History[T]
- records: list[T]
- retention: RetentionPolicy
- live_edge_at: datetime | None

Viewport[T]
- data: T | None
- cursor: TemporalCursor | None
- mode: "follow" | "frozen"
- live_edge_at: datetime | None
- at_live_edge: bool

TemporalCursor
- anchor_time: datetime | None
- anchor_id: str | None
- anchor_index: int | None
```

`RetentionPolicy` is equivalent to:

```text
RetentionPolicy
- family: "event" | "sample" | "snapshot"
- max_items: int | None
- recent_seconds: int | None
- recent_count: int | None
```

`ProvenanceRecord` is equivalent to:

```text
ProvenanceRecord
- source_type: str
- source_name: str
- source_location: str | None
- observed_at: datetime | None
```

Rules:
- `get_current()` returns the most recently acquired data, or `None` if no data
  has been acquired
- `get_snapshot()` returns the data plus metadata about freshness and errors
- `get_history()` returns the retained bounded history used to derive viewports
- `get_viewport()` returns the render-ready state for one temporal cursor
- `is_stale()` returns `True` when the data has not been refreshed within the
  expected cadence
- `last_refreshed_at()` returns the timestamp of the most recent successful
  refresh
- the view never triggers a refresh directly; the data source manages its own
  refresh lifecycle
- the data source or its view-model layer, not the view, is responsible for
  deriving windowed metrics and temporal slices

### One Source Per View Domain
Each view should depend on one primary data source for its domain data.

Examples:
- the trace view depends on a trace data source
- the policy view depends on a policy data source
- the turn view depends on a turn data source
- the `llm` view depends on an LLM usage data source

A view should not scatter multiple independent substrate readers across its
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
  filesystem watches, or Valkey pub/sub
- more responsive, but requires deciding on a notification surface

### Current Default
The initial implementation should use polling.

Polling is the simplest mechanism that satisfies all requirements without
requiring any changes to Brain internals.

Each data source should poll its substrate on a configured cadence and update its
internal buffers and latest snapshot.

### The Requirement
The data source interface _must_ support either mechanism without requiring view
changes.

If the underlying mechanism later changes from polling to push-driven:
- the data source implementation changes
- the view code does not change
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
- llm: moderate to fast

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
- preserve source timestamps and correlation ids whenever the substrate exposes
  them

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
- views must render gracefully when their data source is in a failed or stale
  state
- connection failures must not leak connections or exhaust the pool
- query timeouts must be explicit and enforced
- no failure path may silently replace unknown data with zero-valued data

### Degradation Behavior
When a data source fails:
- the view should continue rendering the last known good data
- the view should visually indicate staleness or error state
- the data source should continue attempting to refresh on its normal cadence
- recovery should be automatic when the substrate becomes available again

The dashboard must preserve operator trust by distinguishing:
- no data retained yet
- data retained and value is zero
- data unavailable or unknown because acquisition failed

------------------------------------------------------------------------
## Configuration
Dashboard data access configuration should define:
- polling cadence per data source
- query timeouts
- connection pool sizing
- staleness thresholds
- retention bounds by view family
- recent-window defaults by view family
- optional LLM provider/model budgets

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
    llm:
      poll_seconds: 1.0
  retention:
    events:
      recent_seconds: 300
      max_items: 5000
    samples:
      recent_seconds: 600
      max_items: 1200
    snapshots:
      recent_count: 50
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
- retention-bound enforcement
- consistent distinction between event, sample, and snapshot histories
- provenance preservation through normalization
- view-model derivation of windowed rates outside view rendering code

------------------------------------------------------------------------
## Contributor Notes
- Keep the dashboard external to Brain's architecture in all data access code.
- Keep all substrate access read-only by construction.
- Keep the data source interface agnostic to push vs poll.
- Keep view code free of substrate-specific logic.
- Keep view code free of retention policy and windowed metric computation.
- Keep queries explicit, bounded, and schema-targeted.
- Keep normalized ids, timestamps, correlation fields, and provenance
  consistent across sources.
- Do not import or depend on Brain's SQLAlchemy models, ORM sessions, or
  internal service code.
- Do not add notification hooks, event listeners, or pub/sub channels inside
  Brain service code for dashboard purposes.
- Prefer simplicity. Polling works. Push can come later without rearchitecting.


------------------------------------------------------------------------
_End of Dashboard Data Access Plan_
