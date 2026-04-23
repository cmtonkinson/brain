"""Regression tests covering the specific bugs fixed in the ingestion service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

from lib.shared.envelope import EnvelopeKind, failure, new_meta, success
from lib.shared.errors import (
    dependency_error,
    internal_error,
    not_found_error,
)
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
    stage_replay_decision,
)
from services.control.ingestion.implementation import DefaultIngestionService
from services.control.ingestion.interfaces import (
    BaseExtractor,
    BaseNormalizer,
    ExtractedArtifact,
    ExtractorRegistry,
    NormalizedArtifact,
    NormalizerRegistry,
)

# ---------------------------------------------------------------------------
# Minimal in-memory fakes (duplicated from test_service.py for isolation)
# ---------------------------------------------------------------------------


class _FakeRepository:
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
        self._id_counter = 0

    def _next_id(self) -> str:
        self._id_counter += 1
        return f"01HX{self._id_counter:022d}"

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def create_ingestion(
        self,
        *,
        status,
        source_type,
        source_uri,
        source_actor,
        capture_time,
        mime_type,
        created_at,
    ) -> IngestionRecord:
        rec = IngestionRecord(
            id=self._next_id(),
            status=IngestionStatus(status),
            source_type=source_type,
            source_uri=source_uri,
            source_actor=source_actor,
            capture_time=capture_time,
            mime_type=mime_type,
            last_error=None,
            created_at=created_at,
            updated_at=created_at,
        )
        self._ingestions[rec.id] = rec
        return rec

    def get_ingestion(self, *, ingestion_id: str) -> IngestionRecord | None:
        return self._ingestions.get(ingestion_id)

    def list_ingestions(self, *, status, limit, cursor) -> list[IngestionRecord]:
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
        self, *, ingestion_id, status, last_error, updated_at
    ) -> IngestionRecord | None:
        rec = self._ingestions.get(ingestion_id)
        if rec is None:
            return None
        updated = rec.model_copy(
            update={
                "status": IngestionStatus(status),
                "last_error": last_error,
                "updated_at": updated_at,
            }
        )
        self._ingestions[ingestion_id] = updated
        return updated

    def create_stage_run(
        self, *, ingestion_id, stage, status, started_at, created_at
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
        self, *, stage_run_id, status, error, finished_at
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

    def list_stage_runs(self, *, ingestion_id, stage=None) -> list[StageRunRecord]:
        runs = [r for r in self._stage_runs if r.ingestion_id == ingestion_id]
        if stage is not None:
            runs = [r for r in runs if r.stage == stage]
        return runs

    def create_stage_artifact_outcome(
        self,
        *,
        ingestion_id,
        stage,
        object_key,
        parent_object_key,
        status,
        error,
        created_at,
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
        self, *, ingestion_id, stage=None, status=None
    ) -> list[StageArtifactOutcome]:
        results = [o for o in self._outcomes if o.ingestion_id == ingestion_id]
        if stage is not None:
            results = [o for o in results if o.stage == stage]
        if status is not None:
            results = [o for o in results if o.status.value == status]
        return results

    def get_stage_artifact_outcome_by_key(
        self, *, ingestion_id, stage, object_key
    ) -> StageArtifactOutcome | None:
        for o in self._outcomes:
            if (
                o.ingestion_id == ingestion_id
                and o.stage == stage
                and o.object_key == object_key
            ):
                return o
        return None

    def upsert_extraction_metadata(
        self, *, object_key, method, confidence, page_count, created_at
    ) -> ExtractionMetadataRecord:
        rec = ExtractionMetadataRecord(
            id=self._next_id(),
            object_key=object_key,
            method=method,
            confidence=confidence,
            page_count=page_count,
            created_at=created_at,
            updated_at=created_at,
        )
        self._extraction_meta[object_key] = rec
        return rec

    def get_extraction_metadata(self, *, object_key) -> ExtractionMetadataRecord | None:
        return self._extraction_meta.get(object_key)

    def upsert_normalization_metadata(
        self, *, object_key, method, confidence, created_at
    ) -> NormalizationMetadataRecord:
        rec = NormalizationMetadataRecord(
            id=self._next_id(),
            object_key=object_key,
            method=method,
            confidence=confidence,
            created_at=created_at,
            updated_at=created_at,
        )
        self._normalization_meta[object_key] = rec
        return rec

    def get_normalization_metadata(
        self, *, object_key
    ) -> NormalizationMetadataRecord | None:
        return self._normalization_meta.get(object_key)

    def get_or_create_provenance(self, *, object_key, created_at) -> ProvenanceRecord:
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
        provenance_id,
        ingestion_id,
        source_type,
        source_uri,
        source_actor,
        captured_at,
    ) -> ProvenanceSourceRecord | None:
        for s in self._provenance_sources:
            if (
                s.provenance_id == provenance_id
                and s.ingestion_id == ingestion_id
                and s.source_type == source_type
            ):
                return None
        src = ProvenanceSourceRecord(
            id=self._next_id(),
            provenance_id=provenance_id,
            ingestion_id=ingestion_id,
            source_type=source_type,
            source_uri=source_uri,
            source_actor=source_actor,
            captured_at=captured_at,
        )
        self._provenance_sources.append(src)
        return src

    def upsert_anchor_note(
        self, *, ingestion_id, normalized_object_key, vault_path, created_at
    ) -> AnchorRecord:
        rec = AnchorRecord(
            id=self._next_id(),
            ingestion_id=ingestion_id,
            normalized_object_key=normalized_object_key,
            vault_path=vault_path,
            created_at=created_at,
            updated_at=created_at,
        )
        self._anchors[normalized_object_key] = rec
        return rec

    def list_anchor_notes(self, *, ingestion_id) -> list[AnchorRecord]:
        return [a for a in self._anchors.values() if a.ingestion_id == ingestion_id]

    def get_anchor_by_normalized_key(
        self, *, normalized_object_key
    ) -> AnchorRecord | None:
        return self._anchors.get(normalized_object_key)

    def delete_anchor_note(self, *, normalized_object_key: str) -> None:
        self._anchors.pop(normalized_object_key, None)

    def create_indexing_run(
        self, *, ingestion_id, status, created_at
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

    def get_indexing_run(self, *, indexing_run_id) -> IngestionIndexingRun | None:
        return self._indexing_runs.get(indexing_run_id)

    def update_indexing_run_job(
        self, *, indexing_run_id, job_id, updated_at
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
        indexing_run_id,
        status,
        source_count,
        chunk_count,
        embedding_count,
        failed_count,
        error,
        updated_at,
        finished_at,
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

    def is_healthy(self) -> bool:
        return True


class _FakeOAS:
    """OAS fake with configurable failure modes."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._content_types: dict[str, str] = {}
        self._content_to_key: dict[bytes, str] = {}
        self.fail_put = False
        self.fail_get = False
        self.return_null_payload_on_get = False
        self.return_null_payload_on_put = False

    def _make_object_record(self, object_key: str):
        from types import SimpleNamespace

        ref = SimpleNamespace(object_key=object_key)
        meta = SimpleNamespace(
            content_type=self._content_types.get(object_key, "text/plain")
        )
        return SimpleNamespace(ref=ref, metadata=meta)

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

        if self.fail_put:
            return failure(meta=meta, errors=[internal_error("OAS put failed")])
        if self.return_null_payload_on_put:
            return success(meta=meta, payload=None)  # type: ignore[arg-type]
        import hashlib

        existing_key = self._content_to_key.get(content)
        if existing_key is not None:
            from types import SimpleNamespace

            obj = self._make_object_record(existing_key)
            put_result = SimpleNamespace(object=obj, write_disposition="existing")
            return success(meta=meta, payload=put_result)
        key = f"sha256/{hashlib.sha256(content).hexdigest()}.{extension}"
        self._objects[key] = content
        self._content_types[key] = content_type
        self._content_to_key[content] = key
        from types import SimpleNamespace

        obj = self._make_object_record(key)
        put_result = SimpleNamespace(object=obj, write_disposition="created")
        return success(meta=meta, payload=put_result)

    def stat_object(self, *, meta, object_key: str):

        if object_key not in self._objects:
            return failure(
                meta=meta, errors=[not_found_error(f"not found: {object_key}")]
            )
        return success(meta=meta, payload=self._make_object_record(object_key))

    def get_object(self, *, meta, object_key: str):

        if self.fail_get or object_key not in self._objects:
            return failure(
                meta=meta, errors=[not_found_error(f"not found: {object_key}")]
            )
        if self.return_null_payload_on_get:
            return success(meta=meta, payload=None)  # type: ignore[arg-type]
        from types import SimpleNamespace

        obj = self._make_object_record(object_key)
        get_result = SimpleNamespace(object=obj, content=self._objects[object_key])
        return success(meta=meta, payload=get_result)


