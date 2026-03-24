# Dashboard
Local, read-only observability dashboard for Brain runtime behavior and
operational state.

------------------------------------------------------------------------
## What This Component Is
`packages/dashboard/` is a standalone Textual application for inspecting
Brain from outside the runtime architecture.

Core module roles:
- `main.py`: process entrypoint
- `app.py`: top-level Textual `App`
- `workspace.py`: pane visibility, focus, and layout orchestration
- `config.py`: dashboard-local runtime configuration
- `data_sources/`: read-only substrate readers
- `panes/`: primary workspace panes (`welcome`, `trace`, `turn`, `policy`, `log`)
- `widgets/`: shared chrome widgets (`health_header`, `keymap_footer`)
- `models/`: dashboard view models decoupled from raw substrate payloads

Launcher:
- `bin/dashboard`: local shell wrapper that resolves Python and executes
  `packages.dashboard.main`

------------------------------------------------------------------------
## Boundary and Ownership
Dashboard is not an _Actor_, _Service_, or _Resource_.

It is an out-of-band local utility with privileged read-only access to
operational substrates.

Boundary rules:
- Dashboard does not participate in Brain runtime orchestration.
- Dashboard does not call `brain_sdk`.
- Dashboard does not mutate Brain domain state.
- Dashboard may inspect local operational substrates strictly for
  observability.

------------------------------------------------------------------------
## Primary Data Sources
Primary observability inputs:
- PostgreSQL runtime state
- Redis queue/cache state
- local files and logs
- Docker/container runtime state

The dashboard converts raw substrate data into compact view models under
`models/` before rendering panes.

------------------------------------------------------------------------
## Workspace Model
The application keeps a fixed top header and bottom footer, with a central
workspace composed of independently togglable panes.

Initial pane set:
- `WelcomePane`
- `TracePane`
- `TurnPane`
- `PolicyPane`
- `LogPane`

High-level interaction model:
- numeric keys toggle panes
- `tab` cycles pane focus
- `enter` maximizes the focused pane
- `q` quits the app

------------------------------------------------------------------------
## Operational Flow (High Level)
1. User launches `bin/dashboard`.
2. `main.py` constructs and runs `BrainDashboardApp`.
3. `app.py` mounts a health header, workspace, and keymap footer.
4. `workspace.py` manages visible panes and layout state.
5. Panes pull read-only snapshots from `data_sources/`.
6. Panes render compact summaries derived from dashboard view models.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- Dashboard failures must not affect Brain runtime behavior.
- Substrate access failures should remain local to the dashboard and surface as
  degraded or unavailable pane/header state.
- The dashboard must fail safe: no mutation fallback, no hidden control paths,
  no runtime dependency from Brain services back to the dashboard.

------------------------------------------------------------------------
## Testing and Validation
Dashboard tests live in `packages/dashboard/tests/`.

Project-wide validation command:
```bash
make test integration
```

------------------------------------------------------------------------
## Contributor Notes
- Keep the dashboard out-of-band; do not turn it into an Actor.
- Keep substrate access read-only.
- Keep pane widgets focused on presentation, not raw substrate querying.
- Keep raw operational payload handling inside `data_sources/`.
- Keep dashboard-specific shaping in `models/`.


------------------------------------------------------------------------
_End of Dashboard README_
