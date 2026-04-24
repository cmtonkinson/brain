"""Request validation models for Commitment Service public API inputs."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.reason.commitment.domain import (
    CommitmentState,
    CreationProposalDecision,
    LoopClosureIntent,
    ProposalActor,
    TransitionProposalDecision,
)

_MAX_PAGE_SIZE = 200


def _validate_timezone(value: str | None) -> str | None:
    """Normalize and validate an IANA timezone string, returning None for empty inputs."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        ZoneInfo(normalized)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid due_timezone: {normalized}") from exc
    return normalized


class _ValidationModel(BaseModel):
    """Base request model with strict shape semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CreateCommitmentRequest(_ValidationModel):
    """Validated create-commitment request shape."""

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
    requested_by: ProposalActor = ProposalActor.OPERATOR

    @field_validator("due_by")
    @classmethod
    def _validate_due_by(cls, value: datetime | date | None) -> datetime | date | None:
        """Require timezone-aware datetimes while preserving date-only inputs."""
        return _reject_naive_datetime(value, field_name="due_by")

    @field_validator("due_timezone")
    @classmethod
    def _validate_due_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone(value)


class UpdateCommitmentRequest(_ValidationModel):
    """Validated update-commitment request shape."""

    commitment_id: str = Field(min_length=1)
    description: str | None = Field(default=None, min_length=1, max_length=512)
    provenance_reference: str | None = None
    ingestion_id: str | None = None
    source: str | None = None
    due_by: datetime | date | None = None
    due_timezone: str | None = None
    importance: int | None = Field(default=None, ge=1, le=3)
    effort_provided: int | None = Field(default=None, ge=1, le=3)
    effort_inferred: int | None = Field(default=None, ge=1, le=3)
    reviewed_at: datetime | None = None

    @field_validator("due_by")
    @classmethod
    def _validate_due_by(cls, value: datetime | date | None) -> datetime | date | None:
        """Require timezone-aware datetimes while preserving date-only inputs."""
        return _reject_naive_datetime(value, field_name="due_by")

    @field_validator("due_timezone")
    @classmethod
    def _validate_due_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone(value)


class TransitionCommitmentRequest(_ValidationModel):
    """Validated transition-commitment request shape."""

    commitment_id: str = Field(min_length=1)
    to_state: CommitmentState
    requested_by: ProposalActor
    reason: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class RecordProgressRequest(_ValidationModel):
    """Validated record-progress request shape."""

    commitment_id: str = Field(min_length=1)
    provenance_reference: str | None = None
    occurred_at: datetime
    summary: str = Field(min_length=1, max_length=512)
    snippet: str | None = None


class CreationProposalDecisionRequest(_ValidationModel):
    """Validated create-proposal decision request."""

    proposal_id: str = Field(min_length=1)
    decision: CreationProposalDecision
    decided_by: str = Field(min_length=1)
    decision_reason: str | None = None


class TransitionProposalDecisionRequest(_ValidationModel):
    """Validated transition-proposal decision request."""

    proposal_id: str = Field(min_length=1)
    decision: TransitionProposalDecision
    decided_by: str = Field(min_length=1)
    decision_reason: str | None = None


class CommitmentIdRequest(_ValidationModel):
    """Validated request keyed by commitment_id."""

    commitment_id: str = Field(min_length=1)


class ReviewRunIdRequest(_ValidationModel):
    """Validated request keyed by review_run_id."""

    review_run_id: str = Field(min_length=1)


class ListCommitmentsRequest(_ValidationModel):
    """Validated list-commitments request."""

    state: CommitmentState | None = None
    limit: int = Field(default=50, ge=1, le=_MAX_PAGE_SIZE)
    cursor: str | None = None


class ListReviewRunsRequest(_ValidationModel):
    """Validated list-review-runs request."""

    limit: int = Field(default=50, ge=1, le=_MAX_PAGE_SIZE)
    cursor: str | None = None


class ListReviewItemsRequest(_ValidationModel):
    """Validated list-review-items request."""

    review_run_id: str = Field(min_length=1)


class LoopClosureReplyRequest(_ValidationModel):
    """Validated loop-closure resolution request."""

    commitment_id: str = Field(min_length=1)
    intent: LoopClosureIntent
    response_text: str = ""
    new_due_by: datetime | date | None = None
    due_timezone: str | None = None

    @field_validator("new_due_by")
    @classmethod
    def _validate_due_by(cls, value: datetime | date | None) -> datetime | date | None:
        """Require timezone-aware datetimes while preserving date-only inputs."""
        return _reject_naive_datetime(value, field_name="new_due_by")

    @field_validator("due_timezone")
    @classmethod
    def _validate_due_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone(value)

    @model_validator(mode="after")
    def _validate_new_due_by(self) -> "LoopClosureReplyRequest":
        """Require new_due_by for renegotiation."""
        if self.intent == LoopClosureIntent.RENEGOTIATE and self.new_due_by is None:
            raise ValueError("new_due_by is required for renegotiate intent")
        return self


def _reject_naive_datetime(
    value: datetime | date | None, *, field_name: str
) -> datetime | date | None:
    """Reject naive datetimes while allowing date-only due inputs."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} datetime must be timezone-aware")
    return value
