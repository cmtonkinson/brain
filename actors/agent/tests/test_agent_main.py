"""Behavior tests for the stub Agent process entrypoint."""

from __future__ import annotations

from pathlib import Path

from packages.brain_shared.config import ActorSettings


def test_resolve_config_path_uses_env_override(monkeypatch) -> None:
    """Config-path helper should return a Path only when the env var is set."""
    from actors.agent import main

    monkeypatch.setenv("BRAIN_ACTORS_CONFIG_FILE", "/tmp/actors.yaml")

    assert main._resolve_config_path() == Path("/tmp/actors.yaml")


def test_resolve_config_path_returns_none_when_env_is_empty(monkeypatch) -> None:
    """Config-path helper should defer to loader defaults when unset."""
    from actors.agent import main

    monkeypatch.delenv("BRAIN_ACTORS_CONFIG_FILE", raising=False)

    assert main._resolve_config_path() is None


def test_main_loads_settings_and_exits_when_shutdown_is_requested(monkeypatch) -> None:
    """Main should load settings, then stop cleanly when the loop is interrupted."""
    from actors.agent import main

    captured: dict[str, object] = {}

    def _fake_load_actor_settings(*, config_path=None, cli_params=None, environ=None):
        del cli_params, environ
        captured["config_path"] = config_path
        return ActorSettings()

    def _fake_sleep(_seconds: float) -> None:
        main._RUNNING = False

    monkeypatch.setattr(main, "load_actor_settings", _fake_load_actor_settings)
    monkeypatch.setattr(main.time, "sleep", _fake_sleep)
    monkeypatch.setattr(main.signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_configure_logging", lambda: None)
    monkeypatch.delenv("BRAIN_ACTORS_CONFIG_FILE", raising=False)

    main.main()

    assert captured["config_path"] is None
