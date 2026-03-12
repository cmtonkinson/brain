"""Typed configuration models for Brain runtime settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import PydanticUndefined
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULT_CORE_CONFIG_PATH = Path.home() / ".config" / "brain" / "core.yaml"
DEFAULT_RESOURCES_CONFIG_PATH = Path.home() / ".config" / "brain" / "resources.yaml"
DEFAULT_ACTORS_CONFIG_PATH = Path.home() / ".config" / "brain" / "actors.yaml"
SECRETS_CONFIG_FILENAME = "secrets.yaml"


class LoggingSettings(BaseModel):
    """Structured logging configuration shared by Brain components."""

    level: Literal["VERBOSE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    file_capture_enabled: bool = False
    file_capture_level: Literal[
        "VERBOSE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    ] = "VERBOSE"
    file_capture_directory: str = "logs"
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

    signal_contact_e164: str = "+12222222222"


class ProfileSettings(BaseModel):
    """Root profile settings for operator identity and webhook verification."""

    operator: OperatorProfileSettings = Field(default_factory=OperatorProfileSettings)
    default_dial_code: str = "+1"
    webhook_shared_secret: str = "replace-me"
    operator_name: str = "Operator"
    brain_name: str = "Brain"
    brain_verbosity: str = "normal"
    system_prompt_append: str | None = None


class CoreBootSettings(BaseModel):
    """Core boot framework settings under ``boot``."""

    run_migrations_on_startup: bool = True
    readiness_poll_interval_seconds: float = Field(default=0.25, gt=0)
    readiness_timeout_seconds: float = Field(default=30.0, gt=0)
    boot_retry_attempts: int = Field(default=3, gt=0)
    boot_retry_delay_seconds: float = Field(default=0.5, ge=0)
    boot_timeout_seconds: float = Field(default=30.0, gt=0)


class CoreHttpSettings(BaseModel):
    """Core HTTP runtime settings under ``http``."""

    host: str = "0.0.0.0"
    port: int = Field(default=8898, ge=1, le=65535)


class CoreHealthSettings(BaseModel):
    """Core aggregate health policy under ``health``."""

    max_timeout_seconds: float = Field(default=1.0, gt=0)


class ComponentNamespaceSettings(BaseModel):
    """Namespace map for grouped component settings."""

    model_config = ConfigDict(extra="allow")


def _yaml_source_if_exists(
    settings_cls: type[BaseSettings], path: Path
) -> YamlConfigSettingsSource | None:
    """Return a YAML source for path only if the file exists."""
    if not path.exists():
        return None
    return YamlConfigSettingsSource(
        settings_cls, yaml_file=path, yaml_file_encoding="utf-8"
    )


def _merged_yaml_source(
    settings_cls: type[BaseSettings],
    *,
    config_path: Path,
) -> YamlConfigSettingsSource:
    """Return one deep-merged YAML source over config + optional secrets."""
    return YamlConfigSettingsSource(
        settings_cls,
        yaml_file=[config_path, config_path.parent / SECRETS_CONFIG_FILENAME],
        yaml_file_encoding="utf-8",
        deep_merge=True,
    )


class CoreSettings(BaseSettings):
    """Core service runtime settings — loaded from core.yaml."""

    model_config = SettingsConfigDict(
        env_prefix="BRAIN_CORE_",
        env_nested_delimiter="__",
        extra="ignore",
        nested_model_default_partial_update=True,
    )

    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    profile: ProfileSettings = Field(default_factory=ProfileSettings)
    boot: CoreBootSettings = Field(default_factory=CoreBootSettings)
    http: CoreHttpSettings = Field(default_factory=CoreHttpSettings)
    health: CoreHealthSettings = Field(default_factory=CoreHealthSettings)
    service: ComponentNamespaceSettings = Field(
        default_factory=ComponentNamespaceSettings
    )

    _config_path: ClassVar[Path] = DEFAULT_CORE_CONFIG_PATH

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Apply Core precedence: init > env > secrets.yaml > core.yaml > defaults."""
        config_path = cls._config_path
        return (
            init_settings,
            env_settings,
            _merged_yaml_source(settings_cls, config_path=config_path),
        )


