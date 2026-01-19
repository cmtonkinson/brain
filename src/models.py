"""Data models for Brain assistant."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import declarative_base

from config import settings
from time_utils import to_local

# SQLAlchemy base
Base = declarative_base()


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


class AttentionFailClosedQueue(Base):
    """Queued signal for fail-closed routing recovery."""

    __tablename__ = "attention_fail_closed_queue"

    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    source_component = Column(String(200), nullable=False)
    actor = Column(String(200), nullable=True)
    from_number = Column(String(200), nullable=False)
    to_number = Column(String(200), nullable=False)
    channel = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    signal_reference = Column(String(500), nullable=True)
    envelope_version = Column(String(50), nullable=True)
    signal_type = Column(String(200), nullable=True)
    urgency = Column(Float, nullable=True)
    channel_cost = Column(Float, nullable=True)
    content_type = Column(String(200), nullable=True)
    correlation_id = Column(String(200), nullable=True)
    routing_intent = Column(String(50), nullable=True)
    envelope_timestamp = Column(DateTime(timezone=True), nullable=True)
    deadline = Column(DateTime(timezone=True), nullable=True)
    previous_severity = Column(Integer, nullable=True)
    current_severity = Column(Integer, nullable=True)
    authorization_autonomy_level = Column(String(50), nullable=True)
    authorization_approval_status = Column(String(50), nullable=True)
    notification_version = Column(String(50), nullable=True)
    notification_origin_signal = Column(String(500), nullable=True)
    notification_confidence = Column(Float, nullable=True)
    reason = Column(String(200), nullable=False)
    queued_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    retry_at = Column(DateTime(timezone=True), nullable=False)


class AttentionFailClosedProvenanceInput(Base):
    """Provenance inputs linked to a fail-closed queue entry."""

    __tablename__ = "attention_fail_closed_provenance_inputs"

    id = Column(Integer, primary_key=True)
    queue_id = Column(Integer, ForeignKey("attention_fail_closed_queue.id"), nullable=False)
    input_type = Column(String(200), nullable=False)
    reference = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttentionFailClosedPolicyTag(Base):
    """Policy tags linked to a fail-closed queue entry."""

    __tablename__ = "attention_fail_closed_policy_tags"

    id = Column(Integer, primary_key=True)
    queue_id = Column(Integer, ForeignKey("attention_fail_closed_queue.id"), nullable=False)
    tag = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


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
