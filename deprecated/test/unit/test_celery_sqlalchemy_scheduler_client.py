"""Unit tests for the SQLAlchemy-based Celery scheduler client."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from celery_sqlalchemy_v2_scheduler import models
from celery_sqlalchemy_v2_scheduler.session import SessionManager, session_cleanup
from sqlalchemy import select

from scheduler.adapters.celery_adapter import (
    CeleryBeatEntry,
    CeleryCallbackPayload,
    CeleryEtaSchedule,
    CeleryIntervalSchedule,
)
from scheduler.adapters.celery_sqlalchemy_scheduler_client import CelerySqlAlchemySchedulerClient


class _StubCeleryApp:
    """Captures send_task calls for enqueue_callback assertions."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_task(
        self,
        name: str,
        *,
        args: tuple | list | None = None,
        kwargs: dict | None = None,
        eta: datetime | None = None,
        queue: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "name": name,
                "args": tuple(args or ()),
                "kwargs": dict(kwargs or {}),
                "eta": eta,
                "queue": queue,
            }
        )


def _sqlite_uri(tmp_path):
    return f"sqlite:///{tmp_path / 'scheduler.db'}"


def _build_client(tmp_path, celery_app=None):
    app = celery_app or _StubCeleryApp()
    manager = SessionManager()
    db_uri = _sqlite_uri(tmp_path)
    client = CelerySqlAlchemySchedulerClient(
        celery_app=app,
        callback_task_name="scheduler.dispatch",
        db_uri=db_uri,
        queue_name="scheduler",
        session_manager_override=manager,
    )
    return client, manager, db_uri


def _load_task_snapshot(manager: SessionManager, db_uri: str, name: str) -> dict[str, Any] | None:
    session = manager.session_factory(db_uri)
    with session_cleanup(session):
        task = session.execute(
            select(models.PeriodicTask).filter_by(name=name)
        ).scalar_one_or_none()
        if task is None:
            return None
        return {
            "enabled": bool(task.enabled),
            "one_off": bool(task.one_off),
            "interval_every": task.interval.every if task.interval else None,
            "start_time": task.start_time,
        }


def test_register_interval_schedule_persists_entry(tmp_path) -> None:
    client, manager, db_uri = _build_client(tmp_path)
    entry = CeleryBeatEntry(
        name="schedule:10",
        task="scheduler.dispatch",
        schedule=CeleryIntervalSchedule(every=2, period="minutes"),
        args=(),
        kwargs={"schedule_id": 10, "scheduled_for": None, "trigger_source": "scheduler_callback"},
        options={"queue": "scheduler"},
        enabled=True,
    )

    client.register_entry(entry)

    snapshot = _load_task_snapshot(manager, db_uri, entry.name)
    assert snapshot is not None
    assert snapshot["enabled"]
    assert not snapshot["one_off"]


def test_register_one_time_schedule_sets_one_off(tmp_path) -> None:
    client, manager, db_uri = _build_client(tmp_path)
    run_at = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    entry = CeleryBeatEntry(
        name="schedule:one",
        task="scheduler.dispatch",
        schedule=CeleryEtaSchedule(eta=run_at),
        args=(),
        kwargs={"schedule_id": 1, "scheduled_for": run_at, "trigger_source": "scheduler_callback"},
        options={"queue": "scheduler"},
        enabled=True,
    )

    client.register_entry(entry)

    snapshot = _load_task_snapshot(manager, db_uri, entry.name)
    assert snapshot is not None
    assert snapshot["one_off"]
    assert snapshot["start_time"] == run_at.replace(tzinfo=None)


def test_pause_and_resume_toggle_enabled_state(tmp_path) -> None:
    client, manager, db_uri = _build_client(tmp_path)
    entry = CeleryBeatEntry(
        name="schedule:pause",
        task="scheduler.dispatch",
        schedule=CeleryIntervalSchedule(every=1, period="hours"),
        args=(),
        kwargs={"schedule_id": 42, "scheduled_for": None, "trigger_source": "scheduler_callback"},
        options={},
        enabled=True,
    )
    client.register_entry(entry)
    client.pause_entry(entry.name)

    snapshot = _load_task_snapshot(manager, db_uri, entry.name)
    assert snapshot is not None
    assert not snapshot["enabled"]

    client.resume_entry(entry.name)
    snapshot = _load_task_snapshot(manager, db_uri, entry.name)
    assert snapshot is not None
    assert snapshot["enabled"]


def test_delete_entry_removes_record(tmp_path) -> None:
    client, manager, db_uri = _build_client(tmp_path)
    entry = CeleryBeatEntry(
        name="schedule:delete",
        task="scheduler.dispatch",
        schedule=CeleryIntervalSchedule(every=3, period="minutes"),
        args=(),
        kwargs={"schedule_id": 9, "scheduled_for": None, "trigger_source": "scheduler_callback"},
        options={},
        enabled=True,
    )
    client.register_entry(entry)

    client.delete_entry(entry.name)
    assert _load_task_snapshot(manager, db_uri, entry.name) is None


def test_enqueue_callback_uses_celery_app(tmp_path) -> None:
    stub = _StubCeleryApp()
    client, _, _ = _build_client(tmp_path, celery_app=stub)
    payload = CeleryCallbackPayload(
        schedule_id=7,
        scheduled_for=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        trace_id="trace-7",
        trigger_source="run_now",
    )

    eta = payload.scheduled_for
    client.enqueue_callback(payload, eta=eta, queue_name=None)

    assert stub.calls
    call = stub.calls[0]
    assert call["name"] == "scheduler.dispatch"
    assert call["queue"] == "scheduler"
    assert call["eta"] == eta
    assert call["args"] == (7,)
    kwargs = cast(dict[str, object], call["kwargs"])
    assert kwargs["trigger_source"] == "run_now"
    assert kwargs["trace_id"] == "trace-7"
    assert "scheduled_for" in kwargs
