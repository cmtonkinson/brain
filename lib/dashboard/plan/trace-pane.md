# Dashboard Trace View Plan
This document defines the intended design for the dashboard trace view.

------------------------------------------------------------------------
## Purpose
The trace view exists to answer two closely related questions:

1. _What happened in the most recent execution trace?_
2. _What are the details of the currently selected envelope or service call
   within that trace?_

The pane is both a navigation surface and an inspection surface for
execution-level structure: envelope DAGs, service calls, timings, and status.

It is the engineer's view of _how_ something executed, not a conversational
view of _what_ was said.

------------------------------------------------------------------------
## Core Principles
### Tree and Detail, Not Positional Assumptions
The trace view is composed of two semantic subviews:
- `tree`
- `detail`

The design must not hard-code these as "top/bottom" or "left/right".

Orientation should be chosen adaptively based on available pane dimensions.

### Most Recent Trace by Default
At any given time, the pane is scoped to one trace.

The default selected trace is the most recent trace.

The trace view is an entity/snapshot view with event-backed history:
- acquisition may continue to update retained trace records and selected trace
  detail
- the viewport may follow the live edge or freeze on a retained trace
- stepping moves by retained trace or snapshot timestamp, not by raw log line

### Selection Drives Detail
The tree is the navigation surface.

As the user changes the selected node in the tree, the detail subview updates to
show information for that selected envelope or call.

### Structured Labels
Tree nodes should use a structured compact label rather than a single opaque
identifier.

Preferred node presentation:
- component
- operation
- status

### Shared Inspection Context Is Optional and Explicit
The trace view may publish to and follow shared inspection context, but it must
remain useful standalone.

Compatible context fields include:
- `turn_id`
- `trace_id`
- `envelope_id`
- `component`
- focal timestamp or time range

------------------------------------------------------------------------
## Subviews
### `tree`
The `tree` subview renders the currently selected trace as a hierarchical
envelope DAG or service-call graph.

It is the primary navigation surface.

### `detail`
The `detail` subview renders the selected node from the tree.

It is the primary inspection surface.

------------------------------------------------------------------------
## Layout Behavior
The pane should support adaptive orientation between the `tree` and `detail`
subviews.

Possible orientations:
- stacked
- side-by-side

Selection of orientation should be heuristic and based on available pane
dimensions.

The design should not assume one orientation is always correct.

Rules:
- use semantic names `tree` and `detail` in code and docs
- leave exact orientation heuristic as a layout concern
- preserve behavior regardless of orientation

------------------------------------------------------------------------
## Trace Scope
The initial trace view should display exactly one trace at a time.

Default trace selection:
- the most recent trace by timestamp

The pane does not yet need to define how the user changes from one trace to
another.
That can be added later.

If shared inspection context provides a compatible `trace_id`, a context-following
trace view should scope to that trace explicitly rather than defaulting to the
most recent trace.

------------------------------------------------------------------------
## Tree Content
The tree should represent the selected trace as a hierarchical execution graph.

Each visible node should represent one normalized envelope or service call.

Each node label should render:
- component
- operation
- status

Preferred compact shape:

```text
> inbound  ingest_signal           OK
  agent        process_instruction     OK
    memory     assemble_context        OK
    op search                  OK
    policy     authorize               OK
    lms        chat_with_tools         OK
    attention  route_notify            OK
```

This structured format is preferred over a single combined string because it is
more scannable.

------------------------------------------------------------------------
## Tree Node Model
Each tree node should normalize to a shape equivalent to:

```text
TraceTreeNode
- node_id: str
- parent_id: str | None
- component: str
- operation: str
- status: str
- started_at: datetime
- elapsed_ms: int | None
- children: list[TraceTreeNode]
- expanded: bool
- is_leaf: bool
```

Rules:
- the tree should preserve parent-child execution relationships derived from
  envelope `parent_id` linkage
- `expanded` applies only to non-leaf nodes
- collapsed nodes hide descendants from visible traversal

------------------------------------------------------------------------
## Selection Rules
The tree always has at most one selected node.

