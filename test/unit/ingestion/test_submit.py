"""Unit tests for ingestion submit service."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from ingestion.errors import IngestionRequestRejected
from ingestion.schema import IngestionRequest
from ingestion.submit import submit_ingestion
from models import Ingestion


def _valid_request() -> IngestionRequest:
    """Return a minimal valid ingestion request."""
    return IngestionRequest(
        source_type="signal",
        source_uri="signal://msg/123",
        source_actor="user-1",
        payload=b"hello",
        capture_time=datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
    )


def test_submit_ingestion_persists_queued_status(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Valid submissions should persist queued ingestion attempts."""
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    response = submit_ingestion(
        _valid_request(),
        session_factory=sqlite_session_factory,
        now=now,
    )

    with closing(sqlite_session_factory()) as session:
        record = session.query(Ingestion).filter(Ingestion.id == response.ingestion_id).first()

    assert record is not None
    assert str(record.status) == "queued"
    assert record.last_error is None
    assert record.created_at == now.replace(tzinfo=None)


def test_submit_ingestion_rejects_invalid_request_and_persists_failure(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Invalid submissions should persist a failed ingestion and raise."""
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    payload = {
        "source_uri": "signal://msg/123",
        "payload": "hello",
        "capture_time": datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
    }

    with pytest.raises(IngestionRequestRejected) as excinfo:
        submit_ingestion(payload, session_factory=sqlite_session_factory, now=now)

    ingestion_id = excinfo.value.ingestion_id

    with closing(sqlite_session_factory()) as session:
        record = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()

    assert record is not None
    assert str(record.status) == "failed"
    assert record.last_error
    assert record.source_type == "unknown"
    assert record.created_at == now.replace(tzinfo=None)


def test_submit_ingestion_generates_unique_ids(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Multiple submissions should generate distinct ingestion IDs."""
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    response_one = submit_ingestion(
        _valid_request(),
        session_factory=sqlite_session_factory,
        now=now,
    )
    response_two = submit_ingestion(
        _valid_request(),
        session_factory=sqlite_session_factory,
        now=now,
    )

    assert response_one.ingestion_id != response_two.ingestion_id
    assert isinstance(response_one.ingestion_id, uuid.UUID)
    assert isinstance(response_two.ingestion_id, uuid.UUID)
