"""Unit tests for :class:`DockerContainerRuntime` against a faked SDK.

The runtime delegates to the ``docker`` Python SDK; here we inject a
:class:`FakeDockerClient` that mimics the surface DockerContainerRuntime
uses (containers, networks, ping). No Docker daemon is required.

The matching real-Docker integration test lives in
``test_docker_runtime_integration.py`` and is gated by
``BRAIN_RUN_INTEGRATION_REAL=1``.
"""

from __future__ import annotations

from typing import Any

import pytest

from resources.adapters.coding.docker_runtime import DockerContainerRuntime
from resources.adapters.coding.runtime import (
    ContainerLaunchError,
    ContainerNotFoundError,
    ContainerPhase,
    ContainerSpec,
    Mount,
)


class FakeContainer:
    """Minimal stand-in for ``docker.models.containers.Container``."""

    def __init__(self, *, id: str, attrs: dict[str, Any] | None = None) -> None:
        self.id = id
        self.attrs = attrs or {"State": {"Status": "running"}}
        self.removed = False
        self.stop_calls: list[int] = []

    def reload(self) -> None:
        """No-op refresh."""

    def stop(self, *, timeout: int) -> None:
        """Record the stop call and mark the container exited."""
        self.stop_calls.append(timeout)
        self.attrs.setdefault("State", {})["Status"] = "exited"
        self.attrs["State"]["ExitCode"] = 137

    def logs(
        self, *, stdout: bool = True, stderr: bool = True, stream: bool = False
    ) -> bytes:
        """Return a marker payload distinguishing stdout vs stderr."""
        del stream
        if stdout and not stderr:
            return b"stdout-bytes"
        if stderr and not stdout:
            return b"stderr-bytes"
        return b"both"

    def remove(self, *, force: bool = False) -> None:
        """Mark the container removed."""
        del force
        self.removed = True


class FakeContainersAPI:
    """Mimics ``client.containers``."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []
        self.containers: dict[str, FakeContainer] = {}
        self.run_error: Exception | None = None

    def run(self, **kwargs: Any) -> FakeContainer:
        """Capture the run kwargs and return a new fake container."""
        if self.run_error is not None:
            raise self.run_error
        self.runs.append(kwargs)
        cid = f"c{len(self.containers) + 1}"
        container = FakeContainer(id=cid)
        self.containers[cid] = container
        return container

    def get(self, container_id: str) -> FakeContainer:
        """Look up a container or raise the SDK NotFound."""
        if container_id not in self.containers:
            from docker.errors import NotFound  # noqa: PLC0415

            raise NotFound(container_id)
        return self.containers[container_id]

    def list(
        self, *, all: bool = False, filters: dict[str, str] | None = None
    ) -> list[FakeContainer]:
        """Capture filter kwargs and return all containers (no real filtering)."""
        self.list_calls.append({"all": all, "filters": filters})
        return list(self.containers.values())


class FakeNetworksAPI:
    """Mimics ``client.networks``."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.removed: list[str] = []
        self.networks: dict[str, FakeNetwork] = {}
        self.create_error: Exception | None = None

    def create(self, **kwargs: Any) -> "FakeNetwork":
        """Record the create call."""
        if self.create_error is not None:
            raise self.create_error
        self.created.append(kwargs)
        net = FakeNetwork(name=kwargs["name"], parent=self)
        self.networks[net.name] = net
        return net

    def get(self, name: str) -> "FakeNetwork":
        """Return a previously-created network or raise."""
        if name not in self.networks:
            raise KeyError(name)
        return self.networks[name]


class FakeNetwork:
    """Minimal network stand-in."""

    def __init__(self, *, name: str, parent: FakeNetworksAPI) -> None:
        self.name = name
        self._parent = parent

    def remove(self) -> None:
        """Drop this network from the parent registry."""
        self._parent.removed.append(self.name)
        self._parent.networks.pop(self.name, None)


class FakeDockerClient:
    """Top-level fake mimicking ``docker.DockerClient``."""

    def __init__(self) -> None:
        self.containers = FakeContainersAPI()
        self.networks = FakeNetworksAPI()
        self.ping_error: Exception | None = None

    def ping(self) -> bool:
        """Mock ping."""
        if self.ping_error is not None:
            raise self.ping_error
        return True


@pytest.fixture()
def fake_client() -> FakeDockerClient:
    """A fresh fake Docker client per test."""
    return FakeDockerClient()


@pytest.fixture()
def runtime(fake_client: FakeDockerClient) -> DockerContainerRuntime:
    """Runtime wired against the fake client."""
    return DockerContainerRuntime(client=fake_client)


def _spec(
    *,
    image: str = "brain/coding-runtime:claude",
    labels: dict[str, str] | None = None,
) -> ContainerSpec:
    """Construct a minimal ContainerSpec."""
    return ContainerSpec(
        image=image,
        command=("claude", "hello"),
        env={"FOO": "bar"},
        mounts=(Mount(source="/tmp/work", target="/work"),),
        labels=labels or {"brain.coding.task_id": "task-001"},
        workdir="/work",
        stop_timeout_seconds=15,
    )


