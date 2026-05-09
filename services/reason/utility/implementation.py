"""Concrete Utility Service implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from lib.shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
)
from lib.shared.errors import ErrorDetail, codes, validation_error
from lib.shared.logging import get_logger, public_api_instrumented
from services.reason.utility.component import SERVICE_COMPONENT_ID
from services.reason.utility.domain import (
    ConvertedDateTime,
    CurrentDateTime,
    DurationUntil,
    HealthStatus,
    ParsedDateTime,
    TextChunk,
)
from services.reason.utility.service import UtilityService

_LOGGER = get_logger(__name__)


class DefaultUtilityService(UtilityService):
    """Default Utility Service implementation for simple text helpers."""

    def __init__(self, *, preferred_timezone: str = "UTC") -> None:
        """Create utility helpers using the configured operator timezone."""
        self._preferred_timezone = preferred_timezone

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def current_datetime(self, *, meta: EnvelopeMeta) -> Envelope[CurrentDateTime]:
        """Return current UTC and operator-local datetimes."""
        validate_meta(meta)

        current_utc = datetime.now(UTC)
        local_tz = ZoneInfo(self._preferred_timezone)
        current_local = current_utc.astimezone(local_tz)
        return success(
            meta=meta,
            payload=CurrentDateTime(
                utc_timestamp=current_utc.isoformat(),
                local_timestamp=current_local.isoformat(),
                local_timezone=self._preferred_timezone,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def parse_datetime(
        self, *, meta: EnvelopeMeta, timestamp: str, timezone: str | None = None
    ) -> Envelope[ParsedDateTime]:
        """Parse an ISO-like datetime and return normalized projections."""
        validate_meta(meta)

        timezone_name = timezone or self._preferred_timezone
        parsed, error = _parse_timestamp(
            timestamp=timestamp, timezone_name=timezone_name
        )
        if error is not None:
            return failure(meta=meta, errors=[error])
        assert parsed is not None
        local = parsed.astimezone(ZoneInfo(timezone_name))
        utc = parsed.astimezone(UTC)
        return success(
            meta=meta,
            payload=ParsedDateTime(
                input_timestamp=timestamp,
                local_timestamp=local.isoformat(),
                local_timezone=timezone_name,
                utc_timestamp=utc.isoformat(),
                unix_timestamp=utc.timestamp(),
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def convert_datetime(
        self,
        *,
        meta: EnvelopeMeta,
        timestamp: str,
        to_timezone: str,
        from_timezone: str | None = None,
    ) -> Envelope[ConvertedDateTime]:
        """Convert an ISO-like datetime into another timezone."""
        validate_meta(meta)

        source_timezone = from_timezone or self._preferred_timezone
        parsed, error = _parse_timestamp(
            timestamp=timestamp, timezone_name=source_timezone
        )
        if error is not None:
            return failure(meta=meta, errors=[error])
        target_tz, error = _load_timezone(to_timezone)
        if error is not None:
            return failure(meta=meta, errors=[error])
        assert parsed is not None
        assert target_tz is not None
        converted = parsed.astimezone(target_tz)
        utc = parsed.astimezone(UTC)
        return success(
            meta=meta,
            payload=ConvertedDateTime(
                input_timestamp=timestamp,
                from_timezone=source_timezone,
                to_timezone=to_timezone,
                converted_timestamp=converted.isoformat(),
                utc_timestamp=utc.isoformat(),
                unix_timestamp=utc.timestamp(),
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
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
        validate_meta(meta)

        target, error = _parse_timestamp(
            timestamp=target_timestamp,
            timezone_name=target_timezone or self._preferred_timezone,
        )
        if error is not None:
            return failure(meta=meta, errors=[error])
        if now_timestamp is None:
            now = datetime.now(UTC)
        else:
            now, error = _parse_timestamp(
                timestamp=now_timestamp,
                timezone_name=now_timezone or self._preferred_timezone,
            )
            if error is not None:
                return failure(meta=meta, errors=[error])
        assert target is not None
        assert now is not None
        now_utc = now.astimezone(UTC)
        target_utc = target.astimezone(UTC)
        seconds = (target_utc - now_utc).total_seconds()
        return success(
            meta=meta,
            payload=DurationUntil(
                now_timestamp=now_utc.isoformat(),
                target_timestamp=target_utc.isoformat(),
                seconds=seconds,
                minutes=seconds / 60,
                hours=seconds / 3600,
                days=seconds / 86400,
                is_past=seconds < 0,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def chunk_text(self, *, meta: EnvelopeMeta, text: str) -> Envelope[list[TextChunk]]:
        """Return a trivial single-chunk split for non-empty content."""
        validate_meta(meta)

        if text == "":
            return success(meta=meta, payload=[])

        return success(
            meta=meta,
            payload=[
                TextChunk(
                    chunk_ordinal=0,
                    text=text,
                    reference_range=f"0:{len(text)}",
                )
            ],
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Utility Service readiness state."""
        validate_meta(meta)

        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                detail="ok",
            ),
        )


def _load_timezone(timezone_name: str) -> tuple[ZoneInfo | None, ErrorDetail | None]:
    try:
        return ZoneInfo(timezone_name), None
    except (KeyError, ValueError) as exc:
        return None, validation_error(
            f"invalid timezone '{timezone_name}': {exc}", code=codes.INVALID_ARGUMENT
        )


def _parse_timestamp(
    *, timestamp: str, timezone_name: str
) -> tuple[datetime | None, ErrorDetail | None]:
    tz, error = _load_timezone(timezone_name)
    if error is not None:
        return None, error
    assert tz is not None
    normalized = timestamp.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        return None, validation_error(
            f"invalid timestamp '{timestamp}': {exc}", code=codes.INVALID_ARGUMENT
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed, None
