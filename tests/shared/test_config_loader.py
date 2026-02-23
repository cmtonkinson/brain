"""Tests for pydantic-settings-backed shared configuration loading."""

from __future__ import annotations

from pathlib import Path

from packages.brain_shared.config import load_settings


def test_load_settings_uses_brain_precedence_cascade(tmp_path: Path) -> None:
    """Init params should override env, env should override YAML, then defaults."""
    config_file = tmp_path / "brain.yaml"
    config_file.write_text(
        "\n".join(
            [
                "logging:",
                "  level: WARNING",
                "postgres:",
                "  pool_size: 7",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(
        cli_params={"logging": {"level": "DEBUG"}},
        environ={
            "BRAIN_LOGGING__LEVEL": "ERROR",
            "BRAIN_POSTGRES__POOL_SIZE": "9",
        },
        config_path=config_file,
    )

    assert settings.logging.level == "DEBUG"
    assert settings.postgres.pool_size == 9
    assert settings.embedding.max_list_limit == 500


def test_load_settings_uses_model_defaults_when_sources_missing() -> None:
    """Settings should fall back to model defaults when env and YAML are absent."""
    settings = load_settings(environ={})

    assert settings.logging.service == "brain"
    assert settings.postgres.pool_size == 5
    assert settings.logging.level == "INFO"
