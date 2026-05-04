"""Typed configuration models for Brain runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.fields import PydanticUndefined

DEFAULT_CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", "").strip() or (Path.home() / ".config"))
    / "brain"
)
DEFAULT_DASHBOARD_CONFIG_PATH = DEFAULT_CONFIG_DIR / "dashboard.yaml"
SECRETS_CONFIG_PREFIX = "secrets"
SECRETS_CONFIG_FILENAME = "secrets.yaml"


class LoggingSettings(BaseModel):
    """Structured logging configuration shared by Brain components.

    ``process_name`` defaults to ``None`` so each binary supplies its own
    identifier (e.g. ``"core"``, ``"assistant"``, ``"worker"``). Operators can
    still override it by setting ``logging.process_name`` in YAML.
    """

    level: Literal["VERBOSE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    file_capture_enabled: bool = False
    file_capture_level: Literal[
        "VERBOSE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    ] = "VERBOSE"
    file_capture_directory: str = "logs"
    json_output: bool = True
    process_name: str | None = None
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


class PublicApiObservabilitySettings(BaseModel):
    """Public API observability subtree."""

    otel: PublicApiOtelSettings = Field(default_factory=PublicApiOtelSettings)


class OtlpObservabilitySettings(BaseModel):
    """OTLP exporter settings for process-level telemetry."""

    endpoint: str = "http://otel-collector:4318"
    headers: dict[str, str] = Field(default_factory=dict)


class TraceObservabilitySettings(BaseModel):
    """Trace export settings."""

    enabled: bool = True
    sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)


class MetricObservabilitySettings(BaseModel):
    """Metric export settings."""

    enabled: bool = True


class LlmObservabilitySettings(BaseModel):
    """LLM observability settings."""

    enabled: bool = True
    backend: Literal["langfuse"] = "langfuse"
    capture_content: bool = True


class ObservabilitySettings(BaseModel):
    """Global observability configuration."""

    enabled: bool = False
    otlp: OtlpObservabilitySettings = Field(default_factory=OtlpObservabilitySettings)
    traces: TraceObservabilitySettings = Field(
        default_factory=TraceObservabilitySettings
    )
    metrics: MetricObservabilitySettings = Field(
        default_factory=MetricObservabilitySettings
    )
    llm: LlmObservabilitySettings = Field(default_factory=LlmObservabilitySettings)
    public_api: PublicApiObservabilitySettings = Field(
        default_factory=PublicApiObservabilitySettings
    )


class OperatorProfileSettings(BaseModel):
    """Operator identity profile settings shared across action services."""

    signal_contact_e164: str = "+12222222222"


class ApprovalResponseSettings(BaseModel):
    """Operator approval-response vocabulary shared across action services."""

    approve_reaction_emojis: tuple[str, ...] = ("👍", "✅")
    reject_reaction_emojis: tuple[str, ...] = ("👎", "❌")
    approve_text_responses: tuple[str, ...] = ("approve", "approved", "yes")
    reject_text_responses: tuple[str, ...] = ("deny", "denied", "no")


class ProfileSettings(BaseModel):
    """Root profile settings shared across services for operator identity."""

    operator: OperatorProfileSettings = Field(default_factory=OperatorProfileSettings)
    approval_responses: ApprovalResponseSettings = Field(
        default_factory=ApprovalResponseSettings
    )
    default_dial_code: str = "+1"
    operator_name: str = "Operator"
    brain_name: str = "Brain"
    brain_verbosity: str = "normal"
    preferred_timezone: str = "UTC"

    @field_validator("preferred_timezone")
    @classmethod
    def _validate_preferred_timezone(cls, value: str) -> str:
        """Validate the operator's preferred IANA timezone."""
        normalized = value.strip()
        if normalized == "":
            raise ValueError("preferred_timezone is required")
        try:
            ZoneInfo(normalized)
        except Exception as exc:
            raise ValueError(f"invalid preferred_timezone: {normalized}") from exc
        return normalized