Suggested default selected node:
- the deepest active node if the trace is still in progress
- otherwise the newest node in the most recent trace

As the selected node changes:
- the detail subview updates immediately

------------------------------------------------------------------------
## Detail Content
The detail subview should display compact, execution-relevant information for
the selected node.

Suggested fields:
- `Time`
- `Component`
- `Operation`
- `Status`
- `Principal`
- `Source`
- `Envelope`
- `Parent`
- `Elapsed`
- `Summary`
- `Errors`

Illustrative render:

```text
Selected

Time        14:31:59.021
Component   language_model
Operation   chat_with_tools
Status      OK
Principal   operator
Source      agent
Envelope    E01JQY...
Parent      E01JQX...
Elapsed     2.87s

Summary
Tool-capable chat completion started with 3 candidate ops.

Errors
none
```

The detail panel should not dump raw JSON in the initial design.
For richer structured inspection of a selected node, see the Inspect Modal
section below.

------------------------------------------------------------------------
## Explicit Exclusions
The initial trace view should not attempt to show all of these at once:
- full raw payload JSON
- full timeline as an always-visible third subview
- cross-pane linked context assumptions
- arbitrary trace search and selection UI
- conversational or dialogue-level content

These may be added later, but they should not complicate the initial shape.

------------------------------------------------------------------------
## Tree Navigation
The tree should support keyboard navigation over visible nodes.

Required navigation behaviors:
- move selection to previous visible node
- move selection to next visible node
- expand selected node
- collapse selected node

Suggested key actions:
- `move_up`
- `move_down`
- `expand_node`
- `collapse_node`

Illustrative default bindings:
- `j` / `k` for up/down
- `l` / `h` for expand/collapse
- `+` / `-` for expand/collapse as alternates

Bindings themselves should remain configuration-driven.

------------------------------------------------------------------------
## Expand and Collapse Rules
Expand/collapse actions apply only to non-leaf nodes.

Rules:
- expanding a leaf does nothing
- collapsing a leaf does nothing
- collapsing a selected parent hides all descendants
- if a selected descendant becomes hidden due to collapse, selection should move
  to the collapsed parent
- expanding a node reveals its direct and indirect descendants according to
  current expansion state

------------------------------------------------------------------------
## Visibility and Traversal
The visible tree is the expansion-filtered traversal of the normalized trace
tree.

Navigation operates on visible nodes only.

This means:
- up/down movement skips hidden descendants
- recent/default selection should resolve against visible nodes

------------------------------------------------------------------------
## Context Workflows
Illustrative trace-view workflows:
- a `TurnView` publishes `trace_id`; `TraceView` follows and opens that trace
- selecting a node in `TraceView` publishes `trace_id`, `envelope_id`,
  `component`, and focal timestamp
- a `LogView` in another pane follows that context and filters to correlated
  log events

Rules:
- context following is opt-in
- pinning local trace state detaches the view from future workspace context
  updates
- trace selection must remain explicit and visible

------------------------------------------------------------------------
## Status Rendering
Tree node status should normalize to the same compact state family used
elsewhere in the dashboard where appropriate.

Suggested visible states:
- `OK`
- `NO`
- `??`
- possibly `RUN` or equivalent later for active/in-progress execution if the
  trace model needs it

The initial tree should prioritize clarity over exhaustive state taxonomy.

------------------------------------------------------------------------
## Data Requirements
The trace view needs:
- one normalized most-recent trace tree
- one selected node detail view

This suggests two primary dashboard-facing view models:

```text
TraceTreeView
- trace_id: str
- nodes: list[TraceTreeNode]
- selected_node_id: str | None

TraceDetailView
- node_id: str
- time: datetime
- component: str
- operation: str
- status: str
- principal: str
- source: str
- envelope_id: str
- parent_id: str | None
- elapsed_ms: int | None
- summary: str
- errors: list[str]
```

------------------------------------------------------------------------
## Rendering Rules
### Tree
The tree should:
- align component, operation, and status columns consistently
- visibly indicate selected node
- visibly indicate collapsed vs expanded parents
- keep labels compact

