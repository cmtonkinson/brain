"""EmptyPicker: placeholder shown in unpopulated pane slots."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

VIEW_CHOICES = ["trace", "turn", "policy", "log"]


class EmptyPicker(Widget):
    """Shown in a pane slot that has no view loaded yet.

    View selection is handled by the app-level key bindings (1-4) which post
    `load_view` actions. This widget is a non-focusable hint only.
    """

    can_focus = False

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

    def compose(self) -> ComposeResult:
        if self._is_sole:
            yield Static(
                "Brain Dashboard\n\n"
                "\\[1] Trace  \\[2] Turn  \\[3] Policy  \\[4] Log\n\n"
                "s/v to split"
            )
        else:
            yield Static("\\[1] Trace  \\[2] Turn  \\[3] Policy  \\[4] Log")
