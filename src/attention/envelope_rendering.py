"""Render notification envelope metadata for supported channels."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from attention.envelope_schema import EnvelopeDecision
from models import NotificationEnvelope, NotificationProvenanceInput

logger = logging.getLogger(__name__)

SUPPORTED_CHANNELS = {"signal"}


@dataclass(frozen=True)
class EnvelopeRenderResult:
    """Result of rendering envelope metadata for a channel."""

    decision: str
    metadata: str | None
    error: str | None


def render_envelope_metadata(
    session: Session, envelope_id: int, channel: str
) -> EnvelopeRenderResult:
    """Render envelope metadata for the given channel."""
    try:
        if channel not in SUPPORTED_CHANNELS:
            raise ValueError(f"Unsupported channel: {channel}")
        envelope = session.get(NotificationEnvelope, envelope_id)
        if envelope is None:
            raise ValueError(f"Envelope not found: {envelope_id}")
        provenance = (
            session.query(NotificationProvenanceInput)
            .filter(NotificationProvenanceInput.envelope_id == envelope_id)
            .all()
        )
        metadata = _format_metadata(envelope, provenance)
        if channel == "signal":
            metadata = f"[{metadata}]"
        return EnvelopeRenderResult(
            decision=EnvelopeDecision.ACCEPT.value,
            metadata=metadata,
            error=None,
        )
    except Exception as exc:
        logger.exception("Envelope rendering failed for channel=%s", channel)
        return EnvelopeRenderResult(
            decision=EnvelopeDecision.LOG_ONLY.value,
            metadata=None,
            error=str(exc),
        )


def _format_metadata(
    envelope: NotificationEnvelope,
    provenance: list[NotificationProvenanceInput],
) -> str:
    """Format a compact metadata string for envelope provenance."""
    provenance_bits = [f"{entry.input_type}:{entry.reference}" for entry in provenance] or ["none"]
    prov = ",".join(provenance_bits)
    return f"src={envelope.source_component} " f"conf={envelope.confidence:.2f} " f"prov={prov}"
