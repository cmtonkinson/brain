"""Repository implementations for the Software Service.

In-memory backings for unit tests; Postgres backings for production. All
repositories implement the Protocols declared in
:mod:`services.effect.software.interfaces`.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from lib.shared.ids import ulid_bytes_to_str, ulid_str_to_bytes
from resources.adapters.coding.adapter import ExecutorId, TerminationReason
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.effect.software.data.schema import tasks, workspaces
from services.effect.software.domain import Task, TaskStatus, Workspace
from services.effect.software.interfaces import (
    TaskRepository,
    WorkspaceRepository,
)

_TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
)


class InMemoryWorkspaceRepository(WorkspaceRepository):
    """In-memory workspace repository for unit tests."""

    def __init__(self) -> None:
        self._rows: list[Workspace] = []

    def append(self, *, workspace: Workspace) -> Workspace:
        """Persist one workspace row in append-only order."""
        self._rows.append(workspace)
        return workspace

    def get_by_id(self, *, workspace_id: str) -> Workspace | None:
        """Return one workspace by primary key, or ``None`` when absent."""
        for row in self._rows:
            if row.id == workspace_id:
                return row
        return None

    def get_by_path(self, *, path: str) -> Workspace | None:
        """Return the most recent non-revoked workspace at ``path``.

        Revoked rows are skipped so revoking a workspace and re-registering
        the same path is permitted (the revoked row remains for audit).
        """
        for row in reversed(self._rows):
            if row.path == path and row.revoked_at is None:
                return row
        return None

    def list_all(self, *, include_revoked: bool) -> tuple[Workspace, ...]:
        """Return every workspace row, filtered by revocation when requested."""
        if include_revoked:
            return tuple(self._rows)
        return tuple(row for row in self._rows if row.revoked_at is None)

    def mark_revoked(self, *, workspace_id: str, revoked_at: object) -> Workspace:
        """Stamp ``revoked_at`` on one workspace and return the updated row.

        Idempotent: returns the existing row unchanged when already revoked.
        """
        for index, row in enumerate(self._rows):
            if row.id != workspace_id:
                continue
            if row.revoked_at is not None:
                return row
            updated = row.model_copy(update={"revoked_at": revoked_at})
            self._rows[index] = updated
            return updated
        raise KeyError(workspace_id)


class InMemoryTaskRepository(TaskRepository):
    """In-memory task repository for unit tests."""

    def __init__(self) -> None:
        self._rows: list[Task] = []

    def append(self, *, task: Task) -> Task:
        """Persist one task row in append-only order."""
        self._rows.append(task)
        return task

    def get_by_id(self, *, task_id: str) -> Task | None:
        """Return one task by primary key, or ``None`` when absent."""
        for row in self._rows:
            if row.id == task_id:
                return row
        return None

    def update(self, *, task: Task) -> Task:
        """Overwrite the existing row with the same id; raise when absent."""
        for index, row in enumerate(self._rows):
            if row.id == task.id:
                self._rows[index] = task
                return task
        raise KeyError(task.id)

    def list_all(self) -> tuple[Task, ...]:
        """Return every task row in insertion order."""
        return tuple(self._rows)

    def list_active(self) -> tuple[Task, ...]:
        """Return every task currently in a non-terminal status."""
        return tuple(row for row in self._rows if row.status not in _TERMINAL_STATUSES)


class PostgresWorkspaceRepository(WorkspaceRepository):
    """SQL repository over the ``service_software.workspaces`` table."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def append(self, *, workspace: Workspace) -> Workspace:
        """Persist one workspace row keyed on canonical ULID bytes."""
        with self._sessions.session() as session:
            session.execute(
                insert(workspaces).values(
                    id=ulid_str_to_bytes(workspace.id),
                    path=workspace.path,
                    default_executor=str(workspace.default_executor),
                    test_command=workspace.test_command,
                    max_wallclock_seconds=workspace.max_wallclock_seconds,
                    branch_prefix=workspace.branch_prefix,
                    created_at=workspace.created_at,
                    revoked_at=workspace.revoked_at,
                )
            )
        return workspace

    def get_by_id(self, *, workspace_id: str) -> Workspace | None:
        """Return one workspace by primary key, or ``None``."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(workspaces).where(
                        workspaces.c.id == ulid_str_to_bytes(workspace_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _row_to_workspace(row)

    def get_by_path(self, *, path: str) -> Workspace | None:
        """Return one non-revoked workspace by path, or ``None``."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(workspaces)
                    .where(workspaces.c.path == path)
                    .where(workspaces.c.revoked_at.is_(None))
                    .order_by(workspaces.c.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _row_to_workspace(row)

    def list_all(self, *, include_revoked: bool) -> tuple[Workspace, ...]:
        """Return every workspace row, filtered by revocation when requested."""
        with self._sessions.session() as session:
            stmt = select(workspaces).order_by(workspaces.c.created_at.asc())
            if not include_revoked:
                stmt = stmt.where(workspaces.c.revoked_at.is_(None))
            rows = session.execute(stmt).mappings().all()
        return tuple(_row_to_workspace(row) for row in rows)

    def mark_revoked(self, *, workspace_id: str, revoked_at: object) -> Workspace:
        """Stamp ``revoked_at`` on one workspace and return the updated row."""
        existing = self.get_by_id(workspace_id=workspace_id)
        if existing is None:
            raise KeyError(workspace_id)
        if existing.revoked_at is not None:
            return existing
        with self._sessions.session() as session:
            session.execute(
                update(workspaces)
                .where(workspaces.c.id == ulid_str_to_bytes(workspace_id))
                .values(revoked_at=revoked_at)
            )
        updated = self.get_by_id(workspace_id=workspace_id)
        assert updated is not None
        return updated


class PostgresTaskRepository(TaskRepository):
    """SQL repository over the ``service_software.tasks`` table."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def append(self, *, task: Task) -> Task:
        """Persist one task lineage row keyed on canonical ULID bytes."""
        with self._sessions.session() as session:
            session.execute(insert(tasks).values(_task_columns(task)))
        return task

    def get_by_id(self, *, task_id: str) -> Task | None:
        """Return one task by primary key, or ``None``."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(tasks).where(tasks.c.id == ulid_str_to_bytes(task_id))
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _row_to_task(row)

    def update(self, *, task: Task) -> Task:
        """Overwrite one task lineage row in place; raise when absent."""
        existing = self.get_by_id(task_id=task.id)
        if existing is None:
            raise KeyError(task.id)
        values = _task_columns(task)
        values.pop("id")
        with self._sessions.session() as session:
            session.execute(
                update(tasks)
                .where(tasks.c.id == ulid_str_to_bytes(task.id))
                .values(**values)
            )
        return task

    def list_all(self) -> tuple[Task, ...]:
        """Return every task row ordered by start time."""
        with self._sessions.session() as session:
            rows = (
                session.execute(select(tasks).order_by(tasks.c.started_at.asc()))
                .mappings()
                .all()
            )
        return tuple(_row_to_task(row) for row in rows)

    def list_active(self) -> tuple[Task, ...]:
        """Return every task currently in a non-terminal status."""
        terminal_values = tuple(str(status) for status in _TERMINAL_STATUSES)
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(tasks)
                    .where(tasks.c.status.notin_(terminal_values))
                    .order_by(tasks.c.started_at.asc())
                )
                .mappings()
                .all()
            )
        return tuple(_row_to_task(row) for row in rows)


