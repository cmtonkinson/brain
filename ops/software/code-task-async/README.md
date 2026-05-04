# code-task-async
Dispatch one coding task against a registered Software workspace and
return immediately with a `RUNNING` task row.

------------------------------------------------------------------------
## Inputs
- `workspace_id`: identifier of the registered workspace to operate on.
- `prompt`: natural-language description of the task for the coding executor.
- `executor` (optional): override the workspace's default executor.

------------------------------------------------------------------------
## Behavior
- Creates a fresh git worktree on a new branch under the workspace's
  `branch_prefix`, persists a `Task` row in `RUNNING` with the adapter
  handle stamped on it, and returns immediately.
- A background driver in the Software Service polls the Coding Adapter
  to terminal, runs the workspace's `test_command`, and commits if green.
- Drive completion via `code-task-status` (cheap polling) or
  `code-task-wait` (blocking).
- The worktree is preserved on disk regardless of outcome. **No push,
  no PR.**
- Suitable for long-running tasks (multi-minute coding-agent runs) and
  for `Job Service`-scheduled invocations that should not hold open the
  caller's command.

------------------------------------------------------------------------
## Output
The initial `Task` lineage row in `RUNNING` status.

------------------------------------------------------------------------
## Effect/Approval
This op is classified `(external, never)`. Trust was granted at workspace
registration; the Service rejects calls against unregistered or revoked
workspaces.


------------------------------------------------------------------------
_End of code-task-async_
