"""Component declaration for Ingestion Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_ingestion")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="control",
        module_roots=frozenset({ModuleRoot("services.control.ingestion")}),
        public_api_roots=frozenset({ModuleRoot("services.control.ingestion.service")}),
        owns_resources=frozenset(),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for the Ingestion Service."""
    from services.control.ingestion.service import build_ingestion_service

    return build_ingestion_service(settings=settings, components=components)
