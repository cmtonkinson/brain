"""Tests for pydantic-settings-backed shared configuration loading."""

from __future__ import annotations

from pathlib import Path

from packages.brain_shared.config import (
    load_core_runtime_settings,
    load_core_settings,
    resolve_component_settings,
)
from resources.substrates.postgres.config import PostgresSettings
from services.state.embedding_authority.component import SERVICE_COMPONENT_ID
from services.state.embedding_authority.config import EmbeddingServiceSettings


def test_load_core_settings_uses_brain_precedence_cascade(tmp_path: Path) -> None:
    """Init params should override env, env should override YAML, then defaults."""
    config_file = tmp_path / "core.yaml"
    config_file.write_text(
        "\n".join(
            [
                "logging:",
                "  level: WARNING",
                "boot:",
                "  boot_retry_attempts: 5",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_core_settings(
        cli_params={"logging": {"level": "DEBUG"}},
        environ={
            "BRAIN_CORE_LOGGING__LEVEL": "ERROR",
            "BRAIN_CORE_BOOT__BOOT_RETRY_ATTEMPTS": "4",
            "BRAIN_CORE_HTTP__SOCKET_PATH": "/tmp/test.sock",
        },
        config_path=config_file,
    )

    assert settings.logging.level == "DEBUG"
    assert settings.boot.boot_retry_attempts == 4
    assert settings.http.socket_path == "/tmp/test.sock"


def test_load_core_runtime_settings_resolves_substrate_component(
    tmp_path: Path,
) -> None:
    """resolve_component_settings should find substrate config from resources settings."""
    resources_file = tmp_path / "resources.yaml"
    resources_file.write_text(
        "\n".join(
            [
                "substrate:",
                "  postgres:",
                "    pool_size: 7",
            ]
        ),
        encoding="utf-8",
    )

    runtime = load_core_runtime_settings(
        resources_config_path=resources_file,
        core_config_path=tmp_path / "core.yaml",
    )

    postgres = resolve_component_settings(
        settings=runtime,
        component_id="substrate_postgres",
        model=PostgresSettings,
    )
    assert postgres.pool_size == 7


def test_load_core_runtime_settings_resolves_service_component(tmp_path: Path) -> None:
    """resolve_component_settings should find service config from core settings."""
    core_file = tmp_path / "core.yaml"
    core_file.write_text(
        "\n".join(
            [
                "service:",
                "  embedding_authority:",
                "    max_list_limit: 250",
            ]
        ),
        encoding="utf-8",
    )

    runtime = load_core_runtime_settings(
        core_config_path=core_file,
        resources_config_path=tmp_path / "resources.yaml",
    )

    embedding = resolve_component_settings(
        settings=runtime,
        component_id=str(SERVICE_COMPONENT_ID),
        model=EmbeddingServiceSettings,
    )
    assert embedding.max_list_limit == 250


def test_load_core_settings_uses_model_defaults_when_sources_missing(
    tmp_path: Path,
) -> None:
    """Settings should fall back to model defaults when env and YAML are absent."""
    settings = load_core_settings(config_path=tmp_path / "core.yaml", environ={})

    assert settings.logging.service == "brain"
    assert settings.logging.level == "INFO"
    assert settings.boot.boot_retry_attempts == 3
    assert settings.http.socket_path == "/app/config/generated/brain.sock"


def test_load_core_settings_applies_secrets_yaml_over_core_yaml(tmp_path: Path) -> None:
    """Optional secrets.yaml should override matching keys from core.yaml only."""
    config_file = tmp_path / "core.yaml"
    config_file.write_text(
        "\n".join(
            [
                "profile:",
                "  webhook_shared_secret: public-secret",
                "logging:",
                "  level: WARNING",
            ]
        ),
        encoding="utf-8",
    )
    secrets_file = tmp_path / "secrets.yaml"
    secrets_file.write_text(
        "\n".join(
            [
                "profile:",
                "  webhook_shared_secret: private-secret",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_core_settings(config_path=config_file, environ={})

    assert settings.profile.webhook_shared_secret == "private-secret"
    assert settings.logging.level == "WARNING"


def test_load_core_settings_ignores_secrets_yaml_when_missing(tmp_path: Path) -> None:
    """core.yaml values should be used unchanged when secrets.yaml does not exist."""
    config_file = tmp_path / "core.yaml"
    config_file.write_text(
        "\n".join(
            [
                "profile:",
                "  webhook_shared_secret: public-secret",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_core_settings(config_path=config_file, environ={})

    assert settings.profile.webhook_shared_secret == "public-secret"
