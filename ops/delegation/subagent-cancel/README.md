# subagent-cancel

Request cancellation of one queued or running subagent invocation. Cancellation
cascades to all transitive children.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `invocation_id` | `str` | yes | — | The ULID identifier of the invocation to cancel. |
| `reason` | `str` | no | `manual` | Cancel reason code. One of `manual`, `budget_tokens`, `budget_turns`, `budget_wallclock`, `parent_canceled`, `actor_lost`. |

## Returns

Object with `accepted: bool` indicating whether the row was eligible to flip
to `canceling` (false when already in a terminal state).
