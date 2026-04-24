"""Authoritative Postgres repository for Commitment Service state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from lib.shared.ids import (
    generate_ulid_bytes,
    ulid_bytes_to_str,
    ulid_str_to_bytes,
)
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.reason.commitment.domain import (
    CommitmentCreationProposal,
    CommitmentJobLink,
    CommitmentProgressRecord,
    CommitmentRecord,
    CommitmentReviewItem,
    CommitmentReviewRun,
    CommitmentState,
    CommitmentTransitionProposal,
    CommitmentTransitionRecord,
    ProposalActor,
    ProposalStatus,
    ReviewCategory,
)

from .schema import (
    commitment_job_links,
    commitment_progress,
    commitment_transitions,
    commitments,
    creation_proposals,
    review_items,
    review_runs,
    transition_proposals,
)

_UNSET = object()


class PostgresCommitmentRepository:
    """SQL repository over Commitment Service-owned schema tables."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

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
    ) -> CommitmentRecord:
        """Persist one commitment."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                commitments.insert().values(
                    id=row_id,
                    description=description,
                    state=state,
                    provenance_reference=provenance_reference,
                    ingestion_id=ingestion_id,
                    source=source,
                    due_by=due_by,
                    due_timezone=due_timezone,
                    importance=importance,
                    effort_provided=effort_provided,
                    effort_inferred=effort_inferred,
                    urgency=urgency,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            row = (
                session.execute(select(commitments).where(commitments.c.id == row_id))
                .mappings()
                .one()
            )
            return _to_commitment_record(row)

    def get_commitment(self, *, commitment_id: str) -> CommitmentRecord | None:
        """Read one commitment by id."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(commitments).where(
                        commitments.c.id == ulid_str_to_bytes(commitment_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_commitment_record(row)

    def list_commitments(
        self, *, state: str | None, limit: int, cursor: str | None
    ) -> list[CommitmentRecord]:
        """List commitments with optional state filter and cursor pagination."""
        with self._sessions.session() as session:
            stmt = select(commitments).order_by(commitments.c.id)
            if state is not None:
                stmt = stmt.where(commitments.c.state == state)
            if cursor is not None:
                stmt = stmt.where(commitments.c.id > ulid_str_to_bytes(cursor))
            rows = session.execute(stmt.limit(limit)).mappings().all()
            return [_to_commitment_record(row) for row in rows]

    def update_commitment(
        self,
        *,
        commitment_id: str,
        description: str | None = None,
        provenance_reference: str | None = _UNSET,
        ingestion_id: str | None = _UNSET,
        source: str | None = _UNSET,
        due_by: datetime | None = _UNSET,
        due_timezone: str | None = _UNSET,
        importance: int | None = None,
        effort_provided: int | None = None,
        effort_inferred: int | None = _UNSET,
        urgency: int | None = None,
        last_modified_at: datetime | None = _UNSET,
        reviewed_at: datetime | None = _UNSET,
        updated_at: datetime = None,  # type: ignore[assignment]
    ) -> CommitmentRecord | None:
        """Update one commitment and return the refreshed record."""
        if updated_at is None:
            raise ValueError("updated_at is required")
        values: dict[str, Any] = {"updated_at": updated_at}
        if description is not None:
            values["description"] = description
        if provenance_reference is not _UNSET:
            values["provenance_reference"] = provenance_reference
        if ingestion_id is not _UNSET:
            values["ingestion_id"] = ingestion_id
        if source is not _UNSET:
            values["source"] = source
        if due_by is not _UNSET:
            values["due_by"] = due_by
        if due_timezone is not _UNSET:
            values["due_timezone"] = due_timezone
        if importance is not None:
            values["importance"] = importance
        if effort_provided is not None:
            values["effort_provided"] = effort_provided
        if effort_inferred is not _UNSET:
            values["effort_inferred"] = effort_inferred
        if urgency is not None:
            values["urgency"] = urgency
        if last_modified_at is not _UNSET:
            values["last_modified_at"] = last_modified_at
        if reviewed_at is not _UNSET:
            values["reviewed_at"] = reviewed_at

        commitment_id_bytes = ulid_str_to_bytes(commitment_id)
        with self._sessions.session() as session:
            session.execute(
                update(commitments)
                .where(commitments.c.id == commitment_id_bytes)
                .values(**values)
            )
            row = (
                session.execute(
                    select(commitments).where(commitments.c.id == commitment_id_bytes)
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_commitment_record(row)

    def create_progress_record(
        self,
        *,
        commitment_id: str,
        provenance_reference: str | None,
        occurred_at: datetime,
        summary: str,
        snippet: str | None,
        created_at: datetime,
    ) -> tuple[CommitmentRecord | None, CommitmentProgressRecord]:
        """Persist one progress row and atomically update last_progress_at."""
        commitment_id_bytes = ulid_str_to_bytes(commitment_id)
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                update(commitments)
                .where(commitments.c.id == commitment_id_bytes)
                .values(last_progress_at=occurred_at, updated_at=created_at)
            )
            session.execute(
                commitment_progress.insert().values(
                    id=row_id,
                    commitment_id=commitment_id_bytes,
                    provenance_reference=provenance_reference,
                    occurred_at=occurred_at,
                    summary=summary,
                    snippet=snippet,
                    created_at=created_at,
                )
            )
            commitment_row = (
                session.execute(
                    select(commitments).where(commitments.c.id == commitment_id_bytes)
                )
                .mappings()
                .one_or_none()
            )
            progress_row = (
                session.execute(
                    select(commitment_progress).where(
                        commitment_progress.c.id == row_id
                    )
                )
                .mappings()
                .one()
            )
            commitment = (
                None
                if commitment_row is None
                else _to_commitment_record(commitment_row)
            )
            return commitment, _to_progress_record(progress_row)

    def list_progress(self, *, commitment_id: str) -> list[CommitmentProgressRecord]:
        """List progress rows for one commitment newest-first."""
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(commitment_progress)
                    .where(
                        commitment_progress.c.commitment_id
                        == ulid_str_to_bytes(commitment_id)
                    )
                    .order_by(commitment_progress.c.occurred_at.desc())
                )
                .mappings()
                .all()
            )
            return [_to_progress_record(row) for row in rows]

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
    ) -> tuple[CommitmentRecord | None, CommitmentTransitionRecord]:
        """Persist one transition row and update commitment lifecycle state."""
        commitment_id_bytes = ulid_str_to_bytes(commitment_id)
        row_id = generate_ulid_bytes()
        values: dict[str, Any] = {
            "state": to_state,
            "updated_at": created_at,
        }
        if ever_missed_at is not None:
            values["ever_missed_at"] = ever_missed_at
        with self._sessions.session() as session:
            session.execute(
                update(commitments)
                .where(commitments.c.id == commitment_id_bytes)
                .values(**values)
            )
            session.execute(
                commitment_transitions.insert().values(
                    id=row_id,
                    commitment_id=commitment_id_bytes,
                    from_state=from_state,
                    to_state=to_state,
                    actor=actor,
                    reason=reason,
                    confidence=confidence,
                    created_at=created_at,
                )
            )
            commitment_row = (
                session.execute(
                    select(commitments).where(commitments.c.id == commitment_id_bytes)
                )
                .mappings()
                .one_or_none()
            )
            transition_row = (
                session.execute(
                    select(commitment_transitions).where(
                        commitment_transitions.c.id == row_id
                    )
                )
                .mappings()
                .one()
            )
            commitment = (
                None
                if commitment_row is None
                else _to_commitment_record(commitment_row)
            )
            return commitment, _to_transition_record(transition_row)

    def list_transitions(
        self, *, commitment_id: str
    ) -> list[CommitmentTransitionRecord]:
        """List transition rows for one commitment newest-first."""
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(commitment_transitions)
                    .where(
                        commitment_transitions.c.commitment_id
                        == ulid_str_to_bytes(commitment_id)
                    )
                    .order_by(commitment_transitions.c.created_at.desc())
                )
                .mappings()
                .all()
            )
            return [_to_transition_record(row) for row in rows]

    def cancel_pending_transition_proposals(
        self,
        *,
        commitment_id: str,
        decided_by: str,
        decision_reason: str,
        decided_at: datetime,
    ) -> None:
        """Cancel all pending transition proposals for one commitment."""
        with self._sessions.session() as session:
            session.execute(
                update(transition_proposals)
                .where(
                    transition_proposals.c.commitment_id
                    == ulid_str_to_bytes(commitment_id),
                    transition_proposals.c.status == ProposalStatus.PENDING.value,
                )
                .values(
                    status=ProposalStatus.CANCELED.value,
                    decided_by=decided_by,
                    decision_reason=decision_reason,
                    decided_at=decided_at,
                )
            )

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
    ) -> CommitmentCreationProposal:
        """Persist one creation proposal."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                creation_proposals.insert().values(
                    id=row_id,
                    description=description,
                    provenance_reference=provenance_reference,
                    ingestion_id=ingestion_id,
                    source=source,
                    due_by=due_by,
                    due_timezone=due_timezone,
                    importance=importance,
                    effort_provided=effort_provided,
                    effort_inferred=effort_inferred,
                    requested_by=requested_by,
                    confidence=confidence,
                    status=ProposalStatus.PENDING.value,
                    matched_commitment_id=matched_commitment_id,
                    match_summary=match_summary,
                    dedupe_confidence=dedupe_confidence,
                    created_at=created_at,
                )
            )
            row = (
                session.execute(
                    select(creation_proposals).where(creation_proposals.c.id == row_id)
                )
                .mappings()
                .one()
            )
            return _to_creation_proposal(row)

    def get_creation_proposal(
        self, *, proposal_id: str
    ) -> CommitmentCreationProposal | None:
        """Read one creation proposal by id."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(creation_proposals).where(
                        creation_proposals.c.id == ulid_str_to_bytes(proposal_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_creation_proposal(row)

    def decide_creation_proposal(
        self,
        *,
        proposal_id: str,
        status: str,
        decided_by: str,
        decision_reason: str | None,
        decided_at: datetime,
        created_commitment_id: str | None,
    ) -> CommitmentCreationProposal | None:
        """Mark one creation proposal as decided."""
        row_id = ulid_str_to_bytes(proposal_id)
        with self._sessions.session() as session:
            session.execute(
                update(creation_proposals)
                .where(creation_proposals.c.id == row_id)
                .values(
                    status=status,
                    decided_by=decided_by,
                    decision_reason=decision_reason,
                    decided_at=decided_at,
                    created_commitment_id=created_commitment_id,
                )
            )
            row = (
                session.execute(
                    select(creation_proposals).where(creation_proposals.c.id == row_id)
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_creation_proposal(row)

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
    ) -> CommitmentTransitionProposal:
        """Persist one transition proposal."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                transition_proposals.insert().values(
                    id=row_id,
                    commitment_id=ulid_str_to_bytes(commitment_id),
                    from_state=from_state,
                    to_state=to_state,
                    requested_by=requested_by,
                    confidence=confidence,
                    threshold=threshold,
                    reason=reason,
                    status=ProposalStatus.PENDING.value,
                    created_at=created_at,
                )
            )
            row = (
                session.execute(
                    select(transition_proposals).where(
                        transition_proposals.c.id == row_id
                    )
                )
                .mappings()
                .one()
            )
            return _to_transition_proposal(row)

    def get_transition_proposal(
        self, *, proposal_id: str
    ) -> CommitmentTransitionProposal | None:
        """Read one transition proposal by id."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(transition_proposals).where(
                        transition_proposals.c.id == ulid_str_to_bytes(proposal_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_transition_proposal(row)

    def get_pending_transition_proposal_for_commitment(
        self, *, commitment_id: str
    ) -> CommitmentTransitionProposal | None:
        """Return the pending transition proposal for one commitment, if present."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(transition_proposals)
                    .where(
                        transition_proposals.c.commitment_id
                        == ulid_str_to_bytes(commitment_id),
                        transition_proposals.c.status == ProposalStatus.PENDING.value,
                    )
                    .order_by(transition_proposals.c.created_at.desc())
                )
                .mappings()
                .first()
            )
            return None if row is None else _to_transition_proposal(row)

    def decide_transition_proposal(
        self,
        *,
        proposal_id: str,
        status: str,
        decided_by: str,
        decision_reason: str | None,
        decided_at: datetime,
    ) -> CommitmentTransitionProposal | None:
        """Mark one transition proposal as decided."""
        row_id = ulid_str_to_bytes(proposal_id)
        with self._sessions.session() as session:
            session.execute(
                update(transition_proposals)
                .where(transition_proposals.c.id == row_id)
                .values(
                    status=status,
                    decided_by=decided_by,
                    decision_reason=decision_reason,
                    decided_at=decided_at,
                )
            )
            row = (
                session.execute(
                    select(transition_proposals).where(
                        transition_proposals.c.id == row_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_transition_proposal(row)

    def upsert_job_link(
        self,
        *,
        commitment_id: str,
        job_id: str,
        job_timezone: str,
        linked_at: datetime,
    ) -> CommitmentJobLink:
        """Create or update the single follow-up job link for one commitment."""
        commitment_id_bytes = ulid_str_to_bytes(commitment_id)
        with self._sessions.session() as session:
            existing = (
                session.execute(
                    select(commitment_job_links).where(
                        commitment_job_links.c.commitment_id == commitment_id_bytes
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                row_id = generate_ulid_bytes()
                session.execute(
                    commitment_job_links.insert().values(
                        id=row_id,
                        commitment_id=commitment_id_bytes,
                        job_id=job_id,
                        job_timezone=job_timezone,
                        is_active=True,
                        linked_at=linked_at,
                        unlinked_at=None,
                    )
                )
            else:
                row_id = existing["id"]
                session.execute(
                    update(commitment_job_links)
                    .where(commitment_job_links.c.id == row_id)
                    .values(
                        job_id=job_id,
                        job_timezone=job_timezone,
                        is_active=True,
                        linked_at=linked_at,
                        unlinked_at=None,
                    )
                )
            row = (
                session.execute(
                    select(commitment_job_links).where(
                        commitment_job_links.c.id == row_id
                    )
                )
                .mappings()
                .one()
            )
            return _to_job_link(row)

    def clear_job_link(
        self, *, commitment_id: str, unlinked_at: datetime
    ) -> CommitmentJobLink | None:
        """Deactivate the follow-up job link for one commitment."""
        commitment_id_bytes = ulid_str_to_bytes(commitment_id)
        with self._sessions.session() as session:
            session.execute(
                update(commitment_job_links)
                .where(commitment_job_links.c.commitment_id == commitment_id_bytes)
                .values(is_active=False, unlinked_at=unlinked_at, job_id=None)
            )
            row = (
                session.execute(
                    select(commitment_job_links).where(
                        commitment_job_links.c.commitment_id == commitment_id_bytes
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_job_link(row)

    def get_job_link(self, *, commitment_id: str) -> CommitmentJobLink | None:
        """Read the follow-up job link for one commitment."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(commitment_job_links).where(
                        commitment_job_links.c.commitment_id
                        == ulid_str_to_bytes(commitment_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_job_link(row)

    def list_open_due_commitments(
        self, *, due_before: datetime, commitment_id: str | None = None
    ) -> list[CommitmentRecord]:
        """List open commitments due before the given instant."""
        with self._sessions.session() as session:
            stmt = select(commitments).where(
                commitments.c.state == CommitmentState.OPEN.value,
                commitments.c.due_by.is_not(None),
                commitments.c.due_by <= due_before,
            )
            if commitment_id is not None:
                stmt = stmt.where(commitments.c.id == ulid_str_to_bytes(commitment_id))
            rows = (
                session.execute(stmt.order_by(commitments.c.due_by.asc()))
                .mappings()
                .all()
            )
            return [_to_commitment_record(row) for row in rows]

    def latest_review_run(self) -> CommitmentReviewRun | None:
        """Return the most recent review run."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(review_runs).order_by(review_runs.c.run_at.desc())
                )
                .mappings()
                .first()
            )
            return None if row is None else _to_review_run(row)

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
    ) -> CommitmentReviewRun:
        """Persist one review run."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                review_runs.insert().values(
                    id=row_id,
                    since_at=since_at,
                    run_at=run_at,
                    completed_count=completed_count,
                    missed_count=missed_count,
                    modified_count=modified_count,
                    no_due_date_count=no_due_date_count,
                    created_at=created_at,
                )
            )
            row = (
                session.execute(select(review_runs).where(review_runs.c.id == row_id))
                .mappings()
                .one()
            )
            return _to_review_run(row)

    def mark_review_run_delivered(
        self,
        *,
        review_run_id: str,
        delivered_at: datetime,
        notification_reference: str | None,
    ) -> CommitmentReviewRun | None:
        """Mark one review run delivered."""
        row_id = ulid_str_to_bytes(review_run_id)
        with self._sessions.session() as session:
            session.execute(
                update(review_runs)
                .where(review_runs.c.id == row_id)
                .values(
                    delivered_at=delivered_at,
                    notification_reference=notification_reference,
                )
            )
            row = (
                session.execute(select(review_runs).where(review_runs.c.id == row_id))
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_review_run(row)

    def get_review_run(self, *, review_run_id: str) -> CommitmentReviewRun | None:
        """Read one review run by id."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(review_runs).where(
                        review_runs.c.id == ulid_str_to_bytes(review_run_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_review_run(row)

    def list_review_runs(
        self, *, limit: int, cursor: str | None
    ) -> list[CommitmentReviewRun]:
        """List review runs with cursor pagination."""
        with self._sessions.session() as session:
            stmt = select(review_runs).order_by(review_runs.c.id)
            if cursor is not None:
                stmt = stmt.where(review_runs.c.id > ulid_str_to_bytes(cursor))
            rows = session.execute(stmt.limit(limit)).mappings().all()
            return [_to_review_run(row) for row in rows]

    def create_review_item(
        self,
        *,
        review_run_id: str,
        commitment_id: str,
        category: ReviewCategory,
        message: str,
        presented_at: datetime,
        created_at: datetime,
    ) -> CommitmentReviewItem:
        """Persist one review item."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                review_items.insert().values(
                    id=row_id,
                    review_run_id=ulid_str_to_bytes(review_run_id),
                    commitment_id=ulid_str_to_bytes(commitment_id),
                    category=category.value,
                    message=message,
                    presented_at=presented_at,
                    created_at=created_at,
                )
            )
            row = (
                session.execute(select(review_items).where(review_items.c.id == row_id))
                .mappings()
                .one()
            )
            return _to_review_item(row)

    def list_review_items(self, *, review_run_id: str) -> list[CommitmentReviewItem]:
        """List review items for one run."""
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(review_items)
                    .where(
                        review_items.c.review_run_id == ulid_str_to_bytes(review_run_id)
                    )
                    .order_by(review_items.c.id)
                )
                .mappings()
                .all()
            )
            return [_to_review_item(row) for row in rows]

    def mark_commitment_presented_for_review(
        self, *, commitment_id: str, presented_at: datetime, updated_at: datetime
    ) -> CommitmentRecord | None:
        """Update one commitment's presented-for-review timestamp."""
        row_id = ulid_str_to_bytes(commitment_id)
        with self._sessions.session() as session:
            session.execute(
                update(commitments)
                .where(commitments.c.id == row_id)
                .values(
                    presented_for_review_at=presented_at,
                    updated_at=updated_at,
                )
            )
            row = (
                session.execute(select(commitments).where(commitments.c.id == row_id))
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_commitment_record(row)

    def list_completed_since(self, *, since: datetime) -> list[CommitmentRecord]:
        """List commitments completed since the given instant."""
        return self._list_transition_targets_since(
            since=since, to_state=CommitmentState.COMPLETED.value
        )

    def list_missed_since(self, *, since: datetime) -> list[CommitmentRecord]:
        """List commitments missed since the given instant."""
        return self._list_transition_targets_since(
            since=since, to_state=CommitmentState.MISSED.value
        )

    def list_modified_since(self, *, since: datetime) -> list[CommitmentRecord]:
        """List commitments substantively modified since the given instant."""
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(commitments)
                    .where(
                        commitments.c.last_modified_at.is_not(None),
                        commitments.c.last_modified_at > since,
                    )
                    .order_by(commitments.c.last_modified_at.asc())
                )
                .mappings()
                .all()
            )
            return [_to_commitment_record(row) for row in rows]

    def list_open_without_due_date(self) -> list[CommitmentRecord]:
        """List OPEN commitments with no due date."""
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(commitments)
                    .where(
                        commitments.c.state == CommitmentState.OPEN.value,
                        commitments.c.due_by.is_(None),
                    )
                    .order_by(commitments.c.id)
                )
                .mappings()
                .all()
            )
            return [_to_commitment_record(row) for row in rows]

    def _list_transition_targets_since(
        self, *, since: datetime, to_state: str
    ) -> list[CommitmentRecord]:
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(commitments)
                    .join(
                        commitment_transitions,
                        commitments.c.id == commitment_transitions.c.commitment_id,
                    )
                    .where(
                        commitment_transitions.c.to_state == to_state,
                        commitment_transitions.c.created_at > since,
                    )
                    .order_by(commitment_transitions.c.created_at.asc())
                )
                .mappings()
                .all()
            )
            seen: set[str] = set()
            ordered: list[CommitmentRecord] = []
            for row in rows:
                record = _to_commitment_record(row)
                if record.id in seen:
                    continue
                seen.add(record.id)
                ordered.append(record)
            return ordered


