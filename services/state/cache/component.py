"""Component declaration for Cache Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_cache")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="state",
        module_roots=frozenset({ModuleRoot("services.state.cache")}),
        public_api_roots=frozenset({ModuleRoot("services.state.cache.service")}),
        owns_resources=frozenset({ComponentId("substrate_valkey")}),
        exposes_ops=True,
        tool_system_label="Cache Service",
        tool_system_summary="Component-scoped cache values and FIFO queues.",
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.state.cache.service import build_cache_service

    return build_cache_service(
        settings=settings,
        backend=components.get("substrate_valkey"),
    )
