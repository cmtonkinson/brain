"""Tests for HostPane rendering logic."""

from __future__ import annotations

from datetime import datetime, timezone

from lib.dashboard.models.host import HostSnapshotView
from lib.dashboard.panes.host import HostPane, _format_uptime, _humanize_rate_bytes


def _snapshot(**kwargs) -> HostSnapshotView:
    defaults = dict(
        cpu_percent=23.2,
        memory_percent=61.1,
        load_1m=2.31,
        load_5m=2.04,
        load_15m=1.88,
        disk_percent=74.0,
        io_read_rate_bytes=12 * 1024 * 1024,
        io_write_rate_bytes=4 * 1024 * 1024,
        uptime_seconds=2 * 24 * 60 * 60 + 4 * 60 * 60,
        battery_percent=82.0,
        battery_charging=True,
        sampled_at=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return HostSnapshotView(**defaults)


def test_host_pane_no_data_renders_dash() -> None:
    pane = HostPane()
    assert pane._render_body() == "Host\n—"


def test_host_pane_renders_expected_rows() -> None:
    pane = HostPane(snapshot=_snapshot())
    text = pane._render_body()
    assert "CPU   23%" in text
    assert "Mem   61%" in text
    assert "Load  2.31 2.04 1.88" in text
    assert "Disk  74%" in text
    assert "I/O   r12M w4M" in text
    assert "Power 82% charging" in text
    assert "Up    2d 04h" in text


def test_host_pane_omits_power_row_without_battery() -> None:
    pane = HostPane(
        snapshot=_snapshot(battery_percent=None, battery_charging=None),
    )
    text = pane._render_body()
    assert "Power" not in text
    assert "Up    2d 04h" in text


def test_host_pane_unknown_metrics_render_unknown_markers() -> None:
    pane = HostPane(
        snapshot=_snapshot(
            cpu_percent=None,
            memory_percent=None,
            load_1m=None,
            load_5m=None,
            load_15m=None,
            disk_percent=None,
            io_read_rate_bytes=None,
            io_write_rate_bytes=None,
            uptime_seconds=None,
            battery_percent=None,
            battery_charging=None,
        )
    )
    text = pane._render_body()
    assert "CPU   ??" in text
    assert "Mem   ??" in text
    assert "Load  ?? ?? ??" in text
    assert "Disk  ??" in text
    assert "I/O   r?? w??" in text
    assert "Up    ??" in text


def test_humanize_rate_bytes_uses_compact_units() -> None:
    assert _humanize_rate_bytes(1536) == "1.5K"
    assert _humanize_rate_bytes(10 * 1024 * 1024) == "10M"


def test_format_uptime_prefers_compact_ranges() -> None:
    assert _format_uptime(59) == "59s"
    assert _format_uptime(5 * 60 + 7) == "5m 07s"
    assert _format_uptime(2 * 60 * 60 + 9 * 60) == "2h 09m"
