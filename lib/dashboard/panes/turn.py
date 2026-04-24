"""Turn pane: current agent turn and compact recent history."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from textual.app import ComposeResult
from textual.widgets import Static

from lib.dashboard.data_sources.turns import TurnDataSource
from lib.dashboard.models.turn import CurrentTurnView, RecentTurnItemView
from lib.dashboard.panes.base import BaseView

_RECENT_MAX = 8
_TRUNCATE = 52
_REFRESH_INTERVAL = 2.0


def _trunc(text: str, n: int = _TRUNCATE) -> str:
    return text if len(text) <= n else text[:n] + "..."


def _fmt_time(value: datetime) -> str:
    """Format one timestamp for compact dashboard display."""
    return value.strftime("%H:%M:%S")


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
        recent: Sequence[RecentTurnItemView] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._turn_source = turn_source
        self._current = current
        self._recent: Sequence[RecentTurnItemView] = recent or ()

    def compose(self) -> ComposeResult:
        yield Static(self._render_current(), id="turn-current")
        yield Static(self._render_recent(), id="turn-recent")

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self._refresh_from_source)

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
        turn = self._current
        lines = [
            "Current",
            f"State      {turn.state}",
            f"Inbound    {_trunc(turn.inbound_content)}",
            f"Principal  {turn.inbound_principal}",
            f"Time       {_fmt_time(turn.inbound_time)}",
        ]
        if turn.state == "complete":
            lines.append(f"Response   {_trunc(turn.response_content or '')}")
            if turn.model:
                lines.append(f"Model      {turn.model}")
            if turn.provider:
                lines.append(f"Provider   {turn.provider}")
            if turn.reasoning_level:
                lines.append(f"Reasoning  {turn.reasoning_level}")
        elif turn.elapsed_ms is not None:
            lines.append(f"Elapsed    {turn.elapsed_ms}ms")
        if turn.token_count is not None:
            lines.append(f"Tokens     {turn.token_count}")
        return "\n".join(lines)

    def _render_recent(self) -> str:
        if not self._recent:
            return ""
        lines = ["Recent"]
        for item in self._recent[:_RECENT_MAX]:
            lines.append(
                f"{_fmt_time(item.timestamp)}  {item.direction}  {_trunc(item.summary, 42)}"
            )
        return "\n".join(lines)

    def refresh_data(
        self,
        current: CurrentTurnView | None,
        recent: Sequence[RecentTurnItemView],
    ) -> None:
        self._current = current
        self._recent = recent
        try:
            self.query_one("#turn-current", Static).update(self._render_current())
            self.query_one("#turn-recent", Static).update(self._render_recent())
        except Exception:
            pass
