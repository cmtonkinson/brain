"""Canonical approval-response vocabulary and normalization helpers."""

from __future__ import annotations

from typing import Literal

from lib.shared.config.models import ApprovalResponseSettings

ApprovalIntent = Literal["approve", "reject"]


def normalize_approval_intent(
    *,
    message_text: str = "",
    reaction_emoji: str = "",
    settings: ApprovalResponseSettings | None = None,
) -> ApprovalIntent | None:
    """Return approve/reject for unambiguous approval responses, else None."""
    config = settings if settings is not None else ApprovalResponseSettings()
    emoji = reaction_emoji.strip()
    if emoji in config.approve_reaction_emojis:
        return "approve"
    if emoji in config.reject_reaction_emojis:
        return "reject"

    text = " ".join(message_text.strip().lower().replace(",", " ").split())
    if text == "":
        return None
    if text in config.approve_text_responses:
        return "approve"
    if text.startswith("yes ") or " approved" in text:
        return "approve"
    if text in config.reject_text_responses:
        return "reject"
    if text.startswith("no ") or text.startswith("reject "):
        return "reject"
    return None
