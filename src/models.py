"""Data models for Brain assistant."""

from datetime import datetime, timezone
import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Index,
    JSON,
    String,
    Text,
    Time,
    Uuid,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

from commitments.constants import COMMITMENT_STATES
from config import settings
from time_utils import to_local

# SQLAlchemy base
Base = declarative_base()

# Scheduler enums
ScheduleTypeEnum = Enum(
    "one_time",
    "interval",
    "calendar_rule",
    "conditional",
    name="schedule_type",
    native_enum=False,
)
ScheduleStateEnum = Enum(
    "draft",
    "active",
    "paused",
    "canceled",
    "archived",
    "completed",
    name="schedule_state",
    native_enum=False,
)
ExecutionStatusEnum = Enum(
    "queued",
    "running",
    "succeeded",
    "failed",
    "retry_scheduled",
    "canceled",
    name="execution_status",
    native_enum=False,
)
IngestionStatusEnum = Enum(
    "queued",
    "running",
    "complete",
    "failed",
    name="ingestion_status",
    native_enum=False,
)
ArtifactTypeEnum = Enum(
    "raw",
    "extracted",
    "normalized",
    name="artifact_type",
    native_enum=False,
)
IngestionStageEnum = Enum(
    "store",
    "extract",
    "normalize",
    "anchor",
    name="ingestion_stage",
    native_enum=False,
)
ArtifactParentStageEnum = Enum(
    "store",
    "extract",
    "normalize",
    name="artifact_parent_stage",
    native_enum=False,
)
IngestionArtifactStatusEnum = Enum(
    "success",
    "failed",
    "skipped",
    name="ingestion_artifact_status",
    native_enum=False,
)
IntervalUnitEnum = Enum(
    "minute",
    "hour",
    "day",
    "week",
    "month",
    name="interval_unit",
    native_enum=False,
)
PredicateOperatorEnum = Enum(
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "exists",
    "matches",
    name="predicate_operator",
    native_enum=False,
)
EvaluationIntervalUnitEnum = Enum(
    "minute",
    "hour",
    "day",
    "week",
    name="evaluation_interval_unit",
    native_enum=False,
)
PredicateEvaluationStatusEnum = Enum(
    "true",
    "false",
    "error",
    "unknown",
    name="predicate_evaluation_status",
    native_enum=False,
)
BackoffStrategyEnum = Enum(
    "fixed",
    "exponential",
    "none",
    name="backoff_strategy",
    native_enum=False,
)
ScheduleAuditEventTypeEnum = Enum(
    "create",
    "update",
    "pause",
    "resume",
    "delete",
    "run_now",
    name="schedule_audit_event_type",
    native_enum=False,
)
_COMMITMENT_STATE_VALUES = "', '".join(COMMITMENT_STATES)
CommitmentStateEnum = Enum(
    *COMMITMENT_STATES,
    name="commitment_state",
    native_enum=False,
)
CommitmentTransitionActorEnum = Enum(
    "user",
    "system",
    name="commitment_transition_actor",
    native_enum=False,
)
CommitmentTransitionProposalStatusEnum = Enum(
    "pending",
    "approved",
    "rejected",
    "canceled",
    name="commitment_transition_proposal_status",
    native_enum=False,
)
CommitmentCreationProposalKindEnum = Enum(
    "dedupe",
    "approval",
    name="commitment_creation_proposal_kind",
    native_enum=False,
)
CommitmentCreationProposalStatusEnum = Enum(
    "pending",
    "approved",
    "rejected",
    "canceled",
    name="commitment_creation_proposal_status",
    native_enum=False,
)


# Database models
class Task(Base):
    """Pending task or reminder."""

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    description = Column(Text, nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)


