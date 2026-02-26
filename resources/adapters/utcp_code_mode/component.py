"""Component declaration for UTCP code-mode adapter resource."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("adapter_utcp_code_mode")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="action",
        kind="adapter",
        module_roots=frozenset({ModuleRoot("resources.adapters.utcp_code_mode")}),
        owner_service_id=ComponentId("service_capability_engine"),
    )
)


def build_component(
    *, settings: BrainSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered resource component."""
    del components
    from resources.adapters.utcp_code_mode.config import (
        resolve_utcp_code_mode_adapter_settings,
    )
    from resources.adapters.utcp_code_mode.utcp_code_mode_adapter import (
        LocalFileUtcpCodeModeAdapter,
    )

    return LocalFileUtcpCodeModeAdapter(
        settings=resolve_utcp_code_mode_adapter_settings(settings),
    )
