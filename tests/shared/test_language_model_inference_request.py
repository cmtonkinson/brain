"""Validation tests for the canonical language-model inference request."""

from __future__ import annotations

import pytest

from lib.shared.language_model import (
    InferenceControls,
    InferenceParallelToolCalls,
    InferenceToolChoice,
    dump_inference_request,
    validate_inference_request,
)
from tests.helpers.inference_request import make_inference_request


def test_inference_request_round_trips_through_transport_dump() -> None:
    """Canonical inference requests should survive dump/validate round-trip."""
    request = make_inference_request()

    dumped = dump_inference_request(request)
    restored = validate_inference_request(dumped)

    assert restored == request


def test_inference_controls_require_named_tool_for_require_one() -> None:
    """Named-tool mode must include a concrete tool name."""
    with pytest.raises(ValueError, match="tool_choice.tool_name is required"):
        InferenceControls(tool_choice=InferenceToolChoice(mode="require_one"))


def test_inference_controls_reject_tool_name_outside_require_one() -> None:
    """Tool name should be rejected outside named-tool mode."""
    with pytest.raises(ValueError, match="tool_choice.tool_name is only valid"):
        InferenceControls(
            tool_choice=InferenceToolChoice(mode="auto", tool_name="demo-tool")
        )


def test_inference_parallel_tool_calls_require_positive_max_calls() -> None:
    """Parallel tool-call limits must be positive when provided."""
    with pytest.raises(ValueError, match="parallel_tool_calls.max_calls must be > 0"):
        InferenceControls(
            parallel_tool_calls=InferenceParallelToolCalls(
                mode="allow",
                max_calls=0,
            )
        )


def test_validate_inference_request_accepts_existing_model_instance() -> None:
    """Shared validator should accept canonical model instances directly."""
    request = make_inference_request()

    assert validate_inference_request(request) == request
