"""Unit tests for Valkey substrate settings resolution and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from resources.substrates.valkey.config import ValkeySettings


def test_valkey_settings_rejects_ambiguous_password_sources() -> None:
    """Password cannot be supplied inline and via env reference together."""
    with pytest.raises(ValidationError, match="mutually exclusive"):
        ValkeySettings(url=None, password="one", password_env="VALKEY_PASSWORD")


def test_valkey_settings_resolves_password_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Password should resolve from referenced environment variable."""
    monkeypatch.setenv("VALKEY_PASSWORD", "secret")

    settings = ValkeySettings(url=None, password_env="VALKEY_PASSWORD")

    assert settings.password == "secret"
    assert settings.url == "valkey://:secret@valkey:6379/0"


def test_valkey_settings_rejects_empty_url() -> None:
    """Empty string url must be rejected; callers must use None for split-field mode."""
    with pytest.raises(ValidationError, match="must not be empty"):
        ValkeySettings(url="")


def test_valkey_settings_builds_url_from_split_fields() -> None:
    """Settings should build URL when explicit URL is not provided."""
    settings = ValkeySettings(
        url=None,
        host="localhost",
        port=6380,
        db=4,
        username="brain",
        password="pw",
    )

    assert settings.url == "valkey://brain:pw@localhost:6380/4"


def test_valkey_settings_ignores_password_env_when_explicit_url_is_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit URL mode should not require split-field auth environment values."""
    monkeypatch.delenv("VALKEY_PASSWORD", raising=False)

    settings = ValkeySettings(
        url="valkey://example:6380/3",
        password_env="VALKEY_PASSWORD",
    )

    assert settings.url == "valkey://example:6380/3"


def test_valkey_settings_rejects_missing_password_env_when_url_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Split-field mode should fail when referenced password env var is unset."""
    monkeypatch.delenv("VALKEY_PASSWORD", raising=False)
    with pytest.raises(ValidationError, match="references missing env var"):
        ValkeySettings(url=None, password_env="VALKEY_PASSWORD")
