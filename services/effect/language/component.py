"""Component declaration for Language Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_language")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="effect",
        module_roots=frozenset({ModuleRoot("services.effect.language")}),
        public_api_roots=frozenset({ModuleRoot("services.effect.language.service")}),
        owns_resources=frozenset({ComponentId("adapter_llm")}),
        exposes_ops=True,
        tool_system_label="Language Service",
        tool_system_summary="LLM inference and embedding generation.",
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.effect.language.service import build_language_service

    return build_language_service(
        settings=settings,
        adapter=components.get("adapter_llm"),
    )
