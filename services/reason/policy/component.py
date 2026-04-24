"""Component declaration for Policy Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_policy")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="reason",
        module_roots=frozenset({ModuleRoot("services.reason.policy")}),
        public_api_roots=frozenset(
            {
                ModuleRoot("services.reason.policy.service"),
                ModuleRoot("services.reason.policy.domain"),
            }
        ),
        owns_resources=frozenset(),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.effect.relay.service import RelayService
    from services.reason.policy.service import build_policy_service

    outbound = components.get("service_relay")
    if outbound is not None and not isinstance(outbound, RelayService):
        raise TypeError("service_relay")

    return build_policy_service(
        settings=settings,
        outbound_service=outbound,
    )
