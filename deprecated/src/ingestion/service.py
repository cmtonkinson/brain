"""Public ingestion status service surface."""

from __future__ import annotations

from contextlib import closing
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from ingestion.status import IngestionStatus, fetch_ingestion_status
from services.database import get_sync_session


def get_ingestion_status(
    ingestion_id: UUID,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> IngestionStatus:
    """Return the ingestion status for a given ingestion identifier."""
    session_factory = session_factory or get_sync_session
    with closing(session_factory()) as session:
        return fetch_ingestion_status(session, ingestion_id)
