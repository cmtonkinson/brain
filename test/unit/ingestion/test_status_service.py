"""Unit tests for ingestion status service surface."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from ingestion.errors import IngestionNotFound
from ingestion.service import get_ingestion_status
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


def test_get_ingestion_status_returns_snapshot(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Service should return status for existing ingestions."""
    ingestion = _create_ingestion(sqlite_session_factory)

    status = get_ingestion_status(
        ingestion.id,
        session_factory=sqlite_session_factory,
    )

    assert status.ingestion_id == ingestion.id
    assert status.status == "queued"
    assert status.last_error is None


def test_get_ingestion_status_raises_not_found(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Service should surface not-found distinctly."""
    with pytest.raises(IngestionNotFound):
        get_ingestion_status(uuid.uuid4(), session_factory=sqlite_session_factory)
