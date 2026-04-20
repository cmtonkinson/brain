"""Behaviour tests for DefaultIngestionService using in-memory fakes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from services.control.ingestion.config import IngestionServiceSettings
from services.control.ingestion.domain import (
    AnchorRecord,
    ExtractionMetadataRecord,
    IngestionIndexingRun,
    IngestionRecord,
    IngestionStatus,
    IndexingRunStatus,
    NormalizationMetadataRecord,
    ProvenanceRecord,
    ProvenanceSourceRecord,
    StageArtifactOutcome,
    StageArtifactStatus,
    StageRunRecord,
    StageRunStatus,
)
from services.control.ingestion.implementation import DefaultIngestionService
from services.control.ingestion.interfaces import (
    BaseExtractor,
    BaseNormalizer,
    BuiltInTextExtractor,
    BuiltInTextNormalizer,
    ExtractedArtifact,
    ExtractorRegistry,
    NormalizedArtifact,
    NormalizerRegistry,
)


# ---------------------------------------------------------------------------
# In-memory repository fake
# ---------------------------------------------------------------------------


class _FakeRepository:
    """Minimal in-memory IngestionRepository for unit testing."""

    def __init__(self) -> None:
        self._ingestions: dict[str, IngestionRecord] = {}
        self._stage_runs: list[StageRunRecord] = []
        self._outcomes: list[StageArtifactOutcome] = []
        self._extraction_meta: dict[str, ExtractionMetadataRecord] = {}
        self._normalization_meta: dict[str, NormalizationMetadataRecord] = {}
        self._provenance: dict[str, ProvenanceRecord] = {}
        self._provenance_sources: list[ProvenanceSourceRecord] = []
        self._anchors: dict[str, AnchorRecord] = {}
        self._indexing_runs: dict[str, IngestionIndexingRun] = {}
        self._healthy: bool = True
        self._id_counter = 0

    def _next_id(self) -> str:
        self._id_counter += 1
        return f"01HX{self._id_counter:022d}"

    def _now(self) -> datetime:
        return datetime.now(UTC)

    # -- ingestion records --

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
        now = created_at
        record = IngestionRecord(
            id=self._next_id(),
            status=IngestionStatus(status),
            source_type=source_type,
            source_uri=source_uri,
            source_actor=source_actor,
            capture_time=capture_time,
            mime_type=mime_type,
            last_error=None,
            created_at=now,
            updated_at=now,
        )
        self._ingestions[record.id] = record
        return record

    def get_ingestion(self, *, ingestion_id: str) -> IngestionRecord | None:
        return self._ingestions.get(ingestion_id)

    def list_ingestions(
        self,
        *,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> list[IngestionRecord]:
        records = list(self._ingestions.values())
        if status is not None:
            records = [r for r in records if r.status.value == status]
        if cursor is not None:
            try:
                idx = next(i for i, r in enumerate(records) if r.id == cursor)
                records = records[idx + 1 :]
            except StopIteration:
                records = []
        return records[:limit]

    def update_ingestion_status(
        self,
        *,
        ingestion_id: str,
        status: str,
        last_error: str | None,
        updated_at: datetime,
    ) -> IngestionRecord | None:
        record = self._ingestions.get(ingestion_id)
        if record is None:
            return None
        updated = record.model_copy(
            update={
                "status": IngestionStatus(status),
                "last_error": last_error,
                "updated_at": updated_at,
            }
        )
        self._ingestions[ingestion_id] = updated
        return updated

    # -- stage run records --

    def create_stage_run(
        self,
        *,
        ingestion_id: str,
        stage: str,
        status: str,
        started_at: datetime,
        created_at: datetime,
    ) -> StageRunRecord:
        run = StageRunRecord(
            id=self._next_id(),
            ingestion_id=ingestion_id,
            stage=stage,
            status=StageRunStatus(status),
            error=None,
            started_at=started_at,
            finished_at=None,
            created_at=created_at,
        )
        self._stage_runs.append(run)
        return run

    def finish_stage_run(
        self,
        *,
        stage_run_id: str,
        status: str,
        error: str | None,
        finished_at: datetime,
    ) -> StageRunRecord | None:
        for i, run in enumerate(self._stage_runs):
            if run.id == stage_run_id:
                updated = run.model_copy(
                    update={
                        "status": StageRunStatus(status),
                        "error": error,
                        "finished_at": finished_at,
                    }
                )
                self._stage_runs[i] = updated
                return updated
        return None

    def list_stage_runs(
        self,
        *,
        ingestion_id: str,
        stage: str | None,
    ) -> list[StageRunRecord]:
        runs = [r for r in self._stage_runs if r.ingestion_id == ingestion_id]
        if stage is not None:
            runs = [r for r in runs if r.stage == stage]
        return runs

    # -- stage artifact outcomes --

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
        outcome = StageArtifactOutcome(
            id=self._next_id(),
            ingestion_id=ingestion_id,
            stage=stage,
            object_key=object_key,
            parent_object_key=parent_object_key,
            status=StageArtifactStatus(status),
            error=error,
            created_at=created_at,
        )
        self._outcomes.append(outcome)
        return outcome

    def list_stage_artifact_outcomes(
        self,
        *,
        ingestion_id: str,
        stage: str | None,
        status: str | None,
    ) -> list[StageArtifactOutcome]:
        results = [o for o in self._outcomes if o.ingestion_id == ingestion_id]
        if stage is not None:
            results = [o for o in results if o.stage == stage]
        if status is not None:
            results = [o for o in results if o.status.value == status]
        return results

    def get_stage_artifact_outcome_by_key(
        self,
        *,
        ingestion_id: str,
        stage: str,
        object_key: str,
    ) -> StageArtifactOutcome | None:
        for o in self._outcomes:
            if (
                o.ingestion_id == ingestion_id
                and o.stage == stage
                and o.object_key == object_key
            ):
                return o
        return None

    # -- extraction metadata --

    def upsert_extraction_metadata(
        self,
        *,
        object_key: str,
        method: str,
        confidence: float | None,
        page_count: int | None,
        created_at: datetime,
    ) -> ExtractionMetadataRecord:
        now = created_at
        record = ExtractionMetadataRecord(
            id=self._next_id(),
            object_key=object_key,
            method=method,
            confidence=confidence,
            page_count=page_count,
            created_at=now,
            updated_at=now,
        )
        self._extraction_meta[object_key] = record
        return record

    def get_extraction_metadata(
        self, *, object_key: str
    ) -> ExtractionMetadataRecord | None:
        return self._extraction_meta.get(object_key)

    # -- normalization metadata --

    def upsert_normalization_metadata(
        self,
        *,
        object_key: str,
        method: str,
        confidence: float | None,
        created_at: datetime,
    ) -> NormalizationMetadataRecord:
        now = created_at
        record = NormalizationMetadataRecord(
            id=self._next_id(),
            object_key=object_key,
            method=method,
            confidence=confidence,
            created_at=now,
            updated_at=now,
        )
        self._normalization_meta[object_key] = record
        return record

    def get_normalization_metadata(
        self, *, object_key: str
    ) -> NormalizationMetadataRecord | None:
        return self._normalization_meta.get(object_key)

    # -- provenance --

    def get_or_create_provenance(
        self, *, object_key: str, created_at: datetime
    ) -> ProvenanceRecord:
        if object_key not in self._provenance:
            self._provenance[object_key] = ProvenanceRecord(
                id=self._next_id(),
                object_key=object_key,
                created_at=created_at,
                updated_at=created_at,
            )
        return self._provenance[object_key]

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
        for s in self._provenance_sources:
            if (
                s.provenance_id == provenance_id
                and s.ingestion_id == ingestion_id
                and s.source_type == source_type
            ):
                return None
        source = ProvenanceSourceRecord(
            id=self._next_id(),
            provenance_id=provenance_id,
            ingestion_id=ingestion_id,
            source_type=source_type,
            source_uri=source_uri,
            source_actor=source_actor,
            captured_at=captured_at,
        )
        self._provenance_sources.append(source)
        return source

    # -- anchor notes --

    def upsert_anchor_note(
        self,
        *,
        ingestion_id: str,
        normalized_object_key: str,
        vault_path: str,
        created_at: datetime,
    ) -> AnchorRecord:
        record = AnchorRecord(
            id=self._next_id(),
            ingestion_id=ingestion_id,
            normalized_object_key=normalized_object_key,
            vault_path=vault_path,
            created_at=created_at,
            updated_at=created_at,
        )
        self._anchors[normalized_object_key] = record
        return record

    def list_anchor_notes(self, *, ingestion_id: str) -> list[AnchorRecord]:
        return [a for a in self._anchors.values() if a.ingestion_id == ingestion_id]

    def get_anchor_by_normalized_key(
        self, *, normalized_object_key: str
    ) -> AnchorRecord | None:
        return self._anchors.get(normalized_object_key)

    def delete_anchor_note(self, *, normalized_object_key: str) -> None:
        self._anchors.pop(normalized_object_key, None)

    # -- indexing runs --

    def create_indexing_run(
        self,
        *,
        ingestion_id: str,
        status: str,
        created_at: datetime,
    ) -> IngestionIndexingRun:
        run = IngestionIndexingRun(
            id=self._next_id(),
            ingestion_id=ingestion_id,
            job_id=None,
            status=IndexingRunStatus(status),
            source_count=0,
            chunk_count=0,
            embedding_count=0,
            failed_count=0,
            error=None,
            created_at=created_at,
            updated_at=created_at,
            finished_at=None,
        )
        self._indexing_runs[run.id] = run
        return run

    def get_indexing_run(self, *, indexing_run_id: str) -> IngestionIndexingRun | None:
        return self._indexing_runs.get(indexing_run_id)

    def update_indexing_run_job(
        self,
        *,
        indexing_run_id: str,
        job_id: str,
        updated_at: datetime,
    ) -> IngestionIndexingRun | None:
        run = self._indexing_runs.get(indexing_run_id)
        if run is None:
            return None
        updated = run.model_copy(update={"job_id": job_id, "updated_at": updated_at})
        self._indexing_runs[indexing_run_id] = updated
        return updated

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
        run = self._indexing_runs.get(indexing_run_id)
        if run is None:
            return None
        updated = run.model_copy(
            update={
                "status": IndexingRunStatus(status),
                "source_count": source_count,
                "chunk_count": chunk_count,
                "embedding_count": embedding_count,
                "failed_count": failed_count,
                "error": error,
                "updated_at": updated_at,
                "finished_at": finished_at,
            }
        )
        self._indexing_runs[indexing_run_id] = updated
        return updated

    # -- health --

    def is_healthy(self) -> bool:
        return self._healthy


# ---------------------------------------------------------------------------
# In-memory OAS fake
# ---------------------------------------------------------------------------


class _FakeOAS:
    """Minimal OAS fake for store-stage testing."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._content_types: dict[str, str] = {}
        self._fail_put = False
        self._fail_stat = False
        self._content_to_key: dict[bytes, str] = {}

    def _make_object_record(self, object_key: str):
        """Mimics OAS ObjectRecord (returned by put_object / stat_object)."""
        from types import SimpleNamespace

        ref = SimpleNamespace(object_key=object_key)
        meta = SimpleNamespace(
            content_type=self._content_types.get(object_key, "application/octet-stream")
        )
        return SimpleNamespace(ref=ref, metadata=meta)

    def _make_put_result(self, object_key: str, write_disposition: str):
        """Mimics OAS ObjectPutResult."""
        from types import SimpleNamespace

        return SimpleNamespace(
            object=self._make_object_record(object_key),
            write_disposition=write_disposition,
        )

    def _make_get_result(self, object_key: str, content: bytes):
        """Mimics OAS ObjectGetResult (returned by get_object)."""
        from types import SimpleNamespace

        obj = self._make_object_record(object_key)
        return SimpleNamespace(object=obj, content=content)

    def put_object(
        self,
        *,
        meta,
        content: bytes,
        extension: str,
        content_type: str,
        original_filename: str,
        source_uri: str,
    ):
        from packages.brain_shared.envelope import success, failure
        from packages.brain_shared.errors import internal_error

        if self._fail_put:
            return failure(meta=meta, errors=[internal_error("OAS put failed")])
        import hashlib

        existing_key = self._content_to_key.get(content)
        if existing_key is not None:
            self._objects[existing_key] = content
            self._content_types[existing_key] = content_type
            return success(
                meta=meta, payload=self._make_put_result(existing_key, "existing")
            )

        key = f"sha256/{hashlib.sha256(content).hexdigest()}.{extension}"
        self._objects[key] = content
        self._content_types[key] = content_type
        self._content_to_key[content] = key
        return success(meta=meta, payload=self._make_put_result(key, "created"))

    def stat_object(self, *, meta, object_key: str):
        from packages.brain_shared.envelope import success, failure
        from packages.brain_shared.errors import not_found_error

        if self._fail_stat or object_key not in self._objects:
            return failure(
                meta=meta, errors=[not_found_error(f"not found: {object_key}")]
            )
        return success(meta=meta, payload=self._make_object_record(object_key))

    def get_object(self, *, meta, object_key: str):
        from packages.brain_shared.envelope import success, failure
        from packages.brain_shared.errors import not_found_error

        if object_key not in self._objects:
            return failure(
                meta=meta, errors=[not_found_error(f"not found: {object_key}")]
            )
        content = self._objects[object_key]
        return success(meta=meta, payload=self._make_get_result(object_key, content))