### Detail
The detail should:
- align labels consistently
- wrap long summaries cleanly
- show errors only when present, or render `none`

### Space-Constrained Behavior
When the pane is constrained:
- preserve the tree first
- reduce detail verbosity before sacrificing tree legibility
- retain the selected node summary even if the full detail panel must compact

------------------------------------------------------------------------
## Suggested Render Shape
Illustrative conceptual shape:

```text
Trace

Tree
> inbound  ingest_signal           OK
  agent        process_instruction     OK
    memory     assemble_context        OK
    op search                  OK
    policy     authorize               OK
    lms        chat_with_tools         OK
    attention  route_notify            OK

Detail
Time        14:31:59.021
Component   language_model
Operation   chat_with_tools
Status      OK
Principal   operator
Source      agent
Envelope    E01JQY...
Parent      E01JQX...
Elapsed     2.87s

Summary
Tool-capable chat completion started with 3 candidate ops.
```

------------------------------------------------------------------------
## Inspect Modal
The inspect modal is a transient deep-dive overlay for a selected trace node.

It provides richer, structured inspection when the compact detail subview is
insufficient. The modal is not a persistent view; it is opened on demand and
dismissed when no longer needed.

### Purpose
The inspect modal exists to expose structured execution details for the
currently selected trace node without turning the main trace view into an
unreadable blob.

This is especially valuable for Language nodes such as:
- `chat`
- `chat_with_tools`

and for policy decision and op invocation nodes where the full envelope
payload is relevant.

### Core Principles
#### Secondary Drill-Down, Not Primary Display
The trace view remains the primary navigation and compact inspection surface.

The inspect modal is optional, invoked on demand, and focused on the currently
selected node.

#### Structured, Not Raw
The modal should display structured summaries, not raw JSON dumps.

It should help the engineer understand what was sent, what was returned, and how
large or complex the interaction was.

#### Node-Type Aware
The modal should be aware of the selected node type.

Not every node needs or supports a rich inspect view.

Language nodes are the primary target.

### Invocation
The inspect modal should be opened from the trace view by a dedicated action.

Suggested action:
- `open_inspect_modal`

Suggested default binding:
- `i`

Bindings remain configuration-driven.

Rules:
- if the selected node supports rich inspection, open the modal
- if the selected node does not support rich inspection, no-op safely or show a
  compact unsupported-state message

### Scope
The inspect modal initially targets Language request/response inspection.

Primary supported node types:
- Language `chat`
- Language `chat_with_tools`

Possible future supported node types:
- policy decisions
- op invocations
- tool-call results

### Modal Layout
The inspect modal should be:
- large
- scrollable
- read-only
- structured into sections

Suggested top-level sections:
- `Request`
- `Tools`
- `Tool Results`
- `Response`

The modal should not require the engineer to parse transport-level shapes or raw
wire payloads.

### Request Section
The `Request` section should summarize the selected Language request.

Suggested fields:
- provider
- model
- profile
- estimated input token count
- message count by role
- first `N` lines of system prompt
- first `N` lines of user content

Illustrative render:

```text
Request

Provider        openai
Model           gpt-5.4
Profile         standard
Input Tokens    ~8412
Messages        system=1 user=1 assistant=2 tool=3

System Prompt
1  You are Brain...
2  Respect policy constraints...
3  Use tools only when...

User Content
1  Text Chris back about tomorrow...
2  Mention...
```

### Tools Section
The `Tools` section should summarize the tool definitions made available to the
selected Language call.

Suggested fields:
- tool count
- tool names
- compact schema or argument summary per tool
- estimated token count consumed by tool definitions

Illustrative render:

```text
Tools

Count           3
Tool Tokens     ~1250

- discover_ops
  query: string

- describe_op
  op_id: string

- send-message-draft
  recipient: string
  body: string
```

### Tool Results Section
The `Tool Results` section should summarize tool calls and returned tool output.

