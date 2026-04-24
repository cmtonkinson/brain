# dialogue-compact
Force-summarize all recent verbatim turns into the rolling session summary and
advance the dialogue frontier so that subsequent context assembly returns only
focus and summary with zero recent turns.

## Parameters
- `session_id` — ULID of the session to compact.

## Returns
`SessionRecord` — the updated session with new `dialogue_summary`,
`dialogue_summary_token_count`, and `dialogue_start_turn_id`.

## Slash Command
`/compact` (alias: `/compress`) — summarize all recent turns and compress
context.
