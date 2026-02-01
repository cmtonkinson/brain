"""Unit tests for ingestion request schema validation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ingestion.schema import IngestionRequest


def _base_payload() -> dict[str, object]:
    """Return a minimal valid ingestion request payload."""
    return {
        "source_type": "signal",
        "source_uri": "signal://msg/123",
        "source_actor": "user-1",
        "payload": "hello",
        "capture_time": datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
    }


def test_ingestion_request_accepts_payload() -> None:
    """Valid payload requests should parse successfully."""
    request = IngestionRequest.model_validate(_base_payload())

    assert request.source_type == "signal"
    assert request.payload == "hello"
    assert request.existing_object_key is None


def test_ingestion_request_accepts_existing_object_key() -> None:
    """Valid existing_object_key requests should parse successfully."""
    payload = _base_payload()
    payload.pop("payload")
    payload["existing_object_key"] = "blob/abc123"

    request = IngestionRequest.model_validate(payload)

    assert request.existing_object_key == "blob/abc123"
    assert request.payload is None


def test_ingestion_request_missing_required_field_fails() -> None:
    """Missing required fields should fail validation deterministically."""
    payload = _base_payload()
    payload.pop("source_type")

    with pytest.raises(ValidationError) as excinfo:
        IngestionRequest.model_validate(payload)

    assert "source_type" in str(excinfo.value)


def test_ingestion_request_rejects_both_payload_and_existing() -> None:
    """Providing both payload and existing_object_key should fail."""
    payload = _base_payload()
    payload["existing_object_key"] = "blob/abc123"

    with pytest.raises(ValidationError) as excinfo:
        IngestionRequest.model_validate(payload)

    assert "exactly one of payload or existing_object_key" in str(excinfo.value)


def test_ingestion_request_requires_timezone_aware_capture_time() -> None:
    """Naive capture_time values should be rejected."""
    payload = _base_payload()
    payload["capture_time"] = datetime(2025, 1, 1, 12, 0)

    with pytest.raises(ValidationError) as excinfo:
        IngestionRequest.model_validate(payload)

    assert "capture_time must be timezone-aware" in str(excinfo.value)
