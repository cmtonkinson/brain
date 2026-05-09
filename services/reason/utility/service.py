"""Authoritative in-process Python API for Utility Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from services.reason.utility.domain import (
    ConvertedDateTime,
    CurrentDateTime,
    DurationUntil,
    HealthStatus,
    ParsedDateTime,
    TextChunk,
)


class UtilityService(ABC):
    """Public API for lightweight reusable utility operations."""

    @abstractmethod
    def current_datetime(self, *, meta: EnvelopeMeta) -> Envelope[CurrentDateTime]:
        """Return current UTC and operator-local datetimes."""

    @abstractmethod
    def parse_datetime(
        self, *, meta: EnvelopeMeta, timestamp: str, timezone: str | None = None
    ) -> Envelope[ParsedDateTime]:
        """Parse an ISO-like datetime and return normalized projections."""

    @abstractmethod
    def convert_datetime(
        self,
        *,
        meta: EnvelopeMeta,
        timestamp: str,
        to_timezone: str,
        from_timezone: str | None = None,
    ) -> Envelope[ConvertedDateTime]:
        """Convert an ISO-like datetime into another timezone."""

    @abstractmethod
    def duration_until(
        self,
        *,
        meta: EnvelopeMeta,
        target_timestamp: str,
        target_timezone: str | None = None,
        now_timestamp: str | None = None,
        now_timezone: str | None = None,
    ) -> Envelope[DurationUntil]:
        """Return the signed duration from now, or a supplied instant, to target."""

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
    from services.reason.utility.implementation import DefaultUtilityService

    return DefaultUtilityService(
        preferred_timezone=settings.core.profile.preferred_timezone
    )
