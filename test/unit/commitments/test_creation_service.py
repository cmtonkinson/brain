"""Unit tests for commitment creation orchestration behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from commitments.creation_authority import CommitmentCreationSource
from commitments.creation_types import ValidationError
from commitments.creation_service import (
    CommitmentCreationRequest,
    CommitmentCreationService,
)
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.schedule_link_service import CommitmentScheduleLinkService
from commitments.urgency import compute_urgency
from models import Commitment, Schedule
from scheduler.adapter_interface import SchedulerAdapterError
from scheduler.schedule_service_interface import ScheduleAdapterSyncError
from test.helpers.scheduler_adapter_stub import RecordingSchedulerAdapter


@dataclass
class StubLLMClient:
    """Stub LLM client for deterministic dedupe responses."""

    response: str

    def complete_sync(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
        """Return the configured JSON response."""
        return self.response


class FailingSchedulerAdapter(RecordingSchedulerAdapter):
    """Scheduler adapter that fails to register schedules."""

    def register_schedule(self, payload) -> None:  # noqa: ANN001
        """Raise an error to simulate adapter sync failure."""
        raise SchedulerAdapterError("adapter_failure", "Adapter registration failed.")


def _count_commitments(factory: sessionmaker) -> int:
    """Return the total number of commitments stored."""
    with factory() as session:
        return int(session.query(Commitment).count())


def _find_any_schedule(factory: sessionmaker) -> Schedule | None:
    """Return any schedule stored in the database."""
    with factory() as session:
        return session.query(Schedule).first()


def test_creation_success_description_only(sqlite_session_factory: sessionmaker) -> None:
    """Description-only creation should persist without scheduling."""
    adapter = RecordingSchedulerAdapter()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    service = CommitmentCreationService(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )

    result = service.create(
        CommitmentCreationRequest(
            payload={"description": "Plan quarterly review"},
            source=CommitmentCreationSource.USER,
        )
    )

    assert result.status == "success"
    assert result.schedule_id is None
    repo = CommitmentRepository(sqlite_session_factory)
    stored = repo.get_by_id(result.commitment.commitment_id)
    assert stored is not None
    expected_urgency = compute_urgency(2, 2, None, now)
    assert stored.urgency == expected_urgency


def test_creation_with_due_by_creates_schedule(sqlite_session_factory: sessionmaker) -> None:
    """due_by inputs should trigger miss detection schedule creation."""
    adapter = RecordingSchedulerAdapter()
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=3)
    service = CommitmentCreationService(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )

    result = service.create(
        CommitmentCreationRequest(
            payload={"description": "Submit report", "due_by": due_by},
            source=CommitmentCreationSource.USER,
        )
    )

    assert result.status == "success"
    assert result.schedule_id is not None
    link_service = CommitmentScheduleLinkService(sqlite_session_factory)
    assert (
        link_service.get_active_schedule_id(result.commitment.commitment_id) == result.schedule_id
    )


def test_validation_error_halts_creation(sqlite_session_factory: sessionmaker) -> None:
    """Validation errors should raise and avoid persistence."""
    adapter = RecordingSchedulerAdapter()
    service = CommitmentCreationService(sqlite_session_factory, adapter)

    with pytest.raises(ValidationError):
        service.create(
            CommitmentCreationRequest(
                payload={},
                source=CommitmentCreationSource.USER,
            )
        )

    assert _count_commitments(sqlite_session_factory) == 0


def test_dedupe_proposal_halts_creation(sqlite_session_factory: sessionmaker) -> None:
    """Dedupe proposals should block persistence."""
    repo = CommitmentRepository(sqlite_session_factory)
    existing = repo.create(CommitmentCreateInput(description="Book dentist appointment"))
    client = StubLLMClient(
        response=(
            '{"duplicate_commitment_id": %d, "confidence": 0.9, "summary": "Duplicate"}'
            % existing.commitment_id
        )
    )
    adapter = RecordingSchedulerAdapter()
    service = CommitmentCreationService(
        sqlite_session_factory,
        adapter,
        llm_client=client,
    )

    result = service.create(
        CommitmentCreationRequest(
            payload={"description": "Schedule dentist visit"},
            source=CommitmentCreationSource.USER,
        )
    )

    assert result.status == "dedupe_required"
    assert _count_commitments(sqlite_session_factory) == 1


def test_authority_proposal_halts_creation(sqlite_session_factory: sessionmaker) -> None:
    """Agent-suggested commitments should require approval by default."""
    adapter = RecordingSchedulerAdapter()
    service = CommitmentCreationService(sqlite_session_factory, adapter)

    result = service.create(
        CommitmentCreationRequest(
            payload={"description": "Agent suggestion"},
            source=CommitmentCreationSource.AGENT,
            confidence=0.0,
        )
    )

    assert result.status == "approval_required"
    assert _count_commitments(sqlite_session_factory) == 0


def test_schedule_failure_rolls_back_commitment(sqlite_session_factory: sessionmaker) -> None:
    """Schedule creation failures should remove the commitment."""
    adapter = FailingSchedulerAdapter()
    now = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    service = CommitmentCreationService(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )

    with pytest.raises(ScheduleAdapterSyncError):
        service.create(
            CommitmentCreationRequest(
                payload={"description": "Fail schedule", "due_by": due_by},
                source=CommitmentCreationSource.USER,
            )
        )

    assert _count_commitments(sqlite_session_factory) == 0
    schedule = _find_any_schedule(sqlite_session_factory)
    if schedule is not None:
        assert schedule.state == "canceled"
