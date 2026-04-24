# Dashboard Window Management Plan
This document defines the intended window-management model for the dashboard
workspace. It is a design plan for the out-of-band Textual UI, not a runtime
architecture contract for Brain itself.

------------------------------------------------------------------------
## Purpose
The dashboard needs a pane system that feels closer to a terminal multiplexer or
editor split model than to a fixed grid.

The window-management system exists to provide:
- deterministic pane placement
- keyboard-driven focus movement
- split/tiling behavior that adapts to pane count and terminal size
- a maximized or zoomed pane mode
- clean separation between layout concerns and view content concerns
- one shared inspection-context surface for explicit cross-view correlation
- one shared action model for workspace, temporal, context, and view actions
- user-configurable keybindings and startup behavior

------------------------------------------------------------------------
## Non-Goals
The window-management system is not intended to provide:
- arbitrary floating windows
- drag-and-drop interaction
- direct control over Brain runtime behavior
- browser-style CSS layout semantics
- a second tmux implementation with session persistence and shell management

------------------------------------------------------------------------
## Core Principles
### Workspace Owns Layout
The `Workspace` is the sole owner of layout state.

Panes do not create, remove, split, or rearrange other panes directly.
Panes are layout slots only. The content inside a pane is a view.

### Binary Split Tree
The canonical internal layout representation is a binary split tree.

Each internal node defines:
- split orientation
- ratio between the two children

Each leaf node defines:
- one pane, identified by a pane id
- the view currently loaded into that pane, or None if the pane is empty

This yields tmux-like or vim-like split behavior while keeping the model small,
deterministic, and easy to mutate.

### State First, Rendering Second
Layout is not inferred from mounted view structure.

Instead:
1. mutate pure Python workspace state
2. derive a layout tree
3. render nested Textual containers from that tree

### Content Is Separate from Placement
Views render content.
The workspace decides where and how panes appear.

No view should encode assumptions about:
- whether it is top, bottom, left, or right
- how large it is allowed to be
- whether it is maximized
- who its neighbors are

### Canonical Actions
Keybindings map to high-level actions, not to ad hoc implementation details.

Examples:
- `focus_left`
- `focus_right`
- `split_horizontal`
- `split_vertical`
- `maximize`
- `close_view`
- `close_pane`
- `quit`

This keeps keyboard configuration stable even if the implementation changes.

------------------------------------------------------------------------
## Terminology
- _Workspace_: the central dashboard view that owns pane layout and focus
- _Pane_: a layout slot in the split tree; a container that holds at most one
  view at a time
- _View_: a content unit loaded into a pane; one of `trace`, `turn`,
  `policy`, `log`, `host`, `llm`
- _Empty Pane_: a pane with no view loaded; shows a numbered picker so the user
  can load a view
- _Leaf_: one layout-tree node containing a pane id
- _Split_: one layout-tree node containing exactly two children and an
  orientation
- _Orientation_: `horizontal` or `vertical`
- _Ratio_: the relative size distribution between two sibling nodes
- _Focused Pane_: the pane currently targeted by navigation and pane-level
  actions
- _Maximized Pane_: the single pane temporarily expanded to occupy the workspace
- _Inspection Context_: a structured workspace-level correlation object that
  views may publish to or follow
- _Temporal Cursor_: the point in a view's buffered history to which its
  viewport is anchored
- _Live Edge_: the most recent retained point currently available to a view
- _Live-Follow_: viewport mode where the cursor tracks the live edge
- _Frozen_: viewport mode where the cursor is detached from the live edge while
  acquisition continues

------------------------------------------------------------------------
## Workspace Model
The workspace maintains state roughly equivalent to:

```text
WorkspaceState
- focused_pane_id: str | None
- maximized_pane_id: str | None
- root: LayoutNode | None
- inspection_context: InspectionContext
- pane_context_follow: dict[str, bool]
- pane_temporal_mode: dict[str, "follow" | "frozen"]

LayoutNode
- split: "horizontal" | "vertical" | None
- ratio: int | None
- children: tuple[LayoutNode, LayoutNode] | None
- pane_id: str | None
- view_id: str | None   # None means the pane is empty
```

Rules:
- a node is either a split node or a leaf node, never both
- split nodes always have exactly two children
- leaf nodes always map to exactly one pane id
- leaf nodes carry `view_id`, which is `None` when the pane is empty
- ratios apply only to split nodes
- `root` is `None` only when the workspace has never been rendered; in practice,
  at least one empty pane is always present
- workspace state owns shared inspection context and pane-level follow state;
  individual views own only their local selection and pinned state

