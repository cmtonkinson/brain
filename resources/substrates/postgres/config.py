"""Pydantic settings for the Postgres substrate component."""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote_plus

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from pydantic import BaseModel, Field, model_validator
from resources.substrates.postgres.component import RESOURCE_COMPONENT_ID


class PostgresSettings(BaseModel):
    """Postgres connectivity and pooling configuration."""

    url: str | None = "postgresql+psycopg://brain:brain@postgres:5432/brain"
    pool_size: int = Field(default=5, gt=0)
    max_overflow: int = Field(default=10, ge=0)
    pool_timeout_seconds: float = Field(default=30.0, gt=0)
    pool_pre_ping: bool = True
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    health_timeout_seconds: float = Field(default=1.0, gt=0)
    sslmode: Literal[
        "disable",
        "allow",
        "prefer",
        "require",
        "verify-ca",
        "verify-full",
    ] = "prefer"
    host: str = "postgres"
    port: int = 5432
    database: str = "brain"
    user: str = "brain"
    password: str = "brain"

    @model_validator(mode="after")
    def _resolve_url(self) -> "PostgresSettings":
        """Build URL from split fields when explicit URL is omitted."""
        if self.url is not None and self.url.strip() != "":
            self.url = self.url.strip()
            return self
        self.url = _build_postgres_url_from_parts(self)
        return self


def _build_postgres_url_from_parts(postgres: PostgresSettings) -> str:
    """Construct SQLAlchemy psycopg URL from split Postgres fields."""
    host = postgres.host.strip()
    port = postgres.port
    database = postgres.database.strip()
    user = postgres.user.strip()
    password = postgres.password.strip()

    if host == "":
        raise ValueError(
            "components.substrate.postgres.host is required when url is unset"
        )
    if database == "":
        raise ValueError(
            "components.substrate.postgres.database is required when url is unset"
        )
    if user == "":
        raise ValueError(
            "components.substrate.postgres.user is required when url is unset"
        )

    return (
        "postgresql+psycopg://"
        f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database)}"
    )


def resolve_postgres_settings(settings: BrainSettings) -> PostgresSettings:
    """Resolve Postgres substrate settings from ``components.substrate.postgres``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=PostgresSettings,
    )
