# Dashboard Logging Plan
This document defines the intended logging and log-streaming design for the
dashboard.

------------------------------------------------------------------------
## Purpose
The dashboard needs a live log surface that:
- shows recent operational activity
- correlates with trace and health information when possible
- correlates with shared inspection context when the operator opts in
- works across both host-local and containerized components
- remains read-only and out-of-band

------------------------------------------------------------------------
## Core Principles
### One Abstraction
The dashboard should consume logs through one canonical source abstraction, not
through view-specific readers.

Suggested abstraction:
- `LogSource`

Responsibilities:
- yield raw log lines or structured log payloads
- identify source/component metadata
- support follow/stream semantics
- maintain bounded event history independent of viewport follow state

### File First
When durable file logs exist and are readable, prefer them.

Reasoning:
- they are usually more stable
- they are often already structured
- they do not depend on container runtime availability

### Docker Is Fallback, Not Default
Docker logs are a fallback for containerized components when file logs are
missing, unreadable, or not configured.

They are not the canonical source when readable file logs already exist.

### Host-Metal Components Stay Host-Metal
The gateway is host-side and should never be treated as containerized.

Its fallback path must remain host-local, not Docker-based.

### Normalize Before Rendering
The log view should render canonical dashboard log events, not raw lines from
heterogeneous sources.

------------------------------------------------------------------------
## Component Source Policy
### Containerized Components
The following components may use Docker as a fallback source:
- `core`
- `agent`
- `signal`
- `postgres`
- `valkey`
- `qdrant`

Source preference:
1. file logs
2. Docker logs

### Host-Local Components
The following component is host-local:
- `gateway`

Source preference:
1. file logs
2. host-local runtime log source

Never use Docker logs for `gateway`.

------------------------------------------------------------------------
## Source Types
### `FileLogSource`
Reads logs from a configured file path.

Behavior:
- open file read-only
- on startup, tail the last configured `N` lines
- continue following appended content
- if a read fails or the file handle becomes invalid, attempt to reopen

Intentionally omitted for now:
- explicit rotation detection
- inode tracking
- truncation-specific logic

If reopening succeeds, resume following.
If reopening fails, continue retrying on the source refresh cadence.

### `DockerLogSource`
Streams logs from one configured container.

Behavior:
- request recent historical lines on startup
- follow new stdout/stderr output
- attach container identity to each produced event

Use only for components that are actually containerized.

### `HostLocalLogSource`
Reads logs from a non-Docker host-local source when file logs are unavailable.

Initial expected use:
- gateway

This may still read from files, process-managed logs, or another local-only
runtime surface, but it must not assume Docker.

------------------------------------------------------------------------
## Selection Rules
For each component:
1. if configured file log exists and is readable, use `FileLogSource`
2. otherwise, if the component is containerized, use `DockerLogSource`
3. otherwise, if the component is host-local, use `HostLocalLogSource`
4. otherwise produce no live log stream for that component

Selection must be deterministic and component-specific.

------------------------------------------------------------------------
## Canonical Event Model
All raw log inputs should normalize into a canonical event model equivalent to:

```text
DashboardLogEvent
- timestamp: datetime | str
- level: str
- component: str
- source: str
- message: str
- trace_id: str | None
- envelope_id: str | None
- raw_payload: object
```

Rules:
- `component` is the dashboard’s canonical component id
- `source` identifies the transport or origin, such as `file`, `docker`, or
  `host-local`
- `raw_payload` is preserved for future drill-down or debugging

------------------------------------------------------------------------
## Decode and Normalize Pipeline
The intended pipeline is:

```text
raw source
  -> line reader / stream reader
  -> decoder
  -> normalizer
  -> canonical DashboardLogEvent
  -> in-memory buffer
  -> LogView
```

### Decoder
The decoder should:
- parse JSON log lines when possible
- otherwise treat the line as plain text

### Normalizer
The normalizer should:
- extract timestamp when present
- extract level when present
- extract message text
- extract `trace_id` and `envelope_id` when present
- fill `component` and `source`
- preserve raw payload

------------------------------------------------------------------------
## Streaming Model
The log system should support both:
- startup backfill
- follow mode