class _FakeVAS:
    """Minimal VAS fake for anchor-stage testing."""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    def create_file(self, *, meta, file_path: str, content: str):
        from packages.brain_shared.envelope import failure, success
        from packages.brain_shared.errors import conflict_error

        if file_path in self.files:
            return failure(meta=meta, errors=[conflict_error(f"exists: {file_path}")])
        self.files[file_path] = content
        return success(meta=meta, payload=object())

    def append_file(self, *, meta, file_path: str, content: str):
        from packages.brain_shared.envelope import failure, success
        from packages.brain_shared.errors import not_found_error

        if file_path not in self.files:
            return failure(meta=meta, errors=[not_found_error(f"missing: {file_path}")])
        self.files[file_path] += content
        return success(meta=meta, payload=object())


class _FakeJobService:
    """Minimal Job Service fake for async ingestion orchestration tests."""

    def __init__(self) -> None:
        self.created_jobs: list[dict[str, object]] = []
        self.run_now_calls: list[str] = []
        self.fail_create = False
        self.fail_run_now = False
        self._counter = 0

    def create_job(
        self,
        *,
        meta,
        summary: str,
        details: str | None = None,
        origin_reference: str | None = None,
        schedule_type: str,
        timezone: str,
        definition: dict[str, object],
        job_action: dict[str, object],
        start_state: str = "draft",
    ):
        from types import SimpleNamespace

        from packages.brain_shared.envelope import failure, success
        from packages.brain_shared.errors import dependency_error

        if self.fail_create:
            return failure(meta=meta, errors=[dependency_error("job create failed")])
        self._counter += 1
        job_id = f"job-{self._counter}"
        self.created_jobs.append(
            {
                "job_id": job_id,
                "summary": summary,
                "origin_reference": origin_reference,
                "schedule_type": schedule_type,
                "timezone": timezone,
                "definition": definition,
                "job_action": job_action,
                "start_state": start_state,
            }
        )
        payload = SimpleNamespace(job=SimpleNamespace(id=job_id))
        return success(meta=meta, payload=payload)

    def run_job_now(self, *, meta, job_id: str):
        from types import SimpleNamespace

        from packages.brain_shared.envelope import failure, success
        from packages.brain_shared.errors import dependency_error

        if self.fail_run_now:
            return failure(meta=meta, errors=[dependency_error("job run_now failed")])
        self.run_now_calls.append(job_id)
        payload = SimpleNamespace(job=SimpleNamespace(id=job_id), execution=None)
        return success(meta=meta, payload=payload)


