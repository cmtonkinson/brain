"""Component declaration for Switchboard Service."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.manifest import (
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
    from resources.adapters.signal.adapter import SignalAdapter
    from services.action.switchboard.service import build_switchboard_service
    from services.state.cache_authority.service import CacheAuthorityService

    cache_service = components.get("service_cache_authority")
    if not isinstance(cache_service, CacheAuthorityService):
        raise KeyError("service_cache_authority")

    signal_adapter = components.get("adapter_signal")
    if signal_adapter is not None and not isinstance(signal_adapter, SignalAdapter):
        raise TypeError("adapter_signal")

    return build_switchboard_service(
        settings=settings,
        cache_service=cache_service,
        signal_adapter=signal_adapter,
    )
