# Dashboard Footer Plan
This document defines the intended design for the dashboard footer.

------------------------------------------------------------------------
## Purpose
The footer exists to provide a compact, always-visible keybinding reference for
the current dashboard state.

It should answer:
- what global workspace actions are available right now?
- what shared temporal and context actions are available right now?
- what view-specific actions are available for the currently focused pane?

It is not intended to be a full command reference or tutorial surface.

------------------------------------------------------------------------
## Core Principles
### Always Visible
The footer should remain visible at all times as part of the fixed app chrome.

### Global Plus Contextual
The footer should combine:
- global workspace actions
- shared temporal actions
- shared context actions
- context-sensitive actions for the view loaded in the currently focused pane

### Context Only When Relevant
View-specific actions should appear only when they are meaningful in the
current state.

Examples:
- expand/collapse tree bindings appear only when the focused pane contains a
  trace view and the selected node can expand or collapse
- inspect-modal binding appears only when the selected node supports rich
  inspection
- context-follow toggle appears only when the focused view can follow shared
  inspection context

### Width-Aware
The footer should adapt to available width.

When there is enough width:
- show all global actions
- show shared temporal and context actions
- show contextual view actions

When width is constrained:
- preserve the highest-value actions first
- degrade gracefully rather than wrapping into unreadable noise

------------------------------------------------------------------------
## Footer Content Model
The footer should be composed from four conceptual groups:

- `global`
- `temporal`
- `context`
- `contextual`

Suggested internal shape:

```text
FooterState
- global_items: list[FooterItem]
- temporal_items: list[FooterItem]
- context_items: list[FooterItem]
- contextual_items: list[FooterItem]

FooterItem
- key: str
- label: str
- visible: bool
- priority: int
```

Rules:
- `global_items` are derived from workspace state
- `temporal_items` are derived from the focused pane's temporal state and the
  focused view's stepping semantics
- `context_items` are derived from the focused view's relationship to shared
  inspection context
- `contextual_items` are derived from the view loaded in the currently focused
  pane and its local state; if the focused pane is empty, contextual items are
  empty
- the footer renderer is responsible for fitting visible items into available
  width

------------------------------------------------------------------------
## Global Items
Global items should include workspace-level actions that are always or nearly
always relevant.

Suggested global actions:
- focus next / previous
- split horizontal / split vertical
- maximize / restore
- quit

Illustrative full-width global section:

```text
[tab] Focus  [s] Split-H  [v] Split-V  [enter] Max  [Q] Quit
```

There are no numbered pane toggle items. Views are loaded into panes via the
empty-pane view picker, not via global footer keys.

------------------------------------------------------------------------
## Temporal Items
Temporal items are shared action concepts even when views step differently.

Suggested temporal actions:
- freeze
- step backward
- step forward
- jump to live
- follow live

Rules:
- temporal items appear only for views that have retained history
- `freeze` and `follow live` are mutually exclusive in the rendered footer
- stepping actions should disappear or disable when the focused view is in
  live-follow and stepping would be meaningless

Illustrative temporal section:

```text
[f] Freeze  [[] Prev  []] Next  [g] Live
```

------------------------------------------------------------------------
## Context Items
Context items expose the focused view's relationship to shared inspection
context.

Suggested context actions:
- follow context
- pin local state
- publish selection

Rules:
- follow state must be explicit
- if the focused view cannot interpret shared inspection context, omit context
  items entirely
- pinning local state is the action that stops following without clearing the
  view's current scope

------------------------------------------------------------------------
## Contextual Items
Contextual items depend on the view loaded in the focused pane and the current
selection within that view. If the focused pane is empty, no contextual items
are shown.

### Trace View Context
When the focused pane contains a trace view:
- show up/down navigation
- show expand/collapse when the selected node is expandable
- show inspect-modal action when the selected node supports rich inspection

Illustrative contextual items:

```text
[j/k] Move  [h/l] Collapse/Expand  [i] Inspect
```

If the selected node is a leaf:
- omit collapse/expand

If the selected node does not support inspect:
- omit inspect

### Log View Context
When the focused pane contains a log view:
- show filter/search if supported

Illustrative contextual items:

```text
[/] Filter
```

### Policy View Context
The initial policy view may have little or no contextual behavior beyond
selection movement if a recent list becomes selectable.

Until then, it is acceptable for the policy view to contribute no contextual
footer items.

