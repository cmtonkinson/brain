"""Component declaration for the Coding Adapter resource."""

from __future__ import annotations

import os
import socket
from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("adapter_coding")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        tier=1,
        plane="effect",
        kind="adapter",
        module_roots=frozenset({ModuleRoot("resources.adapters.coding")}),
        owner_service_id=ComponentId("service_software"),
    )
)


def _owner_id() -> str:
    """Return a stable owner-id string for *this* Brain Core process.

    Prefers ``BRAIN_CORE_INSTANCE_ID`` so operator overrides survive
    restarts; falls back to the container hostname for distinctness
    across compose invocations.
    """
    explicit = os.environ.get("BRAIN_CORE_INSTANCE_ID", "").strip()
    if explicit:
        return explicit
    return f"brain-core@{socket.gethostname()}"


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build the concrete :class:`DockerCodingAdapter` for this component."""
    from resources.adapters.coding.config import resolve_coding_adapter_settings
    from resources.adapters.coding.docker_coding_adapter import DockerCodingAdapter
    from resources.adapters.coding.docker_runtime import DockerContainerRuntime
    from resources.adapters.coding.image_builder import DockerImageBuilder

    adapter_settings = resolve_coding_adapter_settings(settings)
    runtime = DockerContainerRuntime(
        docker_socket=adapter_settings.docker_socket,
        client_timeout_seconds=adapter_settings.client_timeout_seconds,
    )
    image_builder = DockerImageBuilder(
        docker_socket=adapter_settings.docker_socket,
        client_timeout_seconds=adapter_settings.client_timeout_seconds,
    )
    return DockerCodingAdapter(
        settings=adapter_settings,
        runtime=runtime,
        image_builder=image_builder,
        owner_id=_owner_id(),
    )