class ActionLog(Base):
    """Log of actions taken by the agent."""

    __tablename__ = "action_logs"

    id = Column(Integer, primary_key=True)
    action_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    result = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Conversation(Base):
    """Conversation metadata (full content stored in Obsidian)."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    obsidian_path = Column(String(500), nullable=False)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_message_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    message_count = Column(Integer, default=0)


class IndexedNote(Base):
    """Indexed note metadata for Qdrant embedding sync."""

    __tablename__ = "indexed_notes"

    id = Column(Integer, primary_key=True)
    path = Column(String(1000), nullable=False)
    collection = Column(String(200), nullable=False)
    content_hash = Column(String(64), nullable=False)
    modified_at = Column(DateTime(timezone=True), nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0)
    last_indexed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class IndexedChunk(Base):
    """Indexed chunk metadata for a note."""

    __tablename__ = "indexed_chunks"

    id = Column(Integer, primary_key=True)
    note_id = Column(Integer, ForeignKey("indexed_notes.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    qdrant_id = Column(String(64), nullable=False)
    chunk_chars = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Ingestion(Base):
    """Ingestion attempt metadata for intake submissions."""

    __tablename__ = "ingestions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type = Column(String(200), nullable=False)
    source_uri = Column(Text, nullable=True)
    source_actor = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    status = Column(IngestionStatusEnum, nullable=False)
    last_error = Column(Text, nullable=True)


class Artifact(Base):
    """Metadata for raw or derived ingestion artifacts."""

    __tablename__ = "artifacts"

    object_key = Column(Text, primary_key=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    size_bytes = Column(BigInteger, nullable=False)
    mime_type = Column(Text, nullable=True)
    checksum = Column(Text, nullable=False)
    artifact_type = Column(ArtifactTypeEnum, nullable=False)
    first_ingested_at = Column(DateTime(timezone=True), nullable=False)
    last_ingested_at = Column(DateTime(timezone=True), nullable=False)
    parent_object_key = Column(Text, ForeignKey("artifacts.object_key"), nullable=True)
    parent_stage = Column(ArtifactParentStageEnum, nullable=True)


class ExtractionMetadata(Base):
    """Extraction metadata recorded for derived artifacts."""

    __tablename__ = "extraction_metadata"

    object_key = Column(Text, ForeignKey("artifacts.object_key"), primary_key=True)
    method = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    page_count = Column(Integer, nullable=True)
    tool_metadata = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class NormalizationMetadata(Base):
    """Normalization metadata recorded for canonical Markdown artifacts."""

    __tablename__ = "normalization_metadata"

    object_key = Column(Text, ForeignKey("artifacts.object_key"), primary_key=True)
    method = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    tool_metadata = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class IngestionArtifact(Base):
    """Stage-level artifact outcome record for a specific ingestion."""

    __tablename__ = "ingestion_artifacts"
    __table_args__ = (
        UniqueConstraint("ingestion_id", "stage", "object_key", name="uq_ingestion_stage_object"),
        CheckConstraint(
            "stage IN ('store', 'extract', 'normalize', 'anchor')",
            name="ck_ingestion_artifacts_stage",
        ),
        CheckConstraint(
            "status IN ('success', 'failed', 'skipped')",
            name="ck_ingestion_artifacts_status",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingestion_id = Column(Uuid(as_uuid=True), ForeignKey("ingestions.id"), nullable=False)
    stage = Column(IngestionStageEnum, nullable=False)
    object_key = Column(Text, ForeignKey("artifacts.object_key"), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    status = Column(IngestionArtifactStatusEnum, nullable=False)
    error = Column(Text, nullable=True)


class AnchorNote(Base):
    """Mapping between normalized artifacts and Obsidian anchor notes."""

    __tablename__ = "anchor_notes"

    normalized_object_key = Column(
        Text,
        ForeignKey("artifacts.object_key"),
        primary_key=True,
    )
    ingestion_id = Column(Uuid(as_uuid=True), ForeignKey("ingestions.id"), nullable=False)
    note_uri = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class IngestionIndexUpdate(Base):
    """Audit record that tracks ingestion-triggered index-update attempts."""

    __tablename__ = "ingestion_index_updates"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingestion_id = Column(Uuid(as_uuid=True), ForeignKey("ingestions.id"), nullable=False)
    status = Column(IngestionArtifactStatusEnum, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class IngestionEmbeddingDispatch(Base):
    """Per-artifact record of embeddings dispatch attempts for an ingestion."""

    __tablename__ = "ingestion_embedding_dispatches"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingestion_id = Column(Uuid(as_uuid=True), ForeignKey("ingestions.id"), nullable=False)
    normalized_object_key = Column(Text, ForeignKey("artifacts.object_key"), nullable=False)
    status = Column(IngestionArtifactStatusEnum, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class IngestionStageRun(Base):
    """Per-stage outcome record tracking timing, status, and errors for each ingestion attempt."""

    __tablename__ = "ingestion_stage_runs"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('store', 'extract', 'normalize', 'anchor')",
            name="ck_ingestion_stage_runs_stage",
        ),
        CheckConstraint(
            "status IN ('success', 'failed', 'skipped')",
            name="ck_ingestion_stage_runs_status",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingestion_id = Column(Uuid(as_uuid=True), ForeignKey("ingestions.id"), nullable=False)
    stage = Column(IngestionStageEnum, nullable=False)
    status = Column(IngestionArtifactStatusEnum, nullable=False)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ProvenanceRecord(Base):
    """Provenance record anchored to a specific artifact object key."""

    __tablename__ = "provenance_records"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    object_key = Column(Text, ForeignKey("artifacts.object_key"), nullable=False, unique=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ProvenanceSource(Base):
    """Deduplicated provenance source tied to an ingestion attempt."""

    __tablename__ = "provenance_sources"
    __table_args__ = (
        UniqueConstraint(
            "provenance_id",
            "source_type",
            "source_uri",
            "source_actor",
            name="uq_provenance_source_dedupe",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provenance_id = Column(Uuid(as_uuid=True), ForeignKey("provenance_records.id"), nullable=False)
    ingestion_id = Column(Uuid(as_uuid=True), ForeignKey("ingestions.id"), nullable=False)
    source_type = Column(Text, nullable=False)
    source_uri = Column(Text, nullable=True)
    source_actor = Column(Text, nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=False)


class Commitment(Base):
    """Commitment record tracking obligations and their lifecycle."""

    __tablename__ = "commitments"
    __table_args__ = (
        CheckConstraint(
            f"state IN ('{_COMMITMENT_STATE_VALUES}')",
            name="ck_commitments_state",
        ),
        CheckConstraint("importance BETWEEN 1 AND 3", name="ck_commitments_importance"),
        CheckConstraint("effort_provided BETWEEN 1 AND 3", name="ck_commitments_effort_provided"),
    )

    commitment_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    description = Column(Text, nullable=False)
    provenance_id = Column(Uuid(as_uuid=True), ForeignKey("provenance_records.id"), nullable=True)
    state = Column(CommitmentStateEnum, nullable=False, default="OPEN")
    importance = Column(Integer, nullable=False, default=2)
    effort_provided = Column(Integer, nullable=False, default=2)
    effort_inferred = Column(Integer, nullable=True)
    urgency = Column(Integer, nullable=True)
    due_by = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_progress_at = Column(DateTime(timezone=True), nullable=True)
    last_modified_at = Column(DateTime(timezone=True), nullable=True)
    ever_missed_at = Column(DateTime(timezone=True), nullable=True)
    presented_for_review_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    next_schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=True)


class CommitmentReviewRun(Base):
    """Audit record tracking a weekly review run timestamp."""

    __tablename__ = "commitment_review_runs"

    id = Column(Integer, primary_key=True)
    run_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    owner = Column(String, nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    engaged_at = Column(DateTime(timezone=True), nullable=True)


class CommitmentReviewItem(Base):
    """Commitment records included in a weekly review run."""

    __tablename__ = "commitment_review_items"
    __table_args__ = (
        UniqueConstraint(
            "review_run_id",
            "commitment_id",
            name="uq_commitment_review_items_review_run_commitment",
        ),
        Index("idx_commitment_review_items_review_run_id", "review_run_id"),
        Index("idx_commitment_review_items_commitment_id", "commitment_id"),
    )

    id = Column(Integer, primary_key=True)
    review_run_id = Column(
        Integer,
        ForeignKey("commitment_review_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    commitment_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("commitments.commitment_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class CommitmentProgress(Base):
    """Progress event recorded against a commitment."""

    __tablename__ = "commitment_progress"

    progress_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    commitment_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("commitments.commitment_id", ondelete="CASCADE"),
        nullable=False,
    )
    provenance_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("provenance_records.id"),
        nullable=True,
    )
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    summary = Column(Text, nullable=False)
    snippet = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSONB().with_variant(JSON(), "sqlite"), nullable=True)


class CommitmentArtifact(Base):
    """Junction table linking commitments to related artifacts."""

    __tablename__ = "commitment_artifacts"
    __table_args__ = (
        CheckConstraint(
            "relationship_type IN ('evidence', 'context', 'reference', 'progress', 'related')",
            name="ck_commitment_artifacts_relationship_type",
        ),
        CheckConstraint(
            "added_by IN ('user', 'system')",
            name="ck_commitment_artifacts_added_by",
        ),
        Index("ix_commitment_artifacts_commitment_id", "commitment_id"),
        Index("ix_commitment_artifacts_object_key", "object_key"),
    )

    commitment_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("commitments.commitment_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    object_key = Column(
        Text,
        ForeignKey("artifacts.object_key", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    relationship_type = Column(Text, nullable=False)
    added_at = Column(DateTime(timezone=True), nullable=False)
    added_by = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)


class CommitmentStateTransition(Base):
    """Audit record for a commitment state transition."""

    __tablename__ = "commitment_state_transitions"
    __table_args__ = (
        CheckConstraint(
            f"from_state IN ('{_COMMITMENT_STATE_VALUES}')",
            name="ck_commitment_state_transitions_from_state",
        ),
        CheckConstraint(
            f"to_state IN ('{_COMMITMENT_STATE_VALUES}')",
            name="ck_commitment_state_transitions_to_state",
        ),
        CheckConstraint(
            "actor IN ('user', 'system')",
            name="ck_commitment_state_transitions_actor",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.00 AND confidence <= 1.00)",
            name="ck_commitment_state_transitions_confidence",
        ),
    )

    transition_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    commitment_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("commitments.commitment_id", ondelete="CASCADE"),
        nullable=False,
    )
    from_state = Column(CommitmentStateEnum, nullable=False)
    to_state = Column(CommitmentStateEnum, nullable=False)
    transitioned_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    actor = Column(CommitmentTransitionActorEnum, nullable=False)
    reason = Column(Text, nullable=True)
    context = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    confidence = Column(Float, nullable=True)
    provenance_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("provenance_records.id"),
        nullable=True,
    )


class CommitmentTransitionProposal(Base):
    """Proposed commitment transition awaiting user confirmation."""

    __tablename__ = "commitment_transition_proposals"
    __table_args__ = (
        CheckConstraint(
            f"from_state IN ('{_COMMITMENT_STATE_VALUES}')",
            name="ck_commitment_transition_proposals_from_state",
        ),
        CheckConstraint(
            f"to_state IN ('{_COMMITMENT_STATE_VALUES}')",
            name="ck_commitment_transition_proposals_to_state",
        ),
        CheckConstraint(
            "actor IN ('user', 'system')",
            name="ck_commitment_transition_proposals_actor",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.00 AND confidence <= 1.00)",
            name="ck_commitment_transition_proposals_confidence",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'canceled')",
            name="ck_commitment_transition_proposals_status",
        ),
    )

    proposal_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    commitment_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("commitments.commitment_id", ondelete="CASCADE"),
        nullable=False,
    )
    from_state = Column(CommitmentStateEnum, nullable=False)
    to_state = Column(CommitmentStateEnum, nullable=False)
    actor = Column(CommitmentTransitionActorEnum, nullable=False)
    confidence = Column(Float, nullable=True)
    threshold = Column(Float, nullable=False)
    reason = Column(Text, nullable=True)
    context = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    proposed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    status = Column(CommitmentTransitionProposalStatusEnum, nullable=False, default="pending")
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_by = Column(CommitmentTransitionActorEnum, nullable=True)
    decision_reason = Column(Text, nullable=True)
    provenance_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("provenance_records.id"),
        nullable=True,
    )


class CommitmentCreationProposal(Base):
    """Persisted dedupe/approval proposal awaiting a user decision."""

    __tablename__ = "commitment_creation_proposals"
    __table_args__ = (
        Index(
            "ix_commitment_creation_proposals_status",
            "status",
            "proposed_at",
        ),
        Index(
            "ix_commitment_creation_proposals_channel_status",
            "source_channel",
            "status",
            "proposed_at",
        ),
        CheckConstraint(
            "proposal_kind IN ('dedupe', 'approval')",
            name="ck_commitment_creation_proposals_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'canceled')",
            name="ck_commitment_creation_proposals_status",
        ),
    )

    proposal_ref = Column(String(120), primary_key=True)
    proposal_kind = Column(CommitmentCreationProposalKindEnum, nullable=False)
    status = Column(CommitmentCreationProposalStatusEnum, nullable=False, default="pending")
    payload = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    source_channel = Column(String(50), nullable=False)
    source_actor = Column(String(200), nullable=True)
    proposed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_by = Column(String(200), nullable=True)
    decision_reason = Column(Text, nullable=True)
    created_commitment_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("commitments.commitment_id", ondelete="SET NULL"),
        nullable=True,
    )


class CommitmentScheduleLink(Base):
    """Link record between commitments and schedules."""

    __tablename__ = "commitment_schedules"

    commitment_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("commitments.commitment_id", ondelete="CASCADE"),
        primary_key=True,
    )
    schedule_id = Column(
        Integer,
        ForeignKey("schedules.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    is_active = Column(Boolean, nullable=False, default=True)


class NotificationEnvelope(Base):
    """Notification metadata wrapper with provenance and confidence."""

    __tablename__ = "notification_envelopes"

    id = Column(Integer, primary_key=True)
    version = Column(String(50), nullable=False)
    source_component = Column(String(200), nullable=False)
    origin_signal = Column(String(200), nullable=False)
    confidence = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class NotificationProvenanceInput(Base):
    """Normalized provenance input linked to a notification envelope."""

    __tablename__ = "notification_provenance_inputs"

    id = Column(Integer, primary_key=True)
    envelope_id = Column(Integer, ForeignKey("notification_envelopes.id"), nullable=False)
    input_type = Column(String(200), nullable=False)
    reference = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionContextWindow(Base):
    """Stored attention context window for a given owner."""

    __tablename__ = "attention_context_windows"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    source = Column(String(200), nullable=False)
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True), nullable=False)
    interruptible = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class NotificationHistoryEntry(Base):
    """History record for a routed notification decision."""

    __tablename__ = "notification_history"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    signal_reference = Column(String(500), nullable=False)
    outcome = Column(String(50), nullable=False)
    channel = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionAuditLog(Base):
    """Audit log entry for attention routing events."""

    __tablename__ = "attention_audit_logs"

    id = Column(Integer, primary_key=True)
    event_type = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    source_component = Column(String(200), nullable=False)
    signal_reference = Column(String(500), nullable=False)
    base_assessment = Column(String(50), nullable=False)
    policy_outcome = Column(String(100), nullable=True)
    final_decision = Column(String(100), nullable=False)
    envelope_id = Column(Integer, ForeignKey("notification_envelopes.id"), nullable=True)
    preference_reference = Column(String(100), nullable=True)


class DeferredSignal(Base):
    """Deferred signal awaiting re-evaluation."""

    __tablename__ = "attention_deferred_signals"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    signal_reference = Column(String(500), nullable=False)
    source_component = Column(String(200), nullable=False)
    reason = Column(Text, nullable=False)
    reevaluate_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class BatchedSignal(Base):
    """Batched signal awaiting digest generation."""

    __tablename__ = "attention_batched_signals"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    signal_reference = Column(String(500), nullable=False)
    source_component = Column(String(200), nullable=False)
    topic = Column(String(200), nullable=False)
    category = Column(String(200), nullable=False)
    batch_id = Column(Integer, ForeignKey("attention_batches.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionQuietHours(Base):
    """Stored quiet hours window for an owner."""

    __tablename__ = "attention_quiet_hours"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    timezone = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionDoNotDisturb(Base):
    """Stored do-not-disturb window for an owner."""

    __tablename__ = "attention_do_not_disturb"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    timezone = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionChannelPreference(Base):
    """Stored channel preference for an owner."""

    __tablename__ = "attention_channel_preferences"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    channel = Column(String(50), nullable=False)
    preference = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionEscalationThreshold(Base):
    """Stored escalation threshold for an owner."""

    __tablename__ = "attention_escalation_thresholds"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    signal_type = Column(String(200), nullable=False)
    threshold = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionAlwaysNotify(Base):
    """Stored always-notify exception for an owner."""

    __tablename__ = "attention_always_notify"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    signal_type = Column(String(200), nullable=False)
    source_component = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionEscalationLog(Base):
    """Logged escalation decision with triggering condition."""

    __tablename__ = "attention_escalation_logs"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    signal_type = Column(String(200), nullable=True)
    signal_reference = Column(String(500), nullable=False)
    trigger = Column(String(200), nullable=False)
    level = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionBatch(Base):
    """Scheduled batch record for grouped signals."""

    __tablename__ = "attention_batches"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    batch_type = Column(String(50), nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    topic = Column(String(200), nullable=True)
    category = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionBatchLog(Base):
    """Logged batch creation event."""

    __tablename__ = "attention_batch_logs"

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("attention_batches.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionBatchSummary(Base):
    """Stored summary for a batch."""

    __tablename__ = "attention_batch_summaries"

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("attention_batches.id"), nullable=False)
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionBatchItem(Base):
    """Stored ranked item for a batch."""

    __tablename__ = "attention_batch_items"

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("attention_batches.id"), nullable=False)
    signal_reference = Column(String(500), nullable=False)
    rank = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionReviewLog(Base):
    """Audit log for suppressed signal reviews."""

    __tablename__ = "attention_review_logs"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    signal_reference = Column(String(500), nullable=True)
    action = Column(String(100), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionDecisionRecord(Base):
    """Persisted attention routing decision."""

    __tablename__ = "attention_decision_records"

    id = Column(Integer, primary_key=True)
    signal_reference = Column(String(500), nullable=False)
    channel = Column(String(100), nullable=True)
    base_assessment = Column(String(50), nullable=False)
    policy_outcome = Column(String(100), nullable=True)
    final_decision = Column(String(100), nullable=False)
    explanation = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TaskIntent(Base):
    """Task intent statement for scheduled executions."""

    __tablename__ = "task_intents"

    id = Column(Integer, primary_key=True)
    summary = Column(String(500), nullable=False)
    details = Column(Text, nullable=True)
    creator_actor_type = Column(String(100), nullable=False)
    creator_actor_id = Column(String(200), nullable=True)
    creator_channel = Column(String(100), nullable=False)
    origin_reference = Column(String(500), nullable=True)
    superseded_by_intent_id = Column(Integer, ForeignKey("task_intents.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Schedule(Base):
    """Schedule definition linked to a task intent."""

    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True)
    task_intent_id = Column(Integer, ForeignKey("task_intents.id"), nullable=False)
    schedule_type = Column(ScheduleTypeEnum, nullable=False)
    state = Column(ScheduleStateEnum, nullable=False)
    timezone = Column(String(100), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_status = Column(ExecutionStatusEnum, nullable=True)
    failure_count = Column(Integer, nullable=False, default=0)
    last_execution_id = Column(Integer, ForeignKey("executions.id"), nullable=True)
    created_by_actor_type = Column(String(100), nullable=False)
    created_by_actor_id = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    run_at = Column(DateTime(timezone=True), nullable=True)
    interval_count = Column(Integer, nullable=True)
    interval_unit = Column(IntervalUnitEnum, nullable=True)
    anchor_at = Column(DateTime(timezone=True), nullable=True)
    rrule = Column(String(1000), nullable=True)
    calendar_anchor_at = Column(DateTime(timezone=True), nullable=True)
    predicate_subject = Column(String(200), nullable=True)
    predicate_operator = Column(PredicateOperatorEnum, nullable=True)
    predicate_value = Column(String(500), nullable=True)
    evaluation_interval_count = Column(Integer, nullable=True)
    evaluation_interval_unit = Column(EvaluationIntervalUnitEnum, nullable=True)
    last_evaluated_at = Column(DateTime(timezone=True), nullable=True)
    last_evaluation_status = Column(PredicateEvaluationStatusEnum, nullable=True)
    last_evaluation_error_code = Column(String(200), nullable=True)


class Execution(Base):
    """Execution record for a scheduled task."""

    __tablename__ = "executions"

    id = Column(Integer, primary_key=True)
    task_intent_id = Column(Integer, ForeignKey("task_intents.id"), nullable=False)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    actor_type = Column(String(100), nullable=False)
    actor_context = Column(String(200), nullable=True)
    trace_id = Column(String(200), nullable=True)
    status = Column(ExecutionStatusEnum, nullable=False)
    attempt_count = Column(Integer, nullable=False, default=0)
    retry_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=1)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    failure_count = Column(Integer, nullable=False, default=0)
    retry_backoff_strategy = Column(BackoffStrategyEnum, nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(200), nullable=True)
    last_error_message = Column(Text, nullable=True)


class ScheduleAuditLog(Base):
    """Audit log for schedule mutations."""

    __tablename__ = "schedule_audit_logs"

    id = Column(Integer, primary_key=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    task_intent_id = Column(Integer, ForeignKey("task_intents.id"), nullable=False)
    event_type = Column(ScheduleAuditEventTypeEnum, nullable=False)
    actor_type = Column(String(100), nullable=False)
    actor_id = Column(String(200), nullable=True)
    actor_channel = Column(String(100), nullable=False)
    trace_id = Column(String(200), nullable=False)
    request_id = Column(String(200), nullable=True)
    reason = Column(Text, nullable=True)
    diff_summary = Column(String(1000), nullable=True)
    occurred_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def _ensure_aware_timestamp(value: datetime | None) -> datetime | None:
    """Normalize timestamps to UTC when timezone info is missing."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


