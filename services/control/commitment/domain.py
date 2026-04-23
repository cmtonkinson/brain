"""Commitment Service domain models, enums, and typed contracts."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CommitmentState(str, Enum):
    """Commitment lifecycle states."""

    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELED = "CANCELED"


class ProposalStatus(str, Enum):
    """Decision state for persisted proposals."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"


class ProposalActor(str, Enum):
    """Authority identities for proposal and transition requests."""

    OPERATOR = "operator"
    SERVICE = "service"


class ReviewCategory(str, Enum):
    """Weekly review aggregation categories."""

    COMPLETED = "completed"
    MISSED = "missed"
    MODIFIED = "modified"
    NO_DUE_DATE = "no_due_date"


class LoopClosureIntent(str, Enum):
    """Normalized loop-closure actions."""

    COMPLETE = "complete"
    CANCEL = "cancel"
    RENEGOTIATE = "renegotiate"
    REVIEW = "review"
    NOOP = "noop"


class CreationProposalDecision(str, Enum):
    """Supported creation proposal decisions."""

    APPROVE = "approve"
    REJECT = "reject"


class TransitionProposalDecision(str, Enum):
    """Supported transition proposal decisions."""

    APPROVE = "approve"
    REJECT = "reject"


class HealthStatus(BaseModel):
    """Commitment Service readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    detail: str


class CommitmentRecord(BaseModel):
    """Authoritative commitment state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    description: str
    state: CommitmentState
    provenance_reference: str | None = None
    ingestion_id: str | None = None
    source: str | None = None
    due_by: datetime | None = None
    due_timezone: str | None = None
    importance: int
    effort_provided: int
    effort_inferred: int | None = None
    urgency: int
    last_progress_at: datetime | None = None
    last_modified_at: datetime | None = None
    ever_missed_at: datetime | None = None
    presented_for_review_at: datetime | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CommitmentProgressRecord(BaseModel):
    """One commitment progress entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    commitment_id: str
    provenance_reference: str | None = None
    occurred_at: datetime
    summary: str
    snippet: str | None = None
    created_at: datetime


class CommitmentTransitionRecord(BaseModel):
    """One commitment state transition audit row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    commitment_id: str
    from_state: CommitmentState
    to_state: CommitmentState
    actor: ProposalActor
    reason: str | None = None
    confidence: float | None = None
    created_at: datetime


class CommitmentCreationProposal(BaseModel):
    """Pending or decided proposal to create one commitment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    description: str
    provenance_reference: str | None = None
    ingestion_id: str | None = None
    source: str | None = None
    due_by: datetime | None = None
    due_timezone: str | None = None
    importance: int
    effort_provided: int
    effort_inferred: int | None = None
    requested_by: ProposalActor
    confidence: float | None = None
    status: ProposalStatus
    decided_by: str | None = None
    decision_reason: str | None = None
    created_commitment_id: str | None = None
    matched_commitment_id: str | None = None
    match_summary: str | None = None
    dedupe_confidence: float | None = None
    created_at: datetime
    decided_at: datetime | None = None


class CommitmentTransitionProposal(BaseModel):
    """Pending or decided proposal to transition one commitment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    commitment_id: str
    from_state: CommitmentState
    to_state: CommitmentState
    requested_by: ProposalActor
    confidence: float | None = None
    threshold: float
    reason: str | None = None
    status: ProposalStatus
    decided_by: str | None = None
    decision_reason: str | None = None
    created_at: datetime
    decided_at: datetime | None = None


class CommitmentReviewRun(BaseModel):
    """One persisted review run summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    since_at: datetime
    run_at: datetime
    delivered_at: datetime | None = None
    notification_reference: str | None = None
    completed_count: int
    missed_count: int
    modified_count: int
    no_due_date_count: int
    created_at: datetime


class CommitmentReviewItem(BaseModel):
    """One persisted review item."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    review_run_id: str
    commitment_id: str
    category: ReviewCategory
    message: str
    presented_at: datetime
    reviewed_at: datetime | None = None
    created_at: datetime


class CommitmentJobLink(BaseModel):
    """Opaque link from a commitment to one follow-up job."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    commitment_id: str
    job_id: str | None = None
    job_timezone: str | None = None
    is_active: bool
    linked_at: datetime
    unlinked_at: datetime | None = None


class CommitmentMutationResult(BaseModel):
    """Result payload for create, update, transition, and proposal decisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    commitment: CommitmentRecord | None = None
    progress: CommitmentProgressRecord | None = None
    transition: CommitmentTransitionRecord | None = None
    creation_proposal: CommitmentCreationProposal | None = None
    transition_proposal: CommitmentTransitionProposal | None = None
    job_link: CommitmentJobLink | None = None


class CommitmentHistoryResult(BaseModel):
    """History view for one commitment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    commitment: CommitmentRecord
    progress: tuple[CommitmentProgressRecord, ...]
    transitions: tuple[CommitmentTransitionRecord, ...]


class CommitmentListResult(BaseModel):
    """Paginated commitment listing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[CommitmentRecord, ...]
    next_cursor: str | None = None


class MissDetectionResult(BaseModel):
    """Outcome of one miss-detection run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checked_count: int
    missed_count: int
    notified_count: int
    commitment_ids: tuple[str, ...]


class ReviewDeliveryResult(BaseModel):
    """Outcome of delivering one review run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_run: CommitmentReviewRun
    decision: str
    delivered: bool
    detail: str


class LoopClosureResolutionResult(BaseModel):
    """Outcome of applying one loop-closure reply."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    commitment: CommitmentRecord
    intent: LoopClosureIntent
    transition: CommitmentTransitionRecord | None = None
    progress: CommitmentProgressRecord | None = None
    job_link: CommitmentJobLink | None = None


class CommitmentCandidateIntakeRequest(BaseModel):
    """Typed intake payload for ingestion-derived commitment candidates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = Field(min_length=1, max_length=512)
    provenance_reference: str | None = None
    ingestion_id: str | None = None
    source: str | None = None
    due_by: datetime | date | None = None
    due_timezone: str | None = None
    importance: int = Field(default=2, ge=1, le=3)
    effort_provided: int = Field(default=2, ge=1, le=3)
    effort_inferred: int | None = Field(default=None, ge=1, le=3)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class CommitmentCandidate(BaseModel):
    """One commitment signal extracted from source text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str
    importance: int | None = None
    effort_provided: int | None = None
    due_by: datetime | None = None
    due_timezone: str | None = None
    confidence: float
    reasoning: str | None = None


class ExtractCandidatesResult(BaseModel):
    """Result of extracting commitment candidates from one text input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidates: tuple[CommitmentCandidate, ...]
    requested_by: ProposalActor = ProposalActor.SERVICE