class _FakeUtilityService:
    """Minimal Utility Service fake for indexing tests."""

    def chunk_text(self, *, meta, text: str):
        from types import SimpleNamespace

        from packages.brain_shared.envelope import success

        return success(
            meta=meta,
            payload=[SimpleNamespace(chunk_ordinal=0, text=text, reference_range="0")],
        )


class _FakeLanguageModelService:
    """Minimal LMS fake for indexing tests."""

    def embed_batch(self, *, meta, texts):
        from types import SimpleNamespace

        from packages.brain_shared.envelope import success

        return success(
            meta=meta,
            payload=[
                SimpleNamespace(values=(0.1, 0.2), provider="fake", model="fake")
                for _text in texts
            ],
        )


class _FakeEmbeddingAuthorityService:
    """Minimal EAS fake for indexing tests."""

    def __init__(self) -> None:
        self.sources: list[dict[str, object]] = []
        self.chunks: list[object] = []
        self.vectors: list[object] = []

    def get_active_spec(self, *, meta):
        from types import SimpleNamespace

        from packages.brain_shared.envelope import success

        return success(meta=meta, payload=SimpleNamespace(id="spec-1"))

    def upsert_source(
        self,
        *,
        meta,
        canonical_reference: str,
        source_type: str,
        service: str,
        principal: str,
        metadata,
    ):
        from types import SimpleNamespace

        from packages.brain_shared.envelope import success

        source = SimpleNamespace(id=f"source-{len(self.sources) + 1}")
        self.sources.append(
            {
                "canonical_reference": canonical_reference,
                "source_type": source_type,
                "service": service,
                "principal": principal,
                "metadata": metadata,
            }
        )
        return success(meta=meta, payload=source)

    def upsert_chunks(self, *, meta, items):
        from types import SimpleNamespace

        from packages.brain_shared.envelope import success

        chunks = [
            SimpleNamespace(
                id=f"chunk-{len(self.chunks) + index + 1}",
                text=item["text"],
            )
            for index, item in enumerate(items)
        ]
        self.chunks.extend(chunks)
        return success(meta=meta, payload=chunks)

    def upsert_embedding_vectors(self, *, meta, items):
        from types import SimpleNamespace

        from packages.brain_shared.envelope import success

        records = [SimpleNamespace(chunk_id=item["chunk_id"]) for item in items]
        self.vectors.extend(records)
        return success(meta=meta, payload=records)


