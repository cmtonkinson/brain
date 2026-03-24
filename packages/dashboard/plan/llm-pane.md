# Dashboard LLM View Plan
This document defines the intended design for the dashboard `LLMView`.

------------------------------------------------------------------------
## Purpose
`LLMView` exists to answer two questions quickly:

1. _Which provider/model pairs are currently under token or rate pressure?_
2. _Is current recent activity likely to breach configured limits even if it is
   not over them yet?_

It is a resource-pressure observability view.
It emphasizes rate over cumulative totals.

------------------------------------------------------------------------
## Core Principles
### Provider/Model Is the Primary Key
`LLMView` groups activity by:
- provider
- model

Every row or detail scope in the view is keyed by that pair.

### Rate Over Totals
The view prioritizes:
- request rate
- token rate
- allowance
- headroom

Cumulative totals may appear as supporting context, but they are not the primary
signal.

### Derived Metrics Live Below the View
`LLMView` renders derived, presentation-ready usage data.

It must not compute:
- rolling windows
- projected breach states
- allowance math

Those belong in the normalized and derived layers defined by the data-access
plan.

### Standalone by Default, Correlatable by Choice
`LLMView` must be useful on its own, but it may also follow shared inspection
context when the operator wants correlation by:
- provider
- model
- focal timestamp
- time range

------------------------------------------------------------------------
## Temporal Model
`LLMView` is a sampled or bucketed-rate view.

It participates in the shared dashboard temporal model:
- acquisition continues into bounded retained rate buckets
- the viewport may follow the live edge or freeze on retained history
- stepping moves by retained bucket or sample interval
- `freeze` never stops ingestion

`recent` for `LLMView` means configured retained windows such as:
- 5 seconds
- 60 seconds
- 10 minutes

These windows are derived windows, not ad hoc render calculations.

------------------------------------------------------------------------
## Core Model
Suggested canonical row shape:

```text
LLMUsageRowView
- provider: str
- model: str
- request_count: int
- token_count: int
- request_rate_5s: float | None
- request_rate_60s: float | None
- request_rate_10m: float | None
- token_rate_5s: float | None
- token_rate_60s: float | None
- token_rate_10m: float | None
- allowance_requests_per_minute: float | None
- allowance_tokens_per_minute: float | None
- headroom_requests_per_minute: float | None
- headroom_tokens_per_minute: float | None
- pressure_state: "safe" | "projected_breach" | "over_limit" | "unknown"
- sampled_at: datetime
- provenance: list[ProvenanceRecord]
```

Rules:
- allowance fields are optional; some providers or models may have no configured
  budget
- headroom fields are derivable only when allowance is known
- `unknown` is valid when the dashboard cannot determine allowance or rate
  confidently

------------------------------------------------------------------------
## Pressure Semantics
`LLMView` must distinguish exactly these states:

- `over_limit`: current observed rate is above a configured or inferred limit
- `projected_breach`: current rate is below the limit now, but sustained recent
  rate indicates likely breach
- `safe`: currently under limit with adequate headroom
- `unknown`: no trustworthy allowance or current rate signal is available

Rules:
- do not collapse `unknown` into `safe`
- do not collapse a zero current rate into missing data
- projected breach is about recent rate pressure, not about cumulative monthly
  spend

------------------------------------------------------------------------
## Suggested Render Shape
The initial `LLMView` should use a compact table-like summary with one row per
provider/model pair.

Suggested columns:
- provider
- model
- req/s (short window)
- tok/s (short window)
- req/m (medium window)
- tok/m (medium window)
- headroom
- state

Illustrative render:

```text
LLM

Provider   Model                  Req/s  Tok/s  Req/m  Tok/m  Headroom   State
openai     gpt-5.4                0.8    920    46     55200  tok 18%    projected_breach
anthropic  claude-sonnet-4-20250514
                                 0.2    140    11     8400   tok 71%    safe
ollama     qwen3:14b              0.0    0      0      0      n/a        unknown
```

The view may add a compact detail region later, but the primary initial shape is
the summary table.

------------------------------------------------------------------------
## Data Requirements
`LLMView` needs:

### Normalized Usage Records
Each usage record should preserve:
- provider
- model
- request timestamp
- token count
- request identity where available
- trace or turn correlation when available
- provenance

### Derived Windows
The data source or derived layer should produce bounded recent windows for:
- request counts
- token counts
- request rates
- token rates
- allowance and headroom
- projected pressure state

------------------------------------------------------------------------
## Context Integration
`LLMView` may follow shared inspection context when the context includes:
- `provider`
- `model`
- focal timestamp
- time range

Expected workflows:
- selecting a turn publishes its provider/model and focal time; `LLMView`
  scopes to that usage region
- selecting a provider/model row in `LLMView` publishes provider/model and time
  range so logs or traces can investigate contributing activity

Rules:
- context following is opt-in
- pinning local state detaches the view from future workspace context updates
- panes remain independent; `LLMView` does not force any other pane to move

------------------------------------------------------------------------
## Explicit Exclusions
The initial `LLMView` should not attempt to include:
- billing dashboards
- provider account management
- quota mutation
- arbitrary historical analytics beyond retained recent windows
- per-request raw prompt inspection

------------------------------------------------------------------------
## Failure and Trust Semantics
`LLMView` must preserve operator trust.

Rules:
- unavailable allowance data renders as unknown, not infinite headroom
- missing activity data renders as unknown until the source has established a
  trustworthy zero-activity window
- stale derived rates remain visible as stale, not silently current
- provenance should make clear whether activity came from logs, database state,
  or another read-only source

------------------------------------------------------------------------
## Testing Expectations
`LLMView` tests should cover:
- grouping by provider/model
- correct rendering of safe, projected-breach, over-limit, and unknown states
- derivation of headroom only when allowance exists
- explicit distinction between zero activity and unavailable activity
- temporal freeze/follow behavior over retained rate buckets
- optional inspection-context follow by provider/model and time window

------------------------------------------------------------------------
## Contributor Notes
- Keep `LLMView` focused on rate pressure, not cumulative accounting.
- Keep allowance and headroom derivation outside the view.
- Keep provider/model correlation explicit and provenance-preserving.
- Keep temporal behavior consistent with the shared dashboard model.


------------------------------------------------------------------------
_End of Dashboard LLM View Plan_
