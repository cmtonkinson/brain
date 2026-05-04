# code-workspace-revoke
Revoke trust on a registered Software workspace.

------------------------------------------------------------------------
## Inputs
- `workspace_id`: the workspace identifier to revoke.

------------------------------------------------------------------------
## Output
The updated `Workspace` record with `revoked_at` set.

------------------------------------------------------------------------
## Behavior
- Idempotent: revoking an already-revoked workspace returns the existing row unchanged.
- Subsequent task ops (`code-task-async`, `code-task-sync`) against the revoked workspace are rejected by the Service.
- In-flight tasks are **not** cancelled by revocation; use `code-task-cancel` for that.

------------------------------------------------------------------------
## Effect/Approval
This op is classified `(write, always)`. Trust-mutating ops
(`code-workspace-register`, `code-workspace-revoke`) require operator
approval; all other ops in the subsystem carry `approval: never` and
rely on the Service to reject calls against unregistered or revoked
workspaces.

------------------------------------------------------------------------
_End of code-workspace-revoke_