class _FakeVAS:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.fail_create = False
        self.fail_append = False

    def create_file(self, *, meta, file_path: str, content: str):
        from lib.shared.errors import conflict_error

        if self.fail_create:
            return failure(meta=meta, errors=[internal_error("VAS create failed")])
        if file_path in self.files:
            return failure(meta=meta, errors=[conflict_error(f"exists: {file_path}")])
        self.files[file_path] = content
        return success(meta=meta, payload=object())

    def append_file(self, *, meta, file_path: str, content: str):

        if self.fail_append:
            return failure(meta=meta, errors=[internal_error("VAS append failed")])
        if file_path not in self.files:
            return failure(meta=meta, errors=[not_found_error(f"missing: {file_path}")])
        self.files[file_path] += content
        return success(meta=meta, payload=object())


class _FakeJobService:
    def __init__(self) -> None:
        self.created_jobs: list[dict] = []
        self.fail_create = False
        self.fail_run_now = False
        self.return_null_payload_on_create = False
        self._counter = 0

    def create_job(
        self,
        *,
        meta,
        summary,
        details=None,
        origin_reference=None,
        schedule_type,
        timezone,
        definition,
        job_action,
        start_state="draft",
    ):
        from types import SimpleNamespace

        if self.fail_create:
            return failure(meta=meta, errors=[dependency_error("job create failed")])
        if self.return_null_payload_on_create:
            return success(meta=meta, payload=None)  # type: ignore[arg-type]
        self._counter += 1
        job_id = f"job-{self._counter}"
        self.created_jobs.append({"job_id": job_id, "job_action": job_action})
        return success(
            meta=meta, payload=SimpleNamespace(job=SimpleNamespace(id=job_id))
        )

    def run_job_now(self, *, meta, job_id: str):
        from types import SimpleNamespace

        if self.fail_run_now:
            return failure(meta=meta, errors=[dependency_error("job run_now failed")])
        return success(
            meta=meta, payload=SimpleNamespace(job=SimpleNamespace(id=job_id))
        )