Suggested shared inspection context shape:

```text
InspectionContext
- turn_id: str | None
- trace_id: str | None
- envelope_id: str | None
- component: str | None
- provider: str | None
- model: str | None
- op_ref: str | None
- focal_timestamp: datetime | None
- time_range_start: datetime | None
- time_range_end: datetime | None
- source_pane_id: str | None
- published_at: datetime | None
```

Rules:
- the workspace owns exactly one current inspection context object
- views may publish a partial context; omitted fields remain `None`
- views may choose to follow or ignore the shared context
- follow state must be explicit and visible
- a view may pin local state, which detaches it from future context updates
- panes remain structurally independent even when several views follow the same
  context

------------------------------------------------------------------------
## Canonical View Set
View type ids:
- `trace`
- `turn`
- `policy`
- `log`
- `host`
- `llm`

Rules:
- any of these view types can be loaded into any pane
- if the same view type is loaded into two different panes, each instance is
  fully independent: separate scroll position, selection state, modal state, and
  temporal cursor, context follow state, and data subscription
- a pane may be empty (no view loaded); this is a normal, first-class state

------------------------------------------------------------------------
## Empty Pane Behavior
An empty pane shows a view picker — a numbered list of available view types the
user can load.

Picker keys correspond to the view type list and allow loading a view by
pressing the associated number key.

The picker has two rendering modes depending on context:

Welcome treatment: when the empty pane is the only pane visible, it receives
styled welcome treatment — a decorative heading, brief orientation text, and the
picker list. This is the startup surface.

Plain picker: when the empty pane appears alongside other panes (for example,
after splitting), it renders a plain picker with no special heading or decoration.

The distinction is a rendering concern on the empty pane, not a separate pane
type. There is no `WelcomePane` class; there is only an empty pane that renders
differently depending on whether it is the sole pane.

------------------------------------------------------------------------
## Layout Behavior
### Normal Tiled Mode
In normal mode, panes are arranged by the layout tree.

Each leaf in the tree corresponds to one mounted pane container.

### Maximized Mode
When a pane is maximized:
- the maximized pane occupies the full workspace
- the underlying split tree is preserved
- exiting maximized mode restores the prior tree layout unchanged

### Single Empty Pane (Welcome State)
When the workspace contains exactly one empty pane and no loaded views:
- render the pane with welcome treatment
- no split tree manipulation is required; the single leaf is the root

------------------------------------------------------------------------
## Split and Collapse Rules
### Splitting
Splitting a focused pane:
1. finds the focused leaf
2. replaces that leaf with a split node
3. makes the original pane one child
4. inserts a new empty pane as the other child
5. assigns an initial default ratio
6. focuses the new empty pane

Two split actions exist:
- `split_horizontal`
- `split_vertical`

The new pane always starts empty, showing the plain picker.

### Closing a View
When a pane has a view loaded, `close_view` (`q`):
1. unloads the view from the pane
2. the pane transitions to the empty/picker state
3. the pane itself remains in the split tree
4. any local pinned state or view-owned temporal cursor is discarded with the
   unloaded view instance

### Closing a Pane
When a pane is empty, `close_pane` (`q`):
1. removes the leaf from the tree
2. if its parent now has only one remaining child, collapse the parent
3. promote the remaining child into the collapsed parent's place

If closing the pane would leave zero panes visible, do not close it. Keep the
pane in the empty/welcome state rather than collapsing the workspace to nothing.

------------------------------------------------------------------------
## Insertion Strategy
Splitting always inserts a new empty pane adjacent to the focused pane.

There is no insertion strategy for named views — views are not inserted by the
workspace; they are loaded into existing panes by the user via the picker.

The only relevant insertion rule is:
- if no pane is focused when a split action is invoked, the action is a no-op

------------------------------------------------------------------------
## Focus Movement
Focus movement should feel spatial, not merely sequential.

Canonical actions:
- `focus_left`
- `focus_down`
- `focus_up`
- `focus_right`
- `focus_next`
- `focus_previous`

Rules:
- directional focus should prefer the nearest visible pane in the requested
  direction
- `focus_next` and `focus_previous` provide deterministic fallback traversal
- if only one pane is visible, focus remains on that pane

------------------------------------------------------------------------
## Shared Inspection Context
The workspace owns one shared inspection context for explicit cross-view
correlation.

Views interact with it in exactly three ways:
- publish context: a selection or focus change emits a structured context
  update
- follow context: the view updates its local scope when compatible context
  fields change
- pin local state: the view stops following and keeps its current local scope

