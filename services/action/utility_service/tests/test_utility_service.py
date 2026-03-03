"""Behavior tests for Utility Service implementation."""

from __future__ import annotations

from datetime import UTC, datetime

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from services.action.utility_service.implementation import DefaultUtilityService


def _meta() -> object:
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
    """Clock access should return a UTC-aware datetime payload."""
    service = DefaultUtilityService()

    result = service.current_datetime(meta=_meta())

    assert result.ok is True
    assert result.payload is not None
    current = result.payload.value
    assert isinstance(current, datetime)
    assert current.tzinfo == UTC


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
