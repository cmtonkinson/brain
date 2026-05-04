"""Unit tests for the Docker-backed CodingAdapter.

Exercises adapter logic against an in-memory fake :class:`ContainerRuntime`
so the suite runs deterministically without requiring a Docker daemon.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from resources.adapters.coding.adapter import (
    CodingAdapterUnavailable,
    CodingTaskHandle,
    CodingTaskNotFoundError,
    CodingTaskRuntimeError,
    CodingTaskSpec,
    ExecutorId,
    TaskPhase,
    TerminationReason,
)
from resources.adapters.coding.config import (
    CodingAdapterSettings,
    CodingExecutorSettings,
)
from resources.adapters.coding.docker_coding_adapter import (
    LABEL_EXECUTOR,
    LABEL_OWNER,
    LABEL_TASK_ID,
    DockerCodingAdapter,
)
from resources.adapters.coding.runtime import (
    ContainerHandle,
    ContainerLaunchError,
    ContainerLogs,
    ContainerNotFoundError,
    ContainerPhase,
    ContainerRuntime,
    ContainerRuntimeUnavailable,
    ContainerSpec,
    ContainerStatus,
)


def _now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class FakeRuntime(ContainerRuntime):
    """In-memory :class:`ContainerRuntime` for unit tests.

    Records launches in ``self.launched`` and supports scripted phase
    transitions (``self.phases`` keyed by container_id).
    """

    def __init__(self) -> None:
        self.launched: list[ContainerSpec] = []
        self.containers: dict[str, ContainerSpec] = {}
        self.phases: dict[str, ContainerPhase] = {}
        self.exit_codes: dict[str, int | None] = {}
        self.stopped: list[str] = []
        self.removed: list[str] = []
        self.healthy: bool = True
        self.launch_error: Exception | None = None
        self.owned: list[ContainerHandle] = []
        # Maps container path → host bind source. Default covers the test
        # workspace_path used in _make_spec; tests can override or clear.
        self.host_paths: dict[str, str | None] = {
            "/mount/software/repo/test": "/Users/chris/repo/test",
        }
        self.host_path_error: Exception | None = None
        self._next_id: int = 0

    def health(self) -> bool:
        """Mock health probe."""
        return self.healthy

    def launch(self, *, spec: ContainerSpec) -> ContainerHandle:
        """Record the launch and return a synthetic handle."""
        if self.launch_error is not None:
            raise self.launch_error
        self._next_id += 1
        cid = f"c{self._next_id:04d}"
        self.launched.append(spec)
        self.containers[cid] = spec
        self.phases[cid] = ContainerPhase.RUNNING
        self.exit_codes[cid] = None
        return ContainerHandle(
            container_id=cid, started_at=_now(), labels=dict(spec.labels)
        )

    def status(self, *, handle: ContainerHandle) -> ContainerStatus:
        """Return the scripted phase for the given container."""
        if handle.container_id not in self.containers:
            raise ContainerNotFoundError(handle.container_id)
        return ContainerStatus(
            container_id=handle.container_id,
            phase=self.phases.get(handle.container_id, ContainerPhase.UNKNOWN),
            exit_code=self.exit_codes.get(handle.container_id),
            observed_at=_now(),
        )

    def stop(self, *, handle: ContainerHandle) -> None:
        """Mark the container stopped and transition to EXITED."""
        if handle.container_id not in self.containers:
            raise ContainerNotFoundError(handle.container_id)
        self.stopped.append(handle.container_id)
        self.phases[handle.container_id] = ContainerPhase.EXITED
        self.exit_codes.setdefault(handle.container_id, 137)

    def logs(self, *, handle: ContainerHandle) -> ContainerLogs:
        """Return empty logs for tests."""
        if handle.container_id not in self.containers:
            raise ContainerNotFoundError(handle.container_id)
        return ContainerLogs(stdout=b"", stderr=b"")

    def remove(self, *, handle: ContainerHandle) -> None:
        """Drop the container from the in-memory state."""
        self.removed.append(handle.container_id)
        self.containers.pop(handle.container_id, None)

    def list_owned(self, *, owner_label: str) -> tuple[ContainerHandle, ...]:
        """Return any pre-seeded owned handles regardless of label string."""
        del owner_label
        return tuple(self.owned)

    def host_path_for(self, *, container_path: str) -> str | None:
        """Return the configured host source for ``container_path``.

        Defaults are seeded so the canonical ``_make_spec`` workspace
        resolves; tests that need to exercise the "no bind mount" branch
        clear the entry, and tests that need the unavailable branch set
        ``self.host_path_error``.
        """
        if self.host_path_error is not None:
            raise self.host_path_error
        return self.host_paths.get(container_path)


@pytest.fixture()
def settings(tmp_path) -> CodingAdapterSettings:
    """A small executor catalog covering claude_code and codex.

    ``workspace_image_root`` points at an empty subdir of ``tmp_path``;
    individual tests drop a script there to exercise the per-workspace
    image-build path.
    """
    return CodingAdapterSettings(
        workspace_image_root=str(tmp_path / "coding_images"),
        executors={
            ExecutorId.CLAUDE_CODE: CodingExecutorSettings(
                cli="claude",
                env_keys=("ANTHROPIC_API_KEY",),
            ),
            ExecutorId.CODEX: CodingExecutorSettings(
                cli="codex",
                env_keys=("OPENAI_API_KEY",),
            ),
        },
    )


@pytest.fixture()
def runtime() -> FakeRuntime:
    """A fresh fake runtime per test."""
    return FakeRuntime()


class FakeImageBuilder:
    """In-memory ImageBuilder for tests; records calls, configurable presence."""

    def __init__(self) -> None:
        self.created_at: dict[str, datetime | None] = {}
        self.builds: list[tuple[str, str, Path]] = []
        self.unavailable = False
        self.build_failure: Exception | None = None

    def image_created_at(self, *, tag: str) -> datetime | None:
        if self.unavailable:
            from resources.adapters.coding.image_builder import (
                ImageBuilderUnavailable,
            )

            raise ImageBuilderUnavailable("test-induced unavailable")
        return self.created_at.get(tag)

    def build_workspace_image(
        self, *, tag: str, base_image: str, install_script_path: Path
    ) -> None:
        if self.build_failure is not None:
            raise self.build_failure
        self.builds.append((tag, base_image, install_script_path))
        # Mark the tag as "now present" so subsequent resolves see it.
        from datetime import UTC

        self.created_at[tag] = datetime.now(UTC)


@pytest.fixture()
def image_builder() -> FakeImageBuilder:
    return FakeImageBuilder()


@pytest.fixture()
def adapter(
    settings: CodingAdapterSettings,
    runtime: FakeRuntime,
    image_builder: FakeImageBuilder,
) -> DockerCodingAdapter:
    """Adapter wired against the fake runtime and image builder."""
    return DockerCodingAdapter(
        settings=settings,
        runtime=runtime,
        image_builder=image_builder,
        owner_id="brain-core@test",
        env_source={},
    )


def _make_spec(
    *,
    executor: ExecutorId = ExecutorId.CLAUDE_CODE,
    task_id: str = "task-001",
    prompt: str = "Add a docstring",
    max_wallclock_seconds: int = 60,
    workspace_relative_path: str = "repo/test",
) -> CodingTaskSpec:
    """Build a CodingTaskSpec with sane defaults for tests."""
    return CodingTaskSpec(
        task_id=task_id,
        executor=executor,
        worktree_path="/tmp/work",
        workspace_path="/mount/software/repo/test",
        workspace_relative_path=workspace_relative_path,
        prompt=prompt,
        max_wallclock_seconds=max_wallclock_seconds,
    )


class TestRunTask:
    """run_task() materialises specs into container launches."""

    def test_launches_with_base_image_when_no_workspace_script(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        """Workspaces without a customization script spawn from `:base`."""
        spec = _make_spec()
        handle = adapter.run_task(spec=spec)
        assert handle.task_id == "task-001"
        assert len(runtime.launched) == 1
        launched = runtime.launched[0]
        assert launched.image == "brain/coding-runtime:base"
        assert launched.command == ("claude", "-p", "Add a docstring")

    def test_applies_brain_owned_labels(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        adapter.run_task(spec=_make_spec(task_id="task-xyz"))
        labels = runtime.launched[0].labels
        assert labels[LABEL_TASK_ID] == "task-xyz"
        assert labels[LABEL_OWNER] == "brain-core@test"
        assert labels[LABEL_EXECUTOR] == ExecutorId.CLAUDE_CODE.value

    def test_mounts_worktree_and_workspace(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        adapter.run_task(spec=_make_spec())
        mounts = runtime.launched[0].mounts
        assert len(mounts) == 2
        # Worktree at the canonical /work mount.
        assert mounts[0].source == "/tmp/work"
        assert mounts[0].target == "/work"
        assert mounts[0].read_only is False
        # Workspace source is resolved fresh via runtime.host_path_for so the
        # task container sees the workspace at the same absolute path
        # brain-core does and the worktree's `.git` link resolves.
        assert mounts[1].source == "/Users/chris/repo/test"
        assert mounts[1].target == "/mount/software/repo/test"
        assert mounts[1].read_only is False
        assert runtime.launched[0].workdir == "/work"

    def test_workspace_without_bind_mount_raises_unavailable(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        """If brain-core has no bind mount covering the workspace, refuse."""
        runtime.host_paths.clear()
        with pytest.raises(CodingAdapterUnavailable):
            adapter.run_task(spec=_make_spec())

    def test_runtime_unavailable_during_host_path_lookup_translates(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        """Daemon unavailable during host-path resolution surfaces as adapter unavailable."""
        runtime.host_path_error = ContainerRuntimeUnavailable("daemon down")
        with pytest.raises(CodingAdapterUnavailable):
            adapter.run_task(spec=_make_spec())

    def test_filters_env_to_allowlisted_keys(
        self,
        settings: CodingAdapterSettings,
        runtime: FakeRuntime,
        image_builder: FakeImageBuilder,
    ) -> None:
        """env_source values matching env_keys are forwarded; everything else is dropped."""
        adapter = DockerCodingAdapter(
            settings=settings,
            runtime=runtime,
            image_builder=image_builder,
            owner_id="brain-core@test",
            env_source={
                "ANTHROPIC_API_KEY": "sk-test",
                "SOMETHING_ELSE": "not allowed",
            },
        )
        adapter.run_task(spec=_make_spec())
        env = runtime.launched[0].env
        assert env == {"ANTHROPIC_API_KEY": "sk-test"}

    def test_missing_env_key_in_source_is_skipped(
        self,
        settings: CodingAdapterSettings,
        runtime: FakeRuntime,
        image_builder: FakeImageBuilder,
    ) -> None:
        """Allowlisted keys absent from env_source are silently skipped."""
        adapter = DockerCodingAdapter(
            settings=settings,
            runtime=runtime,
            image_builder=image_builder,
            owner_id="brain-core@test",
            env_source={},
        )
        adapter.run_task(spec=_make_spec())
        assert runtime.launched[0].env == {}

    def test_empty_env_allowlist_is_default_deny(
        self,
        runtime: FakeRuntime,
        image_builder: FakeImageBuilder,
        tmp_path,
    ) -> None:
        """An executor with no ``env_keys`` must receive zero env vars."""
        deny_settings = CodingAdapterSettings(
            workspace_image_root=str(tmp_path / "coding_images"),
            executors={
                ExecutorId.CLAUDE_CODE: CodingExecutorSettings(
                    cli="claude",
                    env_keys=(),
                ),
            },
        )
        adapter = DockerCodingAdapter(
            settings=deny_settings,
            runtime=runtime,
            image_builder=image_builder,
            owner_id="brain-core@test",
            env_source={"ANTHROPIC_API_KEY": "sk-test", "OTHER": "v"},
        )
        adapter.run_task(spec=_make_spec())
        assert runtime.launched[0].env == {}

    def test_unknown_executor_raises_unavailable(
        self,
        settings: CodingAdapterSettings,
        runtime: FakeRuntime,
        image_builder: FakeImageBuilder,
    ) -> None:
        adapter = DockerCodingAdapter(
            settings=settings,
            runtime=runtime,
            image_builder=image_builder,
            owner_id="brain-core@test",
        )
        with pytest.raises(CodingAdapterUnavailable):
            adapter.run_task(spec=_make_spec(executor=ExecutorId.OPENCODE))


class TestImageResolution:
    """Per-workspace image build orchestration."""

    def _drop_script(
        self, *, settings: CodingAdapterSettings, relative: str, content: str = "exit 0"
    ) -> Path:
        path = Path(settings.workspace_image_root).expanduser() / f"{relative}.sh"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_no_script_uses_base_image_no_build_call(
        self,
        adapter: DockerCodingAdapter,
        runtime: FakeRuntime,
        image_builder: FakeImageBuilder,
    ) -> None:
        adapter.run_task(spec=_make_spec(workspace_relative_path="repo/test"))
        assert runtime.launched[0].image == "brain/coding-runtime:base"
        assert image_builder.builds == []

    def test_script_present_builds_layer_then_uses_workspace_tag(
        self,
        adapter: DockerCodingAdapter,
        runtime: FakeRuntime,
        image_builder: FakeImageBuilder,
        settings: CodingAdapterSettings,
    ) -> None:
        script = self._drop_script(settings=settings, relative="repo/brain")
        adapter.run_task(spec=_make_spec(workspace_relative_path="repo/brain"))
        assert runtime.launched[0].image == "brain/coding-runtime:repo_brain"
        assert image_builder.builds == [
            ("brain/coding-runtime:repo_brain", "brain/coding-runtime:base", script)
        ]

    def test_existing_fresh_image_skips_build(
        self,
        adapter: DockerCodingAdapter,
        runtime: FakeRuntime,
        image_builder: FakeImageBuilder,
        settings: CodingAdapterSettings,
    ) -> None:
        self._drop_script(settings=settings, relative="repo/brain")
        # Pretend the image already exists and was built after the script's mtime.
        image_builder.created_at["brain/coding-runtime:repo_brain"] = (
            _now() + timedelta(hours=1)
        )
        adapter.run_task(spec=_make_spec(workspace_relative_path="repo/brain"))
        assert image_builder.builds == []
        assert runtime.launched[0].image == "brain/coding-runtime:repo_brain"

    def test_stale_image_triggers_rebuild(
        self,
        adapter: DockerCodingAdapter,
        runtime: FakeRuntime,
        image_builder: FakeImageBuilder,
        settings: CodingAdapterSettings,
    ) -> None:
        self._drop_script(settings=settings, relative="repo/brain")
        # Pretend the image existed but predates the script: must rebuild.
        image_builder.created_at["brain/coding-runtime:repo_brain"] = (
            _now() - timedelta(days=1)
        )
        adapter.run_task(spec=_make_spec(workspace_relative_path="repo/brain"))
        assert len(image_builder.builds) == 1

    def test_build_failure_translates_to_task_runtime_error(
        self,
        adapter: DockerCodingAdapter,
        image_builder: FakeImageBuilder,
        settings: CodingAdapterSettings,
    ) -> None:
        from resources.adapters.coding.image_builder import ImageBuildFailed

        self._drop_script(settings=settings, relative="repo/brain")
        image_builder.build_failure = ImageBuildFailed(
            tag="brain/coding-runtime:repo_brain",
            build_output="apt-get: command not found",
        )
        with pytest.raises(CodingTaskRuntimeError):
            adapter.run_task(spec=_make_spec(workspace_relative_path="repo/brain"))

    def test_builder_unavailable_translates_to_adapter_unavailable(
        self,
        adapter: DockerCodingAdapter,
        image_builder: FakeImageBuilder,
        settings: CodingAdapterSettings,
    ) -> None:
        self._drop_script(settings=settings, relative="repo/brain")
        image_builder.unavailable = True
        with pytest.raises(CodingAdapterUnavailable):
            adapter.run_task(spec=_make_spec(workspace_relative_path="repo/brain"))

    def test_runtime_unavailable_translates_to_adapter_unavailable(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        runtime.launch_error = ContainerRuntimeUnavailable("daemon down")
        with pytest.raises(CodingAdapterUnavailable):
            adapter.run_task(spec=_make_spec())

    def test_launch_error_translates_to_task_runtime_error(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        runtime.launch_error = ContainerLaunchError("image missing")
        with pytest.raises(CodingTaskRuntimeError):
            adapter.run_task(spec=_make_spec())


class TestPoll:
    """poll() projects container phases onto task phases."""

    def test_running_when_container_running(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        handle = adapter.run_task(spec=_make_spec())
        snap = adapter.poll(handle=handle)
        assert snap.phase is TaskPhase.RUNNING
        assert snap.exit_code is None

    def test_succeeded_on_zero_exit(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        handle = adapter.run_task(spec=_make_spec())
        runtime.phases[handle.container_id] = ContainerPhase.EXITED
        runtime.exit_codes[handle.container_id] = 0
        snap = adapter.poll(handle=handle)
        assert snap.phase is TaskPhase.SUCCEEDED
        assert snap.exit_code == 0

    def test_failed_on_nonzero_exit(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        handle = adapter.run_task(spec=_make_spec())
        runtime.phases[handle.container_id] = ContainerPhase.EXITED
        runtime.exit_codes[handle.container_id] = 17
        snap = adapter.poll(handle=handle)
        assert snap.phase is TaskPhase.FAILED
        assert snap.exit_code == 17


@pytest.mark.parametrize(
    "method",
    ["poll", "cancel", "collect"],
)
def test_unknown_handle_raises(adapter: DockerCodingAdapter, method: str) -> None:
    """Each lifecycle method must reject unknown handles uniformly."""
    bogus = CodingTaskHandle(
        handle_id="nope",
        task_id="t",
        container_id="c",
        started_at=_now(),
    )
    with pytest.raises(CodingTaskNotFoundError):
        getattr(adapter, method)(handle=bogus)


class TestCancel:
    """cancel() requests termination via the runtime."""

    def test_idempotent_stop(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        """A second cancel on an already-EXITED container must complete cleanly."""
        handle = adapter.run_task(spec=_make_spec())
        adapter.cancel(handle=handle)
        # After cancel the FakeRuntime has flipped the container to EXITED;
        # the second cancel must not raise even though stop() is sent again.
        adapter.cancel(handle=handle)

    def test_marks_record_cancelled_so_phase_resolves_to_cancelled(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        """After cancel, polling an EXITED container reports CANCELLED."""
        handle = adapter.run_task(spec=_make_spec())
        adapter.cancel(handle=handle)
        runtime.phases[handle.container_id] = ContainerPhase.EXITED
        runtime.exit_codes[handle.container_id] = 137
        snap = adapter.poll(handle=handle)
        assert snap.phase is TaskPhase.CANCELLED


class TestCollect:
    """collect() drains and reaps the container."""

    def test_returns_terminal_result_and_removes_container(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        handle = adapter.run_task(spec=_make_spec())
        runtime.phases[handle.container_id] = ContainerPhase.EXITED
        runtime.exit_codes[handle.container_id] = 0
        result = adapter.collect(handle=handle)
        assert result.phase is TaskPhase.SUCCEEDED
        assert result.termination_reason is TerminationReason.EXECUTOR_EXITED
        assert handle.container_id in runtime.removed

    def test_repeated_collect_raises(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        handle = adapter.run_task(spec=_make_spec())
        runtime.phases[handle.container_id] = ContainerPhase.EXITED
        runtime.exit_codes[handle.container_id] = 0
        adapter.collect(handle=handle)
        with pytest.raises(CodingTaskNotFoundError):
            adapter.collect(handle=handle)

    def test_cancel_collect_reports_cancelled(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        """Cancel-then-collect surfaces CANCELLED phase + reason."""
        handle = adapter.run_task(spec=_make_spec())
        adapter.cancel(handle=handle)
        runtime.phases[handle.container_id] = ContainerPhase.EXITED
        runtime.exit_codes[handle.container_id] = 137
        result = adapter.collect(handle=handle)
        assert result.phase is TaskPhase.CANCELLED
        assert result.termination_reason is TerminationReason.CANCELLED

    def test_timeout_termination_reason(
        self,
        settings: CodingAdapterSettings,
        runtime: FakeRuntime,
        image_builder: FakeImageBuilder,
    ) -> None:
        """Inject a future clock so elapsed time exceeds max_wallclock."""
        spec = _make_spec(max_wallclock_seconds=1)
        future = _now() + timedelta(seconds=10)
        adapter = DockerCodingAdapter(
            settings=settings,
            runtime=runtime,
            image_builder=image_builder,
            owner_id="brain-core@test",
            now_func=lambda: future,
        )
        handle = adapter.run_task(spec=spec)
        runtime.phases[handle.container_id] = ContainerPhase.EXITED
        runtime.exit_codes[handle.container_id] = 124
        result = adapter.collect(handle=handle)
        assert result.termination_reason is TerminationReason.TIMEOUT


class TestLogs:
    """logs() reads captured stdout/stderr without reaping the container."""

    def test_returns_runtime_logs(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        """Adapter forwards the runtime's captured bytes."""

        def _scripted_logs(*, handle: ContainerHandle) -> ContainerLogs:
            return ContainerLogs(stdout=b"hello\n", stderr=b"warn\n")

        runtime.logs = _scripted_logs  # type: ignore[method-assign]
        handle = adapter.run_task(spec=_make_spec())
        captured = adapter.logs(handle=handle)
        assert captured.handle_id == handle.handle_id
        assert captured.stdout == b"hello\n"
        assert captured.stderr == b"warn\n"
        # Container is still in place — collect has not been called yet.
        assert handle.container_id not in runtime.removed

    def test_unknown_handle_raises_not_found(
        self, adapter: DockerCodingAdapter
    ) -> None:
        synthetic = CodingTaskHandle(
            handle_id="never-issued",
            task_id="task-x",
            container_id="cZZ",
            started_at=_now(),
        )
        with pytest.raises(CodingTaskNotFoundError):
            adapter.logs(handle=synthetic)


