"""Postgres-backed Celery Beat client that manages periodic entries via SQLAlchemy."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from celery import Celery
from sqlalchemy import select

from celery_sqlalchemy_v2_scheduler import models
from celery_sqlalchemy_v2_scheduler.session import SessionManager, session_cleanup

from scheduler.adapters.celery_adapter import (
    CeleryBeatEntry,
    CeleryCrontabSchedule,
    CeleryEtaSchedule,
    CeleryIntervalSchedule,
    CelerySchedulerClient,
    SchedulerAdapterError,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_SESSION_MANAGER = SessionManager()


class CelerySqlAlchemySchedulerClient(CelerySchedulerClient):
    """Celery Beat client implemented with celery_sqlalchemy_v2_scheduler."""

    def __init__(
        self,
        *,
        celery_app: Celery,
        callback_task_name: str,
        db_uri: str,
        queue_name: str | None = None,
        session_manager_override: SessionManager | None = None,
    ) -> None:
        self._celery_app = celery_app
        self._callback_task_name = callback_task_name
        self._db_uri = db_uri
        self._queue_name = queue_name
        self._session_manager = session_manager_override or DEFAULT_SESSION_MANAGER

    def register_entry(self, entry: CeleryBeatEntry) -> None:
        """Create or replace the periodic task entry for the schedule."""
        self._save_entry(entry)

    def update_entry(self, entry: CeleryBeatEntry) -> None:
        """Update the periodic task entry for the schedule."""
        self._save_entry(entry)

    def pause_entry(self, entry_name: str) -> None:
        """Mark the beat entry as disabled."""
        self._set_enabled(entry_name, False)

    def resume_entry(self, entry_name: str) -> None:
        """Enable a previously paused beat entry."""
        self._set_enabled(entry_name, True)

    def delete_entry(self, entry_name: str) -> None:
        """Delete the beat entry from the database."""
        try:
            session = self._session_manager.session_factory(self._db_uri)
            with session_cleanup(session):
                entry = self._find_entry(session, entry_name)
                session.delete(entry)
                session.commit()
        except SchedulerAdapterError:
            raise
        except Exception as exc:
            LOGGER.exception("Failed to delete beat entry: %s", entry_name)
            raise SchedulerAdapterError(
                "beat_entry_delete_failed",
                "Could not delete the Celery beat entry.",
                {"entry_name": entry_name},
            ) from exc

    def enqueue_callback(
        self,
        payload: object,
        *,
        eta: datetime,
        queue_name: str | None,
    ) -> None:
        """Enqueue a calendar callback task (run_now or retry)."""
        if not isinstance(payload, dict) and hasattr(payload, "__dict__"):
            payload_data = dict(payload.__dict__)
        else:
            payload_data = dict(payload or {})
        scheduled_for = payload_data.get("scheduled_for")
        if isinstance(scheduled_for, datetime):
            scheduled_for = scheduled_for.isoformat()

        kwargs = {
            "scheduled_for": scheduled_for,
            "trigger_source": payload_data.get("trigger_source"),
        }
        trace_id = payload_data.get("trace_id")
        if trace_id:
            kwargs["trace_id"] = trace_id

        self._celery_app.send_task(
            self._callback_task_name,
            args=(payload_data.get("schedule_id"),),
            kwargs=kwargs,
            eta=eta,
            queue=queue_name or self._queue_name,
        )

    def check_health(self) -> bool:
        """Verify the scheduler database is reachable."""
        try:
            session = self._session_manager.session_factory(self._db_uri)
            with session_cleanup(session):
                session.execute(select(1))
            return True
        except Exception:
            LOGGER.exception("Scheduler client health check failed.")
            return False

    def _save_entry(self, entry: CeleryBeatEntry) -> None:
        """Create or update the beat entry in the scheduler tables."""
        try:
            session = self._session_manager.session_factory(self._db_uri)
            with session_cleanup(session):
                task = session.execute(
                    select(models.PeriodicTask).filter_by(name=entry.name)
                ).scalar_one_or_none()
                if task is None:
                    task = models.PeriodicTask(name=entry.name)
                    session.add(task)
                self._apply_entry(session, task, entry)
                session.commit()
        except Exception as exc:
            LOGGER.exception("Failed to persist beat entry: %s", entry.name)
            raise SchedulerAdapterError(
                "beat_entry_persistence_failed",
                "Failed to persist Celery beat entry.",
                {"entry_name": entry.name},
            ) from exc

    def _apply_entry(self, session: Any, task: models.PeriodicTask, entry: CeleryBeatEntry) -> None:
        """Populate the periodic task model with the adapter entry data."""
        task.task = entry.task
        task.args = json.dumps(list(entry.args), default=_json_default)
        task.kwargs = json.dumps(entry.kwargs or {}, default=_json_default)
        task.enabled = entry.enabled
        task.queue = entry.options.get("queue")
        task.exchange = entry.options.get("exchange")
        task.routing_key = entry.options.get("routing_key")
        task.priority = entry.options.get("priority")
        task.expires = _normalize_expires(entry.options.get("expires"))
        task.description = entry.options.get("description") or ""
        self._attach_schedule(session, task, entry.schedule)

    def _attach_schedule(
        self,
        session: Any,
        task: models.PeriodicTask,
        schedule: CeleryIntervalSchedule | CeleryCrontabSchedule | CeleryEtaSchedule,
    ) -> None:
        """Associate the correct schedule object for the beat entry."""
        task.interval = None
        task.crontab = None
        task.solar = None
        task.one_off = False
        task.start_time = None

        if isinstance(schedule, CeleryEtaSchedule):
            task.interval = _find_or_create_interval(session, 0, "seconds")
            task.one_off = True
            task.start_time = schedule.eta
        elif isinstance(schedule, CeleryIntervalSchedule):
            task.interval = _find_or_create_interval(session, schedule.every, schedule.period)
            task.start_time = schedule.anchor_at
        elif isinstance(schedule, CeleryCrontabSchedule):
            task.crontab = _find_or_create_crontab(session, schedule)
        else:
            raise SchedulerAdapterError(
                "unsupported_schedule_payload",
                "Celery schedule payload is not supported.",
                {"schedule": type(schedule).__name__},
            )

    def _set_enabled(self, entry_name: str, enabled: bool) -> None:
        """Enable or disable a beat entry."""
        try:
            session = self._session_manager.session_factory(self._db_uri)
            with session_cleanup(session):
                task = self._find_entry(session, entry_name)
                task.enabled = enabled
                session.commit()
        except SchedulerAdapterError:
            raise
        except Exception as exc:
            LOGGER.exception("Failed to update enabled state for %s", entry_name)
            raise SchedulerAdapterError(
                "beat_entry_update_failed",
                "Could not update beat entry state.",
                {"entry_name": entry_name},
            ) from exc

    def _find_entry(self, session: Any, entry_name: str) -> models.PeriodicTask:
        """Load the periodic task model for the entry name."""
        task = session.execute(
            select(models.PeriodicTask).filter_by(name=entry_name)
        ).scalar_one_or_none()
        if task is None:
            raise SchedulerAdapterError(
                "beat_entry_not_found",
                "Celery beat entry not found.",
                {"entry_name": entry_name},
            )
        return task


def _normalize_expires(value: Any) -> datetime | None:
    """Normalize expires to a timezone-aware datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, timedelta):
        return datetime.now(timezone.utc) + value
    if isinstance(value, int):
        return datetime.now(timezone.utc) + timedelta(seconds=value)
    return None


