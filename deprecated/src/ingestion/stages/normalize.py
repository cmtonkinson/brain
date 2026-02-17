"""Stage 3 normalization runner, metadata persistence, and regeneration."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from config import settings
from ingestion.normalizers import (
    ExtractionMetadataSnapshot,
    NormalizedArtifact,
    NormalizerContext,
    NormalizerRegistry,
)
from ingestion.normalizers.text import DefaultTextNormalizer
from ingestion.provenance import ProvenanceSourceInput, record_provenance
from ingestion.stage_recorder import StageRecorder
from ingestion.store import _checksum_from_object_key
from models import (
    Artifact,
    ExtractionMetadata,
    Ingestion,
    IngestionArtifact,
    NormalizationMetadata,
    ProvenanceRecord,
    ProvenanceSource,
)
from services.database import get_sync_session
from services.object_store import ObjectStore


@dataclass(frozen=True)
class Stage3NormalizationResult:
    """Summary of Stage 3 normalization execution outcomes."""

    ingestion_id: UUID
    normalized_artifacts: int
    failures: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExtractedArtifactContext:
    """Lightweight descriptor for extracted artifacts eligible for normalization."""

    object_key: str
    mime_type: str | None


class Stage3NormalizationRunner:
    """Runner that fans extracted artifacts into normalized canonical Markdown."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
        object_store: ObjectStore | None = None,
        registry: NormalizerRegistry | None = None,
    ) -> None:
        """Initialize dependencies for database access, storage, and normalizers."""
        self._session_factory = session_factory or get_sync_session
        self._object_store = object_store or ObjectStore(settings.objects.root_dir)
        self._registry = registry or NormalizerRegistry([DefaultTextNormalizer()])

    def run(self, ingestion_id: UUID, *, now: datetime | None = None) -> Stage3NormalizationResult:
        """Execute Stage 3 normalization for every eligible extracted artifact."""
        timestamp = now or datetime.now(timezone.utc)
        ingestion = self._load_ingestion(ingestion_id)
        errors: list[str] = []
        failures = 0
        normalized_artifacts = 0
        recorder = StageRecorder(session_factory=self._session_factory)

        # Note: We don't use the context manager here because we need to handle
        # per-artifact failures specially - we want to mark the stage as failed
        # while still allowing the pipeline to continue with successful artifacts.
        run_id = recorder._start_stage_run(ingestion_id, "normalize", timestamp)

        try:
            for extracted in self._load_extracted_artifacts(ingestion_id):
                try:
                    count, artifact_errors = self._process_extracted_artifact(
                        context=self._build_context(extracted, ingestion),
                        ingestion=ingestion,
                        timestamp=timestamp,
                    )
                except Exception as exc:
                    message = f"artifact={extracted.object_key} error={exc}"
                    self._record_ingestion_failure(ingestion_id, message, timestamp)
                    errors.append(message)
                    failures += 1
                else:
                    normalized_artifacts += count
                    failures += len(artifact_errors)
                    errors.extend(artifact_errors)

            # Determine stage status based on whether any failures occurred
            finish_timestamp = now or datetime.now(timezone.utc)
            if failures > 0:
                error_summary = f"{failures} artifact(s) failed normalization"
                recorder._finish_stage_run(run_id, "failed", error_summary, finish_timestamp)
                # Note: We do NOT update ingestion status to failed here, as we want
                # the pipeline to continue processing successful artifacts
            else:
                recorder._finish_stage_run(run_id, "success", None, finish_timestamp)

        except Exception as exc:
            # Unexpected error during stage execution - fail the stage and re-raise
            finish_timestamp = now or datetime.now(timezone.utc)
            recorder._finish_stage_run(run_id, "failed", str(exc), finish_timestamp)
            recorder._update_ingestion_status(ingestion_id, "failed", str(exc))
            raise

        return Stage3NormalizationResult(
            ingestion_id=ingestion_id,
            normalized_artifacts=normalized_artifacts,
            failures=failures,
            errors=tuple(errors),
        )

    def _load_ingestion(self, ingestion_id: UUID) -> Ingestion:
        """Return ingestion metadata used for provenance context."""
        with closing(self._session_factory()) as session:
            ingestion = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
            if ingestion is None:
                raise ValueError(f"ingestion not found: {ingestion_id}")
            return ingestion

    def _load_extracted_artifacts(self, ingestion_id: UUID) -> list[ExtractedArtifactContext]:
        """Return previously extracted artifacts eligible for normalization."""
        with closing(self._session_factory()) as session:
            rows = (
                session.query(Artifact.object_key, Artifact.mime_type)
                .join(
                    IngestionArtifact,
                    Artifact.object_key == IngestionArtifact.object_key,
                )
                .filter(
                    IngestionArtifact.ingestion_id == ingestion_id,
                    IngestionArtifact.stage == "extract",
                    IngestionArtifact.status.in_(("success", "skipped")),
                    IngestionArtifact.object_key.is_not(None),
                )
                .distinct()
                .all()
            )
        return [
            ExtractedArtifactContext(object_key=row.object_key, mime_type=row.mime_type)
            for row in rows
        ]

    def _build_context(
        self,
        extracted: ExtractedArtifactContext,
        ingestion: Ingestion,
    ) -> NormalizerContext:
        """Build a normalizer context combining metadata and payload."""
        payload = self._object_store.read(extracted.object_key)
        extraction_metadata = self._load_extraction_metadata(extracted.object_key)
        return NormalizerContext(
            ingestion_id=ingestion.id,
            extracted_object_key=extracted.object_key,
            payload=payload,
            mime_type=extracted.mime_type,
            source_type=ingestion.source_type,
            source_uri=ingestion.source_uri,
            source_actor=ingestion.source_actor,
            extraction_metadata=extraction_metadata,
        )

    def _process_extracted_artifact(
        self,
        context: NormalizerContext,
        ingestion: Ingestion,
        timestamp: datetime,
    ) -> tuple[int, list[str]]:
        """Normalize an extracted artifact via the available normalizers."""
        normalizers = self._registry.match(context)
        if not normalizers:
            message = f"artifact={context.extracted_object_key} error=no normalizer available"
            self._record_ingestion_failure(ingestion.id, message, timestamp)
            return 0, [message]

        normalized_count = 0
        errors: list[str] = []
        for normalizer in normalizers:
            try:
                artifacts = normalizer.normalize(context)
            except Exception as exc:
                message = f"artifact={context.extracted_object_key} error={normalizer.__class__.__name__}:{exc}"
                self._record_ingestion_failure(ingestion.id, message, timestamp)
                errors.append(message)
                continue
            for artifact in artifacts:
                try:
                    object_key = self._persist_normalized_artifact(artifact, context, timestamp)
                    self._persist_normalization_metadata(object_key, artifact, timestamp)
                    self._persist_provenance(ingestion, object_key, artifact, timestamp)
                    self._record_ingestion_success(ingestion.id, object_key, timestamp)
                    normalized_count += 1
                except Exception as exc:
                    message = f"artifact={context.extracted_object_key} error={normalizer.__class__.__name__}:{exc}"
                    self._record_ingestion_failure(ingestion.id, message, timestamp)
                    errors.append(message)
        return normalized_count, errors

    def _persist_normalized_artifact(
        self,
        artifact: NormalizedArtifact,
        context: NormalizerContext,
        timestamp: datetime,
    ) -> str:
        """Persist normalized artifact blob and metadata for later stages."""
        object_key = self._object_store.write(artifact.payload)
        checksum = _checksum_from_object_key(object_key)
        size_bytes = len(artifact.payload)
        with closing(self._session_factory()) as session:
            existing = session.query(Artifact).filter(Artifact.object_key == object_key).first()
            if existing is None:
                record = Artifact(
                    object_key=object_key,
                    created_at=timestamp,
                    size_bytes=size_bytes,
                    mime_type=artifact.mime_type,
                    checksum=checksum,
                    artifact_type="normalized",
                    first_ingested_at=timestamp,
                    last_ingested_at=timestamp,
                    parent_object_key=context.extracted_object_key,
                    parent_stage="extract",
                )
                session.add(record)
            else:
                existing.size_bytes = size_bytes
                existing.mime_type = artifact.mime_type
                existing.checksum = checksum
                existing.artifact_type = "normalized"
                existing.last_ingested_at = timestamp
                existing.parent_object_key = context.extracted_object_key
                existing.parent_stage = "extract"
                session.flush()
            session.commit()
        return object_key

    def _persist_normalization_metadata(
        self,
        object_key: str,
        artifact: NormalizedArtifact,
        timestamp: datetime,
    ) -> None:
        """Persist normalization metadata describing the canonical output."""
        with closing(self._session_factory()) as session:
            existing = (
                session.query(NormalizationMetadata)
                .filter(NormalizationMetadata.object_key == object_key)
                .first()
            )
            if existing is None:
                record = NormalizationMetadata(
                    object_key=object_key,
                    method=artifact.method,
                    confidence=artifact.confidence,
                    tool_metadata=artifact.tool_metadata,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(record)
            else:
                existing.method = artifact.method
                existing.confidence = artifact.confidence
                existing.tool_metadata = artifact.tool_metadata
                existing.updated_at = timestamp
            session.commit()

    def _persist_provenance(
        self,
        ingestion: Ingestion,
        object_key: str,
        artifact: NormalizedArtifact,
        timestamp: datetime,
    ) -> None:
        """Record provenance for the normalized artifact."""
        source = ProvenanceSourceInput(
            source_type=f"normalizer:{artifact.method}",
            source_uri=ingestion.source_uri,
            source_actor=ingestion.source_actor,
            captured_at=timestamp,
        )
        with closing(self._session_factory()) as session:
            record_provenance(
                session,
                object_key=object_key,
                ingestion_id=ingestion.id,
                sources=[source],
                now=timestamp,
            )
            session.commit()

    def _record_ingestion_success(
        self,
        ingestion_id: UUID,
        object_key: str,
        timestamp: datetime,
    ) -> None:
        """Persist record of a successful normalization output."""
        with closing(self._session_factory()) as session:
            existing = (
                session.query(IngestionArtifact)
                .filter(
                    IngestionArtifact.ingestion_id == ingestion_id,
                    IngestionArtifact.stage == "normalize",
                    IngestionArtifact.object_key == object_key,
                )
                .first()
            )
            if existing is not None:
                return
            record = IngestionArtifact(
                ingestion_id=ingestion_id,
                stage="normalize",
                object_key=object_key,
                created_at=timestamp,
                status="success",
                error=None,
            )
            session.add(record)
            session.commit()

    def _record_ingestion_failure(
        self,
        ingestion_id: UUID,
        error: str,
        timestamp: datetime,
    ) -> None:
        """Persist failure metadata when normalization cannot produce output."""
        with closing(self._session_factory()) as session:
            record = IngestionArtifact(
                ingestion_id=ingestion_id,
                stage="normalize",
                object_key=None,
                created_at=timestamp,
                status="failed",
                error=error,
            )
            session.add(record)
            session.commit()

    def _load_extraction_metadata(self, object_key: str) -> ExtractionMetadataSnapshot | None:
        """Return extraction metadata for the provided extracted artifact."""
        with closing(self._session_factory()) as session:
            row = (
                session.query(ExtractionMetadata)
                .filter(ExtractionMetadata.object_key == object_key)
                .first()
            )
            if row is None:
                return None
            return ExtractionMetadataSnapshot(
                method=row.method,
                confidence=row.confidence,
                page_count=row.page_count,
                tool_metadata=row.tool_metadata,
            )


def parse_stage3_payload(payload: dict[str, object]) -> UUID:
    """Parse the ingestion identifier out of a Stage 3 payload."""
    ingestion_id_raw = payload.get("ingestion_id")
    if not isinstance(ingestion_id_raw, str):
        raise ValueError("ingestion_id is required for Stage 3 payload")
    return UUID(ingestion_id_raw)


def run_stage3_normalization(
    ingestion_id: UUID,
    *,
    session_factory: Callable[[], Session] | None = None,
    object_store: ObjectStore | None = None,
    registry: NormalizerRegistry | None = None,
    now: datetime | None = None,
) -> Stage3NormalizationResult:
    """Execute Stage 3 normalization for the ingestion."""
    runner = Stage3NormalizationRunner(
        session_factory=session_factory,
        object_store=object_store,
        registry=registry,
    )
    return runner.run(ingestion_id, now=now)


def regenerate_normalized_artifacts(
    ingestion_id: UUID,
    *,
    session_factory: Callable[[], Session] | None = None,
    object_store: ObjectStore | None = None,
    registry: NormalizerRegistry | None = None,
    extracted_object_key: str | None = None,
    now: datetime | None = None,
) -> Stage3NormalizationResult:
    """Delete and rerun normalization for a given ingestion or extracted artifact."""
    session_factory = session_factory or get_sync_session
    store = object_store or ObjectStore(settings.objects.root_dir)

    with closing(session_factory()) as session:
        keys_with_parents = _collect_normalized_keys(session, ingestion_id, extracted_object_key)
        object_keys = [key for key, _ in keys_with_parents]
        if object_keys:
            _cleanup_normalized_artifacts(session, object_keys)
            session.commit()
            for object_key, parent_key in keys_with_parents:
                if parent_key is None or parent_key != object_key:
                    store.delete(object_key)

    return run_stage3_normalization(
        ingestion_id,
        session_factory=session_factory,
        object_store=store,
        registry=registry,
        now=now,
    )


def _collect_normalized_keys(
    session: Session,
    ingestion_id: UUID,
    extracted_object_key: str | None,
) -> list[tuple[str, str | None]]:
    """Return normalized artifacts (and parents) that should be regenerated."""
    query = (
        session.query(Artifact.object_key, Artifact.parent_object_key)
        .join(
            IngestionArtifact,
            Artifact.object_key == IngestionArtifact.object_key,
        )
        .filter(
            IngestionArtifact.ingestion_id == ingestion_id,
            IngestionArtifact.stage == "normalize",
            Artifact.artifact_type == "normalized",
            Artifact.parent_stage == "extract",
        )
    )
    if extracted_object_key:
        query = query.filter(Artifact.parent_object_key == extracted_object_key)
    return [(row.object_key, row.parent_object_key) for row in query.all()]


def _cleanup_normalized_artifacts(session: Session, object_keys: list[str]) -> None:
    """Remove normalized artifacts and related metadata for regeneration."""
    if not object_keys:
        return

    provenance_records = session.query(ProvenanceRecord).filter(
        ProvenanceRecord.object_key.in_(object_keys)
    )
    record_ids = [row.id for row in provenance_records]
    if record_ids:
        session.query(ProvenanceSource).filter(
            ProvenanceSource.provenance_id.in_(record_ids)
        ).delete(synchronize_session=False)
        session.query(ProvenanceRecord).filter(ProvenanceRecord.id.in_(record_ids)).delete(
            synchronize_session=False
        )

    metadata_query = session.query(NormalizationMetadata).filter(
        NormalizationMetadata.object_key.in_(object_keys)
    )
    metadata_query.delete(synchronize_session=False)

    ingestion_query = (
        session.query(IngestionArtifact)
        .filter(IngestionArtifact.object_key.in_(object_keys))
        .filter(IngestionArtifact.stage == "normalize")
    )
    ingestion_query.delete(synchronize_session=False)
