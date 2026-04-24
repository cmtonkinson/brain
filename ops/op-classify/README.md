# op-classify
Classify one observed dynamic op by setting its effect and/or approval. Targets the rows that the Execution Service writes when it discovers MCP-backed tools but cannot register them as ops until an operator decides how the system should treat them.

------------------------------------------------------------------------
## Behavior
- Accepts an `op_id` and a free-form list of `words`.
- Each word must be a member of either the effect set (`read`, `write`, `execute`, `external`) or the approval set (`always`, `never`).
- Word order does not matter.
- Operator may supply only an effect, only an approval, or both. Partial classifications persist; the op becomes active only once both effect and approval are set.
- Conflicting words from the same set (e.g. two effects) raise an error rather than choosing one.
- Unknown words raise an error rather than silently dropping; this prevents typos persisting incomplete classifications.

------------------------------------------------------------------------
## Slash Command
`/op-classify <op_id> <word1> <word2> ...`

Examples:
- `/op-classify eventkit--list-events read never`
- `/op-classify eventkit--create-event always write`
- `/op-classify eventkit--list-reminders never` — sets approval only.
- `/op-classify eventkit--probe read` — sets effect only.

------------------------------------------------------------------------
## Output
Plain text confirmation describing what was set and what is persisted, plus whether the op is now active or still pending the missing field.

------------------------------------------------------------------------
## Effect/Approval
This op itself is classified `(write, always)` so any approval-gated channel can invoke it after operator approval.


------------------------------------------------------------------------
_End of op-classify_
