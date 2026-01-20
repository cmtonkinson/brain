"""Provider-agnostic scheduler adapter interface and payload definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class SchedulerAdapterError(Exception):
    """Raised when a scheduler adapter operation fails."""

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize the adapter error with structured metadata."""
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class AdapterHealth:
    """Adapter health snapshot for readiness checks."""

    status: str
    message: str


@dataclass(frozen=True)
class ScheduleDefinition:
    """Typed schedule definition fields for adapter translation."""

    run_at: datetime | None = None
    interval_count: int | None = None
    interval_unit: str | None = None
    anchor_at: datetime | None = None
    rrule: str | None = None
    calendar_anchor_at: datetime | None = None
    predicate_subject: str | None = None
    predicate_operator: str | None = None
    predicate_value: str | int | float | None = None
    evaluation_interval_count: int | None = None
    evaluation_interval_unit: str | None = None


@dataclass(frozen=True)
class SchedulePayload:
    """Provider-agnostic schedule payload for adapter registration."""

    schedule_id: int
    schedule_type: str
    timezone: str
    definition: ScheduleDefinition


class SchedulerAdapter(Protocol):
    """Protocol for scheduler adapter implementations."""

    def register_schedule(self, payload: SchedulePayload) -> None:
        """Register a schedule with the provider."""
        ...

    def update_schedule(self, payload: SchedulePayload) -> None:
        """Update a schedule with the provider."""
        ...

    def pause_schedule(self, schedule_id: int) -> None:
        """Pause a provider schedule without deleting it."""
        ...

    def resume_schedule(self, schedule_id: int) -> None:
        """Resume a paused provider schedule."""
        ...

    def delete_schedule(self, schedule_id: int) -> None:
        """Delete a schedule from the provider."""
        ...

    def trigger_callback(self, schedule_id: int, scheduled_for: datetime) -> None:
        """Trigger a callback execution for the schedule."""
        ...

    def check_health(self) -> AdapterHealth:
        """Return adapter readiness health information."""
        ...