def _to_commitment_record(row: Any) -> CommitmentRecord:
    return CommitmentRecord(
        id=ulid_bytes_to_str(row["id"]),
        description=str(row["description"]),
        state=CommitmentState(str(row["state"])),
        provenance_reference=_opt_str(row, "provenance_reference"),
        ingestion_id=_opt_str(row, "ingestion_id"),
        source=_opt_str(row, "source"),
        due_by=_dt(row, "due_by"),
        due_timezone=_opt_str(row, "due_timezone"),
        importance=int(row["importance"]),
        effort_provided=int(row["effort_provided"]),
        effort_inferred=_opt_int(row, "effort_inferred"),
        urgency=int(row["urgency"]),
        last_progress_at=_dt(row, "last_progress_at"),
        last_modified_at=_dt(row, "last_modified_at"),
        ever_missed_at=_dt(row, "ever_missed_at"),
        presented_for_review_at=_dt(row, "presented_for_review_at"),
        reviewed_at=_dt(row, "reviewed_at"),
        created_at=_dt_required(row, "created_at"),
        updated_at=_dt_required(row, "updated_at"),
    )


def _to_progress_record(row: Any) -> CommitmentProgressRecord:
    return CommitmentProgressRecord(
        id=ulid_bytes_to_str(row["id"]),
        commitment_id=ulid_bytes_to_str(row["commitment_id"]),
        provenance_reference=_opt_str(row, "provenance_reference"),
        occurred_at=_dt_required(row, "occurred_at"),
        summary=str(row["summary"]),
        snippet=_opt_str(row, "snippet"),
        created_at=_dt_required(row, "created_at"),
    )


