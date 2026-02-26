"""Tests for pydantic-settings-backed shared configuration loading."""

from __future__ import annotations

from pathlib import Path

from packages.brain_shared.config import load_settings, resolve_component_settings
from resources.substrates.postgres.config import PostgresSettings
from services.state.embedding_authority.component import SERVICE_COMPONENT_ID
from services.state.embedding_authority.config import EmbeddingServiceSettings


def test_load_settings_uses_brain_precedence_cascade(tmp_path: Path) -> None:
    """Init params should override env, env should override YAML, then defaults."""
    config_file = tmp_path / "brain.yaml"
    config_file.write_text(
        "\n".join(
            [
                "logging:",
                "  level: WARNING",
                "components:",
                "  substrate:",
                "    postgres:",
                "      pool_size: 7",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(
        cli_params={"logging": {"level": "DEBUG"}},
        environ={
            "BRAIN_LOGGING__LEVEL": "ERROR",
            "BRAIN_COMPONENTS__CORE_BOOT__BOOT_RETRY_ATTEMPTS": "4",
            "BRAIN_COMPONENTS__SUBSTRATE__POSTGRES__POOL_SIZE": "9",
        },
        config_path=config_file,
    )

    postgres = resolve_component_settings(
        settings=settings,
        component_id="substrate_postgres",
        model=PostgresSettings,
    )
    embedding = resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=EmbeddingServiceSettings,
    )

    assert settings.logging.level == "DEBUG"
    assert settings.components.core_boot.boot_retry_attempts == 4
    assert postgres.pool_size == 9
    assert embedding.max_list_limit == 500


def test_load_settings_uses_model_defaults_when_sources_missing() -> None:
    """Settings should fall back to model defaults when env and YAML are absent."""
    settings = load_settings(environ={})
    postgres = resolve_component_settings(
        settings=settings,
        component_id="substrate_postgres",
        model=PostgresSettings,
    )

    assert settings.logging.service == "brain"
    assert postgres.pool_size == 5
    assert settings.logging.level == "INFO"
    assert settings.components.core_boot.boot_retry_attempts == 3
