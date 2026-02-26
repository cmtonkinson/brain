"""Component declaration for Policy Service."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_policy_service")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="action",
        module_roots=frozenset({ModuleRoot("services.action.policy_service")}),
        public_api_roots=frozenset(
            {
                ModuleRoot("services.action.policy_service.service"),
                ModuleRoot("services.action.policy_service.domain"),
            }
        ),
        owns_resources=frozenset(),
    )
)


def build_component(
    *, settings: BrainSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.action.attention_router.service import AttentionRouterService
    from services.action.policy_service.service import build_policy_service

    attention_router = components.get("service_attention_router")
    if attention_router is not None and not isinstance(
        attention_router, AttentionRouterService
    ):
        raise TypeError("service_attention_router")

    return build_policy_service(
        settings=settings,
        attention_router_service=attention_router,
    )
