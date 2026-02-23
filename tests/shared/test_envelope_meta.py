"""Tests for envelope metadata creation, normalization, and validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from packages.brain_shared.envelope import (
    EnvelopeKind,
    EnvelopeMeta,
    new_meta,
    normalize_meta,
    validate_meta,
)


def test_new_meta_generates_ids_and_normalizes_naive_timestamp() -> None:
    """new_meta should create ids and attach UTC to naive timestamps."""
    timestamp = datetime(2026, 1, 1, 12, 0, 0)

    meta = new_meta(
        kind=EnvelopeKind.RESULT,
        source="service_embedding_authority",
        principal="operator",
        timestamp=timestamp,
    )

    assert meta.envelope_id
    assert meta.trace_id
    assert meta.parent_id == ""
    assert meta.timestamp == timestamp.replace(tzinfo=UTC)
    assert meta.kind == EnvelopeKind.RESULT
    assert meta.source == "service_embedding_authority"
    assert meta.principal == "operator"


def test_new_meta_normalizes_aware_timestamp_to_utc() -> None:
    """new_meta should convert aware timestamps into UTC."""
    local_tz = timezone(timedelta(hours=-5))
    timestamp = datetime(2026, 1, 1, 7, 0, 0, tzinfo=local_tz)

    meta = new_meta(
        kind=EnvelopeKind.EVENT,
        source="switchboard",
        principal="operator",
        timestamp=timestamp,
    )

    assert meta.timestamp == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_normalize_meta_returns_same_object_for_already_utc_timestamp() -> None:
    """normalize_meta should return the same object when timestamp is UTC."""
    meta = new_meta(
        kind=EnvelopeKind.COMMAND,
        source="agent",
        principal="operator",
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )

    normalized = normalize_meta(meta)

    assert normalized is meta


def test_validate_meta_rejects_unspecified_kind() -> None:
    """validate_meta should fail when kind is unspecified."""
    meta = new_meta(
        kind=EnvelopeKind.UNSPECIFIED,
        source="agent",
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