### Turn View Context
The initial turn view may also contribute no contextual footer items beyond
selection movement if and when the recent list becomes interactive.

### Host View Context
The host view likely contributes no contextual footer items initially.

### LLM View Context
When the focused pane contains an `LLMView`:
- show move/select actions for provider/model rows
- show freeze/follow state only through shared temporal items

------------------------------------------------------------------------
## Width-Adaptive Rendering
The footer must degrade by priority, not arbitrarily.

Suggested priority order:
1. quit
2. maximize / restore
3. focus next / previous
4. split actions
5. temporal actions affecting live/frozen state
6. context follow state
7. focused-pane contextual view actions
8. lower-value secondary actions

More specifically:

- very narrow width:
  - show only the most critical global actions
- medium width:
  - show global navigation and a small contextual set
- wide width:
  - show full global actions plus context-sensitive view actions

The footer should not wrap into multiple lines.
It should truncate by dropping lower-priority items.

------------------------------------------------------------------------
## Rendering Style
The footer should render compact action chips in a consistent style.

Suggested shape:

```text
[tab] Focus  [s] Split-H  [v] Split-V  [enter] Max  [Q] Quit
```

Contextual additions follow the same pattern:

```text
[j/k] Move  [h/l] Collapse/Expand  [i] Inspect
```

Rules:
- key first, label second
- concise labels
- no explanatory prose
- consistent spacing between items

------------------------------------------------------------------------
## Dynamic Behavior
The footer should update whenever any of the following changes:
- focused pane changes
- view loaded into or unloaded from the focused pane
- focused pane selection changes
- focused view temporal mode changes
- focused view context-follow state changes
- selected trace node expands or collapses
- inspect eligibility changes
- pane maximize state changes
- terminal width changes

The footer must be a reactive view of app state, not a static string.

------------------------------------------------------------------------
## Data Requirements
The footer should derive its content from:
- workspace state
- focused pane identity and view loaded therein
- focused view-local capability state
- focused view temporal state
- focused view context-follow state
- width constraints

This suggests a footer-specific builder layer rather than hard-coding the footer
string in the view.

Suggested structure:

```text
FooterBuilder
  -> build_global_items(workspace_state)
  -> build_temporal_items(focused_pane_state)
  -> build_context_items(focused_pane_state, inspection_context)
  -> build_contextual_items(focused_pane_state)
  -> fit_items_to_width(items, width)
  -> render_footer(items)
```

------------------------------------------------------------------------
## Examples
### Wide Footer, Trace View Focused
```text
[tab] Focus  [s] Split-H  [v] Split-V  [f] Freeze  [g] Live  [c] Follow Ctx  [j/k] Move  [h/l] Collapse/Expand  [i] Inspect  [Q] Quit
```

### Medium Footer, Log View Focused
```text
[tab] Focus  [enter] Max  [f] Freeze  [g] Live  [c] Pin  [/] Filter  [Q] Quit
```

### Narrow Footer
```text
[tab] Focus  [enter] Max  [Q] Quit
```

### Wide Footer, Empty Pane Focused
```text
[tab] Focus  [s] Split-H  [v] Split-V  [enter] Max  [Q] Quit
```

------------------------------------------------------------------------
## Explicit Exclusions
The initial footer should not attempt to include:
- numbered pane toggle items
- every possible keybinding in the app
- documentation-like sentences
- hidden actions that are not currently available
- multi-line help text

The footer is a tactical prompt, not a manual.

------------------------------------------------------------------------
## Testing Expectations
Footer tests should cover:
- global item rendering independent of focused view type
- contextual action rendering for a focused trace view
- contextual action rendering for a focused log view
- temporal action rendering for live-follow and frozen states
- context action rendering for a followable versus pinned view
- omission of contextual items when the focused pane is empty
- omission of irrelevant contextual actions based on node or selection state
- width-based item dropping by priority
- updates on focus changes, view load/unload, and selection changes

------------------------------------------------------------------------
## Contributor Notes
- Keep the footer compact.
- Keep global and contextual actions distinct.
- Keep temporal and context actions distinct from both global and
  view-specific actions.
- Show contextual actions only when they are currently meaningful.
- Prefer dropping low-priority items over wrapping.
- Derive footer content from state; do not hard-code one static footer string.
- There are no numbered pane toggle items; do not add them.


------------------------------------------------------------------------
_End of Dashboard Footer Plan_
