"""Configuration management for Brain assistant."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "brain.yml"
_USER_CONFIG_PATHS = [
    Path("~/.config/brain/brain.yml").expanduser(),
    Path("/config/brain.yml"),
]
_USER_SECRETS_PATHS = [
    Path("~/.config/brain/secrets.yml").expanduser(),
    Path("/config/secrets.yml"),
]


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from disk, returning an empty mapping if missing."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return data


def _yaml_settings_source(paths: list[Path]):
    """Create a Pydantic settings source for a list of YAML paths."""

    def source() -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for path in paths:
            merged.update(_load_yaml(path))
        return _apply_legacy_llm_config(merged)

    return source


def _set_nested_value(target: dict[str, Any], path: str, value: Any) -> None:
    """Set a dotted-path value on a nested mapping, creating containers."""
    parts = path.split(".")
    cursor = target
    for key in parts[:-1]:
        node = cursor.get(key)
        if not isinstance(node, dict):
            node = {}
            cursor[key] = node
        cursor = node
    cursor[parts[-1]] = value


def _parse_env_value(raw: str, kind: str) -> Any:
    """Parse an environment value into the requested primitive type."""
    if kind == "int":
        return int(raw)
    if kind == "bool":
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if kind == "json":
        return json.loads(raw)
    return raw


def _env_settings_source():
    """Create a settings source that maps environment variables to config keys."""
    mapping = {
        "ANTHROPIC_API_KEY": ("anthropic_api_key", "str"),
        "OBSIDIAN_API_KEY": ("obsidian.api_key", "str"),
        "OBSIDIAN_VAULT_PATH": ("obsidian.vault_path", "str"),
        "DATABASE_URL": ("database.url", "str"),
        "POSTGRES_PASSWORD": ("database.postgres_password", "str"),
        "QDRANT_URL": ("qdrant.url", "str"),
        "SIGNAL_PHONE_NUMBER": ("signal.phone_number", "str"),
        "ALLOWED_SENDERS": ("signal.allowed_senders", "json"),
        "ALLOWED_SENDERS_BY_CHANNEL": ("signal.allowed_senders_by_channel", "json"),
        "LETTA_BASE_URL": ("letta.base_url", "str"),
        "LETTA_API_KEY": ("letta.api_key", "str"),
        "LETTA_SERVER_PASSWORD": ("letta.server_password", "str"),
        "LETTA_AGENT_NAME": ("letta.agent_name", "str"),
        "LETTA_MODEL": ("letta.model", "str"),
        "LETTA_EMBED_MODEL": ("letta.embed_model", "str"),
        "LLM_BASE_URL": ("llm.base_url", "str"),
        "LLM_TIMEOUT": ("llm.timeout", "int"),
        "LLM_EMBED_BASE_URL": ("llm.embed_base_url", "str"),
        "LITELLM_MODEL": ("llm.model", "str"),
        "OLLAMA_URL": ("llm.embed_base_url", "str"),
        "OLLAMA_EMBED_MODEL": ("llm.embed_model", "str"),
        "USER_TIMEZONE": ("user.timezone", "str"),
        "UTCP_CONFIG_PATH": ("utcp.config_path", "str"),
    }

    def source() -> dict[str, Any]:
        data: dict[str, Any] = {}
        for env_key, (path, kind) in mapping.items():
            raw = os.environ.get(env_key)
            if raw is None:
                continue
            _set_nested_value(data, path, _parse_env_value(raw, kind))
        return data

    return source


def _apply_legacy_llm_config(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy LLM keys into the canonical llm section."""
    llm = data.get("llm")
    if not isinstance(llm, dict):
        llm = {}

    legacy_litellm = data.get("litellm")
    if isinstance(legacy_litellm, dict):
        if legacy_litellm.get("model") is not None:
            llm.setdefault("model", legacy_litellm.get("model"))
        if legacy_litellm.get("base_url") is not None:
            llm.setdefault("base_url", legacy_litellm.get("base_url"))
        if legacy_litellm.get("timeout") is not None:
            llm.setdefault("timeout", legacy_litellm.get("timeout"))

    legacy_ollama = data.get("ollama")
    if isinstance(legacy_ollama, dict):
        if legacy_ollama.get("url") is not None:
            llm.setdefault("embed_base_url", legacy_ollama.get("url"))
        if legacy_ollama.get("embed_model") is not None:
            llm.setdefault("embed_model", legacy_ollama.get("embed_model"))

    if llm:
        data["llm"] = llm
    return data


