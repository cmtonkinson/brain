"""Miss detection schedule creation and maintenance for commitments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session
from scheduler.adapter_interface import SchedulerAdapter
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleCreateRequest,
    ScheduleDeleteRequest,
    ScheduleDefinitionInput,
    ScheduleMutationResult,
    ScheduleUpdateRequest,
    TaskIntentInput,
)
from time_utils import get_local_timezone, to_local

from commitments.repository import CommitmentRepository
from commitments.schedule_link_service import CommitmentScheduleLinkService


@dataclass(frozen=True)
class MissDetectionScheduleResult:
    """Result for miss detection schedule operations."""

    schedule_id: int | None


class MissDetectionScheduleService:
    """Service to create, update, and remove miss detection schedules."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        adapter: SchedulerAdapter,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the miss detection scheduling service."""
        self._session_factory = session_factory
        self._adapter = adapter
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._schedule_service = ScheduleCommandServiceImpl(
            session_factory,
            adapter,
            now_provider=self._now_provider,
        )
        self._link_service = CommitmentScheduleLinkService(session_factory)
        self._commitment_repo = CommitmentRepository(session_factory)

    def ensure_schedule(
        self,
        *,
        commitment_id: int,
        due_by: datetime | None,
    ) -> MissDetectionScheduleResult:
        """Create, update, or remove the miss detection schedule based on due_by."""
        if due_by is None:
            self.remove_schedule(commitment_id=commitment_id, reason="due_by_removed")
            return MissDetectionScheduleResult(schedule_id=None)

        schedule_id = self._link_service.get_active_schedule_id(commitment_id)
        if schedule_id is None:
            return self.create_schedule(commitment_id=commitment_id, due_by=due_by)

        self.update_schedule(schedule_id=schedule_id, due_by=due_by)
        return MissDetectionScheduleResult(schedule_id=schedule_id)

    def create_schedule(
        self,
        *,
        commitment_id: int,
        due_by: datetime,
    ) -> MissDetectionScheduleResult:
        """Create a miss detection schedule and link it to the commitment."""
        commitment = self._commitment_repo.get_by_id(commitment_id)
        if commitment is None:
            raise ValueError(f"Commitment not found: {commitment_id}")

        run_at = _normalize_run_at(due_by)
        request = ScheduleCreateRequest(
            task_intent=TaskIntentInput(
                summary=f"Miss detection for commitment {commitment_id}",
                details=commitment.description,
                origin_reference=f"commitments.miss_detection:{commitment_id}",
            ),
            schedule_type="one_time",
            timezone=get_local_timezone().key,
            definition=ScheduleDefinitionInput(run_at=run_at),
        )
        actor = _default_actor(trace_id=f"commitments.miss_detection:{commitment_id}")
        result = self._schedule_service.create_schedule(request, actor)
        self._link_service.create_link(
            commitment_id=commitment_id,
            schedule_id=result.schedule.id,
            now=self._now_provider(),
        )
        return MissDetectionScheduleResult(schedule_id=result.schedule.id)

    def update_schedule(
        self,
        *,
        schedule_id: int,
        due_by: datetime,
    ) -> ScheduleMutationResult:
        """Update the run_at time for an existing miss detection schedule."""
        run_at = _normalize_run_at(due_by)
        request = ScheduleUpdateRequest(
            schedule_id=schedule_id,
            definition=ScheduleDefinitionInput(run_at=run_at),
        )
        actor = _default_actor(trace_id=f"commitments.miss_detection:update:{schedule_id}")
        return self._schedule_service.update_schedule(request, actor)

    def remove_schedule(
        self,
        *,
        commitment_id: int,
        reason: str,
    ) -> MissDetectionScheduleResult:
        """Remove the miss detection schedule and deactivate its link."""
        schedule_id = self._link_service.get_active_schedule_id(commitment_id)
        if schedule_id is None:
            return MissDetectionScheduleResult(schedule_id=None)

        request = ScheduleDeleteRequest(schedule_id=schedule_id, reason=reason)
        actor = _default_actor(trace_id=f"commitments.miss_detection:delete:{commitment_id}")
        self._schedule_service.delete_schedule(request, actor)
        self._link_service.deactivate_link(
            commitment_id=commitment_id,
            schedule_id=schedule_id,
            now=self._now_provider(),
        )
        return MissDetectionScheduleResult(schedule_id=schedule_id)


def _default_actor(*, trace_id: str) -> ActorContext:
    """Build the default actor context for miss detection scheduling."""
    return ActorContext(
        actor_type="system",
        actor_id=None,
        channel="system",
        trace_id=trace_id,
        reason="miss_detection_schedule",
    )


def _normalize_run_at(value: datetime) -> datetime:
    """Normalize run_at using the operator timezone."""
    local_value = to_local(value)
    if local_value.tzinfo is None:
        return local_value.replace(tzinfo=get_local_timezone())
    return local_value


__all__ = [
    "MissDetectionScheduleResult",
    "MissDetectionScheduleService",
]
