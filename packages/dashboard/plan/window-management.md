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
- clean separation between layout concerns and widget content concerns
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
Panes are layout slots only. The content inside a pane is a widget.

### Binary Split Tree
The canonical internal layout representation is a binary split tree.

Each internal node defines:
- split orientation
- ratio between the two children

Each leaf node defines:
- one pane, identified by a pane id
- the widget currently loaded into that pane, or None if the pane is empty

This yields tmux-like or vim-like split behavior while keeping the model small,
deterministic, and easy to mutate.

### State First, Rendering Second
Layout is not inferred from mounted widget structure.

Instead:
1. mutate pure Python workspace state
2. derive a layout tree
3. render nested Textual containers from that tree

### Content Is Separate from Placement
Widgets render content.
The workspace decides where and how panes appear.

No widget should encode assumptions about:
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
- `close_widget`
- `close_pane`
- `quit`

This keeps keyboard configuration stable even if the implementation changes.

------------------------------------------------------------------------
## Terminology
- _Workspace_: the central dashboard widget that owns pane layout and focus
- _Pane_: a layout slot in the split tree; a container that holds at most one
  widget at a time
- _Widget_: a content unit loaded into a pane; one of `trace`, `turn`,
  `policy`, `log`, `host`
- _Empty Pane_: a pane with no widget loaded; shows a numbered picker so the
  user can load a widget
- _Leaf_: one layout-tree node containing a pane id
- _Split_: one layout-tree node containing exactly two children and an
  orientation
- _Orientation_: `horizontal` or `vertical`
- _Ratio_: the relative size distribution between two sibling nodes
- _Focused Pane_: the pane currently targeted by navigation and pane-level
  actions
- _Maximized Pane_: the single pane temporarily expanded to occupy the workspace

------------------------------------------------------------------------
## Workspace Model
The workspace maintains state roughly equivalent to:

```text
WorkspaceState
- focused_pane_id: str | None
- maximized_pane_id: str | None
- root: LayoutNode | None

LayoutNode
- split: "horizontal" | "vertical" | None
- ratio: int | None
- children: tuple[LayoutNode, LayoutNode] | None
- pane_id: str | None
- widget_id: str | None   # None means the pane is empty
```

Rules:
- a node is either a split node or a leaf node, never both
- split nodes always have exactly two children
- leaf nodes always map to exactly one pane id
- leaf nodes carry `widget_id`, which is `None` when the pane is empty
- ratios apply only to split nodes
- `root` is `None` only when the workspace has never been rendered; in practice,
  at least one empty pane is always present

------------------------------------------------------------------------
## Canonical Widget Set
Widget type ids:
- `trace`
- `turn`
- `policy`
- `log`
- `host`

Rules:
- any of these widget types can be loaded into any pane
- if the same widget type is loaded into two different panes, each instance is
  fully independent: separate scroll position, selection state, modal state, and
  data subscription
- a pane may be empty (no widget loaded); this is a normal, first-class state

------------------------------------------------------------------------
## Empty Pane Behavior
An empty pane shows a widget picker — a numbered list of available widget types
the user can load.

Picker keys correspond to the widget type list and allow loading a widget by
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
When the workspace contains exactly one empty pane and no loaded widgets:
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

### Closing a Widget
When a pane has a widget loaded, `close_widget` (`q`):
1. unloads the widget from the pane
2. the pane transitions to the empty/picker state
3. the pane itself remains in the split tree

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

There is no insertion strategy for named widgets — widgets are not inserted by
the workspace; they are loaded into existing panes by the user via the picker.

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
- leaf node -> pane wrapper container containing the loaded widget or the empty
  picker

Pane wrapper responsibilities:
- apply border and title treatment
- reflect focused/unfocused state
- reflect maximized state if applicable
- host widget body content, or the empty picker when no widget is loaded

The workspace renderer should not depend on implicit CSS grid auto-placement.
Every rendered container relationship should correspond to explicit layout
structure in the split tree.

