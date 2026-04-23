# Dashboard Turn View Plan
This document defines the intended design for the dashboard turn view.

------------------------------------------------------------------------
## Purpose
The turn view exists to answer two questions quickly:

1. _What did the operator say, and how did the agent respond?_
2. _What model, reasoning level, and token cost were involved?_

The turn view is a dialogue-level observability surface.
It shows _what_ happened from a conversational perspective.
It does not show _how_ it happened from an infrastructure perspective; that is
the trace view's job.

------------------------------------------------------------------------
## Core Principles
### Dialogue, Not Execution
A turn is a dialogue-level unit: the operator said something, the agent
reasoned, the agent responded.

A trace is an execution-level unit: envelopes flowed, services were called,
policies were evaluated.

Turns and traces are related but not one-to-one:
- a turn may correlate to one or more traces
- a trace may serve a non-dialogue trigger

The turn view must not conflate these two perspectives.

### Standalone by Default
The turn view should be useful even when no trace, policy, or log view context
is available.

The pane should derive its own current and recent views from dialogue state
only.

The turn view is a snapshot-oriented view with bounded recent history:
- acquisition continues as MAS records new dialogue turns
- the viewport may follow the latest turn or freeze on retained recent turns
- stepping moves by retained turn or paired exchange, not by sample interval

### Current Plus Recent
The pane should have two layers:
- one detailed current section
- one compact recent history section

### MAS Is the Authority
The Memory Authority Service owns dialogue state: sessions, turns, and focus.

The turn view consumes MAS-originated data.
It does not query the Language Model Service, Capability Engine, or trace
infrastructure directly.

### Shared Inspection Context Is Optional and Explicit
The turn view may publish to and follow shared inspection context, but it must
remain useful standalone.

Compatible context fields include:
- `turn_id`
- `trace_id`
- `provider`
- `model`
- focal timestamp or time range

------------------------------------------------------------------------
## Current Item Selection Rule
The top section of the pane should always show exactly one current item.

Selection rule:
1. if an outbound response has been recorded for the most recent inbound
   message, show the completed turn (inbound plus outbound as a pair)
2. if an inbound message exists without a recorded response, show the pending
   turn (inbound only, awaiting response)

This keeps the pane focused on the most recent dialogue exchange.

------------------------------------------------------------------------
## Current Section Content
The current section should present the selected turn in a compact detail
layout.

### For a Completed Turn
Suggested fields:
- `State`
- `Inbound`
- `Response`
- `Model`
- `Provider`
- `Reasoning`
- `Tokens`
- `Principal`
- `Time`

Illustrative render:

```text
Turn

Current
State       complete
Inbound     Can you draft a reply to Chris about tomorrow?
Response    Sure. I've drafted a reply confirming tomorrow at 10am.
Model       claude-sonnet-4-20250514
Provider    anthropic
Reasoning   standard
Tokens      1842
Principal   operator
Time        14:31:59
```

### For a Pending Turn
Suggested fields:
- `State`
- `Inbound`
- `Principal`
- `Time`
- `Elapsed`

Illustrative render:

```text
Turn

Current
State       pending
Inbound     Can you draft a reply to Chris about tomorrow?
Principal   operator
Time        14:31:59
Elapsed     2.4s
```

------------------------------------------------------------------------
## Explicit Exclusions
The initial pane should not include:
- full prompt text (assembled context, system prompt, reference snippets)
- full response text beyond a compact summary or truncation
- raw envelope or trace metadata
- tool call details
- focus content
- session history beyond the recent list
- cross-pane correlated state assumptions

Reason:
- these details either do not help at a glance or belong in the inspect modal
  defined later in this document

------------------------------------------------------------------------
## Recent Section
Below the current section, the pane should show a compact recent list when
space permits.

Columns:
- time
- direction
- summary

Rules:
- newest first
- show paired turns (inbound then outbound) as distinct rows
- fixed small item count
- truncate long content to fit column width
- omitted entirely when the pane height is too constrained

Illustrative render:

```text
Recent
14:31:59  out  Sure. I've drafted a reply confirming tom...
14:31:57  in   Can you draft a reply to Chris about tomo...
14:28:03  out  Done. The reminder is set for 3pm.
14:28:01  in   Remind me about the standup at 3pm
```

------------------------------------------------------------------------
## Turn States
The pane should normalize turn state into a small controlled set.

Suggested state values:
- `complete`: both inbound and outbound turns exist for the exchange
- `pending`: inbound turn exists, outbound response not yet recorded

The pane should render these exact normalized states rather than raw storage
values.

------------------------------------------------------------------------
## Data Requirements
The pane needs two canonical dashboard-facing inputs:

### Current Turn View
The most recent dialogue exchange, composed of:
- the most recent inbound turn
- the corresponding outbound turn, if it has been recorded

### Recent Turn List
The newest dialogue turns in compact list form.

This suggests a turn-specific view model layer rather than rendering raw
database rows directly.

Suggested shapes:

```text
CurrentTurnView
- state: str
- inbound_content: str
- inbound_time: datetime
- inbound_principal: str
- response_content: str | None
- response_time: datetime | None
- model: str | None
- provider: str | None
- reasoning_level: str | None
- token_count: int | None
- trace_id: str | None
- elapsed_ms: int | None

RecentTurnItemView
- timestamp: datetime
- direction: str
- summary: str
```

------------------------------------------------------------------------
## Data Selection Rules
### Current Turn Query
The pane should select the most recent inbound turn from the active session.

If that inbound turn has a corresponding outbound response recorded after it
in the same session, pair them into a completed turn.

If no outbound response follows, treat the turn as pending.

If shared inspection context provides a compatible `turn_id`, a
context-following turn view should scope to that specific turn rather than the
most recent one.