def _to_transition_record(row: Any) -> CommitmentTransitionRecord:
    return CommitmentTransitionRecord(
        id=ulid_bytes_to_str(row["id"]),
        commitment_id=ulid_bytes_to_str(row["commitment_id"]),
        from_state=CommitmentState(str(row["from_state"])),
        to_state=CommitmentState(str(row["to_state"])),
        actor=ProposalActor(str(row["actor"])),
        reason=_opt_str(row, "reason"),
        confidence=_opt_float(row, "confidence"),
        created_at=_dt_required(row, "created_at"),
    )


def _to_creation_proposal(row: Any) -> CommitmentCreationProposal:
    return CommitmentCreationProposal(
        id=ulid_bytes_to_str(row["id"]),
        description=str(row["description"]),
        provenance_reference=_opt_str(row, "provenance_reference"),
        ingestion_id=_opt_str(row, "ingestion_id"),
        source=_opt_str(row, "source"),
        due_by=_dt(row, "due_by"),
        due_timezone=_opt_str(row, "due_timezone"),
        importance=int(row["importance"]),
        effort_provided=int(row["effort_provided"]),
        effort_inferred=_opt_int(row, "effort_inferred"),
        requested_by=ProposalActor(str(row["requested_by"])),
        confidence=_opt_float(row, "confidence"),
        status=ProposalStatus(str(row["status"])),
        decided_by=_opt_str(row, "decided_by"),
        decision_reason=_opt_str(row, "decision_reason"),
        created_commitment_id=_opt_str(row, "created_commitment_id"),
        matched_commitment_id=_opt_str(row, "matched_commitment_id"),
        match_summary=_opt_str(row, "match_summary"),
        dedupe_confidence=_opt_float(row, "dedupe_confidence"),
        created_at=_dt_required(row, "created_at"),
        decided_at=_dt(row, "decided_at"),
    )


