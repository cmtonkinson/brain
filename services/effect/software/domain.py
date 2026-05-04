"""Domain models for Software Service API payloads.

The Software Service tracks two domain concepts:

- :class:`Workspace` — an operator-allowlisted repository on the host
  filesystem. Registration is the binary trust gate.
- :class:`Task` — one coding-task lineage row, capturing the full lifecycle
  from intent through container teardown.

Cross-boundary types (``CodingTaskSpec``, ``CodingTaskResult``, etc.) live
in :mod:`resources.adapters.coding.adapter` and are imported there to avoid
duplicating the schema across the adapter / service boundary.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from resources.adapters.coding.adapter import ExecutorId, TerminationReason


class TaskStatus(StrEnum):
    """Lifecycle phase of one coding task as tracked by the Software Service.

    The Service-side phase set is intentionally a superset of the
    Adapter-side :class:`~resources.adapters.coding.adapter.TaskPhase`
    because the Service also models the pre-launch and post-test commit
    steps that the Adapter does not see.
    """

    PENDING = "pending"
    RUNNING = "running"
    TESTING = "testing"
    COMMITTING = "committing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Workspace(BaseModel):
    """One operator-allowlisted repository workspace.

    Registration is the binary trust gate: a registered, non-revoked
    workspace is trusted; an unregistered or revoked one is not. There
    is no per-task approval and no TTL.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    path: str
    default_executor: ExecutorId
    test_command: str
    max_wallclock_seconds: int
    branch_prefix: str
    created_at: datetime
    revoked_at: datetime | None = None


class Task(BaseModel):
    """One coding-task lineage row.

    Persisted in ``service_software.tasks`` from acceptance through
    terminal phase. References into the Object Store carry stdout, stderr,
    and (eventually) diff blobs so this row stays compact while the audit
    trail remains complete.

    The ``adapter_*`` columns persist enough information for the Service
    to reconstruct a :class:`~resources.adapters.coding.adapter.CodingTaskHandle`
    after a restart, so async-launched tasks can be polled to terminal
    by a freshly-booted Brain Core process or by ``wait_for_task`` invoked
    from a different operator session.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    workspace_id: str
    executor: ExecutorId
    branch: str
    prompt_object_ref: str | None
    status: TaskStatus
    started_at: datetime
    finished_at: datetime | None = None
    commit_sha: str | None = None
    test_passed: bool | None = None
    stdout_object_ref: str | None = None
    stderr_object_ref: str | None = None
    test_stdout_object_ref: str | None = None
    test_stderr_object_ref: str | None = None
    termination_reason: TerminationReason | None = None
    failure_detail: str | None = None
    adapter_handle_id: str | None = None
    adapter_container_id: str | None = None
    adapter_started_at: datetime | None = None


class HealthStatus(BaseModel):
    """Software Service and Coding Adapter readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_ready: bool
    detail: str


__all__ = [
    "HealthStatus",
    "Task",
    "TaskStatus",
    "Workspace",
]
