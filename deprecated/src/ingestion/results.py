"""Results access helpers for the ingestion pipeline."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from ingestion.constants import STAGE_ORDER
from ingestion.errors import IngestionNotFound
from models import Artifact, Ingestion, IngestionArtifact
from services.database import get_sync_session


@dataclass(frozen=True)
class StageArtifactOutcome:
    """A single ingestion artifact outcome for a stage."""

    object_key: str | None
    status: str
    error: str | None
    created_at: datetime
    mime_type: str | None
    size_bytes: int | None
    artifact_type: str | None


@dataclass(frozen=True)
class StageResult:
    """Grouped outcomes for a single ingestion stage."""

    stage: str
    outcomes: tuple[StageArtifactOutcome, ...]


@dataclass(frozen=True)
class IngestionResults:
    """Stable, stage-oriented results view for an ingestion attempt."""

    ingestion_id: UUID
    stages: tuple[StageResult, ...]


def get_ingestion_results(
    ingestion_id: UUID,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> IngestionResults:
    """Return the ingestion results view for the provided identifier."""
    session_factory = session_factory or get_sync_session
    with closing(session_factory()) as session:
        return fetch_ingestion_results(session, ingestion_id)


def fetch_ingestion_results(session: Session, ingestion_id: UUID) -> IngestionResults:
    """Load results for the ingestion within the given SQLAlchemy session."""
    _ensure_ingestion_exists(session, ingestion_id)
    rows = (
        session.query(IngestionArtifact, Artifact)
        .outerjoin(Artifact, IngestionArtifact.object_key == Artifact.object_key)
        .filter(IngestionArtifact.ingestion_id == ingestion_id)
        .order_by(
            IngestionArtifact.stage,
            IngestionArtifact.created_at,
            IngestionArtifact.object_key,
        )
        .all()
    )
    buckets: dict[str, list[StageArtifactOutcome]] = {stage: [] for stage in STAGE_ORDER}
    extras: dict[str, list[StageArtifactOutcome]] = {}
    for artifact_outcome, artifact in rows:
        stage = str(artifact_outcome.stage)
        outcome = StageArtifactOutcome(
            object_key=artifact_outcome.object_key,
            status=str(artifact_outcome.status),
            error=artifact_outcome.error,
            created_at=artifact_outcome.created_at,
            mime_type=(artifact.mime_type if artifact is not None else None),
            size_bytes=(artifact.size_bytes if artifact is not None else None),
            artifact_type=(artifact.artifact_type if artifact is not None else None),
        )
        if stage in buckets:
            buckets[stage].append(outcome)
        else:
            extras.setdefault(stage, []).append(outcome)
    ordered_results = []
    for stage in STAGE_ORDER:
        ordered_results.append(StageResult(stage=stage, outcomes=_sort_outcomes(buckets[stage])))
    for stage in sorted(extras):
        ordered_results.append(StageResult(stage=stage, outcomes=_sort_outcomes(extras[stage])))
    return IngestionResults(ingestion_id=ingestion_id, stages=tuple(ordered_results))


def _ensure_ingestion_exists(session: Session, ingestion_id: UUID) -> None:
    """Raise if the ingestion cannot be found."""
    exists = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
    if exists is None:
        raise IngestionNotFound(ingestion_id)


def _sort_outcomes(outcomes: Sequence[StageArtifactOutcome]) -> tuple[StageArtifactOutcome, ...]:
    """Return a deterministic ordering for stage outcomes."""
    return tuple(
        sorted(
            outcomes,
            key=lambda outcome: (outcome.created_at, outcome.object_key or ""),
        )
    )
