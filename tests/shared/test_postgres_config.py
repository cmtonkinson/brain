"""Tests for Postgres shared configuration and engine wiring."""

from __future__ import annotations

from packages.brain_shared.config import PostgresSettings
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