def _find_or_create_interval(
    session: Any,
    every: int,
    period: str,
) -> models.IntervalSchedule:
    """Find or create an interval schedule."""
    stmt = select(models.IntervalSchedule).filter_by(every=every, period=period)
    interval = session.execute(stmt).scalar_one_or_none()
    if interval is None:
        interval = models.IntervalSchedule(every=every, period=period)
        session.add(interval)
    return interval


def _find_or_create_crontab(
    session: Any,
    schedule: CeleryCrontabSchedule,
) -> models.CrontabSchedule:
    """Find or create a crontab schedule."""
    stmt = select(models.CrontabSchedule).filter_by(
        minute=schedule.minute,
        hour=schedule.hour,
        day_of_week=schedule.day_of_week,
        day_of_month=schedule.day_of_month,
        month_of_year=schedule.month_of_year,
        timezone="UTC",
    )
    crontab = session.execute(stmt).scalar_one_or_none()
    if crontab is None:
        crontab = models.CrontabSchedule(
            minute=schedule.minute,
            hour=schedule.hour,
            day_of_week=schedule.day_of_week,
            day_of_month=schedule.day_of_month,
            month_of_year=schedule.month_of_year,
            timezone="UTC",
        )
        session.add(crontab)
    return crontab


def _json_default(value: Any) -> Any:
    """JSON serializer helper for dates and tuples."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return list(value)
    raise TypeError(f"Type {type(value).__name__} is not JSON serializable")
