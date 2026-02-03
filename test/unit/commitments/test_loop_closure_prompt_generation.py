"""Unit tests for loop-closure prompt generation."""

from __future__ import annotations

from datetime import datetime, timezone

from commitments.loop_closure_prompts import generate_loop_closure_prompt


def test_prompt_includes_description_and_options() -> None:
    """Prompt should include the commitment description and response options."""
    prompt = generate_loop_closure_prompt(
        description="Send the proposal",
        due_by=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert prompt is not None
    assert "Send the proposal" in prompt
    assert "complete" in prompt
    assert "cancel" in prompt
    assert "reschedule" in prompt
    assert "review" in prompt


def test_missing_due_by_returns_none() -> None:
    """Commitments without due_by should not generate prompts."""
    prompt = generate_loop_closure_prompt(description="No due date", due_by=None)

    assert prompt is None
