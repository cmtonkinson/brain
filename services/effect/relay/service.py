"""Authoritative in-process Python API for Relay Service.

Relay combines inbound (operator->Brain) ingestion, outbound (Brain->operator)
notification routing, and approval-token correlation into one bidirectional
comms surface owning the Signal adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from lib.sdk.client import BrainClient
from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from lib.shared.inbound_message import InboundMessage
from resources.adapters.console.adapter import ConsoleAdapter
from resources.adapters.signal.adapter import SignalAdapter

from services.effect.relay._outbound.domain import (
    ApprovalCorrelationPayload,
    ApprovalNotificationPayload,
    RouteNotificationResult,
)
from services.effect.relay._inbound.domain import (
    IngestResult,
    RegisterInboundCallbacksResult,
)
from services.effect.relay.domain import RelayHealthStatus
from services.reason.recall.service import (
    ConversationalMemoryContext,
    RecallService,
)
from services.state.cache.service import CacheService


class RelayService(ABC):
    """Public API for bidirectional operator comms (inbound + outbound + approval)."""

    # --- Inbound (operator -> Brain) ---

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

    # --- Outbound (Brain -> operator) ---

    @abstractmethod
    def route_notification(
        self,
        *,
        meta: EnvelopeMeta,
        actor: str = "operator",
        channel: str = "",
        title: str = "",
        message: str,
        dedupe_key: str = "",
        batch_key: str = "",
        force: bool = False,
        conversational_memory: ConversationalMemoryContext | None = None,
    ) -> Envelope[RouteNotificationResult]:
        """Route one outbound notification and decide suppress/send/batch."""

    @abstractmethod
    def route_approval_notification(
        self,
        *,
        meta: EnvelopeMeta,
        approval: ApprovalNotificationPayload,
    ) -> Envelope[RouteNotificationResult]:
        """Route one Policy approval notification."""

    @abstractmethod
    def flush_batch(
        self,
        *,
        meta: EnvelopeMeta,
        batch_key: str,
        actor: str = "operator",
        channel: str = "",
        title: str = "",
    ) -> Envelope[RouteNotificationResult]:
        """Flush one pending batch by key and deliver consolidated summary."""

    # --- Approval correlation (bidirectional) ---

    @abstractmethod
    def correlate_approval_response(
        self,
        *,
        meta: EnvelopeMeta,
        actor: str,
        channel: str,
        message_text: str = "",
        approval_token: str = "",
        reply_to_proposal_token: str = "",
        reaction_to_proposal_token: str = "",
    ) -> Envelope[ApprovalCorrelationPayload]:
        """Normalize inbound approval-correlation fields for Policy Service."""

    @abstractmethod
    def resolve_approval_notification_proposal_token(
        self,
        *,
        meta: EnvelopeMeta,
        channel: str,
        target_timestamp_ms: int,
    ) -> Envelope[str | None]:
        """Resolve one outbound approval notification timestamp to a proposal token."""

    # --- Health ---

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[RelayHealthStatus]:
        """Return overall Relay readiness across inbound/outbound/adapter."""


def build_relay_service(
    *,
    settings: CoreRuntimeSettings,
    cache_service: CacheService,
    recall_service: RecallService,
    signal_adapter: SignalAdapter | None = None,
    console_adapter: ConsoleAdapter | None = None,
    brain_client: BrainClient | None = None,
) -> RelayService:
    """Build the default Relay implementation from typed settings."""
    from resources.adapters.console import (
        ConsoleAdapterSettings,
        InProcessConsoleAdapter,
    )
    from resources.adapters.signal import (
        SignalRestApiAdapter,
        resolve_signal_adapter_settings,
    )
    from services.effect.relay._outbound.implementation import (
        DefaultRelayOutboundService,
    )
    from services.effect.relay._inbound.implementation import (
        DefaultRelayInboundService,
    )
    from services.effect.relay.config import resolve_relay_settings
    from services.effect.relay.implementation import DefaultRelayService

    relay_settings = resolve_relay_settings(settings)
    adapter_settings = resolve_signal_adapter_settings(settings)
    adapter = signal_adapter or SignalRestApiAdapter(settings=adapter_settings)
    console = console_adapter or InProcessConsoleAdapter(
        settings=ConsoleAdapterSettings()
    )
    inbound_adapters = (
        (adapter, console) if adapter_settings.receive_e164 else (console,)
    )

    inbound = DefaultRelayInboundService(
        settings=relay_settings.inbound,
        identity=relay_settings.identity,
        inbound_adapters=inbound_adapters,
        cache_service=cache_service,
        outbound_service=None,
        recall_service=recall_service,
        approval_response_settings=settings.core.profile.approval_responses,
        brain_client=brain_client,
    )
    outbound = DefaultRelayOutboundService(
        settings=relay_settings.outbound,
        operator_signal_contact_e164=settings.core.profile.operator.signal_contact_e164,
        signal_adapter=adapter,
        signal_receive_e164=adapter_settings.receive_e164,
        console_response_queue_name=relay_settings.inbound.console_response_queue_name,
        cache_service=cache_service,
        recall_service=recall_service,
    )
    relay = DefaultRelayService(inbound=inbound, outbound=outbound)
    inbound._outbound_service = relay
    return relay
