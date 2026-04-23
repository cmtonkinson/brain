"""Component declaration for Switchboard Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_switchboard")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="action",
        module_roots=frozenset({ModuleRoot("services.action.switchboard")}),
        public_api_roots=frozenset({ModuleRoot("services.action.switchboard.service")}),
        owns_resources=frozenset({ComponentId("adapter_signal")}),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from lib.sdk.client import BrainSdkClient
    from resources.adapters.signal.adapter import SignalAdapter
    from services.action.attention_router.service import AttentionRouterService
    from services.action.switchboard.service import build_switchboard_service
    from services.state.cache_authority.service import CacheAuthorityService
    from services.state.memory_authority.service import MemoryAuthorityService

    cache_service = components.get("service_cache_authority")
    if not isinstance(cache_service, CacheAuthorityService):
        raise KeyError("service_cache_authority")

    signal_adapter = components.get("adapter_signal")
    if signal_adapter is not None and not isinstance(signal_adapter, SignalAdapter):
        raise TypeError("adapter_signal")

    attention_router = components.get("service_attention_router")
    if attention_router is None:
        raise KeyError("service_attention_router")
    if not isinstance(attention_router, AttentionRouterService):
        raise TypeError("service_attention_router")

    brain_client = BrainSdkClient(source="switchboard", principal="operator")

    memory_authority = components.get("service_memory_authority")
    if memory_authority is None:
        raise KeyError("service_memory_authority")
    if not isinstance(memory_authority, MemoryAuthorityService):
        raise TypeError("service_memory_authority")

    return build_switchboard_service(
        settings=settings,
        cache_service=cache_service,
        signal_adapter=signal_adapter,
        attention_router_service=attention_router,
        memory_authority_service=memory_authority,
        brain_client=brain_client,
    )
