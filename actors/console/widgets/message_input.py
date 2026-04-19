"""Message input widget with $EDITOR support for the Console TUI."""

from __future__ import annotations

import os
import subprocess
import tempfile

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, TextArea


class ExpandingTextArea(TextArea):
    """TextArea that grows vertically as content is typed (up to MAX_LINES).

    ``enter`` submits; ``shift+enter`` inserts a newline.
    """

    MAX_LINES = 10

    BINDINGS = [
        Binding("enter", "submit_text", "Send", show=False, priority=True),
        Binding("meta+enter", "newline", "New line", show=False, priority=True),
    ]

    class Submitted(Message):
        """Fired when the operator presses enter."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def on_mount(self) -> None:
        self._update_height()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._update_height()

    def _update_height(self) -> None:
        lines = self.wrapped_document.height
        self.styles.height = max(1, min(lines, self.MAX_LINES))

    def action_submit_text(self) -> None:
        """Submit current content and clear the field."""
        text = self.text.strip()
        if text:
            self.post_message(self.Submitted(text))
            self.clear()

    def action_newline(self) -> None:
        """Insert a literal newline at the cursor."""
        self.insert("\n")


class MessageInput(Widget, can_focus=False):
    """Expanding multi-line input with enter-to-send and ctrl+g for $EDITOR.

    ``editor`` is the executable to launch (default: ``vim``). Callers should
    pass ``ConsoleConfig.editor`` so the configured value is honoured.
    """

    DEFAULT_CSS = """
    MessageInput {
        height: auto;
        padding: 0;
    }
    MessageInput ExpandingTextArea {
        height: 1;
        border: none;
        padding: 0;
    }
    MessageInput ExpandingTextArea:focus {
        border: none;
        padding: 0;
    }
    MessageInput #input-hint {
        height: 1;
        color: $text-muted;
        background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+g", "open_editor", "Open $EDITOR", show=False, priority=True),
        Binding("ctrl+l", "clear_input", "Clear input", show=False, priority=True),
    ]

    class Submitted(Message):
        """Fired when the operator submits a message."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, *args: object, editor: str = "vim", **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._editor = editor

    def compose(self) -> ComposeResult:
        """Build the input area."""
        yield ExpandingTextArea(id="input-field", soft_wrap=True)
        yield Static(
            r"\[enter] send  \[alt+enter] newline  \[ctrl+g] $EDITOR  \[ctrl+l] clear",
            id="input-hint",
        )

    @on(ExpandingTextArea.Submitted)
    def _on_expanding_text_area_submitted(
        self, event: ExpandingTextArea.Submitted
    ) -> None:
        self.post_message(self.Submitted(event.text))

    def action_clear_input(self) -> None:
        """Clear the input field."""
        self.query_one("#input-field", ExpandingTextArea).clear()

    def action_open_editor(self) -> None:
        """Spawn $EDITOR with a temp file, send contents on exit."""
        editor = self._editor
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            delete=False,
        ) as tmp:
            tmp_path = tmp.name

        try:
            with self.app.suspend():
                result = subprocess.run([editor, tmp_path], check=False)
            if result.returncode != 0:
                self.app.notify(
                    f"Editor exited with code {result.returncode}",
                    severity="warning",
                )
                return
            with open(tmp_path) as f:
                text = f.read().rstrip("\n")
            if text:
                self.post_message(self.Submitted(text))
        except FileNotFoundError:
            self.app.notify(f"Editor not found: {editor!r}", severity="error")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
