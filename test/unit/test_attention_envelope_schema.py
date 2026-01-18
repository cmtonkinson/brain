"""Unit tests for notification envelope schema and persistence."""

from __future__ import annotations

from contextlib import closing

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from attention.envelope_schema import (
    EnvelopeDecision,
    NotificationEnvelope,
    validate_envelope_payload,
)
from models import NotificationEnvelope as EnvelopeRecord, NotificationProvenanceInput


def test_envelope_schema_accepts_valid_payload() -> None:
    """Ensure valid envelope payloads parse successfully."""
    payload = {
        "version": "1.0.0",
        "source_component": "scheduler",
        "origin_signal": "task.completed",
        "confidence": 0.82,
        "provenance": [
            {
                "input_type": "signal",
                "reference": "task:123",
                "description": "Task completion event",
            }
        ],
    }
    result = validate_envelope_payload(payload)

    assert result.decision == EnvelopeDecision.ACCEPT
    assert result.envelope is not None


def test_envelope_schema_missing_provenance_logs_only() -> None:
    """Ensure missing provenance triggers LOG_ONLY decision."""
    payload = {
        "version": "1.0.0",
        "source_component": "scheduler",
        "origin_signal": "task.completed",
        "confidence": 0.82,
    }
    result = validate_envelope_payload(payload)

    assert result.decision == EnvelopeDecision.LOG_ONLY
    assert result.envelope is None


def test_envelope_schema_rejects_invalid_confidence() -> None:
    """Ensure invalid confidence values fail validation."""
    with pytest.raises(ValidationError):
        NotificationEnvelope.model_validate(
            {
                "version": "1.0.0",
                "source_component": "scheduler",
                "origin_signal": "task.completed",
                "confidence": 1.5,
                "provenance": [
                    {
                        "input_type": "signal",
                        "reference": "task:123",
                    }
                ],
            }
        )


def test_provenance_inputs_persist_with_envelope(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure provenance inputs persist and link to the envelope."""
    session_factory = sqlite_session_factory
    envelope = EnvelopeRecord(
        version="1.0.0",
        source_component="scheduler",
        origin_signal="task.completed",
        confidence=0.9,
    )
    provenance = [
        NotificationProvenanceInput(
            input_type="signal",
            reference="task:123",
            description="Task completion event",
        ),
        NotificationProvenanceInput(
            input_type="input",
            reference="task_payload",
            description="Original payload",
        ),
    ]

    with closing(session_factory()) as session:
        session.add(envelope)
        session.flush()
        for entry in provenance:
            entry.envelope_id = envelope.id
            session.add(entry)
        session.commit()

        stored_envelope = session.get(EnvelopeRecord, envelope.id)
        stored_inputs = (
            session.query(NotificationProvenanceInput)
            .filter(NotificationProvenanceInput.envelope_id == envelope.id)
            .all()
        )

        assert stored_envelope is not None
        assert len(stored_inputs) == 2
