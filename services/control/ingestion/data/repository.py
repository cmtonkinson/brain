"""Authoritative Postgres repository for Ingestion Service state."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from packages.brain_shared.ids import (
    generate_ulid_bytes,
    ulid_bytes_to_str,
    ulid_str_to_bytes,
)
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.control.ingestion.domain import (
    AnchorRecord,
    ExtractionMetadataRecord,
    IngestionRecord,
    IngestionStatus,
    IngestionIndexingRun,
    IndexingRunStatus,
    NormalizationMetadataRecord,
    ProvenanceRecord,
    ProvenanceSourceRecord,
    StageArtifactOutcome,
    StageArtifactStatus,
    StageRunRecord,
    StageRunStatus,
)

from .schema import (
    anchor_notes,
    artifact_provenance,
    extraction_metadata,
    ingestion_stage_runs,
    ingestion_indexing_runs,
    ingestions,
    normalization_metadata,
    provenance_sources,
    stage_artifact_outcomes,
)


class PostgresIngestionRepository:
    """SQL repository over Ingestion Service-owned schema tables."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        """Initialize with a schema-scoped session provider."""
        self._sessions = sessions

    # ------------------------------------------------------------------
    # Ingestion records
    # ------------------------------------------------------------------

    def create_ingestion(
        self,
        *,
        status: str,
        source_type: str,
        source_uri: str | None,
        source_actor: str | None,
        capture_time: datetime,
        mime_type: str | None,
        created_at: datetime,
    ) -> IngestionRecord:
        """Persist one ingestion attempt record."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                ingestions.insert().values(
                    id=row_id,
                    status=status,
                    source_type=source_type,
                    source_uri=source_uri,
                    source_actor=source_actor,
                    capture_time=capture_time,
                    mime_type=mime_type,
                    last_error=None,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            row = (
                session.execute(select(ingestions).where(ingestions.c.id == row_id))
                .mappings()
                .one()
            )
            return _to_ingestion(row)

    def get_ingestion(self, *, ingestion_id: str) -> IngestionRecord | None:
        """Read one ingestion by id."""
        row_bytes = ulid_str_to_bytes(ingestion_id)
        with self._sessions.session() as session:
            row = (
                session.execute(select(ingestions).where(ingestions.c.id == row_bytes))
                .mappings()
                .first()
            )
            return _to_ingestion(row) if row else None

    def list_ingestions(
        self,
        *,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> list[IngestionRecord]:
        """List ingestions with optional status filter and cursor pagination."""
        stmt = select(ingestions).order_by(ingestions.c.id.desc()).limit(limit)
        if status is not None:
            stmt = stmt.where(ingestions.c.status == status)
        if cursor is not None:
            cursor_bytes = ulid_str_to_bytes(cursor)
            stmt = stmt.where(ingestions.c.id < cursor_bytes)
        with self._sessions.session() as session:
            rows = session.execute(stmt).mappings().all()
            return [_to_ingestion(r) for r in rows]

    def update_ingestion_status(
        self,
        *,
        ingestion_id: str,
        status: str,
        last_error: str | None,
        updated_at: datetime,
    ) -> IngestionRecord | None:
        """Update the overall status and error for one ingestion."""
        row_bytes = ulid_str_to_bytes(ingestion_id)
        with self._sessions.session() as session:
            session.execute(
                ingestions.update()
                .where(ingestions.c.id == row_bytes)
                .values(status=status, last_error=last_error, updated_at=updated_at)
            )
            row = (
                session.execute(select(ingestions).where(ingestions.c.id == row_bytes))
                .mappings()
                .first()
            )
            return _to_ingestion(row) if row else None

    # ------------------------------------------------------------------
    # Stage run records
    # ------------------------------------------------------------------

    def create_stage_run(
        self,
        *,
        ingestion_id: str,
        stage: str,
        status: str,
        started_at: datetime,
        created_at: datetime,
    ) -> StageRunRecord:
        """Persist the start of one stage run."""
        row_id = generate_ulid_bytes()
        ingestion_bytes = ulid_str_to_bytes(ingestion_id)
        with self._sessions.session() as session:
            session.execute(
                ingestion_stage_runs.insert().values(
                    id=row_id,
                    ingestion_id=ingestion_bytes,
                    stage=stage,
                    status=status,
                    error=None,
                    started_at=started_at,
                    finished_at=None,
                    created_at=created_at,
                )
            )
            row = (
                session.execute(
                    select(ingestion_stage_runs).where(
                        ingestion_stage_runs.c.id == row_id
                    )
                )
                .mappings()
                .one()
            )
            return _to_stage_run(row)

    def finish_stage_run(
        self,
        *,
        stage_run_id: str,
        status: str,
        error: str | None,
        finished_at: datetime,
    ) -> StageRunRecord | None:
        """Finalize a stage run with outcome."""
        row_bytes = ulid_str_to_bytes(stage_run_id)
        with self._sessions.session() as session:
            session.execute(
                ingestion_stage_runs.update()
                .where(ingestion_stage_runs.c.id == row_bytes)
                .values(status=status, error=error, finished_at=finished_at)
            )
            row = (
                session.execute(
                    select(ingestion_stage_runs).where(
                        ingestion_stage_runs.c.id == row_bytes
                    )
                )
                .mappings()
                .first()
            )
            return _to_stage_run(row) if row else None

    def list_stage_runs(
        self,
        *,
        ingestion_id: str,
        stage: str | None,
    ) -> list[StageRunRecord]:
        """List stage runs for one ingestion, optionally filtered by stage."""
        ingestion_bytes = ulid_str_to_bytes(ingestion_id)
        stmt = (
            select(ingestion_stage_runs)
            .where(ingestion_stage_runs.c.ingestion_id == ingestion_bytes)
            .order_by(ingestion_stage_runs.c.created_at)
        )
        if stage is not None:
            stmt = stmt.where(ingestion_stage_runs.c.stage == stage)
        with self._sessions.session() as session:
            rows = session.execute(stmt).mappings().all()
            return [_to_stage_run(r) for r in rows]

    # ------------------------------------------------------------------
    # Stage artifact outcomes
    # ------------------------------------------------------------------

    def create_stage_artifact_outcome(
        self,
        *,
        ingestion_id: str,
        stage: str,
        object_key: str | None,
        parent_object_key: str | None,
        status: str,
        error: str | None,
        created_at: datetime,
    ) -> StageArtifactOutcome:
        """Persist one per-artifact stage outcome."""
        row_id = generate_ulid_bytes()
        ingestion_bytes = ulid_str_to_bytes(ingestion_id)
        with self._sessions.session() as session:
            session.execute(
                stage_artifact_outcomes.insert().values(
                    id=row_id,
                    ingestion_id=ingestion_bytes,
                    stage=stage,
                    object_key=object_key,
                    parent_object_key=parent_object_key,
                    status=status,
                    error=error,
                    created_at=created_at,
                )
            )
            row = (
                session.execute(
                    select(stage_artifact_outcomes).where(
                        stage_artifact_outcomes.c.id == row_id
                    )
                )
                .mappings()
                .one()
            )
            return _to_artifact_outcome(row)

    def list_stage_artifact_outcomes(
        self,
        *,
        ingestion_id: str,
        stage: str | None,
        status: str | None,
    ) -> list[StageArtifactOutcome]:
        """List artifact outcomes for one ingestion with optional filters."""
        ingestion_bytes = ulid_str_to_bytes(ingestion_id)
        stmt = (
            select(stage_artifact_outcomes)
            .where(stage_artifact_outcomes.c.ingestion_id == ingestion_bytes)
            .order_by(stage_artifact_outcomes.c.created_at)
        )
        if stage is not None:
            stmt = stmt.where(stage_artifact_outcomes.c.stage == stage)
        if status is not None:
            stmt = stmt.where(stage_artifact_outcomes.c.status == status)
        with self._sessions.session() as session:
            rows = session.execute(stmt).mappings().all()
            return [_to_artifact_outcome(r) for r in rows]

    def get_stage_artifact_outcome_by_key(
        self,
        *,
        ingestion_id: str,
        stage: str,
        object_key: str,
    ) -> StageArtifactOutcome | None:
        """Read one artifact outcome by (ingestion, stage, object_key)."""
        ingestion_bytes = ulid_str_to_bytes(ingestion_id)
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(stage_artifact_outcomes).where(
                        stage_artifact_outcomes.c.ingestion_id == ingestion_bytes,
                        stage_artifact_outcomes.c.stage == stage,
                        stage_artifact_outcomes.c.object_key == object_key,
                    )
                )
                .mappings()
                .first()
            )
            return _to_artifact_outcome(row) if row else None

    # ------------------------------------------------------------------
    # Extraction metadata
    # ------------------------------------------------------------------

    def upsert_extraction_metadata(
        self,
        *,
        object_key: str,
        method: str,
        confidence: float | None,
        page_count: int | None,
        created_at: datetime,
    ) -> ExtractionMetadataRecord:
        """Create or update extraction metadata for one artifact."""
        with self._sessions.session() as session:
            existing = (
                session.execute(
                    select(extraction_metadata).where(
                        extraction_metadata.c.object_key == object_key
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                session.execute(
                    extraction_metadata.update()
                    .where(extraction_metadata.c.object_key == object_key)
                    .values(
                        method=method,
                        confidence=confidence,
                        page_count=page_count,
                        updated_at=created_at,
                    )
                )
            else:
                row_id = generate_ulid_bytes()
                try:
                    session.execute(
                        extraction_metadata.insert().values(
                            id=row_id,
                            object_key=object_key,
                            method=method,
                            confidence=confidence,
                            page_count=page_count,
                            created_at=created_at,
                            updated_at=created_at,
                        )
                    )
                except IntegrityError:
                    session.rollback()
                    session.execute(
                        extraction_metadata.update()
                        .where(extraction_metadata.c.object_key == object_key)
                        .values(
                            method=method,
                            confidence=confidence,
                            page_count=page_count,
                            updated_at=created_at,
                        )
                    )
            row = (
                session.execute(
                    select(extraction_metadata).where(
                        extraction_metadata.c.object_key == object_key
                    )
                )
                .mappings()
                .one()
            )
            return _to_extraction_metadata(row)

    def get_extraction_metadata(
        self, *, object_key: str
    ) -> ExtractionMetadataRecord | None:
        """Read extraction metadata by object key."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(extraction_metadata).where(
                        extraction_metadata.c.object_key == object_key
                    )
                )
                .mappings()
                .first()
            )
            return _to_extraction_metadata(row) if row else None

    # ------------------------------------------------------------------
    # Normalization metadata
    # ------------------------------------------------------------------

    def upsert_normalization_metadata(
        self,
        *,
        object_key: str,
        method: str,
        confidence: float | None,
        created_at: datetime,
    ) -> NormalizationMetadataRecord:
        """Create or update normalization metadata for one artifact."""
        with self._sessions.session() as session:
            existing = (
                session.execute(
                    select(normalization_metadata).where(
                        normalization_metadata.c.object_key == object_key
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                session.execute(
                    normalization_metadata.update()
                    .where(normalization_metadata.c.object_key == object_key)
                    .values(
                        method=method,
                        confidence=confidence,
                        updated_at=created_at,
                    )
                )
            else:
                row_id = generate_ulid_bytes()
                try:
                    session.execute(
                        normalization_metadata.insert().values(
                            id=row_id,
                            object_key=object_key,
                            method=method,
                            confidence=confidence,
                            created_at=created_at,
                            updated_at=created_at,
                        )
                    )
                except IntegrityError:
                    session.rollback()
                    session.execute(
                        normalization_metadata.update()
                        .where(normalization_metadata.c.object_key == object_key)
                        .values(
                            method=method,
                            confidence=confidence,
                            updated_at=created_at,
                        )
                    )
            row = (
                session.execute(
                    select(normalization_metadata).where(
                        normalization_metadata.c.object_key == object_key
                    )
                )
                .mappings()
                .one()
            )
            return _to_normalization_metadata(row)

    def get_normalization_metadata(
        self, *, object_key: str
    ) -> NormalizationMetadataRecord | None:
        """Read normalization metadata by object key."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(normalization_metadata).where(
                        normalization_metadata.c.object_key == object_key
                    )
                )
                .mappings()
                .first()
            )
            return _to_normalization_metadata(row) if row else None

    # ------------------------------------------------------------------
    # Provenance
    # ------------------------------------------------------------------

    def get_or_create_provenance(
        self,
        *,
        object_key: str,
        created_at: datetime,
    ) -> ProvenanceRecord:
        """Return existing provenance record or create one for the object key."""
        with self._sessions.session() as session:
            existing = (
                session.execute(
                    select(artifact_provenance).where(
                        artifact_provenance.c.object_key == object_key
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                return _to_provenance(existing)
            row_id = generate_ulid_bytes()
            try:
                session.execute(
                    artifact_provenance.insert().values(
                        id=row_id,
                        object_key=object_key,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
            except IntegrityError:
                session.rollback()
                row = (
                    session.execute(
                        select(artifact_provenance).where(
                            artifact_provenance.c.object_key == object_key
                        )
                    )
                    .mappings()
                    .one()
                )
                return _to_provenance(row)
            row = (
                session.execute(
                    select(artifact_provenance).where(
                        artifact_provenance.c.id == row_id
                    )
                )
                .mappings()
                .one()
            )
            return _to_provenance(row)

    def upsert_provenance_source(
        self,
        *,
        provenance_id: str,
        ingestion_id: str,
        source_type: str,
        source_uri: str | None,
        source_actor: str | None,
        captured_at: datetime,
    ) -> ProvenanceSourceRecord | None:
        """Persist one provenance source; return None when already exists (deduped)."""
        prov_bytes = ulid_str_to_bytes(provenance_id)
        ing_bytes = ulid_str_to_bytes(ingestion_id)
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            try:
                session.execute(
                    provenance_sources.insert().values(
                        id=row_id,
                        provenance_id=prov_bytes,
                        ingestion_id=ing_bytes,
                        source_type=source_type,
                        source_uri=source_uri,
                        source_actor=source_actor,
                        captured_at=captured_at,
                    )
                )
            except IntegrityError:
                session.rollback()
                return None
            row = (
                session.execute(
                    select(provenance_sources).where(provenance_sources.c.id == row_id)
                )
                .mappings()
                .one()
            )
            return _to_provenance_source(row)

    # ------------------------------------------------------------------
    # Anchor notes
    # ------------------------------------------------------------------

    def upsert_anchor_note(
        self,
        *,
        ingestion_id: str,
        normalized_object_key: str,
        vault_path: str,
        created_at: datetime,
    ) -> AnchorRecord:
        """Create or update the anchor note linkage for one normalized artifact."""
        ing_bytes = ulid_str_to_bytes(ingestion_id)
        with self._sessions.session() as session:
            existing = (
                session.execute(
                    select(anchor_notes).where(
                        anchor_notes.c.normalized_object_key == normalized_object_key
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                session.execute(
                    anchor_notes.update()
                    .where(
                        anchor_notes.c.normalized_object_key == normalized_object_key
                    )
                    .values(
                        ingestion_id=ing_bytes,
                        vault_path=vault_path,
                        updated_at=created_at,
                    )
                )
            else:
                row_id = generate_ulid_bytes()
                session.execute(
                    anchor_notes.insert().values(
                        id=row_id,
                        ingestion_id=ing_bytes,
                        normalized_object_key=normalized_object_key,
                        vault_path=vault_path,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
            row = (
                session.execute(
                    select(anchor_notes).where(
                        anchor_notes.c.normalized_object_key == normalized_object_key
                    )
                )
                .mappings()
                .one()
            )
            return _to_anchor(row)

    def list_anchor_notes(self, *, ingestion_id: str) -> list[AnchorRecord]:
        """List anchor note records for one ingestion."""
        ing_bytes = ulid_str_to_bytes(ingestion_id)
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(anchor_notes)
                    .where(anchor_notes.c.ingestion_id == ing_bytes)
                    .order_by(anchor_notes.c.created_at)
                )
                .mappings()
                .all()
            )
            return [_to_anchor(r) for r in rows]

    def get_anchor_by_normalized_key(
        self, *, normalized_object_key: str
    ) -> AnchorRecord | None:
        """Return the anchor record for one normalized artifact key, if any."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(anchor_notes).where(
                        anchor_notes.c.normalized_object_key == normalized_object_key
                    )
                )
                .mappings()
                .first()
            )
            return _to_anchor(row) if row else None

    def delete_anchor_note(self, *, normalized_object_key: str) -> None:
        """Remove an anchor note record — used to roll back on vault write failure."""
        with self._sessions.session() as session:
            session.execute(
                anchor_notes.delete().where(
                    anchor_notes.c.normalized_object_key == normalized_object_key
                )
            )

    # ------------------------------------------------------------------
    # Indexing runs
    # ------------------------------------------------------------------

    def create_indexing_run(
        self,
        *,
        ingestion_id: str,
        status: str,
        created_at: datetime,
    ) -> IngestionIndexingRun:
        """Create one derived indexing run for an ingestion."""
        row_id = generate_ulid_bytes()
        ing_bytes = ulid_str_to_bytes(ingestion_id)
        with self._sessions.session() as session:
            session.execute(
                ingestion_indexing_runs.insert().values(
                    id=row_id,
                    ingestion_id=ing_bytes,
                    job_id=None,
                    status=status,
                    source_count=0,
                    chunk_count=0,
                    embedding_count=0,
                    failed_count=0,
                    error=None,
                    created_at=created_at,
                    updated_at=created_at,
                    finished_at=None,
                )
            )
            row = (
                session.execute(
                    select(ingestion_indexing_runs).where(
                        ingestion_indexing_runs.c.id == row_id
                    )
                )
                .mappings()
                .one()
            )
            return _to_indexing_run(row)

    def get_indexing_run(self, *, indexing_run_id: str) -> IngestionIndexingRun | None:
        """Read one derived indexing run by id."""
        row_bytes = ulid_str_to_bytes(indexing_run_id)
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(ingestion_indexing_runs).where(
                        ingestion_indexing_runs.c.id == row_bytes
                    )
                )
                .mappings()
                .first()
            )
            return _to_indexing_run(row) if row else None

    def update_indexing_run_job(
        self,
        *,
        indexing_run_id: str,
        job_id: str,
        updated_at: datetime,
    ) -> IngestionIndexingRun | None:
        """Attach the Job Service job id to one indexing run."""
        row_bytes = ulid_str_to_bytes(indexing_run_id)
        with self._sessions.session() as session:
            session.execute(
                ingestion_indexing_runs.update()
                .where(ingestion_indexing_runs.c.id == row_bytes)
                .values(job_id=job_id, updated_at=updated_at)
            )
            row = (
                session.execute(
                    select(ingestion_indexing_runs).where(
                        ingestion_indexing_runs.c.id == row_bytes
                    )
                )
                .mappings()
                .first()
            )
            return _to_indexing_run(row) if row else None

    def update_indexing_run_status(
        self,
        *,
        indexing_run_id: str,
        status: str,
        source_count: int,
        chunk_count: int,
        embedding_count: int,
        failed_count: int,
        error: str | None,
        updated_at: datetime,
        finished_at: datetime | None,
    ) -> IngestionIndexingRun | None:
        """Update one indexing run with progress or terminal counts."""
        row_bytes = ulid_str_to_bytes(indexing_run_id)
        with self._sessions.session() as session:
            session.execute(
                ingestion_indexing_runs.update()
                .where(ingestion_indexing_runs.c.id == row_bytes)
                .values(
                    status=status,
                    source_count=source_count,
                    chunk_count=chunk_count,
                    embedding_count=embedding_count,
                    failed_count=failed_count,
                    error=error,
                    updated_at=updated_at,
                    finished_at=finished_at,
                )
            )
            row = (
                session.execute(
                    select(ingestion_indexing_runs).where(
                        ingestion_indexing_runs.c.id == row_bytes
                    )
                )
                .mappings()
                .first()
            )
            return _to_indexing_run(row) if row else None

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def is_healthy(self) -> bool:
        """Return True when backing store is reachable."""
        try:
            with self._sessions.session() as session:
                session.execute(select(ingestions).limit(1))
            return True
        except Exception:  # noqa: BLE001
            return False


# ---------------------------------------------------------------------------
# Row mapping helpers
# ---------------------------------------------------------------------------


def _to_ingestion(row: object) -> IngestionRecord:
    """Map a row mapping to an IngestionRecord."""
    return IngestionRecord(
        id=ulid_bytes_to_str(row["id"]),  # type: ignore[index]
        status=IngestionStatus(row["status"]),  # type: ignore[index]
        source_type=row["source_type"],  # type: ignore[index]
        source_uri=row["source_uri"],  # type: ignore[index]
        source_actor=row["source_actor"],  # type: ignore[index]
        capture_time=row["capture_time"],  # type: ignore[index]
        mime_type=row["mime_type"],  # type: ignore[index]
        last_error=row["last_error"],  # type: ignore[index]
        created_at=row["created_at"],  # type: ignore[index]
        updated_at=row["updated_at"],  # type: ignore[index]
    )


def _to_stage_run(row: object) -> StageRunRecord:
    """Map a row mapping to a StageRunRecord."""
    return StageRunRecord(
        id=ulid_bytes_to_str(row["id"]),  # type: ignore[index]
        ingestion_id=ulid_bytes_to_str(row["ingestion_id"]),  # type: ignore[index]
        stage=row["stage"],  # type: ignore[index]
        status=StageRunStatus(row["status"]),  # type: ignore[index]
        error=row["error"],  # type: ignore[index]
        started_at=row["started_at"],  # type: ignore[index]
        finished_at=row["finished_at"],  # type: ignore[index]
        created_at=row["created_at"],  # type: ignore[index]
    )


def _to_artifact_outcome(row: object) -> StageArtifactOutcome:
    """Map a row mapping to a StageArtifactOutcome."""
    return StageArtifactOutcome(
        id=ulid_bytes_to_str(row["id"]),  # type: ignore[index]
        ingestion_id=ulid_bytes_to_str(row["ingestion_id"]),  # type: ignore[index]
        stage=row["stage"],  # type: ignore[index]
        object_key=row["object_key"],  # type: ignore[index]
        parent_object_key=row["parent_object_key"],  # type: ignore[index]
        status=StageArtifactStatus(row["status"]),  # type: ignore[index]
        error=row["error"],  # type: ignore[index]
        created_at=row["created_at"],  # type: ignore[index]
    )


def _to_extraction_metadata(row: object) -> ExtractionMetadataRecord:
    """Map a row mapping to an ExtractionMetadataRecord."""
    return ExtractionMetadataRecord(
        id=ulid_bytes_to_str(row["id"]),  # type: ignore[index]
        object_key=row["object_key"],  # type: ignore[index]
        method=row["method"],  # type: ignore[index]
        confidence=row["confidence"],  # type: ignore[index]
        page_count=row["page_count"],  # type: ignore[index]
        created_at=row["created_at"],  # type: ignore[index]
        updated_at=row["updated_at"],  # type: ignore[index]
    )


def _to_normalization_metadata(row: object) -> NormalizationMetadataRecord:
    """Map a row mapping to a NormalizationMetadataRecord."""
    return NormalizationMetadataRecord(
        id=ulid_bytes_to_str(row["id"]),  # type: ignore[index]
        object_key=row["object_key"],  # type: ignore[index]
        method=row["method"],  # type: ignore[index]
        confidence=row["confidence"],  # type: ignore[index]
        created_at=row["created_at"],  # type: ignore[index]
        updated_at=row["updated_at"],  # type: ignore[index]
    )


def _to_provenance(row: object) -> ProvenanceRecord:
    """Map a row mapping to a ProvenanceRecord."""
    return ProvenanceRecord(
        id=ulid_bytes_to_str(row["id"]),  # type: ignore[index]
        object_key=row["object_key"],  # type: ignore[index]
        created_at=row["created_at"],  # type: ignore[index]
        updated_at=row["updated_at"],  # type: ignore[index]
    )


def _to_provenance_source(row: object) -> ProvenanceSourceRecord:
    """Map a row mapping to a ProvenanceSourceRecord."""
    return ProvenanceSourceRecord(
        id=ulid_bytes_to_str(row["id"]),  # type: ignore[index]
        provenance_id=ulid_bytes_to_str(row["provenance_id"]),  # type: ignore[index]
        ingestion_id=ulid_bytes_to_str(row["ingestion_id"]),  # type: ignore[index]
        source_type=row["source_type"],  # type: ignore[index]
        source_uri=row["source_uri"],  # type: ignore[index]
        source_actor=row["source_actor"],  # type: ignore[index]
        captured_at=row["captured_at"],  # type: ignore[index]
    )


def _to_anchor(row: object) -> AnchorRecord:
    """Map a row mapping to an AnchorRecord."""
    return AnchorRecord(
        id=ulid_bytes_to_str(row["id"]),  # type: ignore[index]
        ingestion_id=ulid_bytes_to_str(row["ingestion_id"]),  # type: ignore[index]
        normalized_object_key=row["normalized_object_key"],  # type: ignore[index]
        vault_path=row["vault_path"],  # type: ignore[index]
        created_at=row["created_at"],  # type: ignore[index]
        updated_at=row["updated_at"],  # type: ignore[index]
    )


def _to_indexing_run(row: object) -> IngestionIndexingRun:
    """Map a row mapping to an IngestionIndexingRun."""
    return IngestionIndexingRun(
        id=ulid_bytes_to_str(row["id"]),  # type: ignore[index]
        ingestion_id=ulid_bytes_to_str(row["ingestion_id"]),  # type: ignore[index]
        job_id=row["job_id"],  # type: ignore[index]
        status=IndexingRunStatus(row["status"]),  # type: ignore[index]
        source_count=int(row["source_count"]),  # type: ignore[index]
        chunk_count=int(row["chunk_count"]),  # type: ignore[index]
        embedding_count=int(row["embedding_count"]),  # type: ignore[index]
        failed_count=int(row["failed_count"]),  # type: ignore[index]
        error=row["error"],  # type: ignore[index]
        created_at=row["created_at"],  # type: ignore[index]
        updated_at=row["updated_at"],  # type: ignore[index]
        finished_at=row["finished_at"],  # type: ignore[index]
    )
