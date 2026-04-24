"""Component declaration for Delegation Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_delegation")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="reason",
        module_roots=frozenset({ModuleRoot("services.reason.delegation")}),
        public_api_roots=frozenset({ModuleRoot("services.reason.delegation.service")}),
        owns_resources=frozenset(),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.effect.language.service import LanguageService
    from services.reason.delegation.service import build_delegation_service

    language_model = components.get("service_language")
    if not isinstance(language_model, LanguageService):
        raise KeyError("service_language")

    return build_delegation_service(settings=settings, language_model=language_model)