def _to_transition_proposal(row: Any) -> CommitmentTransitionProposal:
    return CommitmentTransitionProposal(
        id=ulid_bytes_to_str(row["id"]),
        commitment_id=ulid_bytes_to_str(row["commitment_id"]),
        from_state=CommitmentState(str(row["from_state"])),
        to_state=CommitmentState(str(row["to_state"])),
        requested_by=ProposalActor(str(row["requested_by"])),
        confidence=_opt_float(row, "confidence"),
        threshold=float(row["threshold"]),
        reason=_opt_str(row, "reason"),
        status=ProposalStatus(str(row["status"])),
        decided_by=_opt_str(row, "decided_by"),
        decision_reason=_opt_str(row, "decision_reason"),
        created_at=_dt_required(row, "created_at"),
        decided_at=_dt(row, "decided_at"),
    )


def _to_review_run(row: Any) -> CommitmentReviewRun:
    return CommitmentReviewRun(
        id=ulid_bytes_to_str(row["id"]),
        since_at=_dt_required(row, "since_at"),
        run_at=_dt_required(row, "run_at"),
        delivered_at=_dt(row, "delivered_at"),
        notification_reference=_opt_str(row, "notification_reference"),
        completed_count=int(row["completed_count"]),
        missed_count=int(row["missed_count"]),
        modified_count=int(row["modified_count"]),
        no_due_date_count=int(row["no_due_date_count"]),
        created_at=_dt_required(row, "created_at"),
    )


