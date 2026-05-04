"""Image-building substrate beneath the Coding Adapter.

The Coding Adapter spawns task containers from one of two image shapes:

* ``base_image`` — Brain's single shipped runtime tag, with every
  configured agent CLI baked in. Used verbatim when a workspace has no
  per-workspace customization script.
* ``<workspace_image_repo>:<workspace_slug>`` — a per-workspace layer
  built lazily by Brain Core when the operator drops an install script
  at ``<workspace_image_root>/<workspace_relative_path>.sh``. The layer
  ``FROM`` s the base image, runs the operator's script as root, and
  switches back to the ``coder`` user that the base image leaves as
  default.

The :class:`ImageBuilder` Protocol abstracts the daemon interaction so
tests can substitute a fake. The :class:`DockerImageBuilder` concrete
implementation talks to the same Docker socket the
:class:`~resources.adapters.coding.runtime.ContainerRuntime` uses; the
two are kept on separate interfaces so the runtime stays single-purpose
(launch / supervise / reap).
"""

from __future__ import annotations

import io
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable


_DOCKERFILE_TEMPLATE: Final[str] = """\
FROM {base_image}
USER root
COPY install.sh /tmp/install.sh
RUN bash /tmp/install.sh && rm /tmp/install.sh
USER coder
"""


class ImageBuilderError(Exception):
    """Base exception for image-building failures."""


class ImageBuildFailed(ImageBuilderError):
    """The image build failed; the operator's script likely raised."""

    def __init__(self, *, tag: str, build_output: str) -> None:
        super().__init__(
            f"failed to build image {tag!r}; build output:\n{build_output}"
        )
        self.tag = tag
        self.build_output = build_output


class ImageBuilderUnavailable(ImageBuilderError):
    """The Docker daemon is not reachable for image operations."""


@runtime_checkable
class ImageBuilder(Protocol):
    """Protocol for build / inspect operations on local Docker images."""

    def image_created_at(self, *, tag: str) -> datetime | None:
        """Return the local image's creation timestamp, or ``None`` if absent."""

    def build_workspace_image(
        self,
        *,
        tag: str,
        base_image: str,
        install_script_path: Path,
    ) -> None:
        """Build ``tag`` ``FROM base_image`` running ``install_script_path``.

        The script is run as root during the build; the resulting image's
        runtime user is reset to ``coder`` so it matches the base image.
        Raises :class:`ImageBuildFailed` with captured build output on
        non-zero builds.
        """


class DockerImageBuilder(ImageBuilder):
    """Docker SDK-backed :class:`ImageBuilder`."""

    def __init__(
        self,
        *,
        docker_socket: str = "/var/run/docker.sock",
        client: Any | None = None,
        client_timeout_seconds: int = 30,
    ) -> None:
        self._socket = docker_socket
        self._client_timeout_seconds = client_timeout_seconds
        if client is not None:
            self._client = client
        else:
            self._client = self._connect()

    def _connect(self) -> Any:
        """Build a Docker SDK client against the configured socket."""
        try:
            import docker  # noqa: PLC0415
            from docker.errors import DockerException  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise ImageBuilderUnavailable(f"docker SDK import failed: {exc}") from exc
        try:
            return docker.DockerClient(
                base_url=f"unix://{self._socket}",
                timeout=self._client_timeout_seconds,
            )
        except DockerException as exc:
            raise ImageBuilderUnavailable(f"docker daemon unavailable: {exc}") from exc

    def image_created_at(self, *, tag: str) -> datetime | None:
        """Return the Docker image's creation timestamp, or ``None`` if absent."""
        from docker.errors import ImageNotFound  # noqa: PLC0415

        try:
            image = self._client.images.get(tag)
        except ImageNotFound:
            return None
        except Exception as exc:
            raise ImageBuilderUnavailable(
                f"docker image inspect failed for {tag!r}: {exc}"
            ) from exc
        raw = image.attrs.get("Created")
        if not isinstance(raw, str) or not raw:
            return None
        # Docker's `Created` is RFC3339 with nanoseconds we need to trim.
        trimmed = raw.rstrip("Z")
        if "." in trimmed:
            head, frac = trimmed.split(".", 1)
            trimmed = f"{head}.{frac[:6]}"
        try:
            return datetime.fromisoformat(trimmed).replace(tzinfo=UTC)
        except ValueError:
            return None

    def build_workspace_image(
        self,
        *,
        tag: str,
        base_image: str,
        install_script_path: Path,
    ) -> None:
        """Build ``tag`` from a synthesized Dockerfile + the operator script."""
        from docker.errors import BuildError  # noqa: PLC0415

        try:
            script_bytes = install_script_path.read_bytes()
        except OSError as exc:
            raise ImageBuildFailed(
                tag=tag,
                build_output=f"could not read install script {install_script_path}: {exc}",
            ) from exc

        dockerfile = _DOCKERFILE_TEMPLATE.format(base_image=base_image)
        context = self._make_build_context(
            dockerfile=dockerfile, script_bytes=script_bytes
        )

        try:
            _, log_iter = self._client.images.build(
                fileobj=context,
                custom_context=True,
                tag=tag,
                rm=True,
                forcerm=True,
                pull=False,
            )
            output_lines: list[str] = []
            for entry in log_iter:
                if isinstance(entry, dict):
                    line = entry.get("stream") or entry.get("error")
                    if isinstance(line, str):
                        output_lines.append(line)
        except BuildError as exc:
            output = "\n".join(line.get("stream", "") for line in exc.build_log)
            raise ImageBuildFailed(tag=tag, build_output=output) from exc
        except Exception as exc:
            raise ImageBuilderUnavailable(
                f"docker build failed for {tag!r}: {exc}"
            ) from exc

    @staticmethod
    def _make_build_context(*, dockerfile: str, script_bytes: bytes) -> io.BytesIO:
        """Pack a Dockerfile + install.sh into an in-memory tar build context."""
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            df_bytes = dockerfile.encode("utf-8")
            df_info = tarfile.TarInfo(name="Dockerfile")
            df_info.size = len(df_bytes)
            df_info.mode = 0o644
            tar.addfile(df_info, io.BytesIO(df_bytes))

            script_info = tarfile.TarInfo(name="install.sh")
            script_info.size = len(script_bytes)
            script_info.mode = 0o755
            tar.addfile(script_info, io.BytesIO(script_bytes))
        buffer.seek(0)
        return buffer
