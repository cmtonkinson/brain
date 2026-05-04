"""Component declaration for Relay Service.

Relay is the single bidirectional comms service. It owns the Signal adapter
and combines what were previously separate Relay inbound (inbound) and
Relay outbound (outbound) services into one component with one cache
namespace, one health endpoint, and one approval round-trip.
"""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_relay")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="effect",
        module_roots=frozenset({ModuleRoot("services.effect.relay")}),
        public_api_roots=frozenset(
            {
                ModuleRoot("services.effect.relay.service"),
                ModuleRoot("services.effect.relay.domain"),
            }
        ),
        owns_resources=frozenset(
            {
                ComponentId("adapter_signal"),
                ComponentId("adapter_console"),
            }
        ),
        exposes_ops=True,
        tool_system_label="Relay Service",
        tool_system_summary=(
            "Bidirectional operator comms: inbound message ingestion, "
            "outbound notification routing, and approval-token correlation."
        ),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build the Relay service from typed settings and resolved deps."""
    from lib.sdk.client import BrainSdkClient
    from resources.adapters.console.adapter import ConsoleAdapter
    from resources.adapters.signal.adapter import SignalAdapter
    from services.effect.relay.service import build_relay_service
    from services.state.cache.service import CacheService
    from services.reason.recall.service import RecallService

    cache_service = components.get("service_cache")
    if not isinstance(cache_service, CacheService):
        raise KeyError("service_cache")

    recall_service = components.get("service_recall")
    if not isinstance(recall_service, RecallService):
        raise KeyError("service_recall")

    signal_adapter = components.get("adapter_signal")
    if signal_adapter is not None and not isinstance(signal_adapter, SignalAdapter):
        raise TypeError("adapter_signal")

    console_adapter = components.get("adapter_console")
    if console_adapter is not None and not isinstance(console_adapter, ConsoleAdapter):
        raise TypeError("adapter_console")

    brain_client = BrainSdkClient(source="relay", principal="operator")

    return build_relay_service(
        settings=settings,
        cache_service=cache_service,
        recall_service=recall_service,
        signal_adapter=signal_adapter,
        console_adapter=console_adapter,
        brain_client=brain_client,
    )
