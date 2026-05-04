"""Concrete Software Service implementation.

Orchestrates the full coding-task lifecycle on top of the
:class:`CodingAdapter` boundary:

1. Operator-allowlisted workspace registration / revocation.
2. Per-task git worktree creation on a fresh feature branch.
3. Coding Adapter dispatch + polling to terminal phase.
4. stdout/stderr capture into the Object Service.
5. Test command execution against the worktree.
6. Brain-bot signed commit on success.
7. Lineage row persistence at every transition.

The worktree is intentionally **left intact** on disk for operator
inspection on every terminal outcome, including failure and cancellation.

Brain Core is assumed single-instance: no row-level lease or claim is
acquired at dispatch time, so running two ``DefaultSoftwareService``
instances against the same Postgres schema is unsupported and would race.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from lib.shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    new_meta,
    success,
    validate_meta,
)
from lib.shared.envelope.meta import EnvelopeKind
from lib.shared.errors import (
    codes,
    conflict_error,
    dependency_error,
    internal_error,
    not_found_error,
    validation_error,
)
from lib.shared.ids import generate_ulid_str
from lib.shared.logging import get_logger, public_api_instrumented
from resources.adapters.coding.adapter import (
    CodingAdapter,
    CodingAdapterError,
    CodingTaskHandle,
    CodingTaskNotFoundError,
    CodingTaskSpec,
    ExecutorId,
    TaskPhase,
    TerminationReason,
)
from services.effect.software.component import SERVICE_COMPONENT_ID
from services.effect.software.config import SoftwareServiceSettings
from services.effect.software.data.repository import (
    InMemoryTaskRepository,
    InMemoryWorkspaceRepository,
)
from services.effect.software.domain import HealthStatus, Task, TaskStatus, Workspace
from services.effect.software.interfaces import (
    TaskRepository,
    WorkspaceRepository,
)
from services.effect.software.service import SoftwareService
from services.state.object.service import ObjectService

_LOGGER = get_logger(__name__)

_DEFAULT_POLL_INTERVAL_SECONDS = 0.25
_DEFAULT_WAIT_INTERVAL_SECONDS = 0.25
_DEFAULT_MAX_DRIVERS = 4
_PROMPT_CONTENT_TYPE = "text/plain; charset=utf-8"
_LOG_CONTENT_TYPE = "text/plain; charset=utf-8"
_PROMPT_EXTENSION = "txt"
_LOG_EXTENSION = "log"
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_SHORT_ID_LENGTH = 8
_MAX_SLUG_LENGTH = 32
_BRAIN_TASK_OBJECT_SOURCE_SCHEME = "brain-task"
_GIT_REV_PARSE_TIMEOUT_SECONDS = 10
_GIT_DEFAULT_TIMEOUT_SECONDS = 120
_WALLCLOCK_GRACE_SECONDS = 5.0
_COMMIT_SUBJECT_MAX_LENGTH = 72

_TERMINAL_PHASES = {TaskPhase.SUCCEEDED, TaskPhase.FAILED, TaskPhase.CANCELLED}
_TERMINAL_STATUSES = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}


class DefaultSoftwareService(SoftwareService):
    """Software Service backed by the Coding Adapter and host filesystem.

    Persistence is delegated to a :class:`WorkspaceRepository` and a
    :class:`TaskRepository`; coding-agent execution to a
    :class:`CodingAdapter`; durable stdout/stderr capture to the Object
    Service. Each collaborator is injected so tests can substitute fakes.

    Tasks may be dispatched in two shapes mirroring Subagent: synchronous
    (block until terminal) via :meth:`run_task_sync`, or asynchronous
    (return immediately with a ``RUNNING`` row, drive to terminal in a
    background thread) via :meth:`run_task_async`. :meth:`wait_for_task`
    blocks on an existing async task. Long-running calls are bounded by
    the workspace's ``max_wallclock_seconds`` budget, enforced both at
    the Adapter and as a Service-side watchdog.

    On construction the Service performs a best-effort reattach sweep:
    any task in a non-terminal status (left in flight by a previous Brain
    Core process) is re-driven to terminal in a background thread. The
    driver consults the persisted ``status`` and resumes at the
    appropriate phase rather than restarting from the top — so a row
    crashed mid-``COMMITTING`` does not re-run ``git commit`` blindly,
    and a row crashed mid-``TESTING`` re-enters the test step rather
    than the executor poll.
    """

    def __init__(
        self,
        *,
        settings: SoftwareServiceSettings,
        adapter: CodingAdapter | None,
        object_service: ObjectService | None = None,
        workspace_repository: WorkspaceRepository | None = None,
        task_repository: TaskRepository | None = None,
        clock: Callable[[], datetime] | None = None,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
        wait_interval_seconds: float = _DEFAULT_WAIT_INTERVAL_SECONDS,
        max_drivers: int = _DEFAULT_MAX_DRIVERS,
        reattach_on_init: bool = True,
    ) -> None:
        self._settings = settings
        self._adapter = adapter
        self._object_service = object_service
        self._workspace_repository: WorkspaceRepository = (
            InMemoryWorkspaceRepository()
            if workspace_repository is None
            else workspace_repository
        )
        self._task_repository: TaskRepository = (
            InMemoryTaskRepository() if task_repository is None else task_repository
        )
        self._now: Callable[[], datetime] = clock if clock is not None else _utc_now
        self._poll_interval_seconds = poll_interval_seconds
        self._wait_interval_seconds = wait_interval_seconds
        self._drive_pool = ThreadPoolExecutor(
            max_workers=max(1, max_drivers),
            thread_name_prefix="software-driver",
        )
        self._drive_lock = threading.Lock()
        self._drive_futures: dict[str, Future[Task]] = {}
        # Per-task row-write serialization. The driver, the cancel path, and
        # any reattach driver may race to update one row; this map ensures
        # every read-modify-write on a task lineage row is atomic with
        # respect to other writers. Single-process only — see class docstring.
        self._task_locks_lock = threading.Lock()
        self._task_locks: dict[str, threading.Lock] = {}
        if reattach_on_init:
            self._reattach_active_tasks()

    def _lock_for(self, task_id: str) -> threading.Lock:
        """Return the per-task write lock, creating it on first use."""
        with self._task_locks_lock:
            existing = self._task_locks.get(task_id)
            if existing is not None:
                return existing
            created = threading.Lock()
            self._task_locks[task_id] = created
            return created

    def shutdown(self, *, wait: bool = False) -> None:
        """Drain the background driver pool. Idempotent.

        ``wait=True`` blocks until in-flight drives finish; ``False``
        (default) returns immediately and lets daemon threads exit when
        the process does. Tests may pass ``wait=True`` for deterministic
        teardown.
        """
        self._drive_pool.shutdown(wait=wait, cancel_futures=False)

    # -- Workspace ops -----------------------------------------------------

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def register_workspace(
        self,
        *,
        meta: EnvelopeMeta,
        path: str,
        default_executor: ExecutorId | None = None,
        test_command: str | None = None,
        max_wallclock_seconds: int | None = None,
        branch_prefix: str | None = None,
    ) -> Envelope[Workspace]:
        """See :meth:`SoftwareService.register_workspace`."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(meta=meta, errors=[validation_error(str(exc))])

        # Fill omitted fields from the Service's configured defaults so the
        # operator only has to type ``--path ...`` for a typical registration.
        if default_executor is None:
            default_executor = self._settings.default_executor
        if test_command is None:
            test_command = self._settings.default_test_command
        if max_wallclock_seconds is None:
            max_wallclock_seconds = self._settings.default_max_wallclock_seconds
        if branch_prefix is None:
            branch_prefix = self._settings.default_branch_prefix

        normalized_path, resolve_error = _resolve_workspace_container_path(
            raw_path=path,
            workspace_root=self._settings.workspace_root,
        )
        if resolve_error is not None:
            return failure(
                meta=meta,
                errors=[validation_error(resolve_error, code=codes.INVALID_ARGUMENT)],
            )
        if max_wallclock_seconds <= 0:
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        "max_wallclock_seconds must be positive",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )
        if branch_prefix.strip() == "":
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        "branch_prefix is required", code=codes.INVALID_ARGUMENT
                    )
                ],
            )

        path_obj = Path(normalized_path)
        if not path_obj.exists() or not path_obj.is_dir():
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        f"workspace path does not exist or is not a directory: {normalized_path}",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )
        if not _is_git_worktree_root(path_obj):
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        f"workspace path is not the root of a git working tree: {normalized_path}",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )

        existing = self._workspace_repository.get_by_path(path=normalized_path)
        if existing is not None:
            return failure(
                meta=meta,
                errors=[
                    conflict_error(
                        f"workspace already registered for path: {normalized_path}",
                    )
                ],
            )

        if self._adapter is not None:
            try:
                bind_source = self._adapter.resolve_workspace_host_path(
                    workspace_path=normalized_path
                )
            except CodingAdapterError as exc:
                return failure(
                    meta=meta,
                    errors=[
                        dependency_error(
                            f"coding adapter unavailable for path lookup: {exc}",
                            code=codes.DEPENDENCY_UNAVAILABLE,
                        )
                    ],
                )
            if bind_source is None:
                return failure(
                    meta=meta,
                    errors=[
                        validation_error(
                            (
                                f"workspace path {normalized_path} is not covered "
                                "by a bind mount in brain-core's container; the "
                                "host Docker daemon would have nothing to mount "
                                "into task containers. Add the host path to "
                                "docker-compose.override.yaml and restart brain-core."
                            ),
                            code=codes.INVALID_ARGUMENT,
                        )
                    ],
                )

        workspace = Workspace(
            id=generate_ulid_str(),
            path=normalized_path,
            default_executor=default_executor,
            test_command=test_command,
            max_wallclock_seconds=max_wallclock_seconds,
            branch_prefix=branch_prefix,
            created_at=self._now(),
            revoked_at=None,
        )
        stored = self._workspace_repository.append(workspace=workspace)
        return success(meta=meta, payload=stored)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def list_workspaces(
        self,
        *,
        meta: EnvelopeMeta,
        include_revoked: bool = False,
    ) -> Envelope[tuple[Workspace, ...]]:
        """See :meth:`SoftwareService.list_workspaces`."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(meta=meta, errors=[validation_error(str(exc))])
        rows = self._workspace_repository.list_all(include_revoked=include_revoked)
        return success(meta=meta, payload=rows)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def revoke_workspace(
        self,
        *,
        meta: EnvelopeMeta,
        workspace_id: str,
    ) -> Envelope[Workspace]:
        """See :meth:`SoftwareService.revoke_workspace`."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(meta=meta, errors=[validation_error(str(exc))])
        if workspace_id.strip() == "":
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        "workspace_id is required", code=codes.INVALID_ARGUMENT
                    )
                ],
            )

        existing = self._workspace_repository.get_by_id(workspace_id=workspace_id)
        if existing is None:
            return failure(
                meta=meta,
                errors=[
                    not_found_error(
                        f"workspace not found: {workspace_id}",
                        code=codes.NOT_FOUND,
                    )
                ],
            )
        revoked = self._workspace_repository.mark_revoked(
            workspace_id=workspace_id, revoked_at=self._now()
        )
        return success(meta=meta, payload=revoked)

    # -- Task ops ----------------------------------------------------------

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def run_task_async(
        self,
        *,
        meta: EnvelopeMeta,
        workspace_id: str,
        prompt: str,
        executor: ExecutorId | None = None,
    ) -> Envelope[Task]:
        """See :meth:`SoftwareService.run_task_async`."""
        dispatch = self._dispatch_task(
            meta=meta,
            workspace_id=workspace_id,
            prompt=prompt,
            executor=executor,
        )
        if dispatch.failure_envelope is not None:
            return dispatch.failure_envelope
        assert dispatch.running is not None
        assert dispatch.workspace is not None

        self._submit_drive(
            workspace=dispatch.workspace,
            running=dispatch.running,
            worktree_path=dispatch.worktree_path,
            prompt=prompt,
        )
        return success(meta=meta, payload=dispatch.running)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def run_task_sync(
        self,
        *,
        meta: EnvelopeMeta,
        workspace_id: str,
        prompt: str,
        executor: ExecutorId | None = None,
    ) -> Envelope[Task]:
        """See :meth:`SoftwareService.run_task_sync`."""
        dispatch = self._dispatch_task(
            meta=meta,
            workspace_id=workspace_id,
            prompt=prompt,
            executor=executor,
        )
        if dispatch.failure_envelope is not None:
            return dispatch.failure_envelope
        assert dispatch.running is not None
        assert dispatch.workspace is not None

        terminal = self._drive(
            meta=meta,
            workspace=dispatch.workspace,
            running=dispatch.running,
            worktree_path=dispatch.worktree_path,
            prompt=prompt,
        )
        return success(meta=meta, payload=terminal)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def wait_for_task(
        self,
        *,
        meta: EnvelopeMeta,
        task_id: str,
        max_wait_seconds: float | None = None,
    ) -> Envelope[Task]:
        """See :meth:`SoftwareService.wait_for_task`."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(meta=meta, errors=[validation_error(str(exc))])
        if task_id.strip() == "":
            return failure(
                meta=meta,
                errors=[
                    validation_error("task_id is required", code=codes.INVALID_ARGUMENT)
                ],
            )
        existing = self._task_repository.get_by_id(task_id=task_id)
        if existing is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"task not found: {task_id}")],
            )

        terminal_or_latest, timed_out = self._wait_terminal(
            task_id=task_id, max_wait_seconds=max_wait_seconds
        )
        if timed_out:
            return failure(
                meta=meta,
                payload=terminal_or_latest,
                errors=[
                    validation_error(
                        f"wait_for_task timed out after {max_wait_seconds}s",
                        code=codes.DEADLINE_EXCEEDED,
                    )
                ],
            )
        return success(meta=meta, payload=terminal_or_latest)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def task_status(
        self,
        *,
        meta: EnvelopeMeta,
        task_id: str,
    ) -> Envelope[Task]:
        """See :meth:`SoftwareService.task_status`."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(meta=meta, errors=[validation_error(str(exc))])
        if task_id.strip() == "":
            return failure(
                meta=meta,
                errors=[
                    validation_error("task_id is required", code=codes.INVALID_ARGUMENT)
                ],
            )
        existing = self._task_repository.get_by_id(task_id=task_id)
        if existing is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"task not found: {task_id}")],
            )
        return success(meta=meta, payload=existing)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def cancel_task(
        self,
        *,
        meta: EnvelopeMeta,
        task_id: str,
    ) -> Envelope[Task]:
        """See :meth:`SoftwareService.cancel_task`."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(meta=meta, errors=[validation_error(str(exc))])
        if task_id.strip() == "":
            return failure(
                meta=meta,
                errors=[
                    validation_error("task_id is required", code=codes.INVALID_ARGUMENT)
                ],
            )
        existing = self._task_repository.get_by_id(task_id=task_id)
        if existing is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"task not found: {task_id}")],
            )
        if existing.status in _TERMINAL_STATUSES:
            return success(meta=meta, payload=existing)

        # Adapter cancel is best-effort and runs outside the row lock so a
        # slow Docker `stop` doesn't pin the driver out of writing terminal
        # state. The lock is taken only around the row read-then-write.
        if self._adapter is not None and existing.adapter_handle_id is not None:
            handle = _synthesize_handle(existing)
            try:
                self._adapter.cancel(handle=handle)
            except CodingTaskNotFoundError:
                pass
            except CodingAdapterError as exc:
                _LOGGER.warning(
                    "coding adapter cancel raised; recording cancellation anyway",
                    extra={"task_id": task_id, "error": str(exc)},
                )

        with self._lock_for(task_id):
            current = self._task_repository.get_by_id(task_id=task_id)
            if current is None:
                return failure(
                    meta=meta,
                    errors=[not_found_error(f"task not found: {task_id}")],
                )
            if current.status in _TERMINAL_STATUSES:
                return success(meta=meta, payload=current)
            cancelled = current.model_copy(
                update={
                    "status": TaskStatus.CANCELLED,
                    "termination_reason": TerminationReason.CANCELLED,
                    "failure_detail": "cancelled by operator",
                    "finished_at": self._now(),
                }
            )
            self._task_repository.update(task=cancelled)
        return success(meta=meta, payload=cancelled)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """See :meth:`SoftwareService.health`."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(meta=meta, errors=[validation_error(str(exc))])

        adapter = self._adapter
        if adapter is None:
            return success(
                meta=meta,
                payload=HealthStatus(
                    adapter_ready=False,
                    detail="Coding Adapter not configured",
                ),
            )
        try:
            adapter_status = adapter.health()
        except CodingAdapterError as exc:
            return success(
                meta=meta,
                payload=HealthStatus(
                    adapter_ready=False,
                    detail=f"Coding Adapter health probe failed: {exc}",
                ),
            )
        return success(
            meta=meta,
            payload=HealthStatus(
                adapter_ready=adapter_status.ready,
                detail=adapter_status.detail,
            ),
        )

    # -- internal orchestration -------------------------------------------

    def _dispatch_task(
        self,
        *,
        meta: EnvelopeMeta,
        workspace_id: str,
        prompt: str,
        executor: ExecutorId | None,
    ) -> _DispatchResult:
        """Validate inputs, create the worktree, and hand off to the Adapter.

        On success the persisted task row carries ``status=RUNNING`` and
        the adapter handle columns; on failure a complete failure
        :class:`Envelope` is returned for the caller to forward verbatim.
        """
        try:
            validate_meta(meta)
        except ValueError as exc:
            return _DispatchResult.from_failure(
                failure(meta=meta, errors=[validation_error(str(exc))])
            )
        if prompt.strip() == "":
            return _DispatchResult.from_failure(
                failure(
                    meta=meta,
                    errors=[
                        validation_error(
                            "prompt is required", code=codes.INVALID_ARGUMENT
                        )
                    ],
                )
            )

        workspace = self._workspace_repository.get_by_id(workspace_id=workspace_id)
        if workspace is None:
            return _DispatchResult.from_failure(
                failure(
                    meta=meta,
                    errors=[
                        not_found_error(
                            f"workspace not found: {workspace_id}",
                            code=codes.NOT_FOUND,
                        )
                    ],
                )
            )
        if workspace.revoked_at is not None:
            return _DispatchResult.from_failure(
                failure(
                    meta=meta,
                    errors=[
                        validation_error(
                            f"workspace is revoked: {workspace_id}",
                            code=codes.INVALID_ARGUMENT,
                        )
                    ],
                )
            )
        if self._adapter is None:
            return _DispatchResult.from_failure(
                failure(
                    meta=meta,
                    errors=[
                        dependency_error(
                            "coding adapter is not configured",
                            code=codes.DEPENDENCY_UNAVAILABLE,
                            metadata={"adapter": "adapter_coding"},
                        )
                    ],
                )
            )

        chosen_executor = executor or workspace.default_executor
        task_id = generate_ulid_str()
        branch = _build_branch_name(prefix=workspace.branch_prefix, prompt=prompt)
        worktree_path = _resolve_worktree_path(
            staging_root=self._settings.staging_root, task_id=task_id
        )

        prompt_object_ref = self._store_blob(
            meta=meta,
            content=prompt.encode("utf-8"),
            extension=_PROMPT_EXTENSION,
            content_type=_PROMPT_CONTENT_TYPE,
            original_filename=f"{task_id}.prompt.txt",
            kind="prompt",
            task_id=task_id,
        )

        try:
            _create_worktree(
                repo_root=workspace.path,
                worktree_path=worktree_path,
                branch=branch,
            )
        except _GitInvocationError as exc:
            return _DispatchResult.from_failure(
                failure(
                    meta=meta,
                    errors=[
                        internal_error(
                            f"failed to create worktree: {exc}",
                            code=codes.INTERNAL_ERROR,
                        )
                    ],
                )
            )

        started_at = self._now()
        pending = Task(
            id=task_id,
            workspace_id=workspace.id,
            executor=chosen_executor,
            branch=branch,
            prompt_object_ref=prompt_object_ref,
            status=TaskStatus.PENDING,
            started_at=started_at,
        )
        self._task_repository.append(task=pending)

        spec = CodingTaskSpec(
            task_id=task_id,
            executor=chosen_executor,
            worktree_path=str(worktree_path),
            workspace_path=workspace.path,
            workspace_relative_path=_workspace_relative_path(
                workspace_path=workspace.path,
                workspace_root=self._settings.workspace_root,
            ),
            prompt=prompt,
            max_wallclock_seconds=workspace.max_wallclock_seconds,
            labels={
                "brain.coding.task_id": task_id,
                "brain.coding.workspace_id": workspace.id,
            },
        )

        try:
            handle = self._adapter.run_task(spec=spec)
        except CodingAdapterError as exc:
            terminal = pending.model_copy(
                update={
                    "status": TaskStatus.FAILED,
                    "termination_reason": TerminationReason.RUNTIME_ERROR,
                    "failure_detail": str(exc) or "coding adapter run_task failed",
                    "finished_at": self._now(),
                }
            )
            self._task_repository.update(task=terminal)
            return _DispatchResult.from_failure(
                failure(
                    meta=meta,
                    payload=terminal,
                    errors=[
                        dependency_error(
                            str(exc) or "coding adapter run_task failed",
                            code=codes.DEPENDENCY_UNAVAILABLE,
                            metadata={"adapter": "adapter_coding"},
                        )
                    ],
                )
            )

        running = pending.model_copy(
            update={
                "status": TaskStatus.RUNNING,
                "adapter_handle_id": handle.handle_id,
                "adapter_container_id": handle.container_id,
                "adapter_started_at": handle.started_at,
            }
        )
        self._task_repository.update(task=running)

        return _DispatchResult.from_success(
            workspace=workspace,
            running=running,
            worktree_path=worktree_path,
        )

    def _submit_drive(
        self,
        *,
        workspace: Workspace,
        running: Task,
        worktree_path: Path,
        prompt: str,
    ) -> Future[Task]:
        """Submit a drive-to-completion job to the background pool."""
        drive_meta = new_meta(
            kind=EnvelopeKind.COMMAND,
            source="service_software",
            principal="service_software",
            trace_id=running.id,
        )
        future = self._drive_pool.submit(
            self._safe_drive,
            drive_meta,
            workspace,
            running,
            worktree_path,
            prompt,
        )
        with self._drive_lock:
            self._drive_futures[running.id] = future

        def _release(_fut: Future[Task]) -> None:
            with self._drive_lock:
                self._drive_futures.pop(running.id, None)

        future.add_done_callback(_release)
        return future

    def _safe_drive(
        self,
        meta: EnvelopeMeta,
        workspace: Workspace,
        running: Task,
        worktree_path: Path,
        prompt: str,
    ) -> Task:
        """Drive a task to terminal, recording uncaught exceptions safely.

        On any uncaught exception, re-reads the persisted row before
        stamping ``FAILED``: if the row already moved to a terminal state
        externally (e.g. ``cancel_task`` ran on another thread) the
        persisted row is returned without overwriting.
        """
        try:
            return self._drive(
                meta=meta,
                workspace=workspace,
                running=running,
                worktree_path=worktree_path,
                prompt=prompt,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception(
                "background drive raised; recording terminal failure",
                extra={"task_id": running.id},
            )
            current = self._task_repository.get_by_id(task_id=running.id)
            if current is not None and current.status in _TERMINAL_STATUSES:
                return current
            return self._record_failure(
                task=current or running,
                reason=TerminationReason.RUNTIME_ERROR,
                detail=f"unexpected drive failure: {type(exc).__name__}: {exc}",
            )

    def _drive(
        self,
        *,
        meta: EnvelopeMeta,
        workspace: Workspace,
        running: Task,
        worktree_path: Path,
        prompt: str,
    ) -> Task:
        """Drive one task lineage row to terminal via :class:`_TaskDriver`."""
        adapter = self._adapter
        assert adapter is not None  # guarded by _dispatch_task and reattach
        driver = _TaskDriver(
            adapter=adapter,
            task_repository=self._task_repository,
            object_service=self._object_service,
            settings=self._settings,
            now=self._now,
            poll_interval_seconds=self._poll_interval_seconds,
            meta=meta,
            workspace=workspace,
            task=running,
            worktree_path=worktree_path,
            prompt=prompt,
            row_lock=self._lock_for(running.id),
        )
        return driver.drive()

    def _wait_terminal(
        self,
        *,
        task_id: str,
        max_wait_seconds: float | None,
    ) -> tuple[Task, bool]:
        """Block until ``task_id`` is terminal or the soft deadline lapses.

        Prefers an in-process ``Future`` when one is registered for this
        task in ``_drive_futures`` (i.e. dispatched by this Service
        instance); otherwise falls back to polling the repository. Returns
        ``(task, timed_out)`` — the most recent row plus whether the wait
        deadline was the reason for returning before terminal.
        """
        deadline = (
            None
            if max_wait_seconds is None
            else time.monotonic() + max(0.0, max_wait_seconds)
        )
        with self._drive_lock:
            future = self._drive_futures.get(task_id)

        if future is not None:
            timeout = (
                None if deadline is None else max(0.0, deadline - time.monotonic())
            )
            try:
                future.result(timeout=timeout)
            except TimeoutError:
                latest = self._task_repository.get_by_id(task_id=task_id)
                assert latest is not None
                return latest, True
            except Exception:  # noqa: BLE001
                # Drive logged + recorded the failure; surface the row.
                pass

        while True:
            current = self._task_repository.get_by_id(task_id=task_id)
            assert current is not None, f"task vanished while waiting: {task_id}"
            if current.status in _TERMINAL_STATUSES:
                return current, False
            if deadline is not None and time.monotonic() >= deadline:
                return current, True
            time.sleep(self._wait_interval_seconds)

    def _reattach_active_tasks(self) -> None:
        """Spawn a driver for every non-terminal task left over from a prior run.

        Best-effort: a task whose worktree is gone, whose workspace was
        deleted, or whose adapter handle columns are missing (i.e. dispatch
        never reached ``RUNNING``) is stamped ``FAILED`` outright. The
        driver's phase loop handles partial-progress resume itself.
        """
        try:
            active = self._task_repository.list_active()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("software-service reattach: list_active() failed")
            return
        if not active:
            return
        _LOGGER.info(
            "software-service reattach: scheduling %d in-flight task(s)",
            len(active),
        )
        for task in active:
            if (
                task.adapter_handle_id is None
                or task.adapter_container_id is None
                or task.adapter_started_at is None
            ):
                _LOGGER.warning(
                    "software-service reattach: task missing adapter handle; failing",
                    extra={"task_id": task.id, "status": str(task.status)},
                )
                self._record_failure(
                    task=task,
                    reason=TerminationReason.RUNTIME_ERROR,
                    detail="task abandoned before adapter dispatch completed",
                )
                continue
            workspace = self._workspace_repository.get_by_id(
                workspace_id=task.workspace_id
            )
            if workspace is None:
                _LOGGER.warning(
                    "software-service reattach: workspace gone; failing task",
                    extra={"task_id": task.id, "workspace_id": task.workspace_id},
                )
                self._record_failure(
                    task=task,
                    reason=TerminationReason.RUNTIME_ERROR,
                    detail="workspace was deleted while task was in flight",
                )
                continue
            worktree_path = _resolve_worktree_path(
                staging_root=self._settings.staging_root, task_id=task.id
            )
            prompt = self._fetch_prompt_text(task)
            self._submit_drive(
                workspace=workspace,
                running=task,
                worktree_path=worktree_path,
                prompt=prompt,
            )

    def _fetch_prompt_text(self, task: Task) -> str:
        """Best-effort recovery of the original prompt for commit summary.

        Used by the reattach path where we no longer have the in-memory
        prompt string. Falls back to a synthetic placeholder when the
        Object Service is not wired or the blob is missing; the resulting
        commit subject still identifies the task.
        """
        if not task.prompt_object_ref or self._object_service is None:
            return f"brain task {task.id}"
        try:
            envelope = self._object_service.get_object(
                meta=new_meta(
                    kind=EnvelopeKind.COMMAND,
                    source="service_software",
                    principal="service_software",
                    trace_id=task.id,
                ),
                object_key=task.prompt_object_ref,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "software-service reattach: prompt fetch failed",
                extra={"task_id": task.id, "object_ref": task.prompt_object_ref},
            )
            return f"brain task {task.id}"
        if not envelope.ok or envelope.payload is None:
            return f"brain task {task.id}"
        content = envelope.payload.value.content
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        if isinstance(content, str):
            return content
        return f"brain task {task.id}"

    def _record_failure(
        self,
        *,
        task: Task,
        reason: TerminationReason,
        detail: str,
        final_status: TaskStatus = TaskStatus.FAILED,
    ) -> Task:
        """Persist a failed/cancelled terminal task row and return it.

        Cancel-aware: re-reads the row under the per-task lock before
        persisting; if another writer already moved it to a terminal
        state, returns that row unchanged.
        """
        with self._lock_for(task.id):
            current = self._task_repository.get_by_id(task_id=task.id)
            if current is not None and current.status in _TERMINAL_STATUSES:
                return current
            terminal = (current or task).model_copy(
                update={
                    "status": final_status,
                    "termination_reason": reason,
                    "failure_detail": detail,
                    "finished_at": self._now(),
                }
            )
            self._task_repository.update(task=terminal)
            return terminal

    def _store_blob(
        self,
        *,
        meta: EnvelopeMeta,
        content: bytes,
        extension: str,
        content_type: str,
        original_filename: str,
        kind: str,
        task_id: str,
    ) -> str | None:
        """Persist one blob via Object Service and return its ``object_key``.

        Returns ``None`` when the Object Service is not wired (unit tests)
        or when ``put_object`` fails, so the orchestration logic remains
        exercisable without a SeaweedFS-backed substrate.
        """
        if self._object_service is None:
            return None
        envelope = self._object_service.put_object(
            meta=_child_meta(meta=meta, source="service_software"),
            content=content,
            extension=extension,
            content_type=content_type,
            original_filename=original_filename,
            source_uri=f"{_BRAIN_TASK_OBJECT_SOURCE_SCHEME}://{task_id}/{kind}",
        )
        if not envelope.ok or envelope.payload is None:
            _LOGGER.warning(
                "object service put_object failed for task asset",
                extra={"task_id": task_id, "kind": kind},
            )
            return None
        return envelope.payload.value.object.ref.object_key


class _DispatchResult:
    """Outcome of :meth:`DefaultSoftwareService._dispatch_task`.

    Two mutually-exclusive shapes: a populated ``failure_envelope`` (the
    dispatcher already built a complete failure :class:`Envelope` the
    caller should return verbatim), or a populated ``running``/``workspace``
    triple the caller should drive forward.
    """

    __slots__ = ("failure_envelope", "workspace", "running", "worktree_path")

    def __init__(
        self,
        *,
        failure_envelope: Envelope[Task] | None,
        workspace: Workspace | None,
        running: Task | None,
        worktree_path: Path | None,
    ) -> None:
        self.failure_envelope = failure_envelope
        self.workspace = workspace
        self.running = running
        self.worktree_path = worktree_path

    @classmethod
    def from_failure(cls, envelope: Envelope[Task]) -> _DispatchResult:
        """Construct a failure result carrying ``envelope`` for the caller."""
        return cls(
            failure_envelope=envelope,
            workspace=None,
            running=None,
            worktree_path=None,
        )

    @classmethod
    def from_success(
        cls,
        *,
        workspace: Workspace,
        running: Task,
        worktree_path: Path,
    ) -> _DispatchResult:
        """Construct a success result carrying the running task + worktree."""
        return cls(
            failure_envelope=None,
            workspace=workspace,
            running=running,
            worktree_path=worktree_path,
        )


# --------------------------------------------------------------------------
# Phase-aware task driver
# --------------------------------------------------------------------------


class _TaskDriver:
    """Drives one task lineage row through phase transitions to terminal.

    The phase loop consults the persisted task ``status`` and resumes at
    the appropriate phase: a row in ``RUNNING`` polls the executor, a row
    in ``TESTING`` re-runs the test command, a row in ``COMMITTING``
    finalizes idempotently. ``PENDING`` rows have not yet reached the
    adapter; they are stamped ``FAILED``.

    Every persistence write is cancel-aware: if another thread has moved
    the row to ``CANCELLED`` (or any terminal state) underneath us, we
    do not overwrite it — the operator's intent wins.
    """

    def __init__(
        self,
        *,
        adapter: CodingAdapter,
        task_repository: TaskRepository,
        object_service: ObjectService | None,
        settings: SoftwareServiceSettings,
        now: Callable[[], datetime],
        poll_interval_seconds: float,
        meta: EnvelopeMeta,
        workspace: Workspace,
        task: Task,
        worktree_path: Path,
        prompt: str,
        row_lock: threading.Lock,
    ) -> None:
        self._adapter = adapter
        self._task_repository = task_repository
        self._object_service = object_service
        self._settings = settings
        self._now = now
        self._poll_interval_seconds = poll_interval_seconds
        self._meta = meta
        self._workspace = workspace
        self._task = task
        self._worktree_path = worktree_path
        self._prompt = prompt
        self._row_lock = row_lock

    def drive(self) -> Task:
        """Drive the task to terminal, picking up at the persisted phase."""
        while self._task.status not in _TERMINAL_STATUSES:
            current = self._refresh_task()
            if current is None:
                return self._fail(
                    TerminationReason.RUNTIME_ERROR,
                    "task vanished from repository during drive",
                )
            self._task = current
            if self._task.status in _TERMINAL_STATUSES:
                return self._task
            if self._task.status is TaskStatus.PENDING:
                return self._fail(
                    TerminationReason.RUNTIME_ERROR,
                    "task abandoned in PENDING — dispatch never completed",
                )
            if self._task.status is TaskStatus.RUNNING:
                self._task = self._phase_run_executor()
            elif self._task.status is TaskStatus.TESTING:
                self._task = self._phase_run_test()
            elif self._task.status is TaskStatus.COMMITTING:
                self._task = self._phase_commit()
            else:
                return self._fail(
                    TerminationReason.RUNTIME_ERROR,
                    f"unexpected status during drive: {self._task.status}",
                )
        return self._task

    # -- phases ------------------------------------------------------------

    def _phase_run_executor(self) -> Task:
        """Poll the adapter to terminal phase, then collect logs."""
        handle = _synthesize_handle(self._task)
        deadline = (
            time.monotonic()
            + max(1, self._workspace.max_wallclock_seconds)
            + _WALLCLOCK_GRACE_SECONDS
        )
        timed_out = False
        while True:
            try:
                snapshot = self._adapter.poll(handle=handle)
            except CodingTaskNotFoundError:
                _LOGGER.warning(
                    "adapter lost handle mid-poll; recording runtime failure",
                    extra={"task_id": self._task.id},
                )
                return self._fail(
                    TerminationReason.RUNTIME_ERROR,
                    "adapter lost task handle while polling",
                )
            except CodingAdapterError as exc:
                _LOGGER.warning(
                    "adapter poll failed; recording runtime failure",
                    extra={"task_id": self._task.id, "error": str(exc)},
                )
                return self._fail(
                    TerminationReason.RUNTIME_ERROR,
                    str(exc) or "adapter poll failed",
                )

            if snapshot.phase in _TERMINAL_PHASES:
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            if self._is_cancelled():
                return self._fresh_or_self()
            time.sleep(self._poll_interval_seconds)

        if timed_out:
            try:
                self._adapter.cancel(handle=handle)
            except CodingAdapterError:
                pass
            stdout_ref, stderr_ref = self._capture_executor_logs(handle=handle)
            return self._persist_terminal(
                status=TaskStatus.FAILED,
                termination_reason=TerminationReason.TIMEOUT,
                failure_detail="task exceeded workspace max_wallclock_seconds",
                stdout_object_ref=stdout_ref,
                stderr_object_ref=stderr_ref,
            )

        stdout_ref, stderr_ref = self._capture_executor_logs(handle=handle)

        try:
            result = self._adapter.collect(handle=handle)
        except CodingAdapterError as exc:
            return self._fail(
                TerminationReason.RUNTIME_ERROR,
                str(exc) or "adapter collect failed",
            )

        if result.phase is TaskPhase.CANCELLED:
            return self._persist_terminal(
                status=TaskStatus.CANCELLED,
                termination_reason=TerminationReason.CANCELLED,
                failure_detail="task cancelled at runtime",
                stdout_object_ref=stdout_ref,
                stderr_object_ref=stderr_ref,
            )

        if result.phase is not TaskPhase.SUCCEEDED or (
            result.exit_code is not None and result.exit_code != 0
        ):
            detail = (
                f"executor exited non-zero: {result.exit_code}"
                if result.exit_code is not None
                else "executor reported failure"
            )
            return self._persist_terminal(
                status=TaskStatus.FAILED,
                termination_reason=result.termination_reason,
                failure_detail=detail,
                stdout_object_ref=stdout_ref,
                stderr_object_ref=stderr_ref,
            )

        if not _worktree_has_changes(self._worktree_path):
            return self._persist_terminal(
                status=TaskStatus.SUCCEEDED,
                termination_reason=result.termination_reason,
                stdout_object_ref=stdout_ref,
                stderr_object_ref=stderr_ref,
            )

        return self._persist_update(
            status=TaskStatus.TESTING,
            stdout_object_ref=stdout_ref,
            stderr_object_ref=stderr_ref,
        )

    def _phase_run_test(self) -> Task:
        """Run the workspace's test command and persist the outcome.

        Re-entrant: a reattach into ``TESTING`` re-runs the test command
        from scratch since intermediate test state is not persisted.
        """
        if not self._worktree_path.exists():
            return self._fail(
                TerminationReason.RUNTIME_ERROR,
                f"worktree missing on resume: {self._worktree_path}",
            )

        if self._workspace.test_command.strip() == "":
            return self._persist_update(status=TaskStatus.COMMITTING)

        # ``max_wallclock_seconds`` is the budget for the *whole* task, not
        # per-phase. Subtract executor wallclock already spent so a long
        # executor run can't trigger a second full-budget test run.
        remaining = self._remaining_wallclock_seconds()
        if remaining <= 0:
            return self._persist_terminal(
                status=TaskStatus.FAILED,
                termination_reason=TerminationReason.TIMEOUT,
                failure_detail=(
                    "no wallclock budget remaining for test command after executor"
                ),
            )

        test_result = _run_test_command(
            command=self._workspace.test_command,
            worktree_path=self._worktree_path,
            timeout_seconds=remaining,
        )
        test_stdout_ref = self._store_blob(
            content=test_result.stdout.encode("utf-8", errors="replace"),
            extension=_LOG_EXTENSION,
            content_type=_LOG_CONTENT_TYPE,
            original_filename=f"{self._task.id}.test.stdout.log",
            kind="test_stdout",
        )
        test_stderr_ref = self._store_blob(
            content=test_result.stderr.encode("utf-8", errors="replace"),
            extension=_LOG_EXTENSION,
            content_type=_LOG_CONTENT_TYPE,
            original_filename=f"{self._task.id}.test.stderr.log",
            kind="test_stderr",
        )

        if not test_result.passed:
            return self._persist_terminal(
                status=TaskStatus.FAILED,
                termination_reason=TerminationReason.EXECUTOR_EXITED,
                failure_detail=(
                    f"test command exited {test_result.exit_code}: "
                    f"{self._workspace.test_command}"
                ),
                test_stdout_object_ref=test_stdout_ref,
                test_stderr_object_ref=test_stderr_ref,
                test_passed=False,
            )

        return self._persist_update(
            status=TaskStatus.COMMITTING,
            test_stdout_object_ref=test_stdout_ref,
            test_stderr_object_ref=test_stderr_ref,
            test_passed=True,
        )

    def _phase_commit(self) -> Task:
        """Idempotently commit the worktree and persist the SHA.

        On reattach into ``COMMITTING`` the prior process may have already
        run ``git commit`` but failed to update the row. We detect that by
        inspecting the worktree: if it is clean and the branch has at least
        one commit, the prior process's commit landed; we record the SHA
        and finalize. Otherwise we run a normal ``git add -A && git commit``.
        """
        if not self._worktree_path.exists():
            return self._fail(
                TerminationReason.RUNTIME_ERROR,
                f"worktree missing on resume: {self._worktree_path}",
            )

        try:
            existing_sha = _detect_already_committed(self._worktree_path)
        except _GitInvocationError as exc:
            return self._fail(
                TerminationReason.RUNTIME_ERROR,
                f"could not inspect worktree state: {exc}",
            )

        if existing_sha is not None:
            return self._persist_terminal(
                status=TaskStatus.SUCCEEDED,
                termination_reason=TerminationReason.EXECUTOR_EXITED,
                commit_sha=existing_sha,
            )

        commit_summary = _build_commit_summary(prompt_text=self._prompt)
        try:
            sha = _commit_worktree(
                worktree_path=self._worktree_path,
                summary=commit_summary,
                author_name=self._settings.commit_author_name,
                author_email=self._settings.commit_author_email,
            )
        except _GitInvocationError as exc:
            return self._persist_terminal(
                status=TaskStatus.FAILED,
                termination_reason=TerminationReason.RUNTIME_ERROR,
                failure_detail=f"commit failed: {exc}",
            )

        return self._persist_terminal(
            status=TaskStatus.SUCCEEDED,
            termination_reason=TerminationReason.EXECUTOR_EXITED,
            commit_sha=sha,
        )

    # -- helpers -----------------------------------------------------------

    def _refresh_task(self) -> Task | None:
        """Return the current persisted state of this task row."""
        return self._task_repository.get_by_id(task_id=self._task.id)

    def _remaining_wallclock_seconds(self) -> int:
        """Return whole seconds left of the task's whole-task wallclock budget.

        Computed against ``task.started_at`` so executor and test phases
        share one budget, not two. Negative remainders are clamped to 0
        (caller fails the task with TIMEOUT).
        """
        elapsed = (self._now() - self._task.started_at).total_seconds()
        remaining = self._workspace.max_wallclock_seconds - elapsed
        return max(0, int(remaining))

    def _is_cancelled(self) -> bool:
        """Return True when the persisted row has been moved to terminal."""
        current = self._refresh_task()
        return current is not None and current.status in _TERMINAL_STATUSES

    def _fresh_or_self(self) -> Task:
        """Return the persisted row when present, else our local copy."""
        current = self._refresh_task()
        return current if current is not None else self._task

    def _fail(self, reason: TerminationReason, detail: str) -> Task:
        """Persist a ``FAILED`` terminal row, respecting external cancel."""
        return self._persist_terminal(
            status=TaskStatus.FAILED,
            termination_reason=reason,
            failure_detail=detail,
        )

    def _persist_update(self, *, status: TaskStatus, **fields: object) -> Task:
        """Persist a non-terminal phase transition; abort if cancelled."""
        with self._row_lock:
            current = self._refresh_task()
            if current is None:
                return self._task
            if current.status in _TERMINAL_STATUSES:
                return current
            updated = current.model_copy(update={"status": status, **fields})
            self._task_repository.update(task=updated)
            return updated

    def _persist_terminal(
        self,
        *,
        status: TaskStatus,
        **fields: object,
    ) -> Task:
        """Persist a terminal phase transition; do not overwrite cancellations."""
        with self._row_lock:
            current = self._refresh_task()
            if current is None:
                return self._task
            if current.status in _TERMINAL_STATUSES:
                return current
            updates: dict[str, object] = {"status": status, "finished_at": self._now()}
            updates.update(fields)
            terminal = current.model_copy(update=updates)
            self._task_repository.update(task=terminal)
            return terminal

    def _store_blob(
        self,
        *,
        content: bytes,
        extension: str,
        content_type: str,
        original_filename: str,
        kind: str,
    ) -> str | None:
        """Persist one log blob via Object Service; ``None`` when not wired."""
        if self._object_service is None:
            return None
        envelope = self._object_service.put_object(
            meta=_child_meta(meta=self._meta, source="service_software"),
            content=content,
            extension=extension,
            content_type=content_type,
            original_filename=original_filename,
            source_uri=(f"{_BRAIN_TASK_OBJECT_SOURCE_SCHEME}://{self._task.id}/{kind}"),
        )
        if not envelope.ok or envelope.payload is None:
            _LOGGER.warning(
                "object service put_object failed for task asset",
                extra={"task_id": self._task.id, "kind": kind},
            )
            return None
        return envelope.payload.value.object.ref.object_key

    def _capture_executor_logs(
        self, *, handle: CodingTaskHandle
    ) -> tuple[str | None, str | None]:
        """Read executor stdout/stderr from the adapter and stash them as blobs.

        Called after the adapter reports a terminal phase but before
        ``collect`` reaps the container. Failures are non-fatal: a missing
        Object Service or an adapter that can't read logs results in
        ``(None, None)`` and a warning, not a task-level failure.
        """
        try:
            captured = self._adapter.logs(handle=handle)
        except CodingTaskNotFoundError:
            _LOGGER.warning(
                "adapter lost handle while reading executor logs",
                extra={"task_id": self._task.id},
            )
            return None, None
        except CodingAdapterError as exc:
            _LOGGER.warning(
                "adapter logs() raised; proceeding without persisted output",
                extra={"task_id": self._task.id, "error": str(exc)},
            )
            return None, None
        stdout_ref = self._store_blob(
            content=captured.stdout,
            extension=_LOG_EXTENSION,
            content_type=_LOG_CONTENT_TYPE,
            original_filename=f"{self._task.id}.executor.stdout.log",
            kind="executor_stdout",
        )
        stderr_ref = self._store_blob(
            content=captured.stderr,
            extension=_LOG_EXTENSION,
            content_type=_LOG_CONTENT_TYPE,
            original_filename=f"{self._task.id}.executor.stderr.log",
            kind="executor_stderr",
        )
        return stdout_ref, stderr_ref


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def _utc_now() -> datetime:
    """Return current UTC datetime; replaceable in tests via ``clock`` arg."""
    return datetime.now(UTC)


def _resolve_workspace_container_path(
    *, raw_path: str, workspace_root: str
) -> tuple[str, str | None]:
    """Resolve an operator-supplied workspace path against ``workspace_root``.

    Returns ``(container_path, error)``. ``error`` is non-None when the
    operator passed a path that cannot be honored (empty, host-style
    absolute, or escapes the workspace root). The container path is
    returned even on success so the caller can chain validation calls.
    """
    if raw_path.strip() == "":
        return "", "path is required"
    root = Path(workspace_root).resolve()
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        # Accept absolute paths only when they already live under the
        # workspace root; otherwise the operator is using a host-style
        # path that brain-core cannot see.
        try:
            resolved_abs = candidate.resolve(strict=False)
        except OSError:
            return str(candidate), (
                f"workspace path could not be resolved: {candidate}"
            )
        try:
            resolved_abs.relative_to(root)
        except ValueError:
            return str(resolved_abs), (
                f"workspace path must be relative to {workspace_root!s} "
                f"or absolute under it; got {raw_path!r}. Bind your repo "
                "tree under that root via docker-compose.override.yaml."
            )
        return str(resolved_abs), None
    # Relative path: join under workspace_root and resolve symlinks.
    joined = (root / candidate).resolve(strict=False)
    try:
        joined.relative_to(root)
    except ValueError:
        return str(joined), (f"workspace path escapes {workspace_root!s}: {raw_path!r}")
    return str(joined), None


def _workspace_relative_path(*, workspace_path: str, workspace_root: str) -> str:
    """Return ``workspace_path`` expressed relative to ``workspace_root``.

    Used by the Coding Adapter to derive the per-workspace customization
    script path and the per-workspace image tag. Both inputs are expected
    to already be absolute container paths (``register_workspace`` resolves
    relative paths against the root before persistence).
    """
    return str(Path(workspace_path).relative_to(Path(workspace_root)))


def _is_git_worktree_root(path: Path) -> bool:
    """Return ``True`` when ``path`` is the working-tree root of a git repo."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_REV_PARSE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError, subprocess.TimeoutExpired:
        return False
    if result.returncode != 0:
        return False
    toplevel = result.stdout.strip()
    if toplevel == "":
        return False
    return Path(toplevel).resolve() == path.resolve()


def _build_branch_name(*, prefix: str, prompt: str) -> str:
    """Derive a deterministic feature-branch name from prompt text."""
    base = _slugify(prompt) or "task"
    short = generate_ulid_str()[-_SHORT_ID_LENGTH:].lower()
    cleaned_prefix = prefix.strip().strip("/")
    return f"{cleaned_prefix}/{base}-{short}"


def _slugify(text: str) -> str:
    """Convert free-form text to a hyphenated lowercase branch slug."""
    lowered = text.strip().lower()
    slug = _SLUG_PATTERN.sub("-", lowered).strip("-")
    if len(slug) > _MAX_SLUG_LENGTH:
        slug = slug[:_MAX_SLUG_LENGTH].rstrip("-")
    return slug


def _resolve_worktree_path(*, staging_root: str, task_id: str) -> Path:
    """Return the canonical worktree directory path for ``task_id``."""
    root = Path(staging_root).expanduser()
    return root / task_id


class _GitInvocationError(RuntimeError):
    """Raised when a ``git`` subprocess returns a non-zero exit status."""


def _run_git(
    *args: str, cwd: str | None = None, env: dict[str, str] | None = None
) -> str:
    """Execute one ``git`` command and return stripped stdout."""
    try:
        result = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
            timeout=_GIT_DEFAULT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise _GitInvocationError("git executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise _GitInvocationError("git command timed out") from exc
    if result.returncode != 0:
        raise _GitInvocationError(
            f"git {' '.join(args)} failed: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def _create_worktree(*, repo_root: str, worktree_path: Path, branch: str) -> None:
    """Materialise a fresh worktree at ``worktree_path`` on a new ``branch``."""
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    if worktree_path.exists():
        raise _GitInvocationError(f"worktree path already exists: {worktree_path}")
    _run_git(
        "-C",
        repo_root,
        "worktree",
        "add",
        "-b",
        branch,
        str(worktree_path),
    )


def _worktree_has_changes(worktree_path: Path) -> bool:
    """Return ``True`` when the worktree has uncommitted changes."""
    try:
        output = _run_git("-C", str(worktree_path), "status", "--porcelain")
    except _GitInvocationError:
        return False
    return output != ""


def _detect_already_committed(worktree_path: Path) -> str | None:
    """Detect a prior process's commit on the worktree's branch.

    Returns the SHA when the worktree is clean and HEAD points at a
    commit that is not the upstream branch tip (i.e. work was committed
    onto the feature branch). Returns ``None`` when the worktree is dirty
    (commit has not run yet) or when no feature commits exist.
    """
    if _worktree_has_changes(worktree_path):
        return None
    head = _run_git("-C", str(worktree_path), "rev-parse", "HEAD")
    if head == "":
        return None
    try:
        upstream = _run_git("-C", str(worktree_path), "rev-parse", "HEAD@{upstream}")
    except _GitInvocationError:
        upstream = ""
    if upstream and head == upstream:
        return None
    return head


def _commit_worktree(
    *,
    worktree_path: Path,
    summary: str,
    author_name: str,
    author_email: str,
) -> str:
    """Stage, commit, and return the commit SHA for the worktree."""
    _run_git("-C", str(worktree_path), "add", "-A")
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        }
    )
    _run_git(
        "-C",
        str(worktree_path),
        "commit",
        "-m",
        summary,
        env=env,
    )
    return _run_git("-C", str(worktree_path), "rev-parse", "HEAD")


class _TestCommandResult:
    """Outcome of running the workspace test command against a worktree."""

    __slots__ = ("passed", "exit_code", "stdout", "stderr")

    def __init__(
        self, *, passed: bool, exit_code: int, stdout: str, stderr: str
    ) -> None:
        self.passed = passed
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def _run_test_command(
    *,
    command: str,
    worktree_path: Path,
    timeout_seconds: int,
) -> _TestCommandResult:
    """Run the workspace test command in ``worktree_path``."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            cwd=str(worktree_path),
            timeout=max(1, timeout_seconds),
        )
    except subprocess.TimeoutExpired as exc:
        return _TestCommandResult(
            passed=False,
            exit_code=124,
            stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "")
            if isinstance(exc.stderr, str)
            else "test command timed out",
        )
    return _TestCommandResult(
        passed=result.returncode == 0,
        exit_code=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
    )


