"""Host pane: compact host-pressure summary for the dashboard."""

from __future__ import annotations

from typing import Protocol

from textual.app import ComposeResult
from textual.widgets import Static

from lib.dashboard.models.host import HostSnapshotView
from lib.dashboard.panes.base import BaseView

_REFRESH_INTERVAL = 2.0


class HostDataSource(Protocol):
    """Minimal host-data contract consumed by the Host pane."""

    def get_current(self) -> HostSnapshotView | None:
        """Return the latest normalized host snapshot."""


def _format_percent(value: float | None) -> str:
    """Render one compact percentage or an unknown marker."""

    if value is None:
        return "??"
    return f"{value:.0f}%"


def _format_load(value: float | None) -> str:
    """Render one load-average point or an unknown marker."""

    if value is None:
        return "??"
    return f"{value:.2f}"


def _humanize_rate_bytes(value: float | None) -> str:
    """Render bytes/sec into a compact single-token rate string."""

    if value is None:
        return "??"

    suffixes = ("B", "K", "M", "G", "T")
    scaled = float(value)
    suffix_index = 0
    while scaled >= 1024 and suffix_index < len(suffixes) - 1:
        scaled /= 1024
        suffix_index += 1

    if scaled >= 10 or scaled.is_integer():
        return f"{scaled:.0f}{suffixes[suffix_index]}"
    return f"{scaled:.1f}{suffixes[suffix_index]}"


def _format_uptime(seconds: int | None) -> str:
    """Render uptime in a compact human-readable form."""

    if seconds is None:
        return "??"

    days, remainder = divmod(seconds, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes, secs = divmod(remainder, 60)

    if days:
        return f"{days}d {hours:02d}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


class HostPane(BaseView):
    """Compact host snapshot focused on pressure, capacity, and uptime."""

    view_id = "host"
    view_title = "Host"

    DEFAULT_CSS = """
    HostPane { layout: vertical; height: 1fr; }
    HostPane > #host-body { height: 1fr; }
    """

    def __init__(
        self,
        host_source: HostDataSource | None = None,
        snapshot: HostSnapshotView | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._host_source = host_source
        self._snapshot = snapshot

    def compose(self) -> ComposeResult:
        yield Static(self._render_body(), id="host-body")

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self._refresh_from_source)

    def _refresh_from_source(self) -> None:
        if self._host_source is None:
            return
        snapshot = self._host_source.get_current()
        if snapshot is None:
            return
        self.refresh_data(snapshot)

    def refresh_data(self, snapshot: HostSnapshotView | None) -> None:
        """Replace pane data and refresh the mounted content widget."""

        self._snapshot = snapshot
        try:
            self.query_one("#host-body", Static).update(self._render_body())
        except Exception:
            pass

    def _render_body(self) -> str:
        if self._snapshot is None:
            return "Host\n—"

        snapshot = self._snapshot
        lines = [
            "Host",
            "",
            f"CPU   {_format_percent(snapshot.cpu_percent)}",
            f"Mem   {_format_percent(snapshot.memory_percent)}",
            (
                "Load  "
                f"{_format_load(snapshot.load_1m)} "
                f"{_format_load(snapshot.load_5m)} "
                f"{_format_load(snapshot.load_15m)}"
            ),
            f"Disk  {_format_percent(snapshot.disk_percent)}",
            (
                "I/O   "
                f"r{_humanize_rate_bytes(snapshot.io_read_rate_bytes)} "
                f"w{_humanize_rate_bytes(snapshot.io_write_rate_bytes)}"
            ),
            f"Up    {_format_uptime(snapshot.uptime_seconds)}",
        ]

        if snapshot.battery_percent is not None:
            power_state = "charging" if snapshot.battery_charging else "battery"
            lines.insert(
                -1, f"Power {_format_percent(snapshot.battery_percent)} {power_state}"
            )

        return "\n".join(lines)