class TestHealth:
    """health() composes runtime probe with executor catalog."""

    def test_ready_when_runtime_healthy(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        runtime.healthy = True
        status = adapter.health()
        assert status.ready is True
        assert {info.id for info in status.executors} == {
            ExecutorId.CLAUDE_CODE,
            ExecutorId.CODEX,
        }

    def test_not_ready_when_runtime_unhealthy(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        runtime.healthy = False
        status = adapter.health()
        assert status.ready is False


class TestListOwned:
    """list_owned() merges in-memory handles with runtime-side orphans."""

    def test_returns_in_memory_handles(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        handle = adapter.run_task(spec=_make_spec(task_id="alive"))
        owned = adapter.list_owned()
        assert any(h.handle_id == handle.handle_id for h in owned)

    def test_orphans_use_label_task_id_and_deterministic_handle_id(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        """An orphan handle is rebuilt from the container's task label,
        and its handle_id is stable across re-listings."""
        runtime.owned = [
            ContainerHandle(
                container_id="orphan-1",
                started_at=_now(),
                labels={"brain.coding.task_id": "task-orphan"},
            ),
        ]
        first = adapter.list_owned()
        second = adapter.list_owned()
        orphan_first = next(h for h in first if h.container_id == "orphan-1")
        orphan_second = next(h for h in second if h.container_id == "orphan-1")
        assert orphan_first.task_id == "task-orphan"
        assert orphan_first.handle_id == orphan_second.handle_id
        assert orphan_first.handle_id == "reattached-task-orphan"

    def test_runtime_unavailable_raises_adapter_unavailable(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        def boom(*, owner_label: str) -> tuple[ContainerHandle, ...]:
            del owner_label
            raise ContainerRuntimeUnavailable("daemon down")

        runtime.list_owned = boom  # type: ignore[method-assign]
        with pytest.raises(CodingAdapterUnavailable):
            adapter.list_owned()

    def test_orphans_without_task_id_label_are_skipped(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        """A container missing the brain.coding.task_id label cannot be
        tied to a Service-side row; refuse to fabricate one."""
        runtime.owned = [
            ContainerHandle(
                container_id="unlabeled-1",
                started_at=_now(),
                labels={},
            ),
        ]
        owned = adapter.list_owned()
        assert all(h.container_id != "unlabeled-1" for h in owned)


class TestListExecutors:
    """list_executors() reflects the configured catalog."""

    def test_marks_complete_entries_available(
        self, adapter: DockerCodingAdapter
    ) -> None:
        infos = adapter.list_executors()
        for info in infos:
            assert info.available is True


class TestResolveWorkspaceHostPath:
    """resolve_workspace_host_path() delegates to the runtime's bind table."""

    def test_returns_runtime_resolved_source(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        runtime.host_paths["/mount/software/repo/brain"] = "/Users/chris/repo/brain"
        result = adapter.resolve_workspace_host_path(
            workspace_path="/mount/software/repo/brain"
        )
        assert result == "/Users/chris/repo/brain"

    def test_returns_none_when_no_bind_covers_path(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        runtime.host_paths.clear()
        result = adapter.resolve_workspace_host_path(
            workspace_path="/mount/software/repo/brain"
        )
        assert result is None

    def test_runtime_unavailable_translates_to_adapter_unavailable(
        self, adapter: DockerCodingAdapter, runtime: FakeRuntime
    ) -> None:
        runtime.host_path_error = ContainerRuntimeUnavailable("daemon down")
        with pytest.raises(CodingAdapterUnavailable):
            adapter.resolve_workspace_host_path(
                workspace_path="/mount/software/repo/brain"
            )
