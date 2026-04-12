"""EmptyPicker: placeholder shown in unpopulated pane slots."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

VIEW_CHOICES = [
    ("1", "trace", "Trace"),
    ("2", "turn", "Turn"),
    ("3", "policy", "Policy"),
    ("4", "log", "Log"),
]


class EmptyPicker(Widget):
    """Shown in a pane slot that has no view loaded yet.

    Numeric picker bindings are local to the empty pane, so loading a view only
    happens when the empty slot is focused.
    """

    class ViewRequested(Message):
        """Posted when the operator chooses a view from the picker."""

        def __init__(self, picker: EmptyPicker, view_id: str) -> None:
            super().__init__()
            self.picker = picker
            self.view_id = view_id

    can_focus = True
    BINDINGS = [
        Binding(key, f"load_view('{view_id}')", label, show=False, priority=True)
        for key, view_id, label in VIEW_CHOICES
    ]

    DEFAULT_CSS = """
    EmptyPicker {
        align: center middle;
        border: round $panel;
        padding: 1 2;
    }
    """

    def __init__(self, is_sole: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._is_sole = is_sole

    def action_load_view(self, view_id: str) -> None:
        """Request that the workspace load the selected view into this pane."""
        self.post_message(self.ViewRequested(self, view_id))

    def compose(self) -> ComposeResult:
        choices = "  ".join(f"\\[{key}] {label}" for key, _, label in VIEW_CHOICES)
        if self._is_sole:
            yield Static(f"Brain Dashboard\n\n{choices}\n\ns/v to split")
        else:
            yield Static(choices)
