"""Dashboard footer widget with primary keybinding hints."""

from __future__ import annotations

from textual.widgets import Static


class KeymapFooter(Static):
    """Compact footer showing the primary global keybindings."""

    def __init__(self) -> None:
        """Initialize the footer widget."""
        super().__init__(
            "[1] Trace  [2] Turn  [3] Policy  [4] Logs  "
            "[tab] Focus  [enter] Maximize  [q] Quit",
            id="keymap-footer",
        )
