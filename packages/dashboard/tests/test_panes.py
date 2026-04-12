"""Tests for dashboard pane widgets."""

from __future__ import annotations

from datetime import datetime, timezone

from packages.dashboard.data_sources.logs import LogBuffer
from packages.dashboard.models.log_event import DashboardLogEvent
from packages.dashboard.panes import BaseView, EmptyPicker
from packages.dashboard.panes import (
    HostPane,
    LLMPane,
    LogPane,
    PolicyPane,
    TracePane,
    TurnPane,
)
from packages.dashboard.panes.empty_picker import VIEW_CHOICES


def test_base_view_has_view_id():
    class MyView(BaseView):
        view_id = "myview"
        view_title = "My View"

    v = MyView()
    assert v.view_id == "myview"
    assert v.view_title == "My View"


def test_log_pane_has_correct_view_id():
    assert LogPane.view_id == "log"


def test_trace_pane_has_correct_view_id():
    assert TracePane.view_id == "trace"


def test_turn_pane_has_correct_view_id():
    assert TurnPane.view_id == "turn"


def test_policy_pane_has_correct_view_id():
    assert PolicyPane.view_id == "policy"


def test_host_pane_has_correct_view_id():
    assert HostPane.view_id == "host"


def test_llm_pane_has_correct_view_id():
    assert LLMPane.view_id == "llm"


def test_empty_picker_view_choices_not_empty():
    assert len(VIEW_CHOICES) > 0


def test_empty_picker_sole_flag():
    picker = EmptyPicker(is_sole=True)
    assert picker._is_sole is True


def test_empty_picker_not_sole():
    picker = EmptyPicker(is_sole=False)
    assert picker._is_sole is False


# --- LogPane tests ---


def _make_event(**kwargs) -> DashboardLogEvent:
    defaults = dict(
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        level="INFO",
        component="core",
        source="file",
        message="test message",
    )
    defaults.update(kwargs)
    return DashboardLogEvent(**defaults)


def test_log_pane_follow_default():
    pane = LogPane()
    assert pane.following is True


def test_log_pane_filter_component():
    buf = LogBuffer()
    buf.append(_make_event(component="core", message="core msg"))
    buf.append(_make_event(component="agent", message="agent msg"))
    pane = LogPane(buffer=buf)
    pane.filter_component = "core"
    matched = [e for e in buf.get_all() if pane._matches(e)]
    assert len(matched) == 1
    assert matched[0].component == "core"


def test_log_pane_filter_level():
    buf = LogBuffer()
    buf.append(_make_event(level="ERROR", message="err"))
    buf.append(_make_event(level="INFO", message="info"))
    pane = LogPane(buffer=buf)
    pane.filter_level = "ERROR"
    matched = [e for e in buf.get_all() if pane._matches(e)]
    assert len(matched) == 1
    assert matched[0].level == "ERROR"


def test_log_pane_filter_text():
    buf = LogBuffer()
    buf.append(_make_event(message="connection reset"))
    buf.append(_make_event(message="everything is fine"))
    pane = LogPane(buffer=buf)
    pane.filter_text = "reset"
    matched = [e for e in buf.get_all() if pane._matches(e)]
    assert len(matched) == 1


def test_log_pane_format_event():
    pane = LogPane()
    event = _make_event(level="ERROR", component="core", message="boom")
    formatted = pane._format_event(event)
    assert "boom" in formatted
    assert "core" in formatted