class ObsidianConfig(BaseModel):
    """Obsidian REST API configuration."""

    api_key: str
    url: str = "http://host.docker.internal:27123"
    vault_path: str
    root_folder: str | None = None
    conversation_folder: str | None = None
    summary_folder: str | None = None


class DatabaseConfig(BaseModel):
    """Database connection configuration."""

    url: str | None = None
    postgres_password: str | None = None

    @model_validator(mode="after")
    def populate_database_url(self) -> "DatabaseConfig":
        """Populate the database URL from the Postgres password when missing."""
        if self.url:
            return self
        if not self.postgres_password:
            return self
        self.url = f"postgresql://brain:{self.postgres_password}@postgres:5432/brain"
        return self


class ObjectStoreConfig(BaseModel):
    """Object store filesystem configuration."""

    root_dir: str = "data/objects"


class LlmConfig(BaseModel):
    """Language model routing and embedding settings."""

    model: str = "anthropic:claude-sonnet-4-20250514"
    base_url: str | None = None
    timeout: int = 600
    embed_model: str = "mxbai-embed-large"
    embed_base_url: str = "http://host.docker.internal:11434"

    @model_validator(mode="after")
    def populate_embed_base_url(self) -> "LlmConfig":
        """Use the LLM base URL for embeddings when no embed URL is set."""
        if not self.embed_base_url and self.base_url:
            self.embed_base_url = self.base_url
        return self


class SignalConfig(BaseModel):
    """Signal API connection and allowlist settings."""

    phone_number: str | None = None
    url: str = "http://signal-api:8080"
    allowed_senders: list[str] = []
    allowed_senders_by_channel: dict[str, list[str]] = Field(default_factory=dict)


class LettaConfig(BaseModel):
    """Letta service configuration."""

    base_url: str | None = None
    api_key: str | None = None
    server_password: str | None = None
    agent_name: str = "brain"
    model: str = "ollama/llama3.1:8b"
    embed_model: str = "ollama/mxbai-embed-large:latest"
    bootstrap_on_start: bool = False

    @model_validator(mode="after")
    def populate_letta_api_key(self) -> "LettaConfig":
        """Default the API key to the server password when provided."""
        if self.api_key:
            return self
        if self.server_password:
            self.api_key = self.server_password
        return self


class ConversationConfig(BaseModel):
    """Conversation note storage defaults."""

    default_channel: str = "signal"
    summary_every_turns: int = 7


class UtcpConfig(BaseModel):
    """UTCP Code-Mode configuration."""

    config_path: str = "~/.config/brain/utcp.json"
    code_mode_timeout: int = 30


class IndexerConfig(BaseModel):
    """Indexer scheduling and chunking settings."""

    interval_seconds: int = 0
    chunk_tokens: int = 1000
    collection: str = "obsidian"


class SchedulerConfig(BaseModel):
    """Scheduler retry/backoff configuration defaults."""

    default_max_attempts: int = 3
    default_backoff_strategy: str = "exponential"
    backoff_base_seconds: int = 60
    failure_notification_threshold: int = 3
    failure_notification_throttle_seconds: int = 3600

    @field_validator("default_max_attempts")
    @classmethod
    def validate_max_attempts(cls, value: int) -> int:
        """Ensure max attempts is positive."""
        if value < 1:
            raise ValueError("scheduler.default_max_attempts must be >= 1.")
        return value

    @field_validator("default_backoff_strategy")
    @classmethod
    def validate_backoff_strategy(cls, value: str) -> str:
        """Ensure backoff strategy is supported."""
        normalized = value.strip().lower()
        if normalized not in {"fixed", "exponential", "none"}:
            raise ValueError(
                "scheduler.default_backoff_strategy must be fixed, exponential, or none."
            )
        return normalized

    @field_validator("backoff_base_seconds")
    @classmethod
    def validate_backoff_seconds(cls, value: int) -> int:
        """Ensure backoff base seconds is non-negative."""
        if value < 0:
            raise ValueError("scheduler.backoff_base_seconds must be >= 0.")
        return value

    @field_validator("failure_notification_threshold")
    @classmethod
    def validate_failure_notification_threshold(cls, value: int) -> int:
        """Ensure failure notification threshold is positive."""
        if value < 1:
            raise ValueError("scheduler.failure_notification_threshold must be >= 1.")
        return value

    @field_validator("failure_notification_throttle_seconds")
    @classmethod
    def validate_failure_notification_throttle_seconds(cls, value: int) -> int:
        """Ensure failure notification throttle window is non-negative."""
        if value < 0:
            raise ValueError("scheduler.failure_notification_throttle_seconds must be >= 0.")
        return value