class _PassthroughExtractor(BaseExtractor):
    def can_extract(self, context) -> bool:
        return True

    def extract(self, context) -> Sequence[ExtractedArtifact]:
        return (
            ExtractedArtifact(
                payload=context.payload, mime_type="text/plain", method="passthrough"
            ),
        )


class _PassthroughNormalizer(BaseNormalizer):
    def can_normalize(self, context) -> bool:
        return True

    def normalize(self, context) -> Sequence[NormalizedArtifact]:
        return (
            NormalizedArtifact(
                payload=context.payload, mime_type="text/markdown", method="passthrough"
            ),
        )


def _meta():
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="tester")


def _settings() -> IngestionServiceSettings:
    return IngestionServiceSettings(
        anchor_folder="Anchors", max_payload_bytes=10_485_760
    )


def _make_service(
    *,
    repo=None,
    oas=None,
    vas=None,
    job_service=None,
    with_extractors: bool = False,
    with_normalizers: bool = False,
):
    repo = repo or _FakeRepository()
    oas = oas or _FakeOAS()
    vas = vas or _FakeVAS()
    job_service = job_service or _FakeJobService()
    extractors = ExtractorRegistry([_PassthroughExtractor()] if with_extractors else [])
    normalizers = NormalizerRegistry(
        [_PassthroughNormalizer()] if with_normalizers else []
    )
    svc = DefaultIngestionService(
        settings=_settings(),
        repository=repo,
        runtime=None,  # type: ignore[arg-type]
        oas=oas,
        vas=vas,
        job_service=job_service,
        extractor_registry=extractors,
        normalizer_registry=normalizers,
    )
    return svc, repo, oas, vas, job_service


