# subagent-status

Read the current status projection for one subagent invocation.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `invocation_id` | `str` | yes | — | The ULID identifier of the invocation. |

## Returns

Object with status, cancel reason (if any), counters, and timestamps.