def _build_commit_summary(*, prompt_text: str) -> str:
    """Produce a short commit subject from the operator prompt text."""
    head = (
        prompt_text.strip().splitlines()[0]
        if prompt_text.strip()
        else "brain coding task"
    )
    return (
        head[:_COMMIT_SUBJECT_MAX_LENGTH]
        if len(head) > _COMMIT_SUBJECT_MAX_LENGTH
        else head
    )


def _synthesize_handle(task: Task) -> CodingTaskHandle:
    """Reconstruct a CodingTaskHandle from a persisted Task row.

    The Service stamps the adapter-issued handle fields (``adapter_handle_id``,
    ``adapter_container_id``, ``adapter_started_at``) on the row at
    dispatch time, so re-entering ``poll`` / ``cancel`` / ``collect`` after
    a process restart targets the same underlying handle. Callers must
    only invoke this helper on rows known to carry those columns; the
    reattach + cancel paths verify that explicitly.
    """
    assert task.adapter_handle_id is not None
    assert task.adapter_container_id is not None
    assert task.adapter_started_at is not None
    return CodingTaskHandle(
        handle_id=task.adapter_handle_id,
        task_id=task.id,
        container_id=task.adapter_container_id,
        started_at=task.adapter_started_at,
    )


def _child_meta(*, meta: EnvelopeMeta, source: str) -> EnvelopeMeta:
    """Derive a child envelope inheriting trace/principal from the parent."""
    return new_meta(
        kind=EnvelopeKind.COMMAND,
        source=source,
        principal=meta.principal,
        trace_id=meta.trace_id,
        parent_id=meta.envelope_id,
    )
