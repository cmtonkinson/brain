# subagent-sync

Spawn one subagent to accomplish a task and block until it returns a result.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `prompt` | `str` | yes | — | The task instruction the subagent should accomplish. |
| `context_text` | `str \| null` | no | `null` | Optional inline scratch context appended to the subagent system prompt. |
| `context_object_refs` | `list[str]` | no | `[]` | Object Service refs the subagent may resolve for additional context. |
| `personality_id` | `str` | no | `subagent` | Personality template id under `lib/sdk/personalities/`. |
| `tool_allowlist` | `list[str] \| null` | no | `null` | Optional explicit allowlist of op_ids the subagent may invoke. |
| `max_turns` | `int` | no | `8` | Hard ceiling on tool-loop turns. |
| `budget_tokens` | `int \| null` | no | `null` | Hard ceiling on total tokens consumed across all turns. |
| `max_wallclock_seconds` | `int \| null` | no | `null` | Hard ceiling on wallclock seconds from claim to terminal. |
| `parent_invocation_id` | `str \| null` | no | `null` | Optional parent invocation id; cascade-cancel propagates here. |
| `timeout_seconds` | `float \| null` | no | `null` | Maximum seconds to block waiting for terminal state. |

## Returns

Object with the terminal status and final response of the invocation.