### Startup Backfill
On startup:
- fetch the last configured `N` lines from each active source
- normalize them
- append them to the in-memory event buffer in timestamp order where possible

### Follow Mode
When follow mode is enabled:
- keep active source readers running
- append normalized events to the event buffer as they arrive

Follow mode is a view concern only at the interaction level.
Source readers should still be capable of streaming regardless of whether the
view is visually focused or temporally frozen.

------------------------------------------------------------------------
## Buffering
The dashboard should keep a bounded in-memory ring buffer of normalized log
events.

Reasons:
- prevents unbounded growth
- decouples stream ingestion from rendering
- allows view-local filtering and navigation without re-reading sources

The log view should read from this buffer, not directly from the sources.

Retention semantics:
- logs are events
- `recent` means a bounded recent duration and/or bounded recent event count
- stepping in a frozen `LogView` moves by retained event, not by wall-clock
  second

------------------------------------------------------------------------
## Filtering
Filtering should happen after normalization and buffering.

Initial filter dimensions:
- component
- level
- text match
- trace id
- envelope id

The log view owns user-facing filter state.
Sources do not need to implement presentation filters.

------------------------------------------------------------------------
## Correlation
The log system should preserve enough metadata to support future correlation
between:
- log events
- traces
- envelopes
- policy decisions

At minimum, normalization should preserve:
- `trace_id`
- `envelope_id`
- component identity
- provider/model when present

When the operator enables shared inspection context following, `LogView` may
apply compatible context fields as filters:
- `trace_id`
- `envelope_id`
- `component`
- focal timestamp or time range

------------------------------------------------------------------------
## Refresh and Retry Behavior
### File Sources
File-source behavior:
- read appended content on the log refresh cadence
- if the file handle fails, attempt reopen
- if reopen fails, keep retrying on cadence

No additional rotation or truncation handling is required at this stage.

### Docker Sources
Docker-source behavior:
- reconnect or restart the stream when the Docker log stream fails
- if Docker cannot provide the stream, keep retrying on cadence

### Host-Local Sources
Host-local behavior:
- retry the configured source on failure
- if the source is unavailable, continue surfacing existing buffered history

------------------------------------------------------------------------
## Failure Semantics
Log-source failures must not crash the dashboard.

Rules:
- one source failure must not suppress unrelated sources
- source failures should degrade only the affected component stream
- malformed lines should not terminate a source reader
- decode failures should preserve the raw line as plain-text message content
- an unavailable source must surface as unknown or degraded, not as an empty
  successful stream

------------------------------------------------------------------------
## Configuration
Dashboard logging configuration should eventually define:
- file paths by component
- whether Docker fallback is allowed
- startup backfill line count
- refresh cadence
- buffer size
- default follow behavior

Illustrative shape:

```yaml
dashboard:
  logs:
    backfill_lines: 200
    buffer_size: 5000
    refresh_seconds: 0.5
    components:
      core:
        file: logs/brain-core.log
        docker_fallback: true
      agent:
        file: logs/brain-agent.log
        docker_fallback: true
      gateway:
        file: logs/host-mcp-gateway.log
        docker_fallback: false
```

------------------------------------------------------------------------
## Testing Expectations
Logging tests should cover:
- file-first source selection
- Docker fallback selection for containerized components
- host-local fallback selection for gateway
- startup backfill behavior
- follow-mode streaming behavior
- frozen viewport behavior while ingestion continues
- reopen-on-failure behavior for file sources
- JSON log-line decode
- plain-text fallback decode
- canonical normalization of `timestamp`, `level`, `message`, `trace_id`, and
  `envelope_id`
- bounded buffer behavior

------------------------------------------------------------------------
## Contributor Notes
- Keep source selection deterministic.
- Keep the gateway explicitly host-local.
- Prefer file logs when readable.
- Use Docker logs only as fallback for containerized components.
- Keep file-handle recovery simple: reopen on failure, no rotation logic yet.
- Keep normalization and buffering independent from view rendering.
- Keep log ingestion live even when the operator freezes a log viewport.


------------------------------------------------------------------------
_End of Dashboard Logging Plan_
