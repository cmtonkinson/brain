"""Formatting helpers for daily batch reminder messages."""

from __future__ import annotations

from collections.abc import Iterable

from models import Commitment
from time_utils import to_local


def format_batch_reminder_message(commitments: Iterable[Commitment]) -> str:
    """Format batch reminder commitments into a concise, scannable message."""
    items = list(commitments)
    if not items:
        return ""
    lines = ["Daily reminders:"]
    for commitment in items:
        due_by = _format_due_by(commitment)
        lines.append(f"- {commitment.description} (due {due_by})")
    return "\n".join(lines)


def _format_due_by(commitment: Commitment) -> str:
    """Format the due_by value in the operator's local timezone."""
    if commitment.due_by is None:
        return "unspecified time"
    local_due = to_local(commitment.due_by)
    return local_due.strftime("%Y-%m-%d %H:%M %Z")


__all__ = [
    "format_batch_reminder_message",
]
