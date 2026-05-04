"""Coding Adapter contracts and DTOs.

The Coding Adapter wraps a configured catalog of coding-agent CLIs (Claude
Code, Codex, OpenCode) running inside ephemeral containers, exposing a
uniform Protocol for the Software Service to consume. The Adapter does not
interpret prompts, edit worktrees, run tests, or commit; those concerns
belong to the Software Service.

A swappable :class:`ContainerRuntime` (see ``runtime.py``) sits beneath the
Adapter so Podman or Apple Container can be slotted in later by providing
an alternate runtime implementation, without disturbing the per-executor
Adapter logic or the Software Service.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class CodingAdapterError(Exception):
    """Base exception for Coding Adapter failures."""


class CodingAdapterUnavailable(CodingAdapterError):
    """The Adapter or one of its required executors is not reachable."""


class CodingTaskRuntimeError(CodingAdapterError):
    """The container runtime failed to launch or supervise the task."""


class CodingTaskNotFoundError(CodingAdapterError):
    """The Adapter has no record of the requested task handle."""


class ExecutorId(StrEnum):
    """One of the supported coding-agent CLIs."""

    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    OPENCODE = "opencode"


class TaskPhase(StrEnum):
    """Lifecycle phase of one coding task as observed at the Adapter boundary."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TerminationReason(StrEnum):
    """Why a task transitioned out of ``RUNNING``.

    Recorded on the final :class:`CodingTaskResult` so the Software Service
    can branch on the cause without parsing logs.
    """

    EXECUTOR_EXITED = "executor_exited"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RUNTIME_ERROR = "runtime_error"
    NETWORK_POLICY_VIOLATION = "network_policy_violation"
    BUDGET_EXCEEDED = "budget_exceeded"


class ExecutorInfo(BaseModel):
    """Capability descriptor for one configured executor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ExecutorId
    version: str = ""
    available: bool


class ExecutorHealthStatus(BaseModel):
    """Coding Adapter readiness payload, including per-executor availability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ready: bool
    executors: tuple[ExecutorInfo, ...]
    detail: str = ""


class CodingTaskSpec(BaseModel):
    """Request to run one coding task in an isolated container.

    Constructed by the Software Service. The Adapter materialises this into
    a container invocation; it must not interpret the prompt or modify the
    worktree itself.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str = Field(min_length=1)
    executor: ExecutorId
    worktree_path: str = Field(min_length=1)
    workspace_path: str = Field(min_length=1)
    workspace_relative_path: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    max_wallclock_seconds: int = Field(gt=0)
    labels: dict[str, str] = Field(default_factory=dict)


class CodingTaskHandle(BaseModel):
    """Opaque handle returned by :meth:`CodingAdapter.run_task`.

    Required for subsequent ``poll``/``cancel``/``collect`` calls. The
    ``handle_id`` is Adapter-issued and need not match ``task_id``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    handle_id: str
    task_id: str
    container_id: str
    started_at: datetime


class CodingTaskStatusSnapshot(BaseModel):
    """Lightweight task status; cheap to call repeatedly."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    handle_id: str
    phase: TaskPhase
    last_observed_at: datetime
    exit_code: int | None = None


class CodingTaskResult(BaseModel):
    """Final outcome of one task. Only valid once ``phase`` is terminal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    handle_id: str
    task_id: str
    phase: TaskPhase
    exit_code: int | None
    elapsed_seconds: float
    termination_reason: TerminationReason


class CodingTaskLogs(BaseModel):
    """Captured stdout / stderr for one task, fetched before ``collect``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    handle_id: str
    stdout: bytes
    stderr: bytes


@runtime_checkable
class CodingAdapter(Protocol):
    """Protocol for invoking coding-agent CLIs inside ephemeral containers.

    Each implementation knows how to launch a configured executor (e.g.,
    Claude Code, Codex, OpenCode) inside a container that mounts the
    supplied worktree path. The Adapter is single-purpose: it does not
    interpret prompts, edit the worktree, run tests, or commit.

    Lifecycle: ``run_task`` accepts the task and returns a handle; the
    Software Service drives status with ``poll`` and finalises with
    ``collect``. ``cancel`` is idempotent and signals the runtime to stop
    the underlying container; the caller must still ``poll`` to confirm
    a terminal phase before calling ``collect``.
    """

    def health(self) -> ExecutorHealthStatus:
        """Probe Adapter and per-executor readiness."""

    def list_executors(self) -> tuple[ExecutorInfo, ...]:
        """Return the catalog of configured executors and their availability."""

    def resolve_workspace_host_path(self, *, workspace_path: str) -> str | None:
        """Translate a workspace's container path to the bind-mount source.

        Returns the host path the runtime would resolve when spawning a
        sibling container against ``workspace_path``, or ``None`` when no
        bind mount in brain-core's container covers it. Used by the
        Software Service at workspace registration to fail-fast on paths
        the operator hasn't bound, and by the Adapter itself at
        task-spawn time to populate the workspace mount source.

        Raises:
            CodingAdapterUnavailable: if the runtime is not reachable.
        """

    def run_task(self, *, spec: CodingTaskSpec) -> CodingTaskHandle:
        """Launch one task. Returns once the container has been accepted by
        the runtime; the task transitions to ``RUNNING`` asynchronously.

        Raises:
            CodingTaskRuntimeError: if the container could not be launched.
            CodingAdapterUnavailable: if the requested executor is not
                configured or its image is missing.
        """

    def poll(self, *, handle: CodingTaskHandle) -> CodingTaskStatusSnapshot:
        """Inspect current task phase. Cheap; safe to call repeatedly.

        Raises:
            CodingTaskNotFoundError: if the handle is unknown.
        """

    def cancel(self, *, handle: CodingTaskHandle) -> None:
        """Request termination. Idempotent; returns once cancellation has
        been accepted (not necessarily once the container has stopped).
        Callers must ``poll`` to observe the resulting terminal phase.

        Raises:
            CodingTaskNotFoundError: if the handle is unknown.
        """

    def logs(self, *, handle: CodingTaskHandle) -> CodingTaskLogs:
        """Read captured stdout / stderr without reaping the container.

        Must be called before :meth:`collect`, since ``collect`` removes the
        container. Safe to call once the task has reached any terminal
        phase.

        Raises:
            CodingTaskNotFoundError: if the handle is unknown.
        """

    def collect(self, *, handle: CodingTaskHandle) -> CodingTaskResult:
        """Drain the final result of a terminal task.

        Must only be called after ``poll`` has reported a terminal phase
        and after ``logs`` has been called if the caller wants to keep
        them. Reaps the underlying container; subsequent calls with the
        same handle raise :class:`CodingTaskNotFoundError`.
        """

    def list_owned(self) -> tuple[CodingTaskHandle, ...]:
        """Enumerate live handles owned by this Adapter instance.

        Used by the Software Service supervisor on Brain Core startup to
        reattach to any in-flight tasks and reap orphans whose Service-side
        lineage has been lost.
        """
