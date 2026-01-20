"""Celery + Redis scheduler adapter implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from scheduler.adapter_interface import AdapterHealth, SchedulePayload, SchedulerAdapterError
from scheduler.schedule_validation import validate_schedule_definition, validate_timezone

_ALLOWED_SCHEDULE_TYPES = {"one_time", "interval", "calendar_rule", "conditional"}
_INTERVAL_UNITS = {
    "minute": "minutes",
    "hour": "hours",
    "day": "days",
    "week": "weeks",
}

# RRULE frequency to crontab field mapping
_RRULE_FREQ_MAP = {
    "MINUTELY": "minute",
    "HOURLY": "hour",
    "DAILY": "day",
    "WEEKLY": "week",
    "MONTHLY": "month",
    "YEARLY": "year",
}

# RRULE BYDAY to crontab day_of_week mapping (0=Monday in crontab)
_RRULE_DAY_MAP = {
    "MO": "1",
    "TU": "2",
    "WE": "3",
    "TH": "4",
    "FR": "5",
    "SA": "6",
    "SU": "0",
}


@dataclass(frozen=True)
class CeleryAdapterConfig:
    """Celery adapter configuration for callback dispatch."""

    callback_task_name: str
    evaluation_callback_task_name: str | None = None
    queue_name: str | None = None


@dataclass(frozen=True)
class CeleryIntervalSchedule:
    """Provider-specific interval schedule payload for Celery Beat."""

    every: int
    period: str
    anchor_at: datetime | None = None


@dataclass(frozen=True)
class CeleryEtaSchedule:
    """Provider-specific ETA schedule payload for Celery Beat."""

    eta: datetime


@dataclass(frozen=True)
class CeleryCrontabSchedule:
    """Provider-specific crontab schedule payload for Celery Beat.

    Maps RRULE calendar rules to Celery crontab parameters.
    Fields use crontab syntax: "*" means any/every.
    """

    minute: str = "0"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"


CelerySchedule = CeleryIntervalSchedule | CeleryEtaSchedule | CeleryCrontabSchedule


@dataclass(frozen=True)
class CeleryCallbackPayload:
    """Payload passed to Celery callback tasks."""

    schedule_id: int
    scheduled_for: datetime | None
    trace_id: str | None = None


@dataclass(frozen=True)
class CeleryBeatEntry:
    """Celery Beat entry definition for a scheduled callback."""

    name: str
    task: str
    schedule: CelerySchedule
    args: tuple[object, ...]
    kwargs: dict[str, object]
    options: dict[str, object]
    enabled: bool


class CelerySchedulerClient(Protocol):
    """Protocol for provider-specific Celery scheduling operations."""

    def register_entry(self, entry: CeleryBeatEntry) -> None:
        """Register a Celery Beat schedule entry."""
        ...

    def update_entry(self, entry: CeleryBeatEntry) -> None:
        """Update a Celery Beat schedule entry."""
        ...

    def pause_entry(self, entry_name: str) -> None:
        """Pause a Celery Beat schedule entry."""
        ...

    def resume_entry(self, entry_name: str) -> None:
        """Resume a Celery Beat schedule entry."""
        ...

    def delete_entry(self, entry_name: str) -> None:
        """Delete a Celery Beat schedule entry."""
        ...

    def enqueue_callback(
        self,
        payload: CeleryCallbackPayload,
        *,
        eta: datetime,
        queue_name: str | None,
    ) -> None:
        """Enqueue a Celery callback task at the requested eta."""
        ...

    def check_health(self) -> bool:
        """Return whether the Celery provider is reachable."""
        ...


class CelerySchedulerAdapter:
    """Celery + Redis adapter that translates schedules into provider entries."""

    def __init__(self, client: CelerySchedulerClient, config: CeleryAdapterConfig) -> None:
        """Initialize the adapter with a provider client and configuration."""
        self._client = client
        self._config = config

    def register_schedule(self, payload: SchedulePayload) -> None:
        """Register a schedule with Celery Beat."""
        entry = _build_beat_entry(payload, self._config)
        self._client.register_entry(entry)

    def update_schedule(self, payload: SchedulePayload) -> None:
        """Update a schedule registered with Celery Beat."""
        entry = _build_beat_entry(payload, self._config)
        self._client.update_entry(entry)

    def pause_schedule(self, schedule_id: int) -> None:
        """Pause a Celery Beat schedule entry."""
        self._client.pause_entry(_entry_name(schedule_id))

    def resume_schedule(self, schedule_id: int) -> None:
        """Resume a Celery Beat schedule entry."""
        self._client.resume_entry(_entry_name(schedule_id))

    def delete_schedule(self, schedule_id: int) -> None:
        """Delete a Celery Beat schedule entry."""
        self._client.delete_entry(_entry_name(schedule_id))

    def trigger_callback(
        self,
        schedule_id: int,
        scheduled_for: datetime,
        *,
        trace_id: str | None = None,
    ) -> None:
        """Trigger an immediate Celery callback execution."""
        eta = _ensure_aware(scheduled_for, timezone.utc)
        payload = CeleryCallbackPayload(
            schedule_id=schedule_id,
            scheduled_for=eta,
            trace_id=trace_id,
        )
        self._client.enqueue_callback(payload, eta=eta, queue_name=self._config.queue_name)

    def check_health(self) -> AdapterHealth:
        """Return adapter readiness status based on provider health."""
        healthy = self._client.check_health()
        if healthy:
            return AdapterHealth(status="ok", message="celery adapter ready")
        return AdapterHealth(status="unhealthy", message="celery adapter unavailable")


def _build_beat_entry(payload: SchedulePayload, config: CeleryAdapterConfig) -> CeleryBeatEntry:
    """Translate a schedule payload into a Celery Beat entry."""
    _validate_payload(payload)
    options: dict[str, object] = {}
    if config.queue_name:
        options["queue"] = config.queue_name

    schedule = _build_schedule(payload)
    kwargs = _build_callback_kwargs(payload, schedule)

    # Conditional schedules use the evaluation callback task for predicate evaluation
    task_name = config.callback_task_name
    if payload.schedule_type == "conditional":
        if config.evaluation_callback_task_name is None:
            raise SchedulerAdapterError(
                "missing_evaluation_callback_task",
                "evaluation_callback_task_name is required for conditional schedules.",
                {"schedule_id": payload.schedule_id},
            )
        task_name = config.evaluation_callback_task_name

    return CeleryBeatEntry(
        name=_entry_name(payload.schedule_id),
        task=task_name,
        schedule=schedule,
        args=(),
        kwargs=kwargs,
        options=options,
        enabled=True,
    )


def _build_schedule(payload: SchedulePayload) -> CelerySchedule:
    """Build the provider-specific schedule object from the payload."""
    if payload.schedule_type == "one_time":
        run_at = _normalize_run_at(payload)
        return CeleryEtaSchedule(eta=run_at)
    if payload.schedule_type == "interval":
        return _build_interval_schedule(payload)
    if payload.schedule_type == "calendar_rule":
        return _build_crontab_schedule(payload)
    if payload.schedule_type == "conditional":
        return _build_evaluation_interval_schedule(payload)
    raise SchedulerAdapterError(
        "unsupported_schedule_type",
        "Schedule type not supported by Celery adapter.",
        {"schedule_type": payload.schedule_type},
    )


def _build_interval_schedule(payload: SchedulePayload) -> CeleryIntervalSchedule:
    """Build a Celery interval schedule from the payload definition."""
    interval_count = payload.definition.interval_count
    interval_unit = payload.definition.interval_unit
    if interval_count is None or interval_count <= 0:
        raise SchedulerAdapterError(
            "invalid_interval_count",
            "interval_count must be provided and > 0.",
            {"interval_count": interval_count},
        )
    if interval_unit is None:
        raise SchedulerAdapterError(
            "invalid_interval_unit",
            "interval_unit is required for interval schedules.",
            {},
        )
    period = _INTERVAL_UNITS.get(interval_unit)
    if period is None:
        raise SchedulerAdapterError(
            "unsupported_interval_unit",
            "Interval unit not supported by Celery adapter.",
            {"interval_unit": interval_unit},
        )
    anchor_at = None
    if payload.definition.anchor_at is not None:
        anchor_at = _normalize_timestamp(payload.definition.anchor_at, payload.timezone)
    return CeleryIntervalSchedule(every=interval_count, period=period, anchor_at=anchor_at)


def _build_crontab_schedule(payload: SchedulePayload) -> CeleryCrontabSchedule:
    """Build a Celery crontab schedule from an RRULE definition.

    Maps RRULE fields to crontab parameters:
    - FREQ: Determines which crontab field to set
    - BYDAY: Maps to day_of_week
    - BYHOUR: Maps to hour
    - BYMINUTE: Maps to minute
    - BYMONTHDAY: Maps to day_of_month
    - BYMONTH: Maps to month_of_year
    - INTERVAL: Applied to the relevant frequency field
    """
    rrule = payload.definition.rrule
    if rrule is None:
        raise SchedulerAdapterError(
            "missing_rrule",
            "rrule is required for calendar_rule schedules.",
            {"schedule_id": payload.schedule_id},
        )

    parts = _parse_rrule_parts(rrule)
    freq = parts.get("FREQ")
    if freq is None:
        raise SchedulerAdapterError(
            "invalid_rrule",
            "RRULE must include FREQ.",
            {"rrule": rrule},
        )

    interval = int(parts.get("INTERVAL", "1"))

    # Default crontab fields
    minute = "0"
    hour = "*"
    day_of_week = "*"
    day_of_month = "*"
    month_of_year = "*"

    # Apply BYHOUR if present
    if "BYHOUR" in parts:
        hour = parts["BYHOUR"]

    # Apply BYMINUTE if present
    if "BYMINUTE" in parts:
        minute = parts["BYMINUTE"]

    # Apply BYDAY if present (day of week)
    if "BYDAY" in parts:
        day_of_week = _map_byday_to_crontab(parts["BYDAY"])

    # Apply BYMONTHDAY if present
    if "BYMONTHDAY" in parts:
        day_of_month = parts["BYMONTHDAY"]

    # Apply BYMONTH if present
    if "BYMONTH" in parts:
        month_of_year = parts["BYMONTH"]

    # Apply FREQ and INTERVAL to the appropriate field
    if freq == "MINUTELY":
        minute = f"*/{interval}" if interval > 1 else "*"
    elif freq == "HOURLY":
        if "BYMINUTE" not in parts:
            minute = "0"
        hour = f"*/{interval}" if interval > 1 else "*"
    elif freq == "DAILY":
        if "BYMINUTE" not in parts:
            minute = "0"
        if "BYHOUR" not in parts:
            hour = "0"
        if interval > 1:
            day_of_month = f"*/{interval}"
    elif freq == "WEEKLY":
        if "BYMINUTE" not in parts:
            minute = "0"
        if "BYHOUR" not in parts:
            hour = "0"
        # Weekly with interval > 1 is not directly supported by crontab
        # We approximate with day_of_week if BYDAY is not set
        if "BYDAY" not in parts:
            # Default to Monday for weekly without BYDAY
            day_of_week = "1"
    elif freq == "MONTHLY":
        if "BYMINUTE" not in parts:
            minute = "0"
        if "BYHOUR" not in parts:
            hour = "0"
        if "BYMONTHDAY" not in parts:
            day_of_month = "1"
        if interval > 1:
            month_of_year = f"*/{interval}"
    elif freq == "YEARLY":
        if "BYMINUTE" not in parts:
            minute = "0"
        if "BYHOUR" not in parts:
            hour = "0"
        if "BYMONTHDAY" not in parts:
            day_of_month = "1"
        if "BYMONTH" not in parts:
            month_of_year = "1"
    else:
        raise SchedulerAdapterError(
            "unsupported_rrule_freq",
            f"RRULE FREQ '{freq}' not supported by Celery adapter.",
            {"freq": freq},
        )

    return CeleryCrontabSchedule(
        minute=minute,
        hour=hour,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
    )


def _build_evaluation_interval_schedule(payload: SchedulePayload) -> CeleryIntervalSchedule:
    """Build a Celery interval schedule for conditional predicate evaluation cadence."""
    interval_count = payload.definition.evaluation_interval_count
    interval_unit = payload.definition.evaluation_interval_unit
    if interval_count is None or interval_count <= 0:
        raise SchedulerAdapterError(
            "invalid_evaluation_interval_count",
            "evaluation_interval_count must be provided and > 0 for conditional schedules.",
            {"evaluation_interval_count": interval_count},
        )
    if interval_unit is None:
        raise SchedulerAdapterError(
            "invalid_evaluation_interval_unit",
            "evaluation_interval_unit is required for conditional schedules.",
            {},
        )
    period = _INTERVAL_UNITS.get(interval_unit)
    if period is None:
        raise SchedulerAdapterError(
            "unsupported_evaluation_interval_unit",
            "Evaluation interval unit not supported by Celery adapter.",
            {"evaluation_interval_unit": interval_unit},
        )
    return CeleryIntervalSchedule(every=interval_count, period=period, anchor_at=None)


def _parse_rrule_parts(rrule: str) -> dict[str, str]:
    """Parse an RRULE string into key/value pairs."""
    parts: dict[str, str] = {}
    for segment in rrule.strip().split(";"):
        if not segment.strip():
            continue
        if "=" not in segment:
            continue
        key, value = segment.split("=", 1)
        parts[key.strip().upper()] = value.strip().upper()
    return parts


def _map_byday_to_crontab(byday: str) -> str:
    """Map RRULE BYDAY value to crontab day_of_week format.

    Handles single days (MO) and lists (MO,WE,FR).
    """
    days = []
    for day in byday.split(","):
        day = day.strip().upper()
        # Handle ordinal days like "1MO" (first Monday) - just extract the day
        if len(day) > 2 and day[-2:] in _RRULE_DAY_MAP:
            day = day[-2:]
        mapped = _RRULE_DAY_MAP.get(day)
        if mapped is not None:
            days.append(mapped)
    if days:
        return ",".join(days)
    return "*"


def _build_callback_kwargs(payload: SchedulePayload, schedule: CelerySchedule) -> dict[str, object]:
    """Return callback keyword arguments for Celery Beat entries."""
    scheduled_for: datetime | None = None
    if isinstance(schedule, CeleryEtaSchedule):
        scheduled_for = schedule.eta
    return {"schedule_id": payload.schedule_id, "scheduled_for": scheduled_for}


def _validate_payload(payload: SchedulePayload) -> None:
    """Validate schedule payload fields before translation."""
    if payload.schedule_type not in _ALLOWED_SCHEDULE_TYPES:
        raise SchedulerAdapterError(
            "unsupported_schedule_type",
            "Schedule type not supported by Celery adapter.",
            {"schedule_type": payload.schedule_type},
        )
    try:
        validate_timezone(payload.timezone)
    except Exception as exc:
        raise SchedulerAdapterError(
            "invalid_timezone",
            "Schedule timezone is invalid.",
            {"timezone": payload.timezone},
        ) from exc
    try:
        validate_schedule_definition(payload.schedule_type, payload.definition)
    except Exception as exc:
        raise SchedulerAdapterError(
            "invalid_schedule_definition",
            "Schedule definition failed validation.",
            {"schedule_type": payload.schedule_type},
        ) from exc


def _normalize_run_at(payload: SchedulePayload) -> datetime:
    """Normalize run_at into an aware datetime for Celery ETA usage."""
    run_at = payload.definition.run_at
    if run_at is None:
        raise SchedulerAdapterError(
            "missing_run_at",
            "run_at is required for one_time schedules.",
            {"schedule_id": payload.schedule_id},
        )
    return _normalize_timestamp(run_at, payload.timezone)


def _normalize_timestamp(value: datetime, timezone_name: str) -> datetime:
    """Return a timezone-aware datetime normalized to the schedule timezone."""
    tz = _load_timezone(timezone_name)
    return _ensure_aware(value, tz).astimezone(tz)


def _ensure_aware(value: datetime, tz: ZoneInfo) -> datetime:
    """Ensure a datetime is timezone-aware in the provided timezone."""
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _load_timezone(timezone_name: str) -> ZoneInfo:
    """Load a ZoneInfo instance or raise an adapter error."""
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise SchedulerAdapterError(
            "invalid_timezone",
            "Schedule timezone is invalid.",
            {"timezone": timezone_name},
        ) from exc


def _entry_name(schedule_id: int) -> str:
    """Return the provider entry name for a schedule id."""
    return f"schedule:{schedule_id}"