class CoreBootSettings(BaseModel):
    """Core boot framework settings under ``core.boot``."""

    run_migrations_on_startup: bool = True
    assert_upgrades_clean: bool = True
    readiness_poll_interval_seconds: float = Field(default=0.25, gt=0)
    readiness_timeout_seconds: float = Field(default=30.0, gt=0)
    boot_retry_attempts: int = Field(default=3, gt=0)
    boot_retry_delay_seconds: float = Field(default=0.5, ge=0)
    boot_timeout_seconds: float = Field(default=30.0, gt=0)


class CoreHttpSettings(BaseModel):
    """Core HTTP runtime settings under ``core.http``."""

    host: str = "0.0.0.0"
    port: int = Field(default=8898, ge=1, le=65535)


class CoreHealthSettings(BaseModel):
    """Core aggregate health policy under ``core.health``."""

    max_timeout_seconds: float = Field(default=1.0, gt=0)


class CoreComponentSettings(BaseModel):
    """Shared ``core`` namespace used by both Core and Actor runtime settings."""

    host: str = "127.0.0.1"
    port: int = Field(default=8898, ge=1, le=65535)
    timeout_seconds: float = Field(default=30.0, gt=0)
    boot: CoreBootSettings = Field(default_factory=CoreBootSettings)
    http: CoreHttpSettings = Field(default_factory=CoreHttpSettings)
    health: CoreHealthSettings = Field(default_factory=CoreHealthSettings)


ActorCoreConnectionSettings = CoreComponentSettings


class ComponentNamespaceSettings(BaseModel):
    """Opaque namespace map for component-local settings."""

    model_config = ConfigDict(extra="allow")


class ActorNamespaceSettings(BaseModel):
    """Per-actor identity settings."""

    model_config = ConfigDict(extra="allow")

    principal: str = "operator"
    source: str = "actor"


class CliActorSettings(ActorNamespaceSettings):
    """CLI actor identity settings."""

    source: str = "cli"


