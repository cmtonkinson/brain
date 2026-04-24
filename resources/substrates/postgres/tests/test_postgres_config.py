"""Tests for Postgres shared configuration and engine wiring."""

from __future__ import annotations

import pytest

from resources.substrates.postgres.config import PostgresSettings
from resources.substrates.postgres.engine import create_postgres_engine


def test_postgres_config_pool_pre_ping_defaults_to_true() -> None:
    """Postgres config should enable pool pre-ping by default."""
    config = PostgresSettings(
        url="postgresql+psycopg://brain:brain@postgres:5432/brain"
    )
    assert config.pool_pre_ping is True


def test_postgres_config_pool_pre_ping_accepts_boolean_like_false() -> None:
    """Postgres config should normalize false-like values for pool pre-ping."""
    config = PostgresSettings(
        url="postgresql+psycopg://brain:brain@postgres:5432/brain",
        pool_pre_ping="false",
    )
    assert config.pool_pre_ping is False


def test_engine_uses_configured_pool_pre_ping(monkeypatch) -> None:
    """Engine builder should pass pool_pre_ping through from PostgresSettings."""
    captured: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return object()

    import resources.substrates.postgres.engine as engine_module

    monkeypatch.setattr(engine_module, "create_engine", fake_create_engine)

    config = PostgresSettings(
        url="postgresql+psycopg://brain:brain@postgres:5432/brain",
        pool_pre_ping=False,
    )

    create_postgres_engine(config)

    assert captured["pool_pre_ping"] is False


def test_url_built_from_parts_when_url_is_none() -> None:
    """Settings with url=None should construct a URL from host/port/database/user/password."""
    config = PostgresSettings(
        url=None,
        host="myhost",
        port=5433,
        database="mydb",
        user="myuser",
        password="mypass",
    )
    assert config.url == "postgresql+psycopg://myuser:mypass@myhost:5433/mydb"


def test_url_built_from_parts_when_url_is_empty_string() -> None:
    """Settings with url='' should construct a URL from split fields."""
    config = PostgresSettings(
        url="", host="h", port=5432, database="d", user="u", password="p"
    )
    assert config.url.startswith("postgresql+psycopg://")


def test_url_parts_special_chars_are_percent_encoded() -> None:
    """User/password with special characters should be percent-encoded in the URL."""
    config = PostgresSettings(
        url=None, host="h", port=5432, database="d", user="u@1", password="p@ss!"
    )
    assert "u%401" in config.url
    assert "p%40ss%21" in config.url


def test_url_missing_host_raises() -> None:
    """URL construction from parts should raise when host is empty."""
    with pytest.raises(ValueError, match="host"):
        PostgresSettings(url=None, host="", database="d", user="u", password="p")


def test_url_missing_database_raises() -> None:
    """URL construction from parts should raise when database is empty."""
    with pytest.raises(ValueError, match="database"):
        PostgresSettings(url=None, host="h", database="", user="u", password="p")


def test_url_missing_user_raises() -> None:
    """URL construction from parts should raise when user is empty."""
    with pytest.raises(ValueError, match="user"):
        PostgresSettings(url=None, host="h", database="d", user="", password="p")
