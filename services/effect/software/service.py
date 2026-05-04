"""Authoritative in-process Python API for Software Service.

The Software Service owns operator-allowlisted workspaces and the lifecycle
of coding tasks dispatched to the Coding Adapter. Trust is binary at
registration: :meth:`SoftwareService.register_workspace` is the only
approval gate; subsequent task ops against a registered, non-revoked
workspace run without per-call approval.

Tasks land in a fresh git worktree on a new branch under the workspace's
configured ``branch_prefix``, are handed off to the Coding Adapter for
execution, then verified against the workspace's configured test command
and committed if green. No push, no PR.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.coding.adapter import CodingAdapter, ExecutorId
from services.effect.software.domain import HealthStatus, Task, Workspace
from services.state.object.service import ObjectService


class SoftwareService(ABC):
    """Public API for the Software Service."""

    @abstractmethod
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
        """Register one repository as an allowlisted workspace.

        This op carries ``approval: always``; the Relay round-trip happens
        upstream of this method via the Execution / Policy pipeline. Once
        persisted, the workspace is trusted until revoked.

        Preconditions:
            ``path`` resolves to an existing directory on the Brain Core
            host that is the root of a git working tree.

        Postconditions:
            A row is appended to ``service_software.workspaces`` with
            ``revoked_at`` null. The returned :class:`Workspace` is the
            persisted record.

        Raises:
            ValueError: if ``path`` does not exist, is not a git repo, or
                is already registered.
        """

    @abstractmethod
    def list_workspaces(
        self,
        *,
        meta: EnvelopeMeta,
        include_revoked: bool = False,
    ) -> Envelope[tuple[Workspace, ...]]:
        """List registered workspaces.

        By default revoked workspaces are excluded; pass
        ``include_revoked=True`` for the full audit view.
        """

    @abstractmethod
    def revoke_workspace(
        self,
        *,
        meta: EnvelopeMeta,
        workspace_id: str,
    ) -> Envelope[Workspace]:
        """Revoke trust on a registered workspace.

        Subsequent :meth:`run_task` calls against the revoked workspace
        are rejected at this Service. Existing in-flight tasks are not
        cancelled by revocation; use :meth:`cancel_task` for that.

        Idempotent: revoking an already-revoked workspace returns the
        existing row unchanged.

        Raises:
            ValueError: if no workspace with ``workspace_id`` exists.
        """

    @abstractmethod
    def run_task_async(
        self,
        *,
        meta: EnvelopeMeta,
        workspace_id: str,
        prompt: str,
        executor: ExecutorId | None = None,
    ) -> Envelope[Task]:
        """Dispatch one coding task and return immediately.

        Creates a fresh git worktree on a new branch under the workspace's
        configured ``branch_prefix``, hands the worktree to the Coding
        Adapter for execution, persists the resulting handle on the task
        row, and returns the row in :class:`~services.effect.software.domain.TaskStatus`
        ``RUNNING``. Drives the task to terminal in a background thread;
        callers poll completion via :meth:`task_status` or block on
        :meth:`wait_for_task`.

        If ``executor`` is omitted, the workspace's ``default_executor``
        is used.

        Failure to dispatch (worktree creation failed, adapter rejected
        the launch, etc.) is surfaced as a failure envelope with a
        terminal task row in :class:`TaskStatus.FAILED`.
        """

    @abstractmethod
    def run_task_sync(
        self,
        *,
        meta: EnvelopeMeta,
        workspace_id: str,
        prompt: str,
        executor: ExecutorId | None = None,
    ) -> Envelope[Task]:
        """Dispatch one coding task and block until terminal.

        Returns the final task row in a terminal status (``SUCCEEDED``,
        ``FAILED``, ``CANCELLED``). The wallclock budget is enforced by
        the workspace's ``max_wallclock_seconds`` setting.

        Suitable for short tasks where the operator wants to type-and-wait
        in one shot. Long-running invocations (multi-minute coding
        agents, scheduled jobs) should prefer :meth:`run_task_async` and
        either poll :meth:`task_status` or block on :meth:`wait_for_task`
        separately.
        """

    @abstractmethod
    def wait_for_task(
        self,
        *,
        meta: EnvelopeMeta,
        task_id: str,
        max_wait_seconds: float | None = None,
    ) -> Envelope[Task]:
        """Block until one task reaches a terminal status.

        Returns the latest task row once the status is one of
        ``SUCCEEDED``, ``FAILED``, ``CANCELLED``. If ``max_wait_seconds``
        elapses first, returns the most recent (still non-terminal) row
        with a timed-out failure envelope; the caller may call again to
        continue waiting.

        Idempotent on already-terminal tasks: returns immediately.

        Raises:
            ValueError: if no task with ``task_id`` exists.
        """

    @abstractmethod
    def task_status(
        self,
        *,
        meta: EnvelopeMeta,
        task_id: str,
    ) -> Envelope[Task]:
        """Return the current task lineage row for one task.

        Raises:
            ValueError: if no task with ``task_id`` exists.
        """

    @abstractmethod
    def cancel_task(
        self,
        *,
        meta: EnvelopeMeta,
        task_id: str,
    ) -> Envelope[Task]:
        """Request cancellation of one in-flight task.

        Idempotent: cancelling a terminal task returns the existing row
        unchanged. The associated container is stopped via the Coding
        Adapter; the worktree is preserved on disk for operator inspection.

        Raises:
            ValueError: if no task with ``task_id`` exists.
        """

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Software Service and Coding Adapter readiness."""


def build_software_service(
    *,
    settings: CoreRuntimeSettings,
    adapter: CodingAdapter | None = None,
    object_service: ObjectService | None = None,
) -> SoftwareService:
    """Build default Software Service implementation from typed settings.

    Wires the concrete
    :class:`~services.effect.software.implementation.DefaultSoftwareService`
    against Postgres-backed workspace and task repositories. The Coding
    Adapter and Object Service are injected by the component loader so
    tests and alternative deployments can substitute fakes.
    """
    from services.effect.software.config import resolve_software_service_settings
    from services.effect.software.data.repository import (
        PostgresTaskRepository,
        PostgresWorkspaceRepository,
    )
    from services.effect.software.data.runtime import SoftwarePostgresRuntime
    from services.effect.software.implementation import DefaultSoftwareService

    runtime = SoftwarePostgresRuntime.from_settings(settings)
    return DefaultSoftwareService(
        settings=resolve_software_service_settings(settings),
        adapter=adapter,
        object_service=object_service,
        workspace_repository=PostgresWorkspaceRepository(runtime.schema_sessions),
        task_repository=PostgresTaskRepository(runtime.schema_sessions),
    )
