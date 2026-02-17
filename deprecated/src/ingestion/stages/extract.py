"""Stage 2 extraction runner and payload helpers."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from config import settings
from ingestion.extractors import ExtractedArtifact, ExtractorContext, ExtractorRegistry
from ingestion.extractors.text import TextExtractor
from ingestion.provenance import ProvenanceSourceInput, record_provenance
from ingestion.sandbox import SandboxExecutor
from ingestion.stage_recorder import StageRecorder
from ingestion.store import _checksum_from_object_key
from models import (
    Artifact,
    ExtractionMetadata,
    Ingestion,
    IngestionArtifact,
)
from services.database import get_sync_session
from services.object_store import ObjectStore


@dataclass(frozen=True)
class RawArtifactContext:
    """Database-backed metadata describing a raw artifact."""

    object_key: str
    mime_type: str | None


@dataclass(frozen=True)
class Stage2ExtractionResult:
    """Summary of Stage 2 extraction outcomes."""

    ingestion_id: UUID
    extracted_artifacts: int
    failures: int
    errors: tuple[str, ...]


def parse_stage2_payload(payload: dict[str, object]) -> UUID:
    """Parse a Stage 2 payload dictionary into an ingestion identifier."""
    ingestion_id_raw = payload.get("ingestion_id")
    if not isinstance(ingestion_id_raw, str):
        raise ValueError("ingestion_id is required for Stage 2 payload")
    return UUID(ingestion_id_raw)


def run_stage2_extraction(
    ingestion_id: UUID,
    *,
    session_factory: Callable[[], Session] | None = None,
    object_store: ObjectStore | None = None,
    registry: ExtractorRegistry | None = None,
    now: datetime | None = None,
) -> Stage2ExtractionResult:
    """Execute Stage 2 extraction for the provided ingestion."""
    runner = Stage2ExtractionRunner(
        session_factory=session_factory,
        object_store=object_store,
        registry=registry,
    )
    return runner.run(ingestion_id, now=now)


class Stage2ExtractionRunner:
    """Runner that fans raw artifacts into extracted outputs."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
        object_store: ObjectStore | None = None,
        registry: ExtractorRegistry | None = None,
        sandbox: SandboxExecutor | None = None,
    ) -> None:
        """Initialize the runner with database, storage, extractor wiring, and sandbox."""
        self._session_factory = session_factory or get_sync_session
        self._object_store = object_store or ObjectStore(settings.objects.root_dir)
        self._registry = registry or ExtractorRegistry([TextExtractor()])
        self._sandbox = sandbox or SandboxExecutor()

    def run(self, ingestion_id: UUID, *, now: datetime | None = None) -> Stage2ExtractionResult:
        """Run extraction for every eligible raw artifact under the ingestion."""
        timestamp = now or datetime.now(timezone.utc)
        ingestion = self._load_ingestion(ingestion_id)
        failures: int = 0
        errors: list[str] = []
        extracted_artifacts = 0
        recorder = StageRecorder(session_factory=self._session_factory)

        # Note: We don't use the context manager here because we need to handle
        # per-artifact failures specially - we want to mark the stage as failed
        # while still allowing the pipeline to continue with successful artifacts.
        run_id = recorder._start_stage_run(ingestion_id, "extract", timestamp)

        # Update ingestion status to running (Stage recorder would do this for Stage 1)
        # For Stage 2+, we just process artifacts
        try:
            for raw in self._load_raw_artifacts(ingestion_id):
                context = self._build_context(raw, ingestion)
                try:
                    success_count, failure_count, artifact_errors = self._process_raw_artifact(
                        context, ingestion, timestamp
                    )
                    extracted_artifacts += success_count
                    failures += failure_count
                    errors.extend(artifact_errors)
                except Exception as exc:
                    failures += 1
                    message = f"artifact={raw.object_key} error={exc}"
                    errors.append(message)
                    self._record_ingestion_failure(ingestion_id, message, timestamp)

            # Determine stage status based on whether any failures occurred
            finish_timestamp = now or datetime.now(timezone.utc)
            if failures > 0:
                error_summary = f"{failures} artifact(s) failed extraction"
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

        return Stage2ExtractionResult(
            ingestion_id=ingestion_id,
            extracted_artifacts=extracted_artifacts,
            failures=failures,
            errors=tuple(errors),
        )

    def _load_ingestion(self, ingestion_id: UUID) -> Ingestion:
        """Read ingestion metadata for provenance context."""
        with closing(self._session_factory()) as session:
            ingestion = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
            if ingestion is None:
                raise ValueError(f"ingestion not found: {ingestion_id}")
            return ingestion

    def _load_raw_artifacts(self, ingestion_id: UUID) -> list[RawArtifactContext]:
        """Return raw artifacts that passed Stage 1 store for the ingestion."""
        with closing(self._session_factory()) as session:
            rows = (
                session.query(Artifact.object_key, Artifact.mime_type)
                .join(
                    IngestionArtifact,
                    Artifact.object_key == IngestionArtifact.object_key,
                )
                .filter(
                    IngestionArtifact.ingestion_id == ingestion_id,
                    IngestionArtifact.stage == "store",
                    IngestionArtifact.status.in_({"success", "skipped"}),
                    IngestionArtifact.object_key.is_not(None),
                )
                .distinct()
                .all()
            )
        return [
            RawArtifactContext(object_key=row.object_key, mime_type=row.mime_type) for row in rows
        ]

    def _build_context(self, raw: RawArtifactContext, ingestion: Ingestion) -> ExtractorContext:
        """Construct extractor context from raw artifact metadata."""
        payload = self._object_store.read(raw.object_key)
        return ExtractorContext(
            ingestion_id=ingestion.id,
            raw_object_key=raw.object_key,
            payload=payload,
            mime_type=raw.mime_type,
            source_type=ingestion.source_type,
            source_uri=ingestion.source_uri,
            source_actor=ingestion.source_actor,
        )

    def _process_raw_artifact(
        self,
        context: ExtractorContext,
        ingestion: Ingestion,
        timestamp: datetime,
    ) -> tuple[int, int, list[str]]:
        """Process a single raw artifact through matching extractors with sandbox isolation.

        Returns:
            Tuple of (success_count, failure_count, error_messages).
        """
        extractors = self._registry.match(context)
        if not extractors:
            return 0, 0, []
        count = 0
        failures = 0
        errors: list[str] = []
        for extractor in extractors:
            # Execute extraction in sandbox
            sandbox_result = self._sandbox.execute(extractor.extract, context)

            if not sandbox_result.success:
                # Sandbox failure - record but continue with other extractors
                error_msg = f"artifact={context.raw_object_key} error={sandbox_result.error}"
                self._record_ingestion_failure(ingestion.id, error_msg, timestamp)
                failures += 1
                errors.append(error_msg)
                continue

            extracted = sandbox_result.result
            if not extracted:
                continue

            for artifact in extracted:
                object_key = self._persist_extracted_artifact(artifact, context, timestamp)
                self._record_ingestion_success(ingestion.id, object_key, timestamp)
                self._persist_extraction_metadata(object_key, artifact, timestamp)
                self._persist_provenance(ingestion, object_key, artifact, timestamp)
                count += 1
        return count, failures, errors

    def _persist_extracted_artifact(
        self,
        artifact: ExtractedArtifact,
        context: ExtractorContext,
        timestamp: datetime,
    ) -> str:
        """Persist extracted artifact blob and metadata."""
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
                    artifact_type="extracted",
                    first_ingested_at=timestamp,
                    last_ingested_at=timestamp,
                    parent_object_key=context.raw_object_key,
                    parent_stage="store",
                )
                session.add(record)
            else:
                existing.size_bytes = size_bytes
                existing.mime_type = artifact.mime_type
                existing.checksum = checksum
                existing.artifact_type = "extracted"
                existing.last_ingested_at = timestamp
                existing.parent_object_key = context.raw_object_key
                existing.parent_stage = "store"
            session.commit()
        return object_key

    def _record_ingestion_success(
        self,
        ingestion_id: UUID,
        object_key: str,
        timestamp: datetime,
    ) -> None:
        """Record a successful extracted artifact outcome."""
        with closing(self._session_factory()) as session:
            existing = (
                session.query(IngestionArtifact)
                .filter(
                    IngestionArtifact.ingestion_id == ingestion_id,
                    IngestionArtifact.stage == "extract",
                    IngestionArtifact.object_key == object_key,
                )
                .first()
            )
            if existing is not None:
                return
            record = IngestionArtifact(
                ingestion_id=ingestion_id,
                stage="extract",
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
        """Record a failed extraction outcome for a raw artifact."""
        with closing(self._session_factory()) as session:
            record = IngestionArtifact(
                ingestion_id=ingestion_id,
                stage="extract",
                object_key=None,
                created_at=timestamp,
                status="failed",
                error=error,
            )
            session.add(record)
            session.commit()

    def _persist_extraction_metadata(
        self,
        object_key: str,
        artifact: ExtractedArtifact,
        timestamp: datetime,
    ) -> None:
        """Persist extraction metadata associated with an artifact."""
        with closing(self._session_factory()) as session:
            existing = (
                session.query(ExtractionMetadata)
                .filter(ExtractionMetadata.object_key == object_key)
                .first()
            )
            if existing is None:
                record = ExtractionMetadata(
                    object_key=object_key,
                    method=artifact.method,
                    confidence=artifact.confidence,
                    page_count=artifact.page_count,
                    tool_metadata=artifact.tool_metadata,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(record)
            else:
                existing.method = artifact.method
                existing.confidence = artifact.confidence
                existing.page_count = artifact.page_count
                existing.tool_metadata = artifact.tool_metadata
                existing.updated_at = timestamp
            session.commit()

    def _persist_provenance(
        self,
        ingestion: Ingestion,
        object_key: str,
        artifact: ExtractedArtifact,
        timestamp: datetime,
    ) -> None:
        """Create provenance records for an extracted artifact."""
        source_type = f"extractor:{artifact.method}"
        source = ProvenanceSourceInput(
            source_type=source_type,
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
