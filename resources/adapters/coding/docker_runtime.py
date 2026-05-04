"""Host-Docker :class:`ContainerRuntime` implementation.

This module ships the v1 substrate beneath the Coding Adapter: a sync
``docker`` SDK client that talks to the **host** Docker daemon over a
bind-mounted socket (DooD). It launches sibling task containers, applies
labels and bind mounts, attaches them to a per-task user-defined network,
and supervises lifecycle/cleanup.

The runtime is single-purpose: launch, observe, stop, log, reap. It
knows nothing about executors, prompts, or worktree semantics. Those
concerns belong to :class:`~resources.adapters.coding.docker_coding_adapter.DockerCodingAdapter`
and the Software Service.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docker.errors import APIError, NotFound
from docker.errors import DockerException as _DockerException

from lib.shared.logging import get_logger
from resources.adapters.coding.runtime import (
    DEFAULT_STOP_TIMEOUT_SECONDS,
    ContainerHandle,
    ContainerLaunchError,
    ContainerLogs,
    ContainerNotFoundError,
    ContainerPhase,
    ContainerRuntime,
    ContainerRuntimeError,
    ContainerRuntimeUnavailable,
    ContainerSpec,
    ContainerStatus,
)

if TYPE_CHECKING:
    from docker.models.containers import Container

_LOGGER = get_logger(__name__)

_NETWORK_ALREADY_EXISTS_STATUS: int = 409


def _now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


def _phase_from_state(state: str) -> ContainerPhase:
    """Map a Docker state string to a :class:`ContainerPhase`."""
    match state:
        case "created":
            return ContainerPhase.CREATED
        case "running" | "restarting" | "removing":
            return ContainerPhase.RUNNING
        case "exited" | "dead":
            return ContainerPhase.EXITED
        case _:
            return ContainerPhase.UNKNOWN


class DockerContainerRuntime(ContainerRuntime):
    """Docker-backed :class:`ContainerRuntime` using the host daemon socket.

    Parameters
    ----------
    docker_socket:
        Path to the Docker daemon socket (default ``/var/run/docker.sock``).
        On Brain Core this is the bind-mounted host socket.
    client:
        Optional pre-built ``docker.DockerClient`` for tests; when supplied
        the constructor will not contact Docker itself.
    client_timeout_seconds:
        Timeout passed to the Docker SDK constructor so a hung daemon
        does not deadlock the driver thread.
    """

    def __init__(
        self,
        *,
        docker_socket: str = "/var/run/docker.sock",
        client: Any | None = None,
        client_timeout_seconds: int = 30,
        self_compose_service: str = "brain-core",
    ) -> None:
        self._socket = docker_socket
        self._client_timeout_seconds = client_timeout_seconds
        self._self_compose_service = self_compose_service
        if client is not None:
            self._client = client
        else:
            self._client = self._connect()
        self._stop_timeouts: dict[str, int] = {}
        self._task_networks: dict[str, str] = {}

    def _connect(self) -> Any:
        """Build a Docker SDK client against the configured socket."""
        try:
            import docker  # noqa: PLC0415

            base_url = f"unix://{self._socket}"
            return docker.DockerClient(
                base_url=base_url, timeout=self._client_timeout_seconds
            )
        except _DockerException as exc:
            raise ContainerRuntimeUnavailable(f"Docker SDK unavailable: {exc}") from exc

    # ------------------------------------------------------------------
    # Public protocol surface
    # ------------------------------------------------------------------
    def health(self) -> bool:
        """Return ``True`` when the Docker daemon answers a ping."""
        try:
            return bool(self._client.ping())
        except Exception as exc:
            _LOGGER.debug("docker ping failed: %s", exc)
            return False

    def launch(self, *, spec: ContainerSpec) -> ContainerHandle:
        """Create + start a sibling container per ``spec``.

        Provisions a per-task user-defined Docker network, attaches the
        container to it, applies labels and mounts, then starts the
        container.
        """
        network_name = self._provision_network(spec=spec)
        volumes = {
            mount.source: {
                "bind": mount.target,
                "mode": "ro" if mount.read_only else "rw",
            }
            for mount in spec.mounts
        }
        kwargs: dict[str, Any] = {
            "image": spec.image,
            "command": list(spec.command) if spec.command else None,
            "environment": dict(spec.env),
            "labels": dict(spec.labels),
            "volumes": volumes,
            "detach": True,
            "stdout": True,
            "stderr": True,
        }
        if spec.workdir:
            kwargs["working_dir"] = spec.workdir
        if network_name:
            kwargs["network"] = network_name

        try:
            container = self._client.containers.run(**kwargs)
        except Exception as exc:
            self._discard_network(network_name)
            raise ContainerLaunchError(
                f"failed to launch container from image {spec.image!r}: {exc}"
            ) from exc

        if network_name:
            self._task_networks[container.id] = network_name
        self._stop_timeouts[container.id] = spec.stop_timeout_seconds
        return ContainerHandle(
            container_id=container.id,
            started_at=_now(),
            labels=dict(spec.labels),
        )

    def status(self, *, handle: ContainerHandle) -> ContainerStatus:
        """Return current lifecycle status of the container."""
        container = self._lookup(container_id=handle.container_id)
        try:
            container.reload()
        except Exception as exc:
            raise ContainerRuntimeError(
                f"failed to refresh container {handle.container_id}: {exc}"
            ) from exc
        state = container.attrs.get("State", {}) or {}
        phase = _phase_from_state(state.get("Status", "unknown"))
        exit_code: int | None = None
        if phase is ContainerPhase.EXITED:
            raw = state.get("ExitCode")
            if raw is not None:
                exit_code = int(raw)
        return ContainerStatus(
            container_id=handle.container_id,
            phase=phase,
            exit_code=exit_code,
            observed_at=_now(),
        )

    def stop(self, *, handle: ContainerHandle) -> None:
        """Send a stop signal honouring ``stop_timeout`` from launch."""
        container = self._lookup(container_id=handle.container_id)
        timeout = self._stop_timeouts.get(
            handle.container_id, DEFAULT_STOP_TIMEOUT_SECONDS
        )
        try:
            container.stop(timeout=timeout)
        except Exception as exc:
            raise ContainerRuntimeError(
                f"failed to stop container {handle.container_id}: {exc}"
            ) from exc

    def logs(self, *, handle: ContainerHandle) -> ContainerLogs:
        """Collect captured stdout / stderr from the container."""
        container = self._lookup(container_id=handle.container_id)
        try:
            stdout = container.logs(stdout=True, stderr=False, stream=False)
            stderr = container.logs(stdout=False, stderr=True, stream=False)
        except Exception as exc:
            raise ContainerRuntimeError(
                f"failed to read logs for {handle.container_id}: {exc}"
            ) from exc
        return ContainerLogs(
            stdout=stdout if isinstance(stdout, bytes) else bytes(stdout or b""),
            stderr=stderr if isinstance(stderr, bytes) else bytes(stderr or b""),
        )

    def remove(self, *, handle: ContainerHandle) -> None:
        """Reap the container and any task-scoped network."""
        try:
            container = self._lookup(container_id=handle.container_id)
        except ContainerNotFoundError:
            self._discard_network(self._task_networks.pop(handle.container_id, None))
            self._stop_timeouts.pop(handle.container_id, None)
            return
        try:
            container.remove(force=True)
        except Exception as exc:
            raise ContainerRuntimeError(
                f"failed to remove container {handle.container_id}: {exc}"
            ) from exc
        self._discard_network(self._task_networks.pop(handle.container_id, None))
        self._stop_timeouts.pop(handle.container_id, None)

    def host_path_for(self, *, container_path: str) -> str | None:
        """Translate a path inside this container to its host bind source.

        Walks brain-core's own container's ``Mounts`` list and finds the
        bind whose destination is the longest prefix of ``container_path``;
        rebases the suffix onto that bind's source. Returns ``None`` when
        no bind covers the path. The lookup is fresh on every call —
        Docker is the source of truth for the live mount table; brain-core
        does not cache.
        """
        self_container = self._lookup_self_container()
        if self_container is None:
            return None
        try:
            self_container.reload()
        except Exception as exc:
            raise ContainerRuntimeError(
                f"failed to refresh self container: {exc}"
            ) from exc
        mounts = self_container.attrs.get("Mounts") or []
        target = Path(container_path)
        best: tuple[str, str] | None = None
        for mount in mounts:
            if not isinstance(mount, dict):
                continue
            destination = mount.get("Destination")
            source = mount.get("Source")
            if not isinstance(destination, str) or not isinstance(source, str):
                continue
            try:
                target.relative_to(destination)
            except ValueError:
                continue
            if best is None or len(destination) > len(best[0]):
                best = (destination, source)
        if best is None:
            return None
        destination, source = best
        relative = target.relative_to(destination)
        if str(relative) == ".":
            return source
        return str(Path(source) / relative)

    def list_owned(self, *, owner_label: str) -> tuple[ContainerHandle, ...]:
        """Enumerate containers carrying the given owner label.

        ``owner_label`` may be ``key`` (matches any value) or ``key=value``.
        """
        try:
            containers = self._client.containers.list(
                all=True,
                filters={"label": owner_label},
            )
        except _DockerException as exc:
            raise ContainerRuntimeUnavailable(
                f"docker daemon unreachable while listing owned containers: {exc}"
            ) from exc
        except Exception as exc:
            raise ContainerRuntimeError(
                f"failed to list owned containers: {exc}"
            ) from exc
        handles: list[ContainerHandle] = []
        for container in containers:
            started_at = _parse_started_at(container.attrs)
            labels = dict((container.attrs.get("Config", {}) or {}).get("Labels") or {})
            handles.append(
                ContainerHandle(
                    container_id=container.id,
                    started_at=started_at,
                    labels=labels,
                )
            )
        return tuple(handles)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _lookup_self_container(self) -> Container | None:
        """Resolve brain-core's own container, tolerating non-default hostnames.

        Tries the conventional Docker default first — the container's
        hostname matches its short id — then falls back to a Compose
        service-label lookup for setups that override ``hostname:`` in
        ``docker-compose.yaml``. Returns ``None`` when neither attempt
        finds a match (the caller treats this as "no bind covers the
        path"); raises only when the daemon itself is unreachable.
        """
        try:
            return self._client.containers.get(socket.gethostname())
        except NotFound:
            pass
        except _DockerException as exc:
            raise ContainerRuntimeUnavailable(
                f"docker daemon unreachable while resolving self container: {exc}"
            ) from exc
        try:
            candidates = self._client.containers.list(
                all=True,
                filters={
                    "label": (
                        f"com.docker.compose.service={self._self_compose_service}"
                    ),
                },
            )
        except _DockerException as exc:
            raise ContainerRuntimeUnavailable(
                f"docker daemon unreachable while listing self by label: {exc}"
            ) from exc
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _lookup(self, *, container_id: str) -> Container:
        """Fetch a container model or raise :class:`ContainerNotFoundError`."""
        try:
            return self._client.containers.get(container_id)
        except NotFound as exc:
            raise ContainerNotFoundError(f"no such container: {container_id}") from exc
        except Exception as exc:
            raise ContainerRuntimeError(
                f"docker error for container {container_id}: {exc}"
            ) from exc

    def _provision_network(self, *, spec: ContainerSpec) -> str:
        """Create a per-task user-defined Docker network.

        Each task is isolated on its own bridge network. Egress filtering
        itself is not enforced today; the network exists for membership
        scoping and future enforcement at the firewall layer.
        """
        task_id = spec.labels.get("brain.coding.task_id", "anon")
        network_name = f"brain-coding-{task_id}"
        labels = {
            **dict(spec.labels),
            "brain.coding.network": "task",
        }
        try:
            self._client.networks.create(
                name=network_name,
                driver="bridge",
                labels=labels,
                internal=False,
            )
        except APIError as exc:
            if getattr(exc, "status_code", None) == _NETWORK_ALREADY_EXISTS_STATUS:
                _LOGGER.debug("reusing existing task network %s", network_name)
                return network_name
            raise ContainerRuntimeError(
                f"failed to provision task network {network_name!r}: {exc}"
            ) from exc
        return network_name

    def _discard_network(self, network_name: str | None) -> None:
        """Best-effort removal of a per-task network."""
        if not network_name:
            return
        try:
            network = self._client.networks.get(network_name)
            network.remove()
        except Exception as exc:
            _LOGGER.debug("network %s cleanup skipped: %s", network_name, exc)


def _parse_started_at(attrs: dict[str, Any]) -> datetime:
    """Best-effort parse of ``State.StartedAt`` from Docker container attrs."""
    raw = (attrs.get("State", {}) or {}).get("StartedAt")
    if isinstance(raw, str) and raw and not raw.startswith("0001"):
        try:
            trimmed = raw[:-1] if raw.endswith("Z") else raw
            if "." in trimmed:
                head, frac = trimmed.split(".", 1)
                trimmed = f"{head}.{frac[:6]}"
            return datetime.fromisoformat(trimmed).replace(tzinfo=UTC)
        except ValueError:
            pass
    return _now()
