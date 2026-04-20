"""Concrete Ingestion Service implementation."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from typing import Any

from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
)
from packages.brain_shared.errors import (
    ErrorDetail,
    codes,
    dependency_error,
    not_found_error,
    validation_error,
)
from packages.brain_shared.logging import get_logger, public_api_instrumented
from services.control.ingestion.component import SERVICE_COMPONENT_ID
from services.control.ingestion.config import IngestionServiceSettings
from services.control.ingestion.data.runtime import IngestionPostgresRuntime
from services.control.ingestion.domain import (
    STAGE_ORDER,
    STAGE_SET,
    AnchorStageResult,
    FanOutStageResult,
    HealthStatus,
    IndexAnchoredIngestionResult,
    IndexingRunStatus,
    IngestionListResult,
    IngestionRecord,
    IngestionResultsView,
    IngestionStatus,
    IngestionStatusResult,
    StageArtifactStatus,
    StageOutcomeSummary,
    StageRunStatus,
    StoreStageResult,
    stage_replay_decision,
)
from services.control.job.service import JobService
from services.control.ingestion.interfaces import (
    ExtractionMetadataSnapshot,
    ExtractorContext,
    ExtractorRegistry,
    IngestionRepository,
    NormalizerContext,
    NormalizerRegistry,
)
from services.control.ingestion.service import IngestionService

_LOGGER = get_logger(__name__)


class DefaultIngestionService(IngestionService):
    """Default Ingestion Service implementation with Postgres authority."""

    def __init__(
        self,
        *,
        settings: IngestionServiceSettings,
        repository: IngestionRepository,
        runtime: IngestionPostgresRuntime,
        oas: Any,
        vas: Any,
        job_service: JobService | Any,
        extractor_registry: ExtractorRegistry,
        normalizer_registry: NormalizerRegistry,
        utility_service: Any = None,
        language_model_service: Any = None,
        embedding_authority_service: Any = None,
    ) -> None:
        """Initialize the service with its dependencies."""
        self._settings = settings
        self._repository = repository
        self._runtime = runtime
        self._oas = oas
        self._vas = vas
        self._job_service = job_service
        self._utility_service = utility_service
        self._language_model_service = language_model_service
        self._embedding_authority_service = embedding_authority_service
        self._extractors = extractor_registry
        self._normalizers = normalizer_registry

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def submit_ingestion(
        self,
        *,
        meta: EnvelopeMeta,
        source_type: str,
        source_uri: str | None = None,
        source_actor: str | None = None,
        payload: bytes | None = None,
        existing_object_key: str | None = None,
        capture_time: str,
        mime_type: str | None = None,
    ) -> Envelope[IngestionRecord]:
        """Validate and persist one ingestion submission."""
        validate_meta(meta)
        now = _utc_now()

        # Parse and validate capture_time
        capture_dt, parse_error = _parse_capture_time(capture_time)
        if parse_error:
            record = self._repository.create_ingestion(
                status=IngestionStatus.rejected.value,
                source_type=(source_type.strip() if source_type else "unknown"),
                source_uri=source_uri,
                source_actor=source_actor,
                capture_time=now,
                mime_type=mime_type,
                created_at=now,
            )
            return failure(
                meta=meta,
                errors=[validation_error(parse_error, code=codes.INVALID_ARGUMENT)],
            )

        # Validate request shape
        errors = _validate_submission(
            source_type=source_type,
            payload=payload,
            existing_object_key=existing_object_key,
            capture_time=capture_dt,
            max_payload_bytes=self._settings.max_payload_bytes,
        )
        if errors:
            record = self._repository.create_ingestion(
                status=IngestionStatus.rejected.value,
                source_type=(source_type.strip() if source_type else "unknown"),
                source_uri=source_uri,
                source_actor=source_actor,
                capture_time=capture_dt or now,
                mime_type=mime_type,
                created_at=now,
            )
            return failure(meta=meta, errors=errors)

        assert capture_dt is not None
        record = self._repository.create_ingestion(
            status=IngestionStatus.queued.value,
            source_type=source_type.strip(),
            source_uri=source_uri,
            source_actor=source_actor,
            capture_time=capture_dt,
            mime_type=mime_type,
            created_at=now,
        )

        # Execute the store stage inline while payload/existing_object_key are in scope.
        # Subsequent stages run via job dispatch; only store requires the raw payload.
        store_env = self._run_store_stage_inline(
            meta=meta,
            record=record,
            payload=payload,
            existing_object_key=existing_object_key,
            now=now,
        )
        if store_env.errors:
            return failure(meta=meta, errors=store_env.errors)

        dispatch_env = self._enqueue_advance_job(
            meta=meta,
            ingestion_id=record.id,
            from_stage="extract",
            force_target=False,
        )
        if dispatch_env.errors:
            return failure(meta=meta, errors=dispatch_env.errors)

        updated = self._repository.get_ingestion(ingestion_id=record.id)
        return success(meta=meta, payload=updated or record)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def retry_ingestion_stage(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
        stage: str,
    ) -> Envelope[IngestionRecord]:
        """Retry one named stage for an existing ingestion."""
        validate_meta(meta)

        if stage not in STAGE_SET:
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        f"unknown stage '{stage}'; must be one of {list(STAGE_ORDER)}",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )

        record = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if record is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"ingestion '{ingestion_id}' not found")],
            )

        stage_runs = self._repository.list_stage_runs(
            ingestion_id=ingestion_id, stage=stage
        )
        decision = stage_replay_decision(stage_runs=stage_runs)
        if not decision.should_run:
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        f"stage '{stage}' cannot be retried: {decision.reason}",
                        code=codes.CONFLICT,
                    )
                ],
            )

        self._repository.update_ingestion_status(
            ingestion_id=ingestion_id,
            status=IngestionStatus.running.value,
            last_error=None,
            updated_at=_utc_now(),
        )
        dispatch_env = self._enqueue_advance_job(
            meta=meta,
            ingestion_id=ingestion_id,
            from_stage=stage,
            force_target=False,
        )
        if dispatch_env.errors:
            return failure(meta=meta, errors=dispatch_env.errors)

        updated = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if updated is None:
            return failure(
                meta=meta,
                errors=[
                    not_found_error(f"ingestion '{ingestion_id}' not found after retry")
                ],
            )
        return success(meta=meta, payload=updated)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def replay_ingestion(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
        from_stage: str,
    ) -> Envelope[IngestionRecord]:
        """Replay an ingestion from the named stage forward through the pipeline."""
        validate_meta(meta)

        if from_stage not in STAGE_SET:
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        f"unknown stage '{from_stage}'; must be one of {list(STAGE_ORDER)}",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )

        record = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if record is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"ingestion '{ingestion_id}' not found")],
            )

        self._repository.update_ingestion_status(
            ingestion_id=ingestion_id,
            status=IngestionStatus.running.value,
            last_error=None,
            updated_at=_utc_now(),
        )
        dispatch_env = self._enqueue_advance_job(
            meta=meta,
            ingestion_id=ingestion_id,
            from_stage=from_stage,
            force_target=True,
        )
        if dispatch_env.errors:
            return failure(meta=meta, errors=dispatch_env.errors)

        updated = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if updated is None:
            return failure(
                meta=meta,
                errors=[
                    not_found_error(
                        f"ingestion '{ingestion_id}' not found after replay"
                    )
                ],
            )
        return success(meta=meta, payload=updated)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def advance_ingestion(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
        from_stage: str,
        force_target: bool = False,
    ) -> Envelope[IngestionRecord]:
        """Advance one ingestion from the named stage onward."""
        validate_meta(meta)

        if from_stage not in STAGE_SET:
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        f"unknown stage '{from_stage}'; must be one of {list(STAGE_ORDER)}",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )

        record = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if record is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"ingestion '{ingestion_id}' not found")],
            )

        self._repository.update_ingestion_status(
            ingestion_id=ingestion_id,
            status=IngestionStatus.running.value,
            last_error=None,
            updated_at=_utc_now(),
        )

        start_index = list(STAGE_ORDER).index(from_stage)
        for index, stage in enumerate(STAGE_ORDER[start_index:]):
            stage_runs = self._repository.list_stage_runs(
                ingestion_id=ingestion_id, stage=stage
            )
            should_force_stage = force_target and index == 0
            decision = stage_replay_decision(stage_runs=stage_runs)
            if not should_force_stage and not decision.should_run:
                _LOGGER.info(
                    "advance skipping stage %s for ingestion %s: %s",
                    stage,
                    ingestion_id,
                    decision.reason,
                )
                continue

            run_result = self._dispatch_stage(
                meta=meta, ingestion_id=ingestion_id, stage=stage
            )
            if run_result.errors:
                return failure(meta=meta, errors=run_result.errors)

            if self._stage_result_failed(stage=stage, result=run_result.payload.value):
                updated = self._repository.get_ingestion(ingestion_id=ingestion_id)
                if updated is None:
                    return failure(
                        meta=meta,
                        errors=[
                            not_found_error(
                                f"ingestion '{ingestion_id}' not found after stage failure"
                            )
                        ],
                    )
                return success(meta=meta, payload=updated)

        updated = self._repository.update_ingestion_status(
            ingestion_id=ingestion_id,
            status=IngestionStatus.complete.value,
            last_error=None,
            updated_at=_utc_now(),
        )
        if updated is None:
            return failure(
                meta=meta,
                errors=[
                    not_found_error(
                        f"ingestion '{ingestion_id}' not found after advance"
                    )
                ],
            )
        return success(meta=meta, payload=updated)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def get_ingestion(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[IngestionRecord]:
        """Read one ingestion record by id."""
        validate_meta(meta)
        record = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if record is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"ingestion '{ingestion_id}' not found")],
            )
        return success(meta=meta, payload=record)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def get_ingestion_status(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[IngestionStatusResult]:
        """Return the current status snapshot for one ingestion."""
        validate_meta(meta)
        record = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if record is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"ingestion '{ingestion_id}' not found")],
            )
        return success(
            meta=meta,
            payload=IngestionStatusResult(
                ingestion_id=record.id,
                status=record.status,
                last_error=record.last_error,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def get_ingestion_results(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[IngestionResultsView]:
        """Return the stage-ordered artifact outcomes view for one ingestion."""
        validate_meta(meta)
        record = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if record is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"ingestion '{ingestion_id}' not found")],
            )

        all_outcomes = self._repository.list_stage_artifact_outcomes(
            ingestion_id=ingestion_id, stage=None, status=None
        )
        buckets: dict[str, list] = {stage: [] for stage in STAGE_ORDER}
        extras: dict[str, list] = {}
        for outcome in all_outcomes:
            if outcome.stage in buckets:
                buckets[outcome.stage].append(outcome)
            else:
                extras.setdefault(outcome.stage, []).append(outcome)

        stage_summaries = []
        for stage in STAGE_ORDER:
            stage_summaries.append(
                StageOutcomeSummary(
                    stage=stage,
                    outcomes=tuple(sorted(buckets[stage], key=lambda o: o.created_at)),
                )
            )
        for stage in sorted(extras):
            stage_summaries.append(
                StageOutcomeSummary(
                    stage=stage,
                    outcomes=tuple(sorted(extras[stage], key=lambda o: o.created_at)),
                )
            )

        return success(
            meta=meta,
            payload=IngestionResultsView(
                ingestion_id=record.id,
                stages=tuple(stage_summaries),
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def list_ingestions(
        self,
        *,
        meta: EnvelopeMeta,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Envelope[IngestionListResult]:
        """List ingestions with optional status filter and cursor pagination."""
        validate_meta(meta)
        limit = max(1, min(limit, 200))
        records = self._repository.list_ingestions(
            status=status, limit=limit, cursor=cursor
        )
        next_cursor = records[-1].id if len(records) == limit else None
        return success(
            meta=meta,
            payload=IngestionListResult(ingestions=records, cursor=next_cursor),
        )

    # ------------------------------------------------------------------
    # Internal orchestration
    # ------------------------------------------------------------------

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def run_store_stage(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[StoreStageResult]:
        """Execute the store stage — write raw artifact to OAS, record outcome."""
        validate_meta(meta)
        now = _utc_now()

        record = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if record is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"ingestion '{ingestion_id}' not found")],
            )

        self._repository.update_ingestion_status(
            ingestion_id=ingestion_id,
            status=IngestionStatus.running.value,
            last_error=None,
            updated_at=now,
        )

        stage_run = self._repository.create_stage_run(
            ingestion_id=ingestion_id,
            stage="store",
            status=StageRunStatus.running.value,
            started_at=now,
            created_at=now,
        )

        try:
            result = self._execute_store_stage(record=record, now=now, meta=meta)
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            _LOGGER.exception("store stage failed for ingestion %s", ingestion_id)
            self._repository.finish_stage_run(
                stage_run_id=stage_run.id,
                status=StageRunStatus.failed.value,
                error=error_text,
                finished_at=_utc_now(),
            )
            self._repository.update_ingestion_status(
                ingestion_id=ingestion_id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            from packages.brain_shared.errors import internal_error

            return failure(meta=meta, errors=[internal_error(error_text)])

        self._repository.finish_stage_run(
            stage_run_id=stage_run.id,
            status=StageRunStatus.success.value,
            error=None,
            finished_at=_utc_now(),
        )
        return success(meta=meta, payload=result)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def run_extract_stage(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[FanOutStageResult]:
        """Execute the extraction stage — fan raw artifacts into derived extracts."""
        validate_meta(meta)
        now = _utc_now()

        record = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if record is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"ingestion '{ingestion_id}' not found")],
            )

        stage_run = self._repository.create_stage_run(
            ingestion_id=ingestion_id,
            stage="extract",
            status=StageRunStatus.running.value,
            started_at=now,
            created_at=now,
        )

        try:
            result = self._execute_extract_stage(record=record, now=now, meta=meta)
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            _LOGGER.exception("extract stage failed for ingestion %s", ingestion_id)
            self._repository.finish_stage_run(
                stage_run_id=stage_run.id,
                status=StageRunStatus.failed.value,
                error=error_text,
                finished_at=_utc_now(),
            )
            self._repository.update_ingestion_status(
                ingestion_id=ingestion_id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            from packages.brain_shared.errors import internal_error

            return failure(meta=meta, errors=[internal_error(error_text)])

        finish_status = (
            StageRunStatus.failed.value
            if result.failed > 0
            else StageRunStatus.success.value
        )
        finish_error = (
            f"{result.failed} artifact(s) failed extraction"
            if result.failed > 0
            else None
        )
        self._repository.finish_stage_run(
            stage_run_id=stage_run.id,
            status=finish_status,
            error=finish_error,
            finished_at=_utc_now(),
        )
        return success(meta=meta, payload=result)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def run_normalize_stage(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[FanOutStageResult]:
        """Execute the normalization stage — fan extracts into canonical output."""
        validate_meta(meta)
        now = _utc_now()

        record = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if record is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"ingestion '{ingestion_id}' not found")],
            )

        stage_run = self._repository.create_stage_run(
            ingestion_id=ingestion_id,
            stage="normalize",
            status=StageRunStatus.running.value,
            started_at=now,
            created_at=now,
        )

        try:
            result = self._execute_normalize_stage(record=record, now=now, meta=meta)
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            _LOGGER.exception("normalize stage failed for ingestion %s", ingestion_id)
            self._repository.finish_stage_run(
                stage_run_id=stage_run.id,
                status=StageRunStatus.failed.value,
                error=error_text,
                finished_at=_utc_now(),
            )
            self._repository.update_ingestion_status(
                ingestion_id=ingestion_id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            from packages.brain_shared.errors import internal_error

            return failure(meta=meta, errors=[internal_error(error_text)])

        finish_status = (
            StageRunStatus.failed.value
            if result.failed > 0
            else StageRunStatus.success.value
        )
        finish_error = (
            f"{result.failed} artifact(s) failed normalization"
            if result.failed > 0
            else None
        )
        self._repository.finish_stage_run(
            stage_run_id=stage_run.id,
            status=finish_status,
            error=finish_error,
            finished_at=_utc_now(),
        )
        return success(meta=meta, payload=result)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def run_anchor_stage(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[AnchorStageResult]:
        """Execute the anchor stage — write anchor notes to vault via VAS."""
        validate_meta(meta)
        now = _utc_now()

        record = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if record is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"ingestion '{ingestion_id}' not found")],
            )

        stage_run = self._repository.create_stage_run(
            ingestion_id=ingestion_id,
            stage="anchor",
            status=StageRunStatus.running.value,
            started_at=now,
            created_at=now,
        )

        try:
            result = self._execute_anchor_stage(record=record, now=now, meta=meta)
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            _LOGGER.exception("anchor stage failed for ingestion %s", ingestion_id)
            self._repository.finish_stage_run(
                stage_run_id=stage_run.id,
                status=StageRunStatus.failed.value,
                error=error_text,
                finished_at=_utc_now(),
            )
            self._repository.update_ingestion_status(
                ingestion_id=ingestion_id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            from packages.brain_shared.errors import internal_error

            return failure(meta=meta, errors=[internal_error(error_text)])

        if result.failed > 0:
            finish_status = StageRunStatus.failed.value
            finish_error = f"{result.failed} artifact(s) failed anchoring"
        elif result.anchored == 0:
            finish_status = StageRunStatus.skipped.value
            finish_error = None
        else:
            finish_status = StageRunStatus.success.value
            finish_error = None
        self._repository.finish_stage_run(
            stage_run_id=stage_run.id,
            status=finish_status,
            error=finish_error,
            finished_at=_utc_now(),
        )
        if finish_status == StageRunStatus.success.value:
            dispatch_env = self._enqueue_indexing_job(
                meta=meta, ingestion_id=ingestion_id
            )
            if dispatch_env.errors:
                return failure(meta=meta, errors=dispatch_env.errors)

        return success(meta=meta, payload=result)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def index_anchored_ingestion(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
        indexing_run_id: str,
    ) -> Envelope[IndexAnchoredIngestionResult]:
        """Index anchored normalized artifacts through Utility, LMS, and EAS."""
        validate_meta(meta)
        if self._oas is None:
            return self._fail_indexing_dependency(
                meta=meta,
                indexing_run_id=indexing_run_id,
                message="Object Authority Service is not available",
            )
        if self._utility_service is None:
            return self._fail_indexing_dependency(
                meta=meta,
                indexing_run_id=indexing_run_id,
                message="Utility Service is not available",
            )
        if self._language_model_service is None:
            return self._fail_indexing_dependency(
                meta=meta,
                indexing_run_id=indexing_run_id,
                message="Language Model Service is not available",
            )
        if self._embedding_authority_service is None:
            return self._fail_indexing_dependency(
                meta=meta,
                indexing_run_id=indexing_run_id,
                message="Embedding Authority Service is not available",
            )

        record = self._repository.get_ingestion(ingestion_id=ingestion_id)
        if record is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"ingestion '{ingestion_id}' not found")],
            )
        indexing_run = self._repository.get_indexing_run(
            indexing_run_id=indexing_run_id
        )
        if indexing_run is None:
            return failure(
                meta=meta,
                errors=[not_found_error(f"indexing run '{indexing_run_id}' not found")],
            )

        now = _utc_now()
        self._repository.update_indexing_run_status(
            indexing_run_id=indexing_run_id,
            status=IndexingRunStatus.running.value,
            source_count=0,
            chunk_count=0,
            embedding_count=0,
            failed_count=0,
            error=None,
            updated_at=now,
            finished_at=None,
        )

        source_count = 0
        chunk_count = 0
        embedding_count = 0
        failed_count = 0
        errors: list[str] = []
        svc_meta = _service_meta(meta=meta)

        active_spec_env = self._embedding_authority_service.get_active_spec(
            meta=svc_meta
        )
        if (
            active_spec_env.errors
            or active_spec_env.payload is None
            or active_spec_env.payload.value is None
        ):
            error_text = (
                _join_errors(active_spec_env.errors) or "EAS active spec missing"
            )
            return self._finish_indexing_failure(
                meta=meta,
                indexing_run_id=indexing_run_id,
                ingestion_id=ingestion_id,
                source_count=0,
                chunk_count=0,
                embedding_count=0,
                failed_count=1,
                error=error_text,
            )
        spec = active_spec_env.payload.value

        anchors = self._repository.list_anchor_notes(ingestion_id=ingestion_id)
        for anchor in anchors:
            get_env = self._oas.get_object(
                meta=svc_meta, object_key=anchor.normalized_object_key
            )
            if (
                get_env.errors
                or get_env.payload is None
                or get_env.payload.value is None
            ):
                failed_count += 1
                errors.append(
                    f"object_key={anchor.normalized_object_key} error=OAS get_object failed"
                )
                continue

            try:
                text = get_env.payload.value.content.decode("utf-8")
            except UnicodeDecodeError:
                failed_count += 1
                errors.append(
                    f"object_key={anchor.normalized_object_key} error=normalized artifact is not UTF-8"
                )
                continue

            chunks_env = self._utility_service.chunk_text(meta=svc_meta, text=text)
            if (
                chunks_env.errors
                or chunks_env.payload is None
                or chunks_env.payload.value is None
            ):
                failed_count += 1
                errors.append(_join_errors(chunks_env.errors) or "chunk_text failed")
                continue

            source_env = self._embedding_authority_service.upsert_source(
                meta=svc_meta,
                canonical_reference=(
                    f"ingestion:{ingestion_id}:{anchor.normalized_object_key}"
                ),
                source_type="ingestion_anchor",
                service="ingestion",
                principal=meta.principal,
                metadata={
                    "ingestion_id": ingestion_id,
                    "normalized_object_key": anchor.normalized_object_key,
                    "vault_path": anchor.vault_path,
                },
            )
            if (
                source_env.errors
                or source_env.payload is None
                or source_env.payload.value is None
            ):
                failed_count += 1
                errors.append(_join_errors(source_env.errors) or "upsert_source failed")
                continue
            source_count += 1
            source = source_env.payload.value

            chunk_inputs = [
                {
                    "source_id": source.id,
                    "chunk_ordinal": chunk.chunk_ordinal,
                    "reference_range": chunk.reference_range,
                    "content_hash": _text_hash(chunk.text),
                    "text": chunk.text,
                    "metadata": {
                        "ingestion_id": ingestion_id,
                        "normalized_object_key": anchor.normalized_object_key,
                        "vault_path": anchor.vault_path,
                    },
                }
                for chunk in chunks_env.payload.value
            ]
            chunk_env = self._embedding_authority_service.upsert_chunks(
                meta=svc_meta, items=chunk_inputs
            )
            if (
                chunk_env.errors
                or chunk_env.payload is None
                or chunk_env.payload.value is None
            ):
                failed_count += 1
                errors.append(_join_errors(chunk_env.errors) or "upsert_chunks failed")
                continue
            chunks = chunk_env.payload.value
            chunk_count += len(chunks)

            if not chunks:
                continue

            embed_env = self._language_model_service.embed_batch(
                meta=svc_meta,
                texts=[chunk.text for chunk in chunks],
            )
            if (
                embed_env.errors
                or embed_env.payload is None
                or embed_env.payload.value is None
            ):
                failed_count += 1
                errors.append(_join_errors(embed_env.errors) or "embed_batch failed")
                continue
            vectors = embed_env.payload.value
            if len(vectors) != len(chunks):
                failed_count += 1
                errors.append("embed_batch returned a different count than chunks")
                continue
            vector_inputs = [
                {"chunk_id": chunk.id, "spec_id": spec.id, "vector": vector.values}
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            vector_env = self._embedding_authority_service.upsert_embedding_vectors(
                meta=svc_meta, items=vector_inputs
            )
            if (
                vector_env.errors
                or vector_env.payload is None
                or vector_env.payload.value is None
            ):
                failed_count += 1
                errors.append(
                    _join_errors(vector_env.errors) or "upsert_embedding_vectors failed"
                )
                continue
            embedding_count += len(vector_env.payload.value)

        finished_at = _utc_now()
        status = (
            IndexingRunStatus.failed.value
            if failed_count > 0
            else IndexingRunStatus.succeeded.value
        )
        error_text = "; ".join(errors) if errors else None
        self._repository.update_indexing_run_status(
            indexing_run_id=indexing_run_id,
            status=status,
            source_count=source_count,
            chunk_count=chunk_count,
            embedding_count=embedding_count,
            failed_count=failed_count,
            error=error_text,
            updated_at=finished_at,
            finished_at=finished_at,
        )

        if failed_count > 0:
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        error_text or "anchored ingestion indexing failed",
                        code=codes.DEPENDENCY_FAILURE,
                    )
                ],
                payload=IndexAnchoredIngestionResult(
                    ingestion_id=ingestion_id,
                    indexing_run_id=indexing_run_id,
                    source_count=source_count,
                    chunk_count=chunk_count,
                    embedding_count=embedding_count,
                    failed_count=failed_count,
                ),
            )

        return success(
            meta=meta,
            payload=IndexAnchoredIngestionResult(
                ingestion_id=ingestion_id,
                indexing_run_id=indexing_run_id,
                source_count=source_count,
                chunk_count=chunk_count,
                embedding_count=embedding_count,
                failed_count=failed_count,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[HealthStatus]:
        """Return Ingestion Service readiness status."""
        validate_meta(meta)
        try:
            ready = self._repository.is_healthy()
        except Exception:  # noqa: BLE001
            ready = False
        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=ready,
                detail="ok" if ready else "repository unreachable",
            ),
        )

    # ------------------------------------------------------------------
    # Private stage execution helpers
    # ------------------------------------------------------------------

    def _dispatch_stage(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
        stage: str,
    ) -> Envelope[Any]:
        """Route to the appropriate stage runner."""
        if stage == "store":
            return self.run_store_stage(meta=meta, ingestion_id=ingestion_id)
        if stage == "extract":
            return self.run_extract_stage(meta=meta, ingestion_id=ingestion_id)
        if stage == "normalize":
            return self.run_normalize_stage(meta=meta, ingestion_id=ingestion_id)
        if stage == "anchor":
            return self.run_anchor_stage(meta=meta, ingestion_id=ingestion_id)
        from packages.brain_shared.errors import internal_error

        return failure(meta=meta, errors=[internal_error(f"unknown stage: {stage}")])

    def _enqueue_advance_job(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
        from_stage: str,
        force_target: bool,
    ) -> Envelope[Any]:
        """Create and immediately run one job that advances the ingestion pipeline."""
        if self._job_service is None:
            error_text = "Job Service is not available"
            self._repository.update_ingestion_status(
                ingestion_id=ingestion_id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            from packages.brain_shared.errors import internal_error

            return failure(meta=meta, errors=[internal_error(error_text)])

        job_meta = meta.model_copy(
            update={
                "source": str(SERVICE_COMPONENT_ID),
                "principal": "service-ingestion",
            }
        )
        now = _utc_now()
        create_env = self._job_service.create_job(
            meta=job_meta,
            summary=f"Advance ingestion {ingestion_id} from {from_stage}",
            details=None,
            origin_reference=ingestion_id,
            schedule_type="one_time",
            timezone="UTC",
            definition={"run_at": now.isoformat()},
            job_action={
                "type": "capability_invocation",
                "capability_id": "ingestion-advance",
                "input_payload": {
                    "ingestion_id": ingestion_id,
                    "from_stage": from_stage,
                    "force_target": force_target,
                },
            },
            start_state="paused",
        )
        if (
            create_env.errors
            or create_env.payload is None
            or create_env.payload.value is None
        ):
            error_text = (
                "; ".join(error.message for error in create_env.errors)
                if create_env.errors
                else "job create returned no payload"
            )
            self._repository.update_ingestion_status(
                ingestion_id=ingestion_id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            from packages.brain_shared.errors import internal_error

            return failure(
                meta=meta,
                errors=create_env.errors or [internal_error(error_text)],
            )

        run_env = self._job_service.run_job_now(
            meta=job_meta,
            job_id=create_env.payload.value.job.id,
        )
        if run_env.errors:
            error_text = "; ".join(error.message for error in run_env.errors)
            self._repository.update_ingestion_status(
                ingestion_id=ingestion_id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            return failure(meta=meta, errors=run_env.errors)
        return success(meta=meta, payload=run_env.payload.value)

    def _enqueue_indexing_job(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[Any]:
        """Create and immediately run one job that indexes anchored artifacts."""
        if self._job_service is None:
            error_text = "Job Service is not available"
            self._repository.update_ingestion_status(
                ingestion_id=ingestion_id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            from packages.brain_shared.errors import internal_error

            return failure(meta=meta, errors=[internal_error(error_text)])

        now = _utc_now()
        indexing_run = self._repository.create_indexing_run(
            ingestion_id=ingestion_id,
            status=IndexingRunStatus.queued.value,
            created_at=now,
        )
        job_meta = meta.model_copy(
            update={
                "source": str(SERVICE_COMPONENT_ID),
                "principal": "service-ingestion",
            }
        )
        create_env = self._job_service.create_job(
            meta=job_meta,
            summary=f"Index anchored ingestion {ingestion_id}",
            details=None,
            origin_reference=f"ingestion:{ingestion_id}:index:{indexing_run.id}",
            schedule_type="one_time",
            timezone="UTC",
            definition={"run_at": now.isoformat()},
            job_action={
                "type": "capability_invocation",
                "capability_id": "ingestion-index-anchored",
                "input_payload": {
                    "ingestion_id": ingestion_id,
                    "indexing_run_id": indexing_run.id,
                },
            },
            start_state="paused",
        )
        if (
            create_env.errors
            or create_env.payload is None
            or create_env.payload.value is None
        ):
            error_text = (
                _join_errors(create_env.errors)
                if create_env.errors
                else "job create returned no payload"
            )
            self._repository.update_indexing_run_status(
                indexing_run_id=indexing_run.id,
                status=IndexingRunStatus.failed.value,
                source_count=0,
                chunk_count=0,
                embedding_count=0,
                failed_count=1,
                error=error_text,
                updated_at=_utc_now(),
                finished_at=_utc_now(),
            )
            self._repository.update_ingestion_status(
                ingestion_id=ingestion_id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            from packages.brain_shared.errors import internal_error

            return failure(
                meta=meta,
                errors=create_env.errors or [internal_error(error_text)],
            )

        job_id = create_env.payload.value.job.id
        self._repository.update_indexing_run_job(
            indexing_run_id=indexing_run.id,
            job_id=job_id,
            updated_at=_utc_now(),
        )
        run_env = self._job_service.run_job_now(meta=job_meta, job_id=job_id)
        if run_env.errors:
            error_text = _join_errors(run_env.errors)
            self._repository.update_indexing_run_status(
                indexing_run_id=indexing_run.id,
                status=IndexingRunStatus.failed.value,
                source_count=0,
                chunk_count=0,
                embedding_count=0,
                failed_count=1,
                error=error_text,
                updated_at=_utc_now(),
                finished_at=_utc_now(),
            )
            self._repository.update_ingestion_status(
                ingestion_id=ingestion_id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            return failure(meta=meta, errors=run_env.errors)
        return success(meta=meta, payload=run_env.payload.value)

    def _fail_indexing_dependency(
        self, *, meta: EnvelopeMeta, indexing_run_id: str, message: str
    ) -> Envelope[IndexAnchoredIngestionResult]:
        """Record dependency failure for one indexing run when possible."""
        run = self._repository.get_indexing_run(indexing_run_id=indexing_run_id)
        ingestion_id = run.ingestion_id if run is not None else ""
        if run is not None:
            self._repository.update_indexing_run_status(
                indexing_run_id=indexing_run_id,
                status=IndexingRunStatus.failed.value,
                source_count=0,
                chunk_count=0,
                embedding_count=0,
                failed_count=1,
                error=message,
                updated_at=_utc_now(),
                finished_at=_utc_now(),
            )
        return failure(
            meta=meta,
            errors=[
                dependency_error(
                    message,
                    code=codes.DEPENDENCY_UNAVAILABLE,
                    retryable=False,
                )
            ],
            payload=IndexAnchoredIngestionResult(
                ingestion_id=ingestion_id,
                indexing_run_id=indexing_run_id,
                source_count=0,
                chunk_count=0,
                embedding_count=0,
                failed_count=1,
            ),
        )

    def _finish_indexing_failure(
        self,
        *,
        meta: EnvelopeMeta,
        indexing_run_id: str,
        ingestion_id: str,
        source_count: int,
        chunk_count: int,
        embedding_count: int,
        failed_count: int,
        error: str,
    ) -> Envelope[IndexAnchoredIngestionResult]:
        """Persist terminal indexing failure and return a structured envelope."""
        self._repository.update_indexing_run_status(
            indexing_run_id=indexing_run_id,
            status=IndexingRunStatus.failed.value,
            source_count=source_count,
            chunk_count=chunk_count,
            embedding_count=embedding_count,
            failed_count=failed_count,
            error=error,
            updated_at=_utc_now(),
            finished_at=_utc_now(),
        )
        return failure(
            meta=meta,
            errors=[
                dependency_error(
                    error,
                    code=codes.DEPENDENCY_FAILURE,
                )
            ],
            payload=IndexAnchoredIngestionResult(
                ingestion_id=ingestion_id,
                indexing_run_id=indexing_run_id,
                source_count=source_count,
                chunk_count=chunk_count,
                embedding_count=embedding_count,
                failed_count=failed_count,
            ),
        )

    def _stage_result_failed(self, *, stage: str, result: Any) -> bool:
        """Return whether one successful stage call still produced a failing outcome."""
        if stage == "store":
            if result.status == StageArtifactStatus.failed:
                self._repository.update_ingestion_status(
                    ingestion_id=result.ingestion_id,
                    status=IngestionStatus.failed.value,
                    last_error=result.error,
                    updated_at=_utc_now(),
                )
                return True
            return False

        if result.failed > 0:
            if stage == "anchor":
                error_text = f"{result.failed} artifact(s) failed anchoring"
            elif stage == "normalize":
                error_text = f"{result.failed} artifact(s) failed normalization"
            else:
                error_text = f"{result.failed} artifact(s) failed extraction"
            self._repository.update_ingestion_status(
                ingestion_id=result.ingestion_id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            return True
        return False

    def _run_store_stage_inline(
        self,
        *,
        meta: EnvelopeMeta,
        record: IngestionRecord,
        payload: bytes | None,
        existing_object_key: str | None,
        now: datetime,
    ) -> Envelope[StoreStageResult]:
        """Create stage run bookkeeping and execute the inline store stage.

        Called from ``submit_ingestion`` while the raw payload is in scope.
        """
        from packages.brain_shared.errors import internal_error

        self._repository.update_ingestion_status(
            ingestion_id=record.id,
            status=IngestionStatus.running.value,
            last_error=None,
            updated_at=now,
        )

        stage_run = self._repository.create_stage_run(
            ingestion_id=record.id,
            stage="store",
            status=StageRunStatus.running.value,
            started_at=now,
            created_at=now,
        )

        try:
            result = self._execute_store_stage_inline(
                record=record,
                payload=payload,
                existing_object_key=existing_object_key,
                now=now,
                meta=meta,
            )
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            _LOGGER.exception("store stage failed for ingestion %s", record.id)
            self._repository.finish_stage_run(
                stage_run_id=stage_run.id,
                status=StageRunStatus.failed.value,
                error=error_text,
                finished_at=_utc_now(),
            )
            self._repository.update_ingestion_status(
                ingestion_id=record.id,
                status=IngestionStatus.failed.value,
                last_error=error_text,
                updated_at=_utc_now(),
            )
            return failure(meta=meta, errors=[internal_error(error_text)])

        if result.status == StageArtifactStatus.failed:
            self._repository.finish_stage_run(
                stage_run_id=stage_run.id,
                status=StageRunStatus.failed.value,
                error=result.error,
                finished_at=_utc_now(),
            )
            self._repository.update_ingestion_status(
                ingestion_id=record.id,
                status=IngestionStatus.failed.value,
                last_error=result.error,
                updated_at=_utc_now(),
            )
            from packages.brain_shared.errors import internal_error as _ie

            return failure(
                meta=meta, errors=[_ie(result.error or "store stage failed")]
            )

        self._repository.finish_stage_run(
            stage_run_id=stage_run.id,
            status=StageRunStatus.success.value,
            error=None,
            finished_at=_utc_now(),
        )
        return success(meta=meta, payload=result)

    def _execute_store_stage(
        self,
        *,
        record: IngestionRecord,
        now: datetime,
        meta: EnvelopeMeta,
    ) -> StoreStageResult:
        """Replay-path store stage: re-validate an existing raw artifact in OAS.

        Called from ``run_store_stage`` during replay/retry flows. The raw
        payload is not re-supplied; instead we locate the prior successful
        store outcome and stat the object in OAS to confirm it still exists.
        """
        if self._oas is None:
            raise RuntimeError("Object Authority Service is not available")

        from packages.brain_shared.envelope import new_meta, EnvelopeKind

        oas_meta = new_meta(
            kind=EnvelopeKind.COMMAND,
            source=str(SERVICE_COMPONENT_ID),
            principal=meta.principal,
            trace_id=meta.trace_id,
            parent_id=meta.envelope_id,
        )

        # Find a prior successful/skipped store outcome with a known object key.
        prior_outcomes = self._repository.list_stage_artifact_outcomes(
            ingestion_id=record.id,
            stage="store",
            status=None,
        )
        eligible = [
            o
            for o in prior_outcomes
            if o.status in (StageArtifactStatus.success, StageArtifactStatus.skipped)
            and o.object_key is not None
        ]
        if not eligible:
            raise RuntimeError(
                f"store stage replay for ingestion '{record.id}' has no prior successful "
                "outcome — submit a new ingestion to supply the raw payload"
            )

        if len(eligible) > 1:
            _LOGGER.warning(
                "store stage replay for ingestion %s has %d eligible prior outcomes; "
                "using most recent (object_key=%s)",
                record.id,
                len(eligible),
                eligible[-1].object_key,
            )
        object_key = eligible[-1].object_key
        assert object_key is not None

        stat_envelope = self._oas.stat_object(meta=oas_meta, object_key=object_key)
        if stat_envelope.errors:
            error_text = f"raw artifact no longer available in OAS: {object_key}"
            self._repository.create_stage_artifact_outcome(
                ingestion_id=record.id,
                stage="store",
                object_key=None,
                parent_object_key=None,
                status=StageArtifactStatus.failed.value,
                error=error_text,
                created_at=now,
            )
            return StoreStageResult(
                ingestion_id=record.id,
                object_key=None,
                status=StageArtifactStatus.failed,
                error=error_text,
            )

        # Object still present — record a success outcome for the replay run.
        self._repository.create_stage_artifact_outcome(
            ingestion_id=record.id,
            stage="store",
            object_key=object_key,
            parent_object_key=None,
            status=StageArtifactStatus.success.value,
            error=None,
            created_at=now,
        )
        self._record_provenance(
            object_key=object_key,
            record=record,
            source_type=record.source_type,
            now=now,
        )
        return StoreStageResult(
            ingestion_id=record.id,
            object_key=object_key,
            status=StageArtifactStatus.success,
            error=None,
        )

    def _execute_store_stage_inline(
        self,
        *,
        record: IngestionRecord,
        payload: bytes | None,
        existing_object_key: str | None,
        now: datetime,
        meta: EnvelopeMeta,
    ) -> StoreStageResult:
        """Inline store stage execution called directly from submit_ingestion.

        Writes raw artifact to OAS (or validates existing key), then records
        the stage outcome and provenance. Returns the outcome summary.
        """
        if self._oas is None:
            raise RuntimeError("Object Authority Service is not available")

        from packages.brain_shared.envelope import new_meta, EnvelopeKind

        oas_meta = new_meta(
            kind=EnvelopeKind.COMMAND,
            source=str(SERVICE_COMPONENT_ID),
            principal=meta.principal,
            trace_id=meta.trace_id,
            parent_id=meta.envelope_id,
        )

        if payload is not None:
            # Determine extension from mime_type or fall back to binary default
            ext = _ext_from_mime(record.mime_type) or "bin"
            ct = record.mime_type or "application/octet-stream"
            source_uri = record.source_uri or ""
            original_filename = _filename_for_ingestion(record.id, ext)

            # Check whether this content already exists in OAS (dedupe)
            put_envelope = self._oas.put_object(
                meta=oas_meta,
                content=payload,
                extension=ext,
                content_type=ct,
                original_filename=original_filename,
                source_uri=source_uri,
            )
            if (
                put_envelope.errors
                or put_envelope.payload is None
                or put_envelope.payload.value is None
            ):
                error_text = (
                    "; ".join(e.message for e in put_envelope.errors)
                    if put_envelope.errors
                    else "OAS put_object returned no payload"
                )
                self._repository.create_stage_artifact_outcome(
                    ingestion_id=record.id,
                    stage="store",
                    object_key=None,
                    parent_object_key=None,
                    status=StageArtifactStatus.failed.value,
                    error=error_text,
                    created_at=now,
                )
                return StoreStageResult(
                    ingestion_id=record.id,
                    object_key=None,
                    status=StageArtifactStatus.failed,
                    error=error_text,
                )

            put_result = put_envelope.payload.value
            object_key = put_result.object.ref.object_key
            outcome_status = (
                StageArtifactStatus.skipped
                if put_result.write_disposition == "existing"
                else StageArtifactStatus.success
            )
            outcome_error = (
                "raw artifact already exists"
                if outcome_status == StageArtifactStatus.skipped
                else None
            )
            self._repository.create_stage_artifact_outcome(
                ingestion_id=record.id,
                stage="store",
                object_key=object_key,
                parent_object_key=None,
                status=outcome_status.value,
                error=outcome_error,
                created_at=now,
            )
            self._record_provenance(
                object_key=object_key,
                record=record,
                source_type=record.source_type,
                now=now,
            )
            return StoreStageResult(
                ingestion_id=record.id,
                object_key=object_key,
                status=outcome_status,
                error=outcome_error,
            )

        # existing_object_key path
        assert existing_object_key is not None
        stat_envelope = self._oas.stat_object(
            meta=oas_meta, object_key=existing_object_key
        )
        if stat_envelope.errors:
            error_text = f"existing object not found: {existing_object_key}"
            self._repository.create_stage_artifact_outcome(
                ingestion_id=record.id,
                stage="store",
                object_key=None,
                parent_object_key=None,
                status=StageArtifactStatus.failed.value,
                error=error_text,
                created_at=now,
            )
            return StoreStageResult(
                ingestion_id=record.id,
                object_key=None,
                status=StageArtifactStatus.failed,
                error=error_text,
            )

        self._repository.create_stage_artifact_outcome(
            ingestion_id=record.id,
            stage="store",
            object_key=existing_object_key,
            parent_object_key=None,
            status=StageArtifactStatus.skipped.value,
            error="raw artifact already exists",
            created_at=now,
        )
        self._record_provenance(
            object_key=existing_object_key,
            record=record,
            source_type=record.source_type,
            now=now,
        )
        return StoreStageResult(
            ingestion_id=record.id,
            object_key=existing_object_key,
            status=StageArtifactStatus.skipped,
            error="raw artifact already exists",
        )

    def _execute_extract_stage(
        self,
        *,
        record: IngestionRecord,
        now: datetime,
        meta: EnvelopeMeta,
    ) -> FanOutStageResult:
        """Core extract-stage logic: fan raw store outcomes through extractor registry."""
        if self._oas is None:
            raise RuntimeError("Object Authority Service is not available")

        from packages.brain_shared.envelope import new_meta, EnvelopeKind

        oas_meta = new_meta(
            kind=EnvelopeKind.COMMAND,
            source=str(SERVICE_COMPONENT_ID),
            principal=meta.principal,
            trace_id=meta.trace_id,
            parent_id=meta.envelope_id,
        )

        # Load raw artifact keys from the store stage
        raw_outcomes = self._repository.list_stage_artifact_outcomes(
            ingestion_id=record.id,
            stage="store",
            status=None,
        )
        eligible = [
            o
            for o in raw_outcomes
            if o.status in (StageArtifactStatus.success, StageArtifactStatus.skipped)
            and o.object_key is not None
        ]

        succeeded = 0
        failed = 0
        errors: list[str] = []

        for raw_outcome in eligible:
            assert raw_outcome.object_key is not None
            get_envelope = self._oas.get_object(
                meta=oas_meta, object_key=raw_outcome.object_key
            )
            if (
                get_envelope.errors
                or get_envelope.payload is None
                or get_envelope.payload.value is None
            ):
                err = f"object_key={raw_outcome.object_key} error=OAS get_object failed"
                errors.append(err)
                failed += 1
                self._repository.create_stage_artifact_outcome(
                    ingestion_id=record.id,
                    stage="extract",
                    object_key=None,
                    parent_object_key=raw_outcome.object_key,
                    status=StageArtifactStatus.failed.value,
                    error=err,
                    created_at=now,
                )
                continue

            oas_result = get_envelope.payload.value
            raw_payload = oas_result.content
            mime_type = oas_result.object.metadata.content_type or None

            context = ExtractorContext(
                ingestion_id=record.id,
                raw_object_key=raw_outcome.object_key,
                payload=raw_payload,
                mime_type=mime_type,
                source_type=record.source_type,
                source_uri=record.source_uri,
                source_actor=record.source_actor,
            )

            extractors = self._extractors.match(context)
            if not extractors:
                err = (
                    f"object_key={raw_outcome.object_key} error=no extractor available"
                )
                errors.append(err)
                failed += 1
                self._repository.create_stage_artifact_outcome(
                    ingestion_id=record.id,
                    stage="extract",
                    object_key=None,
                    parent_object_key=raw_outcome.object_key,
                    status=StageArtifactStatus.failed.value,
                    error=err,
                    created_at=now,
                )
                continue

            for extractor in extractors:
                try:
                    extracted_list = extractor.extract(context)
                except Exception as exc:  # noqa: BLE001
                    err = f"object_key={raw_outcome.object_key} extractor={extractor.__class__.__name__} error={exc}"
                    errors.append(err)
                    failed += 1
                    self._repository.create_stage_artifact_outcome(
                        ingestion_id=record.id,
                        stage="extract",
                        object_key=None,
                        parent_object_key=raw_outcome.object_key,
                        status=StageArtifactStatus.failed.value,
                        error=err,
                        created_at=now,
                    )
                    continue

                for artifact in extracted_list:
                    ext_mime = artifact.mime_type or "application/octet-stream"
                    ext_ext = _ext_from_mime(artifact.mime_type) or "bin"
                    put_env = self._oas.put_object(
                        meta=oas_meta,
                        content=artifact.payload,
                        extension=ext_ext,
                        content_type=ext_mime,
                        original_filename=_filename_for_ingestion(record.id, ext_ext),
                        source_uri=record.source_uri or "",
                    )
                    if (
                        put_env.errors
                        or put_env.payload is None
                        or put_env.payload.value is None
                    ):
                        err = f"object_key={raw_outcome.object_key} error=OAS put_object failed for extracted artifact"
                        errors.append(err)
                        failed += 1
                        self._repository.create_stage_artifact_outcome(
                            ingestion_id=record.id,
                            stage="extract",
                            object_key=None,
                            parent_object_key=raw_outcome.object_key,
                            status=StageArtifactStatus.failed.value,
                            error=err,
                            created_at=now,
                        )
                        continue

                    extracted_key = put_env.payload.value.object.ref.object_key
                    self._repository.upsert_extraction_metadata(
                        object_key=extracted_key,
                        method=artifact.method,
                        confidence=artifact.confidence,
                        page_count=artifact.page_count,
                        created_at=now,
                    )
                    self._repository.create_stage_artifact_outcome(
                        ingestion_id=record.id,
                        stage="extract",
                        object_key=extracted_key,
                        parent_object_key=raw_outcome.object_key,
                        status=StageArtifactStatus.success.value,
                        error=None,
                        created_at=now,
                    )
                    self._record_provenance(
                        object_key=extracted_key,
                        record=record,
                        source_type=f"extractor:{artifact.method}",
                        now=now,
                    )
                    succeeded += 1

        return FanOutStageResult(
            ingestion_id=record.id,
            succeeded=succeeded,
            failed=failed,
            errors=tuple(errors),
        )

    def _execute_normalize_stage(
        self,
        *,
        record: IngestionRecord,
        now: datetime,
        meta: EnvelopeMeta,
    ) -> FanOutStageResult:
        """Core normalize-stage logic: fan extracted artifacts through normalizer registry."""
        if self._oas is None:
            raise RuntimeError("Object Authority Service is not available")

        from packages.brain_shared.envelope import new_meta, EnvelopeKind

        oas_meta = new_meta(
            kind=EnvelopeKind.COMMAND,
            source=str(SERVICE_COMPONENT_ID),
            principal=meta.principal,
            trace_id=meta.trace_id,
            parent_id=meta.envelope_id,
        )

        extracted_outcomes = self._repository.list_stage_artifact_outcomes(
            ingestion_id=record.id,
            stage="extract",
            status=None,
        )
        eligible = [
            o
            for o in extracted_outcomes
            if o.status in (StageArtifactStatus.success, StageArtifactStatus.skipped)
            and o.object_key is not None
        ]

        succeeded = 0
        failed = 0
        errors: list[str] = []

        for extracted_outcome in eligible:
            assert extracted_outcome.object_key is not None
            get_envelope = self._oas.get_object(
                meta=oas_meta, object_key=extracted_outcome.object_key
            )
            if (
                get_envelope.errors
                or get_envelope.payload is None
                or get_envelope.payload.value is None
            ):
                err = f"object_key={extracted_outcome.object_key} error=OAS get_object failed"
                errors.append(err)
                failed += 1
                self._repository.create_stage_artifact_outcome(
                    ingestion_id=record.id,
                    stage="normalize",
                    object_key=None,
                    parent_object_key=extracted_outcome.object_key,
                    status=StageArtifactStatus.failed.value,
                    error=err,
                    created_at=now,
                )
                continue

            oas_result = get_envelope.payload.value
            ext_payload = oas_result.content
            mime_type = oas_result.object.metadata.content_type or None

            extraction_meta_record = self._repository.get_extraction_metadata(
                object_key=extracted_outcome.object_key
            )
            extraction_snapshot: ExtractionMetadataSnapshot | None = None
            if extraction_meta_record is not None:
                extraction_snapshot = ExtractionMetadataSnapshot(
                    method=extraction_meta_record.method,
                    confidence=extraction_meta_record.confidence,
                    page_count=extraction_meta_record.page_count,
                )

            context = NormalizerContext(
                ingestion_id=record.id,
                extracted_object_key=extracted_outcome.object_key,
                payload=ext_payload,
                mime_type=mime_type,
                source_type=record.source_type,
                source_uri=record.source_uri,
                source_actor=record.source_actor,
                extraction_metadata=extraction_snapshot,
            )

            normalizers = self._normalizers.match(context)
            if not normalizers:
                err = f"object_key={extracted_outcome.object_key} error=no normalizer available"
                errors.append(err)
                failed += 1
                self._repository.create_stage_artifact_outcome(
                    ingestion_id=record.id,
                    stage="normalize",
                    object_key=None,
                    parent_object_key=extracted_outcome.object_key,
                    status=StageArtifactStatus.failed.value,
                    error=err,
                    created_at=now,
                )
                continue

            for normalizer in normalizers:
                try:
                    normalized_list = normalizer.normalize(context)
                except Exception as exc:  # noqa: BLE001
                    err = f"object_key={extracted_outcome.object_key} normalizer={normalizer.__class__.__name__} error={exc}"
                    errors.append(err)
                    failed += 1
                    self._repository.create_stage_artifact_outcome(
                        ingestion_id=record.id,
                        stage="normalize",
                        object_key=None,
                        parent_object_key=extracted_outcome.object_key,
                        status=StageArtifactStatus.failed.value,
                        error=err,
                        created_at=now,
                    )
                    continue

                for artifact in normalized_list:
                    norm_mime = artifact.mime_type or "text/plain"
                    norm_ext = _ext_from_mime(artifact.mime_type) or "md"
                    put_env = self._oas.put_object(
                        meta=oas_meta,
                        content=artifact.payload,
                        extension=norm_ext,
                        content_type=norm_mime,
                        original_filename=_filename_for_ingestion(record.id, norm_ext),
                        source_uri=record.source_uri or "",
                    )
                    if (
                        put_env.errors
                        or put_env.payload is None
                        or put_env.payload.value is None
                    ):
                        err = f"object_key={extracted_outcome.object_key} error=OAS put_object failed for normalized artifact"
                        errors.append(err)
                        failed += 1
                        self._repository.create_stage_artifact_outcome(
                            ingestion_id=record.id,
                            stage="normalize",
                            object_key=None,
                            parent_object_key=extracted_outcome.object_key,
                            status=StageArtifactStatus.failed.value,
                            error=err,
                            created_at=now,
                        )
                        continue

                    norm_key = put_env.payload.value.object.ref.object_key
                    self._repository.upsert_normalization_metadata(
                        object_key=norm_key,
                        method=artifact.method,
                        confidence=artifact.confidence,
                        created_at=now,
                    )
                    self._repository.create_stage_artifact_outcome(
                        ingestion_id=record.id,
                        stage="normalize",
                        object_key=norm_key,
                        parent_object_key=extracted_outcome.object_key,
                        status=StageArtifactStatus.success.value,
                        error=None,
                        created_at=now,
                    )
                    self._record_provenance(
                        object_key=norm_key,
                        record=record,
                        source_type=f"normalizer:{artifact.method}",
                        now=now,
                    )
                    succeeded += 1

        return FanOutStageResult(
            ingestion_id=record.id,
            succeeded=succeeded,
            failed=failed,
            errors=tuple(errors),
        )

    def _execute_anchor_stage(
        self,
        *,
        record: IngestionRecord,
        now: datetime,
        meta: EnvelopeMeta,
    ) -> AnchorStageResult:
        """Core anchor-stage logic: write vault anchor notes via VAS public API."""
        if self._vas is None:
            raise RuntimeError("Vault Authority Service is not available")
        if self._oas is None:
            raise RuntimeError("Object Authority Service is not available")

        from packages.brain_shared.envelope import new_meta, EnvelopeKind

        svc_meta = new_meta(
            kind=EnvelopeKind.COMMAND,
            source=str(SERVICE_COMPONENT_ID),
            principal=meta.principal,
            trace_id=meta.trace_id,
            parent_id=meta.envelope_id,
        )

        normalized_outcomes = self._repository.list_stage_artifact_outcomes(
            ingestion_id=record.id,
            stage="normalize",
            status=None,
        )
        eligible = [
            o
            for o in normalized_outcomes
            if o.status in (StageArtifactStatus.success, StageArtifactStatus.skipped)
            and o.object_key is not None
            and self._repository.get_anchor_by_normalized_key(
                normalized_object_key=o.object_key
            )
            is None
        ]

        if not eligible:
            return AnchorStageResult(
                ingestion_id=record.id,
                anchored=0,
                failed=0,
                errors=(),
            )

        note_path = self._anchor_note_path(record.id)
        note_created = False
        anchored = 0
        failed = 0
        errors: list[str] = []

        for index, outcome in enumerate(eligible, start=1):
            assert outcome.object_key is not None
            get_env = self._oas.get_object(meta=svc_meta, object_key=outcome.object_key)
            if (
                get_env.errors
                or get_env.payload is None
                or get_env.payload.value is None
            ):
                err = f"object_key={outcome.object_key} error=OAS get_object failed"
                errors.append(err)
                failed += 1
                self._repository.create_stage_artifact_outcome(
                    ingestion_id=record.id,
                    stage="anchor",
                    object_key=None,
                    parent_object_key=outcome.object_key,
                    status=StageArtifactStatus.failed.value,
                    error=err,
                    created_at=now,
                )
                continue

            oas_result = get_env.payload.value
            norm_payload = oas_result.content
            mime_type = oas_result.object.metadata.content_type or None

            norm_meta = self._repository.get_normalization_metadata(
                object_key=outcome.object_key
            )

            try:
                section = self._build_anchor_section(
                    object_key=outcome.object_key,
                    payload=norm_payload,
                    mime_type=mime_type,
                    normalization_method=norm_meta.method if norm_meta else None,
                    normalization_confidence=norm_meta.confidence
                    if norm_meta
                    else None,
                    ingestion=record,
                    sequence=index,
                    now=now,
                )

                # Write DB anchor record first so any subsequent retry sees this
                # artifact as already claimed and skips it.  If the vault write
                # below fails we delete this record so the retry can try again.
                self._repository.upsert_anchor_note(
                    ingestion_id=record.id,
                    normalized_object_key=outcome.object_key,
                    vault_path=note_path,
                    created_at=now,
                )

                vault_write_ok = False
                if not note_created:
                    intro = self._build_anchor_intro(record=record, now=now)
                    create_env = self._vas.create_file(
                        meta=svc_meta,
                        file_path=note_path,
                        content=f"{intro}{section}",
                    )
                    if create_env.errors:
                        # Note may already exist — try append instead
                        append_env = self._vas.append_file(
                            meta=svc_meta,
                            file_path=note_path,
                            content=f"\n\n---\n\n{section}",
                        )
                        if append_env.errors:
                            self._repository.delete_anchor_note(
                                normalized_object_key=outcome.object_key
                            )
                            err = f"object_key={outcome.object_key} error=VAS create/append file failed"
                            errors.append(err)
                            failed += 1
                            self._repository.create_stage_artifact_outcome(
                                ingestion_id=record.id,
                                stage="anchor",
                                object_key=None,
                                parent_object_key=outcome.object_key,
                                status=StageArtifactStatus.failed.value,
                                error=err,
                                created_at=now,
                            )
                            continue
                    note_created = True
                    vault_write_ok = True
                else:
                    append_env = self._vas.append_file(
                        meta=svc_meta,
                        file_path=note_path,
                        content=f"\n\n---\n\n{section}",
                    )
                    if append_env.errors:
                        self._repository.delete_anchor_note(
                            normalized_object_key=outcome.object_key
                        )
                        err = f"object_key={outcome.object_key} error=VAS append_file failed"
                        errors.append(err)
                        failed += 1
                        self._repository.create_stage_artifact_outcome(
                            ingestion_id=record.id,
                            stage="anchor",
                            object_key=None,
                            parent_object_key=outcome.object_key,
                            status=StageArtifactStatus.failed.value,
                            error=err,
                            created_at=now,
                        )
                        continue
                    vault_write_ok = True

                if vault_write_ok:
                    self._repository.create_stage_artifact_outcome(
                        ingestion_id=record.id,
                        stage="anchor",
                        object_key=outcome.object_key,
                        parent_object_key=outcome.object_key,
                        status=StageArtifactStatus.success.value,
                        error=None,
                        created_at=now,
                    )
                    anchored += 1

            except Exception as exc:  # noqa: BLE001
                err = f"object_key={outcome.object_key} error={exc}"
                _LOGGER.exception(
                    "anchor stage error for artifact %s", outcome.object_key
                )
                errors.append(err)
                failed += 1
                self._repository.create_stage_artifact_outcome(
                    ingestion_id=record.id,
                    stage="anchor",
                    object_key=None,
                    parent_object_key=outcome.object_key,
                    status=StageArtifactStatus.failed.value,
                    error=err,
                    created_at=now,
                )

        return AnchorStageResult(
            ingestion_id=record.id,
            anchored=anchored,
            failed=failed,
            errors=tuple(errors),
        )

    def _record_provenance(
        self,
        *,
        object_key: str,
        record: IngestionRecord,
        source_type: str,
        now: datetime,
    ) -> None:
        """Create or update provenance for the named object key."""
        prov = self._repository.get_or_create_provenance(
            object_key=object_key, created_at=now
        )
        self._repository.upsert_provenance_source(
            provenance_id=prov.id,
            ingestion_id=record.id,
            source_type=source_type,
            source_uri=record.source_uri,
            source_actor=record.source_actor,
            captured_at=record.capture_time,
        )

    def _anchor_note_path(self, ingestion_id: str) -> str:
        """Return the deterministic vault-relative path for an anchor note."""
        folder = self._settings.anchor_folder.strip("/")
        return f"{folder}/ingestion-{ingestion_id}.md"

    def _build_anchor_intro(self, *, record: IngestionRecord, now: datetime) -> str:
        """Render the anchor note introduction block."""
        created = record.created_at.astimezone(UTC).isoformat()
        rendered_now = now.astimezone(UTC).isoformat()
        return (
            f"# Anchor Note: {record.id}\n"
            f"**Source Type:** {record.source_type}\n"
            f"**Source URI:** {self._escape_md_inline(record.source_uri or 'unknown')}\n"
            f"**Source Actor:** {self._escape_md_inline(record.source_actor or 'unknown')}\n"
            f"**Ingestion Created:** {created}\n"
            f"**Anchor Run:** {rendered_now}\n\n---\n\n"
        )

    def _build_anchor_section(
        self,
        *,
        object_key: str,
        payload: bytes,
        mime_type: str | None,
        normalization_method: str | None,
        normalization_confidence: float | None,
        ingestion: IngestionRecord,
        sequence: int,
        now: datetime,
    ) -> str:
        """Render the Markdown section for one normalized artifact anchor."""
        lines = [
            f"## Artifact {sequence}",
            f"**Normalized Object Key:** {object_key}",
            f"**MIME Type:** {mime_type or 'unknown'}",
            f"**Normalization Method:** {normalization_method or 'unknown'}",
            f"**Normalization Confidence:** {self._format_confidence(normalization_confidence)}",
            f"**Source Type:** {ingestion.source_type}",
            f"**Source URI:** {self._escape_md_inline(ingestion.source_uri or 'unknown')}",
            f"**Source Actor:** {self._escape_md_inline(ingestion.source_actor or 'unknown')}",
        ]
        text_body = self._render_text_body(payload, mime_type)
        if text_body:
            lines += ["", "**Normalized Content:**", "", text_body]
        else:
            lines += [
                "",
                f"Normalized artifact content not rendered inline. "
                f"Refer to object key: {object_key}",
            ]
        return "\n".join(lines)

    def _render_text_body(self, payload: bytes, mime_type: str | None) -> str | None:
        """Decode payload to UTF-8 text for inline rendering when appropriate."""
        lower = (mime_type or "").lower()
        if mime_type and (
            lower.startswith("image/")
            or lower in {"application/pdf", "application/octet-stream"}
        ):
            return None
        if lower and not (
            lower.startswith("text/") or "json" in lower or "xml" in lower
        ):
            return None
        try:
            decoded = payload.decode("utf-8")
        except UnicodeDecodeError:
            decoded = payload.decode("utf-8", errors="replace")
        return decoded.strip() or None

    @staticmethod
    def _escape_md_inline(value: str) -> str:
        """Escape characters that break Markdown link/table syntax for inline embedding."""
        for ch in ("\\", "[", "]", "(", ")"):
            value = value.replace(ch, f"\\{ch}")
        return value.replace("\n", " ").replace("\r", " ")

    @staticmethod
    def _format_confidence(value: float | None) -> str:
        """Format confidence to two decimal places, or 'unknown' if absent."""
        return "unknown" if value is None else f"{value:.2f}"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


def _parse_capture_time(raw: str) -> tuple[datetime | None, str | None]:
    """Parse an ISO 8601 capture_time string into a timezone-aware datetime.

    Returns ``(datetime, None)`` on success or ``(None, error_message)`` on failure.
    """
    if not raw or not raw.strip():
        return None, "capture_time is required"
    text = raw.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None, f"capture_time is not a valid ISO 8601 datetime: {raw!r}"
    if parsed.tzinfo is None:
        return None, "capture_time must be timezone-aware (include UTC offset or Z)"
    return parsed.astimezone(UTC), None


def _validate_submission(
    *,
    source_type: str,
    payload: bytes | None,
    existing_object_key: str | None,
    capture_time: datetime | None,
    max_payload_bytes: int,
) -> list[ErrorDetail]:
    """Return structured validation errors for a submission request."""
    errors: list[ErrorDetail] = []
    if not source_type or not source_type.strip():
        errors.append(
            validation_error("source_type is required", code=codes.INVALID_ARGUMENT)
        )
    has_payload = payload is not None
    has_existing = existing_object_key is not None
    if has_payload == has_existing:
        errors.append(
            validation_error(
                "exactly one of payload or existing_object_key must be supplied",
                code=codes.INVALID_ARGUMENT,
            )
        )
    if has_payload and payload is not None and len(payload) > max_payload_bytes:
        errors.append(
            validation_error(
                f"payload exceeds maximum size of {max_payload_bytes} bytes",
                code=codes.INVALID_ARGUMENT,
            )
        )
    if capture_time is not None and capture_time.tzinfo is None:
        errors.append(
            validation_error(
                "capture_time must be timezone-aware",
                code=codes.INVALID_ARGUMENT,
            )
        )
    return errors


def _ext_from_mime(mime_type: str | None) -> str | None:
    """Derive a file extension string from a MIME type string."""
    if not mime_type:
        return None
    parts = mime_type.split("/")
    if len(parts) != 2:
        return None
    subtype = parts[1].split("+")[0].lower()
    _MIME_EXT_OVERRIDES = {
        "markdown": "md",
        "plain": "txt",
        "jpeg": "jpg",
        "svg+xml": "svg",
        "javascript": "js",
    }
    return _MIME_EXT_OVERRIDES.get(subtype, subtype)


def _filename_for_ingestion(ingestion_id: str, ext: str) -> str:
    """Build a stable original_filename for OAS from ingestion context."""
    return f"ingestion-{ingestion_id}.{ext}"


def _service_meta(*, meta: EnvelopeMeta) -> EnvelopeMeta:
    """Build service-origin metadata for internal public API calls."""
    from packages.brain_shared.envelope import EnvelopeKind, new_meta

    return new_meta(
        kind=EnvelopeKind.COMMAND,
        source=str(SERVICE_COMPONENT_ID),
        principal=meta.principal,
        trace_id=meta.trace_id,
        parent_id=meta.envelope_id,
    )


def _join_errors(errors: list[ErrorDetail]) -> str:
    """Render envelope errors as one stable message."""
    return "; ".join(error.message for error in errors)


def _text_hash(text: str) -> str:
    """Return a deterministic SHA-256 hash for text chunk content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
