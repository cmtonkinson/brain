"""Component declaration for SeaweedFS blob substrate resource."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("substrate_seaweedfs")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="state",
        kind="substrate",
        module_roots=frozenset({ModuleRoot("resources.substrates.seaweedfs")}),
        owner_service_id=ComponentId("service_object_authority"),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered resource component."""
    del components
    from resources.substrates.seaweedfs.config import (
        resolve_seaweedfs_substrate_settings,
    )
    from resources.substrates.seaweedfs.seaweedfs_substrate import (
        SeaweedFSBlobSubstrate,
    )

    return SeaweedFSBlobSubstrate(
        settings=resolve_seaweedfs_substrate_settings(settings),
    )
