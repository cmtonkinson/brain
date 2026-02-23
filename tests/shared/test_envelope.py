"""Tests for envelope model and builder behavior."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from packages.brain_shared.envelope import (
    EnvelopeKind,
    EnvelopeMeta,
    empty,
    failure,
    new_meta,
    success,
    with_error,
)
from packages.brain_shared.envelope.envelope import Envelope
from packages.brain_shared.errors import ErrorCategory, ErrorDetail


def _meta() -> EnvelopeMeta:
    """Return deterministic metadata for envelope tests."""
    return new_meta(
        kind=EnvelopeKind.RESULT,
        source="service_embedding_authority",
        principal="operator",
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        envelope_id="env-1",
        trace_id="trace-1",
    )


def _error(code: str = "VALIDATION_ERROR") -> ErrorDetail:
    """Return a deterministic error detail for envelope tests."""
    return ErrorDetail(
        code=code,
        message="Invalid input",
        category=ErrorCategory.VALIDATION,
        retryable=False,
    )


def test_success_builder_returns_ok_envelope_with_payload() -> None:
    """success should build an ok envelope with payload and no errors."""
    envelope = success(meta=_meta(), payload={"source_id": "01ABC"})

    assert envelope.ok is True
    assert envelope.has_payload is True
    assert envelope.payload is not None
    assert envelope.payload.value == {"source_id": "01ABC"}
    assert envelope.errors == []


def test_failure_builder_returns_non_ok_envelope_with_errors() -> None:
    """failure should build a non-ok envelope containing provided errors."""
    envelope = failure(
        meta=_meta(),
        errors=[_error("DEPENDENCY_UNAVAILABLE")],
        payload={"source_id": "01ABC"},
    )

    assert envelope.ok is False
    assert envelope.has_payload is True
    assert envelope.payload is not None
    assert envelope.payload.value == {"source_id": "01ABC"}
    assert [item.code for item in envelope.errors] == ["DEPENDENCY_UNAVAILABLE"]


def test_empty_builder_returns_ok_envelope_without_payload() -> None:
    """empty should build an ok envelope without payload or errors."""
    envelope = empty(meta=_meta())

    assert envelope.ok is True
    assert envelope.has_payload is False
    assert envelope.payload is None
    assert envelope.errors == []


def test_with_error_appends_error_without_mutating_original_envelope() -> None:
    """with_error should append one error and keep original envelope unchanged."""
    original = success(meta=_meta(), payload={"source_id": "01ABC"})
    updated = with_error(envelope=original, error=_error("NOT_FOUND"))

    assert original.errors == []
    assert updated.errors != original.errors
    assert [item.code for item in updated.errors] == ["NOT_FOUND"]
    assert updated.payload == original.payload
    assert updated.metadata == original.metadata
    assert updated.ok is False


def test_envelope_model_validation_rejects_invalid_error_shape() -> None:
    """Envelope model validation should fail for malformed error entries."""
    with pytest.raises(ValidationError):
        Envelope[dict[str, str]].model_validate(
            {
                "metadata": _meta(),
                "payload": {"value": {"source_id": "01ABC"}},
                "errors": [{"code": "BAD"}],
            }
        )


def test_envelope_model_validation_rejects_invalid_metadata_shape() -> None:
    """Envelope model validation should fail for malformed metadata."""
    with pytest.raises(ValidationError):
        Envelope[int].model_validate(
            {
                "metadata": {"kind": "result"},
                "payload": {"value": 1},
                "errors": [],
            }
        )