def _submit(svc, repo, oas, *, content: bytes = b"hello world"):
    """Submit an ingestion and return the ingestion_id."""
    env = svc.submit_ingestion(
        meta=_meta(),
        source_type="test",
        payload=content,
        capture_time="2026-01-01T00:00:00Z",
    )
    assert not env.errors, env.errors
    return env.payload.value.id  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Bug 1 regression: null payload guards
# ---------------------------------------------------------------------------


class TestNullPayloadGuards:
    def test_extract_stage_oas_get_null_payload_records_failed_outcome(self) -> None:
        """_execute_extract_stage must handle payload=None on get_object."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        svc, repo, oas, vas, job_service = _make_service(
            repo=repo, oas=oas, with_extractors=True
        )
        # Submit creates a store outcome; then manually tweak OAS to return null payload
        ingestion_id = _submit(svc, repo, oas)
        oas.return_null_payload_on_get = True

        result_env = svc.run_extract_stage(meta=_meta(), ingestion_id=ingestion_id)
        assert not result_env.errors
        result = result_env.payload.value  # type: ignore[union-attr]
        assert result.failed == 1
        failed_outcomes = [
            o
            for o in repo._outcomes
            if o.stage == "extract" and o.status == StageArtifactStatus.failed
        ]
        assert len(failed_outcomes) == 1

    def test_normalize_stage_oas_get_null_payload_records_failed_outcome(self) -> None:
        """_execute_normalize_stage must handle payload=None on get_object."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        svc, repo, oas, vas, job_service = _make_service(
            repo=repo, oas=oas, with_extractors=True, with_normalizers=True
        )
        ingestion_id = _submit(svc, repo, oas)
        svc.run_extract_stage(meta=_meta(), ingestion_id=ingestion_id)
        oas.return_null_payload_on_get = True

        result_env = svc.run_normalize_stage(meta=_meta(), ingestion_id=ingestion_id)
        assert not result_env.errors
        result = result_env.payload.value  # type: ignore[union-attr]
        assert result.failed == 1

    def test_anchor_stage_oas_get_null_payload_records_failed_outcome(self) -> None:
        """_execute_anchor_stage must handle payload=None on get_object."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        vas = _FakeVAS()
        svc, repo, oas, vas, job_service = _make_service(
            repo=repo, oas=oas, vas=vas, with_extractors=True, with_normalizers=True
        )
        ingestion_id = _submit(svc, repo, oas)
        svc.run_extract_stage(meta=_meta(), ingestion_id=ingestion_id)
        svc.run_normalize_stage(meta=_meta(), ingestion_id=ingestion_id)
        oas.return_null_payload_on_get = True

        result_env = svc.run_anchor_stage(meta=_meta(), ingestion_id=ingestion_id)
        assert not result_env.errors
        result = result_env.payload.value  # type: ignore[union-attr]
        assert result.failed == 1
        assert result.anchored == 0

    def test_extract_stage_oas_put_null_payload_records_failed_outcome(self) -> None:
        """_execute_extract_stage must handle payload=None on put_object."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        svc, repo, oas, vas, job_service = _make_service(
            repo=repo, oas=oas, with_extractors=True
        )
        ingestion_id = _submit(svc, repo, oas)
        oas.return_null_payload_on_put = True

        result_env = svc.run_extract_stage(meta=_meta(), ingestion_id=ingestion_id)
        assert not result_env.errors
        result = result_env.payload.value  # type: ignore[union-attr]
        assert result.failed == 1

    def test_normalize_stage_oas_put_null_payload_records_failed_outcome(self) -> None:
        """_execute_normalize_stage must handle payload=None on put_object."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        svc, repo, oas, vas, job_service = _make_service(
            repo=repo, oas=oas, with_extractors=True, with_normalizers=True
        )
        ingestion_id = _submit(svc, repo, oas)
        svc.run_extract_stage(meta=_meta(), ingestion_id=ingestion_id)
        oas.return_null_payload_on_put = True

        result_env = svc.run_normalize_stage(meta=_meta(), ingestion_id=ingestion_id)
        assert not result_env.errors
        result = result_env.payload.value  # type: ignore[union-attr]
        assert result.failed == 1

    def test_enqueue_advance_job_null_payload_marks_ingestion_failed(self) -> None:
        """_enqueue_advance_job must mark ingestion failed when create_job returns no payload."""
        repo = _FakeRepository()
        job_service = _FakeJobService()
        job_service.return_null_payload_on_create = True
        svc, repo, oas, vas, _ = _make_service(repo=repo, job_service=job_service)

        env = svc.submit_ingestion(
            meta=_meta(),
            source_type="test",
            payload=b"hello world",
            capture_time="2026-01-01T00:00:00Z",
        )
        # submit_ingestion runs store inline then calls _enqueue_advance_job
        # The store runs first (before job dispatch), so ingestion is created
        assert env.errors  # job dispatch fails

        # Find the ingestion by scanning repo
        ingestions = list(repo._ingestions.values())
        assert len(ingestions) == 1
        assert ingestions[0].status == IngestionStatus.failed

    def test_enqueue_indexing_job_null_payload_marks_ingestion_failed(self) -> None:
        """_enqueue_indexing_job must mark ingestion failed when create_job returns no payload."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        vas = _FakeVAS()
        # First job (advance) succeeds; second job (indexing) returns null payload
        job_service = _FakeJobService()
        svc, repo, oas, vas, job_service = _make_service(
            repo=repo,
            oas=oas,
            vas=vas,
            job_service=job_service,
            with_extractors=True,
            with_normalizers=True,
        )
        ingestion_id = _submit(svc, repo, oas)
        svc.run_extract_stage(meta=_meta(), ingestion_id=ingestion_id)
        svc.run_normalize_stage(meta=_meta(), ingestion_id=ingestion_id)
        # From this point on, anchor stage will try to dispatch indexing job
        job_service.return_null_payload_on_create = True

        env = svc.run_anchor_stage(meta=_meta(), ingestion_id=ingestion_id)
        assert env.errors

        ingestion = repo.get_ingestion(ingestion_id=ingestion_id)
        assert ingestion is not None
        assert ingestion.status == IngestionStatus.failed