class AnchoringConfig(BaseModel):
    """Anchoring configuration for Stage 4 Obsidian notes."""

    attachments_dir: str = "_attachments/"
    visual_allowlist: list[str] = Field(default_factory=lambda: ["jpg", "jpeg", "png", "gif"])


class CommitmentConfig(BaseModel):
    """Commitment tracking configuration defaults."""

    autonomous_transition_confidence_threshold: float = 0.8
    autonomous_creation_confidence_threshold: float = 0.9
    dedupe_confidence_threshold: float = 0.8
    dedupe_summary_length: int = 20
    audit_retention_days: int = 0
    review_day: str = "Saturday"
    review_time: str = "10:00"
    batch_reminder_time: str = "06:00"
    review_engagement_window_minutes: int = 60

    @field_validator("autonomous_transition_confidence_threshold")
    @classmethod
    def validate_autonomous_transition_threshold(cls, value: float) -> float:
        """Ensure autonomous transition threshold is between 0 and 1."""
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                "commitments.autonomous_transition_confidence_threshold must be between 0 and 1."
            )
        return value

    @field_validator("autonomous_creation_confidence_threshold")
    @classmethod
    def validate_autonomous_creation_threshold(cls, value: float) -> float:
        """Ensure autonomous creation threshold is between 0 and 1."""
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                "commitments.autonomous_creation_confidence_threshold must be between 0 and 1."
            )
        return value

    @field_validator("dedupe_confidence_threshold")
    @classmethod
    def validate_dedupe_confidence_threshold(cls, value: float) -> float:
        """Ensure dedupe confidence threshold is between 0 and 1."""
        if not 0.0 <= value <= 1.0:
            raise ValueError("commitments.dedupe_confidence_threshold must be between 0 and 1.")
        return value

    @field_validator("dedupe_summary_length")
    @classmethod
    def validate_dedupe_summary_length(cls, value: int) -> int:
        """Ensure dedupe summary length is a positive integer."""
        if value < 1:
            raise ValueError("commitments.dedupe_summary_length must be >= 1.")
        return value

    @field_validator("audit_retention_days")
    @classmethod
    def validate_audit_retention_days(cls, value: int) -> int:
        """Ensure audit retention days is non-negative."""
        if value < 0:
            raise ValueError("commitments.audit_retention_days must be >= 0.")
        return value

    @field_validator("review_day")
    @classmethod
    def validate_review_day(cls, value: str) -> str:
        """Ensure review_day is a supported weekday name."""
        normalized = value.strip().lower()
        if normalized not in {
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        }:
            raise ValueError("commitments.review_day must be a weekday name.")
        return value.strip()

    @field_validator("review_time")
    @classmethod
    def validate_review_time(cls, value: str) -> str:
        """Ensure review_time uses HH:MM 24-hour format."""
        try:
            datetime.strptime(value.strip(), "%H:%M")
        except ValueError as exc:
            raise ValueError("commitments.review_time must be HH:MM.") from exc
        return value.strip()

    @field_validator("batch_reminder_time")
    @classmethod
    def validate_batch_reminder_time(cls, value: str) -> str:
        """Ensure batch_reminder_time uses HH:MM 24-hour format."""
        try:
            datetime.strptime(value.strip(), "%H:%M")
        except ValueError as exc:
            raise ValueError("commitments.batch_reminder_time must be HH:MM.") from exc
        return value.strip()

    @field_validator("review_engagement_window_minutes")
    @classmethod
    def validate_review_engagement_window_minutes(cls, value: int) -> int:
        """Ensure engagement window is positive."""
        if value < 1:
            raise ValueError("commitments.review_engagement_window_minutes must be >= 1.")
        return value


