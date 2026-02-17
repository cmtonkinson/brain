"""Unit tests for timezone conversion helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from config import settings
from time_utils import get_local_timezone, to_local, to_utc


def test_get_local_timezone_uses_settings(monkeypatch) -> None:
    """Local timezone resolves from settings."""
    monkeypatch.setattr(settings.user, "timezone", "UTC", raising=False)
    tz = get_local_timezone()
    assert tz.key == "UTC"


def test_to_utc_converts_from_local(monkeypatch) -> None:
    """to_utc converts naive local times to UTC."""
    monkeypatch.setattr(settings.user, "timezone", "America/New_York", raising=False)
    local_time = datetime(2025, 1, 15, 12, 0, 0)
    converted = to_utc(local_time)

    assert converted.tzinfo == timezone.utc
    assert converted.hour == 17
    assert converted.minute == 0


def test_to_local_converts_from_utc(monkeypatch) -> None:
    """to_local converts aware UTC times to local timezone."""
    monkeypatch.setattr(settings.user, "timezone", "America/New_York", raising=False)
    utc_time = datetime(2025, 1, 15, 17, 0, 0, tzinfo=timezone.utc)
    converted = to_local(utc_time)

    assert converted.hour == 12
    assert converted.tzinfo is not None