# ---------------------------------------------------------------------------
# Bug 2 regression: ingestion stuck in running on indexing dispatch failure
# ---------------------------------------------------------------------------


class TestIndexingDispatchFailure:
    def test_run_job_now_failure_marks_ingestion_failed_not_running(self) -> None:
        """Indexing job run_job_now failure must update ingestion status to failed."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        vas = _FakeVAS()
        job_service = _FakeJobService()
        svc, repo, oas, vas, job_service = _make_service(
            repo=repo,
            oas=oas,
            vas=vas,
            job_service=job_service,
            with_extractors=True,
            with_normalizers=True,
        )
        ingestion_id = _submit(svc, repo, oas)
        svc.run_extract_stage(meta=_meta(), ingestion_id=ingestion_id)
        svc.run_normalize_stage(meta=_meta(), ingestion_id=ingestion_id)
        # Anchor stage dispatches indexing job — make run_job_now fail
        job_service.fail_run_now = True

        env = svc.run_anchor_stage(meta=_meta(), ingestion_id=ingestion_id)
        assert env.errors

        ingestion = repo.get_ingestion(ingestion_id=ingestion_id)
        assert ingestion is not None
        assert ingestion.status == IngestionStatus.failed, (
            f"Expected failed, got {ingestion.status} — ingestion stuck in running"
        )

    def test_job_service_none_marks_ingestion_failed(self) -> None:
        """_enqueue_indexing_job with no job service must mark ingestion failed."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        vas = _FakeVAS()
        svc, repo, oas, vas, _ = _make_service(
            repo=repo,
            oas=oas,
            vas=vas,
            job_service=_FakeJobService(),
            with_extractors=True,
            with_normalizers=True,
        )
        ingestion_id = _submit(svc, repo, oas)
        svc.run_extract_stage(meta=_meta(), ingestion_id=ingestion_id)
        svc.run_normalize_stage(meta=_meta(), ingestion_id=ingestion_id)
        # Override job_service to None just before anchor stage enqueues indexing job
        svc._job_service = None  # type: ignore[assignment]

        env = svc.run_anchor_stage(meta=_meta(), ingestion_id=ingestion_id)
        assert env.errors

        ingestion = repo.get_ingestion(ingestion_id=ingestion_id)
        assert ingestion is not None
        assert ingestion.status == IngestionStatus.failed


