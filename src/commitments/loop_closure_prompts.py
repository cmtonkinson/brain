"""Prompt generation for commitment loop-closure messages."""

from __future__ import annotations

from datetime import datetime

DEFAULT_LOOP_CLOSURE_TEMPLATE = (
    "When you have a moment, how would you like to handle this commitment?\n"
    "Commitment: {description}\n"
    "Reply with: complete, cancel, reschedule <new date>, or review."
)


def generate_loop_closure_prompt(*, description: str, due_by: datetime | None) -> str | None:
    """Generate a loop-closure prompt for a missed commitment."""
    if due_by is None:
        return None
    return DEFAULT_LOOP_CLOSURE_TEMPLATE.format(description=description)
