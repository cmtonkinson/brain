"""Transport-neutral persistence interfaces for Software Service.

Two repository Protocols mirror the two ``service_software`` tables:

- :class:`WorkspaceRepository` — operator-allowlisted repository roots
- :class:`TaskRepository` — coding-task lineage rows

Both are intentionally narrow: each method maps to one row-level operation
the orchestration layer needs. In-memory implementations exist for tests;
Postgres implementations back production.
"""

from __future__ import annotations

from typing import Protocol

from services.effect.software.domain import Task, Workspace


class WorkspaceRepository(Protocol):
    """Persistence Protocol for the operator-allowlisted workspace catalog."""

    def append(self, *, workspace: Workspace) -> Workspace:
        """Persist one workspace row and return the stored value."""

    def get_by_id(self, *, workspace_id: str) -> Workspace | None:
        """Return one workspace by primary key, or ``None`` when absent."""

    def get_by_path(self, *, path: str) -> Workspace | None:
        """Return one workspace by absolute path, or ``None`` when absent.

        Used to enforce the no-duplicate-registration invariant. Path
        comparison is exact-match against the value persisted by the
        registration call.
        """

    def list_all(self, *, include_revoked: bool) -> tuple[Workspace, ...]:
        """Return every workspace row, filtered by revocation when requested."""

    def mark_revoked(self, *, workspace_id: str, revoked_at: object) -> Workspace:
        """Stamp ``revoked_at`` on one workspace and return the updated row.

        Idempotent: if the workspace is already revoked the existing row is
        returned unchanged.
        """


class TaskRepository(Protocol):
    """Persistence Protocol for coding-task lineage rows."""

    def append(self, *, task: Task) -> Task:
        """Persist one task lineage row and return the stored value."""

    def get_by_id(self, *, task_id: str) -> Task | None:
        """Return one task by primary key, or ``None`` when absent."""

    def update(self, *, task: Task) -> Task:
        """Overwrite one task lineage row with the supplied value."""

    def list_all(self) -> tuple[Task, ...]:
        """Return every task row in insertion order; intended for tests."""

    def list_active(self) -> tuple[Task, ...]:
        """Return every task currently in a non-terminal status.

        Used by the Service's startup reattach sweep so async-launched
        tasks left in flight by a previous Brain Core process can be
        polled to terminal by the freshly-booted process.
        """