### Recent List Query
The recent list should include recent turns in descending time order.

Each row normalizes to:
- time
- direction
- summary (truncated content)

------------------------------------------------------------------------
## Rendering Rules
### Current Section
The current section should:
- prioritize legibility over density
- align labels consistently
- keep field order stable
- truncate long inbound and response content with ellipsis
- wrap summaries cleanly when space permits

### Recent Section
The recent section should:
- remain compact
- align columns consistently
- truncate content summaries to fit pane width
- distinguish inbound and outbound rows visually

### Space-Constrained Behavior
When the pane is short:
- preserve the current section
- drop the recent section first

When the pane is narrow:
- keep labels short
- truncate content aggressively
- preserve state, direction, and time visibility over secondary fields

------------------------------------------------------------------------
## Context Workflows
Illustrative turn-view workflows:
- selecting a turn publishes `turn_id`, `trace_id` when known, `provider`,
  `model`, and focal timestamp
- an `LLMView` follows that context and scopes model-usage rates to the same
  provider/model and time region
- a `TraceView` follows the correlated `trace_id` when present

Rules:
- context following is opt-in
- pinning local turn state detaches the view from future workspace context
  updates
- the view must make follow-versus-pinned state visible

------------------------------------------------------------------------
## Suggested Render Shape
Illustrative completed turn:

```text
Turn

Current
State       complete
Inbound     Can you draft a reply to Chris about tomorrow?
Response    Sure. I've drafted a reply confirming tomorrow at 10am.
Model       claude-sonnet-4-20250514
Provider    anthropic
Reasoning   standard
Tokens      1842
Principal   operator
Time        14:31:59

Recent
14:31:59  out  Sure. I've drafted a reply confirming tom...
14:31:57  in   Can you draft a reply to Chris about tomo...
14:28:03  out  Done. The reminder is set for 3pm.
14:28:01  in   Remind me about the standup at 3pm
```

Illustrative pending turn:

```text
Turn

Current
State       pending
Inbound     Can you draft a reply to Chris about tomorrow?
Principal   operator
Time        14:31:59
Elapsed     2.4s

Recent
14:28:03  out  Done. The reminder is set for 3pm.
14:28:01  in   Remind me about the standup at 3pm
14:25:44  out  Here are your open commitments for today...
14:25:41  in   What's on my plate today?
```

------------------------------------------------------------------------
## Inspect Modal
### Purpose
The inspect modal provides a deep-dive view for one selected turn.

It is a transient overlay, not a persistent subview.
It appears on explicit user action and dismisses back to the turn view.

### Activation
The inspect modal should be activated by an explicit action on the currently
selected turn.

Suggested action name:
- `inspect_turn`

### Content
The inspect modal should show the full untruncated detail for the selected
turn.

Suggested fields:
- `Turn ID`
- `Session ID`
- `Trace ID`
- `State`
- `Direction` (for each leg)
- `Time` (for each leg)
- `Principal`
- `Full Inbound` (complete operator message, untruncated)
- `Full Response` (complete agent response, untruncated)
- `Model`
- `Provider`
- `Reasoning Level`
- `Token Count`
- `Elapsed`

Illustrative render:

```text
Turn Inspect

Turn ID     01JQY8...
Session ID  01JQY7...
Trace ID    01JQY8...
State       complete

Inbound
Time        14:31:57
Principal   operator
Content
Can you draft a reply to Chris about tomorrow? I want to confirm
the 10am meeting and mention I'll bring the project notes.

Response
Time        14:31:59
Model       claude-sonnet-4-20250514
Provider    anthropic
Reasoning   standard
Tokens      1842
Content
Sure. I've drafted a reply confirming tomorrow at 10am and
mentioning that you'll bring the project notes. The draft is
ready for your review before sending.
```

### Scrolling
The inspect modal should support vertical scrolling for long content.

Full prompt and response text may be arbitrarily long.
The modal must handle this without truncation.

### Dismissal
The inspect modal should dismiss on:
- an explicit close action
- pressing escape

Dismissal returns focus to the turn view in its prior state.

### Explicit Exclusions for Inspect
The inspect modal should not include in its initial design:
- raw assembled context (system prompt, focus, reference snippets)
- tool call request and response payloads
- raw envelope JSON
- trace tree navigation

These may be added later as the inspect surface matures.

------------------------------------------------------------------------
## Future Expansion
Possible later additions:
- tool call detail within the inspect modal
- assembled context view (full prompt with system, focus, and reference)
- correlation to specific trace ids when the dashboard grows cross-pane context
- session switching or session list
- turn search and filtering
- token cost aggregation across a session
- streaming response progress for pending turns

These should remain out of the initial compact pane design.

------------------------------------------------------------------------
## Testing Expectations
Turn view tests should cover:
- selection of most recent inbound turn as current item
- pairing of inbound with corresponding outbound for completed turns
- pending state when no outbound response exists
- recent-list ordering by descending time
- omission of recent list when space is constrained
- compact rendering of both completed and pending shapes
- truncation of long content in current and recent sections
- inspect modal activation and dismissal
- inspect modal scrolling for long content
- exclusion of prompt, tool call, and trace sections from initial pane

------------------------------------------------------------------------
## Contributor Notes
- Keep the pane standalone.
- Keep the pane centered on dialogue turns, not execution traces.
- Keep the current section primary and recent list secondary.
- Keep the inspect modal as a transient overlay, not a persistent subview.
- Do not conflate turns with traces.
- Do not assume cross-pane linkage unless explicitly designed later.
- Use MAS as the sole data authority for turn content and metadata.


------------------------------------------------------------------------
_End of Dashboard Turn View Plan_
