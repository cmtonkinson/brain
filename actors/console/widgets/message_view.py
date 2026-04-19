"""Scrolling message history view for the Console TUI."""

from __future__ import annotations

from datetime import datetime

from textual.containers import VerticalScroll

from actors.console.widgets.message_bubble import MessageBubble


class MessageView(VerticalScroll):
    """Scrollable container that holds the conversation history."""

    DEFAULT_CSS = """
    MessageView {
        height: 1fr;
        padding: 1 0;
    }
    """

    def append_message(
        self,
        *,
        direction: str,
        text: str,
        timestamp: datetime | None = None,
    ) -> None:
        """Append one message bubble and scroll to bottom."""
        bubble = MessageBubble(
            direction=direction,
            text=text,
            timestamp=timestamp,
        )
        self.mount(bubble)
        bubble.scroll_visible(animate=False)