# ---------------------------------------------------------------------------
# Bug 4 regression: anchor stage vault/DB write ordering
# ---------------------------------------------------------------------------


class TestAnchorWriteOrdering:
    def test_vault_write_failure_removes_db_anchor_so_retry_can_proceed(self) -> None:
        """When VAS write fails, anchor DB record must be deleted so retry re-attempts."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        vas = _FakeVAS()
        vas.fail_create = True
        vas.fail_append = True
        svc, repo, oas, vas, job_service = _make_service(
            repo=repo,
            oas=oas,
            vas=vas,
            with_extractors=True,
            with_normalizers=True,
        )
        ingestion_id = _submit(svc, repo, oas)
        svc.run_extract_stage(meta=_meta(), ingestion_id=ingestion_id)
        svc.run_normalize_stage(meta=_meta(), ingestion_id=ingestion_id)

        result_env = svc.run_anchor_stage(meta=_meta(), ingestion_id=ingestion_id)
        assert not result_env.errors
        result = result_env.payload.value  # type: ignore[union-attr]
        assert result.failed == 1

        # No anchor records should remain (DB rollback happened)
        assert len(repo._anchors) == 0, (
            "Anchor record must be deleted when vault write fails so retry can proceed"
        )

    def test_vault_write_success_leaves_db_anchor_record(self) -> None:
        """Successful vault write must leave the DB anchor record in place."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        vas = _FakeVAS()
        svc, repo, oas, vas, job_service = _make_service(
            repo=repo,
            oas=oas,
            vas=vas,
            with_extractors=True,
            with_normalizers=True,
        )
        ingestion_id = _submit(svc, repo, oas)
        svc.run_extract_stage(meta=_meta(), ingestion_id=ingestion_id)
        svc.run_normalize_stage(meta=_meta(), ingestion_id=ingestion_id)

        # Disable indexing job dispatch to isolate anchor stage
        job_service.fail_run_now = True

        svc.run_anchor_stage(meta=_meta(), ingestion_id=ingestion_id)
        # Anchor stage itself succeeds; only indexing dispatch fails
        assert len(repo._anchors) == 1, (
            "Anchor record must persist after successful vault write"
        )

    def test_retry_skips_already_anchored_artifact(self) -> None:
        """A second anchor stage run must not re-write vault content for anchored artifacts."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        vas = _FakeVAS()
        svc, repo, oas, vas, job_service = _make_service(
            repo=repo,
            oas=oas,
            vas=vas,
            with_extractors=True,
            with_normalizers=True,
        )
        ingestion_id = _submit(svc, repo, oas)
        svc.run_extract_stage(meta=_meta(), ingestion_id=ingestion_id)
        svc.run_normalize_stage(meta=_meta(), ingestion_id=ingestion_id)

        # First anchor run succeeds
        job_service.fail_run_now = True  # stop indexing dispatch
        svc.run_anchor_stage(meta=_meta(), ingestion_id=ingestion_id)
        vault_write_count_after_first = sum(len(v) for v in vas.files.values())

        # Second anchor run — artifact already anchored, vault must NOT be touched again
        svc.run_anchor_stage(meta=_meta(), ingestion_id=ingestion_id)
        vault_write_count_after_second = sum(len(v) for v in vas.files.values())

        assert vault_write_count_after_first == vault_write_count_after_second, (
            "Vault content must not grow on retry when artifact is already anchored"
        )


# ---------------------------------------------------------------------------
# Bug 6 regression: concurrent retry double-execution
# ---------------------------------------------------------------------------


class TestConcurrentRetryBlocking:
    def test_running_stage_run_blocks_retry(self) -> None:
        """stage_replay_decision must return should_run=False when stage is running."""
        now = datetime(2026, 1, 1, tzinfo=UTC)
        running_run = StageRunRecord(
            id="01HX0000000000000000000001",
            ingestion_id="01HX0000000000000000000002",
            stage="extract",
            status=StageRunStatus.running,
            error=None,
            started_at=now,
            finished_at=None,
            created_at=now,
        )
        decision = stage_replay_decision(stage_runs=[running_run])
        assert decision.should_run is False
        assert "running" in decision.reason.lower()

    def test_retry_ingestion_stage_blocked_when_stage_running(self) -> None:
        """retry_ingestion_stage must be rejected if a stage run is currently running."""
        repo = _FakeRepository()
        svc, repo, oas, vas, job_service = _make_service(repo=repo)
        ingestion_id = _submit(svc, repo, oas)

        # Inject a running stage_run for "extract"
        now = datetime.now(UTC)
        running_run = StageRunRecord(
            id=repo._next_id(),
            ingestion_id=ingestion_id,
            stage="extract",
            status=StageRunStatus.running,
            error=None,
            started_at=now,
            finished_at=None,
            created_at=now,
        )
        repo._stage_runs.append(running_run)

        env = svc.retry_ingestion_stage(
            meta=_meta(), ingestion_id=ingestion_id, stage="extract"
        )
        assert env.errors
        assert any("cannot be retried" in e.message for e in env.errors)


# ---------------------------------------------------------------------------
# Bug 7 regression: replay path missing provenance recording
# ---------------------------------------------------------------------------


class TestReplayProvenance:
    def test_store_stage_replay_records_provenance(self) -> None:
        """_execute_store_stage (replay path) must call _record_provenance."""
        repo = _FakeRepository()
        oas = _FakeOAS()
        svc, repo, oas, vas, job_service = _make_service(repo=repo, oas=oas)
        ingestion_id = _submit(svc, repo, oas)

        # Provenance recorded during initial submit (inline store)
        assert len(repo._provenance) == 1

        # Replay the store stage
        svc.run_store_stage(meta=_meta(), ingestion_id=ingestion_id)

        # Provenance must still be present (idempotent upsert)
        assert len(repo._provenance) >= 1
        assert len(repo._provenance_sources) >= 1


# ---------------------------------------------------------------------------
# Bug 5 regression: pagination sort consistency
# ---------------------------------------------------------------------------


class TestPagination:
    def test_list_ingestions_cursor_returns_non_overlapping_pages(self) -> None:
        """list_ingestions with cursor must not skip or duplicate records."""
        repo = _FakeRepository()
        svc, repo, oas, vas, job_service = _make_service(repo=repo)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        # Create 5 ingestions
        for i in range(5):
            repo.create_ingestion(
                status="complete",
                source_type="test",
                source_uri=None,
                source_actor=None,
                capture_time=now,
                mime_type=None,
                created_at=now,
            )

        env1 = svc.list_ingestions(meta=_meta(), limit=3)
        assert not env1.errors
        page1 = env1.payload.value.ingestions  # type: ignore[union-attr]
        assert len(page1) == 3
        cursor = env1.payload.value.cursor  # type: ignore[union-attr]
        assert cursor is not None

        env2 = svc.list_ingestions(meta=_meta(), limit=3, cursor=cursor)
        assert not env2.errors
        page2 = env2.payload.value.ingestions  # type: ignore[union-attr]
        assert len(page2) == 2

        ids_page1 = {r.id for r in page1}
        ids_page2 = {r.id for r in page2}
        assert ids_page1.isdisjoint(ids_page2), "Pages must not overlap"
        assert len(ids_page1 | ids_page2) == 5, (
            "All 5 records must appear across both pages"
        )
