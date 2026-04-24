"""Authoritative in-process Python API for Relay inbound service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lib.sdk.client import BrainClient
from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.signal.adapter import SignalAdapter
from services.effect.relay._outbound.service import RelayOutboundService
from services.reason.recall.service import RecallService
from services.state.cache.service import CacheService
from services.effect.relay._inbound.domain import (
    ConsoleEnqueueResult,
    HealthStatus,
    IngestResult,
    NormalizedOperatorMessage,
    RegisterSignalCallbackResult,
)


class RelayInboundService(ABC):
    """Public API for inbound operator message ingestion and polling."""

    @abstractmethod
    def ingest_signal_message(
        self,
        *,
        meta: EnvelopeMeta,
        raw_body_json: str,
    ) -> Envelope[IngestResult]:
        """Normalize and enqueue one raw inbound Signal payload."""

    @abstractmethod
    def enqueue_console_message(
        self,
        *,
        meta: EnvelopeMeta,
        message_text: str,
    ) -> Envelope[ConsoleEnqueueResult]:
        """Normalize and enqueue one inbound console message."""

    @abstractmethod
    def register_signal_callback(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[RegisterSignalCallbackResult]:
        """Register one in-process Signal callback with the owned adapter."""

    @abstractmethod
    def poll_operator_instruction(
        self,
        *,
        meta: EnvelopeMeta,
        wait_timeout_seconds: float = 0.0,
    ) -> Envelope[NormalizedOperatorMessage | None]:
        """Pop the next queued operator instruction, optionally long-polling."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Relay inbound and dependency health state."""


def build_relay_inbound_service(
    *,
    settings: CoreRuntimeSettings,
    cache_service: CacheService,
    signal_adapter: SignalAdapter | None = None,
    outbound_service: RelayOutboundService | None = None,
    recall_service: RecallService | None = None,
    brain_client: BrainClient | None = None,
) -> RelayInboundService:
    """Build default Relay inbound implementation from typed settings."""
    from resources.adapters.signal import (
        SignalRestApiAdapter,
        resolve_signal_adapter_settings,
    )
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
        adapter=signal_adapter
        or SignalRestApiAdapter(settings=resolve_signal_adapter_settings(settings)),
        cache_service=cache_service,
        outbound_service=outbound_service,
        recall_service=recall_service,
        approval_response_settings=settings.core.profile.approval_responses,
        brain_client=brain_client,
    )