class LocalDateTimeBoundaryResolverSettings(BaseModel):
    """Dynamic local datetime resolver for environment-context input values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resolve: Literal["local_datetime_boundary"]
    boundary: Literal["start_of_day", "end_of_day"]
    day_offset: int = 0
    format: Literal["iso8601"] = "iso8601"


def _validate_environment_context_value(value: Any) -> Any:
    """Recursively validate one environment-context payload value."""
    if isinstance(value, dict):
        if "resolve" in value:
            return LocalDateTimeBoundaryResolverSettings.model_validate(
                value
            ).model_dump(mode="python")
        return {
            str(key): _validate_environment_context_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_validate_environment_context_value(item) for item in value]
    return value


class AgentEnvironmentContextEntrySettings(BaseModel):
    """One op-backed assistant environment-context entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op_id: str = Field(
        min_length=1,
        pattern=r"^[a-z0-9]+(?:-{1,2}[a-z0-9]+)*$",
    )
    input_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_payload")
    @classmethod
    def _validate_input_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Validate recursive resolver specs inside one input payload."""
        return {
            str(key): _validate_environment_context_value(item)
            for key, item in value.items()
        }


class AssistantActorSettings(ActorNamespaceSettings):
    """Assistant-specific settings for prompt rendering and runtime identity."""

    source: str = "assistant"
    session_start_mode: Literal["new", "existing"] = "existing"
    personality: str = "default"
    operator_profile: str = "Refer to me as 'boss'"
    system_prompt_append: str = ""
    op_discovery_deny_list: tuple[str, ...] = ("relay-notify",)
    environment_context: tuple[AgentEnvironmentContextEntrySettings, ...] = (
        AgentEnvironmentContextEntrySettings(op_id="current-datetime"),
    )
    tool_return_max_chars: int = 8000
    tool_return_compress_threshold: int = 4000
    tool_loop_tier2_hop_threshold: int = Field(default=3, ge=1)
    surface_intermediate_text: bool = False


class WorkerActorSettings(ActorNamespaceSettings):
    """Worker Actor runtime settings."""

    source: str = "worker"
    channel: str = "worker"
    max_workers: int = Field(default=4, ge=1, le=32)
    poll_interval_seconds: float = Field(default=2.0, gt=0)


class SubagentActorSettings(ActorNamespaceSettings):
    """Subagent Actor runtime settings."""

    source: str = "subagent"
    principal: str = "subagent"
    max_workers: int = Field(default=1, ge=1, le=16)
    poll_interval_seconds: float = Field(default=2.0, gt=0)
    default_personality: str = "subagent"
    default_max_turns: int = Field(default=8, ge=1, le=64)
    default_budget_tokens: int = Field(default=200_000, ge=1_000)


class ConsoleActorSettings(ActorNamespaceSettings):
    """Console TUI actor runtime settings."""

    source: str = "console"
    poll_timeout_seconds: float = Field(default=30.0, gt=0)
    poll_error_backoff_seconds: float = Field(default=1.0, gt=0)
    input_max_lines: int = Field(default=10, gt=0)
    input_history_size: int = Field(default=1000, gt=0)
    editor: str = "vim"


class CoreSettings(BaseModel):
    """Core-service runtime settings derived from the merged config tree."""

    model_config = ConfigDict(extra="ignore")

    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    profile: ProfileSettings = Field(default_factory=ProfileSettings)
    core: CoreComponentSettings = Field(default_factory=CoreComponentSettings)
    _config_path: ClassVar[Path] = DEFAULT_CONFIG_DIR

    @property
    def boot(self) -> CoreBootSettings:
        """Expose `core.boot` at the historical call site used by Core startup."""
        return self.core.boot

    @property
    def http(self) -> CoreHttpSettings:
        """Expose `core.http` at the historical call site used by Core runtime."""
        return self.core.http

    @property
    def health(self) -> CoreHealthSettings:
        """Expose `core.health` at the historical call site used by Core health."""
        return self.core.health


class ResourcesSettings(BaseModel):
    """Resource-component settings derived from the merged config tree."""

    model_config = ConfigDict(extra="ignore")
    _config_path: ClassVar[Path] = DEFAULT_CONFIG_DIR


class ActorSettings(BaseModel):
    """Actor runtime settings derived from the merged config tree."""

    model_config = ConfigDict(extra="ignore")

    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    core: CoreComponentSettings = Field(default_factory=CoreComponentSettings)
    cli: CliActorSettings = Field(default_factory=CliActorSettings)
    assistant: AssistantActorSettings = Field(default_factory=AssistantActorSettings)
    console: ConsoleActorSettings = Field(default_factory=ConsoleActorSettings)
    worker: WorkerActorSettings = Field(default_factory=WorkerActorSettings)
    subagent: SubagentActorSettings = Field(default_factory=SubagentActorSettings)
    _config_path: ClassVar[Path] = DEFAULT_CONFIG_DIR

    @property
    def agent(self) -> AssistantActorSettings:
        """Compatibility-free internal accessor during the assistant actor rename."""
        return self.assistant


@dataclass(frozen=True, slots=True)
class CoreRuntimeSettings:
    """Combined runtime settings passed to components and boot hooks."""

    core: CoreSettings
    resources: ResourcesSettings
    component_settings: dict[str, dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        """Default component-settings map for direct constructor call sites."""
        if self.component_settings is None:
            object.__setattr__(self, "component_settings", {})


TComponentSettings = TypeVar("TComponentSettings", bound=BaseModel)
AgentActorSettings = AssistantActorSettings


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


def component_settings_for(
    settings: CoreRuntimeSettings,
    *,
    component_name: str,
) -> dict[str, Any]:
    """Return one direct component-root mapping from the merged runtime config."""
    resolved = settings.component_settings.get(component_name, {})
    if not isinstance(resolved, dict):
        raise TypeError(f"{component_name} must resolve to an object mapping")
    return resolved


def resolve_component_settings(
    *,
    settings: CoreRuntimeSettings,
    component_id: str,
    model: type[TComponentSettings],
) -> TComponentSettings:
    """Resolve one component settings object from the merged component-root tree."""
    _kind, separator, name = component_id.partition("_")
    if not separator:
        raise ValueError(
            f"component_id '{component_id}' must contain an underscore-delimited name"
        )

    resolved = component_settings_for(settings, component_name=name)
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
