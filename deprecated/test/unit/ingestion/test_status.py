"""Unit tests for ingestion status data access."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from ingestion.errors import IngestionNotFound
from ingestion.status import fetch_ingestion_status
from models import Ingestion


def _create_ingestion(session_factory: sessionmaker) -> Ingestion:
    """Create and persist an ingestion record for tests."""
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        ingestion = Ingestion(
            source_type="signal",
            source_uri="signal://msg/123",
            source_actor="user-1",
            created_at=now,
            status="queued",
            last_error=None,
        )
        session.add(ingestion)
        session.commit()
        session.refresh(ingestion)
        return ingestion


def test_fetch_ingestion_status_returns_snapshot(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Existing ingestion IDs should return status and last_error."""
    ingestion = _create_ingestion(sqlite_session_factory)

    with closing(sqlite_session_factory()) as session:
        status = fetch_ingestion_status(session, ingestion.id)

    assert status.ingestion_id == ingestion.id
    assert status.status == "queued"
    assert status.last_error is None


def test_fetch_ingestion_status_raises_not_found(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Unknown ingestion IDs should raise a not-found error."""
    with closing(sqlite_session_factory()) as session:
        with pytest.raises(IngestionNotFound):
            fetch_ingestion_status(session, uuid.uuid4())