------------------------------------------------------------------------
## Pane Wrapper Responsibilities
Each leaf should render through a wrapper that provides:
- title/header region
- body region (widget or empty picker)
- optional footer or status region later
- visual focus treatment
- consistent padding and border handling

This prevents each widget from re-implementing the same chrome.

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
- action-to-key binding mapping

The default startup state is one empty pane in welcome mode. Optionally, a
configured startup layout may specify an initial set of widgets auto-loaded into
a configured initial split tree. When no startup layout is configured, no widget
loading happens automatically.

Illustrative shape:

```yaml
dashboard:
  startup:
    # Optional. Omit to start with a single empty welcome pane.
    # When provided, each entry specifies a widget to auto-load and the
    # split relationship that places it.
    layout:
      - widget: trace
      - split: horizontal
        widget: turn
    focused_widget: trace

  layout:
    mode: tiled
    default_split: horizontal
    resize_step: 5
    gap: 1

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
    close_widget: q
    close_pane: q
    quit: Q
```

------------------------------------------------------------------------
## Keybinding Philosophy
The system should support vim-like or tmux-like muscle memory, but no specific
key set is architecturally privileged.

Rules:
- defaults exist in code
- user overrides live in dashboard config
- bindings target actions, not raw widget methods
- widget-local interaction keys and workspace-global management keys must remain
  conceptually distinct

The `q` key is context-sensitive: on a pane with a loaded widget it triggers
`close_widget`; on an empty pane it triggers `close_pane`. The workspace
dispatches to the correct action based on the focused pane's state.

`Q` (shift+q) always quits the application regardless of pane state.

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
  auto-load the specified widgets into their assigned panes
- if no startup layout is configured, start with a single empty pane in welcome
  treatment
- set the initial focused pane

------------------------------------------------------------------------
## Persistence Considerations
The plan does not require persistent layout serialization immediately, but the
model should support it later without redesign.

If persistence is introduced later, it should serialize:
- pane ids and their widget assignments
- focused pane id
- maximized pane id
- split tree structure and ratios

------------------------------------------------------------------------
## Failure and Edge Cases
The window-management system should define behavior for:
- zero loaded widgets (normal; workspace shows one or more empty panes)
- one pane visible (no splits possible to navigate; focus remains)
- maximize when no pane is focused
- close_pane when it is the last pane (keep it empty rather than removing)
- close_widget when the pane is already empty (no-op)
- resize when no applicable split exists
- directional focus with no neighbor in that direction
- configuration that references unknown widget ids or unknown actions

Expected behavior should be explicit and non-surprising:
- invalid config values should fail validation
- impossible actions should no-op safely
- no action should corrupt the split tree

------------------------------------------------------------------------
## Testing Expectations
Window-management tests should cover:
- initial tree construction from a configured startup layout
- startup with no configured layout producing a single empty pane
- split operations in both orientations producing a new empty pane
- close_widget transitioning a loaded pane back to empty picker state
- close_pane collapsing the tree correctly
- close_pane on the last pane keeping one empty pane rather than removing it
- maximize and restore behavior
- focus movement across representative layouts
- ratio adjustment and bounds enforcement
- config validation for widget ids and action names
- rendering correspondence between tree shape and mounted container structure
- empty pane welcome treatment when it is the sole pane
- empty pane plain picker treatment when other panes are present

------------------------------------------------------------------------
## Contributor Notes
- Keep all split topology in `Workspace`, never in pane or widget code.
- Keep layout state model pure Python and independent of Textual widget types.
- Keep rendering as a translation layer from layout state to nested containers.
- Keep keybindings action-based and configuration-driven.
- Do not rely on CSS grid auto-placement as the canonical layout system.
- The pane/widget distinction is load-bearing: a pane is a layout slot, a
  widget is content. Never conflate them in state, naming, or tests.
- The welcome surface is not a special pane type; it is a rendering mode of the
  empty pane when it is the only pane visible.


------------------------------------------------------------------------
_End of Dashboard Window Management Plan_
