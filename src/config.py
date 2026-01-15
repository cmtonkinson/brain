"""Configuration management for Brain assistant."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator
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
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return data


def _yaml_settings_source(paths: list[Path]):
    def source() -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for path in paths:
            merged.update(_load_yaml(path))
        return _apply_legacy_llm_config(merged)

    return source


def _set_nested_value(target: dict[str, Any], path: str, value: Any) -> None:
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
    if kind == "int":
        return int(raw)
    if kind == "bool":
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if kind == "json":
        return json.loads(raw)
    return raw


def _env_settings_source():
    mapping = {
        "ANTHROPIC_API_KEY": ("anthropic_api_key", "str"),
        "OBSIDIAN_API_KEY": ("obsidian.api_key", "str"),
        "OBSIDIAN_URL": ("obsidian.url", "str"),
        "OBSIDIAN_VAULT_PATH": ("obsidian.vault_path", "str"),
        "DATABASE_URL": ("database.url", "str"),
        "POSTGRES_PASSWORD": ("database.postgres_password", "str"),
        "QDRANT_URL": ("qdrant.url", "str"),
        "REDIS_URL": ("redis.url", "str"),
        "SIGNAL_API_URL": ("signal.url", "str"),
        "SIGNAL_PHONE_NUMBER": ("signal.phone_number", "str"),
        "ALLOWED_SENDERS": ("signal.allowed_senders", "json"),
        "ALLOWED_SENDERS_BY_CHANNEL": ("signal.allowed_senders_by_channel", "json"),
        "LETTA_BASE_URL": ("letta.base_url", "str"),
        "LETTA_API_KEY": ("letta.api_key", "str"),
        "LETTA_SERVER_PASSWORD": ("letta.server_password", "str"),
        "LETTA_AGENT_NAME": ("letta.agent_name", "str"),
        "LETTA_MODEL": ("letta.model", "str"),
        "LETTA_EMBED_MODEL": ("letta.embed_model", "str"),
        "LETTA_BOOTSTRAP_ON_START": ("letta.bootstrap_on_start", "bool"),
        "LLM_MODEL": ("llm.model", "str"),
        "LLM_BASE_URL": ("llm.base_url", "str"),
        "LLM_TIMEOUT": ("llm.timeout", "int"),
        "LLM_EMBED_MODEL": ("llm.embed_model", "str"),
        "LLM_EMBED_BASE_URL": ("llm.embed_base_url", "str"),
        "LITELLM_MODEL": ("llm.model", "str"),
        "LITELLM_BASE_URL": ("llm.base_url", "str"),
        "LITELLM_TIMEOUT": ("llm.timeout", "int"),
        "OLLAMA_URL": ("llm.embed_base_url", "str"),
        "OLLAMA_EMBED_MODEL": ("llm.embed_model", "str"),
        "USER": ("user.name", "str"),
        "HOME_DIR": ("user.home_dir", "str"),
        "CONVERSATION_FOLDER": ("conversation.folder", "str"),
        "CONVERSATION_DEFAULT_CHANNEL": ("conversation.default_channel", "str"),
        "SUMMARY_EVERY_TURNS": ("conversation.summary_every_turns", "int"),
        "UTCP_CONFIG_PATH": ("utcp.config_path", "str"),
        "CODE_MODE_TIMEOUT": ("utcp.code_mode_timeout", "int"),
        "INDEXER_INTERVAL_SECONDS": ("indexer.interval_seconds", "int"),
        "INDEXER_CHUNK_TOKENS": ("indexer.chunk_tokens", "int"),
        "INDEXER_COLLECTION": ("indexer.collection", "str"),
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
    api_key: str
    url: str = "http://host.docker.internal:27123"
    vault_path: str


class DatabaseConfig(BaseModel):
    url: str | None = None
    postgres_password: str | None = None

    @model_validator(mode="after")
    def populate_database_url(self) -> "DatabaseConfig":
        if self.url:
            return self
        if not self.postgres_password:
            return self
        self.url = f"postgresql://brain:{self.postgres_password}@postgres:5432/brain"
        return self


class LlmConfig(BaseModel):
    model: str = "anthropic:claude-sonnet-4-20250514"
    base_url: str | None = None
    timeout: int = 600
    embed_model: str = "mxbai-embed-large"
    embed_base_url: str = "http://host.docker.internal:11434"

    @model_validator(mode="after")
    def populate_embed_base_url(self) -> "LlmConfig":
        if not self.embed_base_url and self.base_url:
            self.embed_base_url = self.base_url
        return self


class SignalConfig(BaseModel):
    phone_number: str | None = None
    url: str = "http://signal-api:8080"
    allowed_senders: list[str] = []
    allowed_senders_by_channel: dict[str, list[str]] = Field(default_factory=dict)


class LettaConfig(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    server_password: str | None = None
    agent_name: str = "brain"
    model: str = "ollama/llama3.1:8b"
    embed_model: str = "ollama/mxbai-embed-large:latest"
    bootstrap_on_start: bool = False

    @model_validator(mode="after")
    def populate_letta_api_key(self) -> "LettaConfig":
        if self.api_key:
            return self
        if self.server_password:
            self.api_key = self.server_password
        return self


class ConversationConfig(BaseModel):
    folder: str = "Brain/Conversations"
    default_channel: str = "signal"
    summary_every_turns: int = 7


class UtcpConfig(BaseModel):
    config_path: str = "~/.config/brain/utcp.json"
    code_mode_timeout: int = 30


class IndexerConfig(BaseModel):
    interval_seconds: int = 0
    chunk_tokens: int = 1000
    collection: str = "obsidian"


class ServiceConfig(BaseModel):
    url: str


class UserConfig(BaseModel):
    name: str = "user"
    home_dir: str = str(Path.home())
    test_calendar_name: str | None = None
    test_reminder_list_name: str | None = None


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
        return (
            init_settings,
            _env_settings_source(),
            _yaml_settings_source(_USER_SECRETS_PATHS),
            _yaml_settings_source(_USER_CONFIG_PATHS),
            _yaml_settings_source([_DEFAULT_CONFIG_PATH]),
        )

    # LLM Configuration
    anthropic_api_key: str | None = None

    # Obsidian Configuration
    obsidian: ObsidianConfig

    # Database Configuration
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)

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

    @model_validator(mode="after")
    def validate_sender_allowlist(self) -> "Settings":
        if self.signal.allowed_senders_by_channel:
            return self
        if self.signal.allowed_senders:
            return self
        raise ValueError(
            "signal.allowed_senders or signal.allowed_senders_by_channel must be configured."
        )

    @model_validator(mode="after")
    def validate_home_dir(self) -> "Settings":
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
