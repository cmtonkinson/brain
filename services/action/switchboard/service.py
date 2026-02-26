"""Authoritative in-process Python API for Switchboard Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.signal.adapter import SignalAdapter
from services.state.cache_authority.service import CacheAuthorityService
from services.action.switchboard.domain import (
    HealthStatus,
    IngestResult,
    RegisterSignalWebhookResult,
)


class SwitchboardService(ABC):
    """Public API for webhook registration and inbound Signal ingestion."""

    @abstractmethod
    def ingest_signal_webhook(
        self,
        *,
        meta: EnvelopeMeta,
        raw_body_json: str,
        header_timestamp: str,
        header_signature: str,
    ) -> Envelope[IngestResult]:
        """Validate, normalize, and enqueue one Signal webhook payload."""

    @abstractmethod
    def register_signal_webhook(
        self,
        *,
        meta: EnvelopeMeta,
        callback_url: str,
    ) -> Envelope[RegisterSignalWebhookResult]:
        """Register Signal webhook callback URI and shared secret."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Switchboard and dependency health state."""


def build_switchboard_service(
    *,
    settings: BrainSettings,
    cache_service: CacheAuthorityService,
    signal_adapter: SignalAdapter | None = None,
) -> SwitchboardService:
    """Build default Switchboard implementation from typed settings."""
    from resources.adapters.signal import (
        HttpSignalAdapter,
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
        or HttpSignalAdapter(settings=resolve_signal_adapter_settings(settings)),
        cache_service=cache_service,
    )


def build_switchboard_service_from_settings(
    *,
    settings: BrainSettings,
    cache_service: CacheAuthorityService,
) -> SwitchboardService:
    """Backward-compatible helper retaining previous from-settings behavior."""
    return build_switchboard_service(
        settings=settings,
        cache_service=cache_service,
    )
