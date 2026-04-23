"""Authoritative in-process Python API for Utility Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from services.action.utility_service.domain import (
    CurrentDateTime,
    HealthStatus,
    TextChunk,
)


class UtilityService(ABC):
    """Public API for lightweight reusable utility operations."""

    @abstractmethod
    def current_datetime(self, *, meta: EnvelopeMeta) -> Envelope[CurrentDateTime]:
        """Return current UTC and operator-local datetimes."""

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

    return DefaultUtilityService(
        preferred_timezone=settings.core.profile.preferred_timezone
    )
