"""Message input widget with $EDITOR support for the Console TUI."""

from __future__ import annotations

import collections
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


class InputHistory:
    """Bash-style up/down history buffer with draft preservation.

    Holds the last N submitted messages and a single in-progress *draft* slot
    just past the newest entry. Walking up moves toward older entries; walking
    down moves back toward the draft. Submissions append to history and reset
    navigation state. Lifetime is the owning widget's; nothing is persisted.
    """

    def __init__(self, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._entries: collections.deque[str] = collections.deque(maxlen=max_size)
        self._index: int | None = None
        self._draft: str = ""

    def record(self, text: str) -> None:
        """Record a submitted message and reset navigation to the draft tail.

        Empty strings are not recorded but still reset navigation state.
        """
        if text:
            self._entries.append(text)
        self._index = None
        self._draft = ""

    def prev(self, current_text: str) -> str | None:
        """Step one entry toward older history.

        Returns the text to load into the field, or ``None`` if there's nowhere
        to go (empty history, or already at the oldest entry). The first step
        away from the draft tail saves ``current_text`` so it can be restored.
        """
        if not self._entries:
            return None
        if self._index is None:
            self._draft = current_text
            self._index = len(self._entries) - 1
            return self._entries[self._index]
        if self._index > 0:
            self._index -= 1
            return self._entries[self._index]
        return None

    def next(self, current_text: str) -> str | None:
        """Step one entry toward newer history, ending at the saved draft.

        Returns the text to load into the field, or ``None`` if already at the
        draft tail. Stepping past the newest entry restores the saved draft.
        ``current_text`` is unused today; accepted for symmetry with ``prev``.
        """
        del current_text
        if self._index is None:
            return None
        if self._index < len(self._entries) - 1:
            self._index += 1
            return self._entries[self._index]
        self._index = None
        return self._draft


class ExpandingTextArea(TextArea):
    """TextArea that grows vertically as content is typed, up to a configurable line cap.

    ``enter`` submits; ``alt+enter`` inserts a newline.
    """

    BINDINGS = [
        Binding("enter", "submit_text", "Send", show=False, priority=True),
        Binding("alt+enter", "newline", "New line", show=False, priority=True),
        Binding("up", "history_prev", "History prev", show=False, priority=True),
        Binding("down", "history_next", "History next", show=False, priority=True),
    ]

    class Submitted(Message):
        """Fired when the operator presses enter."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(
        self,
        *args: object,
        max_lines: int = 10,
        history_size: int = 1000,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._max_lines = max_lines
        self._history = InputHistory(max_size=history_size)

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
            self._history.record(text)
            self.post_message(self.Submitted(text))
            self.clear()

    def action_newline(self) -> None:
        """Insert a literal newline at the cursor."""
        self.insert("\n")

    def action_history_prev(self) -> None:
        """At the top edge, recall older history; otherwise move the cursor up."""
        cursor_row, _ = self.cursor_location
        if cursor_row > 0:
            self.action_cursor_up()
            return
        recalled = self._history.prev(self.text)
        if recalled is not None:
            self._load_recalled(recalled)

    def action_history_next(self) -> None:
        """At the bottom edge, walk back toward the draft; otherwise move cursor down."""
        cursor_row, _ = self.cursor_location
        if cursor_row < self.document.line_count - 1:
            self.action_cursor_down()
            return
        recalled = self._history.next(self.text)
        if recalled is not None:
            self._load_recalled(recalled)

    def _load_recalled(self, text: str) -> None:
        """Replace buffer contents with a recalled entry, cursor at end."""
        self.load_text(text)
        self.move_cursor(self.document.end)


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
        input_history_size: int = 1000,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._editor = editor
        self._input_max_lines = input_max_lines
        self._input_history_size = input_history_size

    def compose(self) -> ComposeResult:
        """Build the input area."""
        yield ExpandingTextArea(
            id=_INPUT_FIELD_ID,
            soft_wrap=True,
            max_lines=self._input_max_lines,
            history_size=self._input_history_size,
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
