# Dashboard Footer Plan
This document defines the intended design for the dashboard footer.

------------------------------------------------------------------------
## Purpose
The footer exists to provide a compact, always-visible keybinding reference for
the current dashboard state.

It should answer:
- what global workspace actions are available right now?
- what widget-specific actions are available for the currently focused pane?

It is not intended to be a full command reference or tutorial surface.

------------------------------------------------------------------------
## Core Principles
### Always Visible
The footer should remain visible at all times as part of the fixed app chrome.

### Global Plus Contextual
The footer should combine:
- global workspace actions
- context-sensitive actions for the widget loaded in the currently focused pane

### Context Only When Relevant
Widget-specific actions should appear only when they are meaningful in the
current state.

Examples:
- expand/collapse tree bindings appear only when the focused pane contains a
  trace widget and the selected node can expand or collapse
- inspect-modal binding appears only when the selected node supports rich
  inspection
- follow-mode toggle appears only for widgets that support follow behavior

### Width-Aware
The footer should adapt to available width.

When there is enough width:
- show all global actions
- show contextual widget actions

When width is constrained:
- preserve the highest-value actions first
- degrade gracefully rather than wrapping into unreadable noise

------------------------------------------------------------------------
## Footer Content Model
The footer should be composed from two conceptual groups:

- `global`
- `contextual`

Suggested internal shape:

```text
FooterState
- global_items: list[FooterItem]
- contextual_items: list[FooterItem]

FooterItem
- key: str
- label: str
- visible: bool
- priority: int
```

Rules:
- `global_items` are derived from workspace state
- `contextual_items` are derived from the widget loaded in the currently focused
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

There are no numbered pane toggle items. Widgets are loaded by interacting with
the empty pane picker, not via global footer keys.

------------------------------------------------------------------------
## Contextual Items
Contextual items depend on the widget loaded in the focused pane and the current
selection within that widget. If the focused pane is empty, no contextual items
are shown.

### Trace Widget Context
When the focused pane contains a trace widget:
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

### Log Widget Context
When the focused pane contains a log widget:
- show follow toggle
- show filter/search if supported

Illustrative contextual items:

```text
[f] Follow  [/] Filter
```

### Policy Widget Context
The initial policy widget may have little or no contextual behavior beyond
selection movement if a recent list becomes selectable.

Until then, it is acceptable for the policy widget to contribute no contextual
footer items.

### Turn Widget Context
The initial turn widget may also contribute no contextual footer items beyond
selection movement if and when the recent list becomes interactive.

### Host Widget Context
The host widget likely contributes no contextual footer items initially.

------------------------------------------------------------------------
## Width-Adaptive Rendering
The footer must degrade by priority, not arbitrarily.

Suggested priority order:
1. quit
2. maximize / restore
3. focus next / previous
4. split actions
5. focused-pane contextual widget actions
6. lower-value secondary actions

More specifically:

- very narrow width:
  - show only the most critical global actions
- medium width:
  - show global navigation and a small contextual set
- wide width:
  - show full global actions plus context-sensitive widget actions

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
- widget loaded into or unloaded from the focused pane
- focused pane selection changes
- selected trace node expands or collapses
- inspect eligibility changes
- pane maximize state changes
- terminal width changes

The footer must be a reactive view of app state, not a static string.

------------------------------------------------------------------------
## Data Requirements
The footer should derive its content from:
- workspace state
- focused pane identity and widget loaded therein
- focused widget-local capability state
- width constraints

This suggests a footer-specific builder layer rather than hard-coding the footer
string in the widget.

Suggested structure:

```text
FooterBuilder
  -> build_global_items(workspace_state)
  -> build_contextual_items(focused_pane_state)
  -> fit_items_to_width(items, width)
  -> render_footer(items)
```

------------------------------------------------------------------------
## Examples
### Wide Footer, Trace Widget Focused
```text
[tab] Focus  [s] Split-H  [v] Split-V  [enter] Max  [j/k] Move  [h/l] Collapse/Expand  [i] Inspect  [Q] Quit
```

### Medium Footer, Log Widget Focused
```text
[tab] Focus  [s] Split-H  [v] Split-V  [enter] Max  [f] Follow  [/] Filter  [Q] Quit
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
- global item rendering independent of focused widget type
- contextual action rendering for a focused trace widget
- contextual action rendering for a focused log widget
- omission of contextual items when the focused pane is empty
- omission of irrelevant contextual actions based on node or selection state
- width-based item dropping by priority
- updates on focus changes, widget load/unload, and selection changes

------------------------------------------------------------------------
## Contributor Notes
- Keep the footer compact.
- Keep global and contextual actions distinct.
- Show contextual actions only when they are currently meaningful.
- Prefer dropping low-priority items over wrapping.
- Derive footer content from state; do not hard-code one static footer string.
- There are no numbered pane toggle items; do not add them.


------------------------------------------------------------------------
_End of Dashboard Footer Plan_
