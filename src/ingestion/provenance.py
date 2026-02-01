"""Provenance persistence helpers for ingestion stage outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import ProvenanceRecord, ProvenanceSource


@dataclass(frozen=True)
class ProvenanceSourceInput:
    """Normalized provenance source descriptor for persistence."""

    source_type: str
    source_uri: str | None
    source_actor: str | None
    captured_at: datetime


def record_provenance(
    session: Session,
    *,
    object_key: str,
    ingestion_id: UUID,
    sources: Iterable[ProvenanceSourceInput],
    now: datetime | None = None,
) -> ProvenanceRecord:
    """Create or update provenance records and deduped sources."""
    timestamp = now or datetime.now(timezone.utc)
    record = (
        session.query(ProvenanceRecord).filter(ProvenanceRecord.object_key == object_key).first()
    )
    if record is None:
        record = ProvenanceRecord(
            object_key=object_key,
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(record)
        session.flush()

    sources_list = list(sources)
    if sources_list:
        for source in sources_list:
            _validate_source(source)
            if _source_exists(session, record.id, ingestion_id, source):
                continue
            _insert_source(session, record.id, ingestion_id, source)
        record.updated_at = timestamp
        session.flush()
    return record


def _insert_source(
    session: Session,
    provenance_id: UUID,
    ingestion_id: UUID,
    source: ProvenanceSourceInput,
) -> None:
    """Insert a provenance source while treating duplicates as no-ops."""
    nested = session.begin_nested()
    try:
        session.add(
            ProvenanceSource(
                provenance_id=provenance_id,
                ingestion_id=ingestion_id,
                source_type=source.source_type,
                source_uri=source.source_uri,
                source_actor=source.source_actor,
                captured_at=source.captured_at,
            )
        )
        session.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()


def _validate_source(source: ProvenanceSourceInput) -> None:
    """Validate provenance source invariants before persistence."""
    if not source.source_type.strip():
        raise ValueError("source_type is required for provenance sources")
    if source.captured_at.tzinfo is None:
        raise ValueError("captured_at must be timezone-aware")


def _source_exists(
    session: Session,
    provenance_id: UUID,
    ingestion_id: UUID,
    source: ProvenanceSourceInput,
) -> bool:
    """Return True when the provenance source already exists."""
    query = session.query(ProvenanceSource).filter(
        ProvenanceSource.provenance_id == provenance_id,
        ProvenanceSource.ingestion_id == ingestion_id,
        ProvenanceSource.source_type == source.source_type,
    )
    if source.source_uri is None:
        query = query.filter(ProvenanceSource.source_uri.is_(None))
    else:
        query = query.filter(ProvenanceSource.source_uri == source.source_uri)
    if source.source_actor is None:
        query = query.filter(ProvenanceSource.source_actor.is_(None))
    else:
        query = query.filter(ProvenanceSource.source_actor == source.source_actor)
    return session.query(query.exists()).scalar() is True