Suggested fields:
- tool call count
- invoked tool names
- compact input summary
- compact result summary
- estimated token count consumed by returned tool content

Illustrative render:

```text
Tool Results

Calls           2
Result Tokens   ~980

- discover_ops
  input: query="text Chris back"
  result: 4 op hits

- describe_op
  input: op_id="send-message-draft"
  result: 1 op descriptor
```

### Response Section
The `Response` section should summarize the selected Language response.

Suggested fields:
- finish reason
- estimated output token count
- first `N` lines of assistant response
- tool-call summary when present

Illustrative render:

```text
Response

Finish Reason   stop
Output Tokens   ~611

Assistant Output
1  I can draft that reply for review...
2  Proposed message:
3  "Hey Chris..."
```

### Token Counts
Token counts shown in the inspect modal should be clearly labeled as estimates
unless the system has an exact authoritative count.

Rules:
- prefer exact counts when available
- otherwise render estimated counts with a visible estimate marker such as `~`
- never imply false precision

### Truncation Policy
The inspect modal should never dump unbounded prompt or response content by
default.

Rules:
- show first `N` lines for large textual fields
- make `N` configuration-driven later if useful
- preserve scrollability inside the modal
- allow future expansion to view more, but keep the initial surface compact

### Inspect Data Requirements
The inspect modal requires a normalized inspect model distinct from the compact
trace detail view.

Suggested shape:

```text
TraceInspectView
- node_id: str
- node_type: str
- request_provider: str
- request_model: str
- request_profile: str
- estimated_input_tokens: int | None
- message_role_counts: dict[str, int]
- system_prompt_lines: list[str]
- user_content_lines: list[str]
- tool_summaries: list[ToolSummary]
- estimated_tool_tokens: int | None
- tool_result_summaries: list[ToolResultSummary]
- estimated_tool_result_tokens: int | None
- finish_reason: str
- estimated_output_tokens: int | None
- response_lines: list[str]
```

### Unsupported Nodes
For selected nodes that do not support rich inspection:
- the inspect action should no-op safely, or
- the modal should render a small message such as:

```text
No extended inspection view is available for this node type.
```

Either behavior is acceptable as long as it is predictable.

### Relationship to Trace View
The normal trace view should remain compact.

The inspect modal must not move these richer details into the default trace
detail view.

Responsibilities remain split as:
- `tree` + `detail`: trace navigation and compact inspection
- inspect modal: rich node-specific drill-down

------------------------------------------------------------------------
## Future Expansion
Possible later additions:
- a separate timeline mode or toggle
- explicit trace switching
- filters by component or status
- direct jump to active node
- richer error drill-down
- inspect modal drill-down for policy nodes
- inspect modal drill-down for op invocation payloads
- expandable sections inside the inspect modal
- copy-to-clipboard or export actions from the inspect modal

These are future enhancements, not part of the initial pane definition.

------------------------------------------------------------------------
## Testing Expectations
Trace view tests should cover:
- default selection of the most recent trace
- default node selection behavior
- visible-tree traversal
- expand/collapse behavior
- selection updates to detail view
- structured node-label rendering
- adaptive orientation independence of behavior
- compact fallback under constrained space

Inspect modal tests should cover:
- modal opening only for supported nodes
- structured rendering of request/tools/tool-results/response sections
- truncation of long text fields
- explicit estimated-token rendering
- graceful handling of unsupported node types

------------------------------------------------------------------------
## Contributor Notes
- Use `tree` and `detail`, not positional names, in implementation and docs.
- Keep the tree as the navigation surface.
- Keep the detail view driven entirely by tree selection.
- Prefer structured labels: component, operation, status.
- Support subtree expand/collapse on non-leaf nodes.
- Do not overload the initial pane with a permanent third subview.
- Keep the inspect modal separate from the normal trace detail surface.
- Keep modal renders structured and compact; avoid raw JSON by default.
- Prefer summaries and first-`N`-line previews in the modal.
- Make token counts explicitly approximate when they are not exact.


------------------------------------------------------------------------
_End of Dashboard Trace View Plan_
