"""Component declaration for Attention Router Service."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_attention_router")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="action",
        module_roots=frozenset({ModuleRoot("services.action.attention_router")}),
        public_api_roots=frozenset(
            {
                ModuleRoot("services.action.attention_router.service"),
                ModuleRoot("services.action.attention_router.domain"),
            }
        ),
        owns_resources=frozenset(),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.action.attention_router.service import build_attention_router_service
    from services.state.memory_authority.service import MemoryAuthorityService

    memory_authority = components.get("service_memory_authority")
    if memory_authority is None:
        raise KeyError("service_memory_authority")
    if not isinstance(memory_authority, MemoryAuthorityService):
        raise TypeError("service_memory_authority")

    switchboard_raw = settings.core.service.model_dump(mode="python").get(
        "switchboard", {}
    )
    console_queue = switchboard_raw.get(
        "console_response_queue_name", "console_outbound"
    )

    return build_attention_router_service(
        settings=settings,
        signal_adapter=components.get("adapter_signal"),
        console_response_queue_name=str(console_queue),
        cache_authority_service=components.get("service_cache_authority"),
        memory_authority_service=memory_authority,
    )
