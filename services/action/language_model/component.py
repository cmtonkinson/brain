"""Component declaration for Language Model Service."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import BrainSettings
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


def build_component(
    *, settings: BrainSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.action.language_model.service import build_language_model_service

    return build_language_model_service(
        settings=settings,
        adapter=components.get("adapter_litellm"),
    )
