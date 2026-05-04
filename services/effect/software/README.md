# Software Service
Action *Service* that runs coding tasks against operator-allowlisted
repositories, orchestrating ephemeral containers via the Coding Adapter.

------------------------------------------------------------------------
## What This Component Is
`services/effect/software/` is the Tier 2 *Service* for software work.
It owns the operator-allowlisted workspace catalog and the lifecycle of
coding tasks dispatched to the Coding Adapter.

Core module roles:
* `component.py`: `ServiceManifest` registration (`service_software`)
* `service.py`: authoritative in-process public API contract
* `implementation.py`: concrete service behavior; also houses the
  workspace path-resolution helpers (`_resolve_workspace_container_path`,
  `_workspace_relative_path`) and the procfs-based mountinfo reader
  used to translate container-side paths to host-side equivalents
* `domain.py`: Pydantic payload contracts (`Workspace`, `Task`, `TaskStatus`)
* `config.py`: service-local settings (workspace root, staging root,
  defaults, commit identity)
* `data/schema.py`: `service_software.workspaces` + `service_software.tasks`
* `data/repository.py`: `Workspace` / `Task` row codecs and SQL repos
* `data/runtime.py`: schema-scoped Postgres wiring
* `migrations/`: Alembic environment for the `service_software` schema

------------------------------------------------------------------------
## Boundary and Ownership
Software Service is an Action-System *Service* (`tier=2`, `plane="effect"`).
It declares ownership of the Coding Adapter resource (`adapter_coding`) in
`services/effect/software/component.py`.

A coding capability touches three distinct concerns: **container execution**
(launching the right image with the right credentials for one of several
coding-agent CLIs), **workspace orchestration** (registering operator-trusted
repos, creating worktrees, running tests, committing), and **Brain
integration** (ops, policy gates, audit lineage, scheduled work via Job,
delegation via Subagent). The first concern lives in the Coding Adapter
(`adapter_coding`); the latter two in this Service. Nothing else depends on
the Adapter directly.

Boundary rules:
* Software owns workspace allowlist management, worktree lifecycle, the
  test-and-commit step, and lineage persistence.
* Software does not interpret prompts, edit code, or shell out to coding
  CLIs directly — that is delegated to the Coding Adapter.
* External container-runtime concerns (Docker daemon, image management,
  network policy enforcement) are delegated to the Adapter and the
  `ContainerRuntime` / `ImageBuilder` Protocols beneath it.

Brain Core is assumed single-instance: there is no row-level lease at
dispatch time, so running two `DefaultSoftwareService` instances against
the same Postgres schema is unsupported and would race.

------------------------------------------------------------------------
## Workspace Path Model
Workspaces are registered with paths relative to `software.workspace_root`
(default `/mount/software`), an in-container virtual root under which the
operator's repository trees are bind-mounted via
`docker-compose.override.yaml`. The operator types
`/workspace-register --path repo/brain`, the Service:

1. Resolves the relative path against `workspace_root` →
   `/mount/software/repo/brain`. Rejects paths that escape the root
   or are absolute outside it.
2. Validates that path exists inside brain-core's filesystem and is the
   root of a git working tree.
3. Asks the Coding Adapter to confirm the path is covered by a bind
   mount in brain-core's container (via `resolve_workspace_host_path`,
   which walks brain-core's own Docker mount table). Registration fails
   fast if no bind covers the path — the host Docker daemon would have
   nothing to mount into a task container.
4. Persists the in-container path on the `workspaces` row.

The Coding Adapter resolves the host bind-source again at task-spawn
time (Docker is the source of truth for the live mount table; brain-core
does not cache it on the workspace row). The bind-mount target stays the
registered virtual `path` — so brain-core and task containers see
workspaces at identical absolute paths and host-vs-container path
translation never leaks into op handlers, executor code, or the
worktree's `.git` link.

If the registered path isn't covered by any mount under
`workspace_root` at registration time, the op fails with a message
pointing the operator at `docker-compose.override.yaml`. See
`docs/install.md` for the operator-side walkthrough.

------------------------------------------------------------------------
## Trust Model
Trust is **binary at workspace registration**:
* Trust-mutating ops (`code-workspace-register`, `code-workspace-revoke`)
  require operator approval (`approval: always`); they are the only gates
  in the subsystem.
* All other ops carry `approval: never` and rely on the Service to reject
  calls against unregistered or revoked workspaces.
* Revoked workspaces are kept on disk (with `revoked_at` set) for audit
  history.

There is no per-task approval and no trust TTL. This intentionally
collapses an earlier "trust TTL with first-use approval" design down to
a binary, simpler-to-reason-about gate.

Operator-typed slash commands satisfy the `approval: always` gate
automatically via the slash-authenticity HMAC mechanism (see
`services/reason/policy/`); LLM-driven `invoke_op` calls remain on the
proposal/approval flow.

------------------------------------------------------------------------
## Task Lifecycle
For each `code-task-async` or `code-task-sync`:
1. Resolve the workspace from the allowlist; reject if unregistered or
   revoked.
2. Create a fresh git worktree on a new branch under the workspace's
   `branch_prefix`, persist a `Task` row in `PENDING`. Worktrees live
   under `software.staging_root` (default
   `~/.local/state/brain/software-tasks`), bind-mounted symmetrically
   host↔container so the host Docker daemon resolves the same path
   the worktree was created at.
