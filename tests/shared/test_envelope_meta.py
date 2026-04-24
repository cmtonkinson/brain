"""Tests for envelope metadata creation, normalization, and validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ValidationError

from lib.shared.envelope import (
    EnvelopeKind,
    EnvelopeMeta,
    new_meta,
    normalize_meta,
    validate_meta,
    validate_service_request,
)


def test_new_meta_generates_ids_and_normalizes_naive_timestamp() -> None:
    """new_meta should create ids and attach UTC to naive timestamps."""
    timestamp = datetime(2026, 1, 1, 12, 0, 0)

    meta = new_meta(
        kind=EnvelopeKind.RESULT,
        source="service_embedding",
        principal="operator",
        timestamp=timestamp,
    )

    assert meta.envelope_id
    assert meta.trace_id
    assert meta.parent_id == ""
    assert meta.timestamp == timestamp.replace(tzinfo=UTC)
    assert meta.kind == EnvelopeKind.RESULT
    assert meta.source == "service_embedding"
    assert meta.principal == "operator"


def test_new_meta_normalizes_aware_timestamp_to_utc() -> None:
    """new_meta should convert aware timestamps into UTC."""
    local_tz = timezone(timedelta(hours=-5))
    timestamp = datetime(2026, 1, 1, 7, 0, 0, tzinfo=local_tz)

    meta = new_meta(
        kind=EnvelopeKind.EVENT,
        source="inbound",
        principal="operator",
        timestamp=timestamp,
    )

    assert meta.timestamp == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_normalize_meta_returns_same_object_for_already_utc_timestamp() -> None:
    """normalize_meta should return the same object when timestamp is UTC."""
    meta = new_meta(
        kind=EnvelopeKind.COMMAND,
        source="assistant",
        principal="operator",
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )

    normalized = normalize_meta(meta)

    assert normalized is meta


def test_validate_meta_rejects_unspecified_kind() -> None:
    """validate_meta should fail when kind is unspecified."""
    meta = new_meta(
        kind=EnvelopeKind.UNSPECIFIED,
        source="assistant",
        principal="operator",
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )

    with pytest.raises(ValueError):
        validate_meta(meta)


def test_envelope_meta_model_validation_rejects_missing_required_fields() -> None:
    """EnvelopeMeta model validation should fail for missing required fields."""
    with pytest.raises(ValidationError):
        EnvelopeMeta.model_validate(
            {
                "trace_id": "trace-1",
                "parent_id": "",
                "timestamp": "2026-01-01T12:00:00Z",
                "kind": "result",
                "source": "agent",
            }
        )


def test_normalize_meta_converts_naive_timestamp_to_utc() -> None:
    """normalize_meta should attach UTC to naive timestamps."""
    meta = new_meta(
        kind=EnvelopeKind.COMMAND,
        source="assistant",
        principal="operator",
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    # Manually construct a copy with a naive timestamp to exercise the naive branch.
    naive_meta = meta.model_copy(update={"timestamp": datetime(2026, 1, 1, 12, 0, 0)})

    normalized = normalize_meta(naive_meta)

    assert normalized.timestamp == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert normalized is not naive_meta


def test_normalize_meta_converts_non_utc_aware_timestamp_to_utc() -> None:
    """normalize_meta should convert aware non-UTC timestamps into UTC."""
    local_tz = timezone(timedelta(hours=3))
    meta = new_meta(
        kind=EnvelopeKind.EVENT,
        source="assistant",
        principal="operator",
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    non_utc_meta = meta.model_copy(
        update={"timestamp": datetime(2026, 1, 1, 15, 0, 0, tzinfo=local_tz)}
    )

    normalized = normalize_meta(non_utc_meta)

    assert normalized.timestamp == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert normalized is not non_utc_meta


def _valid_meta() -> EnvelopeMeta:
    return new_meta(
        kind=EnvelopeKind.COMMAND,
        source="test_service",
        principal="operator",
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


class _SampleRequest(BaseModel):
    name: str
    count: int


def test_validate_service_request_returns_model_on_valid_input() -> None:
    """validate_service_request should return a validated model and empty errors."""
    model, errors = validate_service_request(
        meta=_valid_meta(),
        model=_SampleRequest,
        payload={"name": "test", "count": 5},
    )

    assert errors == []
    assert isinstance(model, _SampleRequest)
    assert model.name == "test"
    assert model.count == 5


def test_validate_service_request_returns_errors_for_invalid_payload() -> None:
    """validate_service_request should surface all Pydantic payload errors."""
    model, errors = validate_service_request(
        meta=_valid_meta(),
        model=_SampleRequest,
        payload={"name": 123, "count": "not-a-number"},
    )

    assert model is None
    assert len(errors) >= 1


def test_validate_service_request_returns_error_for_invalid_meta() -> None:
    """validate_service_request should return an error when meta is invalid."""
    bad_meta = new_meta(
        kind=EnvelopeKind.UNSPECIFIED,
        source="test_service",
        principal="operator",
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )

    model, errors = validate_service_request(
        meta=bad_meta,
        model=_SampleRequest,
        payload={"name": "test", "count": 1},
    )

    assert model is None
    assert len(errors) == 1
    assert "kind" in errors[0].message