class _TextExtractor(BaseExtractor):
    """Extractor that emits one text artifact for any raw payload."""

    def can_extract(self, context) -> bool:
        return True

    def extract(self, context) -> Sequence[ExtractedArtifact]:
        return (
            ExtractedArtifact(
                payload=context.payload,
                mime_type="text/plain",
                method="text-extract",
            ),
        )


class _TextNormalizer(BaseNormalizer):
    """Normalizer that passes through extracted text content."""

    def can_normalize(self, context) -> bool:
        return True

    def normalize(self, context) -> Sequence[NormalizedArtifact]:
        return (
            NormalizedArtifact(
                payload=context.payload,
                mime_type="text/markdown",
                method="text-normalize",
            ),
        )


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _test_meta():
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="test-user")


def _pv(env):
    """Unwrap envelope payload value (Payload[T].value)."""
    assert env.payload is not None, f"Expected payload, got errors: {env.errors}"
    return env.payload.value


def _make_settings(**overrides) -> IngestionServiceSettings:
    defaults = {
        "anchor_folder": "Ingestion",
        "max_payload_bytes": 10_485_760,
    }
    defaults.update(overrides)
    return IngestionServiceSettings(**defaults)


def _make_service(
    *,
    repo: _FakeRepository | None = None,
    oas: _FakeOAS | None = None,
    vas: _FakeVAS | None = None,
    job_service: _FakeJobService | None = None,
    utility_service: _FakeUtilityService | None = None,
    language_model_service: _FakeLanguageModelService | None = None,
    embedding_authority_service: _FakeEmbeddingAuthorityService | None = None,
    settings: IngestionServiceSettings | None = None,
    extractor_registry: ExtractorRegistry | None = None,
    normalizer_registry: NormalizerRegistry | None = None,
) -> tuple[DefaultIngestionService, _FakeRepository, _FakeOAS, _FakeJobService]:
    repo = repo or _FakeRepository()
    oas = oas or _FakeOAS()
    vas = vas or _FakeVAS()
    job_service = job_service or _FakeJobService()
    svc_settings = settings or _make_settings()
    svc = DefaultIngestionService(
        settings=svc_settings,
        repository=repo,
        runtime=None,  # type: ignore[arg-type]
        oas=oas,
        vas=vas,
        job_service=job_service,
        extractor_registry=extractor_registry or ExtractorRegistry(),
        normalizer_registry=normalizer_registry or NormalizerRegistry(),
        utility_service=utility_service,
        language_model_service=language_model_service,
        embedding_authority_service=embedding_authority_service,
    )
    return svc, repo, oas, job_service


