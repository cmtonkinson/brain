"""Tests for Commitment Service implementation with in-memory fakes."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import validation_error
from packages.brain_shared.ids import generate_ulid_str
from services.action.attention_router.domain import RouteNotificationResult
from services.action.language_model.domain import ChatResponse
from services.control.commitment.config import CommitmentServiceSettings
from services.control.commitment.domain import (
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
from services.control.commitment.implementation import DefaultCommitmentService
from services.control.job.domain import (
    AuditEventType,
    BackoffStrategy,
    JobMutationAudit,
    JobMutationResult,
    JobRecord,
    JobState,
    OneTimeDefinition,
    ScheduleType,
)


def _meta() -> Any:
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


class _FakeRuntime:
    def is_healthy(self) -> bool:
        return True


class _FakeRepository:
    """Small in-memory repository satisfying the CommitmentService needs."""

    def __init__(self) -> None:
        self.commitments: dict[str, CommitmentRecord] = {}
        self.progress: dict[str, list[CommitmentProgressRecord]] = {}
        self.transitions: dict[str, list[CommitmentTransitionRecord]] = {}
        self.creation_proposals: dict[str, CommitmentCreationProposal] = {}
        self.transition_proposals: dict[str, CommitmentTransitionProposal] = {}
        self.job_links: dict[str, CommitmentJobLink] = {}
        self.review_runs: dict[str, CommitmentReviewRun] = {}
        self.review_items: dict[str, list[CommitmentReviewItem]] = {}

    def create_commitment(self, **kwargs) -> CommitmentRecord:
        record = CommitmentRecord(
            id=generate_ulid_str(),
            description=kwargs["description"],
            state=CommitmentState(kwargs["state"]),
            provenance_reference=kwargs["provenance_reference"],
            ingestion_id=kwargs["ingestion_id"],
            source=kwargs["source"],
            due_by=kwargs["due_by"],
            due_timezone=kwargs["due_timezone"],
            importance=kwargs["importance"],
            effort_provided=kwargs["effort_provided"],
            effort_inferred=kwargs["effort_inferred"],
            urgency=kwargs["urgency"],
            created_at=kwargs["created_at"],
            updated_at=kwargs["created_at"],
        )
        self.commitments[record.id] = record
        return record

    def get_commitment(self, *, commitment_id: str) -> CommitmentRecord | None:
        return self.commitments.get(commitment_id)

    def list_commitments(
        self, *, state: str | None, limit: int, cursor: str | None
    ) -> list[CommitmentRecord]:
        items = sorted(self.commitments.values(), key=lambda item: item.id)
        if state is not None:
            items = [item for item in items if item.state.value == state]
        if cursor is not None:
            items = [item for item in items if item.id > cursor]
        return items[:limit]

    def update_commitment(
        self, *, commitment_id: str, updated_at: datetime, **kwargs
    ) -> CommitmentRecord | None:
        current = self.commitments.get(commitment_id)
        if current is None:
            return None
        data = current.model_dump(mode="python")
        for key, value in kwargs.items():
            data[key] = value
        data["updated_at"] = updated_at
        updated = CommitmentRecord.model_validate(data)
        self.commitments[commitment_id] = updated
        return updated

    def create_progress_record(
        self,
        *,
        commitment_id: str,
        occurred_at: datetime,
        created_at: datetime,
        **kwargs,
    ):
        current = self.commitments.get(commitment_id)
        progress = CommitmentProgressRecord(
            id=generate_ulid_str(),
            commitment_id=commitment_id,
            provenance_reference=kwargs["provenance_reference"],
            occurred_at=occurred_at,
            summary=kwargs["summary"],
            snippet=kwargs["snippet"],
            created_at=created_at,
        )
        self.progress.setdefault(commitment_id, []).append(progress)
        if current is not None:
            self.commitments[commitment_id] = current.model_copy(
                update={"last_progress_at": occurred_at, "updated_at": created_at}
            )
        return self.commitments.get(commitment_id), progress

    def list_progress(self, *, commitment_id: str) -> list[CommitmentProgressRecord]:
        return list(reversed(self.progress.get(commitment_id, [])))

    def create_transition_record(
        self,
        *,
        commitment_id: str,
        from_state: str,
        to_state: str,
        created_at: datetime,
        ever_missed_at: datetime | None,
        **kwargs,
    ):
        current = self.commitments.get(commitment_id)
        transition = CommitmentTransitionRecord(
            id=generate_ulid_str(),
            commitment_id=commitment_id,
            from_state=CommitmentState(from_state),
            to_state=CommitmentState(to_state),
            actor=ProposalActor(kwargs["actor"]),
            reason=kwargs["reason"],
            confidence=kwargs["confidence"],
            created_at=created_at,
        )
        self.transitions.setdefault(commitment_id, []).append(transition)
        if current is not None:
            self.commitments[commitment_id] = current.model_copy(
                update={
                    "state": CommitmentState(to_state),
                    "updated_at": created_at,
                    "ever_missed_at": ever_missed_at or current.ever_missed_at,
                }
            )
        return self.commitments.get(commitment_id), transition

    def list_transitions(
        self, *, commitment_id: str
    ) -> list[CommitmentTransitionRecord]:
        return list(reversed(self.transitions.get(commitment_id, [])))

    def cancel_pending_transition_proposals(
        self,
        *,
        commitment_id: str,
        decided_by: str,
        decision_reason: str,
        decided_at: datetime,
    ) -> None:
        for proposal_id, proposal in list(self.transition_proposals.items()):
            if (
                proposal.commitment_id == commitment_id
                and proposal.status == ProposalStatus.PENDING
            ):
                self.transition_proposals[proposal_id] = proposal.model_copy(
                    update={
                        "status": ProposalStatus.CANCELED,
                        "decided_by": decided_by,
                        "decision_reason": decision_reason,
                        "decided_at": decided_at,
                    }
                )

    def create_creation_proposal(
        self, *, created_at: datetime, **kwargs
    ) -> CommitmentCreationProposal:
        proposal = CommitmentCreationProposal(
            id=generate_ulid_str(),
            description=kwargs["description"],
            provenance_reference=kwargs["provenance_reference"],
            ingestion_id=kwargs["ingestion_id"],
            source=kwargs["source"],
            due_by=kwargs["due_by"],
            due_timezone=kwargs["due_timezone"],
            importance=kwargs["importance"],
            effort_provided=kwargs["effort_provided"],
            effort_inferred=kwargs["effort_inferred"],
            requested_by=ProposalActor(kwargs["requested_by"]),
            confidence=kwargs["confidence"],
            status=ProposalStatus.PENDING,
            matched_commitment_id=kwargs.get("matched_commitment_id"),
            match_summary=kwargs.get("match_summary"),
            dedupe_confidence=kwargs.get("dedupe_confidence"),
            created_at=created_at,
        )
        self.creation_proposals[proposal.id] = proposal
        return proposal

    def get_creation_proposal(
        self, *, proposal_id: str
    ) -> CommitmentCreationProposal | None:
        return self.creation_proposals.get(proposal_id)

    def decide_creation_proposal(
        self,
        *,
        proposal_id: str,
        status: str,
        decided_by: str,
        decision_reason: str | None,
        decided_at: datetime,
        created_commitment_id: str | None,
    ):
        proposal = self.creation_proposals.get(proposal_id)
        if proposal is None:
            return None
        updated = proposal.model_copy(
            update={
                "status": ProposalStatus(status),
                "decided_by": decided_by,
                "decision_reason": decision_reason,
                "decided_at": decided_at,
                "created_commitment_id": created_commitment_id,
            }
        )
        self.creation_proposals[proposal_id] = updated
        return updated

    def create_transition_proposal(
        self, *, created_at: datetime, **kwargs
    ) -> CommitmentTransitionProposal:
        proposal = CommitmentTransitionProposal(
            id=generate_ulid_str(),
            commitment_id=kwargs["commitment_id"],
            from_state=CommitmentState(kwargs["from_state"]),
            to_state=CommitmentState(kwargs["to_state"]),
            requested_by=ProposalActor(kwargs["requested_by"]),
            confidence=kwargs["confidence"],
            threshold=kwargs["threshold"],
            reason=kwargs["reason"],
            status=ProposalStatus.PENDING,
            created_at=created_at,
        )
        self.transition_proposals[proposal.id] = proposal
        return proposal

    def get_transition_proposal(
        self, *, proposal_id: str
    ) -> CommitmentTransitionProposal | None:
        return self.transition_proposals.get(proposal_id)

    def get_pending_transition_proposal_for_commitment(
        self, *, commitment_id: str
    ) -> CommitmentTransitionProposal | None:
        for proposal in self.transition_proposals.values():
            if (
                proposal.commitment_id == commitment_id
                and proposal.status == ProposalStatus.PENDING
            ):
                return proposal
        return None

    def decide_transition_proposal(
        self,
        *,
        proposal_id: str,
        status: str,
        decided_by: str,
        decision_reason: str | None,
        decided_at: datetime,
    ):
        proposal = self.transition_proposals.get(proposal_id)
        if proposal is None:
            return None
        updated = proposal.model_copy(
            update={
                "status": ProposalStatus(status),
                "decided_by": decided_by,
                "decision_reason": decision_reason,
                "decided_at": decided_at,
            }
        )
        self.transition_proposals[proposal_id] = updated
        return updated

    def upsert_job_link(
        self, *, commitment_id: str, job_id: str, job_timezone: str, linked_at: datetime
    ) -> CommitmentJobLink:
        current = self.job_links.get(commitment_id)
        if current is None:
            link = CommitmentJobLink(
                id=generate_ulid_str(),
                commitment_id=commitment_id,
                job_id=job_id,
                job_timezone=job_timezone,
                is_active=True,
                linked_at=linked_at,
            )
        else:
            link = current.model_copy(
                update={
                    "job_id": job_id,
                    "job_timezone": job_timezone,
                    "is_active": True,
                    "linked_at": linked_at,
                    "unlinked_at": None,
                }
            )
        self.job_links[commitment_id] = link
        return link

    def clear_job_link(
        self, *, commitment_id: str, unlinked_at: datetime
    ) -> CommitmentJobLink | None:
        current = self.job_links.get(commitment_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={"job_id": None, "is_active": False, "unlinked_at": unlinked_at}
        )
        self.job_links[commitment_id] = updated
        return updated

    def get_job_link(self, *, commitment_id: str) -> CommitmentJobLink | None:
        return self.job_links.get(commitment_id)

    def list_open_due_commitments(
        self, *, due_before: datetime, commitment_id: str | None = None
    ) -> list[CommitmentRecord]:
        items = [
            item
            for item in self.commitments.values()
            if item.state == CommitmentState.OPEN
            and item.due_by is not None
            and item.due_by <= due_before
        ]
        if commitment_id is not None:
            items = [item for item in items if item.id == commitment_id]
        return items

    def latest_review_run(self) -> CommitmentReviewRun | None:
        if not self.review_runs:
            return None
        return sorted(self.review_runs.values(), key=lambda item: item.run_at)[-1]

    def create_review_run(
        self, *, created_at: datetime, **kwargs
    ) -> CommitmentReviewRun:
        run = CommitmentReviewRun(
            id=generate_ulid_str(),
            since_at=kwargs["since_at"],
            run_at=kwargs["run_at"],
            completed_count=kwargs["completed_count"],
            missed_count=kwargs["missed_count"],
            modified_count=kwargs["modified_count"],
            no_due_date_count=kwargs["no_due_date_count"],
            created_at=created_at,
        )
        self.review_runs[run.id] = run
        self.review_items[run.id] = []
        return run

    def mark_review_run_delivered(
        self,
        *,
        review_run_id: str,
        delivered_at: datetime,
        notification_reference: str | None,
    ):
        run = self.review_runs.get(review_run_id)
        if run is None:
            return None
        updated = run.model_copy(
            update={
                "delivered_at": delivered_at,
                "notification_reference": notification_reference,
            }
        )
        self.review_runs[review_run_id] = updated
        return updated

    def get_review_run(self, *, review_run_id: str) -> CommitmentReviewRun | None:
        return self.review_runs.get(review_run_id)

    def list_review_runs(
        self, *, limit: int, cursor: str | None
    ) -> list[CommitmentReviewRun]:
        runs = sorted(self.review_runs.values(), key=lambda item: item.id)
        if cursor is not None:
            runs = [run for run in runs if run.id > cursor]
        return runs[:limit]

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
        item = CommitmentReviewItem(
            id=generate_ulid_str(),
            review_run_id=review_run_id,
            commitment_id=commitment_id,
            category=category,
            message=message,
            presented_at=presented_at,
            created_at=created_at,
        )
        self.review_items.setdefault(review_run_id, []).append(item)
        return item

    def list_review_items(self, *, review_run_id: str) -> list[CommitmentReviewItem]:
        return list(self.review_items.get(review_run_id, []))

    def mark_commitment_presented_for_review(
        self, *, commitment_id: str, presented_at: datetime, updated_at: datetime
    ) -> CommitmentRecord | None:
        current = self.commitments.get(commitment_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={"presented_for_review_at": presented_at, "updated_at": updated_at}
        )
        self.commitments[commitment_id] = updated
        return updated

    def list_completed_since(self, *, since: datetime) -> list[CommitmentRecord]:
        return self._list_by_transition(since=since, to_state=CommitmentState.COMPLETED)

    def list_missed_since(self, *, since: datetime) -> list[CommitmentRecord]:
        return self._list_by_transition(since=since, to_state=CommitmentState.MISSED)

    def list_modified_since(self, *, since: datetime) -> list[CommitmentRecord]:
        return [
            item
            for item in self.commitments.values()
            if item.last_modified_at is not None and item.last_modified_at > since
        ]

    def list_open_without_due_date(self) -> list[CommitmentRecord]:
        return [
            item
            for item in self.commitments.values()
            if item.state == CommitmentState.OPEN and item.due_by is None
        ]

    def _list_by_transition(
        self, *, since: datetime, to_state: CommitmentState
    ) -> list[CommitmentRecord]:
        result: list[CommitmentRecord] = []
        for commitment_id, transitions in self.transitions.items():
            if any(
                t.to_state == to_state and t.created_at > since for t in transitions
            ):
                result.append(self.commitments[commitment_id])
        return result


class _FakeJobService:
    def __init__(self) -> None:
        self.created_jobs: list[dict[str, Any]] = []
        self.updated_jobs: list[dict[str, Any]] = []
        self.canceled_jobs: list[str] = []

    def create_job(
        self,
        *,
        meta,
        summary: str,
        details: str | None,
        origin_reference: str | None,
        schedule_type: str,
        timezone: str,
        definition: dict[str, object],
        job_action: dict[str, object],
        start_state: str = "draft",
    ):
        now = datetime.now(UTC)
        job = JobRecord(
            id=generate_ulid_str(),
            job_intent_id=generate_ulid_str(),
            schedule_type=ScheduleType(schedule_type),
            state=JobState(start_state),
            timezone=timezone,
            definition=OneTimeDefinition(
                run_at=datetime.fromisoformat(str(definition["run_at"]))
            ),
            retry_max_attempts=1,
            retry_backoff_strategy=BackoffStrategy.none,
            retry_backoff_base_seconds=0,
            origin_trace_id=meta.trace_id,
            origin_envelope_id=meta.envelope_id,
            created_at=now,
            updated_at=now,
        )
        audit = JobMutationAudit(
            id=generate_ulid_str(),
            job_id=job.id,
            event_type=AuditEventType.create,
            actor_type=meta.principal,
            channel=meta.source,
            trace_id=meta.trace_id,
            created_at=now,
        )
        self.created_jobs.append(
            {
                "summary": summary,
                "origin_reference": origin_reference,
                "timezone": timezone,
                "definition": definition,
                "job_action": job_action,
                "job_id": job.id,
            }
        )
        return success(meta=meta, payload=JobMutationResult(job=job, audit=audit))

    def update_job(
        self,
        *,
        meta,
        job_id: str,
        timezone: str | None = None,
        definition: dict[str, object] | None = None,
        notes: str | None = None,
    ):
        self.updated_jobs.append(
            {
                "job_id": job_id,
                "timezone": timezone,
                "definition": definition,
                "notes": notes,
            }
        )
        return self.create_job(
            meta=meta,
            summary="updated",
            details=None,
            origin_reference=None,
            schedule_type="one_time",
            timezone=timezone or "UTC",
            definition=definition or {"run_at": datetime.now(UTC).isoformat()},
            job_action={
                "type": "capability_invocation",
                "capability_id": "demo",
                "input_payload": {},
            },
            start_state="active",
        )

    def cancel_job(self, *, meta, job_id: str):
        self.canceled_jobs.append(job_id)
        return self.create_job(
            meta=meta,
            summary="canceled",
            details=None,
            origin_reference=None,
            schedule_type="one_time",
            timezone="UTC",
            definition={"run_at": datetime.now(UTC).isoformat()},
            job_action={
                "type": "capability_invocation",
                "capability_id": "demo",
                "input_payload": {},
            },
            start_state="canceled",
        )


class _FakeAttentionRouterService:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def route_notification(
        self,
        *,
        meta,
        actor: str = "operator",
        channel: str = "",
        title: str = "",
        message: str,
        dedupe_key: str = "",
        batch_key: str = "",
        force: bool = False,
        conversational_memory=None,
    ):
        self.messages.append(
            {"title": title, "message": message, "dedupe_key": dedupe_key}
        )
        return success(
            meta=meta,
            payload=RouteNotificationResult(
                decision="sent",
                delivered=True,
                detail="ok",
                delivery_timestamp_ms=1234,
            ),
        )


class _FakeLmsService:
    """Fake Language Model Service for dedupe testing."""

    def __init__(self, *, response_text: str | None = None, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response_text = (
            response_text
            or '{"duplicate_commitment_id": null, "confidence": 0.0, "summary": ""}'
        )
        self._fail = fail

    def chat(self, *, meta, system_prompt="", prompt="", profile="standard"):
        self.calls.append(
            {"system_prompt": system_prompt, "prompt": prompt, "profile": profile}
        )
        if self._fail:
            return failure(
                meta=meta,
                errors=[validation_error("LMS unavailable", code="LMS_ERROR")],
            )
        return success(
            meta=meta,
            payload=ChatResponse(
                text=self._response_text, provider="fake", model="fake"
            ),
        )


def _service(
    repository: _FakeRepository | None = None,
    jobs: _FakeJobService | None = None,
    attention: _FakeAttentionRouterService | None = None,
    lms: _FakeLmsService | None = None,
    settings: CommitmentServiceSettings | None = None,
) -> tuple[
    DefaultCommitmentService,
    _FakeRepository,
    _FakeJobService,
    _FakeAttentionRouterService,
]:
    repo = repository or _FakeRepository()
    job_service = jobs or _FakeJobService()
    attention_service = attention or _FakeAttentionRouterService()
    return (
        DefaultCommitmentService(
            settings=settings or CommitmentServiceSettings(),
            repository=repo,
            runtime=_FakeRuntime(),
            job_service=job_service,
            attention_router_service=attention_service,
            language_model_service=lms,
        ),
        repo,
        job_service,
        attention_service,
    )


def test_create_commitment_normalizes_date_due_by_and_creates_follow_up_job() -> None:
    service, repo, jobs, _attention = _service()

    envelope = service.create_commitment(
        meta=_meta(),
        description="Submit report",
        due_by=date(2026, 4, 20),
        due_timezone="America/New_York",
    )

    assert envelope.ok
    record = envelope.payload.value.commitment
    assert record is not None
    assert record.due_by == datetime(2026, 4, 21, 3, 59, 59, tzinfo=UTC)
    assert envelope.payload.value.job_link is not None
    assert len(jobs.created_jobs) == 1
    assert repo.get_job_link(commitment_id=record.id) is not None


def test_create_commitment_rejects_naive_datetime_due_by() -> None:
    service, _repo, _jobs, _attention = _service()

    envelope = service.create_commitment(
        meta=_meta(),
        description="Submit report",
        due_by=datetime(2026, 4, 20, 12, 0, 0),
    )

    assert envelope.errors
    assert "timezone-aware" in envelope.errors[0].message


def test_update_commitment_rejects_naive_datetime_due_by() -> None:
    service, repo, _jobs, _attention = _service()
    record = repo.create_commitment(
        description="Submit report",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=datetime.now(UTC),
    )

    envelope = service.update_commitment(
        meta=_meta(),
        commitment_id=record.id,
        due_by=datetime(2026, 4, 20, 12, 0, 0),
    )

    assert envelope.errors
    assert "timezone-aware" in envelope.errors[0].message


def test_loop_closure_renegotiate_rejects_naive_datetime_due_by() -> None:
    service, repo, _jobs, _attention = _service()
    record = repo.create_commitment(
        description="Submit report",
        state="MISSED",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
        due_timezone="UTC",
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=datetime.now(UTC),
    )

    envelope = service.resolve_loop_closure_reply(
        meta=_meta(),
        commitment_id=record.id,
        intent="renegotiate",
        new_due_by=datetime(2026, 4, 21, 12, 0, 0),
    )

    assert envelope.errors
    assert "timezone-aware" in envelope.errors[0].message


def test_low_confidence_service_creation_returns_proposal() -> None:
    service, repo, _jobs, _attention = _service()

    envelope = service.create_commitment(
        meta=_meta(),
        description="Maybe do this",
        requested_by="service",
        confidence=0.2,
    )

    assert envelope.ok
    assert envelope.payload.value.creation_proposal is not None
    assert envelope.payload.value.commitment is None
    assert repo.commitments == {}


def test_low_confidence_service_transition_returns_proposal() -> None:
    service, repo, _jobs, _attention = _service()
    record = repo.create_commitment(
        description="Ship release",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=datetime.now(UTC),
    )

    envelope = service.transition_commitment(
        meta=_meta(),
        commitment_id=record.id,
        to_state="COMPLETED",
        requested_by="service",
        confidence=0.2,
    )

    assert envelope.ok
    proposal = envelope.payload.value.transition_proposal
    assert proposal is not None
    assert proposal.to_state == CommitmentState.COMPLETED
    assert repo.get_commitment(commitment_id=record.id).state == CommitmentState.OPEN


def test_operator_transition_cancels_pending_proposal_and_removes_job_link() -> None:
    service, repo, jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Close loop",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=now + timedelta(hours=1),
        due_timezone="UTC",
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=50,
        created_at=now,
    )
    repo.create_transition_proposal(
        commitment_id=record.id,
        from_state="OPEN",
        to_state="COMPLETED",
        requested_by="service",
        confidence=0.1,
        threshold=0.9,
        reason="maybe done",
        created_at=now,
    )
    repo.upsert_job_link(
        commitment_id=record.id,
        job_id="job-1",
        job_timezone="UTC",
        linked_at=now,
    )

    envelope = service.transition_commitment(
        meta=_meta(),
        commitment_id=record.id,
        to_state="COMPLETED",
        requested_by="operator",
    )

    assert envelope.ok
    assert envelope.payload.value.commitment.state == CommitmentState.COMPLETED
    assert any(
        proposal.status == ProposalStatus.CANCELED
        for proposal in repo.transition_proposals.values()
    )
    assert jobs.canceled_jobs == ["job-1"]
    assert repo.get_job_link(commitment_id=record.id).is_active is False


def test_record_progress_updates_last_progress_at() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Make progress",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )
    occurred_at = now + timedelta(minutes=5)

    envelope = service.record_progress(
        meta=_meta(),
        commitment_id=record.id,
        occurred_at=occurred_at,
        summary="Started work",
    )

    assert envelope.ok
    assert envelope.payload.value.progress is not None
    assert repo.get_commitment(commitment_id=record.id).last_progress_at == occurred_at


def test_loop_closure_renegotiate_reopens_missed_commitment_and_reschedules() -> None:
    service, repo, jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Renegotiate me",
        state="MISSED",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=now - timedelta(hours=1),
        due_timezone="UTC",
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=80,
        created_at=now,
    )

    envelope = service.resolve_loop_closure_reply(
        meta=_meta(),
        commitment_id=record.id,
        intent="renegotiate",
        new_due_by=date(2026, 4, 25),
        due_timezone="UTC",
        response_text="do it next week",
    )

    assert envelope.ok
    assert envelope.payload.value.commitment.state == CommitmentState.OPEN
    assert envelope.payload.value.job_link is not None
    assert len(jobs.created_jobs) == 1


def test_run_miss_detection_marks_due_open_commitment_missed_and_notifies() -> None:
    service, repo, jobs, attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Past due",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=now - timedelta(minutes=1),
        due_timezone="UTC",
        importance=3,
        effort_provided=2,
        effort_inferred=None,
        urgency=70,
        created_at=now - timedelta(days=1),
    )
    repo.upsert_job_link(
        commitment_id=record.id,
        job_id="job-1",
        job_timezone="UTC",
        linked_at=now - timedelta(days=1),
    )

    envelope = service.run_miss_detection(meta=_meta(), commitment_id=record.id)

    assert envelope.ok
    assert envelope.payload.value.missed_count == 1
    assert repo.get_commitment(commitment_id=record.id).state == CommitmentState.MISSED
    assert jobs.canceled_jobs == ["job-1"]
    assert len(attention.messages) == 1


def test_build_and_deliver_review_persists_run_and_routes_notification() -> None:
    service, repo, _jobs, attention = _service()
    now = datetime.now(UTC)
    repo.create_commitment(
        description="No due date",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now - timedelta(days=2),
    )
    completed = repo.create_commitment(
        description="Done item",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now - timedelta(days=2),
    )
    repo.create_transition_record(
        commitment_id=completed.id,
        from_state="OPEN",
        to_state="COMPLETED",
        actor="operator",
        reason="done",
        confidence=1.0,
        created_at=now - timedelta(hours=1),
        ever_missed_at=None,
    )

    build_env = service.build_review_sets(meta=_meta())
    assert build_env.ok
    run = build_env.payload.value
    assert run.completed_count == 1
    assert run.no_due_date_count == 1
    assert len(repo.list_review_items(review_run_id=run.id)) == 2

    deliver_env = service.deliver_review(meta=_meta(), review_run_id=run.id)
    assert deliver_env.ok
    assert deliver_env.payload.value.review_run.delivered_at is not None
    assert len(attention.messages) == 1


def test_invalid_transition_from_closed_state_is_rejected() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Already done",
        state="COMPLETED",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )

    envelope = service.transition_commitment(
        meta=_meta(),
        commitment_id=record.id,
        to_state="OPEN",
        requested_by="operator",
    )

    assert not envelope.ok
    assert (
        repo.get_commitment(commitment_id=record.id).state == CommitmentState.COMPLETED
    )


def test_update_due_by_recomputes_urgency() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Urgency test",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=now + timedelta(hours=1),
        due_timezone="UTC",
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=60,
        created_at=now,
    )

    envelope = service.update_commitment(
        meta=_meta(),
        commitment_id=record.id,
        due_by=now + timedelta(days=365),
        due_timezone="UTC",
    )

    assert envelope.ok
    updated = envelope.payload.value.commitment
    assert updated is not None
    assert updated.urgency < record.urgency


def test_apply_creation_proposal_decision_approve_creates_commitment() -> None:
    service, repo, jobs, _attention = _service()

    create_env = service.create_commitment(
        meta=_meta(),
        description="Proposed commitment",
        requested_by="service",
        confidence=0.2,
    )
    assert create_env.ok
    proposal_id = create_env.payload.value.creation_proposal.id

    approve_env = service.apply_creation_proposal_decision(
        meta=_meta(),
        proposal_id=proposal_id,
        decision="approve",
        decided_by="operator",
    )

    assert approve_env.ok
    result = approve_env.payload.value
    assert result.commitment is not None
    assert result.creation_proposal.status == ProposalStatus.APPROVED
    assert result.creation_proposal.created_commitment_id == result.commitment.id


def test_apply_creation_proposal_decision_reject_persists_rejection() -> None:
    service, repo, _jobs, _attention = _service()

    create_env = service.create_commitment(
        meta=_meta(),
        description="Rejected proposal",
        requested_by="service",
        confidence=0.2,
    )
    proposal_id = create_env.payload.value.creation_proposal.id

    reject_env = service.apply_creation_proposal_decision(
        meta=_meta(),
        proposal_id=proposal_id,
        decision="reject",
        decided_by="operator",
        decision_reason="not relevant",
    )

    assert reject_env.ok
    assert reject_env.payload.value.creation_proposal.status == ProposalStatus.REJECTED
    assert repo.commitments == {}


def test_apply_transition_proposal_decision_approve_applies_transition() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Approve this transition",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )

    proposal_env = service.transition_commitment(
        meta=_meta(),
        commitment_id=record.id,
        to_state="COMPLETED",
        requested_by="service",
        confidence=0.2,
    )
    assert proposal_env.ok
    proposal_id = proposal_env.payload.value.transition_proposal.id

    approve_env = service.apply_transition_proposal_decision(
        meta=_meta(),
        proposal_id=proposal_id,
        decision="approve",
        decided_by="operator",
    )

    assert approve_env.ok
    result = approve_env.payload.value
    assert result.commitment.state == CommitmentState.COMPLETED
    assert result.transition_proposal.status == ProposalStatus.APPROVED


def test_apply_transition_proposal_decision_reject_keeps_state() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Reject this transition",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )

    proposal_env = service.transition_commitment(
        meta=_meta(),
        commitment_id=record.id,
        to_state="COMPLETED",
        requested_by="service",
        confidence=0.2,
    )
    proposal_id = proposal_env.payload.value.transition_proposal.id

    reject_env = service.apply_transition_proposal_decision(
        meta=_meta(),
        proposal_id=proposal_id,
        decision="reject",
        decided_by="operator",
    )

    assert reject_env.ok
    assert (
        reject_env.payload.value.transition_proposal.status == ProposalStatus.REJECTED
    )
    assert repo.get_commitment(commitment_id=record.id).state == CommitmentState.OPEN


def test_loop_closure_complete_closes_commitment_and_removes_job() -> None:
    service, repo, jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Complete via loop closure",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=now + timedelta(hours=1),
        due_timezone="UTC",
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=60,
        created_at=now,
    )
    repo.upsert_job_link(
        commitment_id=record.id,
        job_id="job-complete",
        job_timezone="UTC",
        linked_at=now,
    )

    envelope = service.resolve_loop_closure_reply(
        meta=_meta(),
        commitment_id=record.id,
        intent="complete",
        response_text="All done",
    )

    assert envelope.ok
    result = envelope.payload.value
    assert result.commitment.state == CommitmentState.COMPLETED
    assert result.transition is not None
    assert jobs.canceled_jobs == ["job-complete"]
    assert result.job_link.is_active is False


def test_loop_closure_cancel_closes_commitment_and_removes_job() -> None:
    service, repo, jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Cancel via loop closure",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=now + timedelta(hours=1),
        due_timezone="UTC",
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=60,
        created_at=now,
    )
    repo.upsert_job_link(
        commitment_id=record.id,
        job_id="job-cancel",
        job_timezone="UTC",
        linked_at=now,
    )

    envelope = service.resolve_loop_closure_reply(
        meta=_meta(),
        commitment_id=record.id,
        intent="cancel",
        response_text="Not happening",
    )

    assert envelope.ok
    result = envelope.payload.value
    assert result.commitment.state == CommitmentState.CANCELED
    assert result.transition is not None
    assert jobs.canceled_jobs == ["job-cancel"]
    assert result.job_link.is_active is False


def test_get_commitment_history_returns_commitment_with_transitions_and_progress() -> (
    None
):
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="History test",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )
    repo.create_transition_record(
        commitment_id=record.id,
        from_state="OPEN",
        to_state="MISSED",
        actor="service",
        reason="overdue",
        confidence=None,
        created_at=now + timedelta(hours=1),
        ever_missed_at=now + timedelta(hours=1),
    )
    repo.create_progress_record(
        commitment_id=record.id,
        provenance_reference=None,
        occurred_at=now + timedelta(minutes=30),
        summary="Some progress made",
        snippet=None,
        created_at=now + timedelta(minutes=30),
    )

    envelope = service.get_commitment_history(
        meta=_meta(),
        commitment_id=record.id,
    )

    assert envelope.ok
    history = envelope.payload.value
    assert history.commitment.id == record.id
    assert len(history.transitions) == 1
    assert len(history.progress) == 1


def test_ingest_commitment_candidate_low_confidence_returns_proposal() -> None:
    service, repo, _jobs, _attention = _service()

    envelope = service.ingest_commitment_candidate(
        meta=_meta(),
        description="Maybe a commitment",
        confidence=0.5,
    )

    assert envelope.ok
    result = envelope.payload.value
    assert result.creation_proposal is not None
    assert result.commitment is None
    assert repo.commitments == {}


# ---------------------------------------------------------------------------
# Coverage gap tests
# ---------------------------------------------------------------------------


def test_loop_closure_review_updates_reviewed_at() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Review me",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )

    envelope = service.resolve_loop_closure_reply(
        meta=_meta(),
        commitment_id=record.id,
        intent="review",
    )

    assert envelope.ok
    result = envelope.payload.value
    assert result.intent.value == "review"
    assert result.commitment.reviewed_at is not None
    assert result.transition is None
    assert result.commitment.state == CommitmentState.OPEN


def test_loop_closure_noop_no_state_change() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Noop me",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )

    envelope = service.resolve_loop_closure_reply(
        meta=_meta(),
        commitment_id=record.id,
        intent="noop",
    )

    assert envelope.ok
    result = envelope.payload.value
    assert result.intent.value == "noop"
    assert result.commitment.state == CommitmentState.OPEN
    assert result.transition is None
    assert result.progress is None


def test_ensure_follow_up_job_creates_link() -> None:
    service, repo, jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Follow up",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=now + timedelta(hours=2),
        due_timezone="UTC",
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=50,
        created_at=now,
    )

    envelope = service.ensure_follow_up_job(meta=_meta(), commitment_id=record.id)

    assert envelope.ok
    result = envelope.payload.value
    assert result.job_link is not None
    assert result.job_link.is_active is True
    assert len(jobs.created_jobs) == 1


def test_remove_follow_up_job_clears_link() -> None:
    service, repo, jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Remove follow up",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=now + timedelta(hours=2),
        due_timezone="UTC",
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=50,
        created_at=now,
    )
    repo.upsert_job_link(
        commitment_id=record.id,
        job_id="job-remove",
        job_timezone="UTC",
        linked_at=now,
    )

    envelope = service.remove_follow_up_job(meta=_meta(), commitment_id=record.id)

    assert envelope.ok
    result = envelope.payload.value
    assert result.job_link is not None
    assert result.job_link.is_active is False
    assert "job-remove" in jobs.canceled_jobs


def test_health_returns_ready() -> None:
    service, _repo, _jobs, _attention = _service()

    envelope = service.health(meta=_meta())

    assert envelope.ok
    result = envelope.payload.value
    assert result.service_ready is True
    assert result.detail == "ok"


def test_list_commitments_with_state_filter() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    for desc in ("Open 1", "Open 2"):
        repo.create_commitment(
            description=desc,
            state="OPEN",
            provenance_reference=None,
            ingestion_id=None,
            source=None,
            due_by=None,
            due_timezone=None,
            importance=2,
            effort_provided=2,
            effort_inferred=None,
            urgency=40,
            created_at=now,
        )
    repo.create_commitment(
        description="Done",
        state="COMPLETED",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )

    envelope = service.list_commitments(meta=_meta(), state="OPEN")

    assert envelope.ok
    result = envelope.payload.value
    assert len(result.items) == 2
    assert all(item.state == CommitmentState.OPEN for item in result.items)


def test_list_commitments_with_cursor_pagination() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    for i in range(3):
        repo.create_commitment(
            description=f"Item {i}",
            state="OPEN",
            provenance_reference=None,
            ingestion_id=None,
            source=None,
            due_by=None,
            due_timezone=None,
            importance=2,
            effort_provided=2,
            effort_inferred=None,
            urgency=40,
            created_at=now,
        )

    page1 = service.list_commitments(meta=_meta(), limit=2)
    assert page1.ok
    result1 = page1.payload.value
    assert len(result1.items) == 2
    assert result1.next_cursor is not None

    page2 = service.list_commitments(meta=_meta(), limit=2, cursor=result1.next_cursor)
    assert page2.ok
    result2 = page2.payload.value
    assert len(result2.items) == 1
    assert result2.next_cursor is None


def test_list_review_runs_returns_persisted_runs() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    repo.create_commitment(
        description="Open for review listing",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )

    service.build_review_sets(meta=_meta())

    envelope = service.list_review_runs(meta=_meta())
    assert envelope.ok
    runs = envelope.payload.value
    assert len(runs) >= 1


def test_update_commitment_multiple_fields() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Old description",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=1,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )

    envelope = service.update_commitment(
        meta=_meta(),
        commitment_id=record.id,
        description="New description",
        importance=3,
    )

    assert envelope.ok
    updated = envelope.payload.value.commitment
    assert updated.description == "New description"
    assert updated.importance == 3
    assert updated.last_modified_at is not None


def test_miss_detection_scans_all_due_commitments() -> None:
    service, repo, _jobs, attention = _service()
    now = datetime.now(UTC)
    for i in range(2):
        repo.create_commitment(
            description=f"Past due {i}",
            state="OPEN",
            provenance_reference=None,
            ingestion_id=None,
            source=None,
            due_by=now - timedelta(minutes=5),
            due_timezone="UTC",
            importance=2,
            effort_provided=2,
            effort_inferred=None,
            urgency=60,
            created_at=now - timedelta(days=1),
        )

    envelope = service.run_miss_detection(meta=_meta())

    assert envelope.ok
    result = envelope.payload.value
    assert result.checked_count == 2
    assert result.missed_count == 2


def test_service_missed_transition_skips_proposal() -> None:
    service, repo, _jobs, _attention = _service()
    now = datetime.now(UTC)
    record = repo.create_commitment(
        description="Should miss directly",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )

    envelope = service.transition_commitment(
        meta=_meta(),
        commitment_id=record.id,
        to_state="MISSED",
        requested_by="service",
        confidence=0.5,
    )

    assert envelope.ok
    result = envelope.payload.value
    assert result.commitment.state == CommitmentState.MISSED
    assert result.transition is not None
    assert result.transition_proposal is None


def test_high_confidence_service_creation_goes_direct() -> None:
    service, repo, _jobs, _attention = _service()

    envelope = service.create_commitment(
        meta=_meta(),
        description="High confidence service create",
        requested_by="service",
        confidence=0.95,
    )

    assert envelope.ok
    result = envelope.payload.value
    assert result.commitment is not None
    assert result.creation_proposal is None


def test_ingest_candidate_high_confidence_creates_directly() -> None:
    service, repo, _jobs, _attention = _service()

    envelope = service.ingest_commitment_candidate(
        meta=_meta(),
        description="High confidence ingested",
        confidence=0.95,
    )

    assert envelope.ok
    result = envelope.payload.value
    assert result.commitment is not None
    assert result.creation_proposal is None


# ---------------------------------------------------------------------------
# Dedupe tests
# ---------------------------------------------------------------------------


def test_dedupe_blocks_creation_when_duplicate_detected() -> None:
    repo = _FakeRepository()
    now = datetime.now(UTC)
    existing = repo.create_commitment(
        description="Ship the release",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )
    lms = _FakeLmsService(
        response_text=json.dumps(
            {
                "duplicate_commitment_id": existing.id,
                "confidence": 0.95,
                "summary": "Same obligation",
            }
        )
    )
    service, _repo, _jobs, _attention = _service(repository=repo, lms=lms)

    envelope = service.create_commitment(
        meta=_meta(),
        description="Ship the release (duplicate)",
    )

    assert envelope.ok
    result = envelope.payload.value
    assert result.creation_proposal is not None
    assert result.creation_proposal.matched_commitment_id == existing.id
    assert result.creation_proposal.dedupe_confidence == 0.95
    assert result.creation_proposal.match_summary == "Same obligation"
    assert result.commitment is None
    assert len(lms.calls) == 1


def test_dedupe_allows_creation_below_threshold() -> None:
    repo = _FakeRepository()
    now = datetime.now(UTC)
    repo.create_commitment(
        description="Ship the release",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )
    lms = _FakeLmsService(
        response_text='{"duplicate_commitment_id": null, "confidence": 0.3, "summary": "somewhat related"}'
    )
    service, _repo, _jobs, _attention = _service(repository=repo, lms=lms)

    envelope = service.create_commitment(
        meta=_meta(),
        description="Different work",
    )

    assert envelope.ok
    assert envelope.payload.value.commitment is not None
    assert envelope.payload.value.creation_proposal is None


def test_dedupe_skipped_when_lms_unavailable() -> None:
    service, repo, _jobs, _attention = _service(lms=None)

    envelope = service.create_commitment(
        meta=_meta(),
        description="No LMS available",
    )

    assert envelope.ok
    assert envelope.payload.value.commitment is not None


def test_dedupe_skipped_when_disabled() -> None:
    lms = _FakeLmsService()
    settings = CommitmentServiceSettings(dedupe_enabled=False)
    service, _repo, _jobs, _attention = _service(lms=lms, settings=settings)

    envelope = service.create_commitment(
        meta=_meta(),
        description="Dedupe disabled",
    )

    assert envelope.ok
    assert envelope.payload.value.commitment is not None
    assert len(lms.calls) == 0


def test_dedupe_graceful_on_lms_error() -> None:
    repo = _FakeRepository()
    now = datetime.now(UTC)
    repo.create_commitment(
        description="Existing",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )
    lms = _FakeLmsService(fail=True)
    service, _repo, _jobs, _attention = _service(repository=repo, lms=lms)

    envelope = service.create_commitment(
        meta=_meta(),
        description="LMS fails gracefully",
    )

    assert envelope.ok
    assert envelope.payload.value.commitment is not None


def test_approve_dedupe_proposal_creates_commitment() -> None:
    repo = _FakeRepository()
    now = datetime.now(UTC)
    existing = repo.create_commitment(
        description="Ship the release",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source=None,
        due_by=None,
        due_timezone=None,
        importance=2,
        effort_provided=2,
        effort_inferred=None,
        urgency=40,
        created_at=now,
    )
    lms = _FakeLmsService(
        response_text=json.dumps(
            {
                "duplicate_commitment_id": existing.id,
                "confidence": 0.95,
                "summary": "Same thing",
            }
        )
    )
    service, _repo, _jobs, _attention = _service(repository=repo, lms=lms)

    create_env = service.create_commitment(
        meta=_meta(),
        description="Ship the release again",
    )
    assert create_env.ok
    proposal_id = create_env.payload.value.creation_proposal.id

    approve_env = service.apply_creation_proposal_decision(
        meta=_meta(),
        proposal_id=proposal_id,
        decision="approve",
        decided_by="operator",
    )

    assert approve_env.ok
    result = approve_env.payload.value
    assert result.commitment is not None
    assert result.commitment.description == "Ship the release again"
    assert result.creation_proposal.status == ProposalStatus.APPROVED
