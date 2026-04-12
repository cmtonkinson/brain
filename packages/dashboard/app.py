"""Textual application for the Brain Dashboard."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container

from packages.dashboard.config import load_dashboard_config
from packages.dashboard.data_sources.health import HealthAggregator
from packages.dashboard.data_sources.logs import FileLogSource, LogBuffer
from packages.dashboard.data_sources.policy import PolicyDataSource
from packages.dashboard.data_sources.traces import TraceDataSource
from packages.dashboard.data_sources.turns import TurnDataSource
from packages.dashboard.widgets import HealthHeader, KeymapFooter
from packages.dashboard.workspace import DashboardDataSources, Workspace


class BrainDashboardApp(App[None]):
    """Out-of-band, read-only Brain observability dashboard."""

    CSS = """
    Screen { layout: vertical; }
    #root { layout: vertical; height: 100%; }
    #health-header { dock: top; height: 1; padding: 0 1; background: $boost; color: $text; }
    #workspace { height: 1fr; }
    #keymap-footer { dock: bottom; height: 1; padding: 0 1; background: $surface; color: $text-muted; }
    """

    BINDINGS = [
        Binding("ctrl+h", "focus_left", "Focus Left", show=False, priority=True),
        Binding("ctrl+l", "focus_right", "Focus Right", show=False, priority=True),
        Binding("ctrl+k", "focus_up", "Focus Up", show=False, priority=True),
        Binding("ctrl+j", "focus_down", "Focus Down", show=False, priority=True),
        Binding("tab", "focus_next", "Focus Next", show=False, priority=True),
        Binding("shift+tab", "focus_previous", "Focus Prev", show=False, priority=True),
        Binding("s", "split_horizontal", "Split H", show=False, priority=True),
        Binding("v", "split_vertical", "Split V", show=False, priority=True),
        Binding("enter", "maximize", "Maximize", show=False, priority=True),
        Binding("q", "close_view_or_pane", "Close", show=False, priority=True),
        Binding("Q", "quit", "Quit", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._config = load_dashboard_config()
        self._log_buffer = LogBuffer(max_size=self._config.logs.buffer_size)
        self._log_sources = [
            FileLogSource(
                path="logs/core.log",
                component="core",
                buffer=self._log_buffer,
                backfill_lines=self._config.logs.backfill_lines,
            ),
            FileLogSource(
                path="logs/agent.log",
                component="agent",
                buffer=self._log_buffer,
                backfill_lines=self._config.logs.backfill_lines,
            ),
        ]
        self._turn_source = TurnDataSource(
            config=self._config.postgres,
            poll_interval=self._config.data_sources.poll_seconds,
        )
        self._trace_source = TraceDataSource(
            config=self._config.postgres,
            poll_interval=self._config.data_sources.poll_seconds,
        )
        self._policy_source = PolicyDataSource(
            config=self._config.postgres,
            poll_interval=self._config.data_sources.poll_seconds,
        )
        self._data_sources = DashboardDataSources(
            log_buffer=self._log_buffer,
            turn_source=self._turn_source,
            trace_source=self._trace_source,
            policy_source=self._policy_source,
        )
        self._health_aggregator = HealthAggregator(
            config=self._config.health,
            poll_interval=self._config.data_sources.poll_seconds,
        )

    def compose(self) -> ComposeResult:
        with Container(id="root"):
            yield HealthHeader(aggregator=self._health_aggregator)
            yield Workspace(data_sources=self._data_sources)
            yield KeymapFooter()

    def on_mount(self) -> None:
        self.title = self._config.app_title
        self._health_aggregator.start()
        self._turn_source.start()
        self._trace_source.start()
        self._policy_source.start()
        for src in self._log_sources:
            src.start()

    def on_unmount(self) -> None:
        """Stop all long-running data source threads."""
        try:
            self._health_aggregator.stop()
        except Exception:
            pass
        try:
            self._turn_source.stop()
        except Exception:
            pass
        try:
            self._trace_source.stop()
        except Exception:
            pass
        try:
            self._policy_source.stop()
        except Exception:
            pass
        for src in self._log_sources:
            try:
                src.stop()
            except Exception:
                pass

    def _workspace(self) -> Workspace:
        return self.query_one(Workspace)

    def action_focus_next(self) -> None:
        self._workspace().focus_next()

    def action_focus_previous(self) -> None:
        self._workspace().focus_previous()

    def action_split_horizontal(self) -> None:
        self._workspace().split_horizontal()

    def action_split_vertical(self) -> None:
        self._workspace().split_vertical()

    def action_maximize(self) -> None:
        self._workspace().maximize()

    def action_close_view_or_pane(self) -> None:
        """Context-sensitive close: unload view if loaded, else close pane."""
        ws = self._workspace()
        if ws.focused_pane_id is None:
            return
        if ws.focused_node_view_id is not None:
            ws.close_view()
        else:
            ws.close_pane()

    def action_load_view(self, view_id: str) -> None:
        """Load a view into the currently focused pane when it is empty."""
        ws = self._workspace()
        focused = ws.focused_pane_id
        if focused is not None and ws.focused_node_view_id is None:
            ws.load_view(focused, view_id)

    def action_focus_left(self) -> None:
        self._workspace().focus_left()

    def action_focus_right(self) -> None:
        self._workspace().focus_right()

    def action_focus_up(self) -> None:
        self._workspace().focus_up()

    def action_focus_down(self) -> None:
        self._workspace().focus_down()
