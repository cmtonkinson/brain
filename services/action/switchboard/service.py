"""Authoritative in-process Python API for Switchboard Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.envelope import Envelope, EnvelopeMeta
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
        shared_secret_ref: str,
    ) -> Envelope[RegisterSignalWebhookResult]:
        """Register Signal webhook callback URI and shared secret."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Switchboard and dependency health state."""