def _to_review_item(row: Any) -> CommitmentReviewItem:
    return CommitmentReviewItem(
        id=ulid_bytes_to_str(row["id"]),
        review_run_id=ulid_bytes_to_str(row["review_run_id"]),
        commitment_id=ulid_bytes_to_str(row["commitment_id"]),
        category=ReviewCategory(str(row["category"])),
        message=str(row["message"]),
        presented_at=_dt_required(row, "presented_at"),
        reviewed_at=_dt(row, "reviewed_at"),
        created_at=_dt_required(row, "created_at"),
    )


def _to_job_link(row: Any) -> CommitmentJobLink:
    return CommitmentJobLink(
        id=ulid_bytes_to_str(row["id"]),
        commitment_id=ulid_bytes_to_str(row["commitment_id"]),
        job_id=_opt_str(row, "job_id"),
        job_timezone=_opt_str(row, "job_timezone"),
        is_active=bool(row["is_active"]),
        linked_at=_dt_required(row, "linked_at"),
        unlinked_at=_dt(row, "unlinked_at"),
    )


def _dt(row: Any, field: str) -> datetime | None:
    value = row[field]
    if value is None:
        return None
    return value.astimezone(UTC)


def _dt_required(row: Any, field: str) -> datetime:
    value = _dt(row, field)
    if value is None:
        raise ValueError(f"{field} is required")
    return value


def _opt_str(row: Any, field: str) -> str | None:
    value = row[field]
    return None if value is None else str(value)


def _opt_int(row: Any, field: str) -> int | None:
    value = row[field]
    return None if value is None else int(value)


def _opt_float(row: Any, field: str) -> float | None:
    value = row[field]
    return None if value is None else float(value)
