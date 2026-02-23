"""Component declaration for Language Model Service."""

from __future__ import annotations

from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_language_model")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="action",
        module_roots=frozenset({ModuleRoot("services.action.language_model")}),
        public_api_roots=frozenset(
            {ModuleRoot("services.action.language_model.service")}
        ),
        owns_resources=frozenset({ComponentId("adapter_litellm")}),
    )
)
