"""Unit tests for YAML configuration loading."""

import pytest

import config as config_module


def _clear_env(monkeypatch, keys):
    """Clear environment variables for config tests."""
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def test_yaml_precedence(monkeypatch, tmp_path):
    """Environment variables override secrets, user, and default YAML."""
    defaults = tmp_path / "defaults.yml"
    user_cfg = tmp_path / "user.yml"
    secrets = tmp_path / "secrets.yml"

    defaults.write_text(
        "\n".join(
            [
                "obsidian:",
                "  api_key: default-key",
                "  vault_path: /vault",
                "signal:",
                "  allowed_senders_by_channel:",
                "    signal:",
                "      - \"+15551234567\"",
                "user:",
                "  name: default-user",
                "llm:",
                "  timeout: 100",
                "qdrant:",
                "  url: http://default",
            ]
        ),
        encoding="utf-8",
    )
    user_cfg.write_text(
        "\n".join(
            [
                "user:",
                "  name: user-override",
                "llm:",
                "  timeout: 200",
                "qdrant:",
                "  url: http://user",
            ]
        ),
        encoding="utf-8",
    )
    secrets.write_text(
        "\n".join(
            [
                "user:",
                "  name: secrets-override",
                "llm:",
                "  timeout: 300",
                "qdrant:",
                "  url: http://secrets",
            ]
        ),
        encoding="utf-8",
    )

    _clear_env(
        monkeypatch,
        [
            "OBSIDIAN_API_KEY",
            "OBSIDIAN_VAULT_PATH",
            "ALLOWED_SENDERS",
            "ALLOWED_SENDERS_BY_CHANNEL",
            "USER",
            "LLM_TIMEOUT",
        ],
    )
    monkeypatch.setenv("USER", "env-user")
    monkeypatch.setenv("LLM_TIMEOUT", "400")

    monkeypatch.setattr(config_module, "_DEFAULT_CONFIG_PATH", defaults)
    monkeypatch.setattr(config_module, "_USER_CONFIG_PATHS", [user_cfg])
    monkeypatch.setattr(config_module, "_USER_SECRETS_PATHS", [secrets])

    settings = config_module.Settings()

    assert settings.user.name == "env-user"
    assert settings.llm.timeout == 400
    assert settings.qdrant.url == "http://secrets"


def test_missing_yaml_files(monkeypatch, tmp_path):
    """Missing YAML files fall back to environment settings."""
    missing_default = tmp_path / "missing-default.yml"
    missing_user = tmp_path / "missing-user.yml"
    missing_secrets = tmp_path / "missing-secrets.yml"

    _clear_env(
        monkeypatch,
        [
            "OBSIDIAN_API_KEY",
            "OBSIDIAN_VAULT_PATH",
            "ALLOWED_SENDERS",
            "ALLOWED_SENDERS_BY_CHANNEL",
        ],
    )
    monkeypatch.setenv("OBSIDIAN_API_KEY", "env-key")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/env-vault")
    monkeypatch.setenv("ALLOWED_SENDERS", "[\"+15551234567\"]")

    monkeypatch.setattr(config_module, "_DEFAULT_CONFIG_PATH", missing_default)
    monkeypatch.setattr(config_module, "_USER_CONFIG_PATHS", [missing_user])
    monkeypatch.setattr(config_module, "_USER_SECRETS_PATHS", [missing_secrets])

    settings = config_module.Settings()

    assert settings.obsidian.api_key == "env-key"
    assert settings.obsidian.vault_path == "/env-vault"


def test_non_mapping_yaml_raises(monkeypatch, tmp_path):
    """Non-mapping YAML raises a validation error."""
    defaults = tmp_path / "defaults.yml"
    defaults.write_text("- just\n- a\n- list\n", encoding="utf-8")

    monkeypatch.setattr(config_module, "_DEFAULT_CONFIG_PATH", defaults)
    monkeypatch.setattr(config_module, "_USER_CONFIG_PATHS", [])
    monkeypatch.setattr(config_module, "_USER_SECRETS_PATHS", [])

    with pytest.raises(ValueError, match="Config file must contain a mapping"):
        config_module.Settings()


def test_legacy_llm_yaml_is_mapped(monkeypatch, tmp_path):
    """Legacy litellm/ollama keys map into llm configuration."""
    defaults = tmp_path / "defaults.yml"
    defaults.write_text(
        "\n".join(
            [
                "obsidian:",
                "  api_key: default-key",
                "  vault_path: /vault",
                "signal:",
                "  allowed_senders_by_channel:",
                "    signal:",
                "      - \"+15551234567\"",
                "litellm:",
                "  model: claude-sonnet-4-20250514",
                "  base_url: http://llm.local",
                "  timeout: 123",
                "ollama:",
                "  url: http://embeddings.local",
                "  embed_model: mxbai-embed-large",
            ]
        ),
        encoding="utf-8",
    )

    _clear_env(
        monkeypatch,
        [
            "OBSIDIAN_API_KEY",
            "OBSIDIAN_VAULT_PATH",
            "ALLOWED_SENDERS",
            "ALLOWED_SENDERS_BY_CHANNEL",
        ],
    )

    monkeypatch.setattr(config_module, "_DEFAULT_CONFIG_PATH", defaults)
    monkeypatch.setattr(config_module, "_USER_CONFIG_PATHS", [])
    monkeypatch.setattr(config_module, "_USER_SECRETS_PATHS", [])

    settings = config_module.Settings()

    assert settings.llm.model == "claude-sonnet-4-20250514"
    assert settings.llm.base_url == "http://llm.local"
    assert settings.llm.timeout == 123
    assert settings.llm.embed_base_url == "http://embeddings.local"
    assert settings.llm.embed_model == "mxbai-embed-large"