class ResourcesSettings(BaseSettings):
    """Infrastructure resource settings — loaded from resources.yaml."""

    model_config = SettingsConfigDict(
        env_prefix="BRAIN_RESOURCES_",
        env_nested_delimiter="__",
        extra="ignore",
        nested_model_default_partial_update=True,
    )

    substrate: ComponentNamespaceSettings = Field(
        default_factory=ComponentNamespaceSettings
    )
    adapter: ComponentNamespaceSettings = Field(
        default_factory=ComponentNamespaceSettings
    )

    _config_path: ClassVar[Path] = DEFAULT_RESOURCES_CONFIG_PATH

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Apply Resources precedence: init > env > secrets.yaml > resources.yaml > defaults."""
        config_path = cls._config_path
        return (
            init_settings,
            env_settings,
            _merged_yaml_source(settings_cls, config_path=config_path),
        )


class ActorCoreConnectionSettings(BaseModel):
    """How actors connect to Core over TCP."""

    host: str = "127.0.0.1"
    port: int = Field(default=8898, ge=1, le=65535)
    timeout_seconds: float = 30.0


class ActorNamespaceSettings(BaseModel):
    """Per-actor identity settings."""

    model_config = ConfigDict(extra="allow")

    principal: str = "operator"
    source: str = "actor"


class CliActorSettings(ActorNamespaceSettings):
    """CLI actor identity settings."""

    source: str = "cli"


class AgentActorSettings(ActorNamespaceSettings):
    """Agent-specific settings for tool exposure and runtime identity."""

    source: str = "agent"
    capability_discovery_deny_list: tuple[str, ...] = ("attention-notify",)


class ActorSettings(BaseSettings):
    """Actor runtime settings — loaded from actors.yaml."""

    model_config = SettingsConfigDict(
        env_prefix="BRAIN_ACTORS_",
        env_nested_delimiter="__",
        extra="ignore",
        nested_model_default_partial_update=True,
    )

    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    core: ActorCoreConnectionSettings = Field(
        default_factory=ActorCoreConnectionSettings
    )
    cli: CliActorSettings = Field(default_factory=CliActorSettings)
    agent: AgentActorSettings = Field(default_factory=AgentActorSettings)
    beat: ActorNamespaceSettings = Field(
        default_factory=lambda: ActorNamespaceSettings(source="beat")
    )
    worker: ActorNamespaceSettings = Field(
        default_factory=lambda: ActorNamespaceSettings(source="worker")
    )

    _config_path: ClassVar[Path] = DEFAULT_ACTORS_CONFIG_PATH

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Apply Actors precedence: init > env > secrets.yaml > actors.yaml > defaults."""
        config_path = cls._config_path
        return (
            init_settings,
            env_settings,
            _merged_yaml_source(settings_cls, config_path=config_path),
        )


@dataclass(frozen=True, slots=True)
class CoreRuntimeSettings:
    """Combined Core + Resources settings passed to components and boot hooks."""

    core: CoreSettings
    resources: ResourcesSettings


TComponentSettings = TypeVar("TComponentSettings", bound=BaseModel)


def _deep_merge_mappings(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    """Recursively merge mapping values, replacing non-mapping leaves."""
    merged = dict(base)
    for key, override_value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            merged[key] = _deep_merge_mappings(base_value, override_value)
        else:
            merged[key] = override_value
    return merged


def _field_default_value(
    model: type[BaseModel],
    *,
    field_name: str,
) -> Any:
    """Return one field default when it can be materialized safely."""
    field = model.model_fields.get(field_name)
    if field is None:
        return PydanticUndefined
    if field.default is not PydanticUndefined:
        return field.default
    if field.default_factory is None:
        return PydanticUndefined
    try:
        return field.get_default(call_default_factory=True, validated_data={})
    except Exception:  # noqa: BLE001
        return PydanticUndefined


def resolve_component_settings(
    *,
    settings: CoreRuntimeSettings,
    component_id: str,
    model: type[TComponentSettings],
) -> TComponentSettings:
    """Resolve one component settings object from the appropriate namespace.

    - ``service_*``   → settings.core.service
    - ``substrate_*`` → settings.resources.substrate
    - ``adapter_*``   → settings.resources.adapter
    """
    kind, separator, name = component_id.partition("_")
    if not separator or kind not in {"service", "substrate", "adapter"}:
        raise ValueError(
            f"component_id '{component_id}' must be prefixed with "
            "service_, substrate_, or adapter_"
        )

    if kind == "service":
        namespace = settings.core.service.model_dump(mode="python")
        namespace_path = "service"
    elif kind == "substrate":
        namespace = settings.resources.substrate.model_dump(mode="python")
        namespace_path = "substrate"
    else:
        namespace = settings.resources.adapter.model_dump(mode="python")
        namespace_path = "adapter"

    resolved = namespace.get(name, {})
    if not isinstance(resolved, dict):
        raise TypeError(f"{namespace_path}.{name} must resolve to an object mapping")
    merged = dict(resolved)
    for key, override_value in resolved.items():
        if not isinstance(override_value, dict):
            continue
        default_value = _field_default_value(model, field_name=key)
        if isinstance(default_value, BaseModel):
            default_value = default_value.model_dump(mode="python")
        if not isinstance(default_value, dict):
            continue
        merged[key] = _deep_merge_mappings(default_value, override_value)
    return model.model_validate(merged)
