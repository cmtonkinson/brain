"""Ingestion Service abstract base class defining the public API."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from services.reason.ingestion.domain import (
    AnchorStageResult,
    FanOutStageResult,
    HealthStatus,
    IndexAnchoredIngestionResult,
    IngestionListResult,
    IngestionRecord,
    IngestionResultsView,
    IngestionStatusResult,
    StoreStageResult,
)


class IngestionService(ABC):
    """Public API for content ingestion, stage orchestration, and artifact lineage."""

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @abstractmethod
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
        """Validate and persist one ingestion submission.

        Exactly one of ``payload`` or ``existing_object_key`` must be supplied.
        ``capture_time`` must be an ISO 8601 string with timezone information.
        A failed validation attempt is persisted as a rejected ingestion record
        before raising the structured error.
        """

    @abstractmethod
    def retry_ingestion_stage(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
        stage: str,
    ) -> Envelope[IngestionRecord]:
        """Retry one named stage for an existing ingestion.

        The stage runs only if its most recent run did not succeed.
        Preserves prior stage run history.
        """

    @abstractmethod
    def replay_ingestion(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
        from_stage: str,
    ) -> Envelope[IngestionRecord]:
        """Replay an ingestion from the named stage forward through the pipeline.

        Stages that already succeeded are skipped unless the replay request
        explicitly targets them. Prior run history is preserved.
        """

    @abstractmethod
    def advance_ingestion(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
        from_stage: str,
        force_target: bool = False,
    ) -> Envelope[IngestionRecord]:
        """Advance one ingestion through the pipeline from the named stage onward.

        Internal orchestration entrypoint used by Job Service op dispatch.
        ``force_target`` bypasses replay-skip logic for only the first stage.
        """

    @abstractmethod
    def index_anchored_ingestion(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
        indexing_run_id: str,
    ) -> Envelope[IndexAnchoredIngestionResult]:
        """Index anchored normalized artifacts through Utility, Language, and Embedding."""

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @abstractmethod
    def get_ingestion(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[IngestionRecord]:
        """Read one ingestion record by id."""

    @abstractmethod
    def get_ingestion_status(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[IngestionStatusResult]:
        """Return the current status snapshot for one ingestion."""

    @abstractmethod
    def get_ingestion_results(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[IngestionResultsView]:
        """Return the stage-ordered artifact outcomes view for one ingestion."""

    @abstractmethod
    def list_ingestions(
        self,
        *,
        meta: EnvelopeMeta,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Envelope[IngestionListResult]:
        """List ingestions with optional status filter and cursor pagination."""

    # ------------------------------------------------------------------
    # Internal orchestration (public API, not HTTP-published)
    # ------------------------------------------------------------------

    @abstractmethod
    def run_store_stage(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[StoreStageResult]:
        """Execute the store stage for the named ingestion.

        Writes the raw artifact to Object and records the outcome. If identical
        content already exists in Object the stage outcome is recorded as skipped.
        """

    @abstractmethod
    def run_extract_stage(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[FanOutStageResult]:
        """Execute the extraction stage for the named ingestion.

        Fans raw artifacts from the store stage into extracted derivatives
        via the extractor registry. Partial failures are recorded without
        aborting the remaining fan-out.
        """

    @abstractmethod
    def run_normalize_stage(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[FanOutStageResult]:
        """Execute the normalization stage for the named ingestion.

        Fans extracted artifacts into canonical Markdown/plain-text derivatives
        via the normalizer registry. Partial failures are recorded without
        aborting the remaining fan-out.
        """

    @abstractmethod
    def run_anchor_stage(
        self,
        *,
        meta: EnvelopeMeta,
        ingestion_id: str,
    ) -> Envelope[AnchorStageResult]:
        """Execute the anchor stage for the named ingestion.

        Creates or appends an anchor note in the vault via Vault public API for
        each unanchored normalized artifact. Attachment materialization is
        governed by the configured visual MIME allowlist.
        """

    @abstractmethod
    def health(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[HealthStatus]:
        """Return Ingestion Service readiness status."""


def build_ingestion_service(
    *,
    settings: CoreRuntimeSettings,
    components: Mapping[str, object],
) -> IngestionService:
    """Build concrete Ingestion Service from typed settings and peer service map."""
    from services.reason.ingestion.config import resolve_ingestion_service_settings
    from services.reason.ingestion.data import (
        IngestionPostgresRuntime,
        PostgresIngestionRepository,
    )
    from services.reason.ingestion.implementation import DefaultIngestionService
    from services.reason.ingestion.interfaces import (
        BuiltInTextExtractor,
        BuiltInTextNormalizer,
        ExtractorRegistry,
        NormalizerRegistry,
    )

    service_settings = resolve_ingestion_service_settings(settings)
    runtime = IngestionPostgresRuntime.from_settings(settings)
    repository = PostgresIngestionRepository(sessions=runtime.schema_sessions)

    object_service = components.get("service_object")
    vault_service = components.get("service_vault")
    job_service = components.get("service_job")
    utility_service = components.get("service_utility")
    language_service = components.get("service_language")
    embedding_service = components.get("service_embedding")

    return DefaultIngestionService(
        settings=service_settings,
        repository=repository,
        runtime=runtime,
        object_service=object_service,
        vault_service=vault_service,
        job_service=job_service,
        utility_service=utility_service,
        language_service=language_service,
        embedding_service=embedding_service,
        extractor_registry=ExtractorRegistry([BuiltInTextExtractor()]),
        normalizer_registry=NormalizerRegistry([BuiltInTextNormalizer()]),
    )
