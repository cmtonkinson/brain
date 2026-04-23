"""Log pane: live stream of normalized dashboard log events."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import RichLog, Static

from lib.dashboard.data_sources.logs import LogBuffer
from lib.dashboard.models.log_event import DashboardLogEvent
from lib.dashboard.panes.base import BaseView


class LogPane(BaseView):
    """Live log event stream with freeze/follow and filter support."""

    view_id = "log"
    view_title = "Log"

    DEFAULT_CSS = """
    LogPane { layout: vertical; height: 1fr; }
    LogPane > #log-status { height: 1; }
    LogPane > #log-output { height: 1fr; }
    """

    BINDINGS = [
        Binding("f", "toggle_follow", "Follow", show=True),
        Binding("c", "clear_filters", "Clear filters", show=False),
    ]

    following: reactive[bool] = reactive(True)
    filter_component: reactive[str] = reactive("")
    filter_level: reactive[str] = reactive("")
    filter_text: reactive[str] = reactive("")

    def __init__(self, buffer: LogBuffer | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._buffer = buffer if buffer is not None else LogBuffer()

    def compose(self) -> ComposeResult:
        yield Static(self._status_line(), id="log-status")
        yield RichLog(id="log-output", highlight=True, markup=True, wrap=True)

    def on_mount(self) -> None:
        self.set_interval(0.5, self._refresh_log)

    def _status_line(self) -> str:
        mode = "FOLLOW" if self.following else "FROZEN"
        filters = []
        if self.filter_component:
            filters.append(f"component={self.filter_component}")
        if self.filter_level:
            filters.append(f"level={self.filter_level}")
        if self.filter_text:
            filters.append(f"text={self.filter_text!r}")
        filter_str = "  " + " | ".join(filters) if filters else ""
        return f"[{mode}]{filter_str}"

    def _matches(self, event: DashboardLogEvent) -> bool:
        if self.filter_component and event.component != self.filter_component:
            return False
        if self.filter_level and event.level != self.filter_level.upper():
            return False
        if self.filter_text and self.filter_text.lower() not in event.message.lower():
            return False
        return True

    def _format_event(self, event: DashboardLogEvent) -> str:
        ts = event.timestamp.strftime("%H:%M:%S")
        level_color = {
            "ERROR": "red",
            "WARNING": "yellow",
            "WARN": "yellow",
            "DEBUG": "dim",
            "INFO": "green",
        }.get(event.level, "white")
        return f"[dim]{ts}[/dim] [{level_color}]{event.level:<7}[/{level_color}] [cyan]{event.component}[/cyan] {event.message}"

    def _refresh_log(self) -> None:
        if not self.following:
            return
        try:
            log_widget = self.query_one("#log-output", RichLog)
            status = self.query_one("#log-status", Static)
        except Exception as e:
            self.log.error(f"LogPane._refresh_log query failed: {e}")
            return
        status.update(self._status_line())
        events = [e for e in self._buffer.get_all() if self._matches(e)]
        log_widget.clear()
        for event in events[-500:]:
            log_widget.write(self._format_event(event))

    def action_toggle_follow(self) -> None:
        self.following = not self.following
        try:
            status = self.query_one("#log-status", Static)
            status.update(self._status_line())
        except Exception:
            pass

    def action_clear_filters(self) -> None:
        self.filter_component = ""
        self.filter_level = ""
        self.filter_text = ""
        self._refresh_log()
