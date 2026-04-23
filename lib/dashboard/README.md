# Dashboard
`btop` for Brain: local, read-only observability dashboard for runtime behavior
and operational state.

------------------------------------------------------------------------
## What This Component Is
`lib/dashboard/` is a standalone Textual application for inspecting
Brain from outside the runtime architecture.

Core module roles:
- `main.py`: process entrypoint
- `app.py`: top-level Textual `App`
- `workspace.py`: pane visibility, focus, and layout orchestration
- `config.py`: dashboard-local runtime configuration
- `data_sources/`: read-only substrate readers
- `panes/`: primary workspace views (`welcome`, `trace`, `turn`, `policy`,
  `log`, `host`, `llm`)
- `widgets/`: shared chrome widgets (`health_header`, `keymap_footer`)
- `models/`: dashboard view models decoupled from raw substrate payloads

Launcher:
- `bin/dashboard`: local shell wrapper that resolves Python and executes
  `lib.dashboard.main`

------------------------------------------------------------------------
## Boundary and Ownership
Dashboard isn't "in" the _Layer_/_Service_ architecture; it's not an _Actor_,
_Service_, or _Substrate_. It is an out-of-band local utility with privileged
read-only access to operational state. Dashboard:
- Does not participate in Brain runtime orchestration
- Does not call `sdk`
- Does not mutate Brain domain state
- May inspect local operational substrates strictly for observability

------------------------------------------------------------------------
## Primary Data Sources
The dashboard converts raw substrate data into compact view models under
`models/` before rendering views inside panes. Primary observability inputs:
- PostgreSQL runtime state
- Valkey queue/cache state
- local files and logs
- Docker/container runtime state

Dashboard data flow is layered:
- raw acquisition: substrate reads from Postgres, Valkey, files, Docker, host
  probes, and health endpoints
- normalized records: canonical dashboard records with stable ids, timestamps,
  correlation fields, and provenance
- derived data: bounded histories, rates, summaries, and other aggregations
- view models: presentation-ready state consumed by one view

Views render view models. They do not query substrates directly and they do not
compute windowed metrics ad hoc.

------------------------------------------------------------------------
## Workspace Model
Key Terms:
- **Workspace**: the central tiling region of the application, between the fixed
  header and footer.
- **Pane**: a rectangular layout slot within the Workspace. A Pane may be empty
  or may host exactly one View. Dashboard starts with one single, active, empty
  Pane. The active Pane can be split horizontally or vertically to create a new
  Pane, similar to tmux.
- **View**: the content loaded into a Pane, such as `TraceView`, `TurnView`,
  `PolicyView`, `LogView`, `HostView`, or `LLMView`.

Illustrative structure:

```text
DashboardApp
├─ HealthHeader
├─ Workspace
│  ├─ Pane A
│  │  └─ TraceView
│  └─ Pane B
│     └─ LogView
└─ KeymapFooter
```

The header and footer are fixed application chrome, not Workspace Panes.

Pane lifecycle and View lifecycle are distinct:
- Pane lifecycle: split, focus, resize, maximize, collapse
- View lifecycle: load into a Pane, render, refresh, unload

The workspace also owns two shared state surfaces:
- _inspection context_: explicit, structured correlation state published by one
  view and optionally followed by others
- _temporal state_: the distinction between ongoing acquisition into bounded
  buffers and the viewport each pane is currently inspecting

Views remain structurally independent. Shared context and temporal following are
explicit opt-in behaviors, not hidden global synchronization.

The result is a small tiling window manager specialized for Brain observability.

------------------------------------------------------------------------
## Correlation Model
The dashboard supports three distinct correlation axes:
- _entity correlation_: how `turn`, `trace`, `envelope`, `policy`, and `log`
  records refer to the same unit of work
- _temporal correlation_: what else happened at the same time or in the same
  time window
- _resource correlation_: which activity contributed to shared budgets or rate
  pressure, such as provider/model token usage

These axes are related but not interchangeable. The dashboard uses explicit
inspection context and provenance-preserving normalized records so views can
correlate intentionally without becoming globally synchronized.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. User launches `bin/dashboard`.
2. `main.py` constructs and runs `BrainDashboardApp`.
3. `app.py` mounts a health header, workspace, and keymap footer.
4. `workspace.py` manages visible panes and layout state.
5. Data sources acquire read-only data into bounded internal buffers.
6. Views derive viewport state from the current buffer, temporal cursor, and
   optional inspection context.
7. Panes render the selected view plus pane chrome.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- Dashboard failures must not affect Brain runtime behavior.
- Substrate access failures should remain local to the dashboard and surface as
  degraded or unavailable pane/header state.
- The dashboard must fail safe: no mutation fallback, no hidden control paths,
  no runtime dependency from Brain services back to the dashboard.
- The dashboard must distinguish clearly between:
  - no data
  - zero value
  - unknown or unavailable
- The dashboard must preserve operator trust through:
  - read-only guarantees
  - visible provenance
  - explicit degraded states
  - no silent fallback from one semantic state to another

------------------------------------------------------------------------
## Testing and Validation
Dashboard tests live in `lib/dashboard/tests/`.

Project-wide validation command:
```bash
make test integration
```

------------------------------------------------------------------------
## Contributor Notes
- Keep the dashboard out-of-band; do not turn it into an Actor.
- Keep substrate access read-only.
- Keep pane views focused on presentation, not raw substrate querying or
  windowed metric computation.
- Keep raw operational payload handling inside `data_sources/`.
- Keep dashboard-specific shaping in `models/`.
- Keep the `App`/`Pane`/`View` distinction explicit: the `App` manages `Pane`s,
  and `Pane`s host `View`s.


------------------------------------------------------------------------
_End of Dashboard README_