Rules:
- no view is required to follow shared context
- no context update may rearrange panes or change layout
- context following must be explicit and reversible
- a view that cannot interpret the current context ignores incompatible fields
  rather than inventing a mapping

Illustrative workflows:
- selecting a turn in `TurnView` publishes `turn_id`, `trace_id` when known,
  `provider`, `model`, and a focal timestamp
- a `TraceView` opened in another pane follows that context and scopes itself
  to the selected turn or trace
- from `TraceView`, selecting an envelope publishes `trace_id`, `envelope_id`,
  `component`, and focal time so `LogView` can filter to correlated log events
- from `LLMView`, selecting a provider/model pair publishes `provider`, `model`,
  and time range so other views can investigate what drove current rate
  pressure

------------------------------------------------------------------------
## Temporal Model
Every view that renders changing operational data must use the same temporal
model.

The model separates:
- acquisition: ongoing ingestion into a bounded per-source or per-domain buffer
- viewport: the slice of buffered history the user is currently looking at

Key concepts:
- _buffer_: bounded retained history for one domain data source
- _live edge_: newest available point in that buffer
- _temporal cursor_: the point or window anchor the viewport is centered on
- _live-follow_: cursor tracks the live edge automatically
- _frozen_: cursor is detached from the live edge while acquisition continues

Operator actions:
- `freeze`: detach the viewport from the live edge; do not stop acquisition
- `step_backward`: move the cursor one semantic unit earlier
- `step_forward`: move the cursor one semantic unit later
- `jump_live`: move the cursor directly to the live edge
- `follow_live`: re-enable live-follow after a frozen inspection session

Semantic stepping rules:
- event-stream views step by event or visible row
- sampled-metric views step by sample interval or retained bucket
- entity/snapshot views step by entity version, selected item, or snapshot
  timestamp

Temporal state is view-local, but the action taxonomy is shared. No view may
invent incompatible freeze/follow semantics.

------------------------------------------------------------------------
## Resizing
Resize actions adjust the ratio of the relevant split.

Canonical actions:
- `resize_left`
- `resize_down`
- `resize_up`
- `resize_right`

Rules:
- resizing modifies only one split ratio at a time
- resize step is configuration-driven
- ratios must remain within sane bounds
- resizing a maximized pane has no effect until maximized mode is exited

------------------------------------------------------------------------
## Rendering Strategy
The split tree is rendered into nested Textual containers.

Mapping:
- horizontal split node -> `Horizontal` container
- vertical split node -> `Vertical` container
- leaf node -> pane wrapper container containing the loaded view or the empty
  picker

Pane wrapper responsibilities:
- apply border and title treatment
- reflect focused/unfocused state
- reflect maximized state if applicable
- host view content, or the empty picker when no view is loaded

The workspace renderer should not depend on implicit CSS grid auto-placement.
Every rendered container relationship should correspond to explicit layout
structure in the split tree.

------------------------------------------------------------------------
## Pane Wrapper Responsibilities
Each leaf should render through a wrapper that provides:
- title/header region
- body region (view or empty picker)
- optional footer or status region later
- visual focus treatment
- consistent padding and border handling

This prevents each view from re-implementing the same chrome.

------------------------------------------------------------------------
## Configuration Model
Window-management behavior must be configurable through:
- `config/dashboard.yaml.sample`
- `~/.config/brain/dashboard.yaml`

Keybindings should map to canonical actions, not to implementation-specific
functions.

Suggested config areas:
- startup layout (optional; defaults to single empty pane)
- startup focused pane
- default split orientation
- layout mode
- resize step
- default temporal behavior
- inspection-context follow defaults
- action-to-key binding mapping

The default startup state is one empty pane in welcome mode. Optionally, a
configured startup layout may specify an initial set of views auto-loaded into
a configured initial split tree. When no startup layout is configured, no view
loading happens automatically.

Illustrative shape:

```yaml
dashboard:
  startup:
    # Optional. Omit to start with a single empty welcome pane.
    # When provided, each entry specifies a view to auto-load and the
    # split relationship that places it.
    layout:
      - view: trace
      - split: horizontal
        view: turn
    focused_view: trace

  layout:
    mode: tiled
    default_split: horizontal
    resize_step: 5
    gap: 1

  temporal:
    default_mode: follow
    recent:
      event_seconds: 300
      sample_seconds: 600
      snapshot_count: 50

  context:
    follow_by_default: true

  keybindings:
    focus_left: ctrl+h
    focus_down: ctrl+j
    focus_up: ctrl+k
    focus_right: ctrl+l
    focus_next: tab
    focus_previous: shift+tab
    split_horizontal: s
    split_vertical: v
    maximize: enter
    close_view: q
    close_pane: q
    freeze: f
    step_backward: "["
    step_forward: "]"
    jump_live: g
    follow_live: F
    toggle_context_follow: c
    quit: Q
```

