"""Hook dispatch helpers for ingestion stage completion events."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import Callable, Sequence
from uuid import UUID

import logging
from sqlalchemy.orm import Session

from ingestion.constants import STAGE_SET
from ingestion.hooks import (
    HookRegistration,
    HookRegistry,
    StageArtifactDescriptor,
    get_hook_registry,
)
from models import Artifact, IngestionArtifact, ProvenanceRecord, ProvenanceSource
from services.database import get_sync_session

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HookDispatchResult:
    """Summary of a hook dispatch run."""

    ingestion_id: UUID
    stage: str
    hooks_dispatched: int


def dispatch_stage_hooks(
    ingestion_id: UUID,
    stage: str,
    *,
    session_factory: Callable[[], Session] | None = None,
    registry: HookRegistry | None = None,
    logger: logging.Logger | None = None,
) -> HookDispatchResult:
    """Dispatch hooks for the completed ingestion stage."""
    session_factory = session_factory or get_sync_session
    registry = registry or get_hook_registry()
    logger = logger or LOGGER
    with closing(session_factory()) as session:
        records = _load_stage_provenance_records(session, ingestion_id, stage)
        descriptors = _build_descriptors(session, records, ingestion_id)
    hooks_dispatched = 0
    for hook in registry.hooks_for_stage(stage):
        if not _should_invoke(hook, descriptors):
            continue
        try:
            hook.callback(ingestion_id, stage, tuple(records))
            hooks_dispatched += 1
        except Exception:
            logger.exception(
                "Hook %s failed during dispatch: ingestion=%s stage=%s",
                hook.hook_id,
                ingestion_id,
                stage,
            )
    return HookDispatchResult(
        ingestion_id=ingestion_id,
        stage=stage,
        hooks_dispatched=hooks_dispatched,
    )


def _should_invoke(hook: HookRegistration, descriptors: Sequence[StageArtifactDescriptor]) -> bool:
    """Return True when a hook should run for the provided descriptors."""
    if not descriptors:
        return hook.filters is None or not hook.filters.is_defensive()
    if hook.filters is None:
        return True
    return any(hook.filters.matches(descriptor) for descriptor in descriptors)


def _load_stage_provenance_records(
    session: Session,
    ingestion_id: UUID,
    stage: str,
) -> list[ProvenanceRecord]:
    """Load provenance records for the ingestion stage's artifacts."""
    if stage not in STAGE_SET:
        raise ValueError(f"unknown stage: {stage}")
    keys = (
        session.query(IngestionArtifact.object_key)
        .filter(
            IngestionArtifact.ingestion_id == ingestion_id,
            IngestionArtifact.stage == stage,
            IngestionArtifact.object_key.is_not(None),
        )
        .distinct()
        .all()
    )
    object_keys = [row.object_key for row in keys if row.object_key]
    if not object_keys:
        return []
    return (
        session.query(ProvenanceRecord).filter(ProvenanceRecord.object_key.in_(object_keys)).all()
    )


def _build_descriptors(
    session: Session,
    records: Sequence[ProvenanceRecord],
    ingestion_id: UUID,
) -> list[StageArtifactDescriptor]:
    """Build descriptors for filter evaluation."""
    if not records:
        return []
    artifact_rows = (
        session.query(Artifact)
        .filter(Artifact.object_key.in_([record.object_key for record in records]))
        .all()
    )
    artifacts_by_key = {artifact.object_key: artifact for artifact in artifact_rows}
    sources = (
        session.query(ProvenanceSource)
        .filter(
            ProvenanceSource.provenance_id.in_([record.id for record in records]),
            ProvenanceSource.ingestion_id == ingestion_id,
        )
        .all()
    )
    sources_by_record: dict[UUID, list[ProvenanceSource]] = {}
    for source in sources:
        sources_by_record.setdefault(source.provenance_id, []).append(source)
    descriptors: list[StageArtifactDescriptor] = []
    for record in records:
        artifact = artifacts_by_key.get(record.object_key)
        descriptor = StageArtifactDescriptor(
            object_key=record.object_key,
            mime_type=(artifact.mime_type if artifact is not None else None),
            size_bytes=(artifact.size_bytes if artifact is not None else None),
            artifact_type=(artifact.artifact_type if artifact is not None else None),
            sources=tuple(sources_by_record.get(record.id, [])),
        )
        descriptors.append(descriptor)
    return descriptors
