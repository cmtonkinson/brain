"""Typed configuration models for Brain runtime settings."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator
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


class OperatorProfileSettings(BaseModel):
    """Operator identity profile settings shared across action services."""

    signal_e164: str = "+10000000000"


class ProfileSettings(BaseModel):
    """Root profile settings for operator identity and webhook verification."""

    operator: OperatorProfileSettings = Field(default_factory=OperatorProfileSettings)
    default_country_code: str = "US"
    webhook_shared_secret: str = "replace-me"


class CoreBootSettings(BaseModel):
    """Core boot framework settings under ``components.core_boot``."""

    run_migrations_on_startup: bool = True
    readiness_poll_interval_seconds: float = Field(default=0.25, gt=0)
    readiness_timeout_seconds: float = Field(default=30.0, gt=0)
    boot_retry_attempts: int = Field(default=3, gt=0)
    boot_retry_delay_seconds: float = Field(default=0.5, ge=0)
    boot_timeout_seconds: float = Field(default=30.0, gt=0)


class ComponentNamespaceSettings(BaseModel):
    """Namespace map for grouped component settings under ``components.<kind>``."""

    model_config = ConfigDict(extra="allow")


class ComponentsSettings(BaseModel):
    """Typed ``components`` subtree with support for component-local extras."""

    model_config = ConfigDict(extra="allow")

    core_boot: CoreBootSettings = Field(default_factory=CoreBootSettings)
    service: ComponentNamespaceSettings = Field(
        default_factory=ComponentNamespaceSettings
    )
    adapter: ComponentNamespaceSettings = Field(
        default_factory=ComponentNamespaceSettings
    )
    substrate: ComponentNamespaceSettings = Field(
        default_factory=ComponentNamespaceSettings
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_flat_component_keys(cls, value: object) -> object:
        """Reject legacy flat component keys in favor of grouped namespaces."""
        if not isinstance(value, dict):
            return value
        flat_prefixed_keys = tuple(
            key
            for key in value
            if isinstance(key, str)
            and key.startswith(("actor_", "service_", "adapter_", "substrate_"))
        )
        if not flat_prefixed_keys:
            return value

        bad_key = flat_prefixed_keys[0]
        kind, _, name = bad_key.partition("_")
        raise ValueError(
            f"components.{bad_key} is invalid; use components.{kind}.{name} instead"
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
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    profile: ProfileSettings = Field(default_factory=ProfileSettings)
    components: ComponentsSettings = Field(default_factory=ComponentsSettings)

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


TComponentSettings = TypeVar("TComponentSettings", bound=BaseModel)


def resolve_component_settings(
    *,
    settings: BrainSettings,
    component_id: str,
    model: type[TComponentSettings],
) -> TComponentSettings:
    """Resolve one component settings object from grouped ``components`` keys."""
    raw_components = settings.components.model_dump(mode="python")
    kind, separator, name = component_id.partition("_")
    if separator and kind in {"actor", "service", "adapter", "substrate"}:
        namespace = raw_components.get(kind, {})
        namespace_path = f"components.{kind}"
        if not isinstance(namespace, dict):
            raise TypeError(f"{namespace_path} must resolve to an object mapping")
        resolved = namespace.get(name, {})
        source_path = f"{namespace_path}.{name}"
    else:
        # Non-prefixed component settings (for example core_boot) remain flat.
        resolved = raw_components.get(component_id, {})
        source_path = f"components.{component_id}"

    if not isinstance(resolved, dict):
        raise TypeError(f"{source_path} must resolve to an object mapping")
    return model.model_validate(resolved)