------------------------------------------------------------------------
## Keybinding Philosophy
The system should support vim-like or tmux-like muscle memory, but no specific
key set is architecturally privileged.

Rules:
- defaults exist in code
- user overrides live in dashboard config
- bindings target actions, not raw view methods
- action families must remain conceptually distinct:
  - global workspace actions
  - temporal actions
  - context actions
  - view-specific actions

The `q` key is context-sensitive: on a pane with a loaded view it triggers
`close_view`; on an empty pane it triggers `close_pane`. The workspace
dispatches to the correct action based on the focused pane's state.

`Q` (shift+q) always quits the application regardless of pane state.

Temporal and context actions should preserve muscle memory across views whenever
possible. A key that freezes one live view should conceptually freeze any other
live view, even if the underlying stepping unit differs.

------------------------------------------------------------------------
## Layout Modes
The initial design should reserve room for multiple layout modes, even if only
one is implemented first.

Planned modes:
- `tiled`: split-tree layout
- `maximized`: one pane full workspace

Welcome treatment is a rendering variant of the tiled mode when a single empty
pane is present, not a distinct layout mode.

Possible future modes:
- `stacked`
- `tabbed`
- `auto`

------------------------------------------------------------------------
## Startup Behavior
On startup:
- load dashboard configuration
- if a startup layout is configured, construct the initial split tree and
  auto-load the specified views into their assigned panes
- if no startup layout is configured, start with a single empty pane in welcome
  treatment
- set the initial focused pane
- initialize empty shared inspection context
- initialize each loaded view in live-follow mode unless config says otherwise

------------------------------------------------------------------------
## Persistence Considerations
The plan does not require persistent layout serialization immediately, but the
model should support it later without redesign.

If persistence is introduced later, it should serialize:
- pane ids and their view assignments
- focused pane id
- maximized pane id
- split tree structure and ratios

------------------------------------------------------------------------
## Failure and Edge Cases
The window-management system should define behavior for:
- zero loaded views (normal; workspace shows one or more empty panes)
- one pane visible (no splits possible to navigate; focus remains)
- maximize when no pane is focused
- close_pane when it is the last pane (keep it empty rather than removing)
- close_view when the pane is already empty (no-op)
- resize when no applicable split exists
- directional focus with no neighbor in that direction
- configuration that references unknown view ids or unknown actions
- stepping in a frozen view at the start or end of retained history
- context publication from a view no other pane follows
- context follow on a view that cannot interpret the current context

Expected behavior should be explicit and non-surprising:
- invalid config values should fail validation
- impossible actions should no-op safely
- no action should corrupt the split tree
- acquisition must continue even when a pane is frozen

------------------------------------------------------------------------
## Testing Expectations
Window-management tests should cover:
- initial tree construction from a configured startup layout
- startup with no configured layout producing a single empty pane
- split operations in both orientations producing a new empty pane
- close_view transitioning a loaded pane back to empty picker state
- close_pane collapsing the tree correctly
- close_pane on the last pane keeping one empty pane rather than removing it
- maximize and restore behavior
- focus movement across representative layouts
- ratio adjustment and bounds enforcement
- config validation for view ids and action names
- rendering correspondence between tree shape and mounted container structure
- empty pane welcome treatment when it is the sole pane
- empty pane plain picker treatment when other panes are present
- shared inspection context publication and follow-state handling
- per-pane live-follow versus frozen temporal state
- preservation of acquisition while one or more panes are frozen

------------------------------------------------------------------------
## Contributor Notes
- Keep all split topology in `Workspace`, never in pane or view code.
- Keep layout state model pure Python and independent of Textual widget types.
- Keep rendering as a translation layer from layout state to nested containers.
- Keep keybindings action-based and configuration-driven.
- Do not rely on CSS grid auto-placement as the canonical layout system.
- The pane/view distinction is load-bearing: a pane is a layout slot, a
  view is content. Never conflate them in state, naming, or tests.
- Keep shared inspection context explicit, visible, and opt-in.
- Keep temporal behavior consistent across views: acquisition continues,
  viewports freeze.
- The welcome surface is not a special pane type; it is a rendering mode of the
  empty pane when it is the only pane visible.


------------------------------------------------------------------------
_End of Dashboard Window Management Plan_
