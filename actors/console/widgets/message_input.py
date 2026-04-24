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


_INPUT_FIELD_ID = "input-field"
_INPUT_HINT_ID = "input-hint"


class ExpandingTextArea(TextArea):
    """TextArea that grows vertically as content is typed, up to a configurable line cap.

    ``enter`` submits; ``alt+enter`` inserts a newline.
    """

    BINDINGS = [
        Binding("enter", "submit_text", "Send", show=False, priority=True),
        Binding("alt+enter", "newline", "New line", show=False, priority=True),
    ]

    class Submitted(Message):
        """Fired when the operator presses enter."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, *args: object, max_lines: int = 10, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._max_lines = max_lines

    def on_mount(self) -> None:
        self._update_height()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._update_height()

    def _update_height(self) -> None:
        lines = self.wrapped_document.height
        self.styles.height = max(1, min(lines, self._max_lines))

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

    ``editor`` is the executable to launch (default: ``vim``).
    ``input_max_lines`` caps the visible height of the text area (default: ``10``).
    Callers should pass ``ConsoleConfig`` values so configured preferences are honoured.
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

    def __init__(
        self,
        *args: object,
        editor: str = "vim",
        input_max_lines: int = 10,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._editor = editor
        self._input_max_lines = input_max_lines

    def compose(self) -> ComposeResult:
        """Build the input area."""
        yield ExpandingTextArea(
            id=_INPUT_FIELD_ID, soft_wrap=True, max_lines=self._input_max_lines
        )
        yield Static(
            r"\[enter] send  \[alt+enter] newline  \[ctrl+g] $EDITOR  \[ctrl+l] clear",
            id=_INPUT_HINT_ID,
        )

    @on(ExpandingTextArea.Submitted)
    def _on_expanding_text_area_submitted(
        self, event: ExpandingTextArea.Submitted
    ) -> None:
        self.post_message(self.Submitted(event.text))

    def focus_input(self) -> None:
        """Focus the inner text area."""
        self.query_one(f"#{_INPUT_FIELD_ID}", ExpandingTextArea).focus()

    def action_clear_input(self) -> None:
        """Clear the input field."""
        self.query_one(f"#{_INPUT_FIELD_ID}", ExpandingTextArea).clear()

    def action_open_editor(self) -> None:
        """Spawn $EDITOR with a temp file; load contents into input buffer on exit."""
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
            with open(tmp_path, encoding="utf-8") as f:
                text = f.read().rstrip("\n")
            if text:
                field = self.query_one(f"#{_INPUT_FIELD_ID}", ExpandingTextArea)
                field.load_text(text)
                field.move_cursor(field.document.end)
                field.focus()
        except FileNotFoundError:
            self.app.notify(f"Editor not found: {editor!r}", severity="error")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