3. Hand a `CodingTaskSpec` (carrying `workspace_path` and
   `workspace_relative_path`) to the Coding Adapter; the Adapter
   resolves the host bind-source at spawn time. Persist the returned
   handle on the row and transition to `RUNNING`.
4. Poll the Adapter; on terminal phase, capture stdout/stderr to the
   Object Store.
5. Run the workspace's `test_command` against the worktree; transition
   through `TESTING`.
6. If the test command passed and there are changes, `git add -A &&
   git commit` as the configured Brain bot author; transition through
   `COMMITTING`.
7. Persist final task row; the worktree is **left intact** on disk for
   operator inspection. **No push, no PR.**

For `code-task-async`, steps 3–7 run in a background driver thread; the
op returns after step 2 with the `RUNNING` row. For `code-task-sync`,
all steps run inline before returning the terminal row.

Cancellation (`code-task-cancel`) writes a cancel intent and signals the
Coding Adapter to stop the underlying container; the worktree is preserved.

### Reattach on Restart
On construction, the Service queries for tasks in non-terminal status
and spawns a driver for each so async-launched tasks left in flight by
a previous Brain Core process are picked up by the new one. The driver
consults the persisted `status` and resumes at the appropriate phase
rather than restarting from the top — a row crashed mid-`COMMITTING`
detects an existing commit on disk and finalizes without re-running
`git commit`; a row crashed mid-`TESTING` re-enters the test step.
Tasks whose workspace is gone, whose worktree is missing, or whose
adapter handle columns are absent (i.e. dispatch never reached
`RUNNING`) are stamped `FAILED` with `RUNTIME_ERROR`.

------------------------------------------------------------------------
## Public API
See `service.py` for full signatures and contracts:

| Method | Effect | Approval | Purpose |
|---|---|---|---|
| `register_workspace` | write | always | Trust gate |
| `list_workspaces` | read | never | Audit / discovery |
| `revoke_workspace` | write | always | Withdraw trust |
| `run_task_async` | external | never | Dispatch a task; return immediately |
| `run_task_sync` | external | never | Dispatch a task; block until terminal |
| `wait_for_task` | read | never | Block on an existing task |
| `task_status` | read | never | Inspect lineage |
| `cancel_task` | execute | never | Stop in-flight work |
| `health` | read | never | Service + Adapter readiness |

The async / sync / wait split mirrors the Subagent precedent
(`subagent-async` / `subagent-sync` / `subagent-wait`). All methods
follow the project convention: keyword-only args after `meta:
EnvelopeMeta`, sync (in the Python sense), returning `Envelope[T]`,
decorated with `@public_api_instrumented` in the concrete implementation.

`register_workspace` accepts `path` plus optional
`default_executor`, `test_command`, `max_wallclock_seconds`,
`branch_prefix`. Any field omitted is filled from the corresponding
`software.default_*` setting, so a typical registration is just
`/workspace-register --path repo/brain`.

Choosing a dispatch shape:
* **`run_task_async`** when the task may take longer than the operator
  wants to wait, when the Job Service is scheduling the work, or when
  one caller dispatches and another (or a later session) collects.
* **`run_task_sync`** for short tasks where the operator types and waits
  for the result. Drives the task inline through the same driver used
  by async; bypasses the cross-thread DB poll.
* **`wait_for_task`** to block on a task already in flight. Idempotent
  on terminal tasks; respects an optional `max_wait_seconds` soft
  deadline so callers can poll-with-backoff without busy-waiting.

------------------------------------------------------------------------
## Persistence
Two tables in the `service_software` Postgres schema:

* `workspaces` — operator-allowlisted repository roots. Stores
  `path` (the in-container virtual path under `workspace_root`); the
  host bind-source is resolved on demand from brain-core's own Docker
  mount table at task spawn time. Soft-deleted on revoke (`revoked_at`
  set; row retained).
* `tasks` — one row per dispatched task, capturing the full lifecycle
  plus the persisted Coding Adapter handle (`adapter_handle_id`,
  `adapter_container_id`, `adapter_started_at`) so the Service can
  reconstruct a `CodingTaskHandle` and continue polling after a Brain
  Core restart. Executor and test-command stdout/stderr are stored in
  separate columns (`stdout_object_ref`, `stderr_object_ref`,
  `test_stdout_object_ref`, `test_stderr_object_ref`) referencing the
  Object Store.

------------------------------------------------------------------------
## Configuration
Service-level settings live under `software.*`:

* `workspace_root` — in-container virtual root under which operator
  repository trees are bind-mounted. Workspace registration paths are
  resolved against this root. Default `/mount/software`.
* `staging_root` — host directory under which per-task worktrees are
  created. Bind-mounted symmetrically (same path on host and inside
  brain-core) so the Coding Adapter sees worktrees at the same
  absolute path brain-core does, no host-vs-container translation.
  Default `~/.local/state/brain/software-tasks`.
* `default_executor`, `default_branch_prefix`,
  `default_max_wallclock_seconds`, `default_test_command` — defaults
  applied when a workspace registration omits a field.
* `commit_author_name`, `commit_author_email` — git identity for
  Brain-authored commits.

Workspaces themselves are not declared in YAML — they go through
`code-workspace-register`. This keeps the trust grant auditable and
prevents silent edits to a config file from granting code-execution
authority.


------------------------------------------------------------------------
_End of Software Service README_
