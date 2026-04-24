# subagent-wait

Block until a previously queued subagent invocation reaches terminal state.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `invocation_id` | `str` | yes | — | The ULID identifier of the invocation to wait on. |
| `timeout_seconds` | `float \| null` | no | `null` | Maximum seconds to block. Returns the latest snapshot at timeout. |

## Returns

Object with the terminal status and final response of the invocation.
