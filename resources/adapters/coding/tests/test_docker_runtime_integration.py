"""Real-Docker integration tests for :class:`DockerContainerRuntime`.

These tests are gated by ``BRAIN_RUN_INTEGRATION_REAL=1``. If Docker is
not reachable the suite is skipped cleanly rather than failing.

They exercise launch, status polling, log capture, cancellation via
``stop``, orphan listing, and container reaping against a deterministic
fake CLI baked into a small ephemeral image.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import textwrap
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from resources.adapters.coding.runtime import (
    ContainerPhase,
    ContainerSpec,
)
from tests.integration.helpers import real_provider_tests_enabled

_LOGGER = logging.getLogger(__name__)

pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def _docker_available() -> bool:
    """Return True when the Docker SDK can reach a daemon."""
    try:
        import docker  # noqa: PLC0415

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


def _build_fake_cli_image() -> str:
    """Build a tiny image whose CMD exits 0 after writing to stdout/stderr.

    Returns the tag of the built image. The caller is responsible for
    eventually cleaning it up via ``docker rmi``.
    """
    import docker  # noqa: PLC0415

    tag = f"brain-coding-test-fakecli:{uuid.uuid4().hex[:8]}"
    workdir = Path(tempfile.mkdtemp(prefix="brain-fakecli-"))
    try:
        (workdir / "Dockerfile").write_text(
            textwrap.dedent(
                """\
                FROM busybox:stable-musl
                CMD ["sh", "-c", "echo hello-stdout; echo hello-stderr 1>&2; exit 0"]
                """
            )
        )
        client = docker.from_env()
        client.images.build(path=str(workdir), tag=tag, rm=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return tag


@pytest.fixture(scope="module")
def fake_cli_image() -> Iterator[str]:
    """Build the fake CLI image once per test module."""
    if not _docker_available():
        pytest.skip("Docker daemon unavailable")
    tag = _build_fake_cli_image()
    yield tag
    try:
        import docker  # noqa: PLC0415

        docker.from_env().images.remove(image=tag, force=True)
    except Exception as exc:
        _LOGGER.warning("failed to remove fake CLI image %s: %s", tag, exc)


@pytest.fixture()
def runtime() -> "object":
    """Build a DockerContainerRuntime against the local daemon."""
    if not _docker_available():
        pytest.skip("Docker daemon unavailable")
    from resources.adapters.coding.docker_runtime import (  # noqa: PLC0415
        DockerContainerRuntime,
    )

    socket = os.environ.get("DOCKER_HOST_SOCKET", "/var/run/docker.sock")
    return DockerContainerRuntime(docker_socket=socket)


def _spec(*, image: str, labels: dict[str, str]) -> ContainerSpec:
    """Build a ContainerSpec for the fake CLI image."""
    return ContainerSpec(
        image=image,
        env={},
        mounts=(),
        labels=labels,
        stop_timeout_seconds=2,
    )


def _wait_for_phase(
    runtime, handle, phase: ContainerPhase, *, timeout: float = 30.0
) -> None:
    """Poll until the container reaches ``phase`` or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runtime.status(handle=handle).phase is phase:
            return
        time.sleep(0.2)
    raise TimeoutError(f"phase {phase} not reached within {timeout}s")


def test_launch_status_logs_and_remove(runtime, fake_cli_image: str) -> None:
    """Real round-trip: launch, observe EXITED, capture logs, reap."""
    label_value = f"int-{uuid.uuid4().hex[:8]}"
    handle = runtime.launch(
        spec=_spec(
            image=fake_cli_image,
            labels={
                "brain.coding.owner": label_value,
                "brain.coding.task_id": "int-task",
            },
        )
    )
    try:
        _wait_for_phase(runtime, handle, ContainerPhase.EXITED)
        status = runtime.status(handle=handle)
        assert status.exit_code == 0
        logs = runtime.logs(handle=handle)
        assert b"hello-stdout" in logs.stdout
        assert b"hello-stderr" in logs.stderr
    finally:
        runtime.remove(handle=handle)


def test_list_owned_finds_orphans(runtime, fake_cli_image: str) -> None:
    """list_owned() should surface containers with the matching label."""
    owner = f"owner-{uuid.uuid4().hex[:8]}"
    handle = runtime.launch(
        spec=_spec(
            image=fake_cli_image,
            labels={
                "brain.coding.owner": owner,
                "brain.coding.task_id": "list-owned",
            },
        )
    )
    try:
        _wait_for_phase(runtime, handle, ContainerPhase.EXITED)
        owned = runtime.list_owned(owner_label=f"brain.coding.owner={owner}")
        assert any(h.container_id == handle.container_id for h in owned)
    finally:
        runtime.remove(handle=handle)


def test_stop_terminates_running_container(runtime) -> None:
    """stop() should terminate a long-running container."""
    if not _docker_available():
        pytest.skip("Docker daemon unavailable")
    spec = ContainerSpec(
        image="busybox:stable-musl",
        command=("sh", "-c", "sleep 60"),
        env={},
        mounts=(),
        labels={"brain.coding.task_id": "stop-test"},
        stop_timeout_seconds=2,
    )
    handle = runtime.launch(spec=spec)
    try:
        _wait_for_phase(runtime, handle, ContainerPhase.RUNNING, timeout=10)
        runtime.stop(handle=handle)
        _wait_for_phase(runtime, handle, ContainerPhase.EXITED, timeout=10)
    finally:
        runtime.remove(handle=handle)
