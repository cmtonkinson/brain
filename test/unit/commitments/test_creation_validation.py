"""Unit tests for commitment creation validation and defaults."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from commitments.creation_types import CommitmentCreationInput, validate_commitment_creation


def test_description_only_applies_defaults() -> None:
    """Description-only input should apply default values."""
    payload = validate_commitment_creation({"description": "Follow up"})

    assert payload.description == "Follow up"
    assert payload.state == "OPEN"
    assert payload.importance == 2
    assert payload.effort_provided == 2


def test_description_with_optional_fields_is_valid() -> None:
    """Optional fields should be accepted when provided."""
    due_by = datetime(2024, 1, 1, tzinfo=timezone.utc)
    provenance_id = uuid4()

    payload = validate_commitment_creation(
        {
            "description": "Draft summary",
            "state": "OPEN",
            "importance": 3,
            "effort_provided": 1,
            "due_by": due_by,
            "effort_inferred": 2,
            "provenance_id": provenance_id,
            "metadata": {"source": "email"},
        }
    )

    assert payload.due_by == due_by
    assert payload.effort_inferred == 2
    assert payload.provenance_id == provenance_id
    assert payload.metadata == {"source": "email"}


def test_missing_description_is_rejected() -> None:
    """Inputs without a description should fail validation."""
    with pytest.raises(ValidationError):
        validate_commitment_creation({})


def test_invalid_state_is_rejected() -> None:
    """Unknown commitment states should fail validation."""
    with pytest.raises(ValidationError):
        validate_commitment_creation({"description": "Test", "state": "UNKNOWN"})


def test_importance_out_of_range_is_rejected() -> None:
    """Importance values outside 1-3 should fail validation."""
    with pytest.raises(ValidationError):
        validate_commitment_creation({"description": "Test", "importance": 0})


def test_effort_provided_out_of_range_is_rejected() -> None:
    """Effort values outside 1-3 should fail validation."""
    with pytest.raises(ValidationError):
        validate_commitment_creation({"description": "Test", "effort_provided": 4})


def test_validator_accepts_model_instance() -> None:
    """Validator should accept already-validated payloads."""
    model = CommitmentCreationInput(description="Already validated")

    assert validate_commitment_creation(model) is model
