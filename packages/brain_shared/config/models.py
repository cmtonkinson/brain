"""Typed configuration models for Brain runtime settings."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "brain" / "brain.yaml"


class LoggingSettings(BaseModel):
    """Structured logging configuration shared by Brain components."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    json_output: bool = True
    service: str = "brain"
    environment: str = "dev"


class PostgresSettings(BaseModel):
    """Postgres connectivity and pooling configuration."""

    url: str | None = "postgresql+psycopg://brain:brain@postgres:5432/brain"
    pool_size: int = Field(default=5, gt=0)
    max_overflow: int = Field(default=10, ge=0)
    pool_timeout_seconds: float = Field(default=30.0, gt=0)
    pool_pre_ping: bool = True
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
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

    def validate(self) -> None:
        """Re-validate this instance against current model constraints."""
        type(self).model_validate(self.model_dump(mode="python"))


class EmbeddingServiceSettings(BaseModel):
    """Embedding Authority Service runtime configuration."""

    qdrant_url: str = "http://qdrant:6333"
    distance_metric: Literal["cosine", "dot", "euclid"] = "cosine"
    request_timeout_seconds: float = Field(default=10.0, gt=0)
    max_list_limit: int = Field(default=500, gt=0)

    def validate(self) -> None:
        """Re-validate this instance against current model constraints."""
        type(self).model_validate(self.model_dump(mode="python"))


class PublicApiOtelSettings(BaseModel):
    """Configurable OTel names for public API tracing and metrics."""

    meter_name: str = "brain.public_api"
    tracer_name: str = "brain.public_api"
    metric_public_api_calls_total: str = "brain_public_api_calls_total"
    metric_public_api_duration_ms: str = "brain_public_api_duration_ms"
    metric_public_api_errors_total: str = "brain_public_api_errors_total"
    metric_instrumentation_failures_total: str = (
        "brain_public_api_instrumentation_failures_total"
    )
    metric_qdrant_ops_total: str = "brain_qdrant_ops_total"
    metric_qdrant_op_duration_ms: str = "brain_qdrant_op_duration_ms"


class PublicApiObservabilitySettings(BaseModel):
    """Public API observability subtree."""

    otel: PublicApiOtelSettings = Field(default_factory=PublicApiOtelSettings)


class ObservabilitySettings(BaseModel):
    """Global observability configuration."""

    public_api: PublicApiObservabilitySettings = Field(
        default_factory=PublicApiObservabilitySettings
    )


class BrainSettings(BaseSettings):
    """Root runtime settings resolved from init/env/yaml/defaults sources."""

    model_config = SettingsConfigDict(
        env_prefix="BRAIN_",
        env_nested_delimiter="__",
        extra="ignore",
        nested_model_default_partial_update=True,
    )

    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    embedding: EmbeddingServiceSettings = Field(
        default_factory=EmbeddingServiceSettings
    )
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    _config_path: ClassVar[Path] = DEFAULT_CONFIG_PATH

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Apply Brain precedence: init > env > yaml > optional defaults."""
        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
            YamlConfigSettingsSource(
                settings_cls,
                yaml_file=cls._config_path,
                yaml_file_encoding="utf-8",
            ),
        ]
        return tuple(sources)


def settings_type_for(
    *,
    config_path: str | Path | None,
    env_prefix: str,
) -> type[BrainSettings]:
    """Create a settings subclass with call-site source parameters bound."""
    resolved_config_path = (
        Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    )
    model_config_data = dict(BrainSettings.model_config)
    model_config_data["env_prefix"] = env_prefix

    class BoundBrainSettings(BrainSettings):
        """Brain settings with runtime-bound source configuration."""

        model_config = SettingsConfigDict(**model_config_data)
        _config_path: ClassVar[Path] = resolved_config_path

    return BoundBrainSettings


def _build_postgres_url_from_parts(postgres: PostgresSettings) -> str:
    """Construct SQLAlchemy psycopg URL from split Postgres fields."""
    host = postgres.host.strip()
    port = postgres.port
    database = postgres.database.strip()
    user = postgres.user.strip()
    password = postgres.password.strip()

    if host == "":
        raise ValueError("postgres.host is required when postgres.url is unset")
    if database == "":
        raise ValueError("postgres.database is required when postgres.url is unset")
    if user == "":
        raise ValueError("postgres.user is required when postgres.url is unset")

    return (
        "postgresql+psycopg://"
        f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database)}"
    )
