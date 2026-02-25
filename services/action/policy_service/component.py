"""Component declaration for Policy Service."""

from __future__ import annotations

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