# ---------------------------------------------------------------------------
# submit_ingestion tests
# ---------------------------------------------------------------------------


class TestSubmitIngestion:
    def test_valid_payload_submission_returns_ingestion(self) -> None:
        svc, repo, _, _ = _make_service()
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"hello world",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert not env.errors
        assert _pv(env).source_type == "test"

    def test_valid_submission_creates_store_stage_run(self) -> None:
        svc, repo, _, _ = _make_service()
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"data",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert not env.errors
        ingestion_id = _pv(env).id
        runs = repo.list_stage_runs(ingestion_id=ingestion_id, stage="store")
        assert len(runs) == 1
        assert runs[0].status == StageRunStatus.success

    def test_valid_submission_records_store_artifact_outcome(self) -> None:
        svc, repo, _, _ = _make_service()
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"artifact content",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert not env.errors
        outcomes = repo.list_stage_artifact_outcomes(
            ingestion_id=_pv(env).id, stage="store", status=None
        )
        assert len(outcomes) == 1
        assert outcomes[0].status == StageArtifactStatus.success
        assert outcomes[0].object_key is not None

    def test_duplicate_payload_records_store_skip(self) -> None:
        svc, repo, _, _ = _make_service()
        first = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"same",
            capture_time="2026-01-01T00:00:00Z",
        )
        second = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"same",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert not first.errors
        assert not second.errors
        outcomes = repo.list_stage_artifact_outcomes(
            ingestion_id=_pv(second).id, stage="store", status=None
        )
        assert len(outcomes) == 1
        assert outcomes[0].status == StageArtifactStatus.skipped

    def test_existing_object_key_path(self) -> None:
        svc, repo, oas, _ = _make_service()
        # Pre-populate OAS with a known key
        oas._objects["existing/key.txt"] = b"content"
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="upload",
            existing_object_key="existing/key.txt",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert not env.errors
        outcomes = repo.list_stage_artifact_outcomes(
            ingestion_id=_pv(env).id, stage="store", status=None
        )
        assert len(outcomes) == 1
        assert outcomes[0].status == StageArtifactStatus.skipped
        assert outcomes[0].object_key == "existing/key.txt"

    def test_invalid_source_type_returns_failure(self) -> None:
        svc, _, _, _ = _make_service()
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="",
            payload=b"data",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert env.errors
        assert env.payload is None

    def test_invalid_capture_time_returns_failure(self) -> None:
        svc, _, _, _ = _make_service()
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"data",
            capture_time="not-a-date",
        )
        assert env.errors
        assert env.payload is None

    def test_naive_capture_time_returns_failure(self) -> None:
        svc, _, _, _ = _make_service()
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"data",
            capture_time="2026-01-01T00:00:00",
        )
        assert env.errors

    def test_both_payload_and_existing_key_returns_failure(self) -> None:
        svc, _, _, _ = _make_service()
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"data",
            existing_object_key="some/key",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert env.errors

    def test_rejected_submissions_still_create_ingestion_record(self) -> None:
        svc, repo, _, _ = _make_service()
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="",
            payload=b"data",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert env.errors
        # A rejected record should still be persisted
        all_records = list(repo._ingestions.values())
        assert len(all_records) == 1
        assert all_records[0].status == IngestionStatus.rejected

    def test_oas_failure_marks_ingestion_failed(self) -> None:
        svc, repo, oas, _ = _make_service()
        oas._fail_put = True
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"data",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert env.errors
        ingestion_records = list(repo._ingestions.values())
        assert len(ingestion_records) == 1
        assert ingestion_records[0].status == IngestionStatus.failed

    def test_provenance_recorded_after_store(self) -> None:
        svc, repo, _, _ = _make_service()
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="web",
            source_uri="https://example.com",
            payload=b"content",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert not env.errors
        assert len(repo._provenance) == 1
        assert len(repo._provenance_sources) == 1

    def test_submit_enqueues_follow_up_job_after_store(self) -> None:
        svc, _, _, jobs = _make_service()
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"payload",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert not env.errors
        assert len(jobs.created_jobs) == 1
        assert jobs.created_jobs[0]["job_action"] == {
            "type": "capability_invocation",
            "capability_id": "ingestion-advance",
            "input_payload": {
                "ingestion_id": _pv(env).id,
                "from_stage": "extract",
                "force_target": False,
            },
        }
        assert jobs.created_jobs[0]["start_state"] == "paused"
        assert jobs.run_now_calls == ["job-1"]

    def test_submit_job_dispatch_failure_marks_ingestion_failed(self) -> None:
        jobs = _FakeJobService()
        jobs.fail_run_now = True
        svc, repo, _, _ = _make_service(job_service=jobs)
        env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"payload",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert env.errors
        record = next(iter(repo._ingestions.values()))
        assert record.status == IngestionStatus.failed


