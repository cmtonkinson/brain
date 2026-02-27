"""Component declaration for Capability Engine Service."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_capability_engine")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="action",
        module_roots=frozenset({ModuleRoot("services.action.capability_engine")}),
        public_api_roots=frozenset(
            {ModuleRoot("services.action.capability_engine.service")}
        ),
        owns_resources=frozenset({ComponentId("adapter_utcp_code_mode")}),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.action.capability_engine.service import (
        build_capability_engine_service,
    )
    from services.action.policy_service.service import PolicyService

    policy_service = components.get("service_policy_service")
    if not isinstance(policy_service, PolicyService):
        raise KeyError("service_policy_service")

    return build_capability_engine_service(
        settings=settings,
        policy_service=policy_service,
        code_mode_adapter=components.get("adapter_utcp_code_mode"),
    )


def after_boot(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> None:
    """Load capability manifests after all component boot hooks succeed."""
    from services.action.capability_engine.implementation import (
        DefaultCapabilityEngineService,
    )

    service = components.get(str(SERVICE_COMPONENT_ID))
    if not isinstance(service, DefaultCapabilityEngineService):
        raise RuntimeError("service_capability_engine is missing or invalid")
    service._load_capabilities()
