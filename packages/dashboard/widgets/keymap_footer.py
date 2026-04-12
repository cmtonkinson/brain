"""Dashboard footer widget: width-adaptive keybinding reference."""

from __future__ import annotations

from dataclasses import dataclass

from textual.widgets import Static


@dataclass
class FooterItem:
    """One keybinding hint shown in the footer."""

    key: str
    label: str
    priority: int  # 1=highest; higher number = dropped first when space constrained


_GLOBAL_ITEMS = [
    FooterItem("Q", "Quit", priority=1),
    FooterItem("enter", "Max", priority=2),
    FooterItem("tab", "Focus", priority=3),
    FooterItem("s", "Split-H", priority=4),
    FooterItem("v", "Split-V", priority=5),
    FooterItem("q", "Close", priority=6),
]


def _format_item(item: FooterItem) -> str:
    return f"\\[{item.key}] {item.label}"


def build_footer_text(items: list[FooterItem], max_width: int) -> str:
    """Fit items into max_width, dropping lowest-priority items first."""
    sorted_items = sorted(items, key=lambda i: i.priority)
    rendered = [_format_item(i) for i in sorted_items]
    # try fitting all, then drop from end until it fits
    sep = "  "
    while rendered:
        line = sep.join(rendered)
        if len(line) <= max_width:
            return line
        rendered.pop()  # drop lowest-priority (last in sorted order)
    return ""


class KeymapFooter(Static):
    """Compact footer showing width-adapted global keybinding hints."""

    def __init__(self) -> None:
        super().__init__(id="keymap-footer", markup=True)

    def on_mount(self) -> None:
        self._rebuild()

    def on_resize(self, event) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        try:
            width = self.size.width or 80
        except Exception:
            width = 80
        self.update(build_footer_text(_GLOBAL_ITEMS, width))
