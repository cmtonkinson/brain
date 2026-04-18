"""Ingestion Service domain models, enums, and typed contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Sequence

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Stage constants
# ---------------------------------------------------------------------------

STAGE_ORDER: Sequence[str] = ("store", "extract", "normalize", "anchor")
"""Deterministic ordered ingestion stages."""

STAGE_SET: frozenset[str] = frozenset(STAGE_ORDER)
"""Fast membership test for known stages."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class IngestionStatus(str, Enum):
    """Overall ingestion attempt lifecycle statuses."""

    queued = "queued"
    running = "running"
    complete = "complete"
    failed = "failed"
    rejected = "rejected"


class StageRunStatus(str, Enum):
    """Per-stage run outcome statuses."""

    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"


class StageArtifactStatus(str, Enum):
    """Per-artifact per-stage outcome statuses."""

    success = "success"
    failed = "failed"
    skipped = "skipped"


# ---------------------------------------------------------------------------
# Core domain entities
# ---------------------------------------------------------------------------


class IngestionRecord(BaseModel):
    """Authoritative state for one ingestion attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    status: IngestionStatus
    source_type: str
    source_uri: str | None
    source_actor: str | None
    capture_time: datetime
    mime_type: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class StageRunRecord(BaseModel):
    """One execution run of a named stage within an ingestion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    ingestion_id: str
    stage: str
    status: StageRunStatus
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class StageArtifactOutcome(BaseModel):
    """Artifact-level outcome for one stage of an ingestion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    ingestion_id: str
    stage: str
    object_key: str | None
    """Opaque OAS object key; null when no artifact was produced."""
    parent_object_key: str | None
    """OAS key of the parent artifact in the lineage chain."""
    status: StageArtifactStatus
    error: str | None
    created_at: datetime


class ExtractionMetadataRecord(BaseModel):
    """Extraction metadata associated with one derived artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    object_key: str
    method: str
    confidence: float | None
    page_count: int | None
    created_at: datetime
    updated_at: datetime


class NormalizationMetadataRecord(BaseModel):
    """Normalization metadata associated with one canonical artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    object_key: str
    method: str
    confidence: float | None
    created_at: datetime
    updated_at: datetime


class ProvenanceRecord(BaseModel):
    """Provenance tracking for one object key across ingestions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    object_key: str
    created_at: datetime
    updated_at: datetime


class ProvenanceSourceRecord(BaseModel):
    """One deduplicated source entry attached to a provenance record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    provenance_id: str
    ingestion_id: str
    source_type: str
    source_uri: str | None
    source_actor: str | None
    captured_at: datetime


class AnchorRecord(BaseModel):
    """Linkage between a normalized artifact and its vault anchor note."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    ingestion_id: str
    normalized_object_key: str
    vault_path: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Stage result summaries (returned from internal stage orchestration)
# ---------------------------------------------------------------------------


class StoreStageResult(BaseModel):
    """Summary of a store stage execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ingestion_id: str
    object_key: str | None
    status: StageArtifactStatus
    error: str | None


class FanOutStageResult(BaseModel):
    """Summary of an extract or normalize stage execution (fan-out)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ingestion_id: str
    succeeded: int
    failed: int
    errors: tuple[str, ...]


class AnchorStageResult(BaseModel):
    """Summary of an anchor stage execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ingestion_id: str
    anchored: int
    failed: int
    errors: tuple[str, ...]


# ---------------------------------------------------------------------------
# Public API result shapes
# ---------------------------------------------------------------------------


class IngestionStatusResult(BaseModel):
    """Status snapshot for an ingestion attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ingestion_id: str
    status: IngestionStatus
    last_error: str | None


class StageOutcomeSummary(BaseModel):
    """Grouped artifact outcomes for one stage in the results view."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: str
    outcomes: tuple[StageArtifactOutcome, ...]


class IngestionResultsView(BaseModel):
    """Stable, stage-ordered results view for one ingestion attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ingestion_id: str
    stages: tuple[StageOutcomeSummary, ...]


class IngestionListResult(BaseModel):
    """Paginated ingestion list result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ingestions: list[IngestionRecord]
    cursor: str | None = None


class HealthStatus(BaseModel):
    """Ingestion Service health status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    detail: str


# ---------------------------------------------------------------------------
# Retry / replay semantics
# ---------------------------------------------------------------------------


class StageReplayDecision(BaseModel):
    """Decision on whether a stage should run based on prior outcomes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    should_run: bool
    reason: str


def stage_replay_decision(
    *,
    stage_runs: list[StageRunRecord],
) -> StageReplayDecision:
    """Determine whether a stage should run given its history.

    A stage should run if:
    - No prior run exists (first attempt).
    - The most recent run failed or was skipped.

    A stage should NOT run if:
    - The most recent run succeeded.
    """
    if not stage_runs:
        return StageReplayDecision(
            should_run=True,
            reason="no prior run exists",
        )
    most_recent = max(stage_runs, key=lambda r: r.created_at)
    if most_recent.status == StageRunStatus.success:
        return StageReplayDecision(
            should_run=False,
            reason=f"stage already succeeded at {most_recent.finished_at}",
        )
    if most_recent.status == StageRunStatus.failed:
        return StageReplayDecision(
            should_run=True,
            reason=f"retrying failed stage (previous: {most_recent.error})",
        )
    if most_recent.status == StageRunStatus.skipped:
        return StageReplayDecision(
            should_run=True,
            reason=f"retrying skipped stage (previous: {most_recent.error})",
        )
    return StageReplayDecision(
        should_run=True,
        reason=f"unknown prior status: {most_recent.status}",
    )