class TestHealth:
    """health()."""

    def test_returns_true_when_ping_ok(self, runtime: DockerContainerRuntime) -> None:
        assert runtime.health() is True

    def test_returns_false_on_ping_error(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        fake_client.ping_error = RuntimeError("daemon down")
        assert runtime.health() is False


class TestLaunch:
    """launch()."""

    def test_passes_image_command_env_and_workdir(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        runtime.launch(spec=_spec())
        kwargs = fake_client.containers.runs[0]
        assert kwargs["image"] == "brain/coding-runtime:claude"
        assert kwargs["command"] == ["claude", "hello"]
        assert kwargs["environment"] == {"FOO": "bar"}
        assert kwargs["working_dir"] == "/work"
        assert kwargs["detach"] is True

    def test_translates_mounts_to_volumes(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        runtime.launch(spec=_spec())
        volumes = fake_client.containers.runs[0]["volumes"]
        assert volumes == {"/tmp/work": {"bind": "/work", "mode": "rw"}}

    def test_provisions_per_task_network(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        """Each launch gets its own bridge network keyed by task id."""
        runtime.launch(spec=_spec())
        assert fake_client.networks.created
        net_kwargs = fake_client.networks.created[0]
        assert net_kwargs["name"] == "brain-coding-task-001"
        assert fake_client.containers.runs[0]["network"] == net_kwargs["name"]

    def test_launch_failure_translates_to_launch_error(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        fake_client.containers.run_error = RuntimeError("image missing")
        with pytest.raises(ContainerLaunchError):
            runtime.launch(spec=_spec())

    def test_network_cleaned_up_on_launch_failure(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        """When containers.run fails, the per-task network is reaped."""
        fake_client.containers.run_error = RuntimeError("image missing")
        with pytest.raises(ContainerLaunchError):
            runtime.launch(spec=_spec())
        assert fake_client.networks.removed == ["brain-coding-task-001"]
        assert "brain-coding-task-001" not in fake_client.networks.networks

    def test_existing_network_409_is_reused(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        """A 409 from networks.create is treated as already-exists and reused."""
        from unittest.mock import MagicMock  # noqa: PLC0415

        from docker.errors import APIError  # noqa: PLC0415

        response = MagicMock()
        response.status_code = 409
        fake_client.networks.create_error = APIError("conflict", response=response)
        runtime.launch(spec=_spec())
        assert fake_client.containers.runs[0]["network"] == "brain-coding-task-001"


class TestStatus:
    """status()."""

    def test_running_phase(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        handle = runtime.launch(spec=_spec())
        status = runtime.status(handle=handle)
        assert status.phase is ContainerPhase.RUNNING
        assert status.exit_code is None

    def test_exited_with_exit_code(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        handle = runtime.launch(spec=_spec())
        fake_client.containers.containers[handle.container_id].attrs = {
            "State": {"Status": "exited", "ExitCode": 7}
        }
        status = runtime.status(handle=handle)
        assert status.phase is ContainerPhase.EXITED
        assert status.exit_code == 7

    def test_unknown_container_raises(self, runtime: DockerContainerRuntime) -> None:
        pytest.importorskip("docker")
        from datetime import UTC, datetime

        from resources.adapters.coding.runtime import ContainerHandle

        bogus = ContainerHandle(container_id="ghost", started_at=datetime.now(UTC))
        with pytest.raises(ContainerNotFoundError):
            runtime.status(handle=bogus)


class TestStop:
    """stop()."""

    def test_honours_stop_timeout(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        handle = runtime.launch(spec=_spec())
        runtime.stop(handle=handle)
        container = fake_client.containers.containers[handle.container_id]
        assert container.stop_calls == [15]


class TestRemove:
    """remove() reaps the container and any per-task network."""

    def test_removes_container_and_network(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        handle = runtime.launch(spec=_spec())
        runtime.remove(handle=handle)
        assert fake_client.networks.removed
        assert fake_client.containers.containers[handle.container_id].removed


class TestListOwned:
    """list_owned() returns container handles with their labels intact."""

    def test_returns_handles_and_passes_label_filter(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        runtime.launch(spec=_spec(labels={"brain.coding.task_id": "task-A"}))
        runtime.launch(spec=_spec(labels={"brain.coding.task_id": "task-B"}))
        owned = runtime.list_owned(owner_label="brain.coding.owner=brain-core@test")
        assert len(owned) == 2
        # The filter kwarg the runtime hands to the SDK must be the
        # label expression we passed in, not discarded.
        assert fake_client.containers.list_calls == [
            {"all": True, "filters": {"label": "brain.coding.owner=brain-core@test"}},
        ]

    def test_propagates_labels_on_handle(
        self, runtime: DockerContainerRuntime, fake_client: FakeDockerClient
    ) -> None:
        """Container labels surface on the returned handle so the adapter
        can derive task_id from them when reattaching to orphans."""
        # Seed a container with labels via the fake.
        cid = "fake-orphan-1"
        fake = FakeContainer(
            id=cid,
            attrs={
                "State": {"Status": "exited", "ExitCode": 0},
                "Config": {"Labels": {"brain.coding.task_id": "task-orphan"}},
            },
        )
        fake_client.containers.containers[cid] = fake
        owned = runtime.list_owned(owner_label="brain.coding.owner=brain-core@test")
        assert len(owned) == 1
        assert owned[0].labels.get("brain.coding.task_id") == "task-orphan"
