"""Unit tests for daily batch reminder schedule setup."""

from __future__ import annotations

from datetime import datetime, timezone

from commitments.daily_batch_scheduler import schedule_daily_batch_reminder
from config import settings


class _AdapterStub:
    """Scheduler adapter stub capturing schedule payloads."""

    def __init__(self) -> None:
        self.payloads = []

    def register_schedule(self, payload) -> None:
        """Capture registered schedule payloads."""
        self.payloads.append(payload)

    def update_schedule(self, payload) -> None:
        """No-op update handler."""
        self.payloads.append(payload)

    def pause_schedule(self, schedule_id: int) -> None:
        """No-op pause handler."""
        return None

    def resume_schedule(self, schedule_id: int) -> None:
        """No-op resume handler."""
        return None

    def delete_schedule(self, schedule_id: int) -> None:
        """No-op delete handler."""
        return None

    def trigger_callback(
        self, schedule_id: int, scheduled_for, trigger_source: str = "scheduler_callback"
    ) -> None:
        """No-op trigger handler."""
        return None


def test_daily_batch_scheduler_uses_defaults(monkeypatch, sqlite_session_factory) -> None:
    """Defaults should schedule a daily batch at 06:00."""
    adapter = _AdapterStub()
    monkeypatch.setattr(settings.commitments, "batch_reminder_time", "06:00", raising=False)
    monkeypatch.setattr(settings.user, "timezone", "America/New_York", raising=False)

    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    result = schedule_daily_batch_reminder(
        session_factory=sqlite_session_factory,
        adapter=adapter,
        now_provider=lambda: now,
    )

    assert result.schedule.definition.rrule == "FREQ=DAILY;BYHOUR=6;BYMINUTE=0"
    assert result.schedule.timezone == settings.user.timezone
    assert adapter.payloads[0].definition.rrule == result.schedule.definition.rrule


def test_daily_batch_scheduler_uses_configured_time(monkeypatch, sqlite_session_factory) -> None:
    """Configured time should apply to the RRULE definition."""
    adapter = _AdapterStub()
    monkeypatch.setattr(settings.commitments, "batch_reminder_time", "14:15", raising=False)
    monkeypatch.setattr(settings.user, "timezone", "America/New_York", raising=False)

    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    result = schedule_daily_batch_reminder(
        session_factory=sqlite_session_factory,
        adapter=adapter,
        now_provider=lambda: now,
    )

    assert result.schedule.definition.rrule == "FREQ=DAILY;BYHOUR=14;BYMINUTE=15"
    assert result.schedule.timezone == settings.user.timezone
