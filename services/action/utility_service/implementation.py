"""Concrete Utility Service implementation."""

from __future__ import annotations

from datetime import datetime

from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    utc_now,
    validate_meta,
)
from packages.brain_shared.errors import codes, validation_error
from packages.brain_shared.logging import get_logger, public_api_instrumented
from services.action.utility_service.component import SERVICE_COMPONENT_ID
from services.action.utility_service.domain import HealthStatus, TextChunk
from services.action.utility_service.service import UtilityService

_LOGGER = get_logger(__name__)


class DefaultUtilityService(UtilityService):
    """Default Utility Service implementation for simple text helpers."""

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def current_datetime(self, *, meta: EnvelopeMeta) -> Envelope[datetime]:
        """Return the current UTC datetime."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        return success(meta=meta, payload=utc_now())

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
