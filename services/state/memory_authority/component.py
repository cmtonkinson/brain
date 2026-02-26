"""Component declaration for Memory Authority Service."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_memory_authority")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="state",
        module_roots=frozenset({ModuleRoot("services.state.memory_authority")}),
        public_api_roots=frozenset(
            {ModuleRoot("services.state.memory_authority.service")}
        ),
        # MAS uses shared Postgres infrastructure; no dedicated L0 resource component.
        owns_resources=frozenset(),
    )
)


def build_component(
    *, settings: BrainSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.action.language_model.service import LanguageModelService
    from services.state.memory_authority.service import build_memory_authority_service

    language_model = components.get("service_language_model")
    if not isinstance(language_model, LanguageModelService):
        raise KeyError("service_language_model")

    return build_memory_authority_service(
        settings=settings,
        language_model=language_model,
    )