# ---------------------------------------------------------------------------
# get_ingestion tests
# ---------------------------------------------------------------------------


class TestGetIngestion:
    def test_not_found_returns_failure(self) -> None:
        svc, _, _, _ = _make_service()
        env = svc.get_ingestion(meta=_test_meta(), ingestion_id="nonexistent")
        assert env.errors
        assert env.payload is None

    def test_existing_record_returned(self) -> None:
        svc, repo, _, _ = _make_service()
        submit_env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"hello",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert not submit_env.errors
        ingestion_id = _pv(submit_env).id

        env = svc.get_ingestion(meta=_test_meta(), ingestion_id=ingestion_id)
        assert not env.errors
        assert _pv(env).id == ingestion_id


# ---------------------------------------------------------------------------
# get_ingestion_status tests
# ---------------------------------------------------------------------------


class TestGetIngestionStatus:
    def test_not_found_returns_failure(self) -> None:
        svc, _, _, _ = _make_service()
        env = svc.get_ingestion_status(meta=_test_meta(), ingestion_id="nope")
        assert env.errors

    def test_returns_status_projection(self) -> None:
        svc, repo, _, _ = _make_service()
        submit_env = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"x",
            capture_time="2026-01-01T00:00:00Z",
        )
        assert not submit_env.errors
        ingestion_id = _pv(submit_env).id

        env = svc.get_ingestion_status(meta=_test_meta(), ingestion_id=ingestion_id)
        assert not env.errors
        assert _pv(env).ingestion_id == ingestion_id
        assert _pv(env).status is not None


# ---------------------------------------------------------------------------
# list_ingestions tests
# ---------------------------------------------------------------------------


class TestListIngestions:
    def test_empty_repository_returns_empty_list(self) -> None:
        svc, _, _, _ = _make_service()
        env = svc.list_ingestions(meta=_test_meta())
        assert not env.errors
        assert _pv(env).ingestions == []
        assert _pv(env).cursor is None

    def test_returns_submitted_ingestions(self) -> None:
        svc, _, _, _ = _make_service()
        for _ in range(3):
            svc.submit_ingestion(
                meta=_test_meta(),
                source_type="test",
                payload=b"data",
                capture_time="2026-01-01T00:00:00Z",
            )
        env = svc.list_ingestions(meta=_test_meta())
        assert not env.errors
        assert len(_pv(env).ingestions) == 3

    def test_limit_respected(self) -> None:
        svc, _, _, _ = _make_service()
        for _ in range(5):
            svc.submit_ingestion(
                meta=_test_meta(),
                source_type="test",
                payload=b"data",
                capture_time="2026-01-01T00:00:00Z",
            )
        env = svc.list_ingestions(meta=_test_meta(), limit=2)
        assert not env.errors
        assert len(_pv(env).ingestions) == 2
        assert _pv(env).cursor is not None

    def test_limit_clamped_to_minimum(self) -> None:
        svc, _, _, _ = _make_service()
        env = svc.list_ingestions(meta=_test_meta(), limit=0)
        assert not env.errors  # should not error, just clamp


# ---------------------------------------------------------------------------
# health tests
# ---------------------------------------------------------------------------


class TestHealth:
    def test_healthy_repository(self) -> None:
        svc, repo, _, _ = _make_service()
        repo._healthy = True
        env = svc.health(meta=_test_meta())
        assert not env.errors
        assert _pv(env).service_ready is True

    def test_unhealthy_repository(self) -> None:
        svc, repo, _, _ = _make_service()
        repo._healthy = False
        env = svc.health(meta=_test_meta())
        assert not env.errors
        assert _pv(env).service_ready is False
        assert "unreachable" in _pv(env).detail

    def test_repository_raises_treated_as_unhealthy(self) -> None:
        svc, repo, _, _ = _make_service()

        def _raise():
            raise RuntimeError("db is gone")

        repo.is_healthy = _raise
        env = svc.health(meta=_test_meta())
        assert not env.errors
        assert _pv(env).service_ready is False


# ---------------------------------------------------------------------------
# retry_ingestion_stage tests
# ---------------------------------------------------------------------------