def _row_to_workspace(row: object) -> Workspace:
    """Construct one :class:`Workspace` from a SQLAlchemy ``RowMapping``."""
    mapping = cast(dict[str, object], dict(row))  # type: ignore[arg-type]
    return Workspace(
        id=_ulid_string(mapping["id"]),
        path=cast(str, mapping["path"]),
        default_executor=ExecutorId(cast(str, mapping["default_executor"])),
        test_command=cast(str, mapping["test_command"]),
        max_wallclock_seconds=cast(int, mapping["max_wallclock_seconds"]),
        branch_prefix=cast(str, mapping["branch_prefix"]),
        created_at=cast(datetime, mapping["created_at"]),
        revoked_at=cast(datetime | None, mapping.get("revoked_at")),
    )


def _row_to_task(row: object) -> Task:
    """Construct one :class:`Task` from a SQLAlchemy ``RowMapping``."""
    mapping = cast(dict[str, object], dict(row))  # type: ignore[arg-type]
    return Task(
        id=_ulid_string(mapping["id"]),
        workspace_id=_ulid_string(mapping["workspace_id"]),
        executor=ExecutorId(cast(str, mapping["executor"])),
        branch=cast(str, mapping["branch"]),
        prompt_object_ref=cast(str | None, mapping.get("prompt_object_ref")),
        status=TaskStatus(cast(str, mapping["status"])),
        commit_sha=cast(str | None, mapping.get("commit_sha")),
        test_passed=cast(bool | None, mapping.get("test_passed")),
        stdout_object_ref=cast(str | None, mapping.get("stdout_object_ref")),
        stderr_object_ref=cast(str | None, mapping.get("stderr_object_ref")),
        test_stdout_object_ref=cast(str | None, mapping.get("test_stdout_object_ref")),
        test_stderr_object_ref=cast(str | None, mapping.get("test_stderr_object_ref")),
        termination_reason=(
            None
            if mapping.get("termination_reason") is None
            else TerminationReason(cast(str, mapping["termination_reason"]))
        ),
        failure_detail=cast(str | None, mapping.get("failure_detail")),
        started_at=cast(datetime, mapping["started_at"]),
        finished_at=cast(datetime | None, mapping.get("finished_at")),
        adapter_handle_id=cast(str | None, mapping.get("adapter_handle_id")),
        adapter_container_id=cast(str | None, mapping.get("adapter_container_id")),
        adapter_started_at=cast(datetime | None, mapping.get("adapter_started_at")),
    )


def _task_columns(task: Task) -> dict[str, object]:
    """Materialise one :class:`Task` into the ``tasks`` insert/update columns."""
    return {
        "id": ulid_str_to_bytes(task.id),
        "workspace_id": ulid_str_to_bytes(task.workspace_id),
        "executor": str(task.executor),
        "branch": task.branch,
        "prompt_object_ref": task.prompt_object_ref,
        "status": str(task.status),
        "commit_sha": task.commit_sha,
        "test_passed": task.test_passed,
        "stdout_object_ref": task.stdout_object_ref,
        "stderr_object_ref": task.stderr_object_ref,
        "test_stdout_object_ref": task.test_stdout_object_ref,
        "test_stderr_object_ref": task.test_stderr_object_ref,
        "termination_reason": (
            None if task.termination_reason is None else str(task.termination_reason)
        ),
        "failure_detail": task.failure_detail,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "adapter_handle_id": task.adapter_handle_id,
        "adapter_container_id": task.adapter_container_id,
        "adapter_started_at": task.adapter_started_at,
    }


def _ulid_string(value: object) -> str:
    """Coerce a row's binary ULID column to canonical 26-char form."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ulid_bytes_to_str(bytes(value))
    if isinstance(value, str):
        return value
    raise TypeError(f"unexpected ULID column type: {type(value)!r}")
