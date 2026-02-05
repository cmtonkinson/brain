"""Prompt generation for commitment transition proposals."""

from __future__ import annotations

DEFAULT_TRANSITION_PROPOSAL_TEMPLATE = (
    "The system suggests updating this commitment:\n"
    "Commitment: {description}\n"
    "Proposed change: {from_state} -> {to_state}\n"
    "Reply with: complete, cancel, reschedule <new date>, or review."
)


def generate_transition_proposal_prompt(
    *,
    description: str,
    from_state: str,
    to_state: str,
) -> str:
    """Generate a prompt for a proposed commitment transition."""
    return DEFAULT_TRANSITION_PROPOSAL_TEMPLATE.format(
        description=description,
        from_state=from_state,
        to_state=to_state,
    )


__all__ = ["generate_transition_proposal_prompt"]
