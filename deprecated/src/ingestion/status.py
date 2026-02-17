"""Data access helpers for ingestion status lookups."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from ingestion.errors import IngestionNotFound
from models import Ingestion


@dataclass(frozen=True)
class IngestionStatus:
    """Status and error snapshot for an ingestion attempt."""

    ingestion_id: UUID
    status: str
    last_error: str | None


def fetch_ingestion_status(session: Session, ingestion_id: UUID) -> IngestionStatus:
    """Fetch ingestion status for the given identifier."""
    ingestion = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
    if ingestion is None:
        raise IngestionNotFound(ingestion_id)
    return IngestionStatus(
        ingestion_id=ingestion.id,
        status=str(ingestion.status),
        last_error=ingestion.last_error,
    )
