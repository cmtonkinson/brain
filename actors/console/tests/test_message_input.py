"""Tests for the Console TUI MessageInput widget."""

from __future__ import annotations

from actors.console.widgets.message_input import MessageInput


def test_submitted_message_carries_text() -> None:
    """Submitted message should carry the operator's text."""
    msg = MessageInput.Submitted(text="hello brain")
    assert msg.text == "hello brain"


def test_submitted_message_empty_text() -> None:
    """Submitted message should preserve empty text for caller to gate."""
    msg = MessageInput.Submitted(text="")
    assert msg.text == ""
