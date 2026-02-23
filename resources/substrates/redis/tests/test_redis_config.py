"""Unit tests for Redis substrate settings resolution and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from resources.substrates.redis.config import RedisSettings


def test_redis_settings_rejects_ambiguous_password_sources() -> None:
    """Password cannot be supplied inline and via env reference together."""
    with pytest.raises(ValidationError, match="mutually exclusive"):
        RedisSettings(url=None, password="one", password_env="REDIS_PASSWORD")


def test_redis_settings_resolves_password_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Password should resolve from referenced environment variable."""
    monkeypatch.setenv("REDIS_PASSWORD", "secret")

    settings = RedisSettings(url=None, password_env="REDIS_PASSWORD")

    assert settings.password == "secret"
    assert settings.url == "redis://:secret@redis:6379/0"


def test_redis_settings_builds_url_from_split_fields() -> None:
    """Settings should build URL when explicit URL is not provided."""
    settings = RedisSettings(
        url="",
        host="localhost",
        port=6380,
        db=4,
        username="brain",
        password="pw",
    )

    assert settings.url == "redis://brain:pw@localhost:6380/4"


def test_redis_settings_ignores_password_env_when_explicit_url_is_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit URL mode should not require split-field auth environment values."""
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)

    settings = RedisSettings(
        url="redis://example:6380/3",
        password_env="REDIS_PASSWORD",
    )

    assert settings.url == "redis://example:6380/3"


def test_redis_settings_rejects_missing_password_env_when_url_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Split-field mode should fail when referenced password env var is unset."""
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    with pytest.raises(ValidationError, match="references missing env var"):
        RedisSettings(url=None, password_env="REDIS_PASSWORD")
