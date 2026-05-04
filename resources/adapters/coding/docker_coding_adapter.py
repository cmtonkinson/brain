"""Docker-backed :class:`CodingAdapter` implementation.

Materialises a :class:`~resources.adapters.coding.adapter.CodingTaskSpec`
into a :class:`~resources.adapters.coding.runtime.ContainerSpec` (image,
argv, mounts, env, labels) and delegates lifecycle to a
:class:`~resources.adapters.coding.runtime.ContainerRuntime` (default:
the host-Docker DooD runtime).

Per the contract in :mod:`resources.adapters.coding.adapter` this module
only launches, observes, and reaps; it does not interpret prompts, edit
worktrees, run tests, or commit. Those concerns live in the Software
Service.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

from resources.adapters.coding.adapter import (
    CodingAdapter,
    CodingAdapterUnavailable,
    CodingTaskHandle,
    CodingTaskLogs,
    CodingTaskNotFoundError,
    CodingTaskResult,
    CodingTaskRuntimeError,
    CodingTaskSpec,
    CodingTaskStatusSnapshot,
    ExecutorHealthStatus,
    ExecutorId,
    ExecutorInfo,
    TaskPhase,
    TerminationReason,
)
from resources.adapters.coding.config import (
    CodingAdapterSettings,
    CodingExecutorSettings,
)
from resources.adapters.coding.image_builder import (
    ImageBuildFailed,
    ImageBuilder,
    ImageBuilderUnavailable,
)
from resources.adapters.coding.registry import UnknownExecutorError, shape_command
from resources.adapters.coding.runtime import (
    ContainerHandle,
    ContainerLaunchError,
    ContainerNotFoundError,
    ContainerPhase,
    ContainerRuntime,
    ContainerRuntimeError,
    ContainerRuntimeUnavailable,
    ContainerSpec,
    Mount,
)

LABEL_TASK_ID: Final[str] = "brain.coding.task_id"
LABEL_OWNER: Final[str] = "brain.coding.owner"
LABEL_EXECUTOR: Final[str] = "brain.coding.executor"
WORKTREE_MOUNT_TARGET: Final[str] = "/work"
_REATTACHED_HANDLE_PREFIX: Final[str] = "reattached-"
_MIN_STOP_TIMEOUT_SECONDS: Final[int] = 1


def _default_now() -> datetime:
    """Return current UTC timestamp (default clock)."""
    return datetime.now(UTC)


class _RuntimeRecord:
    """Adapter-side bookkeeping for one launched task."""

    __slots__ = (
        "cancelled",
        "container_handle",
        "executor",
        "owner",
        "spec",
        "started_at",
        "task_id",
    )

    def __init__(
        self,
        *,
        spec: CodingTaskSpec,
        container_handle: ContainerHandle,
        owner: str,
    ) -> None:
        self.spec = spec
        self.container_handle = container_handle
        self.owner = owner
        self.task_id = spec.task_id
        self.executor = spec.executor
        self.started_at = container_handle.started_at
        self.cancelled = False


class DockerCodingAdapter(CodingAdapter):
    """Concrete :class:`CodingAdapter` over a :class:`ContainerRuntime`.

    Parameters
    ----------
    settings:
        Resolved adapter settings (executor catalog, owner-label key, etc.).
    runtime:
        Container substrate; v1 ships
        :class:`~resources.adapters.coding.docker_runtime.DockerContainerRuntime`.
    owner_id:
        Stable identifier for *this* Brain Core process; written to the
        ``brain.coding.owner`` label so the orphan sweeper can find
        stragglers from a prior process.
    now_func:
        Injectable wall-clock for tests. Defaults to ``datetime.now(UTC)``.
    env_source:
        Mapping the adapter consults for the ``env_keys`` allowlist when
        building each task container's environment. Defaults to
        :data:`os.environ` (operator-supplied via Compose), tests pass an
        explicit dict.
    """

    def __init__(
        self,
        *,
        settings: CodingAdapterSettings,
        runtime: ContainerRuntime,
        image_builder: ImageBuilder,
        owner_id: str,
        now_func: Callable[[], datetime] | None = None,
        env_source: Mapping[str, str] | None = None,
    ) -> None:
        self._settings = settings
        self._runtime = runtime
        self._image_builder = image_builder
        self._owner_id = owner_id
        self._now: Callable[[], datetime] = now_func or _default_now
        self._env_source: Mapping[str, str] = (
            env_source if env_source is not None else os.environ
        )
        self._handles: dict[str, _RuntimeRecord] = {}

    # ------------------------------------------------------------------
    # Adapter protocol surface
    # ------------------------------------------------------------------
    def health(self) -> ExecutorHealthStatus:
        """Probe runtime + per-executor configuration readiness.

        Per-executor "available" is true when an executor has a
        configured image and CLI. Image *presence* on the daemon is not
        verified here (it can race with image builds); ``run_task`` is
        the authoritative point at which a missing image surfaces as
        :class:`CodingAdapterUnavailable`.
        """
        ready = False
        detail = "runtime unreachable"
        try:
            ready = bool(self._runtime.health())
            detail = "ok" if ready else "runtime unreachable"
        except ContainerRuntimeUnavailable as exc:
            detail = f"runtime unavailable: {exc}"
        except Exception as exc:
            detail = f"runtime probe failed: {exc}"
        return ExecutorHealthStatus(
            ready=ready,
            executors=self.list_executors(),
            detail=detail,
        )

    def list_executors(self) -> tuple[ExecutorInfo, ...]:
        """Return capability info for each configured executor."""
        infos: list[ExecutorInfo] = []
        for executor_id, exec_settings in self._settings.executors.items():
            available = bool(exec_settings.cli)
            infos.append(ExecutorInfo(id=executor_id, version="", available=available))
        return tuple(infos)

    def resolve_workspace_host_path(self, *, workspace_path: str) -> str | None:
        """Translate a workspace container path to the bind source on the host."""
        try:
            return self._runtime.host_path_for(container_path=workspace_path)
        except ContainerRuntimeUnavailable as exc:
            raise CodingAdapterUnavailable(str(exc)) from exc

    def run_task(self, *, spec: CodingTaskSpec) -> CodingTaskHandle:
        """Launch the task in a sibling container and return its handle."""
        exec_settings = self._executor_settings(spec.executor)
        container_spec = self._build_container_spec(
            spec=spec, exec_settings=exec_settings
        )
        try:
            container_handle = self._runtime.launch(spec=container_spec)
        except ContainerRuntimeUnavailable as exc:
            raise CodingAdapterUnavailable(str(exc)) from exc
        except ContainerLaunchError as exc:
            raise CodingTaskRuntimeError(str(exc)) from exc
        except ContainerRuntimeError as exc:
            raise CodingTaskRuntimeError(str(exc)) from exc

        handle_id = uuid4().hex
        record = _RuntimeRecord(
            spec=spec,
            container_handle=container_handle,
            owner=self._owner_id,
        )
        self._handles[handle_id] = record
        return CodingTaskHandle(
            handle_id=handle_id,
            task_id=spec.task_id,
            container_id=container_handle.container_id,
            started_at=container_handle.started_at,
        )

    def poll(self, *, handle: CodingTaskHandle) -> CodingTaskStatusSnapshot:
        """Inspect current task phase via the runtime."""
        record = self._record(handle=handle)
        try:
            status = self._runtime.status(handle=record.container_handle)
        except ContainerNotFoundError as exc:
            raise CodingTaskNotFoundError(str(exc)) from exc
        except ContainerRuntimeError as exc:
            raise CodingTaskRuntimeError(str(exc)) from exc

        phase = self._task_phase_for(
            container_phase=status.phase,
            exit_code=status.exit_code,
            elapsed_seconds=self._elapsed_seconds(record=record),
            spec=record.spec,
            cancelled=record.cancelled,
        )
        return CodingTaskStatusSnapshot(
            handle_id=handle.handle_id,
            phase=phase,
            last_observed_at=status.observed_at,
            exit_code=status.exit_code,
        )

    def cancel(self, *, handle: CodingTaskHandle) -> None:
        """Idempotently signal the runtime to stop the underlying container."""
        record = self._record(handle=handle)
        record.cancelled = True
        try:
            self._runtime.stop(handle=record.container_handle)
        except ContainerNotFoundError as exc:
            raise CodingTaskNotFoundError(str(exc)) from exc
        except ContainerRuntimeError as exc:
            raise CodingTaskRuntimeError(str(exc)) from exc

    def logs(self, *, handle: CodingTaskHandle) -> CodingTaskLogs:
        """Read captured stdout / stderr without reaping the container."""
        record = self._record(handle=handle)
        try:
            container_logs = self._runtime.logs(handle=record.container_handle)
        except ContainerNotFoundError as exc:
            raise CodingTaskNotFoundError(str(exc)) from exc
        except ContainerRuntimeError as exc:
            raise CodingTaskRuntimeError(str(exc)) from exc
        return CodingTaskLogs(
            handle_id=handle.handle_id,
            stdout=container_logs.stdout,
            stderr=container_logs.stderr,
        )

    def collect(self, *, handle: CodingTaskHandle) -> CodingTaskResult:
        """Drain final result, reap the container, and forget the handle."""
        record = self._record(handle=handle)
        try:
            status = self._runtime.status(handle=record.container_handle)
        except ContainerNotFoundError as exc:
            raise CodingTaskNotFoundError(str(exc)) from exc
        except ContainerRuntimeError as exc:
            raise CodingTaskRuntimeError(str(exc)) from exc

        elapsed = self._elapsed_seconds(record=record)
        phase = self._task_phase_for(
            container_phase=status.phase,
            exit_code=status.exit_code,
            elapsed_seconds=elapsed,
            spec=record.spec,
            cancelled=record.cancelled,
        )
        termination = self._termination_reason_for(
            phase=phase,
            exit_code=status.exit_code,
            elapsed_seconds=elapsed,
            spec=record.spec,
        )

        try:
            self._runtime.remove(handle=record.container_handle)
        except ContainerRuntimeError as exc:
            raise CodingTaskRuntimeError(str(exc)) from exc

        del self._handles[handle.handle_id]
        return CodingTaskResult(
            handle_id=handle.handle_id,
            task_id=record.task_id,
            phase=phase,
            exit_code=status.exit_code,
            elapsed_seconds=elapsed,
            termination_reason=termination,
        )

    def list_owned(self) -> tuple[CodingTaskHandle, ...]:
        """Enumerate live handles owned by this Adapter instance.

        Resurfaces both in-memory handles and any stragglers labeled with
        this adapter's ``owner_id`` so the Software Service supervisor
        can reap orphans on Brain Core startup. Orphan handles are
        reconstructed deterministically from the container's
        ``brain.coding.task_id`` label so re-listing yields stable ids.
        """
        owned: dict[str, CodingTaskHandle] = {}
        for handle_id, record in self._handles.items():
            owned[record.container_handle.container_id] = CodingTaskHandle(
                handle_id=handle_id,
                task_id=record.task_id,
                container_id=record.container_handle.container_id,
                started_at=record.started_at,
            )
        owner_label = f"{LABEL_OWNER}={self._owner_id}"
        try:
            container_handles = self._runtime.list_owned(owner_label=owner_label)
        except ContainerRuntimeUnavailable as exc:
            raise CodingAdapterUnavailable(str(exc)) from exc
        except ContainerRuntimeError as exc:
            raise CodingTaskRuntimeError(str(exc)) from exc
        for ch in container_handles:
            if ch.container_id in owned:
                continue
            orphan = self._handle_for_orphan(container_handle=ch)
            if orphan is None:
                # No `brain.coding.task_id` label — we can't tie this
                # container back to a Service-side lineage row, so refuse
                # to fabricate one. The orphan is logged at the runtime
                # layer; let the operator reap it manually.
                continue
            owned[ch.container_id] = orphan
        return tuple(owned.values())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _executor_settings(self, executor: ExecutorId) -> CodingExecutorSettings:
        """Resolve the catalog entry for ``executor`` or raise."""
        exec_settings = self._settings.executors.get(executor)
        if exec_settings is None:
            raise CodingAdapterUnavailable(
                f"executor {executor.value!r} is not configured"
            )
        return exec_settings

    def _resolve_image_tag(self, *, spec: CodingTaskSpec) -> str:
        """Pick the image tag for a task, building per-workspace layers on demand.

        Returns the configured ``base_image`` when the workspace has no
        customization script, or ``<workspace_image_repo>:<slug>`` when
        it does. The per-workspace tag is built lazily via the
        :class:`ImageBuilder` and rebuilt when the install script's mtime
        is newer than the existing image's creation timestamp.
        """
        script_path = self._workspace_install_script_path(
            relative_path=spec.workspace_relative_path
        )
        if script_path is None:
            return self._settings.base_image
        slug = self._workspace_image_slug(relative_path=spec.workspace_relative_path)
        tag = f"{self._settings.workspace_image_repo}:{slug}"
        try:
            existing = self._image_builder.image_created_at(tag=tag)
        except ImageBuilderUnavailable as exc:
            raise CodingAdapterUnavailable(str(exc)) from exc

        script_mtime = datetime.fromtimestamp(script_path.stat().st_mtime, tz=UTC)
        if existing is None or existing < script_mtime:
            try:
                self._image_builder.build_workspace_image(
                    tag=tag,
                    base_image=self._settings.base_image,
                    install_script_path=script_path,
                )
            except ImageBuildFailed as exc:
                raise CodingTaskRuntimeError(str(exc)) from exc
            except ImageBuilderUnavailable as exc:
                raise CodingAdapterUnavailable(str(exc)) from exc
        return tag

    def _workspace_install_script_path(self, *, relative_path: str) -> Path | None:
        """Return the operator-supplied install script path, or ``None`` when absent."""
        root = Path(self._settings.workspace_image_root).expanduser()
        candidate = root / f"{relative_path}.sh"
        return candidate if candidate.is_file() else None

    @staticmethod
    def _workspace_image_slug(*, relative_path: str) -> str:
        """Convert a workspace relative path into a Docker-tag-safe slug.

        Docker tag rules disallow ``/``; we substitute ``_``. The Adapter
        is the only consumer, so collisions only matter within one
        operator's catalog (e.g. ``repo/brain`` vs ``repo_brain``); both
        slugify to ``repo_brain`` and would conflict. Per the operator
        convention documented in install.md, the workspace tree under
        ``software.workspace_root`` should not contain colliding leaf
        names.
        """
        return relative_path.replace("/", "_")

    def _build_container_spec(
        self,
        *,
        spec: CodingTaskSpec,
        exec_settings: CodingExecutorSettings,
    ) -> ContainerSpec:
        """Materialise a :class:`CodingTaskSpec` into a :class:`ContainerSpec`."""
        try:
            command = shape_command(
                executor=spec.executor,
                cli=exec_settings.cli,
                prompt=spec.prompt,
            )
        except UnknownExecutorError as exc:
            raise CodingAdapterUnavailable(str(exc)) from exc

        image_tag = self._resolve_image_tag(spec=spec)

        labels = {
            LABEL_TASK_ID: spec.task_id,
            LABEL_OWNER: self._owner_id,
            LABEL_EXECUTOR: spec.executor.value,
            **dict(spec.labels),
        }

        # Strict allowlist: empty allowlist passes zero env vars (default-deny).
        # Values are sourced from this Adapter's process env (operator-supplied
        # via Compose) so secrets never traverse the spec or the lineage row.
        env = {
            key: self._env_source[key]
            for key in exec_settings.env_keys
            if key in self._env_source
        }

        # Two bind mounts:
        # 1. Worktree at WORKTREE_MOUNT_TARGET so the executor's CWD is the
        #    task's isolated working tree.
        # 2. Workspace at its registered virtual path so the worktree's
        #    `.git` link resolves to the parent repo's metadata. The host
        #    source is resolved fresh from brain-core's own bind-mount
        #    table — Docker is the source of truth for the live mount, so
        #    we don't persist a stale copy on the workspace row.
        try:
            workspace_host_source = self._runtime.host_path_for(
                container_path=spec.workspace_path
            )
        except ContainerRuntimeUnavailable as exc:
            raise CodingAdapterUnavailable(str(exc)) from exc
        if workspace_host_source is None:
            raise CodingAdapterUnavailable(
                f"workspace path {spec.workspace_path} is not covered by a "
                "bind mount in brain-core's container; the host Docker "
                "daemon would have nothing to mount into the task container"
            )
        mounts = (
            Mount(source=spec.worktree_path, target=WORKTREE_MOUNT_TARGET),
            Mount(source=workspace_host_source, target=spec.workspace_path),
        )

        stop_timeout = max(
            _MIN_STOP_TIMEOUT_SECONDS,
            min(spec.max_wallclock_seconds, self._settings.stop_timeout_seconds_max),
        )
        return ContainerSpec(
            image=image_tag,
            command=command,
            env=env,
            mounts=mounts,
            labels=labels,
            workdir=WORKTREE_MOUNT_TARGET,
            stop_timeout_seconds=stop_timeout,
        )

    def _record(self, *, handle: CodingTaskHandle) -> _RuntimeRecord:
        """Resolve the bookkeeping record for ``handle`` or raise."""
        record = self._handles.get(handle.handle_id)
        if record is None:
            raise CodingTaskNotFoundError(f"unknown handle: {handle.handle_id}")
        return record

    def _elapsed_seconds(self, *, record: _RuntimeRecord) -> float:
        """Wallclock seconds since launch."""
        delta = self._now() - record.started_at
        return max(delta.total_seconds(), 0.0)

    def _handle_for_orphan(
        self, *, container_handle: ContainerHandle
    ) -> CodingTaskHandle | None:
        """Synthesize a stable handle for an orphan container, or skip it.

        The container was labeled by an earlier instance of *this* Adapter,
        so ``brain.coding.task_id`` is authoritative; ``handle_id`` is
        derived deterministically from it so repeat sweeps converge.
        Returns ``None`` when the label is missing — synthesizing a
        non-ULID ``task_id`` from the container id would feed downstream
        code (lineage rows, repository writes) a value they can't accept.
        """
        task_id = container_handle.labels.get(LABEL_TASK_ID)
        if not task_id:
            return None
        return CodingTaskHandle(
            handle_id=f"{_REATTACHED_HANDLE_PREFIX}{task_id}",
            task_id=task_id,
            container_id=container_handle.container_id,
            started_at=container_handle.started_at,
        )

    def _task_phase_for(
        self,
        *,
        container_phase: ContainerPhase,
        exit_code: int | None,
        elapsed_seconds: float,
        spec: CodingTaskSpec,
        cancelled: bool,
    ) -> TaskPhase:
        """Project a container phase onto the task phase domain."""
        if container_phase is ContainerPhase.CREATED:
            return TaskPhase.PENDING
        if container_phase is ContainerPhase.RUNNING:
            if elapsed_seconds > spec.max_wallclock_seconds:
                return TaskPhase.FAILED
            return TaskPhase.RUNNING
        if container_phase is ContainerPhase.EXITED:
            if cancelled:
                return TaskPhase.CANCELLED
            if exit_code == 0:
                return TaskPhase.SUCCEEDED
            return TaskPhase.FAILED
        return TaskPhase.FAILED

    def _termination_reason_for(
        self,
        *,
        phase: TaskPhase,
        exit_code: int | None,
        elapsed_seconds: float,
        spec: CodingTaskSpec,
    ) -> TerminationReason:
        """Pick the termination reason recorded on the final result."""
        if phase is TaskPhase.SUCCEEDED:
            return TerminationReason.EXECUTOR_EXITED
        if phase is TaskPhase.CANCELLED:
            return TerminationReason.CANCELLED
        if elapsed_seconds > spec.max_wallclock_seconds:
            return TerminationReason.TIMEOUT
        if exit_code is None:
            return TerminationReason.RUNTIME_ERROR
        return TerminationReason.EXECUTOR_EXITED
