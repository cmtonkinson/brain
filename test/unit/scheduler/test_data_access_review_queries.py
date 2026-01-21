"""Unit tests for review detection queries (Task 48)."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from scheduler.data_access import (
    ActorContext,
    ScheduleCreateInput,
    ScheduleDefinitionInput,
    create_schedule,
    create_task_intent,
    get_failing_schedules,
    get_ignored_schedules,
    get_orphaned_schedules,
    TaskIntentInput,
    update_schedule,
    ScheduleUpdateInput,
)


def _actor_context() -> ActorContext:
    """Return a default actor context."""
    return ActorContext(
        actor_type="system",
        actor_id="test-runner",
        channel="test",
        trace_id="trace-test-review",
    )


def test_get_orphaned_schedules_identifies_stale_active_tasks(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure orphans are identified based on next_run_at lag."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc)
    grace_period = timedelta(hours=24)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Orphan Check"), actor)

        # 1. Orphaned
        # Created 3 days ago, scheduled for 25h ago (valid at creation), now overdue > 24h
        orphaned = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now - timedelta(hours=25)),
                next_run_at=now - timedelta(hours=25),
            ),
            actor,
            now=now - timedelta(days=3),
        )
        orphaned_id = orphaned.id

        # 2. Not Orphaned: Active + next_run_at within 24h
        # Created 2 days ago, scheduled for 23h ago (valid at creation), overdue but < 24h
        valid_active = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now - timedelta(hours=23)),
                next_run_at=now - timedelta(hours=23),
            ),
            actor,
            now=now - timedelta(days=2),
        )
        valid_active_id = valid_active.id

        # 3. Not Orphaned: Paused
        # Created 3 days ago, scheduled for 48h ago
        paused = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now - timedelta(hours=48)),
                next_run_at=now - timedelta(hours=48),
                state="paused",
            ),
            actor,
            now=now - timedelta(days=3),
        )
        paused_id = paused.id

        # 4. Not Orphaned: Currently Running
        running = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now - timedelta(hours=30)),
                next_run_at=now - timedelta(hours=30),
            ),
            actor,
            now=now - timedelta(days=3),
        )
        # Manually set running status
        session.query(type(running)).filter_by(id=running.id).update(
            {"last_run_status": "running"}
        )
        running_id = running.id

        session.commit()

        results = get_orphaned_schedules(session, grace_period, now=now)
        result_ids = {s.id for s in results}

    assert orphaned_id in result_ids
    assert valid_active_id not in result_ids
    assert paused_id not in result_ids
    assert running_id not in result_ids


def test_get_failing_schedules_identifies_repeated_failures(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure schedules with excessive failure counts are flagged."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc)
    threshold = 3
    stale_age = timedelta(days=7)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Failure Check"), actor)

        # 1. Failing
        failing_count = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
        )
        failing_count_id = failing_count.id
        update_schedule(
            session,
            failing_count.id,
            ScheduleUpdateInput(
                last_run_status="failed",
                failure_count=3,
                last_run_at=now,
            ),
            actor,
        )

        # 2. Not Failing
        recovering = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
        )
        recovering_id = recovering.id
        update_schedule(
            session,
            recovering.id,
            ScheduleUpdateInput(
                last_run_status="failed",
                failure_count=2,
                last_run_at=now,
            ),
            actor,
        )

        # 3. Not Failing (Recovered)
        recovered = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
        )
        recovered_id = recovered.id
        update_schedule(
            session,
            recovered.id,
            ScheduleUpdateInput(
                last_run_status="succeeded",
                failure_count=10,
                last_run_at=now,
            ),
            actor,
        )

        session.commit()
        results = get_failing_schedules(session, threshold, stale_age, now=now)
        result_ids = {s.id for s in results}

    assert failing_count_id in result_ids
    assert recovering_id not in result_ids
    assert recovered_id not in result_ids


def test_get_failing_schedules_identifies_stale_failures(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure schedules stuck in failure state for too long are flagged."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc)
    threshold = 3
    stale_age = timedelta(days=7)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Stale Failure"), actor)

        # 1. Failing
        stale_fail = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
        )
        stale_fail_id = stale_fail.id
        update_schedule(
            session,
            stale_fail.id,
            ScheduleUpdateInput(
                last_run_status="failed",
                failure_count=1,
                last_run_at=now - timedelta(days=8),
            ),
            actor,
        )

        # 2. Not Failing
        recent_fail = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
        )
        recent_fail_id = recent_fail.id
        update_schedule(
            session,
            recent_fail.id,
            ScheduleUpdateInput(
                last_run_status="failed",
                failure_count=1,
                last_run_at=now - timedelta(days=6),
            ),
            actor,
        )

        session.commit()
        results = get_failing_schedules(session, threshold, stale_age, now=now)
        result_ids = {s.id for s in results}

    assert stale_fail_id in result_ids
    assert recent_fail_id not in result_ids


def test_get_ignored_schedules_identifies_stale_paused_tasks(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure paused schedules untouched for long periods are flagged."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc)
    ignored_age = timedelta(days=30)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Ignored Check"), actor)

        # 1. Ignored
        ignored = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now),
                state="paused",
            ),
            actor,
            now=now - timedelta(days=31),
        )
        ignored_id = ignored.id

        # 2. Not Ignored
        recent_paused = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now),
                state="paused",
            ),
            actor,
            now=now - timedelta(days=10),
        )
        recent_paused_id = recent_paused.id

        # 3. Not Ignored (Active)
        active_old = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now),
                state="active",
            ),
            actor,
            now=now - timedelta(days=40),
        )
        active_old_id = active_old.id

        session.commit()
        results = get_ignored_schedules(session, ignored_age, now=now)
        result_ids = {s.id for s in results}

    assert ignored_id in result_ids
    assert recent_paused_id not in result_ids
    assert active_old_id not in result_ids
