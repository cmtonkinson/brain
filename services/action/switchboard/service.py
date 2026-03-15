"""Authoritative in-process Python API for Switchboard Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.signal.adapter import SignalAdapter
from services.action.attention_router.service import AttentionRouterService
from services.state.cache_authority.service import CacheAuthorityService
from services.action.switchboard.domain import (
    HealthStatus,
    IngestResult,
    NormalizedSignalMessage,
    RegisterSignalCallbackResult,
)


class SwitchboardService(ABC):
    """Public API for inbound Signal ingestion and operator polling."""

    @abstractmethod
    def ingest_signal_message(
        self,
        *,
        meta: EnvelopeMeta,
        raw_body_json: str,
    ) -> Envelope[IngestResult]:
        """Normalize and enqueue one raw inbound Signal payload."""

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
    ) -> Envelope[NormalizedSignalMessage | None]:
        """Pop the next queued operator instruction, optionally long-polling."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Switchboard and dependency health state."""


def build_switchboard_service(
    *,
    settings: CoreRuntimeSettings,
    cache_service: CacheAuthorityService,
    signal_adapter: SignalAdapter | None = None,
    attention_router_service: AttentionRouterService | None = None,
) -> SwitchboardService:
    """Build default Switchboard implementation from typed settings."""
    from resources.adapters.signal import (
        SignalRestApiAdapter,
        resolve_signal_adapter_settings,
    )
    from services.action.switchboard.config import (
        resolve_switchboard_identity_settings,
        resolve_switchboard_service_settings,
    )
    from services.action.switchboard.implementation import DefaultSwitchboardService

    return DefaultSwitchboardService(
        settings=resolve_switchboard_service_settings(settings),
        identity=resolve_switchboard_identity_settings(settings),
        adapter=signal_adapter
        or SignalRestApiAdapter(settings=resolve_signal_adapter_settings(settings)),
        cache_service=cache_service,
        attention_router_service=attention_router_service,
        approval_response_settings=settings.core.profile.approval_responses,
    )


def build_switchboard_service_from_settings(
    *,
    settings: CoreRuntimeSettings,
    cache_service: CacheAuthorityService,
    attention_router_service: AttentionRouterService | None = None,
) -> SwitchboardService:
    """Backward-compatible helper retaining previous from-settings behavior."""
    return build_switchboard_service(
        settings=settings,
        cache_service=cache_service,
        attention_router_service=attention_router_service,
    )
