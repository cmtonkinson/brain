"""Unit tests for envelope metadata rendering."""

from __future__ import annotations

from contextlib import closing

import pytest
from sqlalchemy.orm import sessionmaker

from attention.envelope_rendering import render_envelope_metadata
from attention.envelope_schema import EnvelopeDecision
from models import NotificationEnvelope, NotificationProvenanceInput


def _seed_envelope(session) -> int:
    """Insert a notification envelope with provenance and return its id."""
    envelope = NotificationEnvelope(
        version="1.0.0",
        source_component="scheduler",
        origin_signal="task.completed",
        confidence=0.85,
    )
    session.add(envelope)
    session.flush()
    session.add(
        NotificationProvenanceInput(
            envelope_id=envelope.id,
            input_type="signal",
            reference="task:123",
            description="Task completion event",
        )
    )
    session.flush()
    return envelope.id


def test_signal_envelope_renders_compact_metadata(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure Signal metadata renders compact envelope information."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        envelope_id = _seed_envelope(session)
        session.commit()

        result = render_envelope_metadata(session, envelope_id, "signal")

    assert result.decision == EnvelopeDecision.ACCEPT.value
    assert result.metadata is not None
    assert "src=scheduler" in result.metadata
    assert "conf=0.85" in result.metadata
    assert "prov=signal:task:123" in result.metadata


def test_digest_envelope_renders_compact_metadata(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure Digest metadata renders compact envelope information."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        envelope_id = _seed_envelope(session)
        session.commit()

        result = render_envelope_metadata(session, envelope_id, "digest")

    assert result.decision == EnvelopeDecision.ACCEPT.value
    assert result.metadata is not None
    assert "src=scheduler" in result.metadata
    assert "conf=0.85" in result.metadata
    assert "prov=signal:task:123" in result.metadata


def test_rendering_failure_returns_log_only(
    caplog: pytest.LogCaptureFixture,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure rendering failures default to LOG_ONLY and log errors."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        result = render_envelope_metadata(session, 999, "signal")

    assert result.decision == EnvelopeDecision.LOG_ONLY.value
    assert result.metadata is None
    assert any(record.levelname == "ERROR" for record in caplog.records)