@event.listens_for(ScheduleAuditLog, "load")
def _normalize_schedule_audit_on_load(target: ScheduleAuditLog, _context: object) -> None:
    """Ensure loaded schedule audit timestamps retain timezone awareness."""
    target.occurred_at = _ensure_aware_timestamp(target.occurred_at)


class ExecutionAuditLog(Base):
    """Audit log for execution outcomes."""

    __tablename__ = "execution_audit_logs"

    id = Column(Integer, primary_key=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=False)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    task_intent_id = Column(Integer, ForeignKey("task_intents.id"), nullable=False)
    status = Column(ExecutionStatusEnum, nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    retry_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=1)
    failure_count = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(200), nullable=True)
    last_error_message = Column(Text, nullable=True)
    actor_type = Column(String(100), nullable=False)
    actor_id = Column(String(200), nullable=True)
    actor_channel = Column(String(100), nullable=False)
    actor_context = Column(String(200), nullable=True)
    trace_id = Column(String(200), nullable=False)
    request_id = Column(String(200), nullable=True)
    occurred_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


PredicateValueTypeEnum = Enum(
    "string",
    "number",
    "boolean",
    "timestamp",
    name="predicate_value_type",
    native_enum=False,
)


class PredicateEvaluationAuditLog(Base):
    """Audit log for predicate evaluation outcomes."""

    __tablename__ = "predicate_evaluation_audit_logs"

    id = Column(Integer, primary_key=True)
    evaluation_id = Column(String(200), nullable=False, unique=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=True)
    task_intent_id = Column(Integer, ForeignKey("task_intents.id"), nullable=False)
    actor_type = Column(String(100), nullable=False)
    actor_id = Column(String(200), nullable=True)
    actor_channel = Column(String(100), nullable=False)
    actor_privilege_level = Column(String(50), nullable=False)
    actor_autonomy_level = Column(String(50), nullable=False)
    trace_id = Column(String(200), nullable=False)
    request_id = Column(String(200), nullable=True)
    predicate_subject = Column(String(200), nullable=False)
    predicate_operator = Column(PredicateOperatorEnum, nullable=False)
    predicate_value = Column(String(500), nullable=True)
    predicate_value_type = Column(PredicateValueTypeEnum, nullable=False)
    evaluation_time = Column(DateTime(timezone=True), nullable=False)
    evaluated_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(PredicateEvaluationStatusEnum, nullable=False)
    result_code = Column(String(200), nullable=False)
    message = Column(Text, nullable=True)
    observed_value = Column(String(500), nullable=True)
    error_code = Column(String(200), nullable=True)
    error_message = Column(Text, nullable=True)
    authorization_decision = Column(String(50), nullable=False)
    authorization_reason_code = Column(String(200), nullable=True)
    authorization_reason_message = Column(Text, nullable=True)
    authorization_policy_name = Column(String(200), nullable=True)
    authorization_policy_version = Column(String(50), nullable=True)
    provider_name = Column(String(200), nullable=False)
    provider_attempt = Column(Integer, nullable=False)
    correlation_id = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# Pydantic models for API/validation
