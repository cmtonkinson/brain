"""Integration tests for schedule creation with inline task intent payloads."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from models import ScheduleAuditLog, TaskIntent
from scheduler.data_access import (
    ActorContext,
    ScheduleCreateWithIntentInput,
    ScheduleDefinitionInput,
    TaskIntentInput,
    create_schedule_with_intent,
)


def _actor_context() -> ActorContext:
    """Return a default actor context for schedule mutations."""
    return ActorContext(
        actor_type="human",
        actor_id="user-1",
        channel="signal",
        trace_id="trace-abc",
        request_id="req-123",
        reason="integration-test",
    )


def test_inline_schedule_creation_persists_intent_and_audit(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure inline intent creation persists task intents and schedule audits."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 5, 9, 30, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent, schedule = create_schedule_with_intent(
            session,
            ScheduleCreateWithIntentInput(
                task_intent=TaskIntentInput(
                    summary="Weekly review",
                    details="Summarize outstanding commitments.",
                    origin_reference="signal:thread-99",
                ),
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    interval_count=1,
                    interval_unit="week",
                ),
                next_run_at=now,
            ),
            actor,
            now=now,
        )
        session.commit()

        audit = session.query(ScheduleAuditLog).filter_by(schedule_id=schedule.id).one()
        stored_intent = session.get(TaskIntent, intent.id)

    assert stored_intent is not None
    assert stored_intent.summary == "Weekly review"
    assert schedule.task_intent_id == intent.id
    assert audit.task_intent_id == intent.id
    assert audit.actor_type == actor.actor_type
