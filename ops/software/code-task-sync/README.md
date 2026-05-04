# code-task-sync
Dispatch one coding task against a registered Software workspace and block
until the task reaches a terminal status.

------------------------------------------------------------------------
## Inputs
- `workspace_id`: identifier of the registered workspace to operate on.
- `prompt`: natural-language description of the task for the coding executor.
- `executor` (optional): override the workspace's default executor.
- `max_wait_seconds` (optional): soft deadline for blocking on the task.
  When the deadline elapses before terminal, the op returns the most
  recent non-terminal row with a timed-out failure envelope; the task
  itself continues running and can be observed via `code-task-status`.

------------------------------------------------------------------------
## Behavior
- Sugar over `code-task-async` followed by `code-task-wait` against the
  returned task id. Suitable for short tasks where the operator wants
  type-and-wait UX in one shot.
- Long-running invocations (multi-minute coding-agent runs, Job-Service
  scheduled tasks) should prefer `code-task-async` and either poll
  `code-task-status` or block on `code-task-wait` separately.
- Creates a fresh git worktree on a new branch under the workspace's
  `branch_prefix`. The worktree is preserved on disk for operator
  inspection regardless of outcome. **No push, no PR.**

------------------------------------------------------------------------
## Output
The terminal `Task` lineage row.

------------------------------------------------------------------------
## Effect/Approval
This op is classified `(external, never)`. Trust was granted at workspace
registration; the Service rejects calls against unregistered or revoked
workspaces.


------------------------------------------------------------------------
_End of code-task-sync_
