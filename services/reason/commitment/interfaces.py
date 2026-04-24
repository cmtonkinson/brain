"""Interfaces for Commitment Service persistence and peer orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from services.reason.commitment.domain import (
    CommitmentCreationProposal,
    CommitmentJobLink,
    CommitmentProgressRecord,
    CommitmentRecord,
    CommitmentReviewItem,
    CommitmentReviewRun,
    CommitmentTransitionProposal,
    CommitmentTransitionRecord,
    ReviewCategory,
)


class CommitmentRepository(Protocol):
    """Persistence contract for Commitment Service-owned state."""

    def create_commitment(
        self,
        *,
        description: str,
        state: str,
        provenance_reference: str | None,
        ingestion_id: str | None,
        source: str | None,
        due_by: datetime | None,
        due_timezone: str | None,
        importance: int,
        effort_provided: int,
        effort_inferred: int | None,
        urgency: int,
        created_at: datetime,
    ) -> CommitmentRecord: ...

    def get_commitment(self, *, commitment_id: str) -> CommitmentRecord | None: ...

    def list_commitments(
        self, *, state: str | None, limit: int, cursor: str | None
    ) -> list[CommitmentRecord]: ...

    def update_commitment(
        self,
        *,
        commitment_id: str,
        description: str | None = None,
        provenance_reference: str | None = None,
        ingestion_id: str | None = None,
        source: str | None = None,
        due_by: datetime | None = None,
        due_timezone: str | None = None,
        importance: int | None = None,
        effort_provided: int | None = None,
        effort_inferred: int | None = None,
        urgency: int | None = None,
        last_modified_at: datetime | None = None,
        reviewed_at: datetime | None = None,
        updated_at: datetime,
    ) -> CommitmentRecord | None: ...

    def create_progress_record(
        self,
        *,
        commitment_id: str,
        provenance_reference: str | None,
        occurred_at: datetime,
        summary: str,
        snippet: str | None,
        created_at: datetime,
    ) -> tuple[CommitmentRecord | None, CommitmentProgressRecord]: ...

    def list_progress(
        self, *, commitment_id: str
    ) -> list[CommitmentProgressRecord]: ...

    def create_transition_record(
        self,
        *,
        commitment_id: str,
        from_state: str,
        to_state: str,
        actor: str,
        reason: str | None,
        confidence: float | None,
        created_at: datetime,
        ever_missed_at: datetime | None,
    ) -> tuple[CommitmentRecord | None, CommitmentTransitionRecord]: ...

    def list_transitions(
        self, *, commitment_id: str
    ) -> list[CommitmentTransitionRecord]: ...

    def cancel_pending_transition_proposals(
        self,
        *,
        commitment_id: str,
        decided_by: str,
        decision_reason: str,
        decided_at: datetime,
    ) -> None: ...

    def create_creation_proposal(
        self,
        *,
        description: str,
        provenance_reference: str | None,
        ingestion_id: str | None,
        source: str | None,
        due_by: datetime | None,
        due_timezone: str | None,
        importance: int,
        effort_provided: int,
        effort_inferred: int | None,
        requested_by: str,
        confidence: float | None,
        created_at: datetime,
        matched_commitment_id: str | None = None,
        match_summary: str | None = None,
        dedupe_confidence: float | None = None,
    ) -> CommitmentCreationProposal: ...

    def get_creation_proposal(
        self, *, proposal_id: str
    ) -> CommitmentCreationProposal | None: ...

    def decide_creation_proposal(
        self,
        *,
        proposal_id: str,
        status: str,
        decided_by: str,
        decision_reason: str | None,
        decided_at: datetime,
        created_commitment_id: str | None,
    ) -> CommitmentCreationProposal | None: ...

    def create_transition_proposal(
        self,
        *,
        commitment_id: str,
        from_state: str,
        to_state: str,
        requested_by: str,
        confidence: float | None,
        threshold: float,
        reason: str | None,
        created_at: datetime,
    ) -> CommitmentTransitionProposal: ...

    def get_transition_proposal(
        self, *, proposal_id: str
    ) -> CommitmentTransitionProposal | None: ...

    def get_pending_transition_proposal_for_commitment(
        self, *, commitment_id: str
    ) -> CommitmentTransitionProposal | None: ...

    def decide_transition_proposal(
        self,
        *,
        proposal_id: str,
        status: str,
        decided_by: str,
        decision_reason: str | None,
        decided_at: datetime,
    ) -> CommitmentTransitionProposal | None: ...

    def upsert_job_link(
        self,
        *,
        commitment_id: str,
        job_id: str,
        job_timezone: str,
        linked_at: datetime,
    ) -> CommitmentJobLink: ...

    def clear_job_link(
        self, *, commitment_id: str, unlinked_at: datetime
    ) -> CommitmentJobLink | None: ...

    def get_job_link(self, *, commitment_id: str) -> CommitmentJobLink | None: ...

    def list_open_due_commitments(
        self, *, due_before: datetime, commitment_id: str | None = None
    ) -> list[CommitmentRecord]: ...

    def latest_review_run(self) -> CommitmentReviewRun | None: ...

    def create_review_run(
        self,
        *,
        since_at: datetime,
        run_at: datetime,
        completed_count: int,
        missed_count: int,
        modified_count: int,
        no_due_date_count: int,
        created_at: datetime,
    ) -> CommitmentReviewRun: ...

    def mark_review_run_delivered(
        self,
        *,
        review_run_id: str,
        delivered_at: datetime,
        notification_reference: str | None,
    ) -> CommitmentReviewRun | None: ...

    def get_review_run(self, *, review_run_id: str) -> CommitmentReviewRun | None: ...

    def list_review_runs(
        self, *, limit: int, cursor: str | None
    ) -> list[CommitmentReviewRun]: ...

    def create_review_item(
        self,
        *,
        review_run_id: str,
        commitment_id: str,
        category: ReviewCategory,
        message: str,
        presented_at: datetime,
        created_at: datetime,
    ) -> CommitmentReviewItem: ...

    def list_review_items(
        self, *, review_run_id: str
    ) -> list[CommitmentReviewItem]: ...

    def mark_commitment_presented_for_review(
        self, *, commitment_id: str, presented_at: datetime, updated_at: datetime
    ) -> CommitmentRecord | None: ...

    def list_completed_since(self, *, since: datetime) -> list[CommitmentRecord]: ...

    def list_missed_since(self, *, since: datetime) -> list[CommitmentRecord]: ...

    def list_modified_since(self, *, since: datetime) -> list[CommitmentRecord]: ...

    def list_open_without_due_date(self) -> list[CommitmentRecord]: ...
