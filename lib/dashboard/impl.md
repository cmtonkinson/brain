# Brain Dashboard — Implementation Plan

## Context

The `feat/dashboard` branch has detailed design specs (`lib/dashboard/plan/`) and stub
implementations. The stubs run and tests pass, but there are five foundational mismatches between
the stubs and the plan that must be resolved before any real view work can start:

1. **Workspace uses the wrong model.** Flat `_visible_pane_ids` list + CSS grid must become a
   binary split tree with pure-Python state and a rendering translation step.
2. **DashboardPane is the wrong base.** `Static.render()` returns a string; real views need
   `Widget.compose()` so Textual widgets (`Tree`, `RichLog`, `DataTable`) can be composed.
3. **Data sources have no contract.** The `fetch_*` methods are ad hoc; the plan specifies a typed
   protocol with snapshot metadata, temporal cursors, and error isolation.
4. **WelcomePane is an anti-pattern.** The plan's empty pane is a view picker, not a named class.
5. **App keybindings conflict with the picker.** `1–4` global toggles clash with the plan's number
   keys for picking views into panes.

## Phased Plan

### Phase 1 — Models and Data Source Protocol (pure Python, no Textual)

Establish typed foundation. No Textual imports.

**Files to create/replace:**
- `models/workspace.py` (new) — `WorkspaceState`, `LayoutNode`, `InspectionContext` as Pydantic models
- `models/data_source.py` (new) — `Snapshot[T]`, `History[T]`, `Viewport[T]`, `TemporalCursor`, `ProvenanceRecord`
- `models/trace.py` — replace stubs with `TraceTreeNode`, `TraceTreeView`, `TraceDetailView`
- `models/turn.py` — `CurrentTurnView`, `RecentTurnItemView`
- `models/policy.py` — `CurrentApprovalView`, `CurrentDecisionView`, `RecentPolicyItemView`
- `models/log_event.py` — `DashboardLogEvent` per logging plan
- `models/health.py` — `ComponentHealth` with `state: Literal["ok", "no", "unknown"]`

**Tests:** `WorkspaceState` mutation, `LayoutNode` tree operations, model field validation.

---

### Phase 2 — Data Source Protocol Implementations

Real polling pipeline; no Textual.

**Files to create/replace:**
- `data_sources/base.py` (new) — `DataSource[T]` protocol: `get_current()`, `get_snapshot()`,
  `get_history()`, `get_viewport()`, `is_stale()`, `last_refreshed_at()`; polling loop machinery
- `data_sources/postgres.py` — real `psycopg` connection (read-only), implement base class;
  queries stay placeholder `SELECT 1` for now
- `data_sources/valkey.py` — real connection skeleton, base class, error isolation
- `data_sources/logs.py` — `FileLogSource`, `DockerLogSource`; ring buffer, event normalization
- `data_sources/health.py` (new) — `HealthAggregator` running 7-component probe/normalize/aggregate
- `config.py` — expand `DashboardConfig` with per-source poll cadence, timeouts, retention;
  load from `~/.config/brain/dashboard.yaml` with fallback defaults

**Tests:** snapshot freshness/staleness, error preservation, last-good-data retention, health
normalization (`ok/no/unknown` mapping), config loading.

---

### Phase 3 — Binary Split Tree Workspace + Pane/View Separation

Largest architectural change. Clean break — delete stubs outright.

**Files to replace:**
- `workspace.py` — full replacement; `WorkspaceState` mutation operations (`split_horizontal`,
  `split_vertical`, `close_view`, `close_pane`, `maximize`, `focus_left/right/up/down/next`);
  workspace renderer translates pure-Python tree → mounted Textual containers
- `panes/base.py` — `DashboardPane(Static)` → `BaseView(Widget)`; views compose sub-widgets
- `app.py` — replace `1–4` toggle bindings with canonical action set (`focus_*`, `split_*`,
  `maximize`, `close_view`, `quit`); keybindings from config

**Files to create:**
- `panes/pane_wrapper.py` — `PaneWrapper(Container)`; border, title, focus treatment, maximized state
- `panes/empty_picker.py` — `EmptyPicker`; numbered view-type list; welcome treatment when sole pane;
  emits message to workspace to load view on key press

**Files to delete:**
- `panes/welcome.py`

**Tests:** `WorkspaceState` mutation, tree topology (split/close/collapse), empty picker rendering,
focus movement (spatial + sequential), maximize/restore.

---

### Phase 4 — Real View Implementations (in order)

Each view is a full replacement of the stub. Order: most standalone → most interconnected.

**4a — Log View** (`panes/log.py`, `data_sources/logs.py`)
Standalone; no Postgres. `RichLog` or `ListView` widget. Freeze/follow temporal model.
Component/level/text filter state.

**4b — Policy View** (`panes/policy.py`)
Current + recent layout. Simple Postgres query. Validates Postgres polling pipeline.

**4c — Turn View** (`panes/turn.py`)
Current + recent layout. Inbound/outbound pairing, pending/complete state.

**4d — Trace View** (`panes/trace.py`)
Most complex. Textual `Tree` widget for envelope DAG. Detail subview (adaptive orientation).
Expand/collapse, keyboard navigation.

**Tests per view:** render correctness against fixture data, space-constrained behavior,
freeze/follow step model, context publication/follow with fake `InspectionContext`.

---

### Phase 5 — Header, Footer, and Polish

**5a — Header** (`widgets/health_header.py`) — replace with `HealthAggregator`-backed widget;
correct `ok/no/??` colors; independent poll cadence.

**5b — Footer** (`widgets/keymap_footer.py`) — reactive `FooterBuilder`; observes workspace state,
focused pane, view temporal mode, context-follow state; width-adaptive item groups.

**5c — Inspect Modals** (`panes/modals/trace_inspect.py`, `panes/modals/turn_inspect.py`) —
Textual `Screen` overlays; requires complete view implementations.

**5d — Inspection Context Wiring** — wire `InspectionContext` publish/follow/pin across views;
requires all views to exist.

---

### Phase 6 — Host and LLM Views (deferred)

`panes/host.py` + `panes/llm.py` using `psutil` and aggregated LLM usage records respectively.
No cross-view correlation required for initial versions; can follow Phase 5 without blockers.

---

## Critical Files

| File | Status | Role |
|------|--------|------|
| `workspace.py` | Replace | Binary split tree replaces flat list |
| `panes/base.py` | Replace | `BaseView(Widget)` replaces `DashboardPane(Static)` |
| `data_sources/base.py` | Create | `DataSource[T]` protocol + polling machinery |
| `models/workspace.py` | Create | Pure-Python `WorkspaceState`, `LayoutNode`, `InspectionContext` |
| `app.py` | Replace | Canonical action set replaces `1–4` toggles |
| `panes/welcome.py` | Delete | Replaced by `EmptyPicker` |

## Verification

- `make test integration` after each phase
- Launch `bin/dashboard` and visually verify after Phase 3 (pane tiles, focus, maximize)
- After Phase 4a: log view scrolls, freeze/follow works with live `brain.log`
- After Phase 4d: trace view renders fixture DAG; keyboard navigation selects nodes
- After Phase 5: header reflects real container states; footer updates on focus change
