"""Internal protocols and plugin interfaces for the Ingestion Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Protocol, Sequence

from services.reason.ingestion.domain import (
    AnchorRecord,
    ExtractionMetadataRecord,
    IngestionIndexingRun,
    IngestionRecord,
    NormalizationMetadataRecord,
    ProvenanceRecord,
    ProvenanceSourceRecord,
    StageArtifactOutcome,
    StageRunRecord,
)


# ---------------------------------------------------------------------------
# Repository protocol
# ---------------------------------------------------------------------------


class IngestionRepository(Protocol):
    """Transport-neutral protocol for Ingestion Service persistence."""

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
        """Persist one ingestion attempt record."""
        ...

    def get_ingestion(self, *, ingestion_id: str) -> IngestionRecord | None:
        """Read one ingestion by id."""
        ...

    def list_ingestions(
        self,
        *,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> list[IngestionRecord]:
        """List ingestions with optional status filter and cursor pagination."""
        ...

    def update_ingestion_status(
        self,
        *,
        ingestion_id: str,
        status: str,
        last_error: str | None,
        updated_at: datetime,
    ) -> IngestionRecord | None:
        """Update the overall status of one ingestion."""
        ...

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
        """Persist the start of one stage run."""
        ...

    def finish_stage_run(
        self,
        *,
        stage_run_id: str,
        status: str,
        error: str | None,
        finished_at: datetime,
    ) -> StageRunRecord | None:
        """Finalize a stage run with outcome."""
        ...

    def list_stage_runs(
        self,
        *,
        ingestion_id: str,
        stage: str | None,
    ) -> list[StageRunRecord]:
        """List stage runs for one ingestion, optionally filtered by stage."""
        ...

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
        """Persist one per-artifact stage outcome."""
        ...

    def list_stage_artifact_outcomes(
        self,
        *,
        ingestion_id: str,
        stage: str | None,
        status: str | None,
    ) -> list[StageArtifactOutcome]:
        """List artifact outcomes for one ingestion, with optional filters."""
        ...

    def get_stage_artifact_outcome_by_key(
        self,
        *,
        ingestion_id: str,
        stage: str,
        object_key: str,
    ) -> StageArtifactOutcome | None:
        """Read one artifact outcome by (ingestion, stage, object_key)."""
        ...

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
        """Create or update extraction metadata for one artifact."""
        ...

    def get_extraction_metadata(
        self, *, object_key: str
    ) -> ExtractionMetadataRecord | None:
        """Read extraction metadata by object key."""
        ...

    # -- normalization metadata --

    def upsert_normalization_metadata(
        self,
        *,
        object_key: str,
        method: str,
        confidence: float | None,
        created_at: datetime,
    ) -> NormalizationMetadataRecord:
        """Create or update normalization metadata for one artifact."""
        ...

    def get_normalization_metadata(
        self, *, object_key: str
    ) -> NormalizationMetadataRecord | None:
        """Read normalization metadata by object key."""
        ...

    # -- provenance --

    def get_or_create_provenance(
        self,
        *,
        object_key: str,
        created_at: datetime,
    ) -> ProvenanceRecord:
        """Return existing provenance record or create one for the given object key."""
        ...

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
        """Persist one provenance source; return None if it already exists (deduped)."""
        ...

    # -- anchor notes --

    def upsert_anchor_note(
        self,
        *,
        ingestion_id: str,
        normalized_object_key: str,
        vault_path: str,
        created_at: datetime,
    ) -> AnchorRecord:
        """Create or update the anchor note linkage for one normalized artifact."""
        ...

    def list_anchor_notes(self, *, ingestion_id: str) -> list[AnchorRecord]:
        """List anchor note records for one ingestion."""
        ...

    def get_anchor_by_normalized_key(
        self, *, normalized_object_key: str
    ) -> AnchorRecord | None:
        """Return the anchor record for one normalized artifact key, if any."""
        ...

    def delete_anchor_note(self, *, normalized_object_key: str) -> None:
        """Remove the anchor note linkage for one normalized artifact."""
        ...

    # -- indexing runs --

    def create_indexing_run(
        self,
        *,
        ingestion_id: str,
        status: str,
        created_at: datetime,
    ) -> IngestionIndexingRun:
        """Create one derived indexing run for an ingestion."""
        ...

    def get_indexing_run(self, *, indexing_run_id: str) -> IngestionIndexingRun | None:
        """Read one derived indexing run by id."""
        ...

    def update_indexing_run_job(
        self,
        *,
        indexing_run_id: str,
        job_id: str,
        updated_at: datetime,
    ) -> IngestionIndexingRun | None:
        """Attach a Job Service job id to one indexing run."""
        ...

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
        ...

    # -- health --

    def is_healthy(self) -> bool:
        """Return True when backing store is reachable."""
        ...


# ---------------------------------------------------------------------------
# Extractor plugin interface
# ---------------------------------------------------------------------------


class ExtractorContext:
    """Artifact context supplied to extractor implementations.

    Attributes:
        ingestion_id: Owning ingestion identifier.
        raw_object_key: Object key of the source raw artifact.
        payload: Raw artifact bytes.
        mime_type: Content type of the raw artifact, if known.
        source_type: Ingestion source type string.
        source_uri: Ingestion source URI, if available.
        source_actor: Originating actor identifier, if available.
    """

    __slots__ = (
        "ingestion_id",
        "raw_object_key",
        "payload",
        "mime_type",
        "source_type",
        "source_uri",
        "source_actor",
    )

    def __init__(
        self,
        *,
        ingestion_id: str,
        raw_object_key: str,
        payload: bytes,
        mime_type: str | None,
        source_type: str,
        source_uri: str | None,
        source_actor: str | None,
    ) -> None:
        """Initialize extraction context from raw artifact data."""
        self.ingestion_id = ingestion_id
        self.raw_object_key = raw_object_key
        self.payload = payload
        self.mime_type = mime_type
        self.source_type = source_type
        self.source_uri = source_uri
        self.source_actor = source_actor


class ExtractedArtifact:
    """Descriptor for one derived artifact produced by an extractor.

    Attributes:
        payload: Extracted content bytes.
        mime_type: Content type of the extracted artifact.
        method: Extraction method identifier for metadata.
        confidence: Optional confidence score (0.0–1.0).
        page_count: Optional page count for document artifacts.
    """

    __slots__ = ("payload", "mime_type", "method", "confidence", "page_count")

    def __init__(
        self,
        *,
        payload: bytes,
        mime_type: str | None,
        method: str,
        confidence: float | None = None,
        page_count: int | None = None,
    ) -> None:
        """Initialize an extracted artifact descriptor."""
        self.payload = payload
        self.mime_type = mime_type
        self.method = method
        self.confidence = confidence
        self.page_count = page_count


class BaseExtractor(ABC):
    """Abstract base class for Stage 2 extractor plugin implementations."""

    @abstractmethod
    def can_extract(self, context: ExtractorContext) -> bool:
        """Return True when this extractor can handle the given context."""

    @abstractmethod
    def extract(self, context: ExtractorContext) -> Sequence[ExtractedArtifact]:
        """Produce derived artifacts from the supplied raw artifact context."""


class ExtractorRegistry:
    """Registry that matches extractors against incoming artifact contexts."""

    def __init__(self, extractors: Sequence[BaseExtractor] = ()) -> None:
        """Initialize the registry with an optional sequence of extractor instances."""
        self._extractors: list[BaseExtractor] = list(extractors)

    def register(self, extractor: BaseExtractor) -> None:
        """Add an extractor to the registry."""
        self._extractors.append(extractor)

    def match(self, context: ExtractorContext) -> list[BaseExtractor]:
        """Return all extractors that can handle the supplied context."""
        return [e for e in self._extractors if e.can_extract(context)]


_TEXT_MIME_TYPES = frozenset(
    {
        "application/json",
        "application/markdown",
        "application/x-markdown",
        "text/markdown",
        "text/plain",
    }
)


class BuiltInTextExtractor(BaseExtractor):
    """Built-in extractor for UTF-8 text, Markdown, and JSON artifacts."""

    def can_extract(self, context: ExtractorContext) -> bool:
        """Return True for supported textual MIME types."""
        mime_type = (context.mime_type or "").split(";", 1)[0].strip().lower()
        return mime_type.startswith("text/") or mime_type in _TEXT_MIME_TYPES

    def extract(self, context: ExtractorContext) -> Sequence[ExtractedArtifact]:
        """Validate UTF-8 text payload and return it as one derived artifact."""
        context.payload.decode("utf-8")
        mime_type = (context.mime_type or "text/plain").split(";", 1)[0].strip()
        return (
            ExtractedArtifact(
                payload=context.payload,
                mime_type=mime_type or "text/plain",
                method="builtin_text",
                confidence=1.0,
            ),
        )


# ---------------------------------------------------------------------------
# Normalizer plugin interface
# ---------------------------------------------------------------------------


class ExtractionMetadataSnapshot:
    """Snapshot of extraction metadata for the normalizer context.

    Attributes:
        method: Extraction method identifier.
        confidence: Extraction confidence score, if available.
        page_count: Page count for document artifacts, if available.
    """

    __slots__ = ("method", "confidence", "page_count")

    def __init__(
        self,
        *,
        method: str | None = None,
        confidence: float | None = None,
        page_count: int | None = None,
    ) -> None:
        """Initialize extraction metadata snapshot."""
        self.method = method
        self.confidence = confidence
        self.page_count = page_count


class NormalizerContext:
    """Context supplied to normalizer plugin implementations.

    Attributes:
        ingestion_id: Owning ingestion identifier.
        extracted_object_key: Object key of the source extracted artifact.
        payload: Extracted artifact bytes.
        mime_type: Content type of the extracted artifact, if known.
        source_type: Ingestion source type string.
        source_uri: Ingestion source URI, if available.
        source_actor: Originating actor identifier, if available.
        extraction_metadata: Snapshot of extraction metadata, if available.
    """

    __slots__ = (
        "ingestion_id",
        "extracted_object_key",
        "payload",
        "mime_type",
        "source_type",
        "source_uri",
        "source_actor",
        "extraction_metadata",
    )

    def __init__(
        self,
        *,
        ingestion_id: str,
        extracted_object_key: str,
        payload: bytes,
        mime_type: str | None,
        source_type: str,
        source_uri: str | None,
        source_actor: str | None,
        extraction_metadata: ExtractionMetadataSnapshot | None = None,
    ) -> None:
        """Initialize normalization context from extracted artifact data."""
        self.ingestion_id = ingestion_id
        self.extracted_object_key = extracted_object_key
        self.payload = payload
        self.mime_type = mime_type
        self.source_type = source_type
        self.source_uri = source_uri
        self.source_actor = source_actor
        self.extraction_metadata = extraction_metadata


class NormalizedArtifact:
    """Descriptor for canonical output produced by a normalizer.

    Attributes:
        payload: Normalized content bytes.
        mime_type: Content type of the normalized artifact.
        method: Normalization method identifier for metadata.
        confidence: Optional confidence score (0.0–1.0).
    """

    __slots__ = ("payload", "mime_type", "method", "confidence")

    def __init__(
        self,
        *,
        payload: bytes,
        mime_type: str | None,
        method: str,
        confidence: float | None = None,
    ) -> None:
        """Initialize a normalized artifact descriptor."""
        self.payload = payload
        self.mime_type = mime_type
        self.method = method
        self.confidence = confidence


class BaseNormalizer(ABC):
    """Abstract base class for Stage 3 normalizer plugin implementations."""

    @abstractmethod
    def can_normalize(self, context: NormalizerContext) -> bool:
        """Return True when this normalizer can handle the given context."""

    @abstractmethod
    def normalize(self, context: NormalizerContext) -> Sequence[NormalizedArtifact]:
        """Produce canonical artifacts derived from the supplied extracted context."""


class NormalizerRegistry:
    """Registry that matches normalizers against incoming artifact contexts."""

    def __init__(self, normalizers: Sequence[BaseNormalizer] = ()) -> None:
        """Initialize the registry with an optional sequence of normalizer instances."""
        self._normalizers: list[BaseNormalizer] = list(normalizers)

    def register(self, normalizer: BaseNormalizer) -> None:
        """Add a normalizer to the registry."""
        self._normalizers.append(normalizer)

    def match(self, context: NormalizerContext) -> list[BaseNormalizer]:
        """Return all normalizers that can handle the supplied context."""
        return [n for n in self._normalizers if n.can_normalize(context)]


class BuiltInTextNormalizer(BaseNormalizer):
    """Built-in normalizer that converts UTF-8 text-like payloads to Markdown."""

    def can_normalize(self, context: NormalizerContext) -> bool:
        """Return True for supported textual MIME types."""
        mime_type = (context.mime_type or "").split(";", 1)[0].strip().lower()
        return mime_type.startswith("text/") or mime_type in _TEXT_MIME_TYPES

    def normalize(self, context: NormalizerContext) -> Sequence[NormalizedArtifact]:
        """Return one canonical UTF-8 Markdown/plain-text artifact."""
        import json

        text = context.payload.decode("utf-8")
        mime_type = (context.mime_type or "").split(";", 1)[0].strip().lower()
        if mime_type == "application/json":
            try:
                text = json.dumps(json.loads(text), indent=2, sort_keys=True)
            except json.JSONDecodeError:
                pass
        normalized = text.rstrip() + "\n"
        return (
            NormalizedArtifact(
                payload=normalized.encode("utf-8"),
                mime_type="text/markdown",
                method="builtin_text_to_markdown",
                confidence=1.0,
            ),
        )
