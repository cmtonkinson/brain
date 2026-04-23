"""Concrete Utility Service implementation."""

from __future__ import annotations

from datetime import UTC
from zoneinfo import ZoneInfo

from lib.shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    utc_now,
    validate_meta,
)
from lib.shared.errors import codes, validation_error
from lib.shared.logging import get_logger, public_api_instrumented
from services.action.utility_service.component import SERVICE_COMPONENT_ID
from services.action.utility_service.domain import (
    CurrentDateTime,
    HealthStatus,
    TextChunk,
)
from services.action.utility_service.service import UtilityService

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
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        current_utc = utc_now().astimezone(UTC)
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
    def chunk_text(self, *, meta: EnvelopeMeta, text: str) -> Envelope[list[TextChunk]]:
        """Return a trivial single-chunk split for non-empty content."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        if not isinstance(text, str):
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        "text must be a string",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )

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
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                detail="ok",
            ),
        )
