"""Tests for ConsoleConfig defaults, validation, and load_console_config."""

from __future__ import annotations

import pytest

from actors.console.config import ConsoleConfig


def test_tz_property_resolves() -> None:
    """tz property must return a ZoneInfo matching preferred_timezone."""
    from zoneinfo import ZoneInfo

    cfg = ConsoleConfig(preferred_timezone="America/New_York")
    assert cfg.tz == ZoneInfo("America/New_York")


def test_tz_property_default_utc() -> None:
    """Default preferred_timezone 'UTC' must resolve without error."""
    from zoneinfo import ZoneInfo

    cfg = ConsoleConfig()
    assert cfg.tz == ZoneInfo("UTC")


def test_config_is_immutable() -> None:
    """ConsoleConfig is frozen; mutation must raise."""
    from pydantic import ValidationError

    cfg = ConsoleConfig()
    with pytest.raises((ValidationError, AttributeError, TypeError)):
        cfg.host = "10.0.0.1"  # type: ignore[misc]


def test_invalid_timezone_rejected() -> None:
    """ConsoleConfig rejects an unrecognized timezone string at construction time."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ConsoleConfig(preferred_timezone="Not/A/Timezone")


def test_load_console_config_sources_from_actor_and_core_settings(
    monkeypatch,
) -> None:
    """load_console_config assembles ConsoleConfig from actor settings and core profile."""
    from unittest.mock import MagicMock
    import actors.console.config as config_mod

    mock_actor = MagicMock()
    mock_actor.core.host = "10.0.0.2"
    mock_actor.core.port = 9000
    mock_actor.core.timeout_seconds = 15.0
    mock_actor.console.poll_timeout_seconds = 5.0
    mock_actor.console.poll_error_backoff_seconds = 2.0
    mock_actor.console.input_max_lines = 20
    mock_actor.console.editor = "nano"
    monkeypatch.setattr(config_mod, "load_actor_settings", lambda: mock_actor)

    mock_core = MagicMock()
    mock_core.profile.preferred_timezone = "Europe/London"
    monkeypatch.setattr(config_mod, "load_core_settings", lambda: mock_core)

    monkeypatch.setenv("EDITOR", "emacs")

    cfg = config_mod.load_console_config()

    assert cfg.host == "10.0.0.2"
    assert cfg.port == 9000
    assert cfg.timeout_seconds == 15.0
    assert cfg.poll_timeout_seconds == 5.0
    assert cfg.poll_error_backoff_seconds == 2.0
    assert cfg.input_max_lines == 20
    assert cfg.editor == "emacs"  # EDITOR env var takes precedence over actor setting
    assert cfg.preferred_timezone == "Europe/London"


def test_load_console_config_editor_falls_back_to_actor_setting(
    monkeypatch,
) -> None:
    """When EDITOR env var is unset, load_console_config uses actor settings editor."""
    monkeypatch.delenv("EDITOR", raising=False)

    from unittest.mock import MagicMock
    import actors.console.config as config_mod

    mock_actor = MagicMock()
    mock_actor.core.host = "127.0.0.1"
    mock_actor.core.port = 8898
    mock_actor.core.timeout_seconds = 60.0
    mock_actor.console.poll_timeout_seconds = 30.0
    mock_actor.console.poll_error_backoff_seconds = 1.0
    mock_actor.console.input_max_lines = 10
    mock_actor.console.editor = "vim"
    monkeypatch.setattr(config_mod, "load_actor_settings", lambda: mock_actor)

    mock_core = MagicMock()
    mock_core.profile.preferred_timezone = "UTC"
    monkeypatch.setattr(config_mod, "load_core_settings", lambda: mock_core)

    cfg = config_mod.load_console_config()

    assert cfg.editor == "vim"
    assert cfg.poll_error_backoff_seconds == 1.0
    assert cfg.input_max_lines == 10
