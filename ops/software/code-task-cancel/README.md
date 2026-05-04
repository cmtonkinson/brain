# code-task-cancel
Request cancellation of one in-flight Software task.

------------------------------------------------------------------------
## Inputs
- `task_id`: the task identifier to cancel.

------------------------------------------------------------------------
## Behavior
- Idempotent: cancelling a terminal task returns the existing row unchanged.
- The associated container is stopped via the Coding Adapter.
- The worktree is preserved on disk for operator inspection.

------------------------------------------------------------------------
## Output
The updated `Task` lineage row.

------------------------------------------------------------------------
## Effect/Approval
This op is classified `(execute, never)`.

------------------------------------------------------------------------
_End of code-task-cancel_
