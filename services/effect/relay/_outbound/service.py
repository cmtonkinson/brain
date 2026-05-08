"""Authoritative in-process Python API for Relay outbound service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.signal.adapter import SignalAdapter
from services.effect.relay._outbound.domain import (
    ApprovalCorrelationPayload,
    ApprovalNotificationPayload,
    ConsoleResponseMessage,
    HealthStatus,
    RouteNotificationResult,
)
from services.reason.recall.service import (
    ConversationalMemoryContext,
    RecallService,
)
from services.state.cache.service import CacheService


class RelayOutboundService(ABC):
    """Public API for policy-aware outbound notification routing."""

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
        recipient_e164: str = "",
        sender_e164: str = "",
        title: str = "",
    ) -> Envelope[RouteNotificationResult]:
        """Flush one pending batch by key and deliver consolidated summary."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Relay outbound and adapter health state."""

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

    @abstractmethod
    def poll_console_response(
        self,
        *,
        meta: EnvelopeMeta,
        wait_timeout_seconds: float = 0.0,
    ) -> Envelope[ConsoleResponseMessage | None]:
        """Pop the next queued console response, optionally long-polling."""


def build_outbound_service(
    *,
    settings: CoreRuntimeSettings,
    signal_adapter: SignalAdapter | None = None,
    console_response_queue_name: str,
    cache_service: CacheService | None = None,
    recall_service: RecallService | None = None,
) -> RelayOutboundService:
    """Build default Relay outbound implementation from typed settings."""
    from resources.adapters.signal import (
        SignalRestApiAdapter,
        resolve_signal_adapter_settings,
    )
    from services.effect.relay._outbound.config import (
        resolve_relay_outbound_service_settings,
    )
    from services.effect.relay._outbound.implementation import (
        DefaultRelayOutboundService,
    )

    adapter_settings = resolve_signal_adapter_settings(settings)
    return DefaultRelayOutboundService(
        settings=resolve_relay_outbound_service_settings(settings),
        operator_signal_contact_e164=settings.core.profile.operator.signal_contact_e164,
        signal_adapter=signal_adapter
        or SignalRestApiAdapter(settings=adapter_settings),
        signal_receive_e164=adapter_settings.receive_e164,
        console_response_queue_name=console_response_queue_name,
        cache_service=cache_service,
        recall_service=recall_service,
    )
