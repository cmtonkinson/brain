"""Behavior tests for Utility Service implementation."""

from __future__ import annotations

from datetime import datetime

from lib.shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from services.reason.utility.implementation import DefaultUtilityService


def _meta() -> EnvelopeMeta:
    """Build valid envelope metadata for tests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_chunk_text_returns_single_chunk_for_non_empty_content() -> None:
    """Chunking should return one whole-content chunk for now."""
    service = DefaultUtilityService()

    result = service.chunk_text(meta=_meta(), text="hello")

    assert result.ok is True
    assert result.payload is not None
    assert len(result.payload.value) == 1
    chunk = result.payload.value[0]
    assert chunk.chunk_ordinal == 0
    assert chunk.text == "hello"
    assert chunk.reference_range == "0:5"


def test_current_datetime_returns_utc_aware_timestamp() -> None:
    """Clock access should return UTC and operator-local datetime payload."""
    service = DefaultUtilityService(preferred_timezone="America/New_York")

    result = service.current_datetime(meta=_meta())

    assert result.ok is True
    assert result.payload is not None
    current = result.payload.value
    assert current.local_timezone == "America/New_York"
    utc = datetime.fromisoformat(current.utc_timestamp)
    local = datetime.fromisoformat(current.local_timestamp)
    assert utc.tzinfo is not None
    assert local.tzinfo is not None
    assert utc.timestamp() == local.timestamp()


def test_parse_datetime_applies_timezone_to_naive_timestamp() -> None:
    """Naive input should be interpreted in the requested timezone."""
    service = DefaultUtilityService(preferred_timezone="UTC")

    result = service.parse_datetime(
        meta=_meta(), timestamp="2026-05-09T08:30:00", timezone="America/New_York"
    )

    assert result.ok is True
    assert result.payload is not None
    parsed = result.payload.value
    assert parsed.local_timezone == "America/New_York"
    assert parsed.local_timestamp.endswith("-04:00")
    assert parsed.utc_timestamp.endswith("+00:00")


def test_convert_datetime_projects_to_target_timezone() -> None:
    """Datetime conversion should preserve the instant while changing timezone."""
    service = DefaultUtilityService(preferred_timezone="UTC")

    result = service.convert_datetime(
        meta=_meta(),
        timestamp="2026-05-09T12:30:00+00:00",
        to_timezone="America/Los_Angeles",
    )

    assert result.ok is True
    assert result.payload is not None
    converted = result.payload.value
    assert converted.to_timezone == "America/Los_Angeles"
    assert converted.converted_timestamp.endswith("-07:00")
    assert (
        datetime.fromisoformat(converted.utc_timestamp).timestamp()
        == datetime.fromisoformat(converted.converted_timestamp).timestamp()
    )


def test_duration_until_returns_signed_duration() -> None:
    """Duration helper should return a signed interval in several units."""
    service = DefaultUtilityService(preferred_timezone="UTC")

    result = service.duration_until(
        meta=_meta(),
        now_timestamp="2026-05-09T12:00:00+00:00",
        target_timestamp="2026-05-10T00:00:00+00:00",
    )

    assert result.ok is True
    assert result.payload is not None
    duration = result.payload.value
    assert duration.seconds == 43200
    assert duration.hours == 12
    assert duration.is_past is False


def test_parse_datetime_rejects_invalid_timezone() -> None:
    """Invalid timezones should return a structured failure envelope."""
    service = DefaultUtilityService(preferred_timezone="UTC")

    result = service.parse_datetime(
        meta=_meta(), timestamp="2026-05-09T12:00:00", timezone="No/SuchZone"
    )

    assert result.ok is False
    assert result.errors[0].code == "INVALID_ARGUMENT"


def test_chunk_text_returns_empty_list_for_empty_content() -> None:
    """Empty content should yield no chunks."""
    service = DefaultUtilityService()

    result = service.chunk_text(meta=_meta(), text="")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value == []


def test_health_returns_ready_payload() -> None:
    """Health should report ready when service is available."""
    service = DefaultUtilityService()

    result = service.health(meta=_meta())

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.service_ready is True
    assert result.payload.value.detail == "ok"
