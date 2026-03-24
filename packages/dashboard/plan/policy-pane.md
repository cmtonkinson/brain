# Dashboard Policy Pane Plan
This document defines the intended design for the dashboard policy pane.

------------------------------------------------------------------------
## Purpose
The policy pane exists to answer two questions quickly:

1. _Is anything currently awaiting approval?_
2. _What was the most recent policy decision?_

It is a standalone observability pane.
It does not assume cross-pane context or selection linkage.

------------------------------------------------------------------------
## Core Principles
### Standalone by Default
The policy pane should be useful even when no trace, turn, or log pane context
is available.

The pane should derive its own current and recent views from policy-related
state only.

### Current Plus Recent
The pane should have two layers:
- one detailed current section
- one compact recent history section

### Approval First
If there is an open approval, that approval is the current item.

If there are no open approvals, the most recent policy decision becomes the
current item.

------------------------------------------------------------------------
## Current Item Selection Rule
The top section of the pane should always show exactly one current item.

Selection rule:
1. if one or more approvals are currently pending, show the newest pending
   approval
2. otherwise show the most recent policy decision

This keeps the pane focused on the most actionable or most relevant policy
state.

------------------------------------------------------------------------
## Current Section Content
The current section should present the selected item in a compact detail layout.

### For an Open Approval
Suggested fields:
- `State`
- `Capability`
- `Actor`
- `Channel`
- `Summary`
- `Requested`
- `Expires`

Illustrative render:

```text
Policy

Current
State       pending
Capability  send-message-draft
Actor       operator
Channel     signal
Summary     Draft and send a reply to Chris about tomorrow
Requested   14:31:59
Expires     14:36:59
```

### For a Recent Decision
Suggested fields:
- `State`
- `Capability`
- `Actor`
- `Channel`
- `Summary`
- `Decided`

Illustrative render:

```text
Policy

Current
State       allowed
Capability  send-message-draft
Actor       operator
Channel     signal
Summary     Draft a reply for operator review
Decided     14:31:59
```

------------------------------------------------------------------------
## Explicit Exclusions
The initial pane should not include:
- reason codes
- raw policy JSON
- policy regime metadata
- verbose envelope dumps
- cross-pane correlated state assumptions

Reason:
- these details either do not help at a glance or belong in a deeper drill-down
  view later

------------------------------------------------------------------------
## Recent Section
Below the current section, the pane should show a compact recent list when
space permits.

Columns:
- time
- state
- capability

Rules:
- newest first
- fixed small item count
- omitted entirely when the pane height is too constrained

Illustrative render:

```text
Recent
14:31:58  allowed  capability.search
14:31:59  pending  send-message-draft
14:32:03  allowed  attention.route_notify
```

------------------------------------------------------------------------
## Canonical Policy States
The pane should normalize states into a small controlled set.

Suggested state values:
- `allowed`
- `denied`
- `pending`
- `expired`
- `approved`
- `rejected`

The pane should render these exact normalized states rather than raw storage
values whenever possible.

------------------------------------------------------------------------
## Data Requirements
The pane needs two canonical dashboard-facing inputs:

### Current Approval View
The newest currently pending approval, if one exists.

### Recent Decision Views
The newest policy decisions and approvals in compact list form.

This suggests a policy-specific view model layer rather than rendering raw
database rows directly.

Suggested shapes:

```text
CurrentApprovalView
- state: str
- capability_id: str
- actor: str
- channel: str
- summary: str
- requested_at: datetime
- expires_at: datetime

CurrentDecisionView
- state: str
- capability_id: str
- actor: str
- channel: str
- summary: str
- decided_at: datetime

RecentPolicyItemView
- timestamp: datetime
- state: str
- capability_id: str
```

------------------------------------------------------------------------
## Data Selection Rules
### Open Approval Query
The pane should select the newest approval whose status is currently pending.

If multiple approvals are pending:
- prefer the newest by creation time

### Recent List Query
The recent list should include recent policy-relevant items in descending time
order.

It may contain:
- approvals
- decisions

As long as each row can normalize to:
- time
- state
- capability

------------------------------------------------------------------------
## Rendering Rules
### Current Section
The current section should:
- prioritize legibility over density
- align labels consistently
- keep field order stable
- wrap long summaries cleanly

### Recent Section
The recent section should:
- remain compact
- align columns consistently
- truncate capability ids if required by narrow width

### Space-Constrained Behavior
When the pane is short:
- preserve the current section
- drop the recent section first

When the pane is narrow:
- keep labels short
- wrap summary text
- preserve state/capability visibility over secondary fields if needed

------------------------------------------------------------------------
## Suggested Render Shape
Illustrative full pane:

```text
Policy

Current
State       pending
Capability  send-message-draft
Actor       operator
Channel     signal
Summary     Draft and send a reply to Chris about tomorrow
Requested   14:31:59
Expires     14:36:59

Recent
14:31:58  allowed  capability.search
14:31:59  pending  send-message-draft
14:32:03  allowed  attention.route_notify
```

Illustrative no-approval case:

```text
Policy

Current
State       allowed
Capability  send-message-draft
Actor       operator
Channel     signal
Summary     Draft a reply for operator review
Decided     14:31:59

Recent
14:31:58  allowed  capability.search
14:31:59  allowed  send-message-draft
14:32:03  allowed  attention.route_notify
```

------------------------------------------------------------------------
## Future Expansion
Possible later additions:
- a deeper drill-down for one selected approval or decision
- obligations, if they prove consistently useful
- correlation to trace or envelope ids when the dashboard grows cross-pane
  context

These should remain out of the initial compact pane design.

------------------------------------------------------------------------
## Testing Expectations
Policy pane tests should cover:
- selection of newest pending approval as current item
- fallback to most recent decision when no approval is pending
- recent-list ordering by descending time
- omission of recent list when space is constrained
- compact rendering of both approval and decision shapes
- exclusion of reason-code and raw-policy sections

------------------------------------------------------------------------
## Contributor Notes
- Keep the pane standalone.
- Keep the pane centered on open approvals and recent decisions.
- Keep the current section primary and recent list secondary.
- Do not add reason codes to the initial pane.
- Do not assume cross-pane linkage unless explicitly designed later.


------------------------------------------------------------------------
_End of Dashboard Policy Pane Plan_
