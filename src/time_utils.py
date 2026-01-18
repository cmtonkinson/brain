"""Time zone helpers for UTC storage and local presentation."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import settings


def get_local_timezone() -> ZoneInfo:
    """Return the configured local timezone."""
    timezone_name = settings.user.timezone
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone: {timezone_name}") from exc


def to_local(value: datetime) -> datetime:
    """Convert a datetime to the configured local timezone."""
    local_tz = get_local_timezone()
    if value.tzinfo is None:
        return value.replace(tzinfo=local_tz)
    return value.astimezone(local_tz)


def to_utc(value: datetime) -> datetime:
    """Convert a datetime to UTC."""
    local_value = to_local(value)
    return local_value.astimezone(timezone.utc)


def local_now() -> datetime:
    """Return the current time in the configured local timezone."""
    return datetime.now(get_local_timezone())
