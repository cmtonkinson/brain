"""Turn pane: current agent turn and compact recent history."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from packages.dashboard.data_sources.turns import TurnDataSource
from packages.dashboard.models.turn import CurrentTurnView, RecentTurnItemView
from packages.dashboard.panes.base import BaseView

_RECENT_MAX = 8
_TRUNCATE = 52  # max chars for content preview


def _trunc(text: str, n: int = _TRUNCATE) -> str:
    return text if len(text) <= n else text[:n] + "..."


class TurnPane(BaseView):
    """Current agent turn with compact recent dialogue history."""

    view_id = "turn"
    view_title = "Turn"

    DEFAULT_CSS = """
    TurnPane { layout: vertical; height: 1fr; }
    TurnPane > #turn-current { height: auto; }
    TurnPane > #turn-recent { height: 1fr; }
    """

    def __init__(
        self,
        turn_source: TurnDataSource | None = None,
        current: CurrentTurnView | None = None,
        recent: list[RecentTurnItemView] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._turn_source = turn_source
        self._current = current
        self._recent: list[RecentTurnItemView] = recent or []

    def compose(self) -> ComposeResult:
        yield Static(self._render_current(), id="turn-current")
        yield Static(self._render_recent(), id="turn-recent")

    def on_mount(self) -> None:
        self.set_interval(2.0, self._refresh_from_source)

    def _refresh_from_source(self) -> None:
        if self._turn_source is None:
            return
        snapshot = self._turn_source.get_current()
        if snapshot is None:
            return
        self.refresh_data(current=snapshot.current, recent=snapshot.recent)

    def _render_current(self) -> str:
        if self._current is None:
            return "Current\n—"
        t = self._current
        lines = [
            "Current",
            f"State      {t.phase}",
            f"Inbound    {_trunc(t.inbound_text)}",
            f"Model      {t.model_name}",
            f"Provider   {t.provider}",
            f"Turns      {t.context_turn_count}",
        ]
        if t.token_count is not None:
            lines.append(f"Tokens     {t.token_count}")
        return "\n".join(lines)

    def _render_recent(self) -> str:
        if not self._recent:
            return ""
        lines = ["Recent"]
        for item in self._recent[:_RECENT_MAX]:
            ts = item.recorded_at.strftime("%H:%M:%S")
            direction = "in " if "in" in item.phase else "out"
            preview = _trunc(item.inbound_preview, 42)
            lines.append(f"{ts}  {direction}  {preview}")
        return "\n".join(lines)

    def refresh_data(
        self,
        current: CurrentTurnView | None,
        recent: list[RecentTurnItemView],
    ) -> None:
        self._current = current
        self._recent = recent
        try:
            self.query_one("#turn-current", Static).update(self._render_current())
            self.query_one("#turn-recent", Static).update(self._render_recent())
        except Exception:
            pass
