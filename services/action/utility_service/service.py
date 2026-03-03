"""Authoritative in-process Python API for Utility Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from services.action.utility_service.domain import HealthStatus, TextChunk


class UtilityService(ABC):
    """Public API for lightweight reusable utility operations."""

    @abstractmethod
    def current_datetime(self, *, meta: EnvelopeMeta) -> Envelope[datetime]:
        """Return the current UTC datetime."""

    @abstractmethod
    def chunk_text(self, *, meta: EnvelopeMeta, text: str) -> Envelope[list[TextChunk]]:
        """Return one or more chunks for the provided text content."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Utility Service readiness state."""


def build_utility_service(
    *,
    settings: CoreRuntimeSettings,
) -> UtilityService:
    """Build default Utility Service implementation from typed settings."""
    from services.action.utility_service.implementation import DefaultUtilityService

    del settings
    return DefaultUtilityService()
