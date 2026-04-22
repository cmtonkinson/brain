"""Component declaration for the MCP adapter resource."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("adapter_mcp")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="action",
        kind="adapter",
        module_roots=frozenset({ModuleRoot("resources.adapters.mcp")}),
        owner_service_id=ComponentId("service_capability_engine"),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered resource component."""
    del components
    from resources.adapters.mcp.config import resolve_mcp_adapter_settings
    from resources.adapters.mcp.http_mcp_adapter import HttpMcpAdapter

    return HttpMcpAdapter(settings=resolve_mcp_adapter_settings(settings))
