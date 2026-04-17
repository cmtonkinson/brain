"""Component declaration for the native LLM adapter resource."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("adapter_llm")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="action",
        kind="adapter",
        module_roots=frozenset({ModuleRoot("resources.adapters.llm")}),
        owner_service_id=ComponentId("service_language_model"),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered resource component."""
    del components
    from resources.adapters.llm.config import resolve_llm_adapter_settings
    from resources.adapters.llm.llm_adapter import HttpLlmAdapter

    return HttpLlmAdapter(settings=resolve_llm_adapter_settings(settings))
