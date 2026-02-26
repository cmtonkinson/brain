"""Component declaration for filesystem blob adapter resource."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("adapter_filesystem")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="state",
        kind="adapter",
        module_roots=frozenset({ModuleRoot("resources.adapters.filesystem")}),
        owner_service_id=ComponentId("service_object_authority"),
    )
)


def build_component(
    *, settings: BrainSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered resource component."""
    del components
    from resources.adapters.filesystem.adapter import LocalFilesystemBlobAdapter
    from resources.adapters.filesystem.config import resolve_filesystem_adapter_settings

    return LocalFilesystemBlobAdapter(
        settings=resolve_filesystem_adapter_settings(settings),
    )