class ServiceConfig(BaseModel):
    """Generic service URL wrapper."""

    url: str


class UserConfig(BaseModel):
    """User identity and local directory configuration."""

    name: str = "user"
    home_dir: str = str(Path.home())
    timezone: str = "America/New_York"
    test_calendar_name: str | None = None
    test_reminder_list_name: str | None = None

    @model_validator(mode="after")
    def validate_timezone(self) -> "UserConfig":
        """Ensure the configured timezone is valid."""
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Invalid timezone: {self.timezone}") from exc
        return self


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Layer settings sources in descending order of precedence."""
        return (
            init_settings,
            _env_settings_source(),
            _yaml_settings_source(_USER_SECRETS_PATHS),
            _yaml_settings_source(_USER_CONFIG_PATHS),
            _yaml_settings_source([_DEFAULT_CONFIG_PATH]),
        )

    # Logging
    log_level: str = "INFO"
    log_level_otel: str = "INFO"

    # LLM Configuration
    anthropic_api_key: str | None = None

    # Obsidian Configuration
    obsidian: ObsidianConfig

    # Database Configuration
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)

    # Object Storage
    objects: ObjectStoreConfig = Field(default_factory=ObjectStoreConfig)
    anchoring: AnchoringConfig = Field(default_factory=AnchoringConfig)

    # Service URLs
    qdrant: ServiceConfig = Field(default_factory=lambda: ServiceConfig(url="http://qdrant:6333"))
    redis: ServiceConfig = Field(default_factory=lambda: ServiceConfig(url="redis://redis:6379"))

    # Signal
    signal: SignalConfig = Field(default_factory=SignalConfig)

    # Letta
    letta: LettaConfig = Field(default_factory=LettaConfig)

    # User Context
    user: UserConfig = Field(default_factory=UserConfig)

    # LLM
    llm: LlmConfig = Field(default_factory=LlmConfig)

    # Conversation Storage
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)

    # Code-Mode / UTCP
    utcp: UtcpConfig = Field(default_factory=UtcpConfig)

    # Indexer Configuration
    indexer: IndexerConfig = Field(default_factory=IndexerConfig)

    # Scheduler Configuration
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)

    # Commitment Tracking Configuration
    commitments: CommitmentConfig = Field(default_factory=CommitmentConfig)

    @model_validator(mode="after")
    def validate_sender_allowlist(self) -> "Settings":
        """Ensure a Signal allowlist is configured before startup."""
        if self.signal.allowed_senders_by_channel:
            return self
        if self.signal.allowed_senders:
            return self
        raise ValueError(
            "signal.allowed_senders or signal.allowed_senders_by_channel must be configured."
        )

    @model_validator(mode="after")
    def validate_home_dir(self) -> "Settings":
        """Validate that user.home_dir is within filesystem MCP roots."""
        config_path = Path(os.path.expanduser(self.utcp.config_path))
        if not config_path.exists():
            return self
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return self
        templates = raw.get("manual_call_templates", [])
        roots: list[Path] = []
        for template in templates:
            servers = template.get("config", {}).get("mcpServers", {})
            filesystem = servers.get("filesystem")
            if not filesystem:
                continue
            args = filesystem.get("args", []) or []
            for idx, arg in enumerate(args):
                if isinstance(arg, str) and "server-filesystem" in arg:
                    for path in args[idx + 1 :]:
                        if isinstance(path, str) and path.startswith("/"):
                            roots.append(Path(path))
                    break
            else:
                for path in args:
                    if isinstance(path, str) and path.startswith("/"):
                        roots.append(Path(path))
        if not roots:
            return self
        home_dir = self.user.home_dir
        if not home_dir:
            raise ValueError("user.home_dir must be configured when filesystem MCP is enabled.")
        home_path = Path(os.path.expanduser(home_dir)).resolve()
        for root in roots:
            root_path = Path(os.path.expanduser(str(root))).resolve()
            if home_path == root_path:
                return self
            try:
                home_path.relative_to(root_path)
                return self
            except ValueError:
                continue
        roots_display = ", ".join(str(path) for path in roots)
        raise ValueError(
            "user.home_dir must match a filesystem MCP allowed directory. "
            f"Configured roots: {roots_display}"
        )


# Global settings instance
settings = Settings()
