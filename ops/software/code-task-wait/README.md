# code-task-wait
Block until one Software task reaches a terminal status.

------------------------------------------------------------------------
## Inputs
- `task_id`: the task identifier to wait on.
- `max_wait_seconds` (optional): soft deadline for blocking. When the
  deadline elapses before terminal, returns the most recent non-terminal
  row with a timed-out failure envelope. The task itself continues
  running and can be re-waited on or observed via `code-task-status`.

------------------------------------------------------------------------
## Behavior
- Idempotent on already-terminal tasks: returns the row immediately.
- Used by Job-Service-scheduled flows that submit via `code-task-async`
  and want to surface results when they arrive.
- Cheap to call repeatedly; safe for use as a polling-with-backoff
  primitive from operator UX.

------------------------------------------------------------------------
## Output
The terminal `Task` lineage row, or the most recent non-terminal row if
the wait timed out.

------------------------------------------------------------------------
## Effect/Approval
This op is classified `(read, never)`.


------------------------------------------------------------------------
_End of code-task-wait_
