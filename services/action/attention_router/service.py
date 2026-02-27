"""Authoritative in-process Python API for Attention Router Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.signal.adapter import SignalAdapter
from services.action.attention_router.domain import (
    ApprovalCorrelationPayload,
    ApprovalNotificationPayload,
    HealthStatus,
    RouteNotificationResult,
)


class AttentionRouterService(ABC):
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
        recipient_e164: str = "",
        sender_e164: str = "",
        dedupe_key: str = "",
        batch_key: str = "",
        force: bool = False,
    ) -> Envelope[RouteNotificationResult]:
        """Route one outbound notification and decide suppress/send/batch."""

    @abstractmethod
    def route_approval_notification(
        self,
        *,
        meta: EnvelopeMeta,
        approval: ApprovalNotificationPayload,
    ) -> Envelope[RouteNotificationResult]:
        """Route one token-only Policy->Attention approval notification."""

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
        """Return Attention Router and adapter health state."""

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


def build_attention_router_service(
    *,
    settings: CoreRuntimeSettings,
    signal_adapter: SignalAdapter | None = None,
) -> AttentionRouterService:
    """Build default Attention Router implementation from typed settings."""
    from resources.adapters.signal import (
        HttpSignalAdapter,
        resolve_signal_adapter_settings,
    )
    from services.action.attention_router.config import (
        resolve_attention_router_service_settings,
    )
    from services.action.attention_router.implementation import (
        DefaultAttentionRouterService,
    )

    return DefaultAttentionRouterService(
        settings=resolve_attention_router_service_settings(settings),
        signal_adapter=signal_adapter
        or HttpSignalAdapter(settings=resolve_signal_adapter_settings(settings)),
    )
