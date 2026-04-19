"""Chat message bubble widget for the Console TUI."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class MessageBubble(Widget):
    """One chat message bubble — Brain on left, Operator on right."""

    DEFAULT_CSS = """
    MessageBubble {
        width: 100%;
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    MessageBubble .brain-header {
        text-style: dim;
    }
    MessageBubble .brain-body {
        color: $text-muted;
        padding: 0 0 0 2;
    }
    MessageBubble .operator-header {
        text-align: right;
    }
    MessageBubble .operator-body {
        text-align: right;
        padding: 0 2 0 0;
    }
    """

    def __init__(
        self,
        *,
        direction: str,
        text: str,
        timestamp: datetime | None = None,
    ) -> None:
        super().__init__()
        self._direction = direction
        self._text = text
        self._timestamp = timestamp

    def compose(self) -> ComposeResult:
        """Build the bubble layout based on direction."""
        time_str = self._timestamp.strftime("%H:%M") if self._timestamp else ""
        if self._direction == "brain":
            header = f"Brain  {time_str}" if time_str else "Brain"
            yield Static(header, classes="brain-header")
            yield Static(self._text, classes="brain-body")
        else:
            header = f"{time_str}  You" if time_str else "You"
            yield Static(header, classes="operator-header")
            yield Static(self._text, classes="operator-body")
