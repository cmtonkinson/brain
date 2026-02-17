"""Helpers for triggering indexed handoffs and embeddings dispatch after anchoring."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from models import (
    Artifact,
    IngestionArtifact,
    IngestionEmbeddingDispatch,
    IngestionIndexUpdate,
)
from services.database import get_sync_session

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexUpdateOutcome:
    """Result of a recorded index-update initiation."""

    ingestion_id: UUID
    status: str
    error: str | None


@dataclass(frozen=True)
class EmbeddingDispatchOutcome:
    """Result of a per-artifact embeddings dispatch attempt."""

    ingestion_id: UUID
    normalized_object_key: str
    status: str
    error: str | None


def trigger_index_update(
    ingestion_id: UUID,
    *,
    dispatcher: Callable[[UUID], None] | None = None,
    session_factory: Callable[[], Session] | None = None,
    now: datetime | None = None,
) -> IndexUpdateOutcome:
    """Initiate an index-update action and record the durable outcome."""
    dispatcher = dispatcher or _default_index_dispatcher
    session_factory = session_factory or get_sync_session
    timestamp = now or datetime.now(timezone.utc)
    status = "success"
    error: str | None = None
    try:
        dispatcher(ingestion_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.exception("Index update dispatcher failed for ingestion=%s", ingestion_id)
        status = "failed"
        error = str(exc)
    _persist_index_update(
        session_factory=session_factory,
        ingestion_id=ingestion_id,
        status=status,
        error=error,
        created_at=timestamp,
    )
    return IndexUpdateOutcome(ingestion_id=ingestion_id, status=status, error=error)


def dispatch_embeddings_for_ingestion(
    ingestion_id: UUID,
    *,
    dispatcher: Callable[[UUID, str], None] | None = None,
    session_factory: Callable[[], Session] | None = None,
    now: datetime | None = None,
) -> tuple[EmbeddingDispatchOutcome, ...]:
    """Dispatch embeddings work for normalized artifacts linked to the ingestion."""
    dispatcher = dispatcher or _default_embeddings_dispatcher
    session_factory = session_factory or get_sync_session
    timestamp = now or datetime.now(timezone.utc)
    normalized_keys = _load_normalized_artifact_keys(session_factory, ingestion_id)
    outcomes: list[EmbeddingDispatchOutcome] = []
    for object_key in normalized_keys:
        status = "success"
        error: str | None = None
        try:
            dispatcher(ingestion_id, object_key)
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.exception(
                "Embeddings dispatcher failed for ingestion=%s object=%s",
                ingestion_id,
                object_key,
            )
            status = "failed"
            error = str(exc)
        _persist_embeddings_dispatch(
            session_factory=session_factory,
            ingestion_id=ingestion_id,
            object_key=object_key,
            status=status,
            error=error,
            created_at=timestamp,
        )
        outcomes.append(
            EmbeddingDispatchOutcome(
                ingestion_id=ingestion_id,
                normalized_object_key=object_key,
                status=status,
                error=error,
            )
        )
    return tuple(outcomes)


def _default_index_dispatcher(ingestion_id: UUID) -> None:
    """Default index-update dispatcher that is a no-op (for future wiring)."""
    LOGGER.info("Index update initiated for ingestion=%s", ingestion_id)


def _default_embeddings_dispatcher(ingestion_id: UUID, object_key: str) -> None:
    """Default embeddings dispatcher stub that logs the action."""
    LOGGER.info(
        "Embeddings dispatch initiated for ingestion=%s artifact=%s",
        ingestion_id,
        object_key,
    )


def _load_normalized_artifact_keys(
    session_factory: Callable[[], Session],
    ingestion_id: UUID,
) -> list[str]:
    """Return normalized artifact keys associated with the ingestion."""
    with closing(session_factory()) as session:
        rows = (
            session.query(Artifact.object_key)
            .join(IngestionArtifact, Artifact.object_key == IngestionArtifact.object_key)
            .filter(
                IngestionArtifact.ingestion_id == ingestion_id,
                IngestionArtifact.stage == "normalize",
                IngestionArtifact.status == "success",
                Artifact.artifact_type == "normalized",
            )
            .order_by(Artifact.created_at)
            .distinct()
            .all()
        )
    return [row.object_key for row in rows if row.object_key]


def _persist_index_update(
    *,
    session_factory: Callable[[], Session],
    ingestion_id: UUID,
    status: str,
    error: str | None,
    created_at: datetime,
) -> None:
    """Record the index-update initiation outcome in the database."""
    with closing(session_factory()) as session:
        record = IngestionIndexUpdate(
            ingestion_id=ingestion_id,
            status=status,
            error=error,
            created_at=created_at,
        )
        session.add(record)
        session.commit()


def _persist_embeddings_dispatch(
    *,
    session_factory: Callable[[], Session],
    ingestion_id: UUID,
    object_key: str,
    status: str,
    error: str | None,
    created_at: datetime,
) -> None:
    """Persist a single embeddings dispatch attempt."""
    with closing(session_factory()) as session:
        record = IngestionEmbeddingDispatch(
            ingestion_id=ingestion_id,
            normalized_object_key=object_key,
            status=status,
            error=error,
            created_at=created_at,
        )
        session.add(record)
        session.commit()
