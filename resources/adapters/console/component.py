"""Component declaration for the Console adapter resource."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("adapter_console")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        tier=1,
        plane="effect",
        kind="adapter",
        module_roots=frozenset({ModuleRoot("resources.adapters.console")}),
        owner_service_id=None,
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for the Console adapter."""
    del components
    from resources.adapters.console.config import resolve_console_adapter_settings
    from resources.adapters.console.console_adapter import InProcessConsoleAdapter

    return InProcessConsoleAdapter(settings=resolve_console_adapter_settings(settings))
