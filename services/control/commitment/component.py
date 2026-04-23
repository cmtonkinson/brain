"""Component declaration for Commitment Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_commitment")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="control",
        module_roots=frozenset({ModuleRoot("services.control.commitment")}),
        public_api_roots=frozenset({ModuleRoot("services.control.commitment.service")}),
        owns_resources=frozenset(),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.control.commitment.service import build_commitment_service

    return build_commitment_service(settings=settings, components=components)