class TaskCreate(BaseModel):
    """Create a new task."""

    description: str
    scheduled_for: Optional[datetime] = None


class TaskResponse(BaseModel):
    """Task response."""

    id: int
    description: str
    scheduled_for: Optional[datetime]
    completed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SignalMessage(BaseModel):
    """Incoming Signal message from Signal API."""

    sender: str
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_device: int = 1
    expires_in_seconds: int = 0


class ConversationMessage(BaseModel):
    """In-memory representation of a conversation message."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_markdown(self) -> str:
        """Format message as markdown for Obsidian."""
        local_timestamp = to_local(self.timestamp)
        time_str = local_timestamp.strftime("%H:%M")
        user_display = settings.user.name or "User"
        role_display = user_display if self.role == "user" else "Brain"
        return f"## {time_str} - {role_display}\n\n{self.content}\n"


class ReviewSeverityEnum(str, Enum):
    """Severity levels for review items."""

    high = "high"
    medium = "medium"
    low = "low"


class ReviewIssueTypeEnum(str, Enum):
    """Types of issues identified by the review job."""

    orphaned = "orphaned"
    failing = "failing"
    ignored = "ignored"


class ReviewOutput(Base):
    """Summary of a review execution run."""

    __tablename__ = "review_outputs"

    id = Column(Integer, primary_key=True)
    job_execution_id = Column(Integer, ForeignKey("executions.id"), nullable=True)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    orphan_grace_period_seconds = Column(Integer, nullable=True)
    consecutive_failure_threshold = Column(Integer, nullable=True)
    stale_failure_age_seconds = Column(Integer, nullable=True)
    ignored_pause_age_seconds = Column(Integer, nullable=True)
    orphaned_count = Column(Integer, nullable=False, default=0)
    failing_count = Column(Integer, nullable=False, default=0)
    ignored_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ReviewItem(Base):
    """Individual finding from a review job."""

    __tablename__ = "review_items"

    id = Column(Integer, primary_key=True)
    review_output_id = Column(Integer, ForeignKey("review_outputs.id"), nullable=False)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    task_intent_id = Column(Integer, ForeignKey("task_intents.id"), nullable=False)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=True)
    issue_type = Column(String(50), nullable=False)  # ReviewIssueTypeEnum
    severity = Column(String(50), nullable=False)  # ReviewSeverityEnum
    description = Column(String(500), nullable=False)
    last_error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = ({"sqlite_autoincrement": True},)
