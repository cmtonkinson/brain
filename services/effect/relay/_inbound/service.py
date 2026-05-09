"""Authoritative in-process Python API for Relay inbound service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lib.sdk.client import BrainClient
from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from lib.shared.inbound_adapter import InboundCallbackRegistrar
from lib.shared.inbound_message import InboundMessage
from services.effect.relay._outbound.service import RelayOutboundService
from services.reason.recall.service import RecallService
from services.state.cache.service import CacheService
from services.effect.relay._inbound.domain import (
    HealthStatus,
    IngestResult,
    RegisterInboundCallbacksResult,
)


class RelayInboundService(ABC):
    """Public API for inbound operator message ingestion and polling."""

    @abstractmethod
    def ingest_inbound_message(
        self,
        *,
        meta: EnvelopeMeta,
        message: InboundMessage,
    ) -> Envelope[IngestResult]:
        """Enqueue one normalized inbound operator message."""

    @abstractmethod
    def register_inbound_callbacks(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[RegisterInboundCallbacksResult]:
        """Register in-process inbound adapter callbacks."""

    @abstractmethod
    def poll_operator_instruction(
        self,
        *,
        meta: EnvelopeMeta,
        wait_timeout_seconds: float = 0.0,
    ) -> Envelope[InboundMessage | None]:
        """Pop the next queued operator instruction, optionally long-polling."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Relay inbound and dependency health state."""


def build_relay_inbound_service(
    *,
    settings: CoreRuntimeSettings,
    cache_service: CacheService,
    inbound_adapters: tuple[InboundCallbackRegistrar, ...] = (),
    outbound_service: RelayOutboundService | None = None,
    recall_service: RecallService | None = None,
    brain_client: BrainClient | None = None,
) -> RelayInboundService:
    """Build default Relay inbound implementation from typed settings."""
    from services.effect.relay._inbound.config import (
        resolve_relay_inbound_identity_settings,
        resolve_relay_inbound_service_settings,
    )
    from services.effect.relay._inbound.implementation import (
        DefaultRelayInboundService,
    )

    return DefaultRelayInboundService(
        settings=resolve_relay_inbound_service_settings(settings),
        identity=resolve_relay_inbound_identity_settings(settings),
        inbound_adapters=inbound_adapters,
        cache_service=cache_service,
        outbound_service=outbound_service,
        recall_service=recall_service,
        approval_response_settings=settings.core.profile.approval_responses,
        brain_client=brain_client,
    )
