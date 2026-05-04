"""Container runtime contracts beneath the Coding Adapter.

The :class:`ContainerRuntime` Protocol is a swappable substrate underneath
the Coding Adapter. v1 will be implemented against host Docker via DooD
(socket bind-mounted into Brain Core); Podman or Apple Container can be
slotted in later by providing alternate :class:`ContainerRuntime`
implementations without touching :class:`~resources.adapters.coding.adapter.CodingAdapter`
or the Software Service.

The runtime is single-purpose: launch, supervise, and reap one container.
It does not know about executors, worktrees-as-domain-objects, prompts, or
tests. Those concerns belong upstream.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_STOP_TIMEOUT_SECONDS: Final[int] = 10


class ContainerRuntimeError(Exception):
    """Base exception for runtime-level failures."""


class ContainerRuntimeUnavailable(ContainerRuntimeError):
    """The runtime is not reachable (e.g., Docker daemon down)."""


class ContainerLaunchError(ContainerRuntimeError):
    """The runtime could not launch the requested container."""


class ContainerNotFoundError(ContainerRuntimeError):
    """The runtime has no record of the requested container."""


class ContainerPhase(StrEnum):
    """Container lifecycle phase as observed by the runtime."""

    CREATED = "created"
    RUNNING = "running"
    EXITED = "exited"
    UNKNOWN = "unknown"


class Mount(BaseModel):
    """One bind-mount applied to the container."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    read_only: bool = False


class ContainerSpec(BaseModel):
    """Everything the runtime needs to launch one container.

    The Coding Adapter materialises a
    :class:`~resources.adapters.coding.adapter.CodingTaskSpec` into a
    :class:`ContainerSpec`. The runtime only launches, supervises, and
    reaps; it does not interpret env, mounts, or commands.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    image: str = Field(min_length=1)
    command: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    mounts: tuple[Mount, ...] = ()
    labels: dict[str, str] = Field(default_factory=dict)
    workdir: str = ""
    stop_timeout_seconds: int = Field(default=DEFAULT_STOP_TIMEOUT_SECONDS, ge=0)
    # Note: `env` here is the runtime-level environment block (whatever the
    # Coding Adapter resolved from its env_keys allowlist). It is not the
    # task spec's env — that field has been removed since values now flow
    # through the Adapter's process env.


class ContainerHandle(BaseModel):
    """Runtime-issued handle for one launched container."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    container_id: str
    started_at: datetime
    labels: dict[str, str] = Field(default_factory=dict)


class ContainerStatus(BaseModel):
    """Lifecycle observation of one container."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    container_id: str
    phase: ContainerPhase
    exit_code: int | None = None
    observed_at: datetime


class ContainerLogs(BaseModel):
    """Captured stdout / stderr from one container run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stdout: bytes
    stderr: bytes


@runtime_checkable
class ContainerRuntime(Protocol):
    """Swappable container substrate for the Coding Adapter."""

    def health(self) -> bool:
        """Return ``True`` if the runtime is reachable and ready."""

    def launch(self, *, spec: ContainerSpec) -> ContainerHandle:
        """Launch one container.

        Raises:
            ContainerLaunchError: if the launch fails.
            ContainerRuntimeUnavailable: if the runtime is not reachable.
        """

    def status(self, *, handle: ContainerHandle) -> ContainerStatus:
        """Inspect lifecycle phase. Cheap; safe to call repeatedly.

        Raises:
            ContainerNotFoundError: if the container is unknown.
        """

    def stop(self, *, handle: ContainerHandle) -> None:
        """Send a stop signal. Idempotent; respects ``stop_timeout_seconds``
        from the original :class:`ContainerSpec` before forcing termination.

        Raises:
            ContainerNotFoundError: if the container is unknown.
        """

    def logs(self, *, handle: ContainerHandle) -> ContainerLogs:
        """Collect captured stdout/stderr.

        Only valid once the container has reached :attr:`ContainerPhase.EXITED`;
        otherwise the contents reflect output captured up to the moment of
        the call.
        """

    def remove(self, *, handle: ContainerHandle) -> None:
        """Reap the container. Idempotent."""

    def list_owned(self, *, owner_label: str) -> tuple[ContainerHandle, ...]:
        """Enumerate containers carrying the given owner label.

        Used by the Coding Adapter's startup sweeper to reap orphans left
        behind by a prior Brain Core process.
        """

    def host_path_for(self, *, container_path: str) -> str | None:
        """Translate a container-visible path to its host source.

        Looks up the calling process's own container in the runtime and
        finds the bind mount whose destination is a prefix of
        ``container_path``; returns the corresponding source path the
        host runtime would resolve, or ``None`` if no bind covers it.

        Raises:
            ContainerRuntimeUnavailable: if the runtime is not reachable.
        """
