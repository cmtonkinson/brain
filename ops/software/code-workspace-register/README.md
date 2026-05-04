# code-workspace-register
Register one repository as an allowlisted Software workspace; the binary trust gate.

------------------------------------------------------------------------
## Inputs
- `path`: absolute path on the Brain Core host to the git repository root.
- `default_executor`: default coding executor for tasks against this workspace.
- `test_command`: shell command run by the Service after each task to gate the commit step.
- `max_wallclock_seconds`: hard wallclock budget per task against this workspace.
- `branch_prefix`: branch prefix under which task branches are created.

------------------------------------------------------------------------
## Output
The persisted `Workspace` record.

------------------------------------------------------------------------
## Effect/Approval
This op is classified `(write, always)`. Trust-mutating ops
(`code-workspace-register`, `code-workspace-revoke`) require operator
approval; all other ops in the subsystem carry `approval: never` and
rely on the Service to reject calls against unregistered or revoked
workspaces.

------------------------------------------------------------------------
_End of code-workspace-register_
