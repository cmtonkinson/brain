"""Tests for canonical approval-response normalization."""

from __future__ import annotations

import pytest

from lib.shared.config import ApprovalResponseSettings
from lib.shared.approval import normalize_approval_intent


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


# ---------------------------------------------------------------------------
# Whitespace and comma normalization
# ---------------------------------------------------------------------------


def test_normalize_approval_intent_strips_whitespace_from_text() -> None:
    """Leading and trailing whitespace in text should not affect matching."""
    assert normalize_approval_intent(message_text="  approve  ") == "approve"


def test_normalize_approval_intent_collapses_internal_whitespace() -> None:
    """Multiple internal spaces should collapse to single space."""
    assert normalize_approval_intent(message_text="  yes  ") == "approve"


def test_normalize_approval_intent_strips_whitespace_from_emoji() -> None:
    """Whitespace around emoji should be stripped."""
    assert normalize_approval_intent(reaction_emoji="  👍  ") == "approve"


# ---------------------------------------------------------------------------
# Prefix matching
# ---------------------------------------------------------------------------


def test_normalize_approval_intent_yes_prefix_approves() -> None:
    """Text starting with 'yes ' should normalize to approve."""
    assert normalize_approval_intent(message_text="yes please") == "approve"


def test_normalize_approval_intent_no_prefix_rejects() -> None:
    """Text starting with 'no ' should normalize to reject."""
    assert normalize_approval_intent(message_text="no way") == "reject"


def test_normalize_approval_intent_reject_prefix_rejects() -> None:
    """Text starting with 'reject ' should normalize to reject."""
    assert normalize_approval_intent(message_text="reject this") == "reject"


def test_normalize_approval_intent_approved_substring_approves() -> None:
    """Text containing ' approved' should normalize to approve."""
    assert normalize_approval_intent(message_text="request approved") == "approve"


def test_normalize_approval_intent_approve_prefix_approves() -> None:
    """Text starting with 'approve ' should normalize to approve."""
    assert normalize_approval_intent(message_text="approve token-1") == "approve"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_normalize_approval_intent_empty_text_and_emoji_returns_none() -> None:
    """Both empty text and empty emoji should return None."""
    assert normalize_approval_intent(message_text="", reaction_emoji="") is None


def test_normalize_approval_intent_emoji_takes_priority_over_text() -> None:
    """When both emoji and text are provided, emoji should match first."""
    result = normalize_approval_intent(message_text="deny", reaction_emoji="👍")
    assert result == "approve"
