"""Component declaration for filesystem blob substrate resource."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("substrate_filesystem")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="state",
        kind="substrate",
        module_roots=frozenset({ModuleRoot("resources.substrates.filesystem")}),
        owner_service_id=ComponentId("service_object_authority"),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered resource component."""
    del components
    from resources.substrates.filesystem.filesystem_substrate import (
        LocalFilesystemBlobSubstrate,
    )
    from resources.substrates.filesystem.config import (
        resolve_filesystem_substrate_settings,
    )

    return LocalFilesystemBlobSubstrate(
        settings=resolve_filesystem_substrate_settings(settings),
    )
