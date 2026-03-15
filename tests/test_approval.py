"""Tests for canonical approval-response normalization."""

from __future__ import annotations

import pytest

from packages.brain_shared.config import ApprovalResponseSettings
from packages.brain_shared.approval import normalize_approval_intent


@pytest.mark.parametrize(
    ("reaction_emoji", "expected"),
    [
        ("👍", "approve"),
        ("✅", "approve"),
        ("👎", "reject"),
        ("❌", "reject"),
    ],
)
def test_normalize_approval_intent_supports_configured_reaction_emoji(
    reaction_emoji: str, expected: str
) -> None:
    """Reaction emoji should normalize via the canonical shared vocabulary."""
    assert normalize_approval_intent(reaction_emoji=reaction_emoji) == expected


@pytest.mark.parametrize(
    "reaction_emoji",
    ["👌", "🤘", "👏", "🙌", "🫡", "☑️", "☝️", "👆", "🔥"],
)
def test_normalize_approval_intent_rejects_non_default_approval_emoji(
    reaction_emoji: str,
) -> None:
    """Only the configured default approval emoji should normalize by default."""
    assert normalize_approval_intent(reaction_emoji=reaction_emoji) is None


def test_normalize_approval_intent_supports_approved_text() -> None:
    """Approval text aliases should normalize consistently across services."""
    assert normalize_approval_intent(message_text="approved") == "approve"


@pytest.mark.parametrize("message_text", ["ok", "okay", "ship it", "do it"])
def test_normalize_approval_intent_rejects_non_default_approval_text(
    message_text: str,
) -> None:
    """Only the configured default approval text should normalize by default."""
    assert normalize_approval_intent(message_text=message_text) is None


@pytest.mark.parametrize("message_text", ["reject", "rejected", "cancel"])
def test_normalize_approval_intent_rejects_non_default_rejection_text(
    message_text: str,
) -> None:
    """Only the configured default rejection text should normalize by default."""
    assert normalize_approval_intent(message_text=message_text) is None


def test_normalize_approval_intent_uses_configured_vocab() -> None:
    """Config overrides should define the canonical approval vocabulary."""
    settings = ApprovalResponseSettings(
        approve_reaction_emojis=("abc",),
        reject_reaction_emojis=("xyz",),
        approve_text_responses=("launch",),
        reject_text_responses=("stop",),
    )

    assert (
        normalize_approval_intent(reaction_emoji="abc", settings=settings) == "approve"
    )
    assert (
        normalize_approval_intent(reaction_emoji="xyz", settings=settings) == "reject"
    )
    assert (
        normalize_approval_intent(message_text="launch", settings=settings) == "approve"
    )
    assert normalize_approval_intent(message_text="stop", settings=settings) == "reject"