class TestRetryIngestionStage:
    def test_unknown_stage_returns_failure(self) -> None:
        svc, _, _, _ = _make_service()
        env = svc.retry_ingestion_stage(
            meta=_test_meta(),
            ingestion_id="any",
            stage="unknown_stage",
        )
        assert env.errors
        assert any("unknown stage" in e.message for e in env.errors)

    def test_ingestion_not_found_returns_failure(self) -> None:
        svc, _, _, _ = _make_service()
        env = svc.retry_ingestion_stage(
            meta=_test_meta(),
            ingestion_id="nonexistent",
            stage="extract",
        )
        assert env.errors
        assert any("not found" in e.message for e in env.errors)

    def test_failed_stage_retry_enqueues_advance_job(self) -> None:
        svc, repo, _, jobs = _make_service()
        record = repo.create_ingestion(
            status=IngestionStatus.failed.value,
            source_type="test",
            source_uri=None,
            source_actor=None,
            capture_time=datetime(2026, 1, 1, tzinfo=UTC),
            mime_type="text/plain",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        repo.create_stage_run(
            ingestion_id=record.id,
            stage="extract",
            status=StageRunStatus.failed.value,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        env = svc.retry_ingestion_stage(
            meta=_test_meta(),
            ingestion_id=record.id,
            stage="extract",
        )
        assert not env.errors
        assert len(jobs.created_jobs) == 1
        assert (
            jobs.created_jobs[0]["job_action"]["input_payload"]["from_stage"]
            == "extract"
        )


class TestAdvanceIngestion:
    def test_force_target_replays_successful_requested_stage_only(self) -> None:
        svc, repo, _, _ = _make_service()
        record = repo.create_ingestion(
            status=IngestionStatus.running.value,
            source_type="test",
            source_uri=None,
            source_actor=None,
            capture_time=datetime(2026, 1, 1, tzinfo=UTC),
            mime_type="text/plain",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        repo.create_stage_run(
            ingestion_id=record.id,
            stage="extract",
            status=StageRunStatus.success.value,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        repo.create_stage_run(
            ingestion_id=record.id,
            stage="normalize",
            status=StageRunStatus.success.value,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        repo.create_stage_run(
            ingestion_id=record.id,
            stage="anchor",
            status=StageRunStatus.success.value,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        called: list[str] = []

        def _dispatch_stage(*, meta, ingestion_id: str, stage: str):
            from packages.brain_shared.envelope import success

            called.append(stage)
            if stage == "extract":
                return success(
                    meta=meta,
                    payload=type(
                        "Payload",
                        (),
                        {
                            "ingestion_id": ingestion_id,
                            "succeeded": 1,
                            "failed": 0,
                            "errors": (),
                        },
                    )(),
                )
            if stage == "normalize":
                return success(
                    meta=meta,
                    payload=type(
                        "Payload",
                        (),
                        {
                            "ingestion_id": ingestion_id,
                            "succeeded": 1,
                            "failed": 0,
                            "errors": (),
                        },
                    )(),
                )
            return success(
                meta=meta,
                payload=type(
                    "Payload",
                    (),
                    {
                        "ingestion_id": ingestion_id,
                        "anchored": 1,
                        "failed": 0,
                        "errors": (),
                    },
                )(),
            )

        svc._dispatch_stage = _dispatch_stage  # type: ignore[method-assign]

        env = svc.advance_ingestion(
            meta=_test_meta(),
            ingestion_id=record.id,
            from_stage="extract",
            force_target=True,
        )
        assert not env.errors
        assert called == ["extract"]
        assert _pv(env).status == IngestionStatus.complete

    def test_happy_path_advances_to_complete(self) -> None:
        vas = _FakeVAS()
        svc, repo, _, _ = _make_service(
            vas=vas,
            extractor_registry=ExtractorRegistry([_TextExtractor()]),
            normalizer_registry=NormalizerRegistry([_TextNormalizer()]),
        )
        submit = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"# hello",
            capture_time="2026-01-01T00:00:00Z",
            mime_type="text/plain",
        )
        assert not submit.errors

        env = svc.advance_ingestion(
            meta=_test_meta(),
            ingestion_id=_pv(submit).id,
            from_stage="extract",
            force_target=False,
        )
        assert not env.errors
        assert _pv(env).status == IngestionStatus.complete
        anchor_runs = repo.list_stage_runs(ingestion_id=_pv(submit).id, stage="anchor")
        assert len(anchor_runs) == 1
        assert anchor_runs[0].status == StageRunStatus.success
        assert len(vas.files) == 1

    def test_builtin_text_handlers_advance_to_anchor_and_schedule_indexing(
        self,
    ) -> None:
        vas = _FakeVAS()
        svc, repo, _, jobs = _make_service(
            vas=vas,
            extractor_registry=ExtractorRegistry([BuiltInTextExtractor()]),
            normalizer_registry=NormalizerRegistry([BuiltInTextNormalizer()]),
        )
        submit = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"hello",
            capture_time="2026-01-01T00:00:00Z",
            mime_type="text/plain",
        )
        assert not submit.errors

        env = svc.advance_ingestion(
            meta=_test_meta(),
            ingestion_id=_pv(submit).id,
            from_stage="extract",
            force_target=False,
        )

        assert not env.errors
        assert _pv(env).status == IngestionStatus.complete
        assert len(vas.files) == 1
        assert jobs.created_jobs[-1]["job_action"]["capability_id"] == (
            "ingestion-index-anchored"
        )
        assert jobs.created_jobs[-1]["start_state"] == "paused"

    def test_unsupported_mime_records_extract_failure(self) -> None:
        svc, repo, _, _ = _make_service(
            extractor_registry=ExtractorRegistry([BuiltInTextExtractor()]),
            normalizer_registry=NormalizerRegistry([BuiltInTextNormalizer()]),
        )
        submit = svc.submit_ingestion(
            meta=_test_meta(),
            source_type="test",
            payload=b"\x00\x01",
            capture_time="2026-01-01T00:00:00Z",
            mime_type="application/octet-stream",
        )
        assert not submit.errors

        env = svc.advance_ingestion(
            meta=_test_meta(),
            ingestion_id=_pv(submit).id,
            from_stage="extract",
            force_target=False,
        )

        assert not env.errors
        assert _pv(env).status == IngestionStatus.failed
        outcomes = repo.list_stage_artifact_outcomes(
            ingestion_id=_pv(submit).id, stage="extract", status="failed"
        )
        assert len(outcomes) == 1
        assert "no extractor available" in (outcomes[0].error or "")


class TestAnchorStage:
    def test_noop_anchor_creates_one_skipped_run(self) -> None:
        vas = _FakeVAS()
        svc, repo, _, _ = _make_service(vas=vas)
        record = repo.create_ingestion(
            status=IngestionStatus.running.value,
            source_type="test",
            source_uri=None,
            source_actor=None,
            capture_time=datetime(2026, 1, 1, tzinfo=UTC),
            mime_type="text/plain",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        env = svc.run_anchor_stage(meta=_test_meta(), ingestion_id=record.id)
        assert not env.errors
        runs = repo.list_stage_runs(ingestion_id=record.id, stage="anchor")
        assert len(runs) == 1
        assert runs[0].status == StageRunStatus.skipped


class TestIndexAnchoredIngestion:
    def test_indexes_anchor_through_public_service_dependencies(self) -> None:
        repo = _FakeRepository()
        oas = _FakeOAS()
        utility = _FakeUtilityService()
        lms = _FakeLanguageModelService()
        eas = _FakeEmbeddingAuthorityService()
        svc, repo, oas, _jobs = _make_service(
            repo=repo,
            oas=oas,
            utility_service=utility,
            language_model_service=lms,
            embedding_authority_service=eas,
        )
        record = repo.create_ingestion(
            status=IngestionStatus.complete.value,
            source_type="test",
            source_uri=None,
            source_actor=None,
            capture_time=datetime(2026, 1, 1, tzinfo=UTC),
            mime_type="text/plain",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        put_env = oas.put_object(
            meta=_test_meta(),
            content=b"hello world",
            extension="md",
            content_type="text/markdown",
            original_filename="test.md",
            source_uri="",
        )
        object_key = _pv(put_env).object.ref.object_key
        repo.upsert_anchor_note(
            ingestion_id=record.id,
            normalized_object_key=object_key,
            vault_path="Ingestion/test.md",
            created_at=datetime.now(UTC),
        )
        run = repo.create_indexing_run(
            ingestion_id=record.id,
            status=IndexingRunStatus.queued.value,
            created_at=datetime.now(UTC),
        )

        env = svc.index_anchored_ingestion(
            meta=_test_meta(),
            ingestion_id=record.id,
            indexing_run_id=run.id,
        )

        assert not env.errors
        assert _pv(env).source_count == 1
        assert _pv(env).chunk_count == 1
        assert _pv(env).embedding_count == 1
        refreshed = repo.get_indexing_run(indexing_run_id=run.id)
        assert refreshed is not None
        assert refreshed.status == IndexingRunStatus.succeeded
        assert len(eas.sources) == 1
        assert len(eas.vectors) == 1

    def test_missing_indexing_dependency_marks_run_failed(self) -> None:
        repo = _FakeRepository()
        svc, repo, _, _ = _make_service(repo=repo)
        record = repo.create_ingestion(
            status=IngestionStatus.complete.value,
            source_type="test",
            source_uri=None,
            source_actor=None,
            capture_time=datetime(2026, 1, 1, tzinfo=UTC),
            mime_type="text/plain",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        run = repo.create_indexing_run(
            ingestion_id=record.id,
            status=IndexingRunStatus.queued.value,
            created_at=datetime.now(UTC),
        )

        env = svc.index_anchored_ingestion(
            meta=_test_meta(),
            ingestion_id=record.id,
            indexing_run_id=run.id,
        )

        assert env.errors
        refreshed = repo.get_indexing_run(indexing_run_id=run.id)
        assert refreshed is not None
        assert refreshed.status == IndexingRunStatus.failed
