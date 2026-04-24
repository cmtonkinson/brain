"""Tests for HealthHeader rendering logic."""

from __future__ import annotations

from datetime import datetime, timezone

from lib.dashboard.data_sources.health import COMPONENTS
from lib.dashboard.models.health import ComponentHealth
from lib.dashboard.widgets.health_header import _render_health


def _health(name: str, state: str) -> ComponentHealth:
    return ComponentHealth(
        name=name, state=state, checked_at=datetime(2024, 1, 1, tzinfo=timezone.utc)
    )


def test_render_health_all_unknown_when_empty():
    text = _render_health([])
    assert text.count("??") == 7


def test_render_health_ok_green():
    text = _render_health([_health("core", "ok")])
    assert "OK" in text
    assert "green" in text


def test_render_health_no_red():
    text = _render_health([_health("postgres", "no")])
    assert "NO" in text
    assert "red" in text


def test_render_health_unknown_dim():
    text = _render_health([_health("valkey", "unknown")])
    # valkey should show ??
    assert "??" in text


def test_render_health_component_order():
    components = [_health(name, "ok") for name in COMPONENTS]
    text = _render_health(components)
    # all 7 component names present in order
    positions = [text.index(name) for name in COMPONENTS]
    assert positions == sorted(positions)


def test_render_health_two_char_tokens_only():
    components = [_health("core", "ok"), _health("assistant", "no")]
    text = _render_health(components)
    # Should not contain NOK (old 3-char token)
    assert "NOK" not in text


def test_render_health_missing_component_shows_unknown():
    # Only provide core; other 6 should show ??
    text = _render_health([_health("core", "ok")])
    assert text.count("??") == 6
